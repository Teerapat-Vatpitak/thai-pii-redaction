#!/usr/bin/env bash
# AI Guard backend launcher (git-bash / Linux / macOS).
# Creates the venv and installs deps on first run, then starts the local API
# the browser extension talks to.

set -euo pipefail
cd "$(dirname "$0")"

export PYTHONUTF8=1

# venv layout differs: Scripts/ on Windows (git-bash), bin/ elsewhere.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
else
  echo "Creating virtual environment (.venv)..."
  python -m venv .venv
  if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
  else
    PY=".venv/Scripts/python.exe"
  fi
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt -r requirements-web.txt
fi

echo "Starting AI Guard backend on http://localhost:8000 (Ctrl+C to stop)"
exec "$PY" -m uvicorn app.server:app --port 8000
