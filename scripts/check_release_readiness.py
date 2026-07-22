#!/usr/bin/env python3
"""Validate release metadata before a tag is allowed to build artifacts.

Checks the existing VERSION drift gate, requires CHANGELOG.md to contain both
an Unreleased section and a dated section for the current VERSION, and
optionally verifies a pushed tag is exactly ``v<VERSION>``.

Pure stdlib so it can run before dependency installation in CI.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _version_targets import read_version_file
from check_version import check as check_version_targets
from check_version import check_tag


def check_changelog(
    root: Path, version: str, *, require_empty_unreleased: bool = False
) -> list[str]:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return ["CHANGELOG.md: file not found"]

    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    unreleased = re.search(
        r"^## \[Unreleased\]\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if unreleased is None:
        problems.append("CHANGELOG.md: missing '## [Unreleased]' section")
    elif require_empty_unreleased and unreleased.group("body").strip():
        problems.append(
            "CHANGELOG.md: Unreleased is not empty; move the release scope "
            f"under [{version}] before tagging"
        )

    match = re.search(
        rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})\s*$",
        text,
        re.MULTILINE,
    )
    if match is None:
        problems.append(f"CHANGELOG.md: missing dated section '## [{version}] - YYYY-MM-DD'")
    else:
        try:
            date.fromisoformat(match.group(1))
        except ValueError:
            problems.append(
                f"CHANGELOG.md: release date {match.group(1)!r} is not a valid calendar date"
            )
    return problems


def check(root: Path, expected_tag: str | None = None) -> list[str]:
    version = read_version_file(root)
    problems = check_version_targets(root)
    problems += check_changelog(
        root,
        version,
        require_empty_unreleased=expected_tag is not None,
    )
    if expected_tag is not None:
        problems += check_tag(root, expected_tag)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: parent of this script directory)",
    )
    parser.add_argument(
        "--expect-tag",
        metavar="TAG",
        help='also require TAG to equal "v" + VERSION',
    )
    args = parser.parse_args()
    root = args.root.resolve()
    problems = check(root, args.expect_tag)
    if problems:
        print("Release readiness check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"OK: version targets, changelog, and release metadata agree for {read_version_file(root)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
