"""TEST DOUBLE ONLY: supervisor configuration that drives `fake_sms_worker.py`."""

import json
import sys
import time
from pathlib import Path
from typing import Any

from kavach.models.manifest import load_manifest
from kavach.models.sms_worker import SmsWorkerConfig, SmsWorkerSupervisor

REPO = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
MANIFEST = load_manifest(MANIFEST_PATH)
FAKE = Path(__file__).parent / "fake_sms_worker.py"


def fake_worker_config(
    lock_path: Path, mode: str = "ready", report: Path | None = None, **overrides: Any
) -> SmsWorkerConfig:
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
    settings: dict[str, Any] = {
        "command": tuple(command),
        "lock_path": lock_path,
        "manifest": MANIFEST,
        "inference_timeout_s": 1.0,
        "start_timeout_s": 10.0,
        "commit_reserve_s": 0.5,
        "min_budget_s": 0.05,
        "backoff_s": (0.05, 0.1),
        "failure_window_s": 60.0,
        "circuit_open_s": 30.0,
        "shutdown_grace_s": 2.0,
    } | overrides
    return SmsWorkerConfig(**settings)


def fake_supervisor(lock_path: Path, **kwargs: Any) -> SmsWorkerSupervisor:
    return SmsWorkerSupervisor(fake_worker_config(lock_path, **kwargs))


def worker_pid(report: Path) -> int:
    return int(json.loads(report.read_text())["pid"])


def wait_state(supervisor: SmsWorkerSupervisor, *states: str, timeout: float = 10) -> str:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if supervisor.state in states:
            return supervisor.state
        time.sleep(0.02)
    return supervisor.state
