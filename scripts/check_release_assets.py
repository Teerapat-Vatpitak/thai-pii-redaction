#!/usr/bin/env python3
"""Guard the release assets before they are hashed and attested (REL-3).

`release.yml`'s checksums-and-attest job pulls every asset off the draft release
and then publishes `SHA256SUMS` plus GitHub build provenance for all of them.
That set is whatever happens to be on the release at run time, which is not
necessarily what this run built:

- a re-run after a partial failure reuses an existing draft that may still carry
  the previous run's assets (built from a different commit/version),
- tauri-action's matrix can create a second draft for the same tag, so the
  download step's fallback can resolve a partially-populated release,
- anything uploaded to the draft in between would inherit first-party provenance.

This script fails the job when the asset set is not internally consistent with
the version being released:

- every filename carrying a semver-looking token must carry THIS version,
- at least one asset must be named for this version,
- a filename with NO version must be one of the known unversioned release
  artifacts (SHA256SUMS / latest.json) -- otherwise an arbitrary upload like
  `payload.zip` or `AI-Guard-Setup.exe` would sail through and be attested.

Known limitation (deliberate): this does NOT assert platform coverage, so a
partially-populated release (e.g. only the Windows leg finished) still passes.
Enumerating tauri-action's exact per-platform bundle names for a pipeline that
has never run risks falsely failing the first real release, which would be worse
than the gap. Revisit once a real tagged run shows the true asset set.

Pure stdlib so it runs before any dependency install.

Usage:
    python scripts/check_release_assets.py --dir release-assets --expect-version 2.3.0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# A semver token delimited by non-digits, so "x64", "aarch64", "en-US" and
# "SHA256SUMS" never read as a version.
_VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")

# Release artifacts that legitimately carry no version in their name. Signature
# files are NOT here: tauri names them "<asset>.sig", so they inherit the
# asset's version and are checked like any other versioned file.
_UNVERSIONED_ALLOWED = frozenset({"SHA256SUMS", "latest.json"})


def version_tokens(name: str) -> set[str]:
    """Every semver-looking token in a filename (empty set if none)."""
    return set(_VERSION_RE.findall(name))


def check(assets_dir: Path, expected: str) -> list[str]:
    """Return human-readable problems; empty means the asset set is consistent."""
    if not assets_dir.is_dir():
        return [f"asset directory not found: {assets_dir}"]

    files = sorted(p.name for p in assets_dir.iterdir() if p.is_file())
    if not files:
        return [f"no assets found in {assets_dir}"]

    problems: list[str] = []
    matched_expected = False
    for name in files:
        tokens = version_tokens(name)
        if not tokens:
            if name not in _UNVERSIONED_ALLOWED:
                problems.append(
                    f"{name}: carries no version and is not a known release "
                    f"artifact ({', '.join(sorted(_UNVERSIONED_ALLOWED))}); "
                    "refusing to hash/attest an unexpected upload"
                )
            continue
        if expected in tokens:
            matched_expected = True
        foreign = sorted(t for t in tokens if t != expected)
        if foreign:
            problems.append(
                f"{name}: carries version {', '.join(foreign)} but this release is "
                f"{expected} (stale asset from another run/release?)"
            )
    if not matched_expected:
        problems.append(
            f"no asset is named for version {expected}; the download step likely "
            "resolved the wrong release"
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="directory of downloaded assets")
    parser.add_argument("--expect-version", required=True, help="the VERSION being released")
    args = parser.parse_args()

    problems = check(args.dir.resolve(), args.expect_version)
    if problems:
        print("Release asset check FAILED — refusing to hash/attest this set:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: every versioned asset in {args.dir} belongs to {args.expect_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
