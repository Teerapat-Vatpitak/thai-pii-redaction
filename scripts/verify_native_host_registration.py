#!/usr/bin/env python3
"""Verify exact Chrome Native Messaging registration without printing values."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

try:
    from scripts.native_host_identity import load_extension_identity
except ModuleNotFoundError:  # Direct script execution adds scripts/ to sys.path.
    from native_host_identity import load_extension_identity


HOST_NAME = "th.ac.psu.aiguard.native_host"
MANIFEST_NAME = f"{HOST_NAME}.json"


def _manifest_paths(shape: str) -> list[Path]:
    if shape == "macos":
        root = Path(os.environ["HOME"]) / "Library" / "Application Support"
        return [
            root / "Google" / "Chrome" / "NativeMessagingHosts" / MANIFEST_NAME,
            root / "Google" / "ChromeForTesting" / "NativeMessagingHosts" / MANIFEST_NAME,
            root / "Chromium" / "NativeMessagingHosts" / MANIFEST_NAME,
        ]
    if shape == "deb":
        return [
            Path("/etc/opt/chrome/native-messaging-hosts") / MANIFEST_NAME,
            Path("/etc/opt/chrome_for_testing/native-messaging-hosts") / MANIFEST_NAME,
            Path("/etc/chromium/native-messaging-hosts") / MANIFEST_NAME,
        ]
    if shape == "appimage":
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path(os.environ["HOME"]) / ".config"))
        return [
            root / "google-chrome" / "NativeMessagingHosts" / MANIFEST_NAME,
            root / "google-chrome-for-testing" / "NativeMessagingHosts" / MANIFEST_NAME,
            root / "chromium" / "NativeMessagingHosts" / MANIFEST_NAME,
        ]
    if shape == "nsis":
        return []
    raise ValueError("registration-check-invalid")


def _same_path(left: str | Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(os.fspath(left))) == os.path.normcase(
        os.path.normpath(os.fspath(right))
    )


def _verify_manifest(path: Path, adapter: Path, origin: str, expected_uid: int | None) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError("registration-check-failed")
    if os.name != "nt":
        if stat.S_IMODE(metadata.st_mode) != 0o644:
            raise ValueError("registration-check-failed")
        if expected_uid is not None and metadata.st_uid != expected_uid:
            raise ValueError("registration-check-failed")
    document = json.loads(path.read_text(encoding="utf-8"))
    if set(document) != {"allowed_origins", "description", "name", "path", "type"}:
        raise ValueError("registration-check-failed")
    if (
        document["allowed_origins"] != [origin]
        or document["name"] != HOST_NAME
        or document["type"] != "stdio"
        or document["description"] != "AI Guard Chrome Native Messaging adapter"
        or not isinstance(document["path"], str)
        or not _same_path(document["path"], adapter)
    ):
        raise ValueError("registration-check-failed")


def _windows_registry_values(*, allow_missing: bool = False) -> list[str]:
    import winreg

    values = []
    for product in (r"Google\Chrome", "Chromium"):
        subkey = rf"Software\{product}\NativeMessagingHosts\{HOST_NAME}"
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    subkey,
                    0,
                    winreg.KEY_READ | view,
                )
            except FileNotFoundError:
                if allow_missing:
                    continue
                raise
            with key:
                value, value_type = winreg.QueryValueEx(key, None)
            if value_type != winreg.REG_SZ or not isinstance(value, str):
                raise ValueError("registration-check-failed")
            values.append(value)
    return values


def verify(shape: str, state: str, adapter: Path, origin: str) -> dict[str, object]:
    if not adapter.is_absolute():
        raise ValueError("registration-check-invalid")
    if state == "present" and not adapter.is_file():
        raise ValueError("registration-check-failed")
    if shape == "nsis":
        manifest = adapter.parent / MANIFEST_NAME
        if state == "present":
            _verify_manifest(manifest, adapter, origin, None)
            values = _windows_registry_values()
            if len(values) != 4 or any(not _same_path(value, manifest) for value in values):
                raise ValueError("registration-check-failed")
            count = len(values)
        else:
            if _windows_registry_values(allow_missing=True):
                raise ValueError("registration-check-failed")
            if manifest.exists():
                raise ValueError("registration-check-failed")
            count = 0
    else:
        paths = _manifest_paths(shape)
        if state == "present":
            expected_uid = 0 if shape == "deb" else os.geteuid()
            for path in paths:
                _verify_manifest(path, adapter, origin, expected_uid)
            count = len(paths)
        else:
            if any(path.exists() or path.is_symlink() for path in paths):
                raise ValueError("registration-check-failed")
            count = 0
    return {"registration_count": count, "shape": shape, "state": state}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shape", required=True, choices=("nsis", "macos", "deb", "appimage"))
    parser.add_argument("--state", required=True, choices=("present", "absent"))
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--allow-synthetic-identity", action="store_true")
    args = parser.parse_args()
    try:
        identity = load_extension_identity(
            args.identity.resolve(), allow_synthetic=args.allow_synthetic_identity
        )
        evidence = verify(args.shape, args.state, args.adapter.absolute(), identity.origin)
        evidence["identity_classification"] = identity.classification
    except (FileNotFoundError, KeyError, OSError, ValueError, json.JSONDecodeError):
        print("native-host-registration-check-failed", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
