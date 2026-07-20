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
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
IS_WINDOWS = os.name == "nt"

# REL-2: the NER model is fetched from PyThaiNLP's corpus host at build time and
# baked into the exe that release.yml then hashes into SHA256SUMS and attests as
# "built from this repo at this tag". That download sits OUTSIDE the hash-pinned
# lockfile chain, so without this pin a compromised upstream model would inherit
# first-party provenance -- in a PII-redaction tool, a silently sabotaged NER
# model means silently missed PII.
#
# Recorded trust-on-first-use from a known-good build. If PyThaiNLP ships a new
# model this WILL fail the build: re-pin deliberately (confirm upstream's change
# and the new hash) rather than reflexively.
#
# db.json is deliberately NOT pinned: it is a per-machine catalog of installed
# corpora, so its bytes legitimately differ between dev boxes and CI runners.
PINNED_DATA_SHA256 = {
    "thai-ner-1-4.crfsuite": (
        "8c4f5b73434843d683442b42ddfaf2999a51d7c37579b27bac82c816c8a11e38"
    ),
    # Also network-fetched and also bundled; pinned opportunistically. A clean CI
    # runner may not have these (only the NER model is pre-downloaded), so they
    # are verified when present rather than required.
    "thai_dictionary_v1.0.csv": (
        "07ac1cb64327cfd97459a7bfa0055f0ffe7d06b3daefbf15a83fdb512fea3488"
    ),
    "thai2rom-pytorch-attn-v0.1.tar": (
        "9411f25c3482ac69419cc90f201186eb693dde10c27cbc4a0a04cea915b4c902"
    ),
}
# Files that must exist AND match their pin before we are willing to build.
REQUIRED_PINNED_DATA = ("thai-ner-1-4.crfsuite",)
# Any file matching one of these that is NOT in the pin map hard-fails the build.
# pythainlp's download() rewrites db.json's filename entry on upgrade but never
# unlinks the superseded file, so a newer thai-ner-1-5.crfsuite can sit next to
# the pinned 1-4 -- and data_args() bundles EVERY non-.pth file, so it would ride
# into the attested exe unverified.
PINNED_GLOB_PATTERNS = ("*.crfsuite",)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_pinned_data(
    data_dir: Path,
    pins: dict[str, str] = PINNED_DATA_SHA256,
    required: tuple[str, ...] = REQUIRED_PINNED_DATA,
    pinned_globs: tuple[str, ...] = PINNED_GLOB_PATTERNS,
) -> None:
    """Hard-fail the build if a pinned data file is missing or its bytes changed.

    Files with no pin are skipped (see db.json note above) so a new upstream data
    file does not break the build -- EXCEPT files matching `pinned_globs`, which
    must be pinned explicitly: a model is exactly the thing we refuse to bundle
    unverified.
    """
    for pattern in pinned_globs:
        for path in sorted(data_dir.glob(pattern)):
            if path.is_file() and path.name not in pins:
                sys.exit(
                    f"ERROR: {path.name} matches a pinned pattern ({pattern}) but has "
                    f"no entry in PINNED_DATA_SHA256.\n  path {path}\n"
                    "An unpinned model must not be bundled into an attested build "
                    "(pythainlp leaves superseded models on disk). Pin it in "
                    "scripts/build_sidecar.py or remove the file."
                )
    for name in required:
        if not (data_dir / name).is_file():
            sys.exit(
                f"ERROR: required pinned data file {name} not found in {data_dir}. "
                "Refusing to build."
            )
    for name, expected in pins.items():
        path = data_dir / name
        if not path.is_file():
            continue  # optional pin, file not present on this machine
        actual = _sha256(path)
        if actual != expected:
            sys.exit(
                f"ERROR: {name} failed its SHA256 pin.\n"
                f"  expected {expected}\n"
                f"  actual   {actual}\n"
                f"  path     {path}\n"
                "The model fetched from upstream is not the one this repo pinned. "
                "Refusing to bundle it into an attested build. If PyThaiNLP "
                "legitimately shipped a new model, verify why and update "
                "PINNED_DATA_SHA256 in scripts/build_sidecar.py deliberately."
            )

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
    # REL-2: the model came off the network; verify it is the one we pinned
    # before it goes into a binary that will carry build provenance.
    verify_pinned_data(data_dir)
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
