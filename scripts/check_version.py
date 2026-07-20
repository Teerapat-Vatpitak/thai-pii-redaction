#!/usr/bin/env python3
"""Fail if any version-bearing file has drifted from the single source of
truth, the root `VERSION` file.

Pure stdlib, no dependencies -- runs as a lightweight CI gate (see
`.github/workflows/ci.yml`) without a `pip install` step.

Usage:
    python scripts/check_version.py                  # checks the repo this script lives in
    python scripts/check_version.py --root <path>     # checks a different tree (used by tests)
    python scripts/check_version.py --expect-tag v1.2.3   # also assert the release tag matches

Exit 0 if every tracked file matches VERSION; exit 1 (with the list of
offending files) otherwise.

`--expect-tag` is the release gate (REL-1 audit finding): release.yml runs this
on a `v*` tag push so a tag that does not match the tree's VERSION fails BEFORE
any installer is built and published. Without it, tagging v2.3.0 on a tree that
still says 2.2.0 produced a v2.3.0 release carrying 2.2.0-named installers, and
the packaging/updater URL templates (which assume tag == "v" + VERSION) broke.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _version_targets import read_version_file, targets


def check(root: Path) -> list[str]:
    """Return human-readable drift messages; an empty list means everything
    is consistent."""
    expected = read_version_file(root)
    problems: list[str] = []
    for rel_path, getter, _setter, optional in targets(root):
        path = root / rel_path
        if not path.is_file():
            problems.append(f"{rel_path}: file not found")
            continue
        found = getter(path)
        if found is None:
            if optional:
                continue  # version field legitimately absent (e.g. package.json)
            # Required file the parser couldn't read a version out of: the
            # file's structure changed under us. Failing loudly beats a drift
            # gate that silently passes.
            problems.append(f"{rel_path}: could not parse a version from this file")
            continue
        if found != expected:
            problems.append(f"{rel_path}: found {found!r}, expected {expected!r}")
    return problems


def check_tag(root: Path, tag: str) -> list[str]:
    """Return drift messages if `tag` is not exactly "v" + VERSION."""
    expected = read_version_file(root)
    if tag != f"v{expected}":
        return [
            f"release tag {tag!r} does not match VERSION {expected!r} "
            f"(expected tag {'v' + expected!r})"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root to check (default: repo root this script lives in)",
    )
    parser.add_argument(
        "--expect-tag",
        metavar="TAG",
        help='Also assert the release tag equals "v" + VERSION (e.g. v1.2.3)',
    )
    args = parser.parse_args()
    root = args.root.resolve()

    problems = check(root)
    # `is not None`, not truthiness: an empty --expect-tag (an unset caller
    # variable) must fail the gate, never silently skip it.
    if args.expect_tag is not None:
        problems += check_tag(root, args.expect_tag)
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
