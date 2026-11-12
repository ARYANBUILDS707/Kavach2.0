"""Regression checks for the pinned Horizon model on fictional fixtures (opt-in, `-m model`).

Needs the same environment as `test_sms_worker_model.py`: `workers/sms/.venv` with the `model`
group and the verified artifacts under MODEL_DIR. Run it offline, for example on macOS:

    sandbox-exec -p '(version 1)(allow default)(deny network-outbound (remote ip))' \\
        uv run --project backend --locked \\
        pytest backend/tests/test_sms_model_fixtures.py -m model -s

Every message was written for this file: invented brands, `.example` links, no real numbers or
people. `intent` is what the author wrote the message to look like, not an audited label. The
test never asserts which class the model predicts; it checks that real inference returns a valid,
deterministic native result and prints the predictions beside the intents
(`SMS_MODEL_FIXTURE_REPORT`). Agreement on nine hand-written messages is a smoke signal, never an
accuracy figure, and nothing here touches the M4-Q sample or any dataset split.
"""

import json
import math
import os
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from kavach.models.manifest import load_manifest
from kavach.models.sms_worker import SmsWorkerConfig, SmsWorkerSupervisor, worker_command

pytestmark = pytest.mark.model

REPO = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
WORKER_PYTHON = REPO / "workers" / "sms" / ".venv" / "bin" / "python"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", REPO / "data" / "models"))
LABELS = {"legitimate", "spam", "fraud"}

FIXTURES = [
    (
        "fx-fraud-1",
        "fraud",
        "FICTIONAL TEST: Your Northpay wallet is suspended. Verify your PIN now "
        "at http://northpay-verify.example or lose your balance today.",
    ),
    (
        "fx-fraud-2",
        "fraud",
        "FICTIONAL TEST: Hi Dad, phone broke, this is my new number. Please "
        "transfer Rs 12,000 to my friend's account urgently, will explain.",
    ),
    (
        "fx-fraud-3",
        "fraud",
        "FICTIONAL TEST: Customs has held your parcel. Pay the Rs 49 release "
        "fee within 2 hours: https://parcel-release.example/pay",
    ),
    (
        "fx-spam-1",
        "spam",
        "FICTIONAL TEST: Weekend Bonanza at Fabrikart! Buy 1 get 1 free on all "
        "kurtas. Offer ends Sunday. Reply STOP to opt out.",
    ),
    (
        "fx-spam-2",
        "spam",
        "FICTIONAL TEST: Get 2GB extra data for just Rs 19 with Zoomtel! Recharge "
        "today and enjoy unlimited calls. T&C apply.",
    ),
    (
        "fx-spam-3",
        "spam",
        "FICTIONAL TEST: Grand opening of Spicebox restaurant this Friday. Flat 30% "
        "off on your first meal. Book a table now!",
    ),
    (
        "fx-legit-1",
        "legitimate",
        "FICTIONAL TEST: Hi, reaching the station in 10 minutes. Wait near "
        "the ticket counter, see you soon.",
    ),
    (
        "fx-legit-2",
        "legitimate",
        "FICTIONAL TEST: 731904 is your Northpay sign-in code. It expires in "
        "10 minutes. Do not share it with anyone.",
    ),
    (
        "fx-legit-3",
        "legitimate",
        "FICTIONAL TEST: Reminder: your dentist appointment is tomorrow at "
        "4.30 pm. Reply C to confirm or R to reschedule.",
    ),
]

if (
    not WORKER_PYTHON.exists()
    or not (MODEL_DIR / load_manifest(MANIFEST_PATH).manifest.artifact_dir).is_dir()
):
    pytest.skip("real worker environment or model artifacts not present", allow_module_level=True)


def _config() -> SmsWorkerConfig:
    return SmsWorkerConfig(
        command=worker_command(WORKER_PYTHON, MANIFEST_PATH, MODEL_DIR, 2),
        lock_path=MODEL_DIR / ".kavach-sms-worker.lock",
        manifest=load_manifest(MANIFEST_PATH),
        threads=2,
        commit_reserve_s=0.0,
    )


def test_fictional_fixtures_get_valid_deterministic_native_predictions() -> None:
    supervisor = SmsWorkerSupervisor(_config())
    supervisor.start()
    rows = []
    try:
        assert supervisor.wait_until(("ready", "unverified"), 120) == "ready"
        for fixture_id, intent, text in FIXTURES:
            first = supervisor.classify(text, time.monotonic() + 30)
            second = supervisor.classify(text, time.monotonic() + 30)
            for result in (first, second):
                assert result.outcome == "complete", (fixture_id, result.reason)
                evidence = result.evidence
                assert set(evidence.labels) == LABELS
                assert all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in evidence.labels.values())
                assert abs(sum(evidence.labels.values()) - 1) < 1e-3
                assert evidence.top_label == max(evidence.labels, key=evidence.labels.__getitem__)
                assert evidence.score_semantics == "uncalibrated_softmax"
                # The evidence carries scores and a version, never the message.
                assert text not in json.dumps(asdict(evidence), default=str)
            assert first.evidence.top_label == second.evidence.top_label, fixture_id
            for label in LABELS:
                assert abs(first.evidence.labels[label] - second.evidence.labels[label]) < 1e-6
            rows.append(
                {
                    "id": fixture_id,
                    "intent": intent,
                    "prediction": first.evidence.top_label,
                    "labels": {k: round(v, 4) for k, v in first.evidence.labels.items()},
                }
            )
        version = first.evidence.model_version
    finally:
        supervisor.close()
    agreement = sum(row["intent"] == row["prediction"] for row in rows)
    print(
        "SMS_MODEL_FIXTURE_REPORT",
        json.dumps(
            {
                "model_version": version,
                "fixtures": len(rows),
                "intent_agreement": agreement,
                "note": "fictional smoke fixtures; not an accuracy evaluation",
                "rows": rows,
            }
        ),
    )
