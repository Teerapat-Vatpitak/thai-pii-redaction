#!/usr/bin/env python3
"""Package `extension/` into a Chrome Web Store upload zip.

Pure stdlib, no dependencies -- runs without a `pip install` step (same
constraint as `scripts/check_version.py`/`scripts/bump_version.py`).

Refuses to build if `extension/manifest.json`'s `version` has drifted from
the root `VERSION` file (single source of truth -- see `scripts/bump_version.py`),
so a stale build can never be uploaded to the store by accident.

Usage:
    python scripts/package_extension.py
    python scripts/package_extension.py --root <path> --dist-dir <path>   # used by tests

Output: `<dist-dir>/aiguard-extension-<VERSION>.zip` containing the runtime
contents of `extension/`. Developer README and test files are not shipped.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

from native_host_identity import load_extension_identity

EXCLUDED_NAMES = {"README.md"}
EXCLUDED_DIRECTORIES = {"tests"}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _zip_info(name: str) -> zipfile.ZipInfo:
    """Return stable regular-file metadata for a reproducible upload ZIP."""
    info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _read_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def _is_link_or_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _runtime_source_files(extension_dir: Path) -> tuple[Path, list[Path]]:
    """Return regular runtime files without following any filesystem link."""
    try:
        if _is_link_or_reparse(extension_dir):
            raise ValueError("extension source links are forbidden")
        canonical_root = extension_dir.resolve(strict=True)
        if not canonical_root.is_dir():
            raise ValueError("extension source must be a directory")
    except OSError:
        raise ValueError("extension source is unavailable") from None

    files: list[Path] = []

    def walk_error(_error: OSError) -> None:
        raise ValueError("extension source is unavailable")

    for current, directory_names, file_names in os.walk(
        extension_dir, topdown=True, followlinks=False, onerror=walk_error
    ):
        current_path = Path(current)
        for name in sorted([*directory_names, *file_names]):
            path = current_path / name
            try:
                metadata = path.lstat()
                if _is_link_or_reparse(path):
                    raise ValueError("extension source links are forbidden")
                resolved = path.resolve(strict=True)
            except OSError:
                raise ValueError("extension source is unavailable") from None
            if not resolved.is_relative_to(canonical_root):
                raise ValueError("extension source escaped its root")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("extension source must contain only regular files")
            if metadata.st_nlink != 1:
                raise ValueError("extension source hard links are forbidden")
            relative = path.relative_to(extension_dir)
            if path.name in EXCLUDED_NAMES or set(relative.parts[:-1]) & EXCLUDED_DIRECTORIES:
                continue
            files.append(path)
    return canonical_root, sorted(files)


def _read_verified_regular(path: Path, canonical_root: Path) -> bytes:
    """Read one already-enumerated file and reject a link or replacement race."""
    try:
        before = path.lstat()
        if _is_link_or_reparse(path) or not stat.S_ISREG(before.st_mode):
            raise ValueError("extension source links are forbidden")
        if before.st_nlink != 1:
            raise ValueError("extension source hard links are forbidden")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(canonical_root):
            raise ValueError("extension source escaped its root")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise ValueError("extension source changed during packaging")
            value = handle.read()
        after = path.lstat()
        if _is_link_or_reparse(path) or (
            after.st_dev,
            after.st_ino,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        ) != (
            before.st_dev,
            before.st_ino,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        ):
            raise ValueError("extension source changed during packaging")
        return value
    except OSError:
        raise ValueError("extension source is unavailable") from None


def build_zip(
    root: Path,
    identity_path: Path,
    dist_dir: Path | None = None,
    *,
    allow_synthetic_identity: bool = False,
) -> Path:
    """Build the CWS upload zip and return its path.

    Raises `ValueError` if the manifest version has drifted from VERSION.
    """
    identity = load_extension_identity(
        identity_path,
        allow_synthetic=allow_synthetic_identity,
    )
    extension_dir = root / "extension"
    canonical_root, files = _runtime_source_files(extension_dir)
    encoded_files = [
        (path.relative_to(extension_dir).as_posix(), _read_verified_regular(path, canonical_root))
        for path in files
    ]
    expected = _read_version(root)
    try:
        source_manifest = next(value for name, value in encoded_files if name == "manifest.json")
    except StopIteration:
        raise ValueError("extension manifest is missing") from None
    manifest = json.loads(source_manifest.decode("utf-8"))
    found = manifest["version"]
    if "key" in manifest:
        raise ValueError("source manifest must not contain an identity key")
    if found != expected:
        raise ValueError(
            f"extension/manifest.json version ({found!r}) does not match "
            f"VERSION ({expected!r}). Run `python scripts/bump_version.py {expected}` "
            "to resync, or fix by hand."
        )

    dist_dir = dist_dir or (root / "dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / f"aiguard-extension-{expected}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for archive_name, value in encoded_files:
            if archive_name == "manifest.json":
                manifest["key"] = identity.public_key
                encoded = json.dumps(manifest, ensure_ascii=True, indent=2) + "\n"
                value = encoded.encode("utf-8")
            zf.writestr(_zip_info(archive_name), value)

    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repo root containing extension/ and VERSION (default: repo root this script lives in)",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="Output directory for the zip (default: <root>/dist)",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        help="Owner-approved public Extension identity JSON",
    )
    parser.add_argument(
        "--allow-synthetic-identity",
        action="store_true",
        help="Allow the isolated public-only test identity for acceptance fixtures",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    dist_dir = args.dist_dir.resolve() if args.dist_dir else None

    try:
        if args.identity is None:
            raise ValueError("an owner-approved extension identity is required")
        zip_path = build_zip(
            root,
            args.identity.resolve(),
            dist_dir,
            allow_synthetic_identity=args.allow_synthetic_identity,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"built {zip_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
