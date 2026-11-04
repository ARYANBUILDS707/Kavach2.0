"""Service-free M3.3 checks: catalog validation, deterministic planning, target and key
restrictions, pacing, 429/401/503 handling, redaction and the catalog endpoint's gates."""

import io
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kavach.api.schemas.events import CallEvent, SMSEvent
from kavach.core.config import Settings
from kavach.main import create_app
from kavach.simulator import cli
from kavach.simulator.catalog import CATALOG_FILE, ScenarioCatalog, load_catalog, parse_catalog
from kavach.simulator.runner import (
    MAX_SUBMISSIONS_PER_RUN,
    HttpResult,
    Pacer,
    Runner,
    SimulatorRefused,
    plan_scenario,
    validate_target,
)

ANCHOR = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
KEY = "kvk_" + "Q" * 43


def raw_catalog() -> dict[str, Any]:
    from importlib.resources import files

    return json.loads((files("kavach.simulator") / CATALOG_FILE).read_bytes())


def with_scenario(**changes: Any) -> bytes:
    data = raw_catalog()
    data["scenarios"] = [data["scenarios"][0] | changes]
    return json.dumps(data).encode()


def sms_step(**changes: Any) -> dict[str, Any]:
    step = {
        "action": "submit",
        "step": "sms",
        "kind": "sms",
        "subscriber": "alpha",
        "offset_seconds": -60,
        "text": "[SIMULATED] A fictional notice.",
        "truth": "legitimate_sms",
        "expect": {"status": 201, "indexed": True, "late": False},
    }
    return step | changes


REPLAY_OF_UNKNOWN_STEP = {"action": "replay", "step": "r", "of": "x", "expect": {"status": 200}}


# --- catalog -------------------------------------------------------------------------------


def test_shipped_catalog_is_valid_complete_and_synthetic() -> None:
    catalog = load_catalog()
    assert catalog.synthetic is True and catalog.source == "simulator"
    assert [s.id for s in catalog.scenarios] == [f"S{n:02d}" for n in range(1, 13)]
    raw = json.dumps(raw_catalog())
    assert "+91" not in raw and "@" not in raw
    for scenario in catalog.scenarios:
        assert scenario.version >= 1 and scenario.description and scenario.expected_summary


def test_catalog_expectations_match_d05_and_are_labeled_provisional() -> None:
    catalog = load_catalog()
    assert catalog.scenario("S10").provisional == ["D05"]
    s10 = {s.step: s.expect for s in catalog.scenario("S10").steps}
    assert (s10["sms_stale"].indexed, s10["sms_stale"].late) == (False, True)
    assert (s10["sms_early"].indexed, s10["sms_early"].late) == (True, True)
    assert [p.linked for p in catalog.scenario("S10").candidate_pairs] == [False, True]
    assert catalog.scenario("S06").candidate_pairs[0].linked is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"steps": [sms_step(expect={"status": 200})]}, "must expect"),
        ({"steps": [sms_step(text="Not marked as synthetic")]}, "SIMULATED"),
        ({"steps": [sms_step(text="[SIMULATED] call 98765432 now")]}, "digit runs"),
        ({"steps": [sms_step(text="[SIMULATED] see https://bank.example.com/x")]}, ".invalid"),
        ({"steps": [sms_step(offset_seconds=-590)]}, "too close"),
        ({"steps": [sms_step(offset_seconds=-2350)]}, "too close"),
        ({"steps": [sms_step(offset_seconds=-900)]}, "indexed/late"),
        ({"steps": [sms_step(offset_seconds=30)]}, "less than or equal"),
        ({"steps": [sms_step(), sms_step()]}, "duplicate step"),
        ({"steps": [sms_step(source="other-feed")]}, "must expect"),
        ({"steps": [sms_step(extra="field")]}, "Extra inputs"),
        ({"steps": [sms_step(kind="call")]}, "a call has no text"),
        (
            {"steps": [sms_step(), REPLAY_OF_UNKNOWN_STEP]},
            "must follow",
        ),
        (
            {
                "steps": [
                    sms_step(),
                    {
                        "action": "conflict",
                        "step": "c",
                        "of": "sms",
                        "text": "[SIMULATED] A fictional notice.",
                        "expect": {"status": 409, "code": "EVENT_ID_CONFLICT"},
                    },
                ]
            },
            "must change",
        ),
        (
            {
                "steps": [sms_step(), sms_step(step="b", subscriber="bravo")],
                "candidate_pairs": [{"between": ["sms", "b"], "linked": True}],
                "provisional": ["D05"],
            },
            "mislabeled",
        ),
        (
            {
                "steps": [sms_step(), sms_step(step="b")],
                "candidate_pairs": [{"between": ["sms", "b"], "linked": True}],
            },
            "D05",
        ),
        ({"steps": [sms_step(step=f"s{n}") for n in range(11)]}, "at most 10"),
    ],
)  # fmt: skip
def test_invalid_catalogs_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_catalog(with_scenario(**changes))


