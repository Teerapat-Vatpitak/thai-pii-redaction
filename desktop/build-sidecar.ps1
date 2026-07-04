# Build the AI Guard backend and stage it as the Tauri sidecar
# (desktop/src-tauri/binaries/aiguard-<triple>.exe).
#
# Thin Windows wrapper around the cross-platform builder scripts/build_sidecar.py.
# Run from the desktop/ dir: ./build-sidecar.ps1

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONUTF8 = "1"

& (Join-Path $root ".venv\Scripts\python.exe") (Join-Path $root "scripts\build_sidecar.py")
