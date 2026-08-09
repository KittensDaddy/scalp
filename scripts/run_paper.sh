#!/usr/bin/env bash
# Miniserver / laptop: pull, then ./scripts/run_paper.sh
# Put secrets in .env (or: export SCALPING_HTTP_PROXY=http://user:pass@host:port)
#
# Serves the paper run AND the dashboard on ONE port (8000), bound to every
# interface so a headless box is reachable from your laptop at
# http://<miniserver-ip>:8000 — no Vite process, no second port, no CORS.
# Pass --local to keep it on 127.0.0.1 (SSH-tunnel setups).
set -euo pipefail
cd "$(dirname "$0")/.."

BIND="0.0.0.0"
if [[ "${1:-}" == "--local" ]]; then
  BIND="127.0.0.1"
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "wrote .env from .env.example"
fi

# Load .env into the environment (pydantic also reads the file; export helps
# one-shot overrides and any child tools). Existing exported vars win.
set -a
# shellcheck disable=SC1091
source .env
set +a

# Bind wins over whatever .env said — this script's whole point is remote access.
export SCALPING_DASHBOARD_HOST="$BIND"

mkdir -p data
uv sync
uv run alembic upgrade head

# Build the dashboard once so the API can serve it. Skipped when already built;
# `npm run build` again by hand (or delete frontend/dist) after a UI change.
if [[ ! -f frontend/dist/index.html ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "building dashboard (one-off)…"
    (cd frontend && npm install --silent && npm run build)
  else
    echo "!! npm not found — the dashboard UI cannot be built on this host." >&2
    echo "!! The API will still run; / will explain how to fix it." >&2
    echo "!! Install Node (e.g. sudo apt install nodejs npm) and re-run." >&2
  fi
fi
if [[ ! -f frontend/dist/index.html ]]; then
  echo "!! dashboard NOT built — http://<ip>:${SCALPING_DASHBOARD_PORT:-8000}/ will return a build hint, not the UI." >&2
fi

if [[ -n "${SCALPING_HTTP_PROXY:-}" ]]; then
  # strip credentials for the status line
  echo "proxy: ${SCALPING_HTTP_PROXY#*@}"
else
  echo "proxy: (none — direct)"
fi

LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
PORT="${SCALPING_DASHBOARD_PORT:-8000}"
if [[ "$BIND" == "0.0.0.0" && -n "${LAN_IP}" ]]; then
  echo "dashboard: http://${LAN_IP}:${PORT}  (open this from your laptop)"
  echo "if unreachable, open the port on this host:"
  echo "  sudo ufw allow ${PORT}/tcp"
else
  echo "dashboard: http://127.0.0.1:${PORT}"
fi

exec uv run scalping --run