def test_audio_references_must_expect_rejection_while_no_manifest_exists() -> None:
    step = sms_step(kind="call", text=None, audio_reference="sim_sample_x", truth="legitimate_call")
    step.pop("text")
    with pytest.raises(ValidationError, match="must expect"):
        parse_catalog(with_scenario(steps=[step]))
    step["expect"] = {"status": 422, "code": "UNKNOWN_AUDIO_REFERENCE"}
    assert parse_catalog(with_scenario(steps=[step])).scenarios[0].steps[0].expect.status == 422


def test_oversized_catalog_is_rejected() -> None:
    with pytest.raises(ValueError, match="too large"):
        parse_catalog(b" " * (64 * 1024 + 1))


# --- planning ------------------------------------------------------------------------------


def plan_all(seed: int, run_id: str) -> list[Any]:
    catalog = load_catalog()
    return [
        step
        for scenario in catalog.scenarios
        for step in plan_scenario(scenario, catalog.source, seed=seed, run_id=run_id, anchor=ANCHOR)
    ]


def test_plans_are_deterministic_for_a_seed_and_run_id() -> None:
    first, second = plan_all(7, "abc123"), plan_all(7, "abc123")
    assert [s.payload for s in first] == [s.payload for s in second]
    other_seed = plan_all(8, "abc123")
    other_run = plan_all(7, "abc124")
    assert [s.external_event_id for s in other_seed] == [s.external_event_id for s in first]
    assert {s.payload["subscriber_token"] for s in other_seed}.isdisjoint(
        {s.payload["subscriber_token"] for s in first}
    )
    assert {s.external_event_id for s in other_run}.isdisjoint({s.external_event_id for s in first})


def test_planned_payloads_are_valid_api_requests_without_labels() -> None:
    catalog = load_catalog()
    by_scenario: dict[str, list[Any]] = {}
    for step in plan_all(0, "run1"):
        by_scenario.setdefault(step.scenario_id, []).append(step)
        model = SMSEvent if step.kind == "sms" else CallEvent
        event = model.model_validate(step.payload, context={"now": ANCHOR})
        assert event.timestamp == ANCHOR + timedelta(seconds=step.offset_seconds)
        assert set(step.payload) <= {
            "event_id", "subscriber_token", "timestamp", "source", "text", "sender_id",
            "audio_reference",
        }  # fmt: skip
        assert step.truth not in json.dumps(step.payload)
    s05 = {s.step: s.payload for s in by_scenario["S05"]}
    assert s05["sms"]["subscriber_token"] == s05["call"]["subscriber_token"]
    s06 = {s.step: s.payload for s in by_scenario["S06"]}
    assert s06["sms"]["subscriber_token"] != s06["call"]["subscriber_token"]
    s08 = by_scenario["S08"]
    assert s08[0].payload == s08[1].payload
    s09 = by_scenario["S09"]
    assert s09[0].external_event_id == s09[1].external_event_id
    assert s09[0].payload["text"] != s09[1].payload["text"]
    assert by_scenario["S11"][0].payload["source"] == "partner-feed"
    assert all(s.payload["source"] == catalog.source for s in by_scenario["S01"])


@pytest.mark.parametrize("run_id", ["", "UPPER", "a" * 17, "has-dash", "../x"])
def test_run_ids_are_restricted(run_id: str) -> None:
    with pytest.raises(SimulatorRefused):
        plan_all(0, run_id)


# --- target --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8000", "http://localhost:8000/", "https://[::1]:8443", "http://127.0.0.1"],
)
def test_loopback_targets_are_accepted(url: str) -> None:
    assert validate_target(url).host in {"127.0.0.1", "localhost", "::1"}


@pytest.mark.parametrize(
    "url",
    [
        "http://kavach.example.com",
        "https://10.0.0.5:8000",
        "http://0.0.0.0:8000",
        "http://127.0.0.1.attacker.invalid:8000",
        "http://localhost.attacker.invalid",
        "http://user:pw@127.0.0.1:8000",
        "http://127.0.0.1:8000/api",
        "http://127.0.0.1:8000?x=1",
        "ftp://127.0.0.1",
        "127.0.0.1:8000",
        "http://127.0.0.1:99999",
    ],
)
def test_other_targets_are_refused(url: str) -> None:
    with pytest.raises(SimulatorRefused):
        validate_target(url)


