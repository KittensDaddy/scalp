#!/usr/bin/env bash
# One-shot LAN paper stack: API :8000 + Vite :5173 on all interfaces.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only || true

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "wrote .env from .env.example"
fi

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
fi
if [[ -z "${LAN_IP}" ]]; then
  echo "could not detect LAN IP" >&2
  exit 1
fi

# Upsert LAN bind / CORS without clobbering proxy or tokens.
python3 - <<PY
from pathlib import Path
lan = "${LAN_IP}"
path = Path(".env")
lines = path.read_text().splitlines()
want = {
    "SCALPING_DASHBOARD_HOST": "0.0.0.0",
    "SCALPING_DASHBOARD_PORT": "8000",
    "SCALPING_DASHBOARD_CORS_ORIGIN": f"http://{lan}:5173,http://localhost:5173,http://127.0.0.1:5173",
}
seen = set()
out = []
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k, _, _ = line.partition("=")
    if k in want:
        out.append(f"{k}={want[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f"{k}={v}")
path.write_text("\\n".join(out) + "\\n")
print(f"LAN UI http://{lan}:5173  API http://{lan}:8000")
PY

set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p data
uv sync
uv run alembic upgrade head

if [[ -n "${SCALPING_HTTP_PROXY:-}" ]]; then
  echo "proxy: ${SCALPING_HTTP_PROXY#*@}"
else
  echo "proxy: (none — direct)"
fi

# Frontend deps once
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi

# Stop prior stack from this repo if still running
pkill -f '/home/sun/scalp/.venv/bin/scalping --run' 2>/dev/null || true
pkill -f 'vite --host 0.0.0.0 --port 5173' 2>/dev/null || true
sleep 1

uv run scalping --run &
API_PID=$!
cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# wait until API answers (or 60s)
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:8000/api/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "open http://${LAN_IP}:5173 from your laptop"
cd frontend
exec env VITE_API_BASE="http://${LAN_IP}:8000" npm run dev -- --host 0.0.0.0 --port 5173
