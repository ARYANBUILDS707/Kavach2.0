# Browser model checks

Evidence that the browser build of the pinned classifier behaves like the PyTorch reference.
Fictional messages only; this is a fidelity check, not an accuracy evaluation (M4-Q is separate).

```sh
# 1. PyTorch reference (worker model environment, verified local artifacts)
workers/sms/.venv/bin/python -I tools/browser-model/reference.py \
  --model-dir data/models/horizon-phishing-scam-base/fa686fc0d6a3634092ada93a7c6b89ab0746b8f8 --out reference.json
# 2. Put the upstream onnx/model_quantized.onnx (SHA-256 93b2e8e5…) and tokenizer.json in <dir>/onnx and <dir>
uv run --project tools/browser-model --locked python tools/browser-model/compare.py \
  --model <dir> --reference reference.json --out comparison.json
```

Result on 16 Nov 2026: 30/30 top labels identical, max score difference 0.007
(docs/C16_BROWSER_INFERENCE_DECISION.md). The page itself is tested end to end by
`frontend/playwright.browser.config.ts` (downloads the real model).
