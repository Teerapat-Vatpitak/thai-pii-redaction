# Build dist/AIGuard.exe — a double-click launcher for the AI Guard backend.
#
# Bundles the base product (FastAPI + regex/checksum + Thai NER + PDF redaction).
# The heavy optional ML stack (torch / sentence-transformers) is excluded so the
# binary stays small; the MiniLM sensitive detector simply stays disabled there.
#
# Run:  ./build_exe.ps1     ->  dist/AIGuard.exe

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"

$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --quiet pyinstaller

& $python -m PyInstaller --noconfirm --onefile --name AIGuard `
    --python-option "X utf8=1" `
    --collect-all pythainlp `
    --collect-all pycrfsuite `
    --collect-all pdfplumber `
    --collect-all pymupdf `
    --collect-submodules uvicorn `
    --hidden-import pycrfsuite `
    --exclude-module torch `
    --exclude-module sentence_transformers `
    --exclude-module transformers `
    launcher.py

Write-Host ""
Write-Host "Built: dist\AIGuard.exe  (double-click to start the backend)"
