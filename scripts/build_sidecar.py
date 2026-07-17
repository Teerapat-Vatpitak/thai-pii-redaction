#!/usr/bin/env python3
"""Cross-platform: build the AI Guard backend as a PyInstaller onefile and stage
it as the Tauri sidecar.

Single source of the PyInstaller build for local dev (Windows / macOS / Linux)
and CI. Produces `dist/AIGuard[.exe]` and stages it as
`desktop/src-tauri/binaries/aiguard-<rust-target-triple>[.exe]` (the name Tauri's
externalBin expects per platform). `build_exe.ps1` and `desktop/build-sidecar.ps1`
are thin Windows wrappers around this.

Bundles the base product (FastAPI + regex/checksum + Thai thainer-CRF NER +
pdfplumber/pypdfium2/reportlab PDF). Heavy optional stacks (torch/transformers,
paddleocr, scipy/pandas) are excluded so the binary stays small.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
IS_WINDOWS = os.name == "nt"

COLLECT_ALL = ["pythainlp", "pycrfsuite", "pdfplumber", "pypdfium2", "reportlab"]

# Excludes keep the binary small. torch/transformers/paddle/cv2 are optional ML/OCR
# stacks; the pythainlp.* submodules are neural features the base engine never uses
# (excluding them stops PyInstaller from dragging in scipy/pandas via fsspec).
EXCLUDE = [
    "torch", "sentence_transformers", "transformers",
    "paddleocr", "paddlepaddle", "paddle", "cv2",
    "pythainlp.word_vector", "pythainlp.corpus.wordnet", "pythainlp.translate",
    "pythainlp.summarize", "pythainlp.parse", "pythainlp.generate", "pythainlp.chat",
    "pythainlp.wangchanberta", "pythainlp.phayathaibert", "pythainlp.lm",
    "pythainlp.wsd", "pythainlp.spell.wanchanberta_thai_grammarly", "pythainlp.ulmfit",
    "scipy", "pandas",
]


def host_triple() -> str:
    # Parse the stable `host:` line of `rustc -vV` rather than
    # `rustc --print host-tuple`: that print-request name changed across rustc
    # versions (`host-triple` before 1.86, `host-tuple` after), so relying on
    # either alone breaks on the other. The `-vV` host line is stable.
    out = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in out.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine host triple from `rustc -vV`")


def data_args() -> list[str]:
    """Bundle PyThaiNLP's data dir (thai-ner CRF model etc.) for offline NER;
    skip *.pth (the 431 MB neural model the base engine never uses).

    Resolve the dir via PyThaiNLP's own API so it honors PYTHAINLP_DATA /
    PYTHAINLP_DATA_DIR instead of assuming ~/pythainlp-data, and hard-fail rather
    than silently ship a NER-less binary if the CRF model is missing."""
    from pythainlp.tools import get_pythainlp_data_path

    data_dir = Path(get_pythainlp_data_path())
    crf = data_dir / "thai-ner-1-4.crfsuite"
    db = data_dir / "db.json"
    if not (data_dir.is_dir() and crf.is_file() and db.is_file()):
        sys.exit(
            f"ERROR: PyThaiNLP NER model not found in {data_dir} (need db.json + "
            "thai-ner-1-4.crfsuite). Run `python -c \"from pythainlp.tag import "
            "NER; NER(engine='thainer')\"` once to download it, then rebuild. "
            "Refusing to ship a NER-less binary."
        )
    args: list[str] = []
    for f in sorted(data_dir.iterdir()):
        if f.is_file() and f.suffix != ".pth":
            # PyInstaller --add-data uses the OS path separator (';' win, ':' unix).
            args += ["--add-data", f"{f}{os.pathsep}pythainlp-data"]
    return args


def main() -> None:
    # Hash-pinned build tooling (Horizon-2 #11): same PyInstaller as CI/release.
    # The lock is compiled for Python 3.13 (matching CI); build the exe on 3.13.
    subprocess.check_call([
        PY, "-m", "pip", "install", "--quiet", "--require-hashes",
        "-r", str(ROOT / "requirements-build.lock"),
    ])

    cmd = [PY, "-m", "PyInstaller", "--noconfirm", "--onefile", "--name", "AIGuard",
           "--python-option", "X utf8=1"]
    for m in COLLECT_ALL:
        cmd += ["--collect-all", m]
    cmd += ["--collect-submodules", "uvicorn", "--hidden-import", "pycrfsuite"]
    for m in EXCLUDE:
        cmd += ["--exclude-module", m]
    # Single-source version (Horizon-1 #5): bundle VERSION at the bundle root
    # so app/server.py's _read_version() finds it via sys._MEIPASS when frozen.
    cmd += ["--add-data", f"{ROOT / 'VERSION'}{os.pathsep}."]
    cmd += data_args()
    # Absolute paths so we never depend on / mutate the caller's working directory.
    cmd += ["--distpath", str(ROOT / "dist"),
            "--workpath", str(ROOT / "build"),
            "--specpath", str(ROOT),
            str(ROOT / "launcher.py")]
    print("Running PyInstaller...")
    subprocess.check_call(cmd)

    triple = host_triple()
    suffix = ".exe" if IS_WINDOWS else ""
    src = ROOT / "dist" / f"AIGuard{suffix}"
    dst_dir = ROOT / "desktop" / "src-tauri" / "binaries"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"aiguard-{triple}{suffix}"
    shutil.copy2(src, dst)
    print(f"Sidecar staged: {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
