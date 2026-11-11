# workers/sms: isolated SMS inference worker

The child process that runs the pinned pretrained SMS model for KAVACH.
- Contract: [docs/M4_SMS_INFERENCE_ARCHITECTURE.md](../../docs/M4_SMS_INFERENCE_ARCHITECTURE.md).
- Results: [docs/M4_I1_SMS_WORKER_REPORT.md](../../docs/M4_I1_SMS_WORKER_REPORT.md).

Third-party weights (Horizon-Labs/phishing-scam-detector-base), not a KAVACH-trained model. The outputs are **uncalibrated** and not validated on KAVACH data.

- **Own locked environment.** The API never installs or imports anything from here.
  - The default install is standard library only: protocol, manifest and artifact checks.
  - torch and transformers are the opt-in `model` group, at exactly the versions in the manifest. The worker refuses to start on any other version.
- **Started only by the API's supervisor** (`kavach.models.sms_worker`):
  - talks over its own stdin/stdout, with no socket or listener;
  - never logs text and returns numbers and fixed codes only.
- **Startup checks, before torch is imported:**
  - the manifest (`deployment/models/`) is validated;
  - every file under `MODEL_DIR/<artifact_dir>/` is checked for size and SHA-256;
  - a stray file, pickle or code file, or a config that requests custom code, refuses startup.
- **Ready.** It loads once with `trust_remote_code=False`, safetensors only, offline, on CPU, then passes the fictional canary self-test before reporting ready.

```sh
uv sync --project workers/sms --locked                  # default: tests only, no torch
uv run --project workers/sms --locked pytest workers/sms/tests
uv sync --project workers/sms --locked --group model    # the real runtime (~1 GB installed)
```

The real-model smoke test runs through the supervisor from the backend project. It is opt-in and local, needs the model group plus the verified artifacts in `data/models/`, and runs under a network denial:

```sh
sandbox-exec -p '(version 1)(allow default)(deny network-outbound (remote ip))' \
  uv run --project backend --locked pytest backend/tests/test_sms_worker_model.py -m model -s
```

Not connected to ingestion (M4-I.2).
