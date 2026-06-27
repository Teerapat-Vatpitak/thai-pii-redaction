# AI Guard backend launcher (Windows / PowerShell).
# Creates the venv and installs deps on first run, then starts the local API
# the browser extension talks to.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$env:PYTHONUTF8 = "1"

$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt -r requirements-web.txt
}

Write-Host "Starting AI Guard backend on http://localhost:8000 (Ctrl+C to stop)"
& $python -m uvicorn app.server:app --port 8000
