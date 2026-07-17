"""scripts/update_packaging.py: winget/scoop manifest bump (Horizon-2 #11).

Runs against a throwaway copy of packaging/ under tmp_path (same convention
as test_version_source.py) and never touches the network -- only the pure
functions (parse_hash, plan_writes) are exercised.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "update_packaging", ROOT / "scripts" / "update_packaging.py"
)
up = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(up)

SHA = "ab" * 32
DATE = "2026-08-01"


@pytest.fixture()
def pkg_root(tmp_path):
    shutil.copytree(ROOT / "packaging", tmp_path / "packaging")
    return tmp_path


def _apply(root, version="9.9.9", sha=SHA, date=DATE):
    for path, text in up.plan_writes(root, version, sha, date):
        path.write_text(text, encoding="utf-8")


def _snapshot(root):
    return {
        p: p.read_text(encoding="utf-8")
        for p in sorted((root / "packaging").rglob("*"))
        if p.is_file()
    }


def test_installer_name():
    assert up.installer_name("9.9.9") == "AI.Guard_9.9.9_x64-setup.exe"


def test_parse_hash_standard_format():
    sums = f"{SHA}  AI.Guard_9.9.9_x64-setup.exe\n{'cd' * 32}  latest.json\n"
    assert up.parse_hash(sums, "AI.Guard_9.9.9_x64-setup.exe") == SHA


def test_parse_hash_binary_marker():
    sums = f"{SHA} *AI.Guard_9.9.9_x64-setup.exe\n"
    assert up.parse_hash(sums, "AI.Guard_9.9.9_x64-setup.exe") == SHA


def test_parse_hash_missing_exits():
    with pytest.raises(SystemExit):
        up.parse_hash(f"{SHA}  something-else.dmg\n", "AI.Guard_9.9.9_x64-setup.exe")


def test_rewrites_all_four_files(pkg_root):
    _apply(pkg_root)
    winget = pkg_root / "packaging" / "winget"
    for fname in (
        "Teerapat-Vatpitak.AIGuard.yaml",
        "Teerapat-Vatpitak.AIGuard.locale.en-US.yaml",
    ):
        assert "PackageVersion: 9.9.9" in (winget / fname).read_text(encoding="utf-8")
    inst = (winget / "Teerapat-Vatpitak.AIGuard.installer.yaml").read_text(
        encoding="utf-8"
    )
    assert "PackageVersion: 9.9.9" in inst
    assert "DisplayVersion: 9.9.9" in inst
    assert f"ReleaseDate: {DATE}" in inst
    assert (
        "InstallerUrl: https://github.com/Teerapat-Vatpitak/thai-pii-redaction"
        "/releases/download/v9.9.9/AI.Guard_9.9.9_x64-setup.exe" in inst
    )
    assert f"InstallerSha256: {SHA.upper()}" in inst
    scoop = json.loads(
        (pkg_root / "packaging" / "scoop" / "aiguard.json").read_text(encoding="utf-8")
    )
    assert scoop["version"] == "9.9.9"
    assert scoop["architecture"]["64bit"]["url"].endswith(
        "AI.Guard_9.9.9_x64-setup.exe#/dl.7z"
    )
    assert scoop["architecture"]["64bit"]["hash"] == SHA


def test_autoupdate_template_untouched(pkg_root):
    _apply(pkg_root)
    scoop = json.loads(
        (pkg_root / "packaging" / "scoop" / "aiguard.json").read_text(encoding="utf-8")
    )
    assert "$version" in scoop["autoupdate"]["architecture"]["64bit"]["url"]


def test_idempotent(pkg_root):
    _apply(pkg_root)
    first = _snapshot(pkg_root)
    _apply(pkg_root)
    assert _snapshot(pkg_root) == first


def test_layout_drift_exits_without_writing(pkg_root):
    inst = pkg_root / "packaging" / "winget" / "Teerapat-Vatpitak.AIGuard.installer.yaml"
    inst.write_text(
        inst.read_text(encoding="utf-8").replace("InstallerSha256:", "InstallerSHA:"),
        encoding="utf-8",
    )
    before = _snapshot(pkg_root)
    with pytest.raises(SystemExit):
        up.plan_writes(pkg_root, "9.9.9", SHA, DATE)
    assert _snapshot(pkg_root) == before


def test_scoop_layout_drift_exits_without_writing(pkg_root):
    scoop = pkg_root / "packaging" / "scoop" / "aiguard.json"
    data = json.loads(scoop.read_text(encoding="utf-8"))
    del data["architecture"]  # structural drift the script must refuse
    scoop.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    before = _snapshot(pkg_root)
    with pytest.raises(SystemExit):
        up.plan_writes(pkg_root, "9.9.9", SHA, DATE)
    assert _snapshot(pkg_root) == before
