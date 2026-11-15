#!/usr/bin/env bash
# Start a local simulated demo on one laptop: seed, server, two simulated hubs.
#
#   demo/run_demo.sh            simulated bands, deterministic scorer
#   demo/run_demo.sh claude     use the Claude scorer (needs ANTHROPIC_API_KEY)
#
# Then open the printed phone links (one per person) and the operator page, and use the
# operator's "Simulated distance" buttons: Near -> both Accept -> Close -> bands tap.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
SCORER="${1:-deterministic}"

[ -x "$PY" ] || { echo "Run ./setup.sh first (it creates .venv)."; exit 1; }
"$PY" -m pip install --quiet --disable-pip-version-check fastapi uvicorn httpx pydantic anthropic >/dev/null

"$PY" demo/seed.py --fresh --mode simulated --scorer "$SCORER"

PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PY" -m uvicorn --factory server.app:serve --host 127.0.0.1 --port 8080 --log-level warning &
PIDS+=($!)
sleep 2
for person in alice bob; do
  "$PY" -m hub.hub --config "config/hub-$person.local.json" --sim --sim-tap-after 4 &
  PIDS+=($!)
done
echo
echo "Running. Phone links and the operator link are above (also in config/tokens.local.json)."
echo "Ctrl+C stops everything."
wait
