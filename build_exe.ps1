# Build dist/AIGuard.exe (a double-click launcher for the AI Guard backend) and
# stage it as the Tauri sidecar.
#
# Thin Windows wrapper around the cross-platform builder scripts/build_sidecar.py
# (single source of the PyInstaller flags / excludes / model bundling, shared with
# macOS/Linux and CI). See that file for the real logic.
#
# Run:  ./build_exe.ps1   ->  dist/AIGuard.exe  +  desktop/src-tauri/binaries/aiguard-<triple>.exe

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"

& ".\.venv\Scripts\python.exe" "scripts\build_sidecar.py"

Write-Host ""
Write-Host "Built: dist\AIGuard.exe  (double-click to start the backend)"
