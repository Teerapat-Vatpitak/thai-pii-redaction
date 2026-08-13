#!/usr/bin/env python3
"""Preseed and verify every Linux helper consumed by Tauri CLI 2.11.4."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit


class Tool(NamedTuple):
    name: str
    url: str
    size: int
    sha256: str
    post_build_sha256: str | None = None


TOOLS = (
    Tool(
        "AppRun-x86_64",
        "https://api.github.com/repos/tauri-apps/binary-releases/releases/assets/274691722",
        31_552,
        "f30140a43a0a59e46db21bdefdf749b9e9f2c6946e92afabbacf98b8ae73fb4f",
    ),
    Tool(
        "linuxdeploy-x86_64.AppImage",
        "https://api.github.com/repos/tauri-apps/binary-releases/releases/assets/182515537",
        13_264_064,
        "e762bea85c8eb0d4b3508d46e5c1f037f717d0f9303ae3b4aafc8b04991fa1ef",
        "20eebde3c18ae2e44279bd624fc72482503aece216d5d77f10932235342f71c1",
    ),
    Tool(
        "linuxdeploy-plugin-gtk.sh",
        "https://raw.githubusercontent.com/tauri-apps/linuxdeploy-plugin-gtk/b5eb8d05b4c0ed40107fe2158c5d8527f94568ef/linuxdeploy-plugin-gtk.sh",
        11_648,
        "cb379f9b0733e9ad9f8bd78f8c2fa038aef2478523bb7d4c8e64ff6a1ea3501a",
    ),
    Tool(
        "linuxdeploy-plugin-gstreamer.sh",
        "https://raw.githubusercontent.com/tauri-apps/linuxdeploy-plugin-gstreamer/2a2e67491c32995a3f279ad0ecbe77abd512b42a/linuxdeploy-plugin-gstreamer.sh",
        4_857,
        "c107b49d84edbffc6ab226ed1007e0626a4f7aa2c3a36b7782bef62351d49e94",
    ),
    Tool(
        "linuxdeploy-plugin-appimage.AppImage",
        "https://api.github.com/repos/linuxdeploy/linuxdeploy-plugin-appimage/releases/assets/497460911",
        16_484_856,
        "a45d3e227bc7f397e9cf6bfa4c9507494efa2293357b6e86690a3de2ca992e79",
    ),
)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify(path: Path, tool: Tool, *, downloaded: bool = False) -> None:
    expected_digest = tool.sha256 if downloaded else (tool.post_build_sha256 or tool.sha256)
    metadata = path.stat() if path.exists() else None
    if (
        path.is_symlink()
        or metadata is None
        or not path.is_file()
        or metadata.st_size != tool.size
        or metadata.st_nlink != 1
    ):
        raise RuntimeError(f"Tauri tool changed unexpectedly: {tool.name}")
    if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o750:
        raise RuntimeError(f"Tauri tool changed unexpectedly: {tool.name}")
    if _digest(path) != expected_digest:
        label = "digest mismatch" if downloaded else "changed unexpectedly"
        raise RuntimeError(f"Tauri tool {label}: {tool.name}")


def _normalize_download(path: Path, tool: Tool) -> None:
    """Apply Tauri's unconditional linuxdeploy header patch before caching."""
    _verify(path, tool, downloaded=True)
    if tool.post_build_sha256 is None:
        return
    with path.open("r+b") as handle:
        handle.seek(8)
        handle.write(b"\0\0\0")
        handle.flush()
        os.fsync(handle.fileno())
    _verify(path, tool)


def verify_cache(
    cache: Path, *, tools: tuple[Tool, ...] = TOOLS, after_build: bool = False
) -> None:
    if cache.is_symlink() or not cache.is_dir():
        raise RuntimeError("invalid Tauri tool cache")
    expected = {tool.name for tool in tools}
    observed = {path.name for path in cache.iterdir()}
    if observed != expected:
        raise RuntimeError("Tauri tool cache changed unexpectedly")
    for tool in tools:
        _verify(cache / tool.name, tool)


def install_tools(
    cache: Path,
    *,
    token: str | None,
    tools: tuple[Tool, ...] = TOOLS,
    opener=urllib.request.urlopen,
) -> None:
    if cache.is_symlink():
        raise RuntimeError("invalid Tauri tool cache")
    cache.mkdir(parents=True, exist_ok=True)
    cache = cache.resolve(strict=True)
    if not cache.is_dir():
        raise RuntimeError("invalid Tauri tool cache")

    for tool in tools:
        destination = cache / tool.name
        try:
            _verify(destination, tool)
            continue
        except (OSError, RuntimeError):
            pass

        descriptor, temporary_name = tempfile.mkstemp(
            dir=cache, prefix=f".{tool.name}.", suffix=".download"
        )
        temporary = Path(temporary_name)
        try:
            headers = {"Accept": "application/octet-stream", "User-Agent": "aiguard-release"}
            if token and urlsplit(tool.url).hostname == "api.github.com":
                headers["Authorization"] = f"Bearer {token}"
            request = urllib.request.Request(tool.url, headers=headers)
            with os.fdopen(descriptor, "wb") as output, opener(request, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if hasattr(os, "chmod"):
                temporary.chmod(
                    stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP
                )
            _normalize_download(temporary, tool)
            os.replace(temporary, destination)
            _verify(destination, tool)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    verify_cache(cache, tools=tools)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--verify-after-build", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_after_build:
            verify_cache(args.cache.resolve(), after_build=True)
        else:
            install_tools(args.cache, token=os.environ.get("GH_TOKEN"))
    except (OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print("OK: pinned Tauri Linux helper set verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
