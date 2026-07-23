#!/usr/bin/env python3
"""Bump the product version everywhere it's hardcoded, from the single
source of truth (`VERSION`) down.

Writes the new version into: `VERSION`, `extension/manifest.json`, the Office
Add-in unified and host-specific local manifests plus package/lock files, `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/Cargo.toml`,
`desktop/src-tauri/Cargo.lock` (only the `desktop` package entry), and
`desktop/package.json` (if it has a `version` field), and both root-version
fields in `desktop/package-lock.json`.

Deliberately does NOT touch `packaging/` (winget/scoop manifests carry a
release-specific hash that must be regenerated at release time, not by this
script -- see `packaging/README.md`).

Pure stdlib, no dependencies.

Usage:
    python scripts/bump_version.py 2.3.0
    python scripts/bump_version.py 2.3.0 --root <path>   # used by tests
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _version_targets import targets

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def bump(root: Path, new_version: str) -> list[Path]:
    """Write `new_version` into VERSION and every tracked file under `root`.
    Returns the list of files actually touched."""
    if not _SEMVER_RE.match(new_version):
        raise ValueError(f"expected a semver X.Y.Z version, got {new_version!r}")

    # Validate the complete target set before the first write. A parser/layout
    # drift must never leave VERSION ahead of only some manifests.
    planned = []
    for rel_path, getter, setter, optional in targets(root):
        path = root / rel_path
        if not path.is_file():
            if optional:
                continue
            raise ValueError(f"required version file {rel_path} is missing -- nothing was written")
        if getter(path) is None:
            if optional:
                continue  # version field legitimately absent -- nothing to bump
            raise ValueError(
                f"could not parse a version from required file {rel_path} -- "
                "fix the file or the parser in scripts/_version_targets.py; "
                "nothing was written"
            )
        planned.append((path, setter))

    version_file = root / "VERSION"
    version_file.write_text(new_version + "\n", encoding="utf-8")
    touched = [version_file]

    for path, setter in planned:
        setter(path, new_version)
        touched.append(path)

    return touched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("new_version", help="New version, e.g. 2.3.0")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root to bump (default: repo root this script lives in)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        touched = bump(root, args.new_version)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in touched:
        print(f"updated {path.relative_to(root)}")
    print(
        "\nNote: packaging/ (winget/scoop) was NOT touched -- regenerate its "
        "hashes at release time."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
