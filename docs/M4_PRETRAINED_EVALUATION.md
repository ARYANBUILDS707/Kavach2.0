# M4 Pretrained SMS Classifier Evaluation Track

Dated 5 November 2026. This is a separate track, authorized by the owner, alongside the original M4 custom-training plan ([M4_EVALUATION_PLAN.md](M4_EVALUATION_PLAN.md)). It **does not replace** that plan, the frozen splits, the review sheets, or the D04 requirements. The track asks one question: can an existing pretrained classifier give KAVACH a functioning local SMS inference prototype sooner, without fabricated accuracy and without weakening security or data governance?

**Status: isolated proof of concept only.**
- No model is connected to ingestion, the API, or the frontend.
- Nothing was trained or fine-tuned.
- No private or dataset message was sent to the model or to any external service.
- The downloaded weights are third-party work, not a KAVACH-trained model.
- None of the scores below is a KAVACH metric.

## Relationship to existing decisions

There is a conflict to resolve:
- PRD FR03 and D04 specify a "versioned TF-IDF classifier".
- `M4_EVALUATION_PLAN.md` says "a transformer is out of scope for M4".

This track runs because the owner explicitly changed the M4 prototype strategy on 5 November 2026. Before any pretrained model can reach the backend, the owner must record a PRD/D04 amendment covering:
- the model family;
- artifact size;
- the dependency set, including torch;
- explainability expectations.

Until then, FR03 stands as written.

The human-label gate is unchanged. Any validated claim about a model on KAVACH data still needs:
- the M4.2 label audit (95% Wilson lower bound ≥ 0.95, cluster-weighted);
- one logged final evaluation on the held-out split.

## Candidates audited

All metadata was read from the Hugging Face API and from files at the pinned revision. Self-reported accuracy is quoted only to describe each publisher's claim; it is **not** independent evidence and is not reproduced here as a KAVACH result.

| | Horizon-Labs/phishing-scam-detector-base | telecomsxchange/OpenTextShield | rehan-ml/scamshield-scam-detector |
| --- | --- | --- | --- |
| Pinned revision | `fa686fc0d6a3634092ada93a7c6b89ab0746b8f8` | `9e839db78bd1daff8062ae2f2638af0b64b416ae` | `0aca58d73bc34d17b247496aa5216fd04aaa39aa` |
| Last modified | 31 Oct 2026 | 8 Oct 2026 | 13 Jul 2026 |
| License | Apache-2.0; LICENSE + NOTICE in repo (base mmBERT is MIT) | MIT (card; GitHub LICENSE) | MIT (card only; no LICENSE file) |
| Base / size | mmBERT-base (ModernBERT), 307M params | mBERT cased, ~180M | DistilBERT uncased, 67M |
| Weights | `model.safetensors` 1,230,144,500 B, `1f056ed6…25af` (also fp32/int8 ONNX, not used) | `model.safetensors` 711,446,532 B, `8e5f65ef…1fe9` | `model.safetensors` 267,832,560 B, `3d722502…f84f`, **plus pickle `training_args.bin`** |
| Labels | `legitimate`, `spam`, `fraud` | `ham`, `spam`, `phishing` | none in config (`LABEL_0` safe, `LABEL_1` scam per card) |
| What the score means | `fraud` = phishing **and** scams (fake bank/delivery/tax, OTP theft, "hi mum", job/investment), kept apart from marketing spam; look-alike genuine notifications trained as legitimate | `phishing` = credential/money/data theft, apart from spam | "scam" includes all UCI spam: no spam/phishing separation |
| Training data | 98,379 synthetic messages written by Qwen3.8-27B (about 70 languages), 59,403 FineWeb web snippets; soft labels from that LLM teacher | public SMS corpora + in-house multilingual corpus; publisher states **UCI and Mishra & Soni texts appear verbatim in training** | UCI SMS Spam + EMSCAD job postings + ~255 LLM-written pairs |
| Overlap with KAVACH data | none published (UCI used only as their eval set); unknown whether the LLM teacher saw these corpora | **direct**: UCI, Mishra; IMC25 is the publisher's held-out set, so as far as published, it was not trained on | **direct**: UCI |
| Custom code / remote code | none (`auto_map` absent; `PreTrainedTokenizerFast`) | none | none |
| Integrity cross-check | LFS SHA-256 = publisher `SHA256SUMS` = git blob IDs at revision | LFS SHA-256 | LFS SHA-256 |
| Publisher-reported limits | ~11% false positives on normal messages at 0.5; misses most Portuguese smishing at 0.5; synthetic training; text only | phishing recall 45.7% on IMC25 and 6.1% on Mishra (scams blocked as "spam"); production API adds a normaliser not in the raw model | job-scam focus; v1–v3 over/under-corrected; not for standalone high-stakes use |
| Fit for KAVACH | **best**: right label semantics, independent of our evaluation data | runner-up: SMS-native, but cannot be evaluated fairly on UCI/Mishra; phishing class unreliable by its own report | **rejected**: wrong label semantics, pickle file present, weakest provenance |

