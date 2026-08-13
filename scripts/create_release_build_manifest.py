#!/usr/bin/env python3
"""Bind the closed Desktop release asset set to one workflow run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path

_VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
_GIT_ID_RE = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID_RE = re.compile(r"[1-9]\d*\Z")


def required_build_artifacts(version: str) -> set[str]:
    """Exact GitHub Release bytes produced by the three Desktop matrix jobs."""
    if _VERSION_RE.fullmatch(version) is None:
        raise ValueError("version must be canonical X.Y.Z")
    windows = f"AI.Guard_{version}_x64-setup.exe"
    macos = f"AI.Guard_{version}_aarch64.app.tar.gz"
    deb = f"AI.Guard_{version}_amd64.deb"
    appimage = f"AI.Guard_{version}_amd64.AppImage"
    return {
        windows,
        f"{windows}.sig",
        f"AI.Guard_{version}_aarch64.dmg",
        macos,
        f"{macos}.sig",
        deb,
        f"{deb}.sig",
        appimage,
        f"{appimage}.sig",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(directory: Path, *, output: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise ValueError(f"build artifact directory not found: {directory}")
    indexed: dict[str, Path] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (path.is_file() and path.stat().st_nlink != 1):
            raise ValueError(f"build artifact must not be a symlink: {path}")
        if (
            not path.is_file()
            or not stat.S_ISREG(path.stat().st_mode)
            or path.resolve() == output.resolve()
        ):
            continue
        if path.name in indexed:
            raise ValueError(f"duplicate build artifact: {path.name}")
        indexed[path.name] = path
    return indexed


def create_manifest(
    directory: Path,
    *,
    version: str,
    source_sha: str,
    source_tree: str,
    run_id: str,
    run_attempt: int,
    output: Path,
) -> Path:
    expected = required_build_artifacts(version)
    for label, value in (("source_sha", source_sha), ("source_tree", source_tree)):
        if _GIT_ID_RE.fullmatch(value) is None:
            raise ValueError(f"{label} must be 40 lowercase hexadecimal characters")
    if _RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run_id must be a positive decimal identifier")
    if isinstance(run_attempt, bool) or not isinstance(run_attempt, int) or run_attempt < 1:
        raise ValueError("run_attempt must be a positive integer")

    files = _files(directory.resolve(), output=output)
    missing = sorted(expected - set(files))
    if missing:
        raise ValueError(f"missing build artifacts: {', '.join(missing)}")
    unexpected = sorted(set(files) - expected)
    if unexpected:
        raise ValueError(f"unexpected build artifacts: {', '.join(unexpected)}")

    artifacts = []
    for name in sorted(expected):
        path = files[name]
        size = path.stat().st_size
        if size == 0:
            raise ValueError(f"build artifact is empty: {name}")
        artifacts.append(
            {
                "name": name,
                "size": size,
                "sha256": _sha256(path),
                "source_sha": source_sha,
            }
        )
    document = {
        "schema": "aiguard-release-build/v1",
        "version": version,
        "source_sha": source_sha,
        "source_tree": source_tree,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "artifacts": artifacts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        create_manifest(
            args.dir,
            version=args.version,
            source_sha=args.source_sha,
            source_tree=args.source_tree,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            output=args.output,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
