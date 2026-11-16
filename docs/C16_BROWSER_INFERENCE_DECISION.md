# Decision C-16: In-browser analysis of visitors' real SMS on a free static site — owner decision record

**Status: APPROVED by the owner on 16 November 2026 for visitors' own real messages, analysed only
in their browser.** Prepared 16 November 2026 and revised the same day at the owner's request from a
fictional-only demonstration (which the owner declined) to the real-message scope below.

## What it is

A static build of the existing public site (`npm run build:static`) where the Analyze SMS page runs
the pinned classifier **inside the visitor's browser** (Transformers.js 4.3.2 / ONNX Runtime Web,
WebAssembly, CPU). Visitors may paste messages they actually received. There is no server API:
the message is tokenized and classified in the tab and is never transmitted, stored, logged or
collected. Cost: ₹0 (GitHub Pages for the site; the model files are downloaded from the model
authors' public Hugging Face repository).

**Model:** `Horizon-Labs/phishing-scam-detector-base` at revision
`fa686fc0d6a3634092ada93a7c6b89ab0746b8f8` (the same revision the server worker pins), using the
authors' own published `onnx/model_quantized.onnx` (int8 embeddings, 641 MB) plus the tokenizer
and config. Licence Apache-2.0; visitors fetch the files from the authors' repository, KAVACH does
not redistribute them. Each file is checked against the size and SHA-256 in the authors'
`SHA256SUMS` before use; any other URL is refused.

## How it differs from C-13 and C-15

| | C-13 | C-15 | C-16 (this) |
| --- | --- | --- | --- |
| Messages | Fictional | Visitors' (server) | Visitors' real messages |
| Where the model runs | Owner's machine | KAVACH server | Visitor's device |
| Who receives the message | Local server only | KAVACH server | Nobody |
| Cost | ₹0 | ≈ $19–22/month | ₹0 |
| Status | Resolved (local, fictional) | Proposed | Proposed |

## Measured fidelity (fictional test messages; not accuracy)

30 invented messages (`tools/browser-model/fictional_messages.json`), PyTorch fp32 reference vs
the browser file run with ONNX Runtime CPU (`tools/browser-model/compare.py`): top label identical
on **30 of 30**, largest native-score difference **0.007**. This shows the browser file behaves like
the pinned model; it says **nothing** about whether either is right on real messages. Testing
uses invented text only; no real message was used to build or test this.

M4-Q is **NOT READY**. Real-world accuracy is unknown in size and direction. No validated accuracy,
calibration or safety claim is made.

## Safeguards implemented on the page

- Notice before use: experimental and unvalidated; can be wrong both ways; “Legitimate” is never
  proof of safety; nothing is blocked or reported; check worrying messages with the sender through
  a trusted channel.
- Privacy notice: the message stays on the device; not sent, stored or logged; links never opened.
- Secrets warning (notice and field hint): remove or do not paste OTPs, passwords, PINs, card
  numbers or other secrets.
- Explicit consent checkbox, required per visit before Analyze is enabled; it is not stored.
- Model download only after the visitor presses "Load model (676 MB)", with progress and honest errors.
- Result shows the class only (scores are uncalibrated), repeats "experimental, unvalidated, can be
  wrong, not a safety verdict", and for Legitimate adds "does not mean this message is safe".
- The text box is cleared after analysis; no cookies, local/session storage or analytics.
- Verified by the real-model browser suite (`frontend/playwright.browser.config.ts`): only the site
  and the pinned Hugging Face revision are contacted, and no request URL or body contains message text.

## What visitors' networks and providers see

GitHub Pages (serves the site) and Hugging Face (serves the model files) see the visitor's IP
address and that the files were requested. Neither receives message text. The browser may keep
the model files in its cache for later visits; message text is never cached.

## Risks the owner accepts

1. Wrong predictions on real messages: a real scam predicted Legitimate may reassure someone; a
   genuine message predicted Fraud may lead someone to ignore or distrust a real sender.
2. People may paste secrets despite the warning; the text still never leaves the device.
3. A 676 MB first download; phones may lack memory (an error is shown, never a guess); no real phone
   has been tested, only phone-size emulation.
4. Dependence on Hugging Face keeping the pinned revision available (failure is shown honestly;
   there is no fallback).
5. No data-protection legal review has been done; none is claimed.

## Owner decision (owner only)

- [ ] Not approved.
- [x] Approved: release the static in-browser analyzer for visitors' real SMS, analysed only on
      their own device, knowing M4-Q is NOT READY and real-world error rates are unknown. This is
      an experimental, unvalidated classifier, not a validated fraud-detection service, and does
      not change C-12, C-13 or C-15.
- Date and name: 16 November 2026, repository owner (ARYANBUILDS707), in their words: "C-16
  approved (real messages). I approve the browser-only experimental release for real visitor SMS,
  acknowledging that M4-Q is NOT READY, accuracy is unknown, false predictions can occur, mobile
  compatibility is limited, and no independent legal review has been completed."

## Release (after approval)

Through the protected flow: PR into `dev`, release PR into `main`, then `.github/workflows/pages.yml`
(official GitHub Pages actions, `main` only) publishes `https://aryanbuilds707.github.io/Kavach2.0/`. To withdraw: disable the workflow
or the Pages site in repository settings. The Railway site is untouched either way.

Incident, 16 Nov 2026: while preparing this, the implementer pushed a `gh-pages` branch expecting
Pages to stay off; GitHub enabled it and an earlier fictional-only build was publicly reachable for
about 15 minutes before the branch was deleted and the URL returned 404. No approval was recorded;
none is implied.
