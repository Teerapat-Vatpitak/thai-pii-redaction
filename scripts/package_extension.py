#!/usr/bin/env python3
"""Package `extension/` into a Chrome Web Store upload zip.

Pure stdlib, no dependencies -- runs without a `pip install` step (same
constraint as `scripts/check_version.py`/`scripts/bump_version.py`).

Refuses to build if `extension/manifest.json`'s `version` has drifted from
the root `VERSION` file (single source of truth -- see `scripts/bump_version.py`),
so a stale build can never be uploaded to the store by accident.

Usage:
    python scripts/package_extension.py
    python scripts/package_extension.py --root <path> --dist-dir <path>   # used by tests

Output: `<dist-dir>/aiguard-extension-<VERSION>.zip` containing the contents
of `extension/` (everything except README.md, which is developer-facing
only and not part of the shipped extension).
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

EXCLUDED_NAMES = {"README.md"}


def _read_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def _read_manifest_version(extension_dir: Path) -> str:
    manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
    return manifest["version"]


def build_zip(root: Path, dist_dir: Path | None = None) -> Path:
    """Build the CWS upload zip and return its path.

    Raises `ValueError` if the manifest version has drifted from VERSION.
    """
    extension_dir = root / "extension"
    expected = _read_version(root)
    found = _read_manifest_version(extension_dir)
    if found != expected:
        raise ValueError(
            f"extension/manifest.json version ({found!r}) does not match "
            f"VERSION ({expected!r}). Run `python scripts/bump_version.py {expected}` "
            "to resync, or fix by hand."
        )

    dist_dir = dist_dir or (root / "dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / f"aiguard-extension-{expected}.zip"

    files = sorted(
        p for p in extension_dir.rglob("*")
        if p.is_file() and p.name not in EXCLUDED_NAMES
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, arcname=path.relative_to(extension_dir).as_posix())

    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root containing extension/ and VERSION (default: repo root this script lives in)",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="Output directory for the zip (default: <root>/dist)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    dist_dir = args.dist_dir.resolve() if args.dist_dir else None

    try:
        zip_path = build_zip(root, dist_dir)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"built {zip_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
