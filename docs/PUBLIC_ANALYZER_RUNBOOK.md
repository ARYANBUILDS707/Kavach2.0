# Public analyzer: local testing and gated hosting

C-13 permits local fictional tests only. C-15 remains unapproved and M4-Q NOT READY.
`PUBLIC_ANALYZER_MODE=hosted` refuses to start unless every condition in
[C15_HOSTED_INFERENCE_DECISION.md](C15_HOSTED_INFERENCE_DECISION.md) §6 is met, the first of which
is an approval value only the owner sets after recording the decision. Hosted inference is not
authorized or enabled anywhere today; the public site runs with the analyzer disabled.

## Local use

Use a separate checkout/ports from any running demo. Reuse the existing verified model and isolated
worker environment; never use an evaluation dataset as a UI fixture or download a different model.
Install locked backend/frontend dependencies only if missing. Start a private local Redis instance
with persistence off. Provide these settings through a secure local environment (never commit it):

- `PUBLIC_ANALYZER_ONLY=true`, `PUBLIC_ANALYZER_MODE=local-experimental`, `APP_ENV=development`
- `APP_ORIGIN=http://127.0.0.1:5184`
- `REDIS_URL` for the isolated Redis and a random `RATE_LIMIT_HMAC_KEY` of at least 32 characters
- `SMS_WORKER_ENABLED=true`, `SMS_MODEL_AUTHORIZATION=experimental-local-unvalidated`
- absolute `SMS_WORKER_PYTHON`, `MODEL_DIR`, `MODEL_MANIFEST_PATH`
- absolute `SMS_WORKER_LOCK_PATH` in a private writable directory if models are read-only

Do not supply database, audit, subscriber or payload keys to this service. Do not expose it through
a tunnel, public interface or proxy. Start from repository root:

```sh
uv run --project backend --locked uvicorn kavach.main:create_app --factory \
  --host 127.0.0.1 --port 8184 --no-access-log --no-proxy-headers
```

From `frontend/`:

```sh
KAVACH_API_TARGET=http://127.0.0.1:8184 npm run dev -- --port 5184
```

Open `http://127.0.0.1:5184/analyze`. Only invented messages. A starting/missing/locked worker returns
unavailable, never a fake prediction. For built same-origin serving, `npm run build`, set
`PUBLIC_FRONTEND_DIR` to the absolute `frontend/dist`, set the matching loopback `APP_ORIGIN`,
and visit that backend port. `/admin` and private APIs do not exist on the isolated host.

## Verification

```sh
uv run --project backend --locked pytest backend/tests
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format --check backend
# Real disposable PostgreSQL/Redis; configure TEST_* URLs as in README:
uv run --project backend --locked pytest backend/tests -m integration
# Real local artifacts/worker + TEST_REDIS_URL; fictional inputs only:
uv run --project backend --locked pytest backend/tests/test_public_analyzer_model.py -m model
cd frontend
npm run verify
# Start the real backend on 8184 first, with APP_ORIGIN matching the browser:
npx playwright test --config playwright.public.config.ts
```

Default unit tests isolate model doubles under tests only. The opt-in model test requires
`SMS_WORKER_PYTHON`, `MODEL_DIR`, `TEST_REDIS_URL` and fails if the real worker cannot become ready.
Browser tests never mock the API. Existing protected-admin journeys still require their separate
credentials/backend setup. These checks establish plumbing, not accuracy or calibration.

## Docker image

Build from repository root:

```sh
docker build -f deployment/Dockerfile.public -t kavach-public-analyzer:local .
# site-only image without the model (smaller; the analyzer then reports the model unavailable):
docker build -f deployment/Dockerfile.public --build-arg KAVACH_MODEL_FETCH=false -t kavach-public-analyzer:site .
```

The image installs both locked Python environments, builds the static frontend and, by default,
**fetches the pinned weights at build time** (`workers/sms/src/kavach_sms_worker/provision.py`): each
file named in `deployment/models/sms_classifier.horizon.v1.json` is downloaded from the manifest's
repository at the pinned revision, checked against the manifest's size and SHA-256, and installed
read-only under `/models` only when every file matches. A mismatch fails the build; nothing is
committed to Git, and the running worker verifies the files again at every start. The runtime runs
as UID 10001, one API process, with `PUBLIC_ANALYZER_MODE=disabled` and the worker off unless the
service's variables say otherwise. `/tmp` must be writable for the worker lock and home.

Why the weights are in the image and not on a volume: Railway mounts volumes with root ownership
and its documented workaround is to run the container as root (`RAILWAY_RUN_UID=0`), which this
service must not do; an image is also verified once, read-only, and rolled back as a unit.

## Measurements (16 November 2026)

Docker Desktop on Apple M1 (Linux VM, `--cpus 2`, swap off), the real model, fictional messages.
These are not Railway hardware numbers; repeat the rate-limit and latency checks there.

