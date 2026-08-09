#!/usr/bin/env bash
# Miniserver / laptop: pull, then ./scripts/run_paper.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "wrote .env from .env.example"
fi

mkdir -p data
uv sync
uv run alembic upgrade head
exec uv run scalping --run
