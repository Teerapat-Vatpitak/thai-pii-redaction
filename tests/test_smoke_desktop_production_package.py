"""Black-box checks for exact non-feature-gated release package bytes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "smoke_desktop_production_package.py"

_spec = importlib.util.spec_from_file_location("smoke_desktop_production_package", SCRIPT)
production = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(production)


def _package(root: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    names = {
        "desktop": f"desktop{suffix}",
        "broker": f"aiguard-native-broker{suffix}",
        "backend": f"aiguard{suffix}",
    }
    for role, name in names.items():
        path = root / name
        path.write_bytes(f"{role}-production-bytes".encode())
        if os.name != "nt":
            path.chmod(0o755)
    manifest = {
        "schema_version": 1,
        "product_version": "3.0.0",
        "clients": [
            {
                "component_id": "desktop",
                "role": "desktop",
                "path": names["desktop"],
                "sha256": hashlib.sha256((root / names["desktop"]).read_bytes()).hexdigest(),
                "build_id": "3.0.0",
            }
        ],
        "broker": {
            "component_id": "native-broker",
            "path": names["broker"],
            "sha256": hashlib.sha256((root / names["broker"]).read_bytes()).hexdigest(),
            "build_id": "3.0.0",
        },
        "backend": {
            "component_id": "python-backend",
            "path": names["backend"],
            "sha256": hashlib.sha256((root / names["backend"]).read_bytes()).hexdigest(),
            "build_id": "3.0.0",
        },
    }
    (root / "native-components-v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_load_package_binds_exact_regular_component_bytes(tmp_path):
    attestation = production.load_package(_package(tmp_path))

    assert attestation.product_version == "3.0.0"
    assert set(attestation.components) == {"desktop", "broker", "backend"}
    assert all(len(item.sha256) == 64 for item in attestation.components.values())


def test_load_package_rejects_digest_substitution_and_links(tmp_path):
    package = _package(tmp_path)
    (package / ("aiguard.exe" if os.name == "nt" else "aiguard")).write_bytes(b"substituted")
    with pytest.raises(RuntimeError, match="component verification failed"):
        production.load_package(package)


def test_package_unchanged_rejects_post_attestation_mutation(tmp_path):
    package = _package(tmp_path)
    attestation = production.load_package(package)
    backend = package / ("aiguard.exe" if os.name == "nt" else "aiguard")
    backend.write_bytes(b"changed after attestation")

    with pytest.raises(RuntimeError, match="component verification failed"):
        production.verify_package_unchanged(attestation)

    package = _package(tmp_path)
    desktop = package / ("desktop.exe" if os.name == "nt" else "desktop")
    target = tmp_path.parent / "outside-desktop"
    target.write_bytes(desktop.read_bytes())
    desktop.unlink()
    try:
        os.symlink(target, desktop)
    except OSError as error:
        pytest.skip(f"symbolic links unavailable: {error}")
    with pytest.raises(RuntimeError, match="component verification failed"):
        production.load_package(package)


def test_value_free_evidence_contains_no_paths_or_process_ids(tmp_path):
    attestation = production.load_package(_package(tmp_path))
    evidence = production.build_evidence(
        attestation,
        mode="direct",
        durations_ms=[120, 130],
    )
    encoded = json.dumps(evidence, sort_keys=True)

    assert evidence["schema"] == "aiguard-production-package-smoke/v1"
    assert evidence["status"] == "passed"
    assert str(tmp_path) not in encoded
    assert "pid" not in encoded.casefold()
    assert set(evidence["components"]) == {"desktop", "broker", "backend"}


def test_smoke_observes_all_three_exact_components_and_cleans_up(tmp_path, monkeypatch):
    package = _package(tmp_path)
    fake_processes = {role: [object()] for role in ("desktop", "broker", "backend")}
    terminated = []

    class Child:
        pid = 123

        @staticmethod
        def poll():
            return None

    ticks = iter(index * 0.6 for index in range(50))
    monkeypatch.setattr(production, "psutil", object())
    monkeypatch.setattr(production.subprocess, "Popen", lambda *_args, **_kwargs: Child())
    monkeypatch.setattr(production, "_matching_processes", lambda *_args: fake_processes)
    monkeypatch.setattr(production, "_all_absent", lambda *_args: True)
    monkeypatch.setattr(
        production,
        "_terminate",
        lambda processes, child: terminated.append((processes, child.pid)),
    )
    monkeypatch.setattr(production.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(production.time, "sleep", lambda _seconds: None)

    evidence = production.smoke(
        package,
        launcher=None,
        mode="direct",
        repetitions=1,
        timeout=30,
    )

    assert evidence["status"] == "passed"
    assert len(terminated) == 1
    assert len(terminated[0][0]) == 3


def test_release_workflow_smokes_every_exact_production_package_class():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--features package-smoke" not in workflow
    assert workflow.count("scripts/smoke_desktop_production_package.py") >= 5
    assert "production-nsis-smoke-evidence.json" in workflow
    assert "production-dmg-smoke-evidence.json" in workflow
    assert "production-updater-smoke-evidence.json" in workflow
    assert "production-deb-smoke-evidence.json" in workflow
    assert "production-appimage-extract-smoke-evidence.json" in workflow
    assert "production-appimage-fuse-smoke-evidence.json" in workflow
    assert "--mode appimage-extract-and-run" in workflow
    assert (
        'APPIMAGE_EXTRACT_AND_RUN=1 "$GITHUB_WORKSPACE/$appimage" --unregister-native-host'
        in workflow
    )
    assert "production-appimage-registration-absent.json" in workflow
    for phase in (
        "updater repair passed",
        "updater registration-present check passed",
        "updater process smoke passed",
        "updater unregister passed",
        "updater registration-absent check passed",
        "dmg attach passed",
        "dmg copy passed",
        "dmg detach passed",
        "dmg repair passed",
        "dmg registration-present check passed",
        "dmg process smoke passed",
        "dmg unregister passed",
        "dmg registration-absent check passed",
    ):
        assert f"mac production phase: {phase}" in workflow
    copy_app = 'ditto "$dmg_app" "$work/dmg/AI Guard.app"'
    detach = 'hdiutil detach "$mount" >/dev/null'
    copied_package = 'dmg_package="$work/dmg/AI Guard.app/Contents/MacOS"'
    assert copy_app in workflow
    assert copied_package in workflow
    copy_offset = workflow.index(copy_app)
    assert copy_offset < workflow.index(detach, copy_offset) < workflow.index(copied_package)