| Container cap | Worker RSS | Container usage | Reclaim events | Single analysis | Two concurrent |
| --- | --- | --- | --- | --- | --- |
| 2 GB | 1.64 GB | 1.77 GiB | 343 | 132–350 ms | 295–427 ms |
| 1.5 GB | 1.63 GB | 1.39 GiB | 2,491 | 258–476 ms | 158–292 ms |
| 1 GB | 1.28 GB | 941 MiB | 16,372 (+ socket throttling) | 413–1,029 ms | 1.9–2.6 s |

Worker ready 26–45 s after container start. The weights are memory-mapped, so the container fills
whatever cap it is given with page cache and survives a 1 GB cap only by re-reading weights from
disk: not a hosting size. Image: 9.5 GB uncompressed, 3.48 GB gzip-compressed, before weights.
The supervisor's default `SMS_WORKER_MAX_RSS_MB=1536` is **below** the measured steady RSS and
would restart the worker between requests; hosted configuration sets 2560.

## Railway activation (owner actions; only after C15_HOSTED_INFERENCE_DECISION.md §8 and §9)

Published Railway figures (docs, 16 November 2026): Trial 1 GB RAM, 0.5 GB volume, 4 GB image, $5
one-time credit; Hobby $5/month with $5 usage included, 48 GB RAM, 100 GB image; RAM $10/GB-month,
CPU $20/vCPU-month, egress $0.05/GB; usage hard limit minimum $10 (reaching it stops all
workloads). The Trial cannot run the model (RAM and image size); Hobby can.

1. **Plan and cap (billing; separate approval):** upgrade the workspace to Hobby. Workspace →
   Usage → Set Usage Limits: hard limit as decided (recommended $30), soft alert $20.
2. **Redis:** in the project, add a Redis service from Railway's template. Keep it on the private
   network only (no public TCP proxy/domain). In the Kavach2.0 service, reference its private
   connection URL as `REDIS_URL` (a variable reference to the Redis service's `redis://…railway.internal…`
   URL). Persistence is unnecessary; the keys live 60 seconds.
3. **Service variables** (Kavach2.0 → Variables). Names only; values never go in Git or chat:
   - `APP_ORIGIN` = the exact public origin, e.g. `https://kavach20-production.up.railway.app`
   - `PUBLIC_ANALYZER_MODE=hosted`
   - `PUBLIC_ANALYZER_HOSTED_APPROVAL=c15-owner-approved` (the owner's act of approval)
   - `SMS_WORKER_ENABLED=true`
   - `PUBLIC_ANALYZER_CLIENT_IP_HEADER=X-Real-IP` (Railway's documented client-address header)
   - `REDIS_URL` (step 2), `RATE_LIMIT_HMAC_KEY` (≥32 random characters, e.g. `openssl rand -hex 32`)
   - `SMS_WORKER_MAX_RSS_MB=2560`, `SMS_WORKER_START_TIMEOUT_SECONDS=180`
   - optional tuning: `PUBLIC_ANALYZER_IP_LIMIT_PER_MINUTE` (5), `PUBLIC_ANALYZER_GLOBAL_LIMIT_PER_MINUTE` (60), `PUBLIC_ANALYZER_MAX_CHARS` (500)
   - **do not set** `SMS_MODEL_AUTHORIZATION`, `DATABASE_URL` or any admin/audit/ingestion key.
   The image already sets `APP_ENV=pilot`, `PUBLIC_ANALYZER_ONLY=true`, the model paths and the lock path.
4. **Replica limits:** Settings → Deploy → Replica Limits (if shown on the plan): memory 3 GB,
   CPU 2 vCPU, 1 replica. Lower memory crashes the worker under load.
5. **Deploy** from `main` (the image build now downloads ~1.2 GB of weights; expect a longer build).
   The build log must contain `model horizon-phishing-scam-base@fa686fc0d6a3+m1:… verified`.
6. **Verify** (fictional text only): `GET /api/v1/public/analyzer` → `enabled: true`; a prediction
   in the browser at `/analyze`; `/admin` and `/api/v1/incidents` → 404; six quick requests from one
   client → the sixth is 429 (if every request is 503 the edge header is not arriving: the service
   is failing closed as designed; pause and investigate); the same six with different spoofed
   `X-Real-IP` values → still 429 (the edge overwrites the header; if not, pause and stop).
7. **Kill switch and rollback:**
   - instant: on the Redis service (`railway connect` or the Data tab) `SET kavach:pilot:public:paused 1`
     → every analysis answers 503 `ANALYZER_PAUSED` at once; `DEL kavach:pilot:public:paused` resumes;
   - configuration: set `PUBLIC_ANALYZER_MODE=disabled` → redeploy (2–3 minutes; the site stays up);
   - rollback: Deployments → the previous deployment → Rollback.

The configuration honors Railway's `PORT` and liveness health-check behavior:
[Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[health checks](https://docs.railway.com/deployments/healthchecks),
[config schema](https://railway.com/railway.schema.json),
[client-address header](https://docs.railway.com/networking/public-networking/specs-and-limits),
[volumes](https://docs.railway.com/reference/volumes), [plans](https://docs.railway.com/pricing/plans),
[usage limits](https://docs.railway.com/reference/usage-limits).
A successful liveness check does not prove inference readiness.

No resources have been provisioned or bought by this work. Costs are estimates in the decision
record until Railway's usage page shows real numbers.
