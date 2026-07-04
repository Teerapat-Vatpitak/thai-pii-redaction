# Build the AI Guard Python backend as a PyInstaller onefile, then copy it into
# the Tauri externalBin location with the required target-triple suffix.
$ErrorActionPreference = "Stop"
# Run from repo root (build_exe.ps1 + dist/ live there). Push/Pop so the caller's
# working directory is restored afterwards — otherwise you'd be left in the repo
# root and `npm run tauri dev` (which must run in desktop/) would fail with ENOENT.
Push-Location -Path (Join-Path $PSScriptRoot "..")
try {
    Write-Host "Building dist/AIGuard.exe via build_exe.ps1 ..."
    ./build_exe.ps1

    $triple = (rustc --print host-tuple).Trim()          # expect x86_64-pc-windows-msvc (older rustc: host-triple)
    $dest = Join-Path $PSScriptRoot "src-tauri/binaries"
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item "dist/AIGuard.exe" (Join-Path $dest "aiguard-$triple.exe") -Force

    Write-Host "Sidecar staged: src-tauri/binaries/aiguard-$triple.exe"
}
finally {
    Pop-Location
}