## Selection: Horizon-Labs/phishing-scam-detector-base

Why:
- **Label semantics.** A separate `fraud` label covers phishing and scams, kept apart from spam. KAVACH needs exactly that separation (DATASET_GOVERNANCE.md label policy).
- **Evaluation independence.** It is the only candidate that can later be evaluated on IMC25, UCI and Mishra without known training contamination. OpenTextShield's publisher says UCI and Mishra are in its training data, so any score on them is meaningless.
- **Supply chain.**
  - Safetensors weights, no custom code.
  - The publisher ships `SHA256SUMS`, which matches the Hub's LFS hashes.
  - Explicit Apache-2.0 LICENSE with an attribution NOTICE.

Known costs:
- The largest of the three: 1.23 GB fp32.
- 8,192-token position embeddings; the runner truncates at 256 tokens.
- Repository modified only five days before the audit. The revision is pinned, so later changes cannot reach us.
- Trained on synthetic LLM text, and by its publisher's own figures has a high false-positive rate on genuine notifications.
- "Fraud" is broader than "phishing", so a mapping decision is needed before it feeds any KAVACH tier.

## Security and supply-chain controls (implemented in `experiments/pretrained/`)

- **Pinned revision.** Every file is fetched from `resolve/<40-hex commit>/`, never `main`.
- **Pinned hashes.** Each file is checked against its pinned size and SHA-256. Downloads are streamed to `.partial`, kept only on a match, and never overwrite a different existing file.
- **Resuming dropped transfers.**
  - Observed on 5 Nov 2026: this network cut the 1.23 GB transfer partway. The first attempt was correctly rejected on hash, and a curl check received only 994,045,243 bytes.
  - The fetcher now resumes with HTTP Range requests, at most 8 attempts, and restarts from zero if a server ignores the range.
  - A leftover `.partial` from an earlier run is discarded, never resumed.
  - The complete file is re-hashed before it is kept.
