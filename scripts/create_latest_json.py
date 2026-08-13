#!/usr/bin/env python3
"""Create canonical Tauri updater metadata from one exact draft release."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import stat
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from create_release_build_manifest import required_build_artifacts  # noqa: E402

_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_AUXILIARY_ASSETS = frozenset({"latest.json", "SHA256SUMS"})


def _regular_text(path: Path, *, maximum: int) -> str:
    metadata = path.stat() if path.exists() else None
    if (
        path.is_symlink()
        or metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= maximum
    ):
        raise ValueError(f"invalid text input: {path.name}")
    return path.read_text(encoding="utf-8")


def _build_document(path: Path) -> tuple[str, dict[str, dict[str, object]]]:
    try:
        document = json.loads(_regular_text(path, maximum=1024 * 1024))
        if document["schema"] != "aiguard-release-build/v1":
            raise ValueError
        version = document["version"]
        expected = required_build_artifacts(version)
        artifacts: dict[str, dict[str, object]] = {}
        for item in document["artifacts"]:
            name = item["name"]
            if (
                not isinstance(name, str)
                or name in artifacts
                or not isinstance(item["size"], int)
                or item["size"] <= 0
                or not isinstance(item["sha256"], str)
                or _SHA256_RE.fullmatch(item["sha256"]) is None
            ):
                raise ValueError
            artifacts[name] = item
        if set(artifacts) != expected:
            raise ValueError
    except (KeyError, TypeError, json.JSONDecodeError, ValueError):
        raise ValueError("invalid current-run build manifest") from None
    return version, artifacts


def _release_assets(
    path: Path, build: dict[str, dict[str, object]]
) -> dict[str, dict[str, object]]:
    try:
        items = json.loads(_regular_text(path, maximum=1024 * 1024))
        if not isinstance(items, list):
            raise ValueError
        assets: dict[str, dict[str, object]] = {}
        for item in items:
            name = item["name"]
            asset_id = item["id"]
            size = item["size"]
            if (
                not isinstance(name, str)
                or name in assets
                or isinstance(asset_id, bool)
                or not isinstance(asset_id, int)
                or asset_id <= 0
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
            ):
                raise ValueError
            assets[name] = item
    except (KeyError, TypeError, json.JSONDecodeError, ValueError):
        raise ValueError("invalid exact-release asset metadata") from None

    missing = sorted(set(build) - set(assets))
    if missing:
        raise ValueError(f"missing release assets: {', '.join(missing)}")
    unexpected = sorted(set(assets) - set(build) - _AUXILIARY_ASSETS)
    if unexpected:
        raise ValueError(f"unexpected release assets: {', '.join(unexpected)}")
    for name, expected in build.items():
        if assets[name]["size"] != expected["size"]:
            raise ValueError(f"release asset size differs from current run: {name}")
    return assets


def _signature(directory: Path, name: str) -> str:
    text = _regular_text(directory / name, maximum=16 * 1024).strip()
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ValueError(f"invalid updater signature: {name}") from None
    if not decoded:
        raise ValueError(f"invalid updater signature: {name}")
    return text


def create_latest(
    *,
    build_manifest: Path,
    asset_metadata: Path,
    signatures_dir: Path,
    notes_path: Path,
    pub_date: str,
    repository: str,
    output: Path,
) -> Path:
    version, build = _build_document(build_manifest)
    assets = _release_assets(asset_metadata, build)
    if _REPOSITORY_RE.fullmatch(repository) is None:
        raise ValueError("repository must be owner/name")
    try:
        parsed_date = dt.datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        if parsed_date.tzinfo is None:
            raise ValueError
    except ValueError:
        raise ValueError("pub_date must be an offset-aware ISO-8601 timestamp") from None
    notes = _regular_text(notes_path, maximum=256 * 1024)

    windows = f"AI.Guard_{version}_x64-setup.exe"
    macos = f"AI.Guard_{version}_aarch64.app.tar.gz"
    appimage = f"AI.Guard_{version}_amd64.AppImage"
    deb = f"AI.Guard_{version}_amd64.deb"

    def update(asset: str) -> dict[str, str]:
        return {
            "signature": _signature(signatures_dir, f"{asset}.sig"),
            "url": (
                f"https://api.github.com/repos/{repository}/releases/assets/{assets[asset]['id']}"
            ),
        }

    document = {
        "version": version,
        "notes": notes,
        "pub_date": pub_date,
        "platforms": {
            "darwin-aarch64": update(macos),
            "darwin-aarch64-app": update(macos),
            "windows-x86_64": update(windows),
            "windows-x86_64-nsis": update(windows),
            "linux-x86_64": update(appimage),
            "linux-x86_64-appimage": update(appimage),
            "linux-x86_64-deb": update(deb),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--asset-metadata", type=Path, required=True)
    parser.add_argument("--signatures-dir", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--pub-date", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        create_latest(
            build_manifest=args.build_manifest,
            asset_metadata=args.asset_metadata,
            signatures_dir=args.signatures_dir,
            notes_path=args.notes,
            pub_date=args.pub_date,
            repository=args.repository,
            output=args.output,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
