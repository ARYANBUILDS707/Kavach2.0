"""Scenario runner: plans run-specific events from the catalog and submits them through the
ordinary event endpoints with an operator-provisioned ingestion key (source `simulator`).

Safety boundaries:
- Targets only loopback hosts (`validate_target`); there is no override.
- Never follows redirects, never retries anything but 429 (honoring Retry-After), and stops
  the whole run on 401, an unexpected 403, 5xx or a lost connection, so a wrong key cannot
  burn the invalid-key throttle and an outage is not hammered.
- Paces itself below the server's per-key limit (D08) and reserves room for a whole scenario
  before starting it; it never tries to evade the server's limit.
- Caps submissions per run.
- Output carries event IDs, statuses, receipt IDs and warning codes only: never the key,
  subscriber tokens, SMS text or ground-truth labels in a payload.

Event IDs (`sim-<run>-<scenario>-<step>`) and subscriber tokens (derived from seed, run ID,
scenario and alias) are deterministic, so the same seed and run ID replay identically. Event
times are fresh: the scenario's offsets are applied to the time the scenario starts.
"""

import hashlib
import http.client
import json
import re
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from kavach.auth.throttle import SUBMISSION_WINDOW_SECONDS, SUBMISSIONS_PER_KEY
from kavach.simulator.catalog import (
    ConflictStep,
    Expectation,
    Scenario,
    ScenarioCatalog,
    SubmitStep,
)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_TARGET = "http://127.0.0.1:8000"
EVENTS_PATH = "/api/v1/events"
RUN_ID = re.compile(r"^[a-z0-9]{1,16}$")
MAX_SEED = 2**31 - 1
MAX_SUBMISSIONS_PER_RUN = 60
MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = SUBMISSION_WINDOW_SECONDS
DEFAULT_PER_MINUTE = 20
# Server deadline (INFERENCE_TIMEOUT_SECONDS, default 30) plus headroom.
REQUEST_TIMEOUT_SECONDS = 35.0
# Expected while no model is deployed (C-01): every stage unavailable, never a score.
NO_MODEL_WARNINGS = {
    "sms": ["SMS_CLASSIFIER_UNAVAILABLE"],
    "call": ["SYNTHESIS_UNAVAILABLE", "TRANSCRIPTION_UNAVAILABLE", "VOICE_INTENT_UNAVAILABLE"],
}
# The only receipt outcomes the contract allows (API.md; M4-I.2 adds the SMS worker): no model,
# or uncalibrated SMS model evidence. A receipt never carries a score or a tier.
ALLOWED_ANALYSIS = {
    "sms": {
        ("unavailable", ("SMS_CLASSIFIER_UNAVAILABLE",)),
        ("complete", ("SMS_SCORE_UNCALIBRATED",)),
    },
    "call": {("unavailable", tuple(NO_MODEL_WARNINGS["call"]))},
}
RECEIPT_FIELDS = ("event_id", "external_event_id", "source", "kind", "analysis_status", "warnings")


class SimulatorRefused(Exception):
    """A configuration or plan the runner will not execute; nothing was sent."""


class TargetUnreachable(Exception):
    """The connection failed or timed out; the outcome of that request is unknown."""


# --- target ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int


