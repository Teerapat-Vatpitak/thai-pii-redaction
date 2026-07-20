"""REL-3: the checksums-and-attest job hashes and attests whatever assets are
sitting on the draft release at run time, not necessarily what this run built.
A re-run over an existing draft, tauri-action's matrix creating a second draft,
or anything uploaded in between could get first-party provenance.

scripts/check_release_assets.py is the gate: before hashing, assert every asset
that carries a version in its filename carries THIS version, so assets left over
from a different release can never be signed as part of this one.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SCRIPT = ROOT / "scripts" / "check_release_assets.py"

_spec = importlib.util.spec_from_file_location("check_release_assets", SCRIPT)
check_release_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_release_assets)


def _run(assets_dir: Path, version: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(SCRIPT), "--dir", str(assets_dir), "--expect-version", version],
        capture_output=True,
        text=True,
    )


def _touch(d: Path, *names: str) -> None:
    for n in names:
        (d / n).write_bytes(b"x")


def test_accepts_assets_all_on_the_expected_version(tmp_path):
    _touch(
        tmp_path,
        "AI.Guard_2.3.0_x64-setup.exe",
        "AI.Guard_2.3.0_x64_en-US.msi",
        "AI.Guard_2.3.0_aarch64.dmg",
        "ai-guard_2.3.0_amd64.AppImage",
    )
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_a_stale_asset_from_another_version(tmp_path):
    """The documented failure: a re-run over a draft still holding the previous
    run's (different-version) assets would attest them as this release."""
    _touch(tmp_path, "AI.Guard_2.3.0_x64-setup.exe", "AI.Guard_2.2.0_x64-setup.exe")
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1
    assert "2.2.0" in (result.stdout + result.stderr)


def test_rejects_empty_asset_dir(tmp_path):
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1


def test_rejects_when_no_asset_carries_the_expected_version(tmp_path):
    """If nothing on the release is named for this version, the download step
    resolved the wrong release — do not hash/attest it."""
    _touch(tmp_path, "SHA256SUMS", "latest.json")
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1


def test_ignores_unversioned_sidecar_files(tmp_path):
    """SHA256SUMS / latest.json / .sig carry no version and must not trip the
    check as long as a real versioned asset is present."""
    _touch(
        tmp_path,
        "AI.Guard_2.3.0_x64-setup.exe",
        "AI.Guard_2.3.0_x64-setup.exe.sig",
        "latest.json",
        "SHA256SUMS",
    )
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 0, result.stdout + result.stderr


def test_download_dir_does_not_collide_with_a_tracked_path():
    """REL-3 regression: the checksums job checks out the repo (to read VERSION
    and this script), so its asset download dir must not be a path the repo
    already tracks. `assets/` IS tracked (logos), and `mkdir assets` under the
    Actions default `bash -e` shell would abort the job — no SHA256SUMS, no
    attestation, on every release."""
    # Deliberately no PyYAML: this guard must also run in the core-only install
    # job (requirements.txt has no yaml), so it scans the raw workflow text.
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    git = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if git.returncode != 0:
        pytest.skip("git not available to list tracked files")
    tracked_top_level = {p.split("/")[0] for p in git.stdout.splitlines() if "/" in p}
    mkdirs = re.findall(r"^\s*mkdir(?:\s+-\S+)*\s+(\S+)", text, re.MULTILINE)
    assert mkdirs, "expected the job to create a download directory"
    for d in mkdirs:
        assert d.strip('"') not in tracked_top_level, (
            f"download dir {d!r} collides with tracked directory {d!r}; "
            "checkout would make mkdir fail and kill the job"
        )


def test_unversioned_asset_is_rejected_unless_allowlisted(tmp_path):
    """REL-3: an asset with no version in its name (a foreign upload to the
    draft) must not silently ride along into SHA256SUMS + attestation."""
    _touch(tmp_path, "AI.Guard_2.3.0_x64-setup.exe", "payload.zip")
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1
    assert "payload.zip" in (result.stdout + result.stderr)


def test_version_tokens_helper_extracts_semver_only():
    f = check_release_assets.version_tokens
    assert f("AI.Guard_2.3.0_x64-setup.exe") == {"2.3.0"}
    assert f("ai-guard_10.20.30_amd64.AppImage") == {"10.20.30"}
    # x64 / aarch64 / en-US must not read as versions
    assert f("AI.Guard_2.3.0_x64_en-US.msi") == {"2.3.0"}
    assert f("SHA256SUMS") == set()
