"""The public site's recorded examples are real outputs of the pinned model, on fictional text.

`frontend/src/features/public/examples.json` is what the login-free site shows. Two checks keep it
honest:

- default suite (service-free, runs in CI): the file is well formed, every message is plainly
  fictional with `.example` links only, and its model version is the pinned manifest revision;
- opt-in `-m model` (local, offline, needs the model environment and verified artifacts): the
  recorded predictions and native scores still equal what the real model returns today.
  With KAVACH_WRITE_PUBLIC_EXAMPLES=1 the same test re-records the file from real inference.

No example is typed by hand and none is ever shown as live analysis.
"""

import json
import math
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kavach.models.manifest import load_manifest
from kavach.models.sms_worker import SmsWorkerConfig, SmsWorkerSupervisor, worker_command

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "frontend" / "src" / "features" / "public" / "examples.json"
MANIFEST_PATH = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
WORKER_PYTHON = REPO / "workers" / "sms" / ".venv" / "bin" / "python"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", REPO / "data" / "models"))
LABELS = {"legitimate", "spam", "fraud"}
ROUNDING = 1e-4


def load() -> dict:
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))


def test_the_recorded_examples_are_well_formed_fictional_and_tied_to_the_pinned_model() -> None:
    data = load()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pinned = f"{manifest['model_key']}@{manifest['revision'][:12]}"
    assert data["model_version"].startswith(pinned + "+"), "re-record against the pinned revision"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["recorded_on"])

    ids = [example["id"] for example in data["examples"]]
    assert len(ids) >= 6 and len(set(ids)) == len(ids)
    predictions = set()
    for example in data["examples"]:
        text = example["text"]
        assert text.startswith("FICTIONAL TEST:"), example["id"]
        for url in re.findall(r"https?://\S+", text):
            host = urlsplit(url).hostname or ""
            assert host.endswith(".example"), f"{example['id']}: real-looking host {host}"
        assert not re.search(r"\b\d{10,}\b", text), f"{example['id']}: phone-number-like digits"
        labels = example["labels"]
        assert set(labels) == LABELS
        assert all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in labels.values())
        assert abs(sum(labels.values()) - 1) < 5e-4, "native softmax scores, rounded to 4 decimals"
        assert example["prediction"] == max(labels, key=labels.__getitem__)
        predictions.add(example["prediction"])
    assert predictions == LABELS, "the page shows all three outcomes the model can give"


@pytest.mark.model
def test_the_recorded_examples_equal_real_inference_from_the_pinned_model() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    if not WORKER_PYTHON.exists() or not (MODEL_DIR / manifest.manifest.artifact_dir).is_dir():
        pytest.skip("real worker environment or model artifacts not present")
    data = load()
    supervisor = SmsWorkerSupervisor(
        SmsWorkerConfig(
            command=worker_command(WORKER_PYTHON, MANIFEST_PATH, MODEL_DIR, 2),
            lock_path=MODEL_DIR / ".kavach-sms-worker.lock",
            manifest=manifest,
            threads=2,
            commit_reserve_s=0.0,
        )
    )
    supervisor.start()
    version = None
    try:
        assert supervisor.wait_until(("ready", "unverified"), 120) == "ready"
        for example in data["examples"]:
            result = supervisor.classify(example["text"], time.monotonic() + 30)
            assert result.outcome == "complete", (example["id"], result.reason)
            evidence = result.evidence
            version = evidence.model_version
            labels = {name: round(value, 4) for name, value in evidence.labels.items()}
            if os.environ.get("KAVACH_WRITE_PUBLIC_EXAMPLES") == "1":
                example["prediction"] = evidence.top_label
                example["labels"] = {name: labels[name] for name in ("legitimate", "spam", "fraud")}
            else:
                assert example["prediction"] == evidence.top_label, example["id"]
                for name, value in labels.items():
                    assert abs(example["labels"][name] - value) <= ROUNDING, (example["id"], name)
    finally:
        supervisor.close()
    if os.environ.get("KAVACH_WRITE_PUBLIC_EXAMPLES") == "1":
        data["model_version"] = version
        data["recorded_on"] = datetime.now(UTC).date().isoformat()
        EXAMPLES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        assert data["model_version"] == version
