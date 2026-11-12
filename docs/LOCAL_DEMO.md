# KAVACH Local Demo Procedure (SMS MVP-1)

This procedure runs the full KAVACH SMS MVP-1 stack on one machine for a controlled demonstration: browser UI, API, PostgreSQL and Redis. It uses only synthetic accounts and fictional messages. It is not a deployment. Everything binds to `127.0.0.1`, and the SMS model stays **disabled** until the M4-Q decision authorizes it.

To show real model predictions instead, follow steps 1–4 below, then switch on the owner-approved local experimental mode in [EXPERIMENTAL_SMS_ANALYSIS.md](EXPERIMENTAL_SMS_ANALYSIS.md) (decision C-13: fictional messages only, not validated).

It uses a separate Compose project, `kavach-demo`, on its own ports, so an existing `kavach-dev` stack and its data are never touched. This is the configuration verified in [MVP1_INTEGRATION_REPORT.md](MVP1_INTEGRATION_REPORT.md).

## Prerequisites

- Docker with Compose v2.
- uv 0.11.16 with Python 3.12.13 (`uv` installs the interpreter if needed).
- Node.js 24.16.0 (see `frontend/.nvmrc`).
- A checkout of `dev` at `61cbffa` (SMS MVP-1 integrated) or later.
- Ports `55532`, `56479`, `8000` and `5173` must be free.

Run every command from the repository root in one zsh or bash terminal, except where step 6 says to open a second terminal.

## 1. Service passwords (kept outside the repository)

```sh
umask 077
mkdir -p ~/.kavach-demo
for n in POSTGRES MIGRATOR APP RETENTION REDIS; do
  echo "export KAVACH_DEV_${n}_PASSWORD=$(openssl rand -hex 24)"
done > ~/.kavach-demo/services.env
echo "export KAVACH_DEV_POSTGRES_PORT=55532 KAVACH_DEV_REDIS_PORT=56479" >> ~/.kavach-demo/services.env
```

## 2. Start PostgreSQL and Redis

```sh
. ~/.kavach-demo/services.env
docker compose -p kavach-demo -f deployment/compose.dev.yml up --detach --wait
```

On first start, the init script creates the least-privilege roles and the `kavach_dev` and `kavach_test` databases.

## 3. Backend settings

The variable names are documented in `.env.example`. Generate fresh values; never reuse development or real keys.

```sh
. ~/.kavach-demo/services.env
k() { openssl rand -hex 32; }
cat > ~/.kavach-demo/runtime.env <<EOF
export APP_ENV=development
export DATABASE_URL='postgresql+psycopg://kavach_app:${KAVACH_DEV_APP_PASSWORD}@127.0.0.1:55532/kavach_dev'
export MIGRATION_DATABASE_URL='postgresql+psycopg://kavach_migrator:${KAVACH_DEV_MIGRATOR_PASSWORD}@127.0.0.1:55532/kavach_dev'
export REDIS_URL='redis://:${KAVACH_DEV_REDIS_PASSWORD}@127.0.0.1:56479/0'
export APP_ORIGIN='http://127.0.0.1:5173'
export RATE_LIMIT_HMAC_KEY='$(k)'
export AUDIT_HMAC_KEYS='{"demo1":"$(k)"}'
export AUDIT_HMAC_ACTIVE_VERSION=demo1
export SUBSCRIBER_HMAC_KEYS='{"demo1":"$(k)"}'
export SUBSCRIBER_HMAC_ACTIVE_VERSION=demo1
export PAYLOAD_HMAC_KEYS='{"demo1":"$(k)"}'
export PAYLOAD_HMAC_ACTIVE_VERSION=demo1
export SMS_WORKER_ENABLED=false
EOF
```

## 4. Install, migrate and create synthetic accounts

```sh
uv sync --project backend --locked --python 3.12.13
. ~/.kavach-demo/runtime.env
uv run --project backend --locked alembic -c backend/alembic.ini upgrade head

# Synthetic admin: the CLI prompts for the password twice (input hidden).
backend/.venv/bin/python -m kavach.cli user create --username demo-admin --display-name "Demo Admin" --bootstrap

# Synthetic viewer, for the authorization demo: prompts for demo-admin's password, then the new one twice.
backend/.venv/bin/python -m kavach.cli user create --username demo-viewer --display-name "Demo Viewer" --role viewer --actor demo-admin
```

Keep the two passwords somewhere private for the demo. Never type them into a recording, a slide or a URL.

## 5. Start the backend (terminal 1)

```sh
. ~/.kavach-demo/runtime.env
backend/.venv/bin/python -m uvicorn kavach.main:create_app --factory \
  --host 127.0.0.1 --port 8000 --no-access-log --no-proxy-headers
```

Check: `curl -s http://127.0.0.1:8000/health` returns `"status":"ok"` with `"analysis_ready":false`.

## 6. Start the frontend (terminal 2)

```sh
cd frontend
npm ci
npm run dev
```

The Vite proxy sends `/api` to `127.0.0.1:8000` (`frontend/vite.config.ts`). Open **http://127.0.0.1:5173/welcome**. Use `127.0.0.1`, not `localhost`: the backend accepts only the exact origin in `APP_ORIGIN`.

## 7. Pre-demo check (two minutes)

1. `/welcome` loads, and the "Pause motion" button works.
2. Sign in as `demo-admin`. Overview shows "SMS model: Disabled".
3. Submit one fictional message on **Analyze SMS**, for example `FICTIONAL DEMO: Your parcel is held, pay the release fee at the link.` The receipt appears, and the incident shows "analysis unavailable" with tier "unknown".
4. Sign out. Sign in as `demo-viewer`: there is no Analyze page, and `/analyze` says "You don't have access".

The backend allows 120 page reads per minute per user. If you click very fast, a "Too many requests · Resuming in N seconds" banner is the documented limit, not a crash. Wait for the countdown.

## 8. Reset or tear down

```sh
docker compose -p kavach-demo -f deployment/compose.dev.yml down --volumes   # demo project only
rm -rf ~/.kavach-demo
```

`down --volumes` deletes only the `kavach-demo` project's data. Never run it against the `kavach-dev` project unless you mean to erase that data.

## If something fails

| Symptom | Cause and fix |
| --- | --- |
| Sign-in says the service is unavailable (503) | Redis or PostgreSQL is not running, or `~/.kavach-demo/runtime.env` was not sourced in terminal 1 |
| Sign-in refused on `localhost:5173` | Use `http://127.0.0.1:5173`, which must match `APP_ORIGIN` |
| `Authentication requires: …` at startup | A variable from step 3 is missing; re-source `~/.kavach-demo/runtime.env` |
| Port already in use | Stop the other process, or change `KAVACH_DEV_*_PORT` and the URLs together |
| "Too many requests" banner | The read limit (120 per minute per user); wait for the countdown |
