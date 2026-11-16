"""Compare the browser (q8 ONNX) model with the PyTorch reference on the fictional messages.

    uv run --project tools/browser-model --locked python tools/browser-model/compare.py \
        --model frontend/public/model --reference reference.json --out comparison.json

Reports top-label agreement and the largest and mean absolute probability differences. This is a
numerical-fidelity check of the quantized build against the pinned model; it is not an accuracy
evaluation (M4-Q is separate and NOT READY).
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

LABELS = ("legitimate", "spam", "fraud")
MAX_TOKENS = 256


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max()
    exp = np.exp(shifted)
    return exp / exp.sum()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True, help="built browser model directory")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    tokenizer = Tokenizer.from_file(str(args.model / "tokenizer.json"))
    tokenizer.enable_truncation(MAX_TOKENS)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(
        str(args.model / "onnx" / "model_quantized.onnx"),
        options,
        providers=["CPUExecutionProvider"],
    )
    reference = json.loads(args.reference.read_text())["results"]
    rows = []
    timings = []
    for item in reference:
        encoded = tokenizer.encode(item["text"])
        feeds = {
            "input_ids": np.array([encoded.ids], dtype=np.int64),
            "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
        }
        started = time.perf_counter()
        logits = session.run(None, feeds)[0][0]
        timings.append(time.perf_counter() - started)
        probabilities = softmax(logits.astype(np.float64))
        top = LABELS[int(probabilities.argmax())]
        diff = np.abs(probabilities - np.array(item["probabilities"]))
        rows.append(
            {
                "intended": item["intended"],
                "reference_top": item["top"],
                "browser_top": top,
                "agree": top == item["top"],
                "tokens_reference": item["tokens"],
                "tokens_browser": len(encoded.ids),
                "max_abs_prob_diff": round(float(diff.max()), 6),
                "reference_probabilities": item["probabilities"],
                "browser_probabilities": [round(float(p), 6) for p in probabilities],
            }
        )
    summary = {
        "messages": len(rows),
        "top_label_agreement": sum(r["agree"] for r in rows) / len(rows),
        "disagreements": [
            {
                "intended": r["intended"],
                "reference": r["reference_top"],
                "browser": r["browser_top"],
            }
            for r in rows
            if not r["agree"]
        ],
        "max_abs_prob_diff": max(r["max_abs_prob_diff"] for r in rows),
        "mean_abs_prob_diff": round(float(np.mean([r["max_abs_prob_diff"] for r in rows])), 6),
        "tokenization_identical": all(r["tokens_reference"] == r["tokens_browser"] for r in rows),
        "onnxruntime_cpu_ms_median": round(1000 * float(np.median(timings)), 1),
        "model_file_mb": round(
            (args.model / "onnx" / "model_quantized.onnx").stat().st_size / 1e6, 1
        ),
    }
    args.out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
