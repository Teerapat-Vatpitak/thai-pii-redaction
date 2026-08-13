#!/usr/bin/env python3
"""Resolve one exact draft from GitHub's authenticated paginated release list.

GitHub's release-by-tag endpoint excludes drafts. Tag-mode provenance must bind
to the draft created by this workflow, so lookup uses the full authenticated
release list and rejects published collisions or ambiguous drafts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TAG_RE = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


def _release_pages(path: Path) -> list[list[dict[str, object]]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("release list response is invalid") from None
    if not isinstance(document, list):
        raise ValueError("release list response is invalid")
    pages: list[list[dict[str, object]]] = []
    for page in document:
        if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
            raise ValueError("release list response is invalid")
        pages.append(page)
    return pages


def resolve_draft_release(path: Path, *, tag: str) -> int:
    if _TAG_RE.fullmatch(tag) is None:
        raise ValueError("release tag must be canonical vX.Y.Z")
    matches = [
        release
        for page in _release_pages(path)
        for release in page
        if release.get("tag_name") == tag
    ]
    if any(not isinstance(release.get("draft"), bool) for release in matches):
        raise ValueError("release list response is invalid")
    if any(release["draft"] is False for release in matches):
        raise ValueError("published release already uses exact tag")
    drafts = [release for release in matches if release["draft"] is True]
    if len(drafts) != 1:
        raise ValueError("expected exactly one draft release for exact tag")
    release_id = drafts[0].get("id")
    if isinstance(release_id, bool) or not isinstance(release_id, int) or release_id <= 0:
        raise ValueError("draft release id is invalid")
    return release_id


def resolve_to_file(path: Path, *, tag: str, output: Path) -> Path:
    release_id = resolve_draft_release(path, tag=tag)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{release_id}\n", encoding="ascii")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        resolve_to_file(args.releases, tag=args.tag, output=args.output)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
