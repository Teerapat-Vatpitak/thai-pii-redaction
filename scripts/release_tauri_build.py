#!/usr/bin/env python3
"""Build release bundles and seal Linux AppImage bytes before publication.

The Tauri action discovers and uploads artifacts immediately after its build
command returns. Linux therefore needs to finalize the post-linuxdeploy AppDir
and replace the raw AppImage updater signature inside that command boundary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPIMAGE_PLUGIN_NAME = "linuxdeploy-plugin-appimage-x86_64.AppImage"

RunChecked = Callable[..., None]


def _run_checked(command: Sequence[object], *, cwd: Path) -> None:
    subprocess.run([str(value) for value in command], cwd=cwd, check=True)


def host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine the Rust host triple")


def preserve_appimage_backend(root: Path, runner_temp: Path, triple: str) -> Path:
    source = root / "desktop" / "src-tauri" / "binaries" / f"aiguard-{triple}"
    if not source.is_file():
        raise FileNotFoundError(f"staged AppImage backend not found: {source}")
    runner_temp.mkdir(parents=True, exist_ok=True)
    preserved = runner_temp / "aiguard-appimage-backend"
    if preserved.exists():
        raise FileExistsError(f"preserved AppImage backend already exists: {preserved}")
    shutil.copyfile(source, preserved)
    preserved.chmod(0o755)
    if source.read_bytes() != preserved.read_bytes():
        raise RuntimeError("preserved AppImage backend differs from its staged source")
    return preserved


def _single_entry(directory: Path, pattern: str, *, want_directory: bool) -> Path:
    matches = sorted(
        path
        for path in directory.glob(pattern)
        if (path.is_dir() if want_directory else path.is_file())
    )
    if len(matches) != 1:
        kind = "directories" if want_directory else "files"
        raise RuntimeError(f"expected one {pattern} in {directory}, found {len(matches)} {kind}")
    return matches[0]


def _finalize_linux_appimage(
    root: Path,
    runner_temp: Path,
    plugin: Path,
    *,
    npm: str,
    run_checked: RunChecked,
) -> None:
    appimage_root = root / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "appimage"
    appimage = _single_entry(appimage_root, "*.AppImage", want_directory=False)
    appdir = _single_entry(appimage_root, "*.AppDir", want_directory=True)
    preserved = runner_temp / "aiguard-appimage-backend"
    if not preserved.is_file():
        raise FileNotFoundError(f"preserved AppImage backend not found: {preserved}")
    if not plugin.is_file() or plugin.name != APPIMAGE_PLUGIN_NAME:
        raise FileNotFoundError(f"pinned AppImage plugin not found: {plugin}")

    run_checked(
        [
            sys.executable,
            root / "scripts" / "prepare_desktop_native_package.py",
            "--finalize-appimage",
            appimage,
            "--appdir",
            appdir,
            "--appimage-backend-source",
            preserved,
            "--appimage-plugin",
            plugin,
            "--appimage-arch",
            "x86_64",
        ],
        cwd=root,
    )

    signature = Path(f"{appimage}.sig")
    if signature.exists():
        signature.unlink()
    run_checked(
        [npm, "run", "tauri", "--", "signer", "sign", appimage],
        cwd=root / "desktop",
    )
    if not signature.is_file() or signature.stat().st_size == 0:
        raise RuntimeError("finalized AppImage signature was not created")


def build(
    command: Sequence[str],
    *,
    root: Path = ROOT,
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    run_checked: RunChecked = _run_checked,
) -> None:
    if not command or command[0] != "build":
        raise ValueError("release wrapper only accepts the Tauri build command")
    environment = os.environ if environ is None else environ
    npm = "npm.cmd" if platform == "win32" else "npm"
    is_linux = platform.startswith("linux")

    if is_linux:
        try:
            runner_temp = Path(environment["RUNNER_TEMP"])
            plugin = Path(environment["AIGUARD_APPIMAGE_PLUGIN"])
        except KeyError as error:
            raise RuntimeError(f"missing Linux release environment: {error.args[0]}") from None
        preserve_appimage_backend(root, runner_temp, host_triple())

    run_checked([npm, "run", "tauri", "--", *command], cwd=root / "desktop")

    if is_linux:
        _finalize_linux_appimage(
            root,
            runner_temp,
            plugin,
            npm=npm,
            run_checked=run_checked,
        )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        build(list(sys.argv[1:] if argv is None else argv))
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"release build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
