#!/usr/bin/env python3
"""Exercise one exact DEB upgrade while a non-root Desktop broker is live."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from smoke_desktop_native_package import smoke, smoke_upgrade_invalidation

DEB_UPGRADE_TIMEOUT_SECONDS = 60
OLD_DESKTOP_INVALIDATION_TIMEOUT_SECONDS = DEB_UPGRADE_TIMEOUT_SECONDS + 60
NEW_DESKTOP_SMOKE_TIMEOUT_SECONDS = 120


def _regular_deb(path: Path) -> Path:
    absolute = path.absolute()
    metadata = absolute.lstat()
    resolved = absolute.resolve(strict=True)
    if (
        absolute != resolved
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size == 0
        or metadata.st_size > 512 * 1024 * 1024
    ):
        raise ValueError("invalid DEB upgrade candidate")
    package = subprocess.check_output(
        ["dpkg-deb", "-f", str(resolved), "Package"],
        text=True,
        timeout=30,
    ).strip()
    if not package or not package.replace("-", "").isalnum():
        raise ValueError("invalid DEB upgrade candidate")
    return resolved


def smoke_live_upgrade(package: Path, deb: Path) -> dict[str, object]:
    def upgrade() -> None:
        result = subprocess.run(
            ["sudo", "dpkg", "-i", str(deb)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=DEB_UPGRADE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError("live DEB upgrade failed")

    invalidation = smoke_upgrade_invalidation(
        package,
        OLD_DESKTOP_INVALIDATION_TIMEOUT_SECONDS,
        ready_callback=upgrade,
    )
    installed = smoke(package, NEW_DESKTOP_SMOKE_TIMEOUT_SECONDS)
    return {
        "lifecycle": "live_nonroot_deb_upgrade",
        "old_desktop": invalidation,
        "new_desktop": installed,
    }


def main() -> int:
    if os.name == "nt":
        raise ValueError("live DEB upgrade requires Linux")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("deb", type=Path)
    args = parser.parse_args()
    evidence = smoke_live_upgrade(args.package, _regular_deb(args.deb))
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
