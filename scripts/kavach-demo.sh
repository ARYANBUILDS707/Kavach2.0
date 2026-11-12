#!/usr/bin/env bash
# KAVACH local demo launcher (docs/LOCAL_DEMO.md, docs/EXPERIMENTAL_SMS_ANALYSIS.md).
#
#   scripts/kavach-demo.sh start                 normal demo: the SMS model stays disabled
#   scripts/kavach-demo.sh start --experimental  decision C-13: real pinned-model predictions,
#                                                local only, fictional messages only, unvalidated
#   scripts/kavach-demo.sh stop                  stop PostgreSQL and Redis (data kept)
#   scripts/kavach-demo.sh reset                 delete the demo services, data and generated secrets
#
# Everything binds to 127.0.0.1. Secrets are generated once into $KAVACH_DEMO_HOME (mode 600) and
# never printed. The experimental settings live only in this process's environment, never in a
# file, so a plain `start` is always model-disabled. Overrides: KAVACH_DEMO_HOME (default
# ~/.kavach-demo), KAVACH_DEMO_WEB_PORT (5173), KAVACH_DEMO_DB_PORT (55532),
# KAVACH_DEMO_REDIS_PORT (56479), KAVACH_DEMO_MODEL_DIR (absolute; default ./data/models, where
# the verified artifacts live outside Git). The API port is 8000 because the Vite proxy targets it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${KAVACH_DEMO_HOME:-$HOME/.kavach-demo}"
WEB_PORT="${KAVACH_DEMO_WEB_PORT:-5173}"
DB_PORT="${KAVACH_DEMO_DB_PORT:-55532}"
REDIS_PORT="${KAVACH_DEMO_REDIS_PORT:-56479}"
API_PORT=8000
PROJECT="kavach-demo"
COMPOSE=(docker compose -p "$PROJECT" -f "$ROOT/deployment/compose.dev.yml")
DEMO_MODEL_MANIFEST="$ROOT/deployment/models/sms_classifier.horizon.v1.json"
DEMO_MODEL_DIR="${KAVACH_DEMO_MODEL_DIR:-$ROOT/data/models}"
PYTHON_VERSION="3.12.13"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || fail "'$tool' is required; see docs/LOCAL_DEMO.md prerequisites."
  done
}

port_free() {
  ! lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1
}

services_env() {
  if [[ ! -f "$STATE/services.env" ]]; then
    say "Generating local service passwords in $STATE (kept private, never printed)"
    {
      for name in POSTGRES MIGRATOR APP RETENTION REDIS; do
        printf 'export KAVACH_DEV_%s_PASSWORD=%s\n' "$name" "$(openssl rand -hex 24)"
      done
    } >"$STATE/services.env"
  fi
  # shellcheck disable=SC1091
  source "$STATE/services.env"
  export KAVACH_DEV_POSTGRES_PORT="$DB_PORT" KAVACH_DEV_REDIS_PORT="$REDIS_PORT"
}

app_keys() {
  if [[ ! -f "$STATE/app-keys.env" ]]; then
    {
      printf "export RATE_LIMIT_HMAC_KEY='%s'\n" "$(openssl rand -hex 32)"
      for name in AUDIT SUBSCRIBER PAYLOAD; do
        printf "export %s_HMAC_KEYS='{\"demo1\":\"%s\"}'\n" "$name" "$(openssl rand -hex 32)"
        printf 'export %s_HMAC_ACTIVE_VERSION=demo1\n' "$name"
      done
    } >"$STATE/app-keys.env"
  fi
  # shellcheck disable=SC1091
  source "$STATE/app-keys.env"
  export APP_ENV=development
  export APP_ORIGIN="http://127.0.0.1:$WEB_PORT"
  export DATABASE_URL="postgresql+psycopg://kavach_app:${KAVACH_DEV_APP_PASSWORD}@127.0.0.1:${DB_PORT}/kavach_dev"
  export MIGRATION_DATABASE_URL="postgresql+psycopg://kavach_migrator:${KAVACH_DEV_MIGRATOR_PASSWORD}@127.0.0.1:${DB_PORT}/kavach_dev"
  export REDIS_URL="redis://:${KAVACH_DEV_REDIS_PASSWORD}@127.0.0.1:${REDIS_PORT}/0"
}

