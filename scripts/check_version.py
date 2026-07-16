#!/usr/bin/env python3
"""Fail if any version-bearing file has drifted from the single source of
truth, the root `VERSION` file.

Pure stdlib, no dependencies -- runs as a lightweight CI gate (see
`.github/workflows/ci.yml`) without a `pip install` step.

Usage:
    python scripts/check_version.py                  # checks the repo this script lives in
    python scripts/check_version.py --root <path>     # checks a different tree (used by tests)

Exit 0 if every tracked file matches VERSION; exit 1 (with the list of
offending files) otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _version_targets import read_version_file, targets  # noqa: E402


def check(root: Path) -> list[str]:
    """Return human-readable drift messages; an empty list means everything
    is consistent."""
    expected = read_version_file(root)
    problems: list[str] = []
    for rel_path, getter, _setter in targets(root):
        path = root / rel_path
        if not path.is_file():
            problems.append(f"{rel_path}: file not found")
            continue
        found = getter(path)
        if found is None:
            continue  # version field not present (e.g. optional package.json field)
        if found != expected:
            problems.append(f"{rel_path}: found {found!r}, expected {expected!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root to check (default: repo root this script lives in)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    problems = check(root)
    if problems:
        print("Version drift detected (VERSION file is the single source of truth):")
        for problem in problems:
            print(f"  - {problem}")
        print("\nRun `python scripts/bump_version.py <version>` to resync, or fix by hand.")
        return 1

    print(f"OK: all version-bearing files match VERSION ({read_version_file(root)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
