#!/usr/bin/env bash
# Run on the host as root after copying the project into INSTALL_DIR.
# Idempotent: kills any old instance, reinstalls deps, restarts under nohup.
#
# Configurable via env vars (with defaults):
#   INSTALL_DIR  install path                       (default: /opt/jenkins-mcp)
#   LOG_FILE     where to send stdout/stderr        (default: /var/log/jenkins-mcp.log)
#   PYTHON       Python version for uv to fetch     (default: 3.12)
#   HTTP_PORT    port the server listens on         (default: 8000; printed endpoint only)
#   ENDPOINT_HOST host shown in the printed URL     (default: $(hostname -f))
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/jenkins-mcp}"
LOG_FILE="${LOG_FILE:-/var/log/jenkins-mcp.log}"
PYTHON="${PYTHON:-3.12}"
HTTP_PORT="${HTTP_PORT:-8000}"
ENDPOINT_HOST="${ENDPOINT_HOST:-$(hostname -f 2>/dev/null || hostname)}"

cd "${INSTALL_DIR}"

if ! command -v uv >/dev/null 2>&1; then
  echo "[setup] installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

echo "[setup] ensuring Python ${PYTHON} via uv..."
uv python install "${PYTHON}"

echo "[setup] uv sync..."
uv sync --python "${PYTHON}"

# 4. Stop any old instance.
if pgrep -f "server.py --http" >/dev/null; then
  echo "[setup] stopping old instance..."
  pkill -f "server.py --http" || true
  sleep 1
fi

echo "[setup] starting server..."
set -a; [ -f .env ] && . ./.env; set +a
nohup uv run --python "${PYTHON}" python server.py --http \
  > "${LOG_FILE}" 2>&1 &
disown

sleep 2

if pgrep -f "server.py --http" >/dev/null; then
  echo "[setup] ✓ running, PID $(pgrep -f 'server.py --http')"
  echo "[setup] logs: tail -f ${LOG_FILE}"
  echo "[setup] endpoint: http://${ENDPOINT_HOST}:${HTTP_PORT}/mcp"
else
  echo "[setup] ✗ failed to start, see ${LOG_FILE}"
  tail -20 "${LOG_FILE}"
  exit 1
fi
