#!/bin/bash
# Double-click to start Clausetrail on macOS (or run ./Clausetrail.command on Linux).
cd "$(dirname "$0")" || exit 1
PY=""
for c in python3.14 python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Clausetrail needs Python 3.12 or newer. Install it from https://www.python.org/downloads/ and double-click again."
  read -r -p "Press Enter to close."; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Clausetrail (about a minute)..."
  "$PY" -m venv .venv || { read -r -p "Setup failed. Press Enter to close."; exit 1; }
fi
if [ ! -f .venv/.installed ] || [ backend/requirements.txt -nt .venv/.installed ]; then
  .venv/bin/python -m pip install -q --disable-pip-version-check -r backend/requirements.txt && touch .venv/.installed \
    || { read -r -p "Installing dependencies failed. Press Enter to close."; exit 1; }
fi
exec .venv/bin/python scripts/start.py --open "$@"
