"""SMS worker supervisor: TD-18 admission, timeouts, crashes, recovery, locking, privacy.

The worker here is the test-only fake in `tests/fakes/fake_sms_worker.py`: a real child process
speaking the real protocol, with scripted faults. All message texts are fictional.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from kavach.models import sms_worker
from kavach.models.manifest import ManifestInvalid, load_manifest, parse_manifest
from kavach.models.protocol import HEADER
from kavach.models.sms_worker import (
    REJECTED_REASONS,
    UNAVAILABLE_REASONS,
    SmsWorkerConfig,
    SmsWorkerSupervisor,
    worker_command,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
FAKE = Path(__file__).parent / "fakes" / "fake_sms_worker.py"
MANIFEST = load_manifest(MANIFEST_PATH)
TEXT = "FICTIONAL TEST: your parcel fee is due at http://parcel.example"
SECRET_TEXT = "FICTIONAL PRIVATE 4417-PRIVACY-CANARY message body"
ALLOWED_ENV = {
    "PATH",
    "HOME",
    "TMPDIR",
    "HF_HOME",
    "LANG",
    "LC_ALL",
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "HF_HUB_DISABLE_TELEMETRY",
    "HF_DATASETS_OFFLINE",
    "TOKENIZERS_PARALLELISM",
    "OMP_NUM_THREADS",
    "PYTHONDONTWRITEBYTECODE",
    "__CF_USER_TEXT_ENCODING",  # added by macOS itself to every process
}


def fake_config(tmp_path: Path, mode: str = "ready", report: Path | None = None, **overrides):
    command = [
        sys.executable,
        "-I",
        str(FAKE),
        "--mode",
        mode,
        "--manifest-sha256",
        MANIFEST.sha256,
        "--model-version",
        MANIFEST.model_version,
    ]
    if report is not None:
        command += ["--report", str(report)]
    settings = {
        "command": tuple(command),
        "lock_path": tmp_path / "sms.lock",
        "manifest": MANIFEST,
        "inference_timeout_s": 1.0,
        "start_timeout_s": 10.0,
        "commit_reserve_s": 0.0,
        "min_budget_s": 0.05,
        "backoff_s": (0.05, 0.1),
        "failure_window_s": 60.0,
        "failure_limit": 3,
        "circuit_open_s": 0.5,
        "shutdown_grace_s": 2.0,
    }
    settings.update(overrides)
    return SmsWorkerConfig(**settings)


def later(seconds: float = 10.0) -> float:
    return time.monotonic() + seconds


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def make(tmp_path):
    created: list[SmsWorkerSupervisor] = []

    def build(config, **kwargs) -> SmsWorkerSupervisor:
        supervisor = SmsWorkerSupervisor(config, **kwargs)
        created.append(supervisor)
        supervisor.start()
        return supervisor

    yield build
    for supervisor in created:
        supervisor.close()


def ready(supervisor: SmsWorkerSupervisor) -> SmsWorkerSupervisor:
    assert supervisor.wait_until(("ready",), 10) == "ready"
    return supervisor


# --- valid inference and output semantics ----------------------------------------------------


def test_valid_inference_returns_native_uncalibrated_evidence_with_provenance(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path)))
    result = supervisor.classify(TEXT, later())
    assert result.outcome == "complete" and result.reason is None
    evidence = result.evidence
    assert evidence.labels == {"legitimate": 0.1, "spam": 0.2, "fraud": 0.7}
    assert evidence.top_label == "fraud" and evidence.truncated is False
    assert evidence.score_semantics == "uncalibrated_softmax"
    assert evidence.model_version == MANIFEST.model_version
    assert evidence.model_version.startswith("horizon-phishing-scam-base@fa686fc0d6a3+m1:")
    assert result.model_ms == 3 and result.total_ms >= 0 and result.wait_ms >= 0
    # No validated probability, risk score or tier is produced anywhere in the result.
    fields = set(vars(result)) | set(vars(evidence))
    assert not fields & {"sms_score", "tier", "risk", "probability", "phishing_probability"}


def test_reason_sets_are_disjoint_and_explicit():
    assert not set(REJECTED_REASONS) & set(UNAVAILABLE_REASONS)


def test_disabled_supervisor_is_unavailable_with_null_evidence():
    supervisor = SmsWorkerSupervisor(None)
    supervisor.start()
    result = supervisor.classify(TEXT, later())
    assert (result.outcome, result.reason, result.evidence) == (
        "unavailable",
        "model_not_deployed",
        None,
    )
    assert supervisor.state == "disabled"


@pytest.mark.parametrize("text", ["", "x" * (MANIFEST.max_input_chars + 1)])
def test_text_outside_manifest_bounds_is_refused_without_taking_a_slot(tmp_path, make, text):
    supervisor = ready(make(fake_config(tmp_path)))
    with pytest.raises(ValueError) as error:
        supervisor.classify(text, later())
    assert text[:20] not in str(error.value) or not text
    assert supervisor.status()["free_slots"] == 2


# --- invalid output, crash, timeout, recovery ------------------------------------------------


@pytest.mark.parametrize(
    "directive",
    [
        "fake:wrong_id",
        "fake:nan",
        "fake:sum",
        "fake:count",
        "fake:extra",
        "fake:error",
        "fake:garbage",
        "fake:oversize",
    ],
)
def test_invalid_worker_output_is_unavailable_and_the_worker_is_replaced(tmp_path, make, directive):
    report = tmp_path / "report.json"
    supervisor = ready(make(fake_config(tmp_path, report=report)))
    first_pid = json.loads(report.read_text())["pid"]
    result = supervisor.classify(directive, later())
    assert (result.outcome, result.reason, result.evidence) == (
        "unavailable",
        "invalid_model_output",
        None,
    )
    assert wait_dead(first_pid)
    ready(supervisor)
    assert json.loads(report.read_text())["pid"] != first_pid
    assert supervisor.classify(TEXT, later()).outcome == "complete"
    assert supervisor.status()["free_slots"] == 2


def test_crash_during_inference_is_reported_and_recovered(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path)))
    result = supervisor.classify("fake:crash", later())
    assert (result.outcome, result.reason, result.evidence) == (
        "unavailable",
        "worker_crashed",
        None,
    )
    assert supervisor.status()["last_failure"] == "worker_crashed"
    ready(supervisor)
    assert supervisor.classify(TEXT, later()).outcome == "complete"
    assert supervisor.status()["starts"] == 2


def test_per_inference_timeout_kills_the_worker_and_no_late_result_is_used(tmp_path, make):
    report = tmp_path / "report.json"
    supervisor = ready(make(fake_config(tmp_path, report=report, inference_timeout_s=0.3)))
    info = json.loads(report.read_text())
    started = time.monotonic()
    result = supervisor.classify("fake:sleep:5", later())
    elapsed = time.monotonic() - started
    assert (result.outcome, result.reason, result.evidence) == (
        "unavailable",
        "inference_timeout",
        None,
    )
    assert 0.3 <= elapsed < 1.5
    assert wait_dead(info["pid"]), "the timed-out worker must be killed, not left running"
    assert info["pgid"] == info["pid"], "the worker runs in its own process group"
    ready(supervisor)
    after = supervisor.classify(TEXT, later())
    assert after.outcome == "complete" and after.evidence.labels["fraud"] == 0.7


def test_inference_budget_respects_the_request_deadline(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path, inference_timeout_s=5.0, commit_reserve_s=0.5)))
    started = time.monotonic()
    result = supervisor.classify("fake:sleep:5", time.monotonic() + 0.9)
    assert result.reason == "inference_timeout"
    assert time.monotonic() - started < 1.2  # 0.9 s deadline minus the 0.5 s commit reserve


def test_exhausted_deadline_sends_nothing(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path, commit_reserve_s=2.0)))
    result = supervisor.classify(TEXT, time.monotonic() + 1.0)
    assert (result.outcome, result.reason) == ("unavailable", "deadline_exhausted")
    assert supervisor.status()["starts"] == 1 and supervisor.status()["free_slots"] == 2


def test_startup_timeout_kills_the_hung_worker_and_retries(tmp_path, make):
    report = tmp_path / "report.json"
    supervisor = make(fake_config(tmp_path, mode="hang", report=report, start_timeout_s=0.4))
    time.sleep(0.2)
    assert supervisor.classify(TEXT, later()).reason == "worker_starting"
    pid = json.loads(report.read_text())["pid"]
    assert wait_dead(pid, 3), "a worker that never becomes ready is killed"
    assert supervisor.wait_until(("restarting", "circuit_open"), 3) in (
        "restarting",
        "circuit_open",
    )
    assert supervisor.status()["last_failure"] == "start_timeout"


def test_repeated_failures_open_the_circuit_and_a_failed_probe_reopens_it(tmp_path, make):
    supervisor = make(fake_config(tmp_path, mode="crash"))
    assert supervisor.wait_until(("circuit_open",), 10) == "circuit_open"
    result = supervisor.classify(TEXT, later())
    assert (result.outcome, result.reason) == ("unavailable", "worker_unavailable")
    starts = supervisor.status()["starts"]
    assert starts == 3
    # After circuit_open_s exactly one probe start runs; it fails, so the circuit opens again.
    assert supervisor.wait_until(("starting", "restarting"), 3) in ("starting", "restarting")
    assert supervisor.wait_until(("circuit_open",), 5) == "circuit_open"
    assert supervisor.status()["starts"] == starts + 1


def test_idle_crash_is_detected_and_recovered(tmp_path, make):
    report = tmp_path / "report.json"
    supervisor = ready(make(fake_config(tmp_path, report=report)))
    pid = json.loads(report.read_text())["pid"]
    os.kill(pid, 9)
    assert supervisor.wait_until(("restarting",), 5) == "restarting"
    ready(supervisor)
    assert supervisor.classify(TEXT, later()).outcome == "complete"


@pytest.mark.parametrize("mode", ["fatal", "wrong_manifest", "no_self_test"])
def test_failed_startup_verification_is_terminal_and_never_restarted(tmp_path, make, mode):
    supervisor = make(fake_config(tmp_path, mode=mode))
    assert supervisor.wait_until(("unverified",), 10) == "unverified"
    result = supervisor.classify(TEXT, later())
    assert (result.outcome, result.reason, result.evidence) == (
        "unavailable",
        "model_unverified",
        None,
    )
    time.sleep(0.3)
    assert supervisor.status()["starts"] == 1


def test_garbage_at_startup_counts_as_a_failure(tmp_path, make):
    supervisor = make(fake_config(tmp_path, mode="garbage"))
    assert supervisor.wait_until(("restarting", "circuit_open"), 5) in (
        "restarting",
        "circuit_open",
    )
    assert supervisor.status()["last_failure"] == "invalid_startup_output"


def test_memory_ceiling_restarts_between_requests_without_counting_a_failure(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path, max_rss_mb=512)))
    result = supervisor.classify("fake:rss:600", later())
    assert result.outcome == "complete"  # the answer is kept; the restart comes after it
    ready(supervisor)
    status = supervisor.status()
    assert status["starts"] == 2 and status["failures_in_window"] == 0


# --- admission, queueing, slots --------------------------------------------------------------


def run_parallel(supervisor, texts, deadline_s=10.0):
    results: list = [None] * len(texts)
    barrier = threading.Barrier(len(texts))

    def worker(index: int) -> None:
        barrier.wait()
        if index:
            time.sleep(0.05 * index)  # deterministic arrival order
        results[index] = supervisor.classify(texts[index], later(deadline_s))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(texts))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    return results


def test_two_admitted_one_executing_one_waiting_third_rejected(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path)))
    results = run_parallel(supervisor, ["fake:sleep:0.5", "fake:sleep:0.1", TEXT])
    assert [r.outcome for r in results] == ["complete", "complete", "rejected"]
    assert results[2].reason == "inference_saturated" and results[2].evidence is None
    assert results[1].wait_ms >= 300, "the second request waited for the first"
    assert supervisor.status()["free_slots"] == 2


def test_waiting_request_is_rejected_when_the_executing_one_kills_the_worker(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path, inference_timeout_s=0.4)))
    results = run_parallel(supervisor, ["fake:sleep:5", TEXT])
    assert results[0].reason == "inference_timeout"
    assert (results[1].outcome, results[1].reason) == ("rejected", "worker_restarting")
    assert supervisor.status()["free_slots"] == 2


def test_slots_are_released_after_an_unexpected_exception(tmp_path, make, monkeypatch):
    supervisor = ready(make(fake_config(tmp_path)))

    def boom(*_args, **_kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(sms_worker, "encode_frame", boom)
    with pytest.raises(RuntimeError):
        supervisor.classify(TEXT, later())
    assert supervisor.status()["free_slots"] == 2
    assert supervisor._exec.acquire(blocking=False)  # the execution lock was released too
    supervisor._exec.release()


def test_slots_are_never_leaked_across_a_mixed_fault_run(tmp_path, make):
    supervisor = ready(make(fake_config(tmp_path, inference_timeout_s=0.3, failure_limit=50)))
    for text in [TEXT, "fake:crash", "fake:nan", "fake:sleep:2", TEXT, "fake:garbage", TEXT]:
        supervisor.wait_until(("ready",), 10)
        supervisor.classify(text, later())
        assert supervisor.status()["free_slots"] == 2
    ready(supervisor)
    assert supervisor.classify(TEXT, later()).outcome == "complete"


# --- one model copy --------------------------------------------------------------------------


def test_the_model_copy_lock_prevents_a_second_worker(tmp_path, make):
    first = ready(make(fake_config(tmp_path)))
    spawned = []

    def counting_popen(*args, **kwargs):
        spawned.append(args)
        return subprocess.Popen(*args, **kwargs)

    second = make(fake_config(tmp_path), popen=counting_popen)
    assert second.state == "lock_held"
    assert second.classify(TEXT, later()).reason == "worker_unavailable"
    time.sleep(0.2)
    assert spawned == [], "a supervisor without the lock never spawns a worker"
    first.close()
    third = ready(make(fake_config(tmp_path)))
    assert third.classify(TEXT, later()).outcome == "complete"


# --- privacy and secrets ---------------------------------------------------------------------


class RecordingStdin:
    """Wraps the worker's stdin to capture exactly what crosses the pipe."""

    def __init__(self, inner) -> None:
        self.inner, self.data = inner, bytearray()

    def write(self, data: bytes) -> int:
        self.data += data
        return self.inner.write(data)

    def flush(self) -> None:
        self.inner.flush()

    def close(self) -> None:
        self.inner.close()


