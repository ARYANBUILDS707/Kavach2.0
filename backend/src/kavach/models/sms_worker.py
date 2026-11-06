"""Supervisor for the isolated SMS inference worker (docs/M4_SMS_INFERENCE_ARCHITECTURE.md).

Standard library and pydantic only; torch lives in the worker's separate environment.

**Process and protocol.**
- One worker child process, reached through anonymous stdin/stdout pipes. There is no socket and
  no network service.
- Frames and responses follow §5 of the design.

**Admission (TD-18).**
- `max_inflight` slots (default 2), taken without blocking. With no free slot the request is
  rejected (`inference_saturated`).
- Slot holders take turns on the single worker: one executes and the other waits, bounded by its
  own deadline budget.

**Timeouts.**
- Per-request budget: `min(inference_timeout, deadline - commit_reserve - now)`.
- On expiry the worker's process group is killed with SIGKILL, the result is
  `inference_timeout`, and the worker restarts.
- Startup has its own timeout.

**Recovery.**
- A crash, timeout or invalid output counts as a failure.
- Restarts back off 1, 2, 4, ... 60 s.
- 3 failures within 10 minutes open a 10-minute circuit, after which one probe start runs.
- A startup verification failure (`fatal` frame) is terminal: `unverified`.

**One model copy.** An exclusive `flock` is held for the supervisor's lifetime, so a second
supervisor, in this or another process, reports `lock_held` and never spawns.

**Privacy.**
- Text travels only inside a `classify` frame on the worker's stdin.
- Request IDs are random per call.
- The worker gets an allowlisted environment with no secrets.
- Its stderr is drained and discarded, never logged.
- Errors and results carry fixed codes and numbers only.
- None of this erases memory (TD-26).

**This module is not connected to ingestion (M4-I.1).**
"""

import contextlib
import fcntl
import math
import os
import queue
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal

from kavach.core.telemetry import operational_event
from kavach.models.manifest import LoadedManifest
from kavach.models.protocol import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    encode_frame,
    read_frame,
)

State = Literal[
    "disabled",
    "unverified",
    "starting",
    "ready",
    "restarting",
    "circuit_open",
    "lock_held",
    "closed",
]
Outcome = Literal["complete", "rejected", "unavailable"]

# Rejected: nothing should be stored; the caller answers 429/503 and a same-ID retry is analyzed.
REJECTED_REASONS = ("inference_saturated", "worker_starting", "worker_restarting", "worker_busy")
# Unavailable: inference was not possible or failed; stored as an explicit unavailable stage.
UNAVAILABLE_REASONS = (
    "model_not_deployed",
    "model_unverified",
    "worker_unavailable",
    "inference_timeout",
    "worker_crashed",
    "invalid_model_output",
    "deadline_exhausted",
)
TERMINAL_STATE_REASON: dict[str, str] = {
    "disabled": "model_not_deployed",
    "unverified": "model_unverified",
    "circuit_open": "worker_unavailable",
    "lock_held": "worker_unavailable",
    "closed": "worker_unavailable",
}
FATAL_CODES = (
    "model_unverified",
    "runtime_mismatch",
    "model_load_failed",
    "self_test_failed",
    "invalid_arguments",
)
OK_KEYS = {"v", "type", "id", "status", "probabilities", "truncated", "duration_ms", "rss_mb"}
WORKER_ENV_PATH = "/usr/bin:/bin"
# Queued by the reader when the worker sent bytes that are not a valid frame (then the stream ends).
PROTOCOL_ERROR: dict[str, Any] = {"__protocol_error__": True}
START_TIMEOUT: dict[str, Any] = {"__start_timeout__": True}


@dataclass(frozen=True)
class SmsModelEvidence:
    """The model's native output: uncalibrated, not a phishing probability, not a risk tier."""

    model_version: str
    labels: dict[str, float]  # manifest label -> softmax output, rounded to 4 decimals
    top_label: str
    truncated: bool
    score_semantics: Literal["uncalibrated_softmax"] = "uncalibrated_softmax"


