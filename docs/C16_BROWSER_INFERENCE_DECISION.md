# Decision C-16: In-browser SMS analysis on a free static site — owner decision record

**Status: AWAITING THE OWNER'S DECISION. Nothing here approves a public release.** Prepared
16 November 2026. The code is in branch `feature/browser-inference`; the site goes public only
when the owner turns on GitHub Pages (see "Release").

## What it is

A static build of the existing public site (`npm run build:static`) where the Analyze SMS page runs
the pinned classifier **inside the visitor's browser** (Transformers.js 4.3.2 / ONNX Runtime Web,
WebAssembly, CPU). There is no server API: the message is tokenized and classified in the tab and
is never sent anywhere. Cost: ₹0 (GitHub Pages for the site; the model files are downloaded from
the model authors' public Hugging Face repository).

**Model:** `Horizon-Labs/phishing-scam-detector-base` at revision
`fa686fc0d6a3634092ada93a7c6b89ab0746b8f8` (the same revision the server worker pins), using the
authors' own published `onnx/model_quantized.onnx` (int8 embeddings, 641 MB) plus the tokenizer
and config. Licence Apache-2.0; the files are fetched from the authors' repository, not
redistributed by KAVACH. Each file is checked against the size and SHA-256 in the authors'
`SHA256SUMS` before use; any other URL is refused.

## How it differs from C-13 and C-15

| | C-13 | C-15 | C-16 (this) |
| --- | --- | --- | --- |
| Where the model runs | Owner's machine | KAVACH server | Visitor's device |
| Who receives the message | Local server only | KAVACH server | Nobody |
| Cost | ₹0 | ≈ $19–22/month | ₹0 |
| Status | Resolved (local, fictional) | Proposed | Proposed |

## Measured fidelity (fictional messages; not accuracy)

30 invented messages (`tools/browser-model/fictional_messages.json`), PyTorch fp32 reference vs
the browser file run with ONNX Runtime CPU (`tools/browser-model/compare.py`):

- Top label identical on **30 of 30**; tokenization identical on 30 of 30.
- Largest native-score difference **0.007**, mean of per-message maxima **0.0008**.
- PyTorch's own top labels: 10 of 10 intended-legitimate → legitimate; 7 of 10 intended-spam →
  spam (3 → fraud); 10 of 10 intended-fraud → fraud. Invented messages written by the
  implementer say **nothing** about real-world accuracy.
- A smaller re-quantization (309 MB, MatMul int8) was rejected: same top labels but score
  differences up to 0.29.

M4-Q is **NOT READY**. No validated accuracy, calibration or safety claim is made. The page shows
the class only (native scores are uncalibrated), says "not validated", "Legitimate does not mean
safe", blocks nothing and reports nothing.

## Privacy and limitations notice (shown on the page)

- The message stays on the device; nothing is stored, logged or collected; links in a message are
  never opened.
- First use downloads 675 MB from Hugging Face, which sees the visitor's IP address; GitHub Pages
  serves the site and sees the visitor's IP address. Neither receives message text.
- Phones may not have enough memory; the page then shows an honest error.

## Risks the owner accepts

Wrong predictions in either direction with unknown error rates; a large download for visitors;
dependence on Hugging Face keeping the pinned revision available (if it disappears, the page
reports a failed download — it never falls back to anything else).

## Owner decision (owner only)

- [ ] Not approved — do not enable GitHub Pages.
- [ ] Approved: release the static in-browser analyzer for fictional demonstration messages,
      knowing M4-Q is NOT READY and error rates are unknown. This is not a validation and does
      not change C-12, C-13 or C-15.
- Date and name: ______________________

## Release (owner action, after approving)

Build with `npm run build:static` in `frontend/`, add an empty `.nojekyll`, and push the contents
of `frontend/dist` as the root of branch **`gh-pages`**. For this repository GitHub enables Pages
automatically on the first push of that branch (observed 16 Nov 2026), so **pushing the branch is
the release act**: do it only after ticking the approval above. The site appears at
`https://aryanbuilds707.github.io/Kavach2.0/` within minutes. To withdraw it, delete the
`gh-pages` branch (Pages then has no source; GitHub's CDN may serve a cached copy for up to
10 minutes). The Railway site is untouched either way.

Incident, 16 Nov 2026: while preparing this, the implementer pushed `gh-pages` expecting Pages to
stay off; GitHub enabled it and the static site was publicly reachable for about 15 minutes before
the branch was deleted and the URL returned 404. No approval was recorded; none is implied.