def validate_target(url: str) -> Target:
    """Only http(s) on a loopback host, with no credentials, path, query or fragment."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise SimulatorRefused("The target URL is malformed") from None
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https") or host not in LOOPBACK_HOSTS:
        raise SimulatorRefused("The simulator only targets http(s) on a loopback host")
    if parts.username or parts.password or parts.path not in ("", "/"):
        raise SimulatorRefused("The target URL must not carry credentials or a path")
    if parts.query or parts.fragment:
        raise SimulatorRefused("The target URL must not carry a query or fragment")
    return Target(parts.scheme, host, port or (443 if parts.scheme == "https" else 80))


# --- transport ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]  # lower-case names
    body: bytes


class Transport(Protocol):
    def request(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResult: ...


class LoopbackTransport:
    """One connection per request with the standard library; redirects are never followed."""

    def __init__(self, target: Target, timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self.target = target
        self.timeout = timeout

    def request(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResult:
        connection_type = (
            http.client.HTTPSConnection
            if self.target.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(self.target.host, self.target.port, timeout=self.timeout)
        try:
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            return HttpResult(
                response.status,
                {name.lower(): value for name, value in response.getheaders()},
                response.read(64 * 1024),
            )
        except (OSError, http.client.HTTPException):
            raise TargetUnreachable from None
        finally:
            connection.close()


# --- planning ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedStep:
    scenario_id: str
    step: str
    action: str
    kind: str
    external_event_id: str
    subscriber: str  # the alias, never the token
    offset_seconds: int
    expect: Expectation
    of: str | None
    truth: str | None  # simulation-only; never sent
    payload: dict[str, Any] = field(repr=False)


def subscriber_token(seed: int, run_id: str, scenario_id: str, alias: str) -> str:
    """Opaque, run-specific and non-numeric (the API rejects phone-like tokens)."""
    material = f"kavach-sim|{seed}|{run_id}|{scenario_id}|{alias}".encode()
    return "sim-" + hashlib.sha256(material).hexdigest()[:24]


def validate_run(seed: int, run_id: str) -> None:
    if not RUN_ID.fullmatch(run_id):
        raise SimulatorRefused("The run ID must be 1-16 lower-case letters or digits")
    if not 0 <= seed <= MAX_SEED:
        raise SimulatorRefused("The seed must be between 0 and 2147483647")


def plan_scenario(
    scenario: Scenario, source: str, *, seed: int, run_id: str, anchor: datetime
) -> list[PlannedStep]:
    """Payloads for one scenario; `anchor` is when it starts (event time = anchor + offset)."""
    validate_run(seed, run_id)
    planned: dict[str, PlannedStep] = {}
    for step in scenario.steps:
        if isinstance(step, SubmitStep):
            event_id = f"sim-{run_id}-{scenario.id.lower()}-{step.step.replace('_', '-')}"
            payload: dict[str, Any] = {
                "event_id": event_id,
                "subscriber_token": subscriber_token(seed, run_id, scenario.id, step.subscriber),
                "timestamp": (anchor + timedelta(seconds=step.offset_seconds)).isoformat(),
                "source": step.source or source,
            }
            if step.kind == "sms":
                payload["text"] = step.text
                if step.sender_id is not None:
                    payload["sender_id"] = step.sender_id
            else:
                payload["audio_reference"] = step.audio_reference
            planned[step.step] = PlannedStep(
                scenario.id,
                step.step,
                step.action,
                step.kind,
                event_id,
                step.subscriber,
                step.offset_seconds,
                step.expect,
                None,
                step.truth,
                payload,
            )
        else:
            base = planned[step.of]
            payload = dict(base.payload)
            if isinstance(step, ConflictStep):
                payload["text"] = step.text
            planned[step.step] = PlannedStep(
                scenario.id,
                step.step,
                step.action,
                base.kind,
                base.external_event_id,
                base.subscriber,
                base.offset_seconds,
                step.expect,
                step.of,
                base.truth,
                payload,
            )
    return list(planned.values())


# --- pacing ------------------------------------------------------------------------------


class Pacer:
    """Client-side sliding window, kept below the server's per-key limit."""

    def __init__(
        self,
        per_minute: int,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 1 <= per_minute <= SUBMISSIONS_PER_KEY:
            raise SimulatorRefused(f"--max-per-minute must be 1-{SUBMISSIONS_PER_KEY}")
        self.per_minute = per_minute
        self.monotonic = monotonic
        self.sleep = sleep
        self.sent: deque[float] = deque()

    def _recent(self) -> int:
        now = self.monotonic()
        while self.sent and self.sent[0] <= now - SUBMISSION_WINDOW_SECONDS:
            self.sent.popleft()
        return len(self.sent)

    def make_room(self, count: int) -> None:
        """Wait until `count` more submissions fit in the window."""
        count = min(count, self.per_minute)
        while self._recent() + count > self.per_minute:
            self.sleep(max(0.05, self.sent[0] + SUBMISSION_WINDOW_SECONDS - self.monotonic()))

    def record(self) -> None:
        self.sent.append(self.monotonic())


# --- results -----------------------------------------------------------------------------


@dataclass
class StepResult:
    step: str
    action: str
    kind: str
    external_event_id: str
    expected_status: int
    expected_code: str | None
    status: int | None = None
    code: str | None = None
    receipt_id: str | None = None
    replayed: bool | None = None
    analysis_status: str | None = None
    warnings: list[str] = field(default_factory=list)
    rate_limit_retries: int = 0
    failures: list[str] = field(default_factory=list)
    skipped: bool = False

    @property
    def passed(self) -> bool:
        return not self.skipped and not self.failures


@dataclass
class ScenarioResult:
    scenario_id: str
    version: int
    name: str
    truth: str
    provisional: list[str]
    steps: list[StepResult]
    elapsed_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps)


