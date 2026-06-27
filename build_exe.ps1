# Build dist/AIGuard.exe — a double-click launcher for the AI Guard backend.
#
# Bundles the base product (FastAPI + regex/checksum + Thai NER + PDF redaction).
# The heavy optional ML stack (torch / sentence-transformers) is excluded so the
# binary stays small; the MiniLM sensitive detector simply stays disabled there.
#
# It also bundles the PyThaiNLP NER model (the thai-ner CRF file) so NER works
# offline on a fresh machine with no runtime download. The 400MB+ neural NNER
# model (.pth) is NOT bundled — engine="thainer" only needs the CRF file.
#
# Run:  ./build_exe.ps1     ->  dist/AIGuard.exe

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"

$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --quiet pyinstaller

# Bundle the PyThaiNLP data files (skip the large *.pth neural model).
$dataDir = "$env:USERPROFILE\pythainlp-data"
$dataArgs = @()
if (Test-Path $dataDir) {
    Get-ChildItem $dataDir -File | Where-Object { $_.Extension -ne ".pth" } | ForEach-Object {
        $dataArgs += "--add-data"
        $dataArgs += "$($_.FullName);pythainlp-data"
    }
} else {
    Write-Warning "No $dataDir found — run the app once so PyThaiNLP downloads its NER model, then rebuild for an offline-capable exe."
}

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
    @dataArgs `
    launcher.py

Write-Host ""
Write-Host "Built: dist\AIGuard.exe  (double-click to start the backend)"
