from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import verify_native_host_registration as registration

ORIGIN = "chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/"
PRODUCTION_ORIGIN = "chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/"


def _write_manifest(manifest_path: Path, adapter: Path, **changes: object) -> None:
    document = {
        "allowed_origins": [ORIGIN],
        "description": "AI Guard Chrome Native Messaging adapter",
        "name": registration.HOST_NAME,
        "path": str(adapter),
        "type": "stdio",
    }
    document.update(changes)
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    if os.name != "nt":
        manifest_path.chmod(0o644)


def test_exact_registration_manifest_is_accepted_without_projecting_values(tmp_path):
    adapter = tmp_path / "adapter"
    adapter.write_bytes(b"synthetic adapter")
    manifest = tmp_path / registration.MANIFEST_NAME
    _write_manifest(manifest, adapter)

    registration._verify_manifest(
        manifest,
        adapter,
        ORIGIN,
        None if os.name == "nt" else os.geteuid(),
    )


def test_production_registration_admits_only_the_owner_approved_origin(tmp_path):
    adapter = tmp_path / "adapter"
    adapter.write_bytes(b"synthetic adapter")
    manifest = tmp_path / registration.MANIFEST_NAME
    _write_manifest(manifest, adapter, allowed_origins=[PRODUCTION_ORIGIN])

    registration._verify_manifest(
        manifest,
        adapter,
        PRODUCTION_ORIGIN,
        None if os.name == "nt" else os.geteuid(),
    )
    with pytest.raises(ValueError, match="registration-check-failed"):
        registration._verify_manifest(manifest, adapter, ORIGIN, None)


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_origins": ["chrome-extension://*/"]},
        {"name": "wrong.host"},
        {"path": "relative-adapter"},
        {"unknown": True},
    ],
)
def test_broad_wrong_or_unknown_registration_values_fail_closed(tmp_path, changes):
    adapter = tmp_path / "adapter"
    adapter.write_bytes(b"synthetic adapter")
    manifest = tmp_path / registration.MANIFEST_NAME
    _write_manifest(manifest, adapter, **changes)

    with pytest.raises(ValueError, match="registration-check-failed"):
        registration._verify_manifest(manifest, adapter, ORIGIN, None)


def test_appimage_registration_paths_are_per_user_and_browser_specific(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    paths = registration._manifest_paths("appimage")

    assert len(paths) == 3
    assert len(set(paths)) == 3
    assert all(path.is_absolute() for path in paths)
    assert {path.parts[-3] for path in paths} == {
        "chromium",
        "google-chrome",
        "google-chrome-for-testing",
    }
