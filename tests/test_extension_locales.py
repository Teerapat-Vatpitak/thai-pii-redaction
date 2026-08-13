"""Horizon-1 #6: Chrome Web Store submission prep.

Covers:
- `extension/_locales/{th,en}/messages.json` parse as valid Chrome i18n
  messages files, with matching keys between locales.
- `extension/manifest.json` wires `default_locale`/`name`/`description` to
  the `__MSG_*__` placeholders backed by those locale files.
- CWS length limits: extension name <=45 chars, description <=132 chars, in
  both locales.
- `scripts/package_extension.py` (stdlib-only, no pip deps) zips
  `extension/` into `dist/aiguard-extension-<VERSION>.zip`, excludes
  README.md, and refuses to build when the manifest version has drifted
  from the root VERSION file.

Stdlib-only (no fastapi import) so this runs in the core-only CI job.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
IDENTITY = ROOT / "tests" / "fixtures" / "native_host" / "synthetic-extension-identity.json"
PRODUCTION_IDENTITY = ROOT / "config" / "chrome-extension-identity.json"

EXTENSION_DIR = ROOT / "extension"
LOCALES_DIR = EXTENSION_DIR / "_locales"
MANIFEST_PATH = EXTENSION_DIR / "manifest.json"

CWS_NAME_MAX = 45
CWS_DESC_MAX = 132


def _load_locale(locale: str) -> dict:
    path = LOCALES_DIR / locale / "messages.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# locale file structure
# ---------------------------------------------------------------------------


def test_th_messages_json_parses():
    data = _load_locale("th")
    assert isinstance(data, dict)
    assert "appName" in data
    assert "appDesc" in data


def test_en_messages_json_parses():
    data = _load_locale("en")
    assert isinstance(data, dict)
    assert "appName" in data
    assert "appDesc" in data


def test_locale_keys_match_between_th_and_en():
    th = set(_load_locale("th").keys())
    en = set(_load_locale("en").keys())
    assert th == en


def test_every_message_entry_has_a_message_string():
    for locale in ("th", "en"):
        data = _load_locale(locale)
        for key, entry in data.items():
            assert isinstance(entry, dict), f"{locale}/{key} must be an object"
            assert isinstance(entry.get("message"), str) and entry["message"], (
                f"{locale}/{key} must have a non-empty 'message' string"
            )


# ---------------------------------------------------------------------------
# CWS length limits
# ---------------------------------------------------------------------------


def test_appName_is_within_cws_45_char_limit_both_locales():
    for locale in ("th", "en"):
        name = _load_locale(locale)["appName"]["message"]
        assert len(name) <= CWS_NAME_MAX, (
            f"{locale} appName is {len(name)} chars, CWS limit is {CWS_NAME_MAX}: {name!r}"
        )


def test_appDesc_is_within_cws_132_char_limit_both_locales():
    for locale in ("th", "en"):
        desc = _load_locale(locale)["appDesc"]["message"]
        assert len(desc) <= CWS_DESC_MAX, (
            f"{locale} appDesc is {len(desc)} chars, CWS limit is {CWS_DESC_MAX}: {desc!r}"
        )


def test_appDesc_describes_only_the_installed_local_detector_boundary():
    for locale in ("th", "en"):
        desc = _load_locale(locale)["appDesc"]["message"].casefold()
        assert "thainer" in desc
        assert "tner" not in desc
        assert "remote" not in desc


# ---------------------------------------------------------------------------
# manifest wiring
# ---------------------------------------------------------------------------


def test_manifest_default_locale_is_th():
    assert _manifest().get("default_locale") == "th"


def test_manifest_name_is_msg_appName_placeholder():
    assert _manifest().get("name") == "__MSG_appName__"


def test_manifest_description_is_msg_appDesc_placeholder():
    assert _manifest().get("description") == "__MSG_appDesc__"


def test_manifest_msg_placeholders_resolve_in_both_locales():
    # A malformed __MSG_x__ (missing from messages.json) makes Chrome refuse
    # to load the extension entirely -- this is the load-bearing check.
    manifest = _manifest()
    for field in ("name", "description"):
        placeholder = manifest[field]
        assert placeholder.startswith("__MSG_") and placeholder.endswith("__")
        key = placeholder[len("__MSG_") : -len("__")]
        for locale in ("th", "en"):
            assert key in _load_locale(locale), f"{locale} messages.json missing key {key!r}"


def test_current_public_docs_do_not_restore_the_retired_http_extension_boundary():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    install = (ROOT / "docs" / "install-from-source.md").read_text(encoding="utf-8")
    combined = "\n".join((readme, security, install))

    assert "one registered Chrome Native Messaging port" in readme
    assert "Extension MV3\n  service worker uses one registered Native Messaging port" in security
    assert "does not supply an Extension endpoint" in install
    for retired in (
        "The Extension and Office paths still use",
        "The extension may retain a security-sensitive opaque HTTP session ID",
        "current source extension requires the current source HTTP-v2 backend",
        "before starting the Extension, Office Add-in",
        "while the separately started fixed-port backend is running",
        "Extension and Office remain fixed-port HTTP-v2 clients",
        '"Backend offline" in the extension',
    ):
        assert retired not in combined


# ---------------------------------------------------------------------------
# scripts/package_extension.py
# ---------------------------------------------------------------------------


def _copy_repo_slice(tmp_path: Path) -> Path:
    """Copy just extension/ + VERSION + the packaging script into a scratch
    dir so tests never touch the real working tree or its real dist/."""
    dest = tmp_path / "repo"
    shutil.copytree(EXTENSION_DIR, dest / "extension")
    shutil.copy2(ROOT / "VERSION", dest / "VERSION")
    (dest / "scripts").mkdir(parents=True)
    shutil.copy2(
        ROOT / "scripts" / "package_extension.py", dest / "scripts" / "package_extension.py"
    )
    shutil.copy2(
        ROOT / "scripts" / "native_host_identity.py",
        dest / "scripts" / "native_host_identity.py",
    )
    fixture_dir = dest / "tests" / "fixtures" / "native_host"
    fixture_dir.mkdir(parents=True)
    shutil.copy2(IDENTITY, fixture_dir / IDENTITY.name)
    return dest


def _run_package(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            PY,
            str(root / "scripts" / "package_extension.py"),
            "--root",
            str(root),
            "--identity",
            str(root / "tests" / "fixtures" / "native_host" / IDENTITY.name),
            "--allow-synthetic-identity",
        ],
        capture_output=True,
        text=True,
    )


def test_package_extension_builds_zip_named_with_version(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    result = _run_package(repo)
    assert result.returncode == 0, result.stdout + result.stderr

    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    zip_path = repo / "dist" / f"aiguard-extension-{version}.zip"
    assert zip_path.is_file()


def test_package_extension_zip_contains_manifest_and_excludes_readme(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    _run_package(repo)

    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    zip_path = repo / "dist" / f"aiguard-extension-{version}.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        packaged_manifest = json.loads(zf.read("manifest.json"))
        text_files = b"\n".join(
            zf.read(name) for name in names if Path(name).suffix in {".html", ".js", ".json"}
        )

    assert "manifest.json" in names
    assert not any(n.upper().endswith("README.MD") for n in names)
    assert not any(n == "tests" or n.startswith("tests/") for n in names)
    # a sanity spot-check that other real extension files made it in
    assert "background.js" in names
    assert "theme-bootstrap.js" in names
    assert "_locales/th/messages.json" in names
    assert "_locales/en/messages.json" in names
    assert "icons/icon128.png" in names
    identity = json.loads(IDENTITY.read_text(encoding="utf-8"))
    assert packaged_manifest["key"] == identity["public_key"]
    assert "key" not in _manifest()

    for forbidden in (
        b"localhost",
        b"127.0.0.1",
        b"fetch(",
        b"AIGUARD_API_KEY",
        b"AIFORTHAI_API_KEY",
        b"TOKENMIND_API_KEY",
        b"backend_url",
        b"backend_port",
        b"session_id",
    ):
        assert forbidden not in text_files


def test_package_extension_builds_owner_approved_production_identity_without_override(tmp_path):
    result = subprocess.run(
        [
            PY,
            str(ROOT / "scripts" / "package_extension.py"),
            "--root",
            str(ROOT),
            "--dist-dir",
            str(tmp_path),
            "--identity",
            str(PRODUCTION_IDENTITY),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    zip_path = tmp_path / f"aiguard-extension-{version}.zip"
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        packaged_text = b"\n".join(
            zf.read(name) for name in names if Path(name).suffix in {".html", ".js", ".json"}
        )

    decoded = base64.b64decode(manifest["key"], validate=True)
    digest = hashlib.sha256(decoded).hexdigest()[:32]
    derived_id = "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)
    assert derived_id == "kdjmkknedgmfphpkjhjdhmjadaelgggm"
    assert manifest["permissions"] == [
        "storage",
        "clipboardWrite",
        "sidePanel",
        "nativeMessaging",
    ]
    assert "host_permissions" not in manifest
    assert b"efocdbdljgaaiflfleofbjpenncenhee" not in packaged_text
    assert b"localhost" not in packaged_text
    assert b"127.0.0.1" not in packaged_text
    assert b"fetch(" not in packaged_text


def test_package_extension_has_reproducible_zip_metadata(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    command = [
        PY,
        str(ROOT / "scripts" / "package_extension.py"),
        "--root",
        str(ROOT),
        "--identity",
        str(PRODUCTION_IDENTITY),
    ]
    first_result = subprocess.run(
        [*command, "--dist-dir", str(first)], capture_output=True, text=True
    )
    second_result = subprocess.run(
        [*command, "--dist-dir", str(second)], capture_output=True, text=True
    )
    assert first_result.returncode == 0, first_result.stdout + first_result.stderr
    assert second_result.returncode == 0, second_result.stdout + second_result.stderr

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    first_zip = first / f"aiguard-extension-{version}.zip"
    second_zip = second / f"aiguard-extension-{version}.zip"

    assert first_zip.read_bytes() == second_zip.read_bytes()
    with zipfile.ZipFile(first_zip) as archive:
        assert archive.infolist()
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert info.external_attr >> 16 == 0o100644


def test_package_extension_refuses_to_create_an_identityless_storefront_artifact(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    result = subprocess.run(
        [PY, str(repo / "scripts" / "package_extension.py"), "--root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "identity" in (result.stdout + result.stderr).casefold()
    assert not (repo / "dist").exists() or not any((repo / "dist").iterdir())


def test_package_extension_fails_on_version_mismatch(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    manifest_path = repo / "extension" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["version"] = "0.0.1"
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    result = _run_package(repo)
    assert result.returncode == 1
    assert "bump_version" in (result.stdout + result.stderr)
    assert not (repo / "dist").exists() or not any((repo / "dist").iterdir())


@pytest.mark.parametrize("link_kind", ["file", "directory"])
def test_package_extension_rejects_links_before_creating_an_artifact(tmp_path, link_kind):
    repo = _copy_repo_slice(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "synthetic-secret.txt"
    target.write_text("synthetic-private-sentinel", encoding="utf-8")
    link = repo / "extension" / "linked-outside"
    try:
        if link_kind == "directory":
            os.symlink(outside, link, target_is_directory=True)
        else:
            os.symlink(target, link)
    except OSError as error:
        pytest.skip(f"symbolic links unavailable: {error}")

    result = _run_package(repo)

    assert result.returncode == 1
    assert "link" in (result.stdout + result.stderr).casefold()
    assert not (repo / "dist").exists() or not any((repo / "dist").iterdir())


def test_package_extension_rejects_hard_links_before_creating_an_artifact(tmp_path):
    repo = _copy_repo_slice(tmp_path)
    outside = repo / "outside-synthetic-private-sentinel.txt"
    outside.write_text("synthetic-private-sentinel", encoding="utf-8")
    link = repo / "extension" / "linked-outside-hardlink"
    try:
        os.link(outside, link)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")

    result = _run_package(repo)

    assert result.returncode == 1
    assert "hard link" in (result.stdout + result.stderr).casefold()
    assert not (repo / "dist").exists() or not any((repo / "dist").iterdir())


def test_package_extension_is_stdlib_only():
    # Must run in the core-only CI job -- no fastapi/requests/etc imports.
    source = (ROOT / "scripts" / "package_extension.py").read_text(encoding="utf-8")
    for banned in ("import fastapi", "import requests", "import httpx"):
        assert banned not in source


def test_public_release_and_privacy_text_describes_live_panel_retention_honestly():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").casefold()
    policy = (ROOT / "docs" / "store" / "privacy-policy.md").read_text(encoding="utf-8")
    policy_folded = policy.casefold()
    policy_words = " ".join(policy_folded.split())

    assert "outside storefront state" not in changelog
    assert "live side-panel" in changelog
    assert "until you clear or replace" in policy_words
    assert "closed or reloaded" in policy_words
    assert "not written to chrome storage or disk" in policy_words
    assert "หน่วยความจำของเอกสารแผงด้านข้างที่เปิดอยู่" in policy
    assert "จนกว่าคุณจะล้างหรือแทนที่" in policy
    assert "ไม่เขียนลง chrome storage หรือดิสก์" in policy_folded


def test_v3_native_broker_protocol_examples_do_not_claim_v2_5_runtime():
    protocol = (ROOT / "docs" / "native-broker-protocol-v1.md").read_text(encoding="utf-8")
    assert "2.5.0" not in protocol
