#!/usr/bin/env python3
"""Build and stage the native broker for Tauri's externalBin convention."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "native-broker" / "Cargo.toml"


def host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine the Rust host triple")


def stage_broker(*, build: bool = True) -> Path:
    if build:
        subprocess.check_call(
            [
                "cargo",
                "build",
                "--locked",
                "--release",
                "--manifest-path",
                str(MANIFEST),
                "--bin",
                "aiguard-native-broker",
            ],
            cwd=ROOT,
        )
    suffix = ".exe" if os.name == "nt" else ""
    source = ROOT / "native-broker" / "target" / "release" / (f"aiguard-native-broker{suffix}")
    if not source.is_file():
        raise FileNotFoundError(f"native broker build output not found: {source}")
    destination = (
        ROOT
        / "desktop"
        / "src-tauri"
        / "binaries"
        / f"aiguard-native-broker-{host_triple()}{suffix}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="stage an already-built release binary",
    )
    args = parser.parse_args()
    destination = stage_broker(build=not args.skip_build)
    print(f"Native broker staged: {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
