#!/usr/bin/env python3
"""Require the exact current-run release bytes before hashing or attesting.

The draft is mutable. A matching version in a filename is therefore not proof
that an asset came from this workflow run. This gate enforces a closed filename
set and, in release mode, compares every Desktop byte with the current-run build
manifest and compares updater metadata with the locally generated latest.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path

# A semver token delimited by non-digits, so "x64", "aarch64", "en-US" and
# "SHA256SUMS" never read as a version.
_VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")

# Release artifacts that legitimately carry no version in their name. Signature
# files are NOT here: tauri names them "<asset>.sig", so they inherit the
# asset's version and are checked like any other versioned file.
_UNVERSIONED_ALLOWED = frozenset({"SHA256SUMS", "latest.json"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def required_build_assets(version: str) -> set[str]:
    """Closed Desktop artifact set produced by the Tauri matrix."""
    return {
        f"AI.Guard_{version}_x64-setup.exe",
        f"AI.Guard_{version}_x64-setup.exe.sig",
        f"AI.Guard_{version}_aarch64.dmg",
        f"AI.Guard_{version}_aarch64.app.tar.gz",
        f"AI.Guard_{version}_aarch64.app.tar.gz.sig",
    }


def required_assets(version: str) -> set[str]:
    """Closed downloadable set before SHA256SUMS is added."""
    return {*required_build_assets(version), "latest.json"}


def version_tokens(name: str) -> set[str]:
    """Every semver-looking token in a filename (empty set if none)."""
    return set(_VERSION_RE.findall(name))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_artifacts(
    path: Path, expected: str
) -> tuple[dict[str, dict[str, object]], list[str]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema"] != "aiguard-release-build/v1" or document["version"] != expected:
            raise ValueError
        artifacts: dict[str, dict[str, object]] = {}
        for item in document["artifacts"]:
            name = item["name"]
            if (
                not isinstance(name, str)
                or name in artifacts
                or isinstance(item["size"], bool)
                or not isinstance(item["size"], int)
                or item["size"] <= 0
                or not isinstance(item["sha256"], str)
                or _SHA256_RE.fullmatch(item["sha256"]) is None
            ):
                raise ValueError
            artifacts[name] = item
        if set(artifacts) != required_build_assets(expected):
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}, ["current workflow run build manifest is invalid or incomplete"]
    return artifacts, []


def _check_sums(assets_dir: Path, expected_names: set[str]) -> list[str]:
    sums = assets_dir / "SHA256SUMS"
    if not sums.exists():
        return []
    try:
        lines = sums.read_text(encoding="ascii").splitlines()
        entries: dict[str, str] = {}
        for line in lines:
            match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
            if match is None or match.group(2) in entries:
                raise ValueError
            entries[match.group(2)] = match.group(1)
        if set(entries) != expected_names:
            raise ValueError
        for name, digest in entries.items():
            if _sha256(assets_dir / name) != digest:
                raise ValueError
    except (OSError, UnicodeError, ValueError):
        return ["SHA256SUMS is not a complete digest map of the closed release set"]
    return []


def check(
    assets_dir: Path,
    expected: str,
    *,
    build_manifest: Path | None = None,
    expected_latest: Path | None = None,
) -> list[str]:
    """Return human-readable problems; empty means the asset set is exact."""
    if not assets_dir.is_dir():
        return [f"asset directory not found: {assets_dir}"]

    entries = sorted(assets_dir.iterdir(), key=lambda path: path.name)
    files = sorted(
        p.name for p in entries if p.is_file() and not p.is_symlink() and p.stat().st_nlink == 1
    )
    if not files:
        return [f"no assets found in {assets_dir}"]

    problems: list[str] = []
    for path in entries:
        if (
            path.is_symlink()
            or not path.is_file()
            or not stat.S_ISREG(path.stat().st_mode)
            or path.stat().st_nlink != 1
        ):
            problems.append(f"{path.name}: release asset must be a regular top-level file")
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
    allowed = {*required_assets(expected), "SHA256SUMS"}
    unexpected = sorted(set(files) - allowed)
    if unexpected:
        problems.append(
            "release contains unexpected assets outside the closed set: " + ", ".join(unexpected)
        )
    missing = sorted(required_assets(expected) - set(files))
    if missing:
        problems.append("release is missing required cross-platform assets: " + ", ".join(missing))

    if build_manifest is not None:
        artifacts, manifest_problems = _manifest_artifacts(build_manifest, expected)
        problems.extend(manifest_problems)
        for name, item in artifacts.items():
            path = assets_dir / name
            if not path.is_file() or path.is_symlink():
                continue
            if path.stat().st_size != item["size"] or _sha256(path) != item["sha256"]:
                problems.append(
                    f"{name}: bytes differ from the current workflow run build manifest"
                )
    if expected_latest is not None:
        latest = assets_dir / "latest.json"
        try:
            if latest.read_bytes() != expected_latest.read_bytes():
                raise ValueError
        except (OSError, ValueError):
            problems.append("latest.json differs from the locally generated current-run file")
    problems.extend(_check_sums(assets_dir, required_assets(expected)))
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True, help="directory of downloaded assets")
    parser.add_argument("--expect-version", required=True, help="the VERSION being released")
    parser.add_argument(
        "--build-manifest",
        type=Path,
        help="current-run aiguard-release-build/v1 manifest",
    )
    parser.add_argument(
        "--expected-latest",
        type=Path,
        help="locally generated latest.json that the draft must contain byte-for-byte",
    )
    args = parser.parse_args()

    if (args.build_manifest is None) != (args.expected_latest is None):
        parser.error("--build-manifest and --expected-latest must be supplied together")
    problems = check(
        args.dir.resolve(),
        args.expect_version,
        build_manifest=args.build_manifest.resolve() if args.build_manifest else None,
        expected_latest=args.expected_latest.resolve() if args.expected_latest else None,
    )
    if problems:
        print("Release asset check FAILED — refusing to hash/attest this set:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: closed release set matches current-run bytes for {args.expect_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
