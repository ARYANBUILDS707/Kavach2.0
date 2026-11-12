# Public analyzer: local testing and gated hosting

C-13 permits local fictional tests only. C-15 remains unapproved and M4-Q NOT READY. The code rejects
`PUBLIC_ANALYZER_MODE=hosted`, even with the reserved approval token. No deployment is authorized.

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

## Docker and Railway preparation (do not deploy yet)

Build from repository root:

```sh
docker build -f deployment/Dockerfile.public -t kavach-public-analyzer:local .
```

The image installs both locked Python environments and builds the static frontend. It runs as UID
10001, one API process, with hosted inference and the worker disabled. No credentials, model binaries
or datasets are copied. Mount only manifest-verified models read-only at `/models` when a release is
authorized; `/tmp` must be writable for the worker lock/home. Apply a measured container memory/CPU
limit; the supervisor RSS threshold is a between-request restart trigger, not a cgroup ceiling.

After separate owner authorization and all launch gates pass:

1. Record C-15, M4-Q GO/approved CONDITIONAL or explicit owner waiver, privacy review/notice/contact,
   edge-log retention, operator, abuse controls, incident response and D10 hosting/budget decision.
2. Obtain independent security review, package/model advisory and license/provenance checks, and
   measured load/timeout/restart evidence on target hardware. Verify trusted client-IP handling
   against the actual edge; the shipped command ignores forwarding headers, sharing limits safely.
3. Review a separate change enabling restricted hosted mode with the approved gates. No environment
   variable in this PR can bypass the current hard block. Review kill-switch behavior by restarting
   with `PUBLIC_ANALYZER_MODE=disabled` (not an instantaneous live config reload).
4. In a new Railway service, select the repository root and config file
   `/deployment/railway.public.json`. Do not attach the admin PostgreSQL or its secrets. Use a separate
   private Redis with persistence off, a new HMAC key, approved HTTPS origin and read-only verified
   model provisioning. Keep one replica until measured; configure host resource/spend limits.
5. Check `/health` for liveness only, then check the disabled status and rejection behavior; after
   approval exercise fictional end-to-end predictions, saturation, Redis outage and timeouts.
   Confirm TLS, CSP, no input/URL logging, admin-route absence, monitoring and rollback before traffic.

The configuration honors Railway's `PORT` and liveness health-check behavior:
[Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[health checks](https://docs.railway.com/deployments/healthchecks),
[config schema](https://railway.com/railway.schema.json).
A successful liveness check does not prove inference readiness. Proxy/header trust remains a launch
check: [Railway network specifications](https://docs.railway.com/networking/public-networking/specs-and-limits).

No resources have been provisioned. Hosting would incur compute, Redis, storage and egress charges;
no price or capacity is promised before hardware measurement and an owner-approved budget.
