"""Real-stack smoke test: the supervisor driving the real worker and the pinned Horizon model.

Opt-in (`-m model`), local only. It needs:
- `workers/sms/.venv` built with the `model` group;
- the verified artifacts under MODEL_DIR (default `data/models`).

Every message is fictional. Run it under an OS network denial to show it is offline; on macOS:

    sandbox-exec -p '(version 1)(allow default)(deny network-outbound (remote ip))' \\
        uv run --project backend --locked pytest backend/tests/test_sms_worker_model.py -m model -s

Measurements are printed as one JSON line (`SMS_WORKER_MEASUREMENTS`) for the milestone record.
"""

import json
import os
import statistics
import subprocess
import threading
import time
from pathlib import Path

import pytest

from kavach.models.manifest import load_manifest
from kavach.models.sms_worker import SmsWorkerConfig, SmsWorkerSupervisor, worker_command

pytestmark = pytest.mark.model

REPO = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO / "deployment" / "models" / "sms_classifier.horizon.v1.json"
WORKER_PYTHON = REPO / "workers" / "sms" / ".venv" / "bin" / "python"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", REPO / "data" / "models"))
MESSAGES = [
    "FICTIONAL DEMO: Your Examplebank KYC expires today. Update at http://kyc-update.example",
    "FICTIONAL DEMO: Running 10 minutes late, start dinner without me.",
    "FICTIONAL DEMO: 482913 is your Examplebank login code. Never share it.",
    "FICTIONAL DEMO: Mega Sale at ShopFictional! Flat 50% off this weekend.",
    "FICTIONAL DEMO: Hi Mum, new number. Please send Rs 8,000 urgently.",
]

if (
    not WORKER_PYTHON.exists()
    or not (MODEL_DIR / load_manifest(MANIFEST_PATH).manifest.artifact_dir).is_dir()
):
    pytest.skip("real worker environment or model artifacts not present", allow_module_level=True)


def rss_mb(supervisor: SmsWorkerSupervisor) -> int | None:
    """The worker's self-reported peak RSS (`ps` is not allowed under the network sandbox)."""
    return supervisor.status()["worker_peak_rss_mb"]


def swap_used_mb() -> float | None:
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True)
    parts = out.stdout.split()
    return float(parts[parts.index("used") + 2].rstrip("M")) if "used" in parts else None


def config(tmp_path: Path, threads: int = 2, **overrides) -> SmsWorkerConfig:
    manifest = load_manifest(MANIFEST_PATH)
    settings = {
        "command": worker_command(WORKER_PYTHON, MANIFEST_PATH, MODEL_DIR, threads),
        "lock_path": MODEL_DIR / ".kavach-sms-worker.lock",
        "manifest": manifest,
        "threads": threads,
        "commit_reserve_s": 0.0,
    }
    settings.update(overrides)
    return SmsWorkerConfig(**settings)


