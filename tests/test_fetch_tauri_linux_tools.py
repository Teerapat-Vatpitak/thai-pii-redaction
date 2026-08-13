"""Tauri's mutable Linux bundling helpers are preseeded from immutable bytes."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "fetch_tauri_linux_tools.py"

_spec = importlib.util.spec_from_file_location("fetch_tauri_linux_tools", SCRIPT)
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _tool(name: str, value: bytes, *, post_value: bytes | None = None):
    return fetch.Tool(
        name=name,
        url="https://api.github.com/repos/owner/repo/releases/assets/123",
        size=len(value),
        sha256=hashlib.sha256(value).hexdigest(),
        post_build_sha256=(hashlib.sha256(post_value).hexdigest() if post_value else None),
    )


def test_repository_pins_every_tauri_cache_input_to_immutable_content():
    assert {tool.name for tool in fetch.TOOLS} == {
        "AppRun-x86_64",
        "linuxdeploy-x86_64.AppImage",
        "linuxdeploy-plugin-gtk.sh",
        "linuxdeploy-plugin-gstreamer.sh",
        "linuxdeploy-plugin-appimage.AppImage",
    }
    for tool in fetch.TOOLS:
        assert len(tool.sha256) == 64
        assert tool.size > 0
        assert "/continuous/" not in tool.url
        assert "/master/" not in tool.url
        assert "raw.githubusercontent.com" not in tool.url or any(
            len(part) == 40 and all(c in "0123456789abcdef" for c in part)
            for part in tool.url.split("/")
        )
    urls = {tool.name: tool.url for tool in fetch.TOOLS}
    assert urls["AppRun-x86_64"].endswith("/tauri-apps/binary-releases/releases/assets/274691722")
    assert urls["linuxdeploy-x86_64.AppImage"].endswith(
        "/tauri-apps/binary-releases/releases/assets/182515537"
    )
    assert "/b5eb8d05b4c0ed40107fe2158c5d8527f94568ef/" in urls["linuxdeploy-plugin-gtk.sh"]
    assert "/2a2e67491c32995a3f279ad0ecbe77abd512b42a/" in urls["linuxdeploy-plugin-gstreamer.sh"]


def test_install_downloads_to_the_exact_cache_name_and_verifies_bytes(tmp_path):
    value = b"pinned tool bytes"
    tool = _tool("tool.AppImage", value)
    seen = []

    def opener(request, timeout):
        seen.append((request.full_url, request.headers, timeout))
        return _Response(value)

    fetch.install_tools(tmp_path, token="synthetic-token", tools=(tool,), opener=opener)

    assert (tmp_path / tool.name).read_bytes() == value
    assert seen[0][0] == tool.url
    assert seen[0][2] > 0
    assert any(key.casefold() == "authorization" for key in seen[0][1])


def test_raw_commit_download_never_receives_the_workflow_token(tmp_path):
    value = b"pinned raw script"
    tool = fetch.Tool(
        name="tool.sh",
        url=(
            "https://raw.githubusercontent.com/owner/repo/"
            "0123456789012345678901234567890123456789/tool.sh"
        ),
        size=len(value),
        sha256=hashlib.sha256(value).hexdigest(),
    )
    seen = []

    def opener(request, timeout):
        seen.append((request.headers, timeout))
        return _Response(value)

    fetch.install_tools(tmp_path, token="synthetic-token", tools=(tool,), opener=opener)

    assert not any(key.casefold() == "authorization" for key in seen[0][0])


def test_install_rejects_corrupt_download_without_leaving_a_cache_file(tmp_path):
    tool = _tool("tool.AppImage", b"expected")

    with pytest.raises(RuntimeError, match="digest mismatch"):
        fetch.install_tools(
            tmp_path,
            token=None,
            tools=(tool,),
            opener=lambda *_args, **_kwargs: _Response(b"corrupt!"),
        )

    assert not (tmp_path / tool.name).exists()


def test_post_build_verification_accepts_only_the_declared_tauri_mutation(tmp_path):
    original = b"0123456789abcdef"
    mutated = bytearray(original)
    mutated[8:11] = b"\0\0\0"
    tool = _tool("linuxdeploy-x86_64.AppImage", original, post_value=bytes(mutated))
    path = tmp_path / tool.name
    path.write_bytes(bytes(mutated))
    if os.name != "nt":
        path.chmod(0o750)

    fetch.verify_cache(tmp_path, tools=(tool,), after_build=True)

    path.write_bytes(b"x" * len(mutated))
    with pytest.raises(RuntimeError, match="changed unexpectedly"):
        fetch.verify_cache(tmp_path, tools=(tool,), after_build=True)


def test_install_preapplies_the_idempotent_linuxdeploy_header_patch(tmp_path):
    original = b"0123456789abcdef"
    mutated = bytearray(original)
    mutated[8:11] = b"\0\0\0"
    tool = _tool("linuxdeploy-x86_64.AppImage", original, post_value=bytes(mutated))

    fetch.install_tools(
        tmp_path,
        token=None,
        tools=(tool,),
        opener=lambda *_args, **_kwargs: _Response(original),
    )

    assert (tmp_path / tool.name).read_bytes() == bytes(mutated)
    fetch.verify_cache(tmp_path, tools=(tool,), after_build=True)


def test_cache_verification_rejects_any_helper_outside_the_closed_set(tmp_path):
    value = b"pinned"
    tool = _tool("tool.AppImage", value)
    path = tmp_path / tool.name
    path.write_bytes(value)
    if os.name != "nt":
        path.chmod(0o750)
    (tmp_path / "unexpected-helper").write_bytes(b"extra")

    with pytest.raises(RuntimeError, match="cache changed unexpectedly"):
        fetch.verify_cache(tmp_path, tools=(tool,))


def test_release_workflow_preseeds_and_reverifies_tauri_tools():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "scripts/fetch_tauri_linux_tools.py" in workflow
    assert "--verify-after-build" in workflow
    assert "releases/download/continuous" not in workflow
    assert "raw.githubusercontent.com" not in workflow