@dataclass(frozen=True)
class SmsInferenceResult:
    outcome: Outcome
    reason: str | None  # None only when complete
    evidence: SmsModelEvidence | None  # present only when complete
    model_ms: int | None  # time inside the worker, as reported by it
    wait_ms: int  # admission wait for the worker
    total_ms: int  # whole call, admission included


@dataclass(frozen=True)
class SmsWorkerConfig:
    command: tuple[str, ...]  # never contains message text
    lock_path: Path
    manifest: LoadedManifest
    max_inflight: int = 2
    inference_timeout_s: float = 2.0
    start_timeout_s: float = 90.0
    commit_reserve_s: float = 2.0
    min_budget_s: float = 0.25
    max_rss_mb: int = 1536
    threads: int = 2
    backoff_s: tuple[float, ...] = (1, 2, 4, 8, 16, 32, 60)
    failure_window_s: float = 600.0
    failure_limit: int = 3
    circuit_open_s: float = 600.0
    healthy_reset_s: float = 600.0
    shutdown_grace_s: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_inflight <= 2:
            raise ValueError("max_inflight must be 1 or 2 while one worker exists")
        if not 0 < self.inference_timeout_s <= 10 or not 0 < self.start_timeout_s <= 600:
            raise ValueError("timeouts out of range")
        if not 1 <= self.threads <= 8 or not 512 <= self.max_rss_mb <= 8192:
            raise ValueError("threads or memory ceiling out of range")


def worker_command(
    python: Path, manifest_path: Path, model_dir: Path, threads: int
) -> tuple[str, ...]:
    """`-I`: isolated mode, so no PYTHONPATH, user site or current directory reaches the worker."""
    return (
        str(python),
        "-I",
        "-m",
        "kavach_sms_worker",
        "--manifest",
        str(manifest_path),
        "--model-dir",
        str(model_dir),
        "--threads",
        str(threads),
    )


