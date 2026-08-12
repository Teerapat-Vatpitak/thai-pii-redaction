from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.native_host_identity import load_extension_identity
from scripts.prepare_desktop_native_package import assemble_package

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = ROOT / "tests" / "fixtures" / "native_host" / "synthetic-extension-identity.json"
PRODUCTION_IDENTITY = ROOT / "config" / "chrome-extension-identity.json"


def _component(path: Path, version: str, *, marker: bool = True) -> Path:
    body = b"synthetic-component"
    if marker:
        body += f"AIGUARD_NATIVE_COMPONENT_BUILD_ID={version}\0".encode()
    path.write_bytes(body)
    return path


def test_desktop_candidate_contains_adapter_manager_and_exact_test_origin(tmp_path: Path):
    version = "2.5.0"
    suffix = ".exe" if os.name == "nt" else ""
    sources = {
        "desktop": _component(tmp_path / f"desktop{suffix}", version),
        "broker": _component(tmp_path / f"aiguard-native-broker{suffix}", version),
        "backend": _component(tmp_path / f"aiguard{suffix}", version, marker=False),
        "adapter": _component(tmp_path / f"aiguard-chrome-native-host{suffix}", version),
        "manager": _component(tmp_path / f"aiguard-native-host-manager{suffix}", version),
    }
    identity = load_extension_identity(IDENTITY, allow_synthetic=True)
    manifest_path = assemble_package(
        tmp_path / "package",
        **sources,
        version=version,
        identity=identity,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [(client["component_id"], client["role"]) for client in manifest["clients"]] == [
        ("desktop", "desktop"),
        ("chrome-native-host", "extension"),
        ("native-host-manager", "maintenance"),
    ]
    assert manifest["native_host"] == {
        "name": "th.ac.psu.aiguard.native_host",
        "allowed_origin": identity.origin,
        "identity_classification": "synthetic_test_only",
    }
    assert (manifest_path.parent / f"aiguard-chrome-native-host{suffix}").is_file()
    assert (manifest_path.parent / f"aiguard-native-host-manager{suffix}").is_file()


def test_partial_native_host_package_inputs_fail_closed(tmp_path: Path):
    version = "2.5.0"
    suffix = ".exe" if os.name == "nt" else ""
    identity = load_extension_identity(IDENTITY, allow_synthetic=True)
    with pytest.raises(ValueError, match="incomplete native host"):
        assemble_package(
            tmp_path / "package",
            desktop=_component(tmp_path / f"desktop{suffix}", version),
            broker=_component(tmp_path / f"aiguard-native-broker{suffix}", version),
            backend=_component(tmp_path / f"aiguard{suffix}", version, marker=False),
            adapter=_component(tmp_path / f"aiguard-chrome-native-host{suffix}", version),
            version=version,
            identity=identity,
        )


def test_desktop_candidate_uses_exact_owner_approved_production_origin(tmp_path: Path):
    version = "2.5.0"
    suffix = ".exe" if os.name == "nt" else ""
    identity = load_extension_identity(PRODUCTION_IDENTITY)
    manifest_path = assemble_package(
        tmp_path / "package",
        desktop=_component(tmp_path / f"desktop{suffix}", version),
        broker=_component(tmp_path / f"aiguard-native-broker{suffix}", version),
        backend=_component(tmp_path / f"aiguard{suffix}", version, marker=False),
        adapter=_component(tmp_path / f"aiguard-chrome-native-host{suffix}", version),
        manager=_component(tmp_path / f"aiguard-native-host-manager{suffix}", version),
        version=version,
        identity=identity,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["native_host"] == {
        "name": "th.ac.psu.aiguard.native_host",
        "allowed_origin": "chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/",
        "identity_classification": "production_owner_approved",
    }
