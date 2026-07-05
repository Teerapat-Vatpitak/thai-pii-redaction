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
    # The real Tauri signer public key is now in place (generated for the v2.1.0
    # release). Reject the old placeholder so it can never regress back in: an
    # unsigned/placeholder pubkey would silently break auto-update verification.
    pubkey = _conf()["plugins"]["updater"]["pubkey"]
    assert isinstance(pubkey, str) and pubkey.strip() != ""
    assert pubkey != "REPLACE_WITH_TAURI_SIGNER_PUBLIC_KEY"


def test_updater_artifacts_enabled():
    assert _conf()["bundle"]["createUpdaterArtifacts"] is True