model_settings() {
  local experimental="$1"
  # Always start from a model-disabled environment, whatever the calling shell exported.
  unset SMS_MODEL_AUTHORIZATION SMS_WORKER_PYTHON MODEL_DIR MODEL_MANIFEST_PATH
  export SMS_WORKER_ENABLED=false
  [[ "$experimental" == "yes" ]] || return 0
  local artifact_dir
  artifact_dir="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifact_dir"])' "$DEMO_MODEL_MANIFEST")"
  [[ -d "$DEMO_MODEL_DIR/$artifact_dir" ]] \
    || fail "Model artifacts not found in data/models/$artifact_dir (never in Git; see docs/M4_I1_SMS_WORKER_REPORT.md)."
  say "Preparing the isolated SMS worker environment (model group, offline at run time)"
  (cd "$ROOT" && uv sync -q --project workers/sms --locked --group model --python "$PYTHON_VERSION" >/dev/null)
  export SMS_WORKER_ENABLED=true
  export SMS_MODEL_AUTHORIZATION=experimental-local-unvalidated
  export SMS_WORKER_PYTHON="$ROOT/workers/sms/.venv/bin/python"
  export MODEL_DIR="$DEMO_MODEL_DIR"
  export MODEL_MANIFEST_PATH="$DEMO_MODEL_MANIFEST"
}

first_accounts() {
  [[ -f "$STATE/accounts-created" ]] && return 0
  say "First run: create the synthetic demo accounts (passwords are typed, hidden, never stored here)"
  echo "Admin account 'demo-admin' (at least 12 characters):"
  "$ROOT/backend/.venv/bin/python" -m kavach.cli user create \
    --username demo-admin --display-name "Demo Admin" --bootstrap
  # Recorded at once: bootstrap succeeds only while no admin exists, so it must never be retried.
  touch "$STATE/accounts-created"
  local answer=""
  read -r -p "Also create a viewer account 'demo-viewer' for the authorization demo? [y/N] " answer || answer=""
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    echo "Type demo-admin's password, then the new viewer password twice:"
    "$ROOT/backend/.venv/bin/python" -m kavach.cli user create \
      --username demo-viewer --display-name "Demo Viewer" --role viewer --actor demo-admin \
      || echo "Viewer not created; you can add it later with the operator CLI (docs/LOCAL_DEMO.md)."
  fi
}

# The demo must only ever migrate or sign in against its own disposable database.
check_own_database() {
  local published
  published="$("${COMPOSE[@]}" port postgres 5432 2>/dev/null || true)"
  [[ "$published" == "127.0.0.1:$DB_PORT" ]] \
    || fail "Port $DB_PORT is not served by the '$PROJECT' PostgreSQL container; refusing to touch another database."
}

wait_for_backend() {
  local log="$1" experimental="$2"
  for _ in $(seq 1 120); do
    curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health" && break
    kill -0 "$BACKEND_PID" 2>/dev/null || fail "The backend stopped during startup; see $log (operational events only, no message text)."
    sleep 0.5
  done
  curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health" || fail "The backend did not become healthy; see $log."
  [[ "$experimental" == "yes" ]] || return 0
  for _ in $(seq 1 120); do
    if grep -q "sms_worker.ready" "$log"; then
      echo "Model worker ready (self-test passed)."
      return 0
    fi
    if grep -qE "sms_worker\.(unverified|failure)" "$log"; then
      echo "WARNING: the model worker is not ready; submissions will be stored as 'analysis unavailable'."
      return 0
    fi
    sleep 1
  done
  echo "WARNING: the model worker is still starting; the UI shows its state honestly meanwhile."
}

