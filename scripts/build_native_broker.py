#!/usr/bin/env python3
"""Build and stage the native broker components for Tauri externalBin."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "native-broker" / "Cargo.toml"
BINARIES = (
    "aiguard-native-broker",
    "aiguard-chrome-native-host",
    "aiguard-native-host-manager",
)


def host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine the Rust host triple")


def stage_native_components(*, build: bool = True) -> dict[str, Path]:
    if build:
        command = [
            "cargo",
            "build",
            "--locked",
            "--release",
            "--manifest-path",
            str(MANIFEST),
        ]
        for binary in BINARIES:
            command.extend(("--bin", binary))
        subprocess.check_call(command, cwd=ROOT)
    suffix = ".exe" if os.name == "nt" else ""
    triple = host_triple()
    staged = {}
    for binary in BINARIES:
        source = ROOT / "native-broker" / "target" / "release" / f"{binary}{suffix}"
        if not source.is_file():
            raise FileNotFoundError(f"native component build output not found: {source}")
        destination = ROOT / "desktop" / "src-tauri" / "binaries" / f"{binary}-{triple}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        staged[binary] = destination
    return staged


def stage_broker(*, build: bool = True) -> Path:
    """Compatibility wrapper returning the broker while staging the full set."""
    return stage_native_components(build=build)["aiguard-native-broker"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="stage an already-built release binary",
    )
    args = parser.parse_args()
    staged = stage_native_components(build=not args.skip_build)
    rendered = ", ".join(str(path.relative_to(ROOT)) for path in staged.values())
    print(f"Native components staged: {rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
