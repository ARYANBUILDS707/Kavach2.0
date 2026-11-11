"""Synthetic artifact sets for the worker tests: small fake files plus a manifest that describes
them. No real weights and no torch; the real model is tested separately (`-m model`)."""

import hashlib
import json
from pathlib import Path

import pytest

from kavach_sms_worker.canary import canary_sha256

REPO = Path(__file__).resolve().parents[3]
REAL_MANIFEST = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
LABELS = ["legitimate", "spam", "fraud"]
CANARY_PROBABILITIES = [0.0007, 0.0008, 0.9985]


def config_bytes(**changes) -> bytes:
    config = {
        "architectures": ["ModernBertForSequenceClassification"],
        "id2label": {"0": "legitimate", "1": "spam", "2": "fraud"},
    }
    config.update(changes)
    return json.dumps(config).encode()


def write_artifacts(root: Path, files: dict[str, bytes] | None = None) -> Path:
    files = files or {
        "config.json": config_bytes(),
        "tokenizer.json": b'{"fake": "tokenizer"}',
        "model.safetensors": b"fake weights, never loaded",
        "LICENSE": b"license text",
    }
    directory = root / "fake-model" / ("a" * 40)
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_bytes(data)
    manifest = json.loads(REAL_MANIFEST.read_text())
    manifest["artifact_dir"] = f"fake-model/{'a' * 40}"
    manifest["files"] = [
        {"name": n, "sha256": hashlib.sha256(d).hexdigest(), "size_bytes": len(d)}
        for n, d in files.items()
    ]
    manifest["self_test"]["canary_sha256"] = canary_sha256()
    manifest["self_test"]["expected_probabilities"] = CANARY_PROBABILITIES
    (root / "manifest.json").write_text(json.dumps(manifest))
    return directory


class FakeClassifier:
    """Test double: returns fixed probabilities; records nothing about the text."""

    def __init__(self, probabilities=None, fail: bool = False) -> None:
        self.probabilities = probabilities or CANARY_PROBABILITIES
        self.fail = fail
        self.calls = 0

    def classify(self, text: str):
        self.calls += 1
        if self.fail and self.calls > 1:  # the self-test call succeeds, later calls fail
            raise RuntimeError(f"library failure mentioning {text}")
        return list(self.probabilities), len(text) > 1000


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    write_artifacts(tmp_path)
    return tmp_path
