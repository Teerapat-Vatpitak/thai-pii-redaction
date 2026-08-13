"""The tag build must publish the finalized Linux AppImage bytes."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "release_tauri_build.py"

_spec = importlib.util.spec_from_file_location("release_tauri_build", SCRIPT)
release_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_build)


def _backend(root: Path, triple: str, value: bytes = b"pre-linuxdeploy") -> Path:
    path = root / "desktop" / "src-tauri" / "binaries" / f"aiguard-{triple}"
    path.parent.mkdir(parents=True)
    path.write_bytes(value)
    return path


def test_preserve_appimage_backend_copies_exact_bytes_and_refuses_overwrite(tmp_path):
    triple = "x86_64-unknown-linux-gnu"
    source = _backend(tmp_path, triple)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()

    preserved = release_build.preserve_appimage_backend(tmp_path, runner_temp, triple)

    assert preserved.read_bytes() == source.read_bytes()
    if os.name != "nt":
        assert preserved.stat().st_mode & 0o777 == 0o755
    with pytest.raises(FileExistsError, match="preserved AppImage backend"):
        release_build.preserve_appimage_backend(tmp_path, runner_temp, triple)


def test_linux_build_finalizes_then_replaces_the_raw_appimage_signature(tmp_path, monkeypatch):
    triple = "x86_64-unknown-linux-gnu"
    source = _backend(tmp_path, triple)
    desktop = tmp_path / "desktop"
    plugin = tmp_path / "runner-temp" / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.parent.mkdir()
    plugin.write_bytes(b"pinned-plugin")
    appimage_root = desktop / "src-tauri" / "target" / "release" / "bundle" / "appimage"
    appimage = appimage_root / "AI.Guard_3.0.0_amd64.AppImage"
    appdir = appimage_root / "AI.Guard.AppDir"
    signature = Path(f"{appimage}.sig")
    calls: list[tuple[list[str], Path]] = []

    monkeypatch.setattr(release_build, "host_triple", lambda: triple)

    def fake_run(command, *, cwd):
        command = [str(value) for value in command]
        calls.append((command, cwd))
        if command[:4] == ["npm", "run", "tauri", "--"] and command[4] == "build":
            appimage_root.mkdir(parents=True)
            appimage.write_bytes(b"raw-appimage")
            appdir.mkdir()
            signature.write_bytes(b"stale-raw-signature")
        elif "--finalize-appimage" in command:
            assert signature.read_bytes() == b"stale-raw-signature"
            appimage.write_bytes(b"finalized-appimage")
        elif command[-3:-1] == ["signer", "sign"]:
            assert not signature.exists()
            signature.write_bytes(b"final-signature")

    release_build.build(
        ["build", "--bundles", "deb,appimage"],
        root=tmp_path,
        platform="linux",
        environ={
            "RUNNER_TEMP": str(plugin.parent),
            "AIGUARD_APPIMAGE_PLUGIN": str(plugin),
        },
        run_checked=fake_run,
    )

    assert appimage.read_bytes() == b"finalized-appimage"
    assert signature.read_bytes() == b"final-signature"
    assert "--finalize-appimage" in calls[1][0]
    assert calls[2][0][-3:] == ["signer", "sign", str(appimage)]
    assert not (plugin.parent / "aiguard-appimage-backend").samefile(source)


def test_non_linux_build_is_an_exact_tauri_passthrough(tmp_path):
    calls = []

    def fake_run(command, *, cwd):
        calls.append(([str(value) for value in command], cwd))

    release_build.build(
        ["build", "--bundles", "nsis"],
        root=tmp_path,
        platform="win32",
        environ={},
        run_checked=fake_run,
    )

    assert calls == [
        (["npm.cmd", "run", "tauri", "--", "build", "--bundles", "nsis"], tmp_path / "desktop")
    ]


@pytest.mark.parametrize("command", ([], ["signer", "sign", "artifact"]))
def test_release_wrapper_rejects_any_command_other_than_build(tmp_path, command):
    with pytest.raises(ValueError, match="only accepts the Tauri build command"):
        release_build.build(command, root=tmp_path, platform=os.name, environ={})