# --- runner with a scripted transport --------------------------------------------------------


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class ScriptedServer:
    """Answers like the M3 contract; `override` can replace any submission response."""

    def __init__(self, override: Callable[[int, dict[str, Any]], HttpResult | None] = None) -> None:
        self.override = override
        self.stored: dict[tuple[str, str], tuple[str, str]] = {}  # -> (uuid, payload json)
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.submissions = 0

    def request(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes | None
    ) -> HttpResult:
        self.requests.append((method, path, dict(headers), body))
        if method == "GET":
            uuid = path.rsplit("/", 1)[1]
            for (source, external), (stored_id, payload) in self.stored.items():
                if stored_id == uuid:
                    kind = json.loads(payload)["kind"]
                    return ok(200, receipt(stored_id, external, source, kind, replayed=False))
            return error(404, "NOT_FOUND")
        self.submissions += 1
        payload = json.loads(body or b"{}")
        if self.override and (answer := self.override(self.submissions, payload)):
            return answer
        kind = path.rsplit("/", 1)[1]
        if payload["source"] != "simulator":
            return error(403, "FORBIDDEN")
        if payload.get("audio_reference"):
            return error(422, "UNKNOWN_AUDIO_REFERENCE")
        canonical = json.dumps(payload | {"kind": kind}, sort_keys=True)
        existing = self.stored.get(("simulator", payload["event_id"]))
        if existing:
            if existing[1] != canonical:
                return error(409, "EVENT_ID_CONFLICT")
            return ok(200, receipt(existing[0], payload["event_id"], "simulator", kind, True))
        event_id = str(uuid4())
        self.stored[("simulator", payload["event_id"])] = (event_id, canonical)
        result = ok(201, receipt(event_id, payload["event_id"], "simulator", kind, False))
        return HttpResult(201, {"location": f"/api/v1/events/{event_id}"}, result.body)


def receipt(event_id: str, external: str, source: str, kind: str, replayed: bool) -> dict:
    return {
        "event_id": event_id,
        "external_event_id": external,
        "source": source,
        "kind": kind,
        "analysis_status": "unavailable",
        "received_at": ANCHOR.isoformat(),
        "processing_ms": 3,
        "replayed": replayed,
        "warnings": (
            ["SMS_CLASSIFIER_UNAVAILABLE"]
            if kind == "sms"
            else ["SYNTHESIS_UNAVAILABLE", "TRANSCRIPTION_UNAVAILABLE", "VOICE_INTENT_UNAVAILABLE"]
        ),
    }


def ok(status: int, data: dict) -> HttpResult:
    return HttpResult(status, {}, json.dumps({"data": data, "request_id": str(uuid4())}).encode())


def error(status: int, code: str, headers: dict[str, str] | None = None) -> HttpResult:
    body = {"error": {"code": code, "message": "x"}, "request_id": str(uuid4())}
    return HttpResult(status, headers or {}, json.dumps(body).encode())


def make_runner(server: ScriptedServer, fake: FakeTime, per_minute: int = 20) -> Runner:
    pacer = Pacer(per_minute, monotonic=fake.monotonic, sleep=fake.sleep)
    return Runner(
        load_catalog(), server, KEY, clock=lambda: ANCHOR, pacer=pacer, seed=0, run_id="unit1"
    )


def all_ids() -> list[str]:
    return [s.id for s in load_catalog().scenarios]


def test_full_catalog_passes_against_a_contract_conformant_server() -> None:
    server, fake = ScriptedServer(), FakeTime()
    report = make_runner(server, fake).run(all_ids())
    assert report.passed, report
    assert report.submissions == server.submissions == 20
    statuses = {(s.scenario_id, st.step): st.status for s in report.scenarios for st in s.steps}
    assert statuses[("S08", "retry")] == 200 and statuses[("S09", "altered")] == 409
    assert statuses[("S11", "sms")] == 403 and statuses[("S12", "call")] == 422


def test_rerunning_the_same_run_id_is_reported_not_hidden() -> None:
    server, fake = ScriptedServer(), FakeTime()
    make_runner(server, fake).run(["S01"])
    again = make_runner(server, fake).run(["S01"])
    step = again.scenarios[0].steps[0]
    assert not again.passed and step.status == 200 and step.replayed is True
    assert "this run ID was used before; choose a new --run-id" in step.failures


