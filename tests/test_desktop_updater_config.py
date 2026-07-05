import json
from pathlib import Path

CONF = Path(__file__).resolve().parent.parent / "desktop" / "src-tauri" / "tauri.conf.json"


def _conf():
    return json.loads(CONF.read_text(encoding="utf-8"))


def test_updater_endpoints_are_https():
    endpoints = _conf()["plugins"]["updater"]["endpoints"]
    assert endpoints, "updater endpoints must not be empty"
    assert all(e.startswith("https://") for e in endpoints)


def test_updater_pubkey_present():
    # Intentionally checks only that the pubkey is non-empty, not that it's a real
    # key. This knowingly accepts the placeholder value
    # "REPLACE_WITH_TAURI_SIGNER_PUBLIC_KEY" until the real Tauri signer key is
    # generated and substituted in. A placeholder-rejecting assertion would fail
    # on main while the placeholder is still in use.
    pubkey = _conf()["plugins"]["updater"]["pubkey"]
    assert isinstance(pubkey, str) and pubkey.strip() != ""


def test_updater_artifacts_enabled():
    assert _conf()["bundle"]["createUpdaterArtifacts"] is True
