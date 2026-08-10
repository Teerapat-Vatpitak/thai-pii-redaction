"""DESK-3 — the webview capability must stay minimal.

Application operations use compiled, typed Tauri commands. The one framework
grant lets the main webview listen for native authority invalidation. Granting
shell, clipboard, global-shortcut, updater, or broader core permissions would
turn a renderer compromise into unnecessary native authority.
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


def test_webview_has_only_the_authority_invalidation_listener_grant():
    assert _permission_ids() == ["core:event:allow-listen"]