def worker_environment(home: Path, threads: int) -> dict[str, str]:
    """Built from scratch, never copied from the API: no database URL, key or secret can leak."""
    return {
        "PATH": WORKER_ENV_PATH,
        "HOME": str(home),
        "TMPDIR": str(home),
        "HF_HOME": str(home / "hf"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OMP_NUM_THREADS": str(threads),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def unavailable(reason: str, wait_ms: int = 0, total_ms: int = 0) -> SmsInferenceResult:
    return SmsInferenceResult("unavailable", reason, None, None, wait_ms, total_ms)


def rejected(reason: str, wait_ms: int = 0, total_ms: int = 0) -> SmsInferenceResult:
    return SmsInferenceResult("rejected", reason, None, None, wait_ms, total_ms)


@dataclass
class _Worker:
    generation: int
    process: subprocess.Popen[bytes]
    responses: "queue.Queue[dict[str, Any] | None]"
    threads: list[threading.Thread] = field(default_factory=list)
    stderr_bytes: int = 0


class SmsWorkerSupervisor:
    def __init__(
        self,
        config: SmsWorkerConfig | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> None:
        self.config = config
        self._clock = clock
        self._popen = popen
        self._cond = threading.Condition()
        self._state: State = "disabled" if config is None else "starting"
        self._slots = threading.BoundedSemaphore(config.max_inflight if config else 1)
        self._exec = threading.Lock()
        self._worker: _Worker | None = None
        self._generation = 0
        self._exited: set[int] = set()  # generations whose exit has been accounted for
        self._planned: set[int] = set()  # generations killed on purpose, not as failures
        self._failures: deque[float] = deque()
        self._consecutive = 0
        self._ready_since: float | None = None
        self._last_failure: str | None = None
        self._fatal_code: str | None = None
        self._starts = 0
        self._closing = False
        self._lock_fd: int | None = None
        self._home: Path | None = None
        self._manager: threading.Thread | None = None
        self._threads: list[threading.Thread] = []  # every generation's reader/stderr threads
        self._peak_rss_mb: int | None = None  # the current worker's self-reported peak RSS

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        """Take the model-copy lock and start the worker in the background (never blocks)."""
        if self.config is None:
            return
        fd = os.open(self.config.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            self._set_state("lock_held", "model_copy_lock_held")
            return
        self._lock_fd = fd
        self._home = Path(tempfile.mkdtemp(prefix="kavach-sms-worker-"))
        self._manager = threading.Thread(
            target=self._manage, name="sms-worker-manager", daemon=True
        )
        self._manager.start()

    def close(self) -> None:
        """Stop the worker (stdin close, grace period, then SIGKILL) and release everything."""
        with self._cond:
            if self._closing:
                return
            self._closing = True
            worker = self._worker
            self._cond.notify_all()
        if worker is not None:
            with contextlib.suppress(OSError):
                if worker.process.stdin:
                    worker.process.stdin.close()
            grace = self.config.shutdown_grace_s if self.config else 1.0
            if self._state != "ready":
                grace = 0.0  # starting or restarting: nothing to finish
            try:
                worker.process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                self._kill_process(worker)
        if self._manager is not None:
            self._manager.join(timeout=10)
        for thread in self._threads:
            thread.join(timeout=5)
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None
        if self._home is not None:
            shutil.rmtree(self._home, ignore_errors=True)
            self._home = None
        with self._cond:
            if self._state not in ("disabled", "lock_held"):
                self._state = "closed"
            self._cond.notify_all()

    def __enter__(self) -> "SmsWorkerSupervisor":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def state(self) -> State:
        with self._cond:
            return self._state

    def wait_until(self, states: tuple[State, ...], timeout: float) -> State:
        """Block until the state is one of `states` (or the timeout passes); returns the state."""
        end = time.monotonic() + timeout
        with self._cond:
            while self._state not in states:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            return self._state

    def status(self) -> dict[str, Any]:
        """Operational status for authenticated health: codes and counts only."""
        with self._cond:
            now = self._clock()
            self._prune(now)
            pid = self._worker.process.pid if self._worker and self._state == "ready" else None
            return {
                "state": self._state,
                "model_version": self.config.manifest.model_version if self.config else None,
                "starts": self._starts,
                "failures_in_window": len(self._failures),
                "last_failure": self._last_failure,
                "fatal_code": self._fatal_code,
                "worker_pid": pid,
                "worker_peak_rss_mb": self._peak_rss_mb,
                "free_slots": self._slots._value,  # noqa: SLF001 - read-only diagnostic
            }

    # --- inference ---------------------------------------------------------------------------

    def classify(self, text: str, deadline: float) -> SmsInferenceResult:
        """Classify one SMS before `deadline` (a `time.monotonic()` instant). Never raises for
        model or worker problems; raises ValueError only for text outside the manifest bounds."""
        started = self._clock()
        if self.config is None:
            return unavailable("model_not_deployed")
        if not isinstance(text, str) or not 1 <= len(text) <= self.config.manifest.max_input_chars:
            raise ValueError("SMS text outside the manifest input bounds")
        early = self._state_result()
        if early is not None:
            return early
        if not self._slots.acquire(blocking=False):
            return rejected("inference_saturated", total_ms=self._ms(started))
        try:
            return self._classify_admitted(text, deadline, started)
        finally:
            self._slots.release()

    def _classify_admitted(self, text: str, deadline: float, started: float) -> SmsInferenceResult:
        assert self.config is not None
        cfg = self.config
        generation_at_admission = self._generation
        wait_budget = deadline - cfg.commit_reserve_s - self._clock()
        if wait_budget < cfg.min_budget_s:
            return unavailable("deadline_exhausted", total_ms=self._ms(started))
        if not self._exec.acquire(timeout=wait_budget):
            reason = (
                "worker_restarting"
                if self._generation != generation_at_admission
                else "worker_busy"
            )
            return rejected(reason, self._ms(started), self._ms(started))
        try:
            wait_ms = self._ms(started)
            early = self._state_result(waited=self._generation != generation_at_admission)
            if early is not None:
                return SmsInferenceResult(
                    early.outcome, early.reason, None, None, wait_ms, self._ms(started)
                )
            with self._cond:
                worker = self._worker
            if worker is None:
                return rejected("worker_restarting", wait_ms, self._ms(started))
            budget = min(cfg.inference_timeout_s, deadline - cfg.commit_reserve_s - self._clock())
            if budget < cfg.min_budget_s:
                return unavailable("deadline_exhausted", wait_ms, self._ms(started))
            return self._exchange(worker, text, budget, started, wait_ms)
        finally:
            self._exec.release()

    def _exchange(
        self, worker: _Worker, text: str, budget: float, started: float, wait_ms: int
    ) -> SmsInferenceResult:
        assert self.config is not None
        request_id = secrets.token_hex(16)
        frame = encode_frame(
            {"v": PROTOCOL_VERSION, "type": "classify", "id": request_id, "text": text},
            MAX_REQUEST_BYTES,
        )
        try:
            assert worker.process.stdin is not None
            worker.process.stdin.write(frame)
            worker.process.stdin.flush()
        except (OSError, ValueError):
            self._fail(worker, "worker_crashed")
            return unavailable("worker_crashed", wait_ms, self._ms(started))
        finally:
            del frame  # the only API-side copy made here; the caller still holds `text`
        try:
            message = worker.responses.get(timeout=budget)
        except queue.Empty:
            self._fail(worker, "inference_timeout")
            return unavailable("inference_timeout", wait_ms, self._ms(started))
        if message is None:
            self._fail(worker, "worker_crashed")
            return unavailable("worker_crashed", wait_ms, self._ms(started))
        parsed = None if message is PROTOCOL_ERROR else self._parse_result(message, request_id)
        if parsed is None:
            self._fail(worker, "invalid_model_output")
            return unavailable("invalid_model_output", wait_ms, self._ms(started))
        probabilities, truncated, model_ms, rss_mb = parsed
        labels = self.config.manifest.labels
        top = labels[max(range(len(labels)), key=probabilities.__getitem__)]
        evidence = SmsModelEvidence(
            model_version=self.config.manifest.model_version,
            labels={label: round(p, 4) for label, p in zip(labels, probabilities, strict=True)},
            top_label=top,
            truncated=truncated,
        )
        with self._cond:
            self._peak_rss_mb = rss_mb
        if rss_mb > self.config.max_rss_mb:
            self._planned_restart(worker, "memory_ceiling")
        return SmsInferenceResult("complete", None, evidence, model_ms, wait_ms, self._ms(started))

    def _parse_result(
        self, message: dict[str, Any], request_id: str
    ) -> tuple[list[float], bool, int, int] | None:
        """Strict validation of a result frame; None for anything unexpected."""
        assert self.config is not None
        if set(message) != OK_KEYS or message.get("id") != request_id:
            return None
        if message.get("v") != PROTOCOL_VERSION or message.get("type") != "result":
            return None
        if message.get("status") != "ok":
            return None
        probabilities = message.get("probabilities")
        if not isinstance(probabilities, list) or len(probabilities) != len(
            self.config.manifest.labels
        ):
            return None
        values = []
        for p in probabilities:
            if isinstance(p, bool) or not isinstance(p, int | float):
                return None
            p = float(p)
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                return None
            values.append(p)
        if abs(sum(values) - 1.0) > 1e-3:
            return None
        truncated, model_ms, rss_mb = (
            message.get("truncated"),
            message.get("duration_ms"),
            message.get("rss_mb"),
        )
        if not isinstance(truncated, bool):
            return None
        for number in (model_ms, rss_mb):
            if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                return None
        return values, truncated, model_ms, rss_mb

    def _state_result(self, waited: bool = False) -> SmsInferenceResult | None:
        with self._cond:
            state = self._state
        if state == "ready":
            return None
        if state in TERMINAL_STATE_REASON:
            return unavailable(TERMINAL_STATE_REASON[state])
        if state == "starting" and not waited:
            return rejected("worker_starting")
        return rejected("worker_restarting")

    # --- failure handling --------------------------------------------------------------------

    def _fail(self, worker: _Worker, reason: str) -> None:
        """Count a failure for this generation once, kill it and let the manager restart."""
        with self._cond:
            if worker.generation in self._exited:
                return
            self._exited.add(worker.generation)
            self._record_failure(reason)
            if self._state == "ready":
                self._state = "restarting"
            self._cond.notify_all()
        self._kill_process(worker)
        operational_event("sms_worker.failure", reason, None)

    def _planned_restart(self, worker: _Worker, reason: str) -> None:
        with self._cond:
            if worker.generation in self._exited:
                return
            self._exited.add(worker.generation)
            self._planned.add(worker.generation)
            if self._state == "ready":
                self._state = "restarting"
            self._cond.notify_all()
        self._kill_process(worker)
        operational_event("sms_worker.planned_restart", reason, None)

    def _record_failure(self, reason: str) -> None:
        now = self._clock()
        if self._ready_since is not None and now - self._ready_since >= (
            self.config.healthy_reset_s if self.config else 0
        ):
            self._consecutive = 0
        self._ready_since = None
        self._failures.append(now)
        self._consecutive += 1
        self._last_failure = reason

    def _prune(self, now: float) -> None:
        window = self.config.failure_window_s if self.config else 0
        while self._failures and now - self._failures[0] > window:
            self._failures.popleft()

    def _kill_process(self, worker: _Worker) -> None:
        """SIGKILL the worker's process group: a running torch call cannot be interrupted."""
        process = worker.process
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)

    # --- manager -----------------------------------------------------------------------------

    def _set_state(self, state: State, reason: str) -> None:
        with self._cond:
            self._state = state
            self._cond.notify_all()
        operational_event(f"sms_worker.{state}", reason, None)

    def _sleep(self, seconds: float) -> bool:
        """Wait unless closing; True if the wait finished without a close."""
        end = time.monotonic() + seconds
        with self._cond:
            while not self._closing:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return True
                self._cond.wait(remaining)
            return False

    def _manage(self) -> None:
        assert self.config is not None
        cfg = self.config
        probing = False
        while True:
            with self._cond:
                if self._closing:
                    return
            outcome = self._start_once()
            if outcome == "fatal":
                return
            if outcome == "ready":
                worker = self._worker
                assert worker is not None
                with self._cond:
                    while not self._closing and worker.generation not in self._exited:
                        self._cond.wait()
                    if self._closing:
                        return
                    planned = worker.generation in self._planned
                probing = False
                if planned:
                    self._set_state("restarting", "planned")
                    continue
            # A failure: back off, or open the circuit.
            with self._cond:
                self._prune(self._clock())
                open_circuit = probing or len(self._failures) >= cfg.failure_limit
                delay = cfg.backoff_s[min(self._consecutive, len(cfg.backoff_s)) - 1]
            if open_circuit:
                self._set_state("circuit_open", self._last_failure or "failure")
                if not self._sleep(cfg.circuit_open_s):
                    return
                probing = True  # exactly one probe start; if it fails, the circuit opens again
            else:
                self._set_state("restarting", self._last_failure or "failure")
                if not self._sleep(delay):
                    return

    def _start_once(self) -> Literal["ready", "failed", "fatal"]:
        assert self.config is not None and self._home is not None
        cfg = self.config
        with self._cond:
            if self._closing:
                return "fatal"
            self._generation += 1
            generation = self._generation
            self._state = "starting"
            self._worker = None
            self._starts += 1
            self._cond.notify_all()
        try:
            process = self._popen(
                list(cfg.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=worker_environment(self._home, cfg.threads),
                cwd=self._home,
                close_fds=True,
                start_new_session=True,
            )
        except OSError:
            with self._cond:
                self._record_failure("spawn_failed")
            operational_event("sms_worker.failure", "spawn_failed", None)
            return "failed"
        worker = _Worker(generation, process, queue.Queue())
        worker.threads = [
            threading.Thread(
                target=self._read_frames,
                args=(worker,),
                daemon=True,
                name=f"sms-worker-reader-{generation}",
            ),
            threading.Thread(
                target=self._drain_stderr,
                args=(worker,),
                daemon=True,
                name=f"sms-worker-stderr-{generation}",
            ),
        ]
        for thread in worker.threads:
            thread.start()
        self._threads.extend(worker.threads)
        with self._cond:
            self._worker = worker  # state is still "starting": classify never uses it yet
            closing = self._closing
        if closing:
            self._kill_process(worker)
            return "fatal"
        try:
            first = worker.responses.get(timeout=cfg.start_timeout_s)
        except queue.Empty:
            first = START_TIMEOUT
        if first is not None and first.get("type") == "fatal":
            code = first.get("code") if first.get("code") in FATAL_CODES else "model_unverified"
            with self._cond:
                self._exited.add(generation)
                self._fatal_code = code
            self._kill_process(worker)
            self._set_state("unverified", code)
            return "fatal"
        if first is not None and first.get("type") == "ready" and self._ready_matches(first):
            with self._cond:
                if self._closing:
                    return "fatal"
                self._state = "ready"
                self._ready_since = self._clock()
                rss = first.get("rss_mb")
                self._peak_rss_mb = (
                    rss if isinstance(rss, int) and not isinstance(rss, bool) else None
                )
                self._cond.notify_all()
            operational_event("sms_worker.ready", "self_test_passed", None)
            return "ready"
        if first is not None and first.get("type") == "ready":
            # A worker that verified a different manifest is not ours: terminal, like a fatal.
            with self._cond:
                self._exited.add(generation)
                self._fatal_code = "manifest_mismatch"
            self._kill_process(worker)
            self._set_state("unverified", "manifest_mismatch")
            return "fatal"
        if first is START_TIMEOUT:
            reason = "start_timeout"
        elif first is PROTOCOL_ERROR or first is not None:
            reason = "invalid_startup_output"
        else:
            reason = "worker_crashed"
        with self._cond:
            self._exited.add(generation)
            self._record_failure(reason)
        self._kill_process(worker)
        operational_event("sms_worker.failure", reason, None)
        return "failed"

    def _ready_matches(self, frame: dict[str, Any]) -> bool:
        assert self.config is not None
        manifest = self.config.manifest
        return (
            frame.get("v") == PROTOCOL_VERSION
            and frame.get("manifest_sha256") == manifest.sha256
            and frame.get("model_version") == manifest.model_version
            and frame.get("self_test") == "passed"
        )

    def _read_frames(self, worker: _Worker) -> None:
        stream: IO[bytes] | None = worker.process.stdout
        assert stream is not None
        try:
            while True:
                message = read_frame(stream, MAX_RESPONSE_BYTES)  # type: ignore[arg-type]
                if message is None:
                    break
                worker.responses.put(message)
        except ProtocolError:
            worker.responses.put(PROTOCOL_ERROR)  # invalid output, then treated as an exit
        except (OSError, ValueError):
            pass  # a dead pipe: an exit
        worker.responses.put(None)
        self._on_exit(worker)

    def _drain_stderr(self, worker: _Worker) -> None:
        """Read and discard: library output could contain anything, so none of it is logged."""
        stream = worker.process.stderr
        assert stream is not None
        with contextlib.suppress(OSError, ValueError):
            while chunk := stream.read(4096):
                worker.stderr_bytes += len(chunk)

    def _on_exit(self, worker: _Worker) -> None:
        """The worker's stdout ended. If nobody accounted for it yet, it is an idle crash."""
        with self._cond:
            current = self._worker is worker and self._state == "ready"
            if self._closing or worker.generation in self._exited or not current:
                return
            self._exited.add(worker.generation)
            self._record_failure("worker_crashed")
            self._state = "restarting"
            self._cond.notify_all()
        self._kill_process(worker)
        operational_event("sms_worker.failure", "worker_crashed", None)

    def _ms(self, since: float) -> int:
        return max(0, int((self._clock() - since) * 1000))
