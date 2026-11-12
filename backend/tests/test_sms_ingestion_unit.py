"""M4-I.2 service-free checks: signals v2, receipt warnings, worker settings and construction."""

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from kavach.core.config import Settings
from kavach.main import build_sms_worker
from kavach.models.sms_worker import SmsInferenceResult, SmsModelEvidence
from kavach.services.ingestion import (
    SMS_POLICY_VERSION,
    check_sms_signals,
    sms_analysis,
    warnings_from,
)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
EVIDENCE = SmsModelEvidence(
    model_version="horizon-phishing-scam-base@fa686fc0d6a3+m1:abcdef012345",
    labels={"legitimate": 0.0133, "spam": 0.0097, "fraud": 0.9771},
    top_label="fraud",
    truncated=False,
)
COMPLETE = SmsInferenceResult("complete", None, EVIDENCE, 33, 0, 35)


def test_completed_inference_stores_native_uncalibrated_evidence_and_no_risk() -> None:
    analysis = sms_analysis(COMPLETE)
    stage = analysis.signals["stages"]["sms_classifier"]
    assert analysis.signals["schema_version"] == 2
    assert stage == {
        "status": "complete",
        "reason": None,
        "duration_ms": 33,
        "model_output": {
            "labels": {"legitimate": 0.0133, "spam": 0.0097, "fraud": 0.9771},
            "top_label": "fraud",
            "score_semantics": "uncalibrated_softmax",
            "truncated": False,
        },
    }
    assert analysis.signals["reason_codes"] == ["sms_model_uncalibrated"]
    assert analysis.model_versions == {"sms_classifier": EVIDENCE.model_version}
    assert analysis.analysis_status == "complete"
    # The assessment knows the model ran, but there is still no calibrated base signal.
    assert analysis.assessment_status == "partial"
    assert analysis.assessment_reasons == ["sms_model_uncalibrated", "no_calibrated_base_signal"]
    assert analysis.policy_version == SMS_POLICY_VERSION
    flat = repr(analysis)
    for forbidden in ("sms_score", "tier", "probability", "risk"):
        assert forbidden not in flat
    assert warnings_from(analysis.signals) == ["SMS_SCORE_UNCALIBRATED"]


@pytest.mark.parametrize(
    "reason",
    [
        "model_unverified",
        "worker_unavailable",
        "inference_timeout",
        "worker_crashed",
        "invalid_model_output",
        "deadline_exhausted",
    ],
)
def test_failed_inference_is_stored_unavailable_with_its_reason_and_no_evidence(reason) -> None:
    analysis = sms_analysis(SmsInferenceResult("unavailable", reason, None, None, 0, 5))
    assert analysis.signals["stages"] == {
        "sms_classifier": {"status": "unavailable", "reason": reason, "duration_ms": 0}
    }
    assert analysis.analysis_status == "unavailable" and analysis.model_versions == {}
    assert analysis.assessment_reasons == ["no_base_signal_available"]
    assert warnings_from(analysis.signals) == ["SMS_CLASSIFIER_UNAVAILABLE"]


def test_a_rejected_result_can_never_be_stored() -> None:
    with pytest.raises(ValueError):
        sms_analysis(SmsInferenceResult("rejected", "inference_saturated", None, None, 0, 0))


def mutated(change) -> dict[str, Any]:
    signals = copy.deepcopy(sms_analysis(COMPLETE).signals)
    change(signals)
    return signals


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(text="raw message"),
        lambda s: s["stages"]["sms_classifier"].update(text="raw message"),
        lambda s: s["stages"]["sms_classifier"]["model_output"].update(tokens=[1, 2]),
        lambda s: s["stages"]["sms_classifier"]["model_output"].update(
            score_semantics="calibrated_probability"
        ),
        lambda s: s["stages"]["sms_classifier"]["model_output"]["labels"].update(fraud="high"),
        lambda s: s["stages"]["sms_classifier"]["model_output"]["labels"].update(fraud=1.5),
        lambda s: s["stages"]["sms_classifier"]["model_output"].update(top_label="phishing"),
        lambda s: s["stages"].update(voice_intent={"status": "complete"}),
        lambda s: s.update(schema_version=1),
    ],
)
def test_the_signals_allowlist_rejects_anything_extra(change) -> None:
    with pytest.raises(ValueError):
        check_sms_signals(mutated(change))


def test_existing_version_one_receipts_are_unchanged() -> None:
    v1 = {
        "schema_version": 1,
        "stages": {
            "sms_classifier": {
                "status": "unavailable",
                "reason": "model_not_deployed",
                "duration_ms": 0,
            }
        },
        "reason_codes": [],
    }
    assert warnings_from(v1) == ["SMS_CLASSIFIER_UNAVAILABLE"]


# --- settings and construction ---------------------------------------------------------------


def worker_settings(tmp_path: Path, **override: Any) -> dict[str, Any]:
    return {
        "sms_worker_enabled": True,
        "sms_model_authorization": "experimental-local-unvalidated",
        "sms_worker_python": Path(sys.executable),
        "model_dir": tmp_path,
        "model_manifest_path": MANIFEST,
    } | override