start() {
  local experimental="no"
  [[ "${1:-}" == "--experimental" ]] && experimental="yes"
  [[ -z "${1:-}" || "$experimental" == "yes" ]] || fail "Unknown option '${1:-}'. Use: start [--experimental]"
  need docker uv npm openssl curl lsof python3
  port_free "$API_PORT" || fail "Port $API_PORT is in use; stop the other backend first."
  port_free "$WEB_PORT" || fail "Port $WEB_PORT is in use; stop the other dev server or set KAVACH_DEMO_WEB_PORT."
  umask 077
  mkdir -p "$STATE"
  services_env
  app_keys
  model_settings "$experimental"

  say "Starting PostgreSQL and Redis (project $PROJECT, loopback ports $DB_PORT and $REDIS_PORT)"
  "${COMPOSE[@]}" up --detach --wait --wait-timeout 180 >/dev/null
  check_own_database

  say "Installing the locked backend environment and applying migrations"
  (cd "$ROOT" && uv sync -q --project backend --locked --python "$PYTHON_VERSION" >/dev/null)
  (cd "$ROOT" && uv run -q --project backend --locked alembic -c backend/alembic.ini upgrade head >/dev/null)
  (cd "$ROOT" && first_accounts)

  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    say "Installing the locked frontend dependencies"
    (cd "$ROOT/frontend" && npm ci --no-audit --no-fund >/dev/null)
  fi

  local log="$STATE/backend.log"
  say "Starting the API on 127.0.0.1:$API_PORT (log: $log)"
  (cd "$ROOT" && exec backend/.venv/bin/python -m uvicorn kavach.main:create_app --factory \
    --host 127.0.0.1 --port "$API_PORT" --no-access-log --no-proxy-headers) >"$log" 2>&1 &
  BACKEND_PID=$!
  WEB_PID=""
  trap 'kill "$BACKEND_PID" ${WEB_PID:+"$WEB_PID"} 2>/dev/null || true' EXIT
  trap 'exit 130' INT TERM
  wait_for_backend "$log" "$experimental"

  if [[ "$experimental" == "yes" ]]; then
    cat <<EOF

  ┌───────────────────────────────────────────────────────────────────────────┐
  │ EXPERIMENTAL LOCAL MODE (decision C-13)                                   │
  │ Real predictions from the pinned model, uncalibrated, NOT validated on    │
  │ KAVACH data. Fictional messages only. Not for real data or production.    │
  └───────────────────────────────────────────────────────────────────────────┘
EOF
  else
    echo
    echo "  Normal mode: the SMS model is disabled; analyses show as unavailable."
  fi
  cat <<EOF

  Open http://127.0.0.1:$WEB_PORT and sign in as demo-admin.
  Fictional messages to try on Analyze SMS:
    FICTIONAL DEMO: Your Northpay account is frozen. Confirm your PIN at http://northpay-unlock.example now.
    FICTIONAL DEMO: Diwali sale at Fabrikart! Flat 60% off this weekend only. Reply STOP to opt out.
    FICTIONAL DEMO: Running 15 minutes late for the meeting, please start without me.
  Press Ctrl-C to stop the API and the web server (database data is kept).

EOF
  cd "$ROOT/frontend"
  # In the background with `wait`, so Ctrl-C or a TERM stops both servers at once.
  npx vite --host 127.0.0.1 --port "$WEB_PORT" --strictPort &
  WEB_PID=$!
  wait "$WEB_PID"
}

stop() {
  need docker
  KAVACH_DEV_POSTGRES_PASSWORD=x KAVACH_DEV_MIGRATOR_PASSWORD=x KAVACH_DEV_APP_PASSWORD=x \
    KAVACH_DEV_RETENTION_PASSWORD=x KAVACH_DEV_REDIS_PASSWORD=x "${COMPOSE[@]}" stop
}

reset() {
  need docker
  # Only the fixed demo project and the launcher's own files are ever removed.
  local answer=""
  read -r -p "Delete the '$PROJECT' database, Redis data and generated secrets in $STATE? [y/N] " answer || answer=""
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Nothing deleted."; return 0; }
  KAVACH_DEV_POSTGRES_PASSWORD=x KAVACH_DEV_MIGRATOR_PASSWORD=x KAVACH_DEV_APP_PASSWORD=x \
    KAVACH_DEV_RETENTION_PASSWORD=x KAVACH_DEV_REDIS_PASSWORD=x "${COMPOSE[@]}" down --volumes
  rm -f "$STATE/services.env" "$STATE/app-keys.env" "$STATE/accounts-created" "$STATE/backend.log"
  echo "Demo services and generated secrets removed."
}

case "${1:-}" in
  start) shift; start "${1:-}" ;;
  stop) stop ;;
  reset) reset ;;
  *) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
