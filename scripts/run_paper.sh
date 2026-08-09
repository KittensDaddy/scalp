#!/usr/bin/env bash
# Miniserver / laptop: pull, then ./scripts/run_paper.sh
# Put secrets in .env (or: export SCALPING_HTTP_PROXY=http://user:pass@host:port)
set -euo pipefail
cd "$(dirname "$0")/.."

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

mkdir -p data
uv sync
uv run alembic upgrade head

if [[ -n "${SCALPING_HTTP_PROXY:-}" ]]; then
  # strip credentials for the status line
  echo "proxy: ${SCALPING_HTTP_PROXY#*@}"
else
  echo "proxy: (none — direct)"
fi

exec uv run scalping --run