def ingestion_env(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "x" * 40
    for name, value in {
        "APP_ORIGIN": "http://localhost:8000",
        "DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:5/db",
        "REDIS_URL": "redis://127.0.0.1:6/0",
        "RATE_LIMIT_HMAC_KEY": secret,
        "AUDIT_HMAC_KEYS": f'{{"v1": "{secret}"}}',
        "AUDIT_HMAC_ACTIVE_VERSION": "v1",
        "SUBSCRIBER_HMAC_KEYS": f'{{"v1": "{secret}"}}',
        "SUBSCRIBER_HMAC_ACTIVE_VERSION": "v1",
        "PAYLOAD_HMAC_KEYS": f'{{"v1": "{secret}"}}',
        "PAYLOAD_HMAC_ACTIVE_VERSION": "v1",
    }.items():
        monkeypatch.setenv(name, value)


def test_the_worker_is_off_by_default_and_needs_no_ml_dependency() -> None:
    settings = Settings()
    assert settings.sms_worker_enabled is False
    supervisor = build_sms_worker(settings)
    assert supervisor.state == "disabled" and supervisor.status()["public_state"] == "disabled"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"model_dir": None}, "requires: MODEL_DIR"),
        ({"model_manifest_path": Path("relative.json")}, "absolute"),
        ({"sms_inference_timeout_ms": 10_000, "inference_timeout_seconds": 11.0}, "commit reserve"),
        ({"inference_device": "mps"}, "inference_device"),
        ({"max_inflight_analyses": 3}, "max_inflight_analyses"),
    ],
)
def test_invalid_worker_settings_refuse_to_load(tmp_path, monkeypatch, override, message) -> None:
    ingestion_env(monkeypatch)
    with pytest.raises(ValidationError, match=message):
        Settings(**worker_settings(tmp_path, **override))


def test_the_worker_requires_the_ingestion_configuration(tmp_path) -> None:
    with pytest.raises(ValidationError, match="event ingestion"):
        Settings(**worker_settings(tmp_path))


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"model_manifest_path": Path("/nonexistent/manifest.json")}, "manifest_invalid"),
        ({"sms_worker_python": Path("/nonexistent/python")}, "worker_python_missing"),
        ({"model_dir": Path("/nonexistent/models")}, "model_dir_missing"),
    ],
)
def test_unusable_worker_paths_make_the_model_unverified_outside_pilot(
    tmp_path, monkeypatch, override, code
) -> None:
    ingestion_env(monkeypatch)
    supervisor = build_sms_worker(Settings(**worker_settings(tmp_path, **override)))
    assert supervisor.state == "unverified" and supervisor.status()["fatal_code"] == code
    result = supervisor.classify("FICTIONAL DEMO: hello", 1e12)
    assert (result.outcome, result.reason, result.evidence) == (
        "unavailable",
        "model_unverified",
        None,
    )


def test_the_worker_needs_the_explicit_experimental_authorization(tmp_path, monkeypatch) -> None:
    ingestion_env(monkeypatch)
    with pytest.raises(ValidationError, match="SMS_MODEL_AUTHORIZATION"):
        Settings(**worker_settings(tmp_path, sms_model_authorization=None))
    with pytest.raises(ValidationError, match="sms_model_authorization"):
        Settings(**worker_settings(tmp_path, sms_model_authorization="validated"))


@pytest.mark.parametrize(
    ("app_env", "origin"),
    [("pilot", "https://kavach.example"), ("development", "https://kavach.example")],
)
def test_experimental_analysis_is_local_development_only(
    tmp_path, monkeypatch, app_env, origin
) -> None:
    ingestion_env(monkeypatch)
    monkeypatch.setenv("APP_ORIGIN", origin)
    with pytest.raises(ValidationError, match="loopback APP_ORIGIN"):
        Settings(app_env=app_env, **worker_settings(tmp_path))


def test_pilot_refuses_to_start_with_an_unusable_worker(tmp_path, monkeypatch) -> None:
    # No pilot authorization exists yet (the experiment is local-only), so the settings are built
    # without validation to keep the fail-closed pilot path covered for a future authorized mode.
    ingestion_env(monkeypatch)
    valid = Settings(**worker_settings(tmp_path))
    settings = valid.model_copy(
        update={
            "app_env": "pilot",
            "app_origin": "https://kavach.example",
            "model_manifest_path": Path("/nonexistent/manifest.json"),
        }
    )
    with pytest.raises(RuntimeError, match="manifest_invalid"):
        build_sms_worker(settings)


def test_a_valid_configuration_builds_an_isolated_offline_command(tmp_path, monkeypatch) -> None:
    ingestion_env(monkeypatch)
    supervisor = build_sms_worker(Settings(**worker_settings(tmp_path)))
    config = supervisor.config
    assert config is not None and supervisor.state == "starting"
    assert config.command[1:4] == ("-I", "-m", "kavach_sms_worker")
    assert config.lock_path == tmp_path / ".kavach-sms-worker.lock"
    assert (config.max_inflight, config.inference_timeout_s, config.commit_reserve_s) == (
        2,
        2.0,
        2.0,
    )
    assert not any("secret" in part or "postgresql" in part for part in config.command)


def test_a_short_configured_timeout_is_still_a_real_timeout_not_deadline_exhausted(
    tmp_path, monkeypatch
) -> None:
    ingestion_env(monkeypatch)
    supervisor = build_sms_worker(
        Settings(**worker_settings(tmp_path, sms_inference_timeout_ms=100))
    )
    config = supervisor.config
    assert config is not None
    assert config.inference_timeout_s == 0.1 and config.min_budget_s <= config.inference_timeout_s
    default = build_sms_worker(Settings(**worker_settings(tmp_path)))
    assert default.config is not None and default.config.min_budget_s == 0.25