def test_pacing_stays_under_the_per_key_limit_and_reserves_whole_scenarios() -> None:
    server, fake = ScriptedServer(), FakeTime()
    sent_at: list[float] = []
    original = server.request

    def timed(method: str, path: str, headers: Mapping[str, str], body: bytes | None) -> HttpResult:
        if method == "POST":
            sent_at.append(fake.now)
        return original(method, path, headers, body)

    server.request = timed  # type: ignore[method-assign]
    report = make_runner(server, fake, per_minute=5).run(all_ids())
    assert report.passed
    for index, moment in enumerate(sent_at):
        assert sum(moment - 60 < t <= moment for t in sent_at[: index + 1]) <= 5
    assert fake.slept  # it had to wait


@pytest.mark.parametrize("per_minute", [0, 31])
def test_pacing_cannot_exceed_the_server_limit(per_minute: int) -> None:
    with pytest.raises(SimulatorRefused):
        Pacer(per_minute)


def test_429_honors_retry_after_and_resends_the_same_payload() -> None:
    def limited(count: int, payload: dict) -> HttpResult | None:
        return error(429, "RATE_LIMITED", {"retry-after": "7"}) if count == 1 else None

    server, fake = ScriptedServer(limited), FakeTime()
    report = make_runner(server, fake).run(["S01"])
    assert report.passed and report.scenarios[0].steps[0].rate_limit_retries == 1
    assert 7 in fake.slept
    posts = [body for method, _, _, body in server.requests if method == "POST"]
    assert posts[0] == posts[1]


def test_persistent_429_aborts_after_bounded_retries() -> None:
    server, fake = (
        ScriptedServer(lambda n, p: error(429, "RATE_LIMITED", {"retry-after": "999"})),
        FakeTime(),
    )
    report = make_runner(server, fake).run(all_ids())
    assert report.aborted == "rate limited after retries" and server.submissions == 3
    assert max(fake.slept) == 60  # Retry-After is capped


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [
        (401, "INVALID_CREDENTIALS", "the API key was rejected (expired, revoked or unknown)"),
        (403, "FORBIDDEN", "the API key is not scoped to the catalog source"),
        (503, "DEPENDENCY_UNAVAILABLE", "server returned 503"),
        (500, "INTERNAL_ERROR", "server returned 500"),
    ],
)
def test_the_run_stops_at_the_first_unsafe_failure(status: int, code: str, reason: str) -> None:
    server, fake = ScriptedServer(lambda n, p: error(status, code)), FakeTime()
    report = make_runner(server, fake).run(all_ids())
    assert report.aborted == reason and not report.passed
    assert server.submissions == 1 and len(server.requests) == 1
    assert len(report.scenarios) == 1


def test_unreachable_target_aborts_without_retrying() -> None:
    from kavach.simulator.runner import TargetUnreachable

    class Down:
        calls = 0

        def request(self, *args: Any) -> HttpResult:
            Down.calls += 1
            raise TargetUnreachable

    fake = FakeTime()
    runner = Runner(
        load_catalog(), Down(), KEY, clock=lambda: ANCHOR,
        pacer=Pacer(20, monotonic=fake.monotonic, sleep=fake.sleep), seed=0, run_id="down1",
    )  # fmt: skip
    report = runner.run(all_ids())
    assert report.aborted == "target unreachable" and Down.calls == 1


def test_wrong_receipt_or_scores_fail_the_scenario() -> None:
    def scored(count: int, payload: dict) -> HttpResult | None:
        data = receipt(str(uuid4()), payload["event_id"], "simulator", "sms", False)
        data |= {"analysis_status": "complete", "warnings": []}
        return HttpResult(
            201, {"location": f"/api/v1/events/{data['event_id']}"}, ok(201, data).body
        )

    report = make_runner(ScriptedServer(scored), FakeTime()).run(["S01"])
    failures = report.scenarios[0].steps[0].failures
    assert "analysis must be unavailable while no model is deployed" in failures
    assert "stored receipt does not match" in failures


def test_submission_cap_refuses_oversized_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    import kavach.simulator.runner as runner_module

    monkeypatch.setattr(runner_module, "MAX_SUBMISSIONS_PER_RUN", 3)
    with pytest.raises(SimulatorRefused, match="safeguard"):
        make_runner(ScriptedServer(), FakeTime()).run(all_ids())
    assert MAX_SUBMISSIONS_PER_RUN == 60


@pytest.mark.parametrize("key", ["", "not-a-key", "kvk_" + "x" * 200, "kvk_ü"])
def test_malformed_keys_are_refused_locally(key: str) -> None:
    with pytest.raises(SimulatorRefused):
        Runner(
            load_catalog(),
            ScriptedServer(),
            key,
            clock=lambda: ANCHOR,
            pacer=Pacer(20),
            seed=0,
            run_id="k1",
        )


