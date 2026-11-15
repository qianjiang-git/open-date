#!/usr/bin/env bash
# One-command setup and check for a Vexo Open band (the "Vexo-HACK-XX" wrist bands).
#
#   ./setup.sh              set everything up, find the band, read it
#   ./setup.sh 36           use band number 36 (skip the search)
#   ./setup.sh --only-scan  just list nearby bands
#   ./setup.sh --led        flash the LED red/green/blue to prove control
#   ./setup.sh --dashboard  serve the browser dashboard instead
#   ./setup.sh --help       all options
#
# Safe to run again: it only installs and downloads what is missing.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

KIT_URL="https://github.com/VexoAI-Org/vexo-open-kit.git"
KIT="$HERE/vexo-open-kit"
VENV="$HERE/.venv"
PYTHON="${PYTHON:-python3}"
DASHBOARD=0
PORT=8000
ARGS=()
BAND=""

if [ -t 1 ]; then
  B=$'\033[1;34m'; Y=$'\033[1;33m'; R=$'\033[1;31m'; N=$'\033[0m'
else
  B=""; Y=""; R=""; N=""
fi

say()  { printf '%s==>%s %s\n' "$B" "$N" "$*"; }
warn() { printf '%sWARN:%s %s\n' "$Y" "$N" "$*" >&2; }
die()  { printf '%sERROR:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage ;;
    --dashboard) DASHBOARD=1; shift ;;
    --port) PORT="${2:?--port needs a number}"; shift 2 ;;
    --band) BAND="${2:?--band needs a number}"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

# 1. Python 3.9 or newer.
command -v "$PYTHON" >/dev/null 2>&1 || die "Python 3 is required: https://www.python.org/downloads/"
"$PYTHON" - <<'EOF' || die "Python 3.9 or newer is required (found an older one)."
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
EOF

# 2. A private virtual environment, so nothing is installed system-wide.
if [ ! -x "$VENV/bin/python" ]; then
  say "Creating .venv"
  "$PYTHON" -m venv "$VENV" || die "Could not create a virtual environment. On Debian/Ubuntu: sudo apt install python3-venv"
fi

# 3. bleak, the Bluetooth library the band speaks.
if ! "$VENV/bin/python" -c "import bleak" >/dev/null 2>&1; then
  say "Installing bleak (Bluetooth library)"
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
  "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check bleak \
    || die "Could not install bleak. Check your internet connection and run ./setup.sh again."
fi

# 4. The Vexo Open kit: the Python/JS libraries and the dashboard.
if [ ! -d "$KIT/python/vexo_open" ]; then
  command -v git >/dev/null 2>&1 || die "git is required to download the kit: https://git-scm.com/downloads"
  say "Downloading vexo-open-kit"
  git clone --depth 1 "$KIT_URL" "$KIT" || die "Could not clone $KIT_URL"
elif [ -d "$KIT/.git" ] && [ "${VEXO_UPDATE:-1}" = "1" ]; then
  say "Updating vexo-open-kit"
  git -C "$KIT" pull --ff-only --quiet 2>/dev/null || warn "Could not update the kit; using the local copy."
fi

# 5. Show the USB side of the hardware, when the OS lets us.
if command -v system_profiler >/dev/null 2>&1; then
  usb="$(system_profiler SPUSBDataType 2>/dev/null | grep -A9 -m1 "Vexo Open band" || true)"
  if [ -n "$usb" ]; then
    say "USB device detected"
    printf '%s\n' "$usb" | sed 's/^[[:space:]]*//' | grep -E "Vexo|Product ID|Vendor ID|Serial|Version" \
      | sed 's/^/  /' || true
  else
    warn "No Vexo band on USB. That is fine for Bluetooth - it just means it is not charging."
  fi
fi

# Helpful first time: macOS and Windows ask for Bluetooth permission once.
case "$(uname -s)" in
  Darwin) [ "${VEXO_QUIET:-0}" = "1" ] || say "If macOS asks whether Terminal may use Bluetooth, click Allow." ;;
esac

# 6. Dashboard mode: a local web page (Chrome or Edge only).
if [ "$DASHBOARD" = "1" ]; then
  if [ -z "$BAND" ]; then
    say "Looking for a band number for the dashboard link"
    set +e
    BAND="$("$VENV/bin/python" "$HERE/detect.py" --only-scan --scan 6 2>/dev/null \
            | sed -n 's/.*Vexo-HACK-\([0-9][0-9]*\).*/\1/p' | head -n1)"
    set -e
  fi
  if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "Port $PORT is already in use. Try: ./setup.sh --dashboard --port 8001"
  fi
  "$VENV/bin/python" -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 &
  SERVER=$!
  trap 'kill "$SERVER" 2>/dev/null || true' EXIT INT TERM
  sleep 1
  if [ -n "$BAND" ]; then
    URL="http://localhost:$PORT/vexo-open-kit/dashboard/?band=$BAND"
  else
    URL="http://localhost:$PORT/vexo-open-kit/dashboard/"
  fi
  say "Dashboard: $URL"
  echo "   1. Open it in Chrome or Edge."
  echo "   2. Double-tap the band (blue blink, 60 s)."
  echo "   3. Press Connect and pick Vexo-HACK-XX."
  echo "   Ctrl+C stops the server."
  command -v open >/dev/null 2>&1 && open "$URL" 2>/dev/null || true
  wait "$SERVER"
  exit 0
fi

# 7. Everything else is the detector.
if [ -n "$BAND" ]; then
  ARGS=("$BAND" "${ARGS[@]}")
fi
say "Starting"
exec "$VENV/bin/python" "$HERE/detect.py" "${ARGS[@]}"
