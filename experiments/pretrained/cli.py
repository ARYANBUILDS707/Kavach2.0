"""Pretrained-model proof of concept (run from experiments/ with `--group pretrained`):

    python -m pretrained candidates            the audited candidates and the selection
    python -m pretrained fetch                 download + verify the selected model (~1.3 GB)
    python -m pretrained verify                offline hash check of the local copy
    python -m pretrained run [--repeats N]     local CPU inference on the fictional demo set

Model files go to the ignored `data/models/<key>/<revision>/`. The only inputs are the fictional
messages in `pretrained/demo.py`: there is no option to classify a file, a dataset or free text,
so no private message can be sent through this runner. The report holds message IDs, labels,
scores and timings, never text.
"""

import argparse
import platform
import resource
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from pretrained.candidates import CANDIDATES, selected
from pretrained.demo import DEMO_MESSAGES
from pretrained.fetch import DEFAULT_MODEL_ROOT, ModelFetchError, fetch, verify
from pretrained.inference import ModelUnavailable, load_classifier, predict
from sms_prep.cli import write_json

REPORTS = Path(__file__).parents[1] / "reports"
REPORT_NAME = "pretrained_poc.json"
DISCLAIMER = (
    "Third-party pretrained weights run locally; not a KAVACH-trained model. Scores are "
    "uncalibrated softmax outputs. Agreement with the authors' intent on 14 fictional messages "
    "is a pipeline smoke test, not an accuracy measurement."
)


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes.
    return round(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024, 1)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))]


def versions() -> dict:
    import tokenizers
    import torch
    import transformers

    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
        "torch_threads": torch.get_num_threads(),
        "device": "cpu",
    }


def cmd_candidates(_: argparse.Namespace) -> int:
    for c in CANDIDATES.values():
        size_mb = c.weights.size_bytes / 1e6
        print(f"{c.key}: {c.repo}@{c.revision[:12]} {c.license.split(' ')[0]} "
              f"{c.parameters} weights {size_mb:.0f} MB labels {list(c.labels)}")  # fmt: skip
        print(f"    {c.decision}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    candidate = selected()
    fetched = fetch(candidate, args.model_root)
    print(f"{candidate.key}: {len(fetched)} file(s) downloaded; all files verified")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    candidate = selected()
    problems = verify(candidate, args.model_root)
    for problem in problems:
        print(f"  {problem}")
    print(f"{candidate.key}: {'NOT VERIFIED' if problems else 'verified'}")
    return 3 if problems else 0


def cmd_run(args: argparse.Namespace) -> int:
    candidate = selected()
    texts = [m.text for m in DEMO_MESSAGES]
    report: dict = {
        "disclaimer": DISCLAIMER,
        "candidate": {
            "key": candidate.key,
            "repo": candidate.repo,
            "revision": candidate.revision,
            "weights_sha256": candidate.weights.sha256,
            "license": candidate.license,
        },
        "inputs": "pretrained/demo.py (fictional, explicitly labeled)",
        "peak_rss_mb_before_load": peak_rss_mb(),
    }
    started = time.perf_counter()
    try:
        classifier = load_classifier(candidate, args.model_root)
    except ModelUnavailable as error:
        results = predict(None, candidate, texts, str(error))
        report.update({"status": "unavailable", "reason": str(error)})
        report["messages"] = [
            {"id": m.id, "intent": m.intent, "status": r.status, "fraud_score": r.fraud_score}
            for m, r in zip(DEMO_MESSAGES, results, strict=True)
        ]
        write_json(args.reports / REPORT_NAME, report)
        print(f"{candidate.key}: UNAVAILABLE ({error}); scores are null")
        return 3
    load_seconds = time.perf_counter() - started
    report["peak_rss_mb_after_load"] = peak_rss_mb()

    predict(classifier, candidate, texts[:1])  # warm-up, not timed
    single: list[float] = []
    results = []
    for text in texts:
        for _ in range(args.repeats):
            t0 = time.perf_counter()
            result = predict(classifier, candidate, [text])[0]
            single.append((time.perf_counter() - t0) * 1000)
        results.append(result)
    t0 = time.perf_counter()
    batch = predict(classifier, candidate, texts)
    batch_ms = (time.perf_counter() - t0) * 1000
    stable = all(
        a.label == b.label and abs(a.fraud_score - b.fraud_score) < 1e-4
        for a, b in zip(results, batch, strict=True)
    )
    report.update({
        "status": "ok",
        "environment": versions(),
        "max_tokens": candidate.max_tokens,
        "load_seconds": round(load_seconds, 2),
        "latency_ms_single_message": {
            "samples": len(single),
            "median": round(statistics.median(single), 1),
            "p95": round(percentile(single, 0.95), 1),
            "max": round(max(single), 1),
        },
        "latency_ms_batch_of_14": round(batch_ms, 1),
        "batch_matches_single": stable,
        "peak_rss_mb_after_inference": peak_rss_mb(),
        "messages": [
            {"id": m.id, "intent": m.intent, "description": m.description, "label": r.label,
             "fraud_score": r.fraud_score, "unwanted_score": r.unwanted_score,
             "probabilities": r.probabilities}
            for m, r in zip(DEMO_MESSAGES, results, strict=True)
        ],
    })  # fmt: skip
    write_json(args.reports / REPORT_NAME, report)
    for m, r in zip(DEMO_MESSAGES, results, strict=True):
        print(f"{m.id} intent={m.intent:<10} label={r.label:<10} fraud={r.fraud_score:.4f} "
              f"unwanted={r.unwanted_score:.4f}")  # fmt: skip
    latency = report["latency_ms_single_message"]
    print(f"load {load_seconds:.2f}s; latency median {latency['median']} ms, p95 "
          f"{latency['p95']} ms; batch of 14 {batch_ms:.0f} ms; peak RSS "
          f"{report['peak_rss_mb_after_inference']} MB")  # fmt: skip
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pretrained")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--reports", type=Path, default=REPORTS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("candidates").set_defaults(func=cmd_candidates)
    commands.add_parser("fetch").set_defaults(func=cmd_fetch)
    commands.add_parser("verify").set_defaults(func=cmd_verify)
    run = commands.add_parser("run")
    run.add_argument("--repeats", type=int, default=5, choices=range(1, 51), metavar="1-50")
    run.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ModelFetchError as error:
        print(f"FETCH STOPPED: {error}", file=sys.stderr)
        return 2
