#!/usr/bin/env python3
"""Observe the exact production Desktop, broker, and backend process chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

try:
    import psutil
except ModuleNotFoundError:  # Importable in the repository's core-only test tier.
    psutil = None

_VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class Component(NamedTuple):
    path: Path
    name: str
    sha256: str


class PackageAttestation(NamedTuple):
    root: Path
    product_version: str
    manifest_sha256: str
    components: dict[str, Component]


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _component(
    root: Path,
    item: object,
    *,
    component_id: str,
    product_version: str,
) -> Component:
    try:
        if not isinstance(item, dict):
            raise ValueError
        relative = item["path"]
        expected = item["sha256"]
        if (
            not isinstance(relative, str)
            or not isinstance(expected, str)
            or _SHA256_RE.fullmatch(expected) is None
            or item.get("component_id") != component_id
            or item.get("build_id") != product_version
        ):
            raise ValueError
        relative_path = Path(relative)
        if relative_path.is_absolute() or len(relative_path.parts) != 1:
            raise ValueError
        original = root / relative_path
        if _is_link_or_reparse(original):
            raise ValueError
        resolved = original.resolve(strict=True)
        metadata = resolved.stat()
        if (
            resolved.parent != root
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (os.name != "nt" and metadata.st_mode & 0o111 == 0)
            or _digest(resolved) != expected
        ):
            raise ValueError
        return Component(resolved, relative_path.name, expected)
    except (KeyError, OSError, TypeError, ValueError):
        raise RuntimeError("package component verification failed") from None


def load_package(package: Path) -> PackageAttestation:
    try:
        if _is_link_or_reparse(package):
            raise ValueError
        root = package.resolve(strict=True)
        if not root.is_dir():
            raise ValueError
        manifest_path = root / "native-components-v1.json"
        if _is_link_or_reparse(manifest_path) or not manifest_path.is_file():
            raise ValueError
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if document.get("schema_version") != 1:
            raise ValueError
        version = document["product_version"]
        if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
            raise ValueError
        clients = document["clients"]
        if not isinstance(clients, list) or not all(isinstance(item, dict) for item in clients):
            raise ValueError
        roles = [item.get("role") for item in clients]
        if len(set(roles)) != len(roles) or any(
            role not in {"desktop", "extension", "maintenance"} for role in roles
        ):
            raise ValueError
        desktops = [item for item in clients if item.get("role") == "desktop"]
        if len(desktops) != 1:
            raise ValueError
        components = {
            "desktop": _component(
                root,
                desktops[0],
                component_id="desktop",
                product_version=version,
            ),
            "broker": _component(
                root,
                document["broker"],
                component_id="native-broker",
                product_version=version,
            ),
            "backend": _component(
                root,
                document["backend"],
                component_id="python-backend",
                product_version=version,
            ),
        }
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("package component verification failed") from None
    return PackageAttestation(root, version, _digest(manifest_path), components)


def build_evidence(
    package: PackageAttestation, *, mode: str, durations_ms: list[int]
) -> dict[str, object]:
    return {
        "schema": "aiguard-production-package-smoke/v1",
        "status": "passed",
        "product_version": package.product_version,
        "execution_mode": mode,
        "repetitions": len(durations_ms),
        "startup_ms": durations_ms,
        "components": dict.fromkeys(sorted(package.components), "observed-exact-digest"),
        "cleanup": "passed",
    }


def verify_package_unchanged(expected: PackageAttestation) -> None:
    observed = load_package(expected.root)
    if (
        observed.product_version != expected.product_version
        or observed.manifest_sha256 != expected.manifest_sha256
        or {
            role: (component.name, component.sha256)
            for role, component in observed.components.items()
        }
        != {
            role: (component.name, component.sha256)
            for role, component in expected.components.items()
        }
    ):
        raise RuntimeError("production package changed during smoke")


def _matching_processes(
    package: PackageAttestation,
    digest_cache: dict[tuple[str, int, int], str | None],
) -> dict[str, list[psutil.Process]]:
    matches: dict[str, list[psutil.Process]] = {role: [] for role in package.components}
    for process in psutil.process_iter(("pid", "name", "exe")):
        try:
            executable = process.info.get("exe")
            if not executable:
                continue
            path = Path(executable)
            candidates = [
                (role, component)
                for role, component in package.components.items()
                if path.name.casefold() == component.name.casefold()
            ]
            if not candidates or _is_link_or_reparse(path):
                continue
            metadata = path.stat()
            key = (str(path), metadata.st_size, metadata.st_mtime_ns)
            if key not in digest_cache:
                digest_cache[key] = _digest(path) if path.is_file() else None
            for role, component in candidates:
                if digest_cache[key] == component.sha256:
                    matches[role].append(process)
        except (OSError, psutil.Error):
            continue
    return matches


def _all_absent(
    package: PackageAttestation,
    digest_cache: dict[tuple[str, int, int], str | None],
) -> bool:
    return all(not processes for processes in _matching_processes(package, digest_cache).values())


def _terminate(processes: list[psutil.Process], launcher: subprocess.Popen) -> None:
    unique = {process.pid: process for process in processes}
    try:
        unique.setdefault(launcher.pid, psutil.Process(launcher.pid))
    except psutil.Error:
        pass
    for process in unique.values():
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(list(unique.values()), timeout=20)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    if alive:
        psutil.wait_procs(alive, timeout=10)


def _launcher_command(
    package: PackageAttestation, launcher: Path | None, mode: str
) -> tuple[list[str], str | None]:
    if mode == "direct":
        if launcher is not None:
            raise ValueError("direct smoke does not accept --launcher")
        return [str(package.components["desktop"].path)], None
    if launcher is None or _is_link_or_reparse(launcher):
        raise ValueError("AppImage smoke requires one regular launcher")
    resolved = launcher.resolve(strict=True)
    if not resolved.is_file() or resolved.suffix != ".AppImage":
        raise ValueError("AppImage smoke requires one regular launcher")
    if mode == "appimage-extract-and-run":
        return [str(resolved), "--appimage-extract-and-run"], _digest(resolved)
    if mode == "appimage-fuse":
        return [str(resolved)], _digest(resolved)
    raise ValueError("unsupported production smoke mode")


def smoke(
    package: Path,
    *,
    launcher: Path | None,
    mode: str,
    repetitions: int,
    timeout: float,
) -> dict[str, object]:
    if psutil is None:
        raise RuntimeError("production package smoke requires psutil")
    if repetitions < 1 or repetitions > 5 or timeout <= 0:
        raise ValueError("invalid production smoke limits")
    attestation = load_package(package)
    command, launcher_digest = _launcher_command(attestation, launcher, mode)
    digest_cache: dict[tuple[str, int, int], str | None] = {}
    if not _all_absent(attestation, digest_cache):
        raise RuntimeError("production component process baseline is not clean")

    durations = []
    for _ in range(repetitions):
        verify_package_unchanged(attestation)
        started = time.monotonic()
        child = subprocess.Popen(
            command,
            cwd=attestation.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        observed: dict[str, list[psutil.Process]] = {}
        deadline = started + timeout
        stable_since = None
        try:
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError("production Desktop exited before native readiness")
                observed = _matching_processes(attestation, digest_cache)
                if all(observed.values()):
                    stable_since = stable_since or time.monotonic()
                    if time.monotonic() - stable_since >= 1.0:
                        break
                else:
                    stable_since = None
                time.sleep(0.2)
            else:
                raise RuntimeError("production native process chain did not become ready")
            durations.append(round((time.monotonic() - started) * 1000))
        finally:
            observed = _matching_processes(attestation, digest_cache)
            _terminate([item for group in observed.values() for item in group], child)
            cleanup_deadline = time.monotonic() + 30
            while time.monotonic() < cleanup_deadline and not _all_absent(
                attestation, digest_cache
            ):
                time.sleep(0.2)
            if not _all_absent(attestation, digest_cache):
                raise RuntimeError("production native process cleanup failed")
        verify_package_unchanged(attestation)
        if launcher is not None and _digest(launcher.resolve(strict=True)) != launcher_digest:
            raise RuntimeError("production AppImage changed during smoke")
    return build_evidence(attestation, mode=mode, durations_ms=durations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument(
        "--mode",
        choices=("direct", "appimage-extract-and-run", "appimage-fuse"),
        default="direct",
    )
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        evidence = smoke(
            args.package,
            launcher=args.launcher,
            mode=args.mode,
            repetitions=args.repetitions,
            timeout=args.timeout,
        )
        encoded = json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
