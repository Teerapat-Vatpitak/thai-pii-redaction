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

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

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
    return dest


def _run_package(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, str(root / "scripts" / "package_extension.py"), "--root", str(root)],
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

    assert "manifest.json" in names
    assert not any(n.upper().endswith("README.MD") for n in names)
    # a sanity spot-check that other real extension files made it in
    assert "background.js" in names
    assert "_locales/th/messages.json" in names
    assert "_locales/en/messages.json" in names
    assert "icons/icon128.png" in names


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


def test_package_extension_is_stdlib_only():
    # Must run in the core-only CI job -- no fastapi/requests/etc imports.
    source = (ROOT / "scripts" / "package_extension.py").read_text(encoding="utf-8")
    for banned in ("import fastapi", "import requests", "import httpx"):
        assert banned not in source
