"""PyTorch reference outputs of the pinned model on the fictional messages.

Run with the worker's model environment (the only place torch and transformers are installed):

    workers/sms/.venv/bin/python -I tools/browser-model/reference.py \
        --model-dir data/models/horizon-phishing-scam-base/<revision> --out reference.json

Writes per-message softmax probabilities (fp32, CPU, truncation to 256 tokens like the worker).
"""

import argparse
import json
from pathlib import Path

LABELS = ("legitimate", "spam", "fraud")
MAX_TOKENS = 256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--messages", type=Path, default=Path(__file__).with_name("fictional_messages.json")
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir, dtype=torch.float32)
    model.eval()
    assert tuple(model.config.id2label[i] for i in range(3)) == LABELS
    messages = json.loads(args.messages.read_text())["messages"]
    results = []
    with torch.inference_mode():
        for item in messages:
            encoded = tokenizer(
                item["text"], return_tensors="pt", truncation=True, max_length=MAX_TOKENS
            )
            probabilities = model(**encoded).logits.softmax(-1)[0].tolist()
            results.append(
                {
                    "intended": item["intended"],
                    "text": item["text"],
                    "tokens": int(encoded["input_ids"].shape[1]),
                    "probabilities": [round(p, 6) for p in probabilities],
                    "top": LABELS[max(range(3), key=probabilities.__getitem__)],
                }
            )
    args.out.write_text(json.dumps({"labels": LABELS, "results": results}, indent=1))
    print(f"wrote {len(results)} reference outputs to {args.out}")


if __name__ == "__main__":
    main()
