"""Horizon-1 #5: single-source version.

Covers:
- `/api/health` and the FastAPI app version both match the root `VERSION` file
  (not a hardcoded string in app/server.py).
- `app.server._read_version()` prefers a PyInstaller `sys._MEIPASS` copy of
  VERSION when frozen, and falls back to a hardcoded string when VERSION can't
  be found anywhere (e.g. an old frozen exe built before VERSION was added to
  PyInstaller datas).
- `scripts/check_version.py` detects real drift (exit 1, lists the offending
  file) and passes when everything is consistent (exit 0).
- `scripts/bump_version.py` writes the new version into every tracked file,
  after which `check_version.py` passes.

All script tests run against a throwaway copy of just the version-bearing
files (under tmp_path) so they never mutate the real working tree.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


def _version_file_contents() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# app/server.py runtime version
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_health_version_matches_VERSION_file():
    from app.server import app

    client = TestClient(app, base_url="http://localhost")
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == _version_file_contents()


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_fastapi_app_version_matches_VERSION_file():
    from app.server import app

    assert app.version == _version_file_contents()


def test_server_fallback_literal_matches_version_file():
    """The last-resort version literal in app/server.py sits OUTSIDE the
    single-source system (bump_version/check_version do not touch it). Guard it
    by reading the source as text — no fastapi import — so a bump that forgets
    the literal fails even on the core-only (no-fastapi) CI job."""
    src = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    literals = re.findall(r'return\s+"(\d+\.\d+\.\d+)"', src)
    assert literals, "no fallback version literal found in app/server.py"
    for lit in literals:
        assert lit == _version_file_contents(), (
            f"app/server.py fallback literal {lit!r} != VERSION "
            f"{_version_file_contents()!r} — bump it by hand at release"
        )


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_read_version_falls_back_when_file_missing(monkeypatch, tmp_path):
    # app.server imports fastapi at module top level, so a core-only install
    # must skip here even though _read_version() itself is stdlib-only.
    from app import server

    missing_module_path = tmp_path / "nowhere" / "app" / "server.py"
    monkeypatch.setattr(server, "__file__", str(missing_module_path))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert server._read_version() == "2.2.0"


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_read_version_prefers_meipass_when_frozen(monkeypatch, tmp_path):
    # Same core-only guard as above: importing app.server needs fastapi.
    from app import server

    frozen_dir = tmp_path / "frozen"
    frozen_dir.mkdir()
    (frozen_dir / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_dir), raising=False)

    assert server._read_version() == "9.9.9"


# ---------------------------------------------------------------------------
# scripts/check_version.py + scripts/bump_version.py
# ---------------------------------------------------------------------------

_TRACKED_FILES = [
    "VERSION",
    "extension/manifest.json",
    "desktop/src-tauri/tauri.conf.json",
    "desktop/src-tauri/Cargo.toml",
    "desktop/src-tauri/Cargo.lock",
    "desktop/package.json",
]


def _copy_repo_slice(tmp_path: Path) -> Path:
    """Copy only the files the scripts touch into a scratch dir, plus the
    scripts themselves, so tests never mutate the real working tree."""
    dest = tmp_path / "repo"
    for rel in _TRACKED_FILES:
        src = ROOT / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for script in ("check_version.py", "bump_version.py", "_version_targets.py"):
        shutil.copy2(ROOT / "scripts" / script, dest / script)
    return dest


def _run_check(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(root / "check_version.py"), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_check_version_passes_when_all_files_match(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    result = _run_check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_version_detects_drift_via_cargo_toml_regex(tmp_path):
    # Exercises the regex-based (non-JSON) getter path end to end.
    repo = _copy_repo_slice(tmp_path)
    cargo_toml = repo / "desktop" / "src-tauri" / "Cargo.toml"
    text = cargo_toml.read_text(encoding="utf-8")
    drifted = text.replace('version = "2.2.0"', 'version = "1.2.3"', 1)
    assert drifted != text
    cargo_toml.write_text(drifted, encoding="utf-8")

    result = _run_check(repo)
    assert result.returncode == 1
    assert "Cargo.toml" in result.stdout


def test_check_version_fails_when_required_file_is_unparseable(tmp_path):
    # A getter returning None on a REQUIRED file means the parser no longer
    # understands the file's structure -- the drift gate must fail loudly,
    # not silently pass. Simulate Cargo.lock's desktop block growing a
    # `source = ...` line between name and version, which breaks the anchored
    # regex.
    repo = _copy_repo_slice(tmp_path)
    cargo_lock = repo / "desktop" / "src-tauri" / "Cargo.lock"
    text = cargo_lock.read_text(encoding="utf-8")
    broken = text.replace(
        '[[package]]\nname = "desktop"\nversion = ',
        '[[package]]\nname = "desktop"\nsource = "somewhere"\nversion = ',
        1,
    )
    assert broken != text
    cargo_lock.write_text(broken, encoding="utf-8")

    result = _run_check(repo)
    assert result.returncode == 1
    assert "could not parse" in result.stdout
    assert "Cargo.lock" in result.stdout


def test_check_version_fails_on_real_drift(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    manifest_path = repo / "extension" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["version"] = "1.2.3"
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    result = _run_check(repo)
    assert result.returncode == 1
    assert "manifest.json" in result.stdout


def test_bump_version_writes_every_tracked_file(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    bump = subprocess.run(
        [PY, str(repo / "bump_version.py"), "9.9.9", "--root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert bump.returncode == 0, bump.stdout + bump.stderr

    assert (repo / "VERSION").read_text(encoding="utf-8").strip() == "9.9.9"

    manifest = json.loads((repo / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "9.9.9"

    tauri_conf = json.loads(
        (repo / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    assert tauri_conf["version"] == "9.9.9"

    cargo_toml = (repo / "desktop" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    assert 'version = "9.9.9"' in cargo_toml

    cargo_lock = (repo / "desktop" / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
    assert 'name = "desktop"\nversion = "9.9.9"' in cargo_lock

    package_json = json.loads((repo / "desktop" / "package.json").read_text(encoding="utf-8"))
    assert package_json["version"] == "9.9.9"

    # check_version must now agree everything is consistent.
    result = _run_check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bump_version_rejects_non_semver(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    bump = subprocess.run(
        [PY, str(repo / "bump_version.py"), "not-a-version", "--root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert bump.returncode != 0
    # Nothing should have been touched on a rejected input.
    assert (repo / "VERSION").read_text(encoding="utf-8").strip() == _version_file_contents()


def test_bump_version_never_targets_packaging_dir():
    # packaging/ (winget/scoop manifests) carries release-specific hashes that
    # must be regenerated at release time -- bump_version must never write there.
    sys.path.insert(0, str(ROOT / "scripts"))
    from _version_targets import targets  # noqa: PLC0415

    tracked_paths = [str(rel_path) for rel_path, *_ in targets(ROOT)]
    assert not any(p.startswith("packaging") for p in tracked_paths)