def test_secrets_never_reach_the_worker_environment_or_arguments(tmp_path, make, monkeypatch):
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "AUDIT_HMAC_KEYS",
        "PAYLOAD_HMAC_KEYS",
        "SUBSCRIBER_HMAC_KEYS",
        "RATE_LIMIT_HMAC_KEY",
        "PYTHONPATH",
        "DYLD_INSERT_LIBRARIES",
        "LD_PRELOAD",
    ):
        monkeypatch.setenv(name, "secret-value-must-not-propagate")
    report = tmp_path / "report.json"
    supervisor = ready(make(fake_config(tmp_path, report=report)))
    supervisor.classify(SECRET_TEXT, later())
    info = json.loads(report.read_text())
    assert set(info["env"]) <= ALLOWED_ENV
    assert "secret-value-must-not-propagate" not in json.dumps(info)
    assert info["env"]["HF_HUB_OFFLINE"] == "1" and info["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert SECRET_TEXT not in " ".join(info["argv"])


def test_text_crosses_only_the_stdin_pipe_with_random_request_ids(tmp_path, make, caplog):
    recorders: list[RecordingStdin] = []

    def recording_popen(*args, **kwargs):
        process = subprocess.Popen(*args, **kwargs)
        process.stdin = RecordingStdin(process.stdin)
        recorders.append(process.stdin)
        return process

    caplog.set_level(logging.DEBUG)
    supervisor = ready(make(fake_config(tmp_path), popen=recording_popen))
    results = [
        supervisor.classify(f"fake:stderr {SECRET_TEXT}", later()),
        supervisor.classify(f"fake:stdout {SECRET_TEXT}", later()),
        supervisor.classify("fake:crash", later()),
    ]
    assert [r.outcome for r in results[:2]] == ["complete", "complete"]
    data = bytes(recorders[0].data)
    frames, ids = [], []
    while data:
        (length,) = HEADER.unpack(data[:4])
        frames.append(json.loads(data[4 : 4 + length]))
        data = data[4 + length :]
    ids = [f["id"] for f in frames]
    assert len(set(ids)) == len(ids) == 3 and all(len(i) == 32 for i in ids)
    assert all(set(f) == {"v", "type", "id", "text"} for f in frames)
    supervisor.close()
    # The worker printed the text to stderr and stdout; none of it reached any log or result.
    logged = caplog.text + json.dumps(supervisor.status())
    assert "PRIVACY-CANARY" not in logged
    assert all("PRIVACY-CANARY" not in repr(r) for r in results)


def test_errors_and_status_never_contain_text(tmp_path, make, caplog):
    caplog.set_level(logging.DEBUG)
    supervisor = ready(make(fake_config(tmp_path, inference_timeout_s=0.3)))
    texts = [f"fake:sleep:2 {SECRET_TEXT}", f"fake:crash {SECRET_TEXT}"]
    for text in texts:
        supervisor.wait_until(("ready",), 10)
        result = supervisor.classify(text, later())
        assert "PRIVACY-CANARY" not in repr(result)
    assert "PRIVACY-CANARY" not in caplog.text + json.dumps(supervisor.status())


# --- teardown --------------------------------------------------------------------------------


def test_close_stops_the_worker_releases_the_lock_and_cleans_up(tmp_path):
    report = tmp_path / "report.json"
    supervisor = SmsWorkerSupervisor(fake_config(tmp_path, report=report))
    supervisor.start()
    ready(supervisor)
    pid = json.loads(report.read_text())["pid"]
    home = Path(json.loads(report.read_text())["env"]["HOME"])
    supervisor.close()
    supervisor.close()  # idempotent
    assert supervisor.state == "closed"
    assert wait_dead(pid, 1)
    assert not home.exists()
    assert supervisor.classify(TEXT, later()).reason == "worker_unavailable"
    assert not [t for t in threading.enumerate() if t.name.startswith("sms-worker")]
    again = SmsWorkerSupervisor(fake_config(tmp_path))
    again.start()
    assert again.state != "lock_held"
    again.close()


def test_close_during_a_hung_startup_is_prompt(tmp_path):
    report = tmp_path / "report.json"
    supervisor = SmsWorkerSupervisor(fake_config(tmp_path, mode="hang", report=report))
    supervisor.start()
    time.sleep(0.3)
    started = time.monotonic()
    supervisor.close()
    assert time.monotonic() - started < 3
    assert wait_dead(json.loads(report.read_text())["pid"], 1)


# --- configuration, manifest, isolation ------------------------------------------------------


def test_worker_command_is_isolated_and_carries_no_text(tmp_path):
    command = worker_command(Path("/opt/w/bin/python"), MANIFEST_PATH, tmp_path, 2)
    assert command[:4] == ("/opt/w/bin/python", "-I", "-m", "kavach_sms_worker")
    with pytest.raises(ValueError):
        replace(fake_config(tmp_path), max_inflight=3)


def test_the_committed_manifest_pins_the_audited_model():
    m = MANIFEST.manifest
    assert m.repo == "Horizon-Labs/phishing-scam-detector-base"
    assert m.revision == "fa686fc0d6a3634092ada93a7c6b89ab0746b8f8"
    assert m.labels == ("legitimate", "spam", "fraud")
    weights = next(f for f in m.files if f.name == "model.safetensors")
    assert weights.sha256 == "1f056ed61f8c0f6bfb11616e9c2f640762dcbbaff92bdb71657723f1d84125af"
    assert m.calibration is None and m.score_semantics == "uncalibrated_softmax"
    assert m.runtime.packages == {
        "huggingface-hub": "2.2.0",
        "numpy": "2.5.4",
        "safetensors": "0.8.0",
        "tokenizers": "0.23.3",
        "torch": "2.14.1",
        "transformers": "5.20.2",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["files"].append(
            {"name": "pytorch_model.bin", "sha256": "a" * 64, "size_bytes": 1}
        ),
        lambda d: d["files"].append({"name": "modeling.py", "sha256": "a" * 64, "size_bytes": 1}),
        lambda d: d["files"].append({"name": "../x.json", "sha256": "a" * 64, "size_bytes": 1}),
        lambda d: d.update(revision="main"),
        lambda d: d.update(calibration={"method": "isotonic"}),
        lambda d: d.update(score_semantics="calibrated_probability"),
        lambda d: d.update(labels=["legitimate", "spam", "spam"]),
        lambda d: d.update(artifact_dir="../outside"),
        lambda d: d.update(unexpected_key=1),
        lambda d: d["self_test"].update(expected_probabilities=[0.5, 0.5]),
        lambda d: d["runtime"].update(device="mps"),
        lambda d: d.update(files=[f for f in d["files"] if f["name"] != "model.safetensors"]),
    ],
)
def test_a_tampered_manifest_is_refused(mutate):
    data = json.loads(MANIFEST_PATH.read_text())
    mutate(data)
    with pytest.raises(ManifestInvalid) as error:
        parse_manifest(json.dumps(data).encode())
    assert "sha256" not in str(error.value) and len(str(error.value)) < 40


def test_the_api_environment_never_imports_torch():
    code = (
        "import sys, kavach.main, kavach.models.sms_worker; "
        "print(sorted(m for m in ('torch','transformers','tokenizers','safetensors','numpy') "
        "if m in sys.modules))"
    )
    found = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert found.stdout.strip() == "[]"
    lock = (REPO / "backend" / "uv.lock").read_text()
    for package in ("torch", "transformers", "tokenizers", "safetensors"):
        assert f'name = "{package}"' not in lock