@dataclass
class RunReport:
    run_id: str
    seed: int
    catalog_version: int
    dry_run: bool
    scenarios: list[ScenarioResult] = field(default_factory=list)
    submissions: int = 0
    aborted: str | None = None

    @property
    def passed(self) -> bool:
        return self.aborted is None and all(s.passed for s in self.scenarios)


class RunAborted(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- execution ---------------------------------------------------------------------------


def error_code(result: HttpResult) -> str | None:
    try:
        return str(json.loads(result.body)["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def receipt_data(result: HttpResult) -> dict[str, Any]:
    try:
        data = json.loads(result.body)["data"]
    except (ValueError, KeyError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


class Runner:
    def __init__(
        self,
        catalog: ScenarioCatalog,
        transport: Transport,
        api_key: str,
        *,
        clock: Callable[[], datetime],
        pacer: Pacer,
        seed: int,
        run_id: str,
    ) -> None:
        validate_run(seed, run_id)
        if not api_key.startswith("kvk_") or len(api_key) > 128 or not api_key.isascii():
            # Checked locally so a mistyped key never reaches the server's invalid-key throttle.
            raise SimulatorRefused("The API key is not a KAVACH ingestion key")
        self.catalog = catalog
        self.transport = transport
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.clock = clock
        self.pacer = pacer
        self.seed = seed
        self.run_id = run_id
        self.sleep = pacer.sleep

    def run(self, scenario_ids: Sequence[str]) -> RunReport:
        scenarios = [self.catalog.scenario(s) for s in scenario_ids]
        planned = sum(len(s.steps) for s in scenarios)
        if planned > MAX_SUBMISSIONS_PER_RUN:
            raise SimulatorRefused(
                f"{planned} submissions exceed the {MAX_SUBMISSIONS_PER_RUN}-per-run safeguard"
            )
        report = RunReport(self.run_id, self.seed, self.catalog.catalog_version, dry_run=False)
        for scenario in scenarios:
            self.pacer.make_room(len(scenario.steps))
            started = time.monotonic()
            steps = plan_scenario(
                scenario,
                self.catalog.source,
                seed=self.seed,
                run_id=self.run_id,
                anchor=self.clock(),
            )
            result = ScenarioResult(
                scenario.id,
                scenario.version,
                scenario.name,
                scenario.truth,
                list(scenario.provisional),
                [result_for(step) for step in steps],
            )
            report.scenarios.append(result)
            try:
                self._run_steps(steps, result, report)
            except RunAborted as abort:
                report.aborted = abort.reason
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            if report.aborted:
                break
        return report

    def _run_steps(
        self, steps: list[PlannedStep], result: ScenarioResult, report: RunReport
    ) -> None:
        receipts: dict[str, StepResult] = {}
        for index, (planned, outcome) in enumerate(zip(steps, result.steps, strict=True)):
            if planned.of is not None and planned.of not in receipts:
                outcome.skipped = True
                outcome.failures.append(f"skipped: step {planned.of} was not stored")
                continue
            try:
                self._submit(planned, outcome, report)
                self._check(planned, outcome, receipts)
            except RunAborted:
                for later in result.steps[index + 1 :]:
                    later.skipped = True
                raise

    def _submit(self, planned: PlannedStep, outcome: StepResult, report: RunReport) -> None:
        body = json.dumps(planned.payload).encode()
        headers = self._headers | {"Content-Type": "application/json"}
        while True:
            if report.submissions >= MAX_SUBMISSIONS_PER_RUN:
                raise RunAborted("submission safeguard reached")
            self.pacer.make_room(1)
            self.pacer.record()
            report.submissions += 1
            response = self._send("POST", f"{EVENTS_PATH}/{planned.kind}", headers, body, outcome)
            if response.status != 429 or outcome.rate_limit_retries >= MAX_RATE_LIMIT_RETRIES:
                break
            # Rejected before the body was read: resending the same payload is safe.
            outcome.rate_limit_retries += 1
            self.sleep(retry_after(response))
        outcome.status = response.status
        outcome.code = error_code(response) if response.status >= 400 else None
        data = receipt_data(response) if response.status < 300 else {}
        outcome.receipt_id = data.get("event_id")
        outcome.replayed = data.get("replayed")
        outcome.analysis_status = data.get("analysis_status")
        outcome.warnings = list(data.get("warnings") or [])
        abort_on(outcome, planned.expect)
        if response.status == 201 and response.headers.get("location") != (
            f"{EVENTS_PATH}/{outcome.receipt_id}"
        ):
            outcome.failures.append("201 without the receipt Location")

    def _send(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes | None,
        outcome: StepResult,
    ) -> HttpResult:
        try:
            return self.transport.request(method, path, headers, body)
        except TargetUnreachable:
            outcome.failures.append("connection failed; outcome unknown (retry with same IDs)")
            raise RunAborted("target unreachable") from None

    def _check(self, planned: PlannedStep, outcome: StepResult, receipts: dict[str, str]) -> None:
        expect = planned.expect
        if (outcome.status, outcome.code) != (expect.status, expect.code):
            outcome.failures.append(
                f"expected {expect.status} {expect.code or ''}".rstrip()
                + f", got {outcome.status} {outcome.code or ''}".rstrip()
            )
            if expect.status == 201 and outcome.status in (200, 409):
                outcome.failures.append("this run ID was used before; choose a new --run-id")
            return
        if expect.status == 201:
            if outcome.replayed is not False:
                outcome.failures.append("a new event must not be a replay")
            self._check_analysis(planned, outcome)
            if outcome.receipt_id:
                receipts[planned.step] = outcome
                self._check_receipt(planned, outcome, outcome)
        elif expect.status == 200:
            original = receipts[planned.of or ""]
            if outcome.replayed is not True or outcome.receipt_id != original.receipt_id:
                outcome.failures.append("a replay must return the original receipt")
            # A replay repeats the stored result exactly; it never re-runs the model.
            if (outcome.analysis_status, outcome.warnings) != (
                original.analysis_status,
                original.warnings,
            ):
                outcome.failures.append("a replay must repeat the original analysis result")
            self._check_analysis(planned, outcome)
        elif expect.status == 409:
            # The original event must be untouched by the rejected reuse of its ID.
            self._check_receipt(planned, outcome, receipts[planned.of or ""])

    def _check_analysis(self, planned: PlannedStep, outcome: StepResult) -> None:
        found = (outcome.analysis_status, tuple(outcome.warnings))
        if found in ALLOWED_ANALYSIS[planned.kind]:
            return
        if planned.kind == "call" or outcome.analysis_status != "complete":
            outcome.failures.append("analysis must be unavailable while no model is deployed")
            outcome.failures.append("every model stage must be reported unavailable")
        else:
            outcome.failures.append("SMS model evidence must be marked uncalibrated")

    def _check_receipt(
        self, planned: PlannedStep, outcome: StepResult, original: StepResult
    ) -> None:
        """Receipt reads go through GET /events/{id} (not counted by the submission limit).
        The stored receipt must match what the original submission returned."""
        receipt_id = original.receipt_id or ""
        response = self._send("GET", f"{EVENTS_PATH}/{receipt_id}", self._headers, None, outcome)
        if response.status in (401, 429) or response.status >= 500:
            outcome.failures.append(f"receipt lookup returned {response.status}")
            raise RunAborted(f"receipt lookup returned {response.status}")
        data = receipt_data(response)
        wanted = {
            "event_id": receipt_id,
            "external_event_id": planned.external_event_id,
            "source": planned.payload["source"],
            "kind": planned.kind,
            "analysis_status": original.analysis_status,
            "warnings": original.warnings,
        }
        if response.status != 200 or {k: data.get(k) for k in RECEIPT_FIELDS} != wanted:
            outcome.failures.append("stored receipt does not match")
        elif data.get("replayed") is not False:
            outcome.failures.append("a receipt lookup is never a replay")


def result_for(planned: PlannedStep) -> StepResult:
    return StepResult(
        planned.step,
        planned.action,
        planned.kind,
        planned.external_event_id,
        planned.expect.status,
        planned.expect.code,
    )


def retry_after(response: HttpResult) -> float:
    try:
        seconds = int(response.headers.get("retry-after", "1"))
    except ValueError:
        seconds = 1
    return float(min(max(seconds, 1), MAX_RETRY_AFTER_SECONDS))


def abort_on(outcome: StepResult, expect: Expectation) -> None:
    """Stop the run when continuing could only add failed or unsafe requests."""
    status = outcome.status or 0
    if status == expect.status:
        return
    reasons = {
        401: "the API key was rejected (expired, revoked or unknown)",
        403: "the API key is not scoped to the catalog source",
        429: "rate limited after retries",
    }
    reason = reasons.get(status) or (f"server returned {status}" if status >= 500 else None)
    if reason:
        outcome.failures.append(f"got {status} {outcome.code or ''}".rstrip())
        raise RunAborted(reason)


# --- dry run and reporting ---------------------------------------------------------------


def dry_run(
    catalog: ScenarioCatalog,
    scenario_ids: Sequence[str],
    *,
    seed: int,
    run_id: str,
    anchor: datetime,
) -> tuple[RunReport, list[PlannedStep]]:
    """The plan only: no key, no network."""
    report = RunReport(run_id, seed, catalog.catalog_version, dry_run=True)
    planned: list[PlannedStep] = []
    for scenario_id in scenario_ids:
        scenario = catalog.scenario(scenario_id)
        steps = plan_scenario(scenario, catalog.source, seed=seed, run_id=run_id, anchor=anchor)
        planned.extend(steps)
        report.scenarios.append(
            ScenarioResult(
                scenario.id,
                scenario.version,
                scenario.name,
                scenario.truth,
                list(scenario.provisional),
                [result_for(step) for step in steps],
            )
        )
    return report, planned


def describe_plan(planned: Sequence[PlannedStep]) -> list[str]:
    lines = []
    for step in planned:
        expect = step.expect
        timing = f"t{step.offset_seconds:+d}s"
        index = "" if expect.indexed is None else f" indexed={expect.indexed} late={expect.late}"
        lines.append(
            f"  {step.scenario_id} {step.step:<13} {step.action:<8} {step.kind:<4} "
            f"{step.external_event_id:<34} subscriber={step.subscriber:<6} {timing:<8} "
            f"expect={expect.status}{' ' + expect.code if expect.code else ''}{index}"
            f"  truth={step.truth} (simulation-only)"
        )
    return lines


def report_lines(report: RunReport) -> list[str]:
    mode = "DRY RUN (nothing sent)" if report.dry_run else "run"
    lines = [
        f"KAVACH simulator {mode}: run_id={report.run_id} seed={report.seed} "
        f"catalog_version={report.catalog_version} (synthetic data only)"
    ]
    if report.dry_run:
        return lines
    for scenario in report.scenarios:
        verdict = "PASS" if scenario.passed else "FAIL"
        provisional = f" [provisional: {', '.join(scenario.provisional)}]"
        lines.append(
            f"{verdict} {scenario.scenario_id} v{scenario.version} {scenario.name}"
            f"{provisional if scenario.provisional else ''} ({scenario.elapsed_seconds:.2f}s)"
        )
        for step in scenario.steps:
            state = "skipped" if step.skipped else ("ok" if step.passed else "FAIL")
            got = f"{step.status} {step.code or ''}".rstrip() if step.status else "-"
            extras = []
            if step.receipt_id:
                extras.append(f"receipt={step.receipt_id}")
            if step.replayed is not None:
                extras.append(f"replayed={str(step.replayed).lower()}")
            if step.warnings:
                extras.append("warnings=" + ",".join(step.warnings))
            if step.rate_limit_retries:
                extras.append(f"rate_limit_retries={step.rate_limit_retries}")
            lines.append(
                f"    {state:<7} {step.step:<13} {step.kind:<4} {step.external_event_id} "
                f"-> {got} {' '.join(extras)}".rstrip()
            )
            lines.extend(f"            {failure}" for failure in step.failures)
    passed = sum(s.passed for s in report.scenarios)
    lines.append(
        f"Summary: {passed}/{len(report.scenarios)} scenarios passed, "
        f"{report.submissions} submissions"
        + (f"; ABORTED: {report.aborted}" if report.aborted else "")
    )
    lines.append(
        "Ground-truth labels are simulation-only; any SMS model evidence is uncalibrated "
        "and no risk conclusion was drawn."
    )
    return lines


def report_dict(report: RunReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "seed": report.seed,
        "catalog_version": report.catalog_version,
        "dry_run": report.dry_run,
        "passed": report.passed,
        "aborted": report.aborted,
        "submissions": report.submissions,
        "scenarios": [
            {
                "id": s.scenario_id,
                "version": s.version,
                "name": s.name,
                "truth": s.truth,
                "provisional": s.provisional,
                "passed": s.passed,
                "elapsed_seconds": s.elapsed_seconds,
                "steps": [
                    {
                        "step": step.step,
                        "action": step.action,
                        "kind": step.kind,
                        "external_event_id": step.external_event_id,
                        "expected_status": step.expected_status,
                        "expected_code": step.expected_code,
                        "status": step.status,
                        "code": step.code,
                        "receipt_id": step.receipt_id,
                        "replayed": step.replayed,
                        "analysis_status": step.analysis_status,
                        "warnings": step.warnings,
                        "rate_limit_retries": step.rate_limit_retries,
                        "skipped": step.skipped,
                        "failures": step.failures,
                    }
                    for step in s.steps
                ],
            }
            for s in report.scenarios
        ],
    }