def test_real_worker_startup_inference_memory_concurrency_and_kill(tmp_path):
    measurements: dict = {"swap_used_mb_before": swap_used_mb()}
    started = time.monotonic()
    supervisor = SmsWorkerSupervisor(config(tmp_path))
    supervisor.start()
    try:
        assert supervisor.wait_until(("ready", "unverified"), 120) == "ready"
        measurements["startup_s"] = round(time.monotonic() - started, 2)
        pid = supervisor.status()["worker_pid"]
        measurements["peak_rss_mb_after_ready"] = rss_mb(supervisor)

        result = supervisor.classify(MESSAGES[0], time.monotonic() + 30)
        assert result.outcome == "complete"
        assert set(result.evidence.labels) == {"legitimate", "spam", "fraud"}
        assert abs(sum(result.evidence.labels.values()) - 1) < 1e-3
        assert result.evidence.score_semantics == "uncalibrated_softmax"
        measurements["example"] = {
            "label": result.evidence.top_label,
            "labels": result.evidence.labels,
        }

        latencies, model_ms = [], []
        for i in range(200):
            t0 = time.monotonic()
            r = supervisor.classify(MESSAGES[i % len(MESSAGES)], time.monotonic() + 30)
            latencies.append((time.monotonic() - t0) * 1000)
            assert r.outcome == "complete"
            model_ms.append(r.model_ms)
        latencies.sort()
        measurements["sequential_200"] = {
            "total_ms_median": round(statistics.median(latencies), 1),
            "total_ms_p95": round(latencies[int(0.95 * len(latencies)) - 1], 1),
            "total_ms_max": round(latencies[-1], 1),
            "model_ms_median": statistics.median(model_ms),
        }
        measurements["peak_rss_mb_after_200"] = rss_mb(supervisor)

        long_text = ("FICTIONAL DEMO: please verify your account details today. " * 70)[:4096]
        r = supervisor.classify(long_text, time.monotonic() + 30)
        assert r.outcome == "complete" and r.evidence.truncated is True
        measurements["max_length_message_model_ms"] = r.model_ms

        # Concurrency: three at once on one worker -> two complete (one waited), one rejected.
        results: list = [None] * 3
        barrier = threading.Barrier(3)

        def call(index: int) -> None:
            barrier.wait()
            results[index] = supervisor.classify(long_text, time.monotonic() + 30)

        threads = [threading.Thread(target=call, args=(i,)) for i in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        outcomes = sorted(r.outcome for r in results)
        assert outcomes == ["complete", "complete", "rejected"]
        assert [r.reason for r in results if r.outcome == "rejected"] == ["inference_saturated"]
        measurements["peak_rss_mb_after_concurrency"] = rss_mb(supervisor)
        assert measurements["peak_rss_mb_after_concurrency"] <= 1536
        measurements["concurrent_3"] = {
            "outcomes": outcomes,
            "max_wait_ms": max(r.wait_ms for r in results),
        }
        assert supervisor.status()["free_slots"] == 2
        assert pid == supervisor.status()["worker_pid"], "one worker, never a second copy"
    finally:
        supervisor.close()
    assert supervisor.state == "closed"

    # A real inference killed mid-run (tiny budget) is gone, and a fresh worker self-tests again.
    killer = SmsWorkerSupervisor(config(tmp_path, inference_timeout_s=0.01, min_budget_s=0.001))
    killer.start()
    try:
        assert killer.wait_until(("ready",), 120) == "ready"
        first_pid = killer.status()["worker_pid"]
        t0 = time.monotonic()
        r = killer.classify(long_text, time.monotonic() + 30)
        assert r.reason == "inference_timeout"
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                os.kill(first_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            pytest.fail("the killed worker is still alive after 1 s")
        measurements["kill_s"] = round(time.monotonic() - t0, 3)
        t1 = time.monotonic()
        assert killer.wait_until(("ready",), 120) == "ready"
        measurements["restart_to_ready_s"] = round(time.monotonic() - t1, 2)
        assert killer.status()["worker_pid"] != first_pid
    finally:
        killer.close()
    measurements["swap_used_mb_after"] = swap_used_mb()
    print("SMS_WORKER_MEASUREMENTS " + json.dumps(measurements, sort_keys=True))


@pytest.mark.parametrize("threads", [1, 2, 4])
def test_latency_by_thread_count(tmp_path, threads):
    supervisor = SmsWorkerSupervisor(config(tmp_path, threads=threads))
    supervisor.start()
    try:
        assert supervisor.wait_until(("ready",), 120) == "ready"
        timings = []
        for i in range(60):
            r = supervisor.classify(MESSAGES[i % len(MESSAGES)], time.monotonic() + 30)
            timings.append(r.model_ms)
        timings.sort()
        rss = rss_mb(supervisor)
    finally:
        supervisor.close()
    print(
        "SMS_WORKER_THREADS "
        + json.dumps(
            {
                "threads": threads,
                "model_ms_median": statistics.median(timings),
                "model_ms_p95": timings[int(0.95 * len(timings)) - 1],
                "rss_mb": rss,
            }
        )
    )


def test_real_worker_refuses_artifacts_that_do_not_match_its_manifest(tmp_path):
    """A manifest recording a different weights hash: the worker hashes the real 1.2 GB file,
    refuses it before importing torch, and the supervisor stays unverified (never restarts)."""
    data = json.loads(MANIFEST_PATH.read_text())
    for item in data["files"]:
        if item["name"] == "model.safetensors":
            item["sha256"] = "0" * 64
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(data))
    manifest = load_manifest(tampered)
    supervisor = SmsWorkerSupervisor(
        SmsWorkerConfig(
            command=worker_command(WORKER_PYTHON, tampered, MODEL_DIR, 2),
            lock_path=tmp_path / "lock",
            manifest=manifest,
        )
    )
    supervisor.start()
    try:
        assert supervisor.wait_until(("unverified", "ready"), 120) == "unverified"
        status = supervisor.status()
        assert status["fatal_code"] == "model_unverified" and status["starts"] == 1
        result = supervisor.classify("FICTIONAL DEMO: hello", time.monotonic() + 30)
        assert (result.outcome, result.reason, result.evidence) == (
            "unavailable",
            "model_unverified",
            None,
        )
    finally:
        supervisor.close()
