#!/usr/bin/env bash
# Starts a throwaway API for end-to-end tests: fresh SQLite DB + storage, background thread jobs, offline AI engine.
set -euo pipefail
DIR="${E2E_DATA_DIR:-/tmp/readbit-e2e}"
rm -rf "$DIR" && mkdir -p "$DIR"
cd "$(dirname "$0")/../services/api"
export APP_ENV=test DATABASE_URL="sqlite:///$DIR/e2e.db" STORAGE_LOCAL_PATH="$DIR/storage" JOB_BACKEND=thread \
  DEFAULT_LLM_PROVIDER=extractive CORS_ORIGINS="http://localhost:3001" APP_URL="http://localhost:3001" USER_RATE_LIMIT=1000 UPLOAD_RATE_LIMIT=1000 \
  SECRET_KEY="e2e-secret-key-0123456789abcdef0123456789" LOG_LEVEL=WARNING TRUST_PROXY_HEADERS=true
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "${E2E_API_PORT:-8001}"
