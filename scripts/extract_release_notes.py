#!/usr/bin/env python3
"""Print one dated CHANGELOG section as the GitHub Release body."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract(changelog: Path, version: str) -> str:
    text = changelog.read_text(encoding="utf-8")
    match = re.search(
        rf"^## \[{re.escape(version)}\] - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})\s*$\n"
        r"(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ValueError(f"missing dated changelog section for {version}")
    body = match.group("body").strip()
    if not body:
        raise ValueError(f"empty changelog section for {version}")
    return f"## AI Guard {version} ({match.group('date')})\n\n{body}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--changelog",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "CHANGELOG.md",
    )
    args = parser.parse_args()
    try:
        print(extract(args.changelog.resolve(), args.version))
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
