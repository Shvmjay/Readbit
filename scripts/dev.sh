#!/usr/bin/env bash
# Run Readbit locally with one command (Mac/Linux). No database server, Redis, Docker or API key needed.
#
#   ./scripts/dev.sh           install what's missing, build, start API + web, open the browser
#   ./scripts/dev.sh --reset   same, but start with an empty local database and storage
#
# Optional environment: API_PORT (default 8000), WEB_PORT (default 3000), NO_OPEN=1 (don't open a browser).
# Data lives in .data/local/ (git-ignored). Press Ctrl+C to stop both servers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/services/api"
WEB_DIR="$ROOT/apps/web"
DATA_DIR="$ROOT/.data/local"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

say() { printf '\033[1;35m[readbit]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[readbit] %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- prerequisites
PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || die "Python 3.11 or newer is required (found: $(python3 --version 2>&1 || echo none)). Install it from https://www.python.org/downloads/"
command -v node >/dev/null 2>&1 || die "Node.js 20 or newer is required. Install it from https://nodejs.org/"
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || die "Node.js 20 or newer is required (found $(node --version)). Install it from https://nodejs.org/"
command -v npm >/dev/null 2>&1 || die "npm is required (it ships with Node.js)."

port_free() { "$PY" -c 'import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) else 1)' "$1"; }
pick_port() {
  local p="$1"
  for _ in $(seq 1 20); do port_free "$p" && { echo "$p"; return; }; p=$((p + 1)); done
  die "No free port found near $1."
}
NEW_API_PORT="$(pick_port "$API_PORT")"; [ "$NEW_API_PORT" = "$API_PORT" ] || say "Port $API_PORT is busy; using $NEW_API_PORT for the API."
NEW_WEB_PORT="$(pick_port "$WEB_PORT")"; [ "$NEW_WEB_PORT" = "$WEB_PORT" ] || say "Port $WEB_PORT is busy; using $NEW_WEB_PORT for the web app."
API_PORT="$NEW_API_PORT"; WEB_PORT="$NEW_WEB_PORT"

if [ "${1:-}" = "--reset" ]; then
  say "Resetting local data in $DATA_DIR"
  rm -rf "$DATA_DIR"
fi
mkdir -p "$DATA_DIR"

# ---------------------------------------------------------------- API dependencies
VENV="$API_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating Python environment (first run only)…"
  "$PY" -m venv "$VENV"
fi
STAMP="$VENV/.readbit-installed"
if [ ! -f "$STAMP" ] || [ "$API_DIR/pyproject.toml" -nt "$STAMP" ]; then
  say "Installing API dependencies (first run takes a few minutes)…"
  "$VENV/bin/python" -m pip install --quiet --upgrade pip
  (cd "$API_DIR" && "$VENV/bin/python" -m pip install --quiet -e ".[dev]") || die "Installing API dependencies failed (see the error above)."
  touch "$STAMP"
fi

# ---------------------------------------------------------------- web dependencies + build
if [ ! -d "$WEB_DIR/node_modules" ] || [ "$WEB_DIR/package-lock.json" -nt "$WEB_DIR/node_modules/.package-lock.json" ]; then
  say "Installing web dependencies (first run takes a few minutes)…"
  (cd "$WEB_DIR" && npm_config_update_notifier=false npm ci --no-audit --no-fund --loglevel=error --silent) || die "Installing web dependencies failed (see the error above)."
fi
BUILD_ID="$WEB_DIR/.next/BUILD_ID"
if [ ! -f "$BUILD_ID" ] || [ -n "$(find "$WEB_DIR/app" "$WEB_DIR/components" "$WEB_DIR/features" "$WEB_DIR/lib" "$WEB_DIR/hooks" "$WEB_DIR/locales" "$WEB_DIR/package.json" -newer "$BUILD_ID" -print -quit 2>/dev/null)" ]; then
  say "Building the web app…"
  (cd "$WEB_DIR" && NEXT_TELEMETRY_DISABLED=1 npm run build --silent) > "$DATA_DIR/build.log" 2>&1 \
    || { tail -n 30 "$DATA_DIR/build.log"; die "The web build failed (full log: $DATA_DIR/build.log)."; }
fi

# ---------------------------------------------------------------- start
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  if [ "${#PIDS[@]}" -gt 0 ]; then
    say "Stopping Readbit…"
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

WEB_URL="http://localhost:$WEB_PORT"
say "Starting the API on port $API_PORT…"
(
  cd "$API_DIR"
  export APP_ENV=development \
    DATABASE_URL="sqlite:///$DATA_DIR/readbit.db" \
    STORAGE_PROVIDER=local STORAGE_LOCAL_PATH="$DATA_DIR/storage" \
    JOB_BACKEND=thread DEFAULT_LLM_PROVIDER="${DEFAULT_LLM_PROVIDER:-extractive}" \
    APP_URL="$WEB_URL" CORS_ORIGINS="$WEB_URL,http://127.0.0.1:$WEB_PORT" \
    EMAIL_DELIVERY=log LOG_LEVEL="${LOG_LEVEL:-WARNING}"
  exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT"
) > "$DATA_DIR/api.log" 2>&1 &
PIDS+=("$!")

wait_for() {  # url, name, log, pid
  for _ in $(seq 1 90); do
    if "$PY" -c 'import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' "$1" 2>/dev/null; then return 0; fi
    kill -0 "$4" 2>/dev/null || { tail -n 30 "$3"; die "The $2 stopped unexpectedly (full log: $3)."; }
    sleep 1
  done
  tail -n 30 "$3"; die "The $2 did not start within 90 seconds (full log: $3)."
}
wait_for "http://127.0.0.1:$API_PORT/health" "API" "$DATA_DIR/api.log" "${PIDS[0]}"

say "Starting the web app on port $WEB_PORT…"
(
  cd "$WEB_DIR"
  export API_URL="http://127.0.0.1:$API_PORT" PORT="$WEB_PORT" NEXT_TELEMETRY_DISABLED=1
  exec npx --no-install next start -p "$WEB_PORT"
) > "$DATA_DIR/web.log" 2>&1 &
PIDS+=("$!")
wait_for "http://127.0.0.1:$WEB_PORT/" "web app" "$DATA_DIR/web.log" "${PIDS[1]}"

cat <<EOF

  Readbit is running:  $WEB_URL

  Sample books to upload: $ROOT/evals/fixtures/
  Logs: $DATA_DIR/api.log and $DATA_DIR/web.log
  Press Ctrl+C to stop.

EOF
if [ -z "${NO_OPEN:-}" ]; then
  if command -v open >/dev/null 2>&1; then open "$WEB_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$WEB_URL" >/dev/null 2>&1 || true; fi
fi

# Stay in the foreground until a server exits or the user presses Ctrl+C.
while kill -0 "${PIDS[0]}" 2>/dev/null && kill -0 "${PIDS[1]}" 2>/dev/null; do sleep 2; done
say "A server stopped; see $DATA_DIR/api.log and $DATA_DIR/web.log."
exit 1