- **File allow-list.** Only `.json`, `.safetensors`, `LICENSE` and `NOTICE`. Pickle-type files (`.bin`, `.pt`, `.pth`, `.pkl`, `.ckpt`, `.joblib`) and code files are refused. A stray file in the model directory blocks loading.
- **Host allow-list.** https only, on Hugging Face hosts, redirects included. URLs (which carry signed tokens) are never printed.
- **Pre-load checks.** Before torch or transformers is imported, `config.json` must have no `auto_map` and must carry the pinned label map.
- **Offline loading.**
  - Loading uses `local_files_only=True`, `trust_remote_code=False` and `use_safetensors=True`.
  - `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are set; telemetry is off.
  - The label map is checked again after loading.
- **Unavailable means null.** A missing, modified or unloadable model returns `status: "unavailable"` with null scores, never zero.
- **No arbitrary input.** The runner classifies only the 14 fictional messages in `pretrained/demo.py`; there is no file, dataset or free-text option. Its report holds IDs, labels, scores and timings, never text.
- **Dependencies.**
  - The `pretrained` group (torch 2.14.1, transformers 5.20.2, tokenizers 0.23.3, safetensors 0.8.0, huggingface-hub 2.2.0, numpy 2.5.4) is opt-in. It is not installed by default, not used by CI, and never part of the API image.
  - Every pin is at least two weeks old.
  - OSV reports no advisories for any of the 69 locked packages (5 Nov 2026).
  - New transitive packages: httpx2/httpcore2 (pydantic project), truststore and hf-xet, all pulled in by huggingface-hub. The CUDA/triton entries are Linux-only markers and are never installed on macOS.
- **Storage.** Model files live in the ignored `data/models/<key>/<revision>/`.

## Local proof-of-concept results

Run on 5 November 2026 with `python -m pretrained run --repeats 5`:
- Machine: Apple M1 (8 GB RAM, 8 cores), macOS arm64, CPU only.
- Software: Python 3.12.13, torch 2.14.1 (4 threads), transformers 5.20.2.
- Network: the process ran under a `sandbox-exec` profile that **blocked all outbound network access**, so loading and inference were fully offline.
- Output: `experiments/reports/pretrained_poc.json` (IDs, labels and scores only; checked to contain no message text).

| Measure | Value |
| --- | --- |
| Download (one time) | 1,264,569,850 B over 7 files (weights 1.23 GB); 107 s after resume support was added |
| Model load (verify hashes + tokenizer + weights) | 9.47 s |
| Single-message latency, warm (70 samples) | median 38.3 ms, p95 47.8 ms, max 68.4 ms |
| Batch of 14 | 193.7 ms |
| Peak RSS | 35.5 MB before load, 665.3 MB after load, 933.1 MB after inference (`/usr/bin/time`: 978 MB max RSS, 0 swaps) |
| Batch and single results identical | yes |
| Failures | first download rejected on hash (truncated transfer, see above); no load or inference failures |

Predicted labels and uncalibrated scores on the 14 **fictional** messages. `fraud` = P(fraud); `unwanted` = P(fraud) + P(spam).

| ID | Author's intent | Label | fraud | unwanted |
| --- | --- | --- | --- | --- |
| demo-01 bank account block + link | phishing | fraud | 0.9958 | 0.9983 |
| demo-02 parcel customs fee + link | phishing | fraud | 0.9975 | 0.9993 |
| demo-03 OTP request | phishing | fraud | 0.9829 | 0.9942 |
| demo-04 tax refund, card details | phishing | fraud | 0.9940 | 0.9970 |
| demo-05 electricity disconnection, call officer | phishing | **legitimate** | 0.2638 | 0.3184 |
| demo-06 "Hi Mum" new number | scam | fraud | 0.9291 | 0.9438 |
| demo-07 job advance fee | scam | fraud | 0.9481 | 0.9934 |
| demo-08 Hinglish PAN update | phishing | fraud | 0.9892 | 0.9949 |
| demo-09 retail promotion | spam | spam | 0.0011 | 0.9960 |
| demo-10 prize text | spam | **fraud** | 0.7209 | 0.9528 |
| demo-11 genuine login code | legitimate | legitimate | 0.0129 | 0.0223 |
| demo-12 delivery done | legitimate | legitimate | 0.1216 | 0.2476 |
| demo-13 debit alert | legitimate | legitimate | 0.3873 | **0.5728** |
| demo-14 personal chat | legitimate | legitimate | 0.0180 | 0.1237 |

The label matched the authors' intent on 12 of 14 items. **This is a smoke test, not accuracy:**
- the messages were hand-written, not sampled;
- there are only 14 of them;
- "intent" is not an audited label.

Observations worth testing properly later, on validation data only:
- A link-free disconnection threat (demo-05) was missed. KAVACH's Indian scam patterns often ask the victim to call rather than click.
- A genuine debit alert (demo-13) crosses 0.5 on the "unwanted" score. This is consistent with the publisher's own warning about false positives on genuine notifications.
- Prize spam (demo-10) is labelled fraud. Whether that is wrong depends on the fraud/spam mapping the owner chooses.

## How it could connect to ingestion later (review only; not implemented)

The seam already exists: `IngestionService.ingest` runs analysis "outside any transaction" (`backend/src/kavach/services/ingestion.py`). It runs after the idempotency lookup and before the insert. A future change would keep all of the following:

| Property | How the model path keeps it |
| --- | --- |
| API-key authentication and source scoping | Inference starts only after the route's existing ingest-key dependency; nothing in the adapter sees keys |
| PostgreSQL idempotency | Replays return the stored result before inference (no recompute); a conflict (409) never reaches the model; concurrent first requests may both infer, and `insert_event_if_absent` still decides the single winner |
| Redis failure behavior and rate limits | Unchanged: the 30/min/key limit and bearer throttling run before ingestion; inference never touches Redis |
| Null/unknown when unavailable | The adapter returns `status: unavailable` with a reason (`model_not_deployed`, `model_unverified`, `inference_timeout`, `inference_saturated`); scores stay null and the tier stays `unknown` |
| Raw-message privacy | Text goes only to the in-process model; persisted `signals` hold scores, label, model version and duration, never text; nothing is logged |

**TD-18 blockers (required before any connection):**
1. Bounded admission control: `MAX_INFLIGHT_ANALYSES = 2`, with an immediate `inference_saturated` instead of queueing.
2. A per-inference timeout inside the 30-second request deadline.
3. A killable worker: a separate process that is terminated on timeout. A thread cannot stop a running torch call, so a timeout must not leave inference running.
4. Separate stage and total latency measurements.

Further requirements:
- A model manifest under an operator-controlled `MODEL_DIR` (ARCHITECTURE.md).
- A startup verification that returns unavailable on a hash mismatch.
- The resident memory of the model process, measured above, must fit the deployment host.

## What is required before any validated claim

1. The M4.2 human label audit passes (currently BLOCKED: 0 of 2,970 reviews).
2. The owner adopts a split (v1 frozen, or the proposed v2).
3. A threshold is chosen on **validation** only, and the fraud/spam mapping to KAVACH tiers is decided.
4. One logged final evaluation on the held-out test split through `HeldOutGuard`, by audited class, with Wilson intervals and denominators. It must be compared with the TF-IDF baseline from the original plan.
5. Calibration is checked on validation before any score is shown as a probability.
