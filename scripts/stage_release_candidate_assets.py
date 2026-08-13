#!/usr/bin/env python3
"""Stage raw Tauri artifacts under their final GitHub Release filenames."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

if __package__:
    from .create_release_candidate_manifest import required_artifacts
else:
    from create_release_candidate_manifest import required_artifacts

_PLATFORMS = frozenset({"windows", "macos", "linux"})


def _raw_tauri_name(published_name: str, metadata: dict[str, object]) -> str:
    if metadata["os"] == "macos" and metadata["kind"] == "updater-archive":
        return "AI Guard.app.tar.gz"
    if metadata["os"] == "macos" and metadata["kind"] == "updater-signature":
        return "AI Guard.app.tar.gz.sig"
    if not published_name.startswith("AI.Guard_"):
        raise ValueError(f"not a Tauri Desktop artifact: {published_name}")
    return published_name.replace("AI.Guard_", "AI Guard_", 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_assets(
    source: Path,
    *,
    output: Path,
    version: str,
    platform: str,
) -> list[Path]:
    if platform not in _PLATFORMS:
        raise ValueError(f"unsupported release platform: {platform}")
    if not source.is_dir():
        raise ValueError(f"Tauri bundle directory not found: {source}")
    if output.exists():
        raise ValueError(f"output directory already exists: {output}")

    expected = {
        name: metadata
        for name, metadata in required_artifacts(version).items()
        if metadata["os"] == platform
    }
    sources: dict[str, Path] = {}
    for published_name, metadata in expected.items():
        raw_name = _raw_tauri_name(published_name, metadata)
        matches = sorted(source.rglob(raw_name))
        if not matches:
            raise ValueError(f"missing raw Tauri artifact: {raw_name}")
        if len(matches) != 1:
            raise ValueError(f"duplicate raw Tauri artifact: {raw_name}")
        candidate = matches[0]
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"raw Tauri artifact is not a regular file: {raw_name}")
        if candidate.stat().st_size == 0:
            raise ValueError(f"raw Tauri artifact is empty: {raw_name}")
        sources[published_name] = candidate

    output.mkdir(parents=True)
    staged = []
    for published_name in sorted(sources):
        source_path = sources[published_name]
        destination = output / published_name
        shutil.copyfile(source_path, destination)
        if destination.stat().st_size != source_path.stat().st_size or _sha256(
            destination
        ) != _sha256(source_path):
            raise ValueError(f"staged artifact digest mismatch: {published_name}")
        staged.append(destination)
    return staged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", choices=sorted(_PLATFORMS), required=True)
    args = parser.parse_args()
    try:
        stage_assets(
            args.source,
            output=args.output,
            version=args.version,
            platform=args.platform,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