# --- CLI -----------------------------------------------------------------------------------


def run_cli(
    argv: list[str],
    *,
    stdin: str = "",
    environ: dict[str, str] | None = None,
    server: ScriptedServer | None = None,
) -> tuple[int, str, str, ScriptedServer]:
    server = server or ScriptedServer()
    fake = FakeTime()
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        argv,
        stdin=io.StringIO(stdin),
        out=out,
        err=err,
        environ=environ or {},
        clock=lambda: ANCHOR,
        transport=server,
        pacer=Pacer(20, monotonic=fake.monotonic, sleep=fake.sleep),
    )
    return code, out.getvalue(), err.getvalue(), server


def test_cli_run_reads_the_key_from_the_environment_and_never_prints_secrets() -> None:
    code, out, err, server = run_cli(
        ["run", "--all", "--run-id", "cli1"], environ={cli.KEY_VARIABLE: KEY}
    )
    assert code == 0, out + err
    assert "Summary: 12/12 scenarios passed, 20 submissions" in out
    plans = plan_all(0, "cli1")
    for secret in [KEY, *{s.payload["subscriber_token"] for s in plans}]:
        assert secret not in out + err
    for text in {s.payload.get("text") for s in plans} - {None}:
        assert text not in out + err
    assert all(h["Authorization"] == f"Bearer {KEY}" for _, _, h, _ in server.requests)


def test_cli_json_report_is_redacted_too() -> None:
    code, out, _, _ = run_cli(
        ["run", "--scenario", "S05", "--run-id", "cli2", "--json", "--key-stdin"], stdin=KEY + "\n"
    )
    report = json.loads(out)
    assert code == 0 and report["passed"] and KEY not in out and "SIMULATED" not in out
    assert "sim-cli2-s05-sms" in out  # event IDs only
    assert "subscriber_token" not in out


def test_cli_refuses_without_a_key_or_with_an_external_target() -> None:
    code, _, err, server = run_cli(["run", "--all"])
    assert code == 2 and "KAVACH_SIMULATOR_API_KEY" in err and not server.requests
    code, _, err, server = run_cli(
        ["run", "--all", "--base-url", "https://kavach.example.com"],
        environ={cli.KEY_VARIABLE: KEY},
    )
    assert code == 2 and "loopback" in err and not server.requests
    code, _, err, _ = run_cli(["run", "--scenario", "S99"], environ={cli.KEY_VARIABLE: KEY})
    assert code == 2 and "Unknown scenario" in err


def test_the_key_is_never_an_argument() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--all", "--key", KEY])


def test_dry_run_sends_nothing_and_needs_no_key() -> None:
    code, out, _, server = run_cli(["run", "--all", "--dry-run", "--run-id", "dry1", "--seed", "4"])
    assert code == 0 and not server.requests
    assert "DRY RUN" in out and "sim-dry1-s10-sms-stale" in out
    assert "simulation-only" in out
    for step in plan_all(4, "dry1"):
        assert step.payload["subscriber_token"] not in out
        assert step.payload.get("text") is None or step.payload["text"] not in out


def test_failed_scenarios_exit_1() -> None:
    server = ScriptedServer(lambda n, p: error(422, "VALIDATION_ERROR"))
    code, out, _, _ = run_cli(
        ["run", "--scenario", "S01"], environ={cli.KEY_VARIABLE: KEY}, server=server
    )
    assert code == 1 and "FAIL S01" in out


def test_list_shows_every_scenario() -> None:
    code, out, _, _ = run_cli(["list"])
    assert code == 0 and out.count("\nS") == 12 and "[provisional: D05]" in out


# --- catalog endpoint ---------------------------------------------------------------------


def test_catalog_endpoint_fails_closed_without_authentication_configuration() -> None:
    with TestClient(create_app(Settings(app_env="test"))) as client:
        response = client.get("/api/v1/simulator/scenarios")
    assert response.status_code == 503


def test_catalog_response_model_round_trips_the_catalog() -> None:
    from kavach.api.schemas.simulator import SimulatorCatalog

    catalog = load_catalog()
    dumped = SimulatorCatalog(
        catalog_version=1,
        synthetic=True,
        source="simulator",
        scenarios=catalog.scenarios,
        samples=[],
    ).model_dump(mode="json", exclude={"samples"})
    assert ScenarioCatalog.model_validate_json(json.dumps(dumped)) == catalog
