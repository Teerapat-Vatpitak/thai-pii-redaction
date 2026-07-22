"""DESK-3 — the webview capability must stay minimal.

The frontend only calls three custom invoke commands (update_check,
update_install, quit_app); the global shortcut, clipboard and sidecar work is
all done Rust-side, which never consults webview capabilities. Granting
shell:allow-execute / clipboard-manager / global-shortcut to the webview means
an XSS there (see DESK-4) escalates to re-executing AIGuard.exe with arbitrary
args and reading the clipboard. This test pins the grants OUT of the file.
"""

import json
from pathlib import Path

CAP_FILE = (
    Path(__file__).resolve().parent.parent
    / "desktop"
    / "src-tauri"
    / "capabilities"
    / "default.json"
)


def _permission_ids() -> list[str]:
    data = json.loads(CAP_FILE.read_text(encoding="utf-8"))
    ids = []
    for perm in data["permissions"]:
        ids.append(perm["identifier"] if isinstance(perm, dict) else perm)
    return ids


def test_webview_has_no_shell_execute_grant():
    assert not any(p.startswith("shell:") for p in _permission_ids())


def test_webview_has_no_clipboard_or_global_shortcut_grants():
    ids = _permission_ids()
    assert not any(p.startswith("clipboard-manager:") for p in ids)
    assert not any(p.startswith("global-shortcut:") for p in ids)


def test_webview_keeps_the_grants_it_actually_needs():
    ids = _permission_ids()
    assert "core:default" in ids
    assert "core:tray:default" in ids
    assert "updater:default" in ids
