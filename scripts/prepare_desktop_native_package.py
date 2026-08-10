#!/usr/bin/env python3
"""Prepare the Slice 4 Desktop native-component manifest.

Portable mode puts the existing Tauri executable and its two native components
in one directory. Bundle-manifest mode hashes direct bundle inputs and leaves
AppImage deliberately invalid until its post-linuxdeploy AppDir is finalized.
Build placeholder mode safely stages invalid manifests for Tauri discovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "native-components-v1.json"
BUNDLE_MANIFEST_DIRECTORY = ROOT / "desktop" / "src-tauri" / "binaries"
BUNDLE_MANIFEST_NAMES = {
    "nsis": "native-components-v1.nsis.json",
    "deb": "native-components-v1.deb.json",
    "appimage": "native-components-v1.appimage.json",
    "macos": "native-components-v1.macos.json",
}
BUNDLE_TYPE_TOKEN = b"__TAURI_BUNDLE_TYPE_VAR_UNK"
BUNDLE_TYPE_PATCHES = {
    "nsis": b"__TAURI_BUNDLE_TYPE_VAR_NSS",
    "deb": b"__TAURI_BUNDLE_TYPE_VAR_DEB",
}
APPIMAGE_PLUGIN_SHA256 = {
    "x86_64": "a45d3e227bc7f397e9cf6bfa4c9507494efa2293357b6e86690a3de2ca992e79",
}
# Exact type2-runtime commit 75849dce7cc37e4319b633df1f116ca895c71a12.
# appimagetool rewrites only .digest_md5, so the pinned digest normalizes that
# field to zero before comparison.
APPIMAGE_RUNTIME_PIN = {
    "x86_64": (
        944_632,
        "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
    ),
}
APPIMAGE_DIGEST_SECTION = b".digest_md5"
APPIMAGE_DIGEST_SIZE = 16
BUILD_MARKER_PREFIX = b"AIGUARD_NATIVE_COMPONENT_BUILD_ID="
# AIGUARD_API_KEY appears in credential-scrub code, so it is not an authority
# marker by itself.
LEGACY_DESKTOP_AUTHORITY_MARKERS = (
    b"http://127.0.0.1:8000",
    b"http://localhost:8000",
    b"localhost:8000",
    b"x-aiguard-key",
    b"openai_api_key",
    b"anthropic_api_key",
    b"gemini_api_key",
)


def _host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not determine the Rust host triple")


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _contains_marker(path: Path, version: str) -> bool:
    marker = BUILD_MARKER_PREFIX + version.encode("ascii") + b"\0"
    carry = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            combined = carry + chunk
            if marker in combined:
                return True
            carry = combined[-len(marker) :]
    return False


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _checked_source(path: Path, *, marker_version: str | None = None) -> Path:
    if _is_link_or_reparse(path):
        raise ValueError(f"invalid package component: {path}")
    path = path.resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"invalid package component: {path}")
    if marker_version is not None and not _contains_marker(path, marker_version):
        raise ValueError(f"component build marker mismatch: {path.name}")
    return path


def _reject_legacy_desktop_authority(path: Path) -> None:
    longest = max(map(len, LEGACY_DESKTOP_AUTHORITY_MARKERS))
    carry = b""
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            combined = (carry + chunk).lower()
            if any(marker in combined for marker in LEGACY_DESKTOP_AUTHORITY_MARKERS):
                raise ValueError("Desktop package contains legacy runtime authority")
            carry = combined[-longest:]


def _checked_version(version: str) -> str:
    if not version or any(character.isspace() for character in version):
        raise ValueError("invalid product version")
    return version


def _manifest_document(
    *,
    desktop: Path,
    broker: Path,
    backend: Path,
    names: dict[str, str],
    version: str,
    desktop_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "product_version": version,
        "broker": {
            "component_id": "native-broker",
            "path": names["broker"],
            "sha256": _digest(broker),
            "build_id": version,
        },
        "clients": [
            {
                "component_id": "desktop",
                "role": "desktop",
                "path": names["desktop"],
                "sha256": desktop_sha256 or _digest(desktop),
                "build_id": version,
            }
        ],
        "backend": {
            "component_id": "python-backend",
            "path": names["backend"],
            "sha256": _digest(backend),
            "build_id": version,
            "arguments": ["--native-broker-backend"],
        },
    }


def _write_manifest(path: Path, manifest: dict[str, object]) -> Path:
    allowed_names = {MANIFEST_NAME, *BUNDLE_MANIFEST_NAMES.values()}
    if path.name not in allowed_names:
        raise ValueError("invalid bundle manifest filename")
    parent = path.parent.resolve(strict=True)
    destination = parent / path.name
    if _is_link_or_reparse(destination) or (destination.exists() and not destination.is_file()):
        raise ValueError("invalid bundle manifest destination")
    encoded = json.dumps(manifest, ensure_ascii=True, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o644)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _checked_bundle_manifest_directory(output: Path) -> Path:
    if _is_link_or_reparse(output):
        raise ValueError("invalid Tauri bundle manifest directory")
    output = output.resolve(strict=True)
    if not output.is_dir():
        raise ValueError("invalid Tauri bundle manifest directory")
    return output


def write_tauri_build_placeholders() -> list[Path]:
    """Atomically stage invalid manifests in the fixed Tauri resource directory."""
    output = _checked_bundle_manifest_directory(BUNDLE_MANIFEST_DIRECTORY)
    return [
        _write_manifest(output / manifest_name, {})
        for manifest_name in BUNDLE_MANIFEST_NAMES.values()
    ]


def _bundle_suffix(path: Path) -> str:
    if path.suffix.casefold() == ".exe":
        return ".exe"
    if path.suffix:
        raise ValueError("unsupported bundle component extension")
    return ""


def write_bundle_manifest(
    manifest_path: Path,
    *,
    desktop: Path,
    broker: Path,
    backend: Path,
    version: str,
    _desktop_sha256: str | None = None,
) -> Path:
    """Hash final build outputs without copying or renaming them."""
    version = _checked_version(version)
    desktop = _checked_source(desktop, marker_version=version)
    broker = _checked_source(broker, marker_version=version)
    backend = _checked_source(backend)
    _reject_legacy_desktop_authority(desktop)
    suffixes = {_bundle_suffix(path) for path in (desktop, broker, backend)}
    if len(suffixes) != 1:
        raise ValueError("bundle component extension mismatch")
    suffix = suffixes.pop()
    if desktop.name != f"desktop{suffix}":
        raise ValueError("Desktop bundle binary name mismatch")
    names = {
        "desktop": f"desktop{suffix}",
        "broker": f"aiguard-native-broker{suffix}",
        "backend": f"aiguard{suffix}",
    }
    manifest = _manifest_document(
        desktop=desktop,
        broker=broker,
        backend=backend,
        names=names,
        version=version,
        desktop_sha256=_desktop_sha256,
    )
    return _write_manifest(manifest_path, manifest)


def _patched_desktop_digest(desktop: Path, bundle_type: str) -> str:
    contents = desktop.read_bytes()
    if contents.count(BUNDLE_TYPE_TOKEN) != 1:
        raise ValueError("Desktop bundle type token is unavailable or ambiguous")
    replacement = BUNDLE_TYPE_PATCHES[bundle_type]
    if len(replacement) != len(BUNDLE_TYPE_TOKEN):
        raise RuntimeError("invalid Tauri bundle type patch")
    patched = contents.replace(BUNDLE_TYPE_TOKEN, replacement, 1)
    return hashlib.sha256(patched).hexdigest()


def write_tauri_bundle_manifests(
    output: Path,
    *,
    platform: str,
    desktop: Path,
    broker: Path,
    backend: Path,
    version: str,
) -> list[Path]:
    """Write final direct-bundle manifests and an invalid AppImage placeholder."""
    version = _checked_version(version)
    output = _checked_bundle_manifest_directory(output)
    if platform == "windows":
        bundle_types = ("nsis",)
    elif platform == "linux":
        bundle_types = ("deb", "appimage")
    elif platform == "macos":
        bundle_types = ("macos",)
    else:
        raise ValueError("unsupported Tauri bundle platform")

    written = []
    for bundle_type in bundle_types:
        if bundle_type == "appimage":
            written.append(_write_manifest(output / BUNDLE_MANIFEST_NAMES[bundle_type], {}))
            continue
        desktop_sha256 = (
            _digest(_checked_source(desktop, marker_version=version))
            if bundle_type == "macos"
            else _patched_desktop_digest(
                _checked_source(desktop, marker_version=version), bundle_type
            )
        )
        written.append(
            write_bundle_manifest(
                output / BUNDLE_MANIFEST_NAMES[bundle_type],
                desktop=desktop,
                broker=broker,
                backend=backend,
                version=version,
                _desktop_sha256=desktop_sha256,
            )
        )
    return written


def _checked_appimage_directory(appdir: Path) -> tuple[Path, Path]:
    if _is_link_or_reparse(appdir):
        raise ValueError("invalid finalized AppImage directory")
    appdir = appdir.resolve(strict=True)
    if not appdir.is_dir() or not appdir.name.endswith(".AppDir"):
        raise ValueError("invalid finalized AppImage directory")
    usr = appdir / "usr"
    package = usr / "bin"
    if _is_link_or_reparse(usr) or _is_link_or_reparse(package):
        raise ValueError("invalid finalized AppImage directory")
    if package.resolve(strict=True) != package or not package.is_dir():
        raise ValueError("invalid finalized AppImage directory")
    return appdir, package


def _appimage_tool_environment(**values: str) -> dict[str, str]:
    environment = {
        name: value
        for name in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
        if (value := os.environ.get(name))
    }
    environment.update(values)
    return environment


def _appimage_runtime_offset(appimage: Path) -> int:
    result = subprocess.run(
        [str(appimage), "--appimage-offset"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=_appimage_tool_environment(),
    )
    rendered = result.stdout.strip()
    if not rendered.isascii() or not rendered.isdecimal():
        raise RuntimeError("AppImage runtime offset unavailable")
    offset = int(rendered)
    if offset <= 0 or offset >= appimage.stat().st_size:
        raise RuntimeError("AppImage runtime offset unavailable")
    return offset


def _copy_prefix(source: Path, destination: Path, length: int) -> None:
    remaining = length
    with source.open("rb") as reader, destination.open("xb") as writer:
        while remaining:
            chunk = reader.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError("AppImage runtime unavailable")
            writer.write(chunk)
            remaining -= len(chunk)
        writer.flush()
        os.fsync(writer.fileno())


def _appimage_runtime_section(data: bytes, name: bytes) -> tuple[int, int]:
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1 or data[6] != 1:
        raise ValueError("unsupported AppImage runtime")

    (
        _elf_type,
        machine,
        version,
        _entry,
        _program_offset,
        section_offset,
        _flags,
        header_size,
        program_entry_size,
        program_count,
        section_entry_size,
        section_count,
        names_index,
    ) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    if (
        machine != 62
        or version != 1
        or header_size != 64
        or section_entry_size != 64
        or section_count < 2
        or section_count > 4096
        or names_index <= 0
        or names_index >= 0xFF00
        or names_index >= section_count
    ):
        raise ValueError("unsupported AppImage runtime")
    program_table_end = _program_offset + (program_entry_size * program_count)
    if program_count and (
        program_entry_size != 56 or _program_offset < header_size or program_table_end > len(data)
    ):
        raise ValueError("invalid AppImage runtime programs")
    executable_ranges: list[tuple[int, int]] = []
    for index in range(program_count):
        offset = _program_offset + (index * program_entry_size)
        (
            program_type,
            program_flags,
            value_offset,
            _vaddr,
            _paddr,
            file_size,
            memory_size,
            _align,
        ) = struct.unpack_from("<IIQQQQQQ", data, offset)
        value_end = value_offset + file_size
        if file_size and value_end > len(data):
            raise ValueError("invalid AppImage runtime program")
        if program_type == 1:
            if memory_size < file_size:
                raise ValueError("invalid AppImage runtime load program")
            if program_flags & 0x1 and file_size:
                executable_ranges.append((value_offset, value_end))
    section_table_end = section_offset + (section_entry_size * section_count)
    if section_offset < header_size or section_table_end > len(data):
        raise ValueError("invalid AppImage runtime sections")
    if any(data[section_offset : section_offset + section_entry_size]):
        raise ValueError("invalid AppImage runtime null section")

    def section(index: int) -> tuple[int, int, int, int, int]:
        offset = section_offset + (index * section_entry_size)
        values = struct.unpack_from("<IIQQQQIIQQ", data, offset)
        return values[0], values[1], values[2], values[4], values[5]

    sections = [section(index) for index in range(section_count)]
    _names_name, names_type, _names_flags, names_offset, names_size = sections[names_index]
    names_end = names_offset + names_size
    if names_type != 3 or names_offset <= 0 or names_size <= 0 or names_end > len(data):
        raise ValueError("invalid AppImage runtime section names")
    names = data[names_offset:names_end]
    if names[0] != 0 or names[-1] != 0:
        raise ValueError("invalid AppImage runtime section names")

    matches: list[tuple[int, int, int]] = []
    file_ranges: list[tuple[int, int, int]] = []
    for index, (name_offset, section_type, section_flags, value_offset, value_size) in enumerate(
        sections
    ):
        if name_offset >= len(names):
            raise ValueError("invalid AppImage runtime section name")
        name_end = names.find(b"\0", name_offset)
        if name_end < 0:
            raise ValueError("invalid AppImage runtime section name")
        if value_size and section_type != 8:
            value_end = value_offset + value_size
            if value_offset <= 0 or value_end > len(data):
                raise ValueError("invalid AppImage runtime section")
            file_ranges.append((index, value_offset, value_end))
        if names[name_offset:name_end] == name:
            if section_type != 1 or value_offset <= 0 or value_size < 16 or value_end > len(data):
                raise ValueError("invalid AppImage runtime mutable section")
            matches.append((index, value_offset, value_size))
    if len(matches) != 1:
        raise ValueError("missing AppImage runtime mutable section")
    digest_index, digest_offset, digest_size = matches[0]
    digest_end = digest_offset + digest_size
    digest_flags = sections[digest_index][2]
    if digest_size != APPIMAGE_DIGEST_SIZE or digest_flags & 0x4:
        raise ValueError("invalid AppImage runtime mutable section")

    protected_ranges = [
        (0, header_size),
        (section_offset, section_table_end),
        (names_offset, names_end),
    ]
    if program_count:
        protected_ranges.append((_program_offset, program_table_end))
    if any(digest_offset < end and start < digest_end for start, end in protected_ranges):
        raise ValueError("invalid AppImage runtime mutable section")
    if any(digest_offset < end and start < digest_end for start, end in executable_ranges):
        raise ValueError("executable AppImage runtime mutable section")
    if any(
        digest_offset < end and start < digest_end
        for index, start, end in file_ranges
        if index != digest_index
    ):
        raise ValueError("overlapping AppImage runtime mutable section")
    return digest_offset, digest_size


def _verify_appimage_runtime_prefix(expected: Path, repacked: Path) -> None:
    try:
        expected_data = expected.read_bytes()
        repacked_data = repacked.read_bytes()
        if len(expected_data) != len(repacked_data):
            raise ValueError("AppImage runtime size changed")
        expected_section = _appimage_runtime_section(expected_data, APPIMAGE_DIGEST_SECTION)
        repacked_section = _appimage_runtime_section(repacked_data, APPIMAGE_DIGEST_SECTION)
        if expected_section != repacked_section:
            raise ValueError("AppImage runtime section changed")
        mutable_start = expected_section[0]
        # appimagetool rewrites only this fixed field after it appends SquashFS.
        mutable_end = mutable_start + APPIMAGE_DIGEST_SIZE
        if (
            expected_data[:mutable_start] != repacked_data[:mutable_start]
            or expected_data[mutable_end:] != repacked_data[mutable_end:]
        ):
            raise ValueError("AppImage runtime changed")
    except (OSError, struct.error, ValueError):
        raise RuntimeError("finalized AppImage runtime verification failed") from None


def _verify_appimage_runtime_provenance(runtime: Path, arch: str) -> None:
    try:
        expected_size, expected_digest = APPIMAGE_RUNTIME_PIN[arch]
        data = runtime.read_bytes()
        if len(data) != expected_size:
            raise ValueError("AppImage runtime size changed")
        mutable_start, mutable_size = _appimage_runtime_section(data, APPIMAGE_DIGEST_SECTION)
        mutable_end = mutable_start + mutable_size
        hasher = hashlib.sha256()
        hasher.update(data[:mutable_start])
        hasher.update(bytes(mutable_size))
        hasher.update(data[mutable_end:])
        if hasher.hexdigest() != expected_digest:
            raise ValueError("AppImage runtime digest changed")
    except (KeyError, OSError, struct.error, ValueError):
        raise RuntimeError("AppImage runtime provenance verification failed") from None


def _repack_appimage(
    *,
    plugin: Path,
    appdir: Path,
    output: Path,
    runtime: Path,
    arch: str,
) -> None:
    if output.exists():
        raise FileExistsError("finalized AppImage output already exists")
    environment = _appimage_tool_environment(
        APPIMAGE_EXTRACT_AND_RUN="1",
        ARCH=arch,
        LDAI_OUTPUT=str(output),
        LDAI_RUNTIME_FILE=str(runtime),
    )
    subprocess.run(
        [str(plugin), "--appimage-extract-and-run", "--appdir", str(appdir)],
        check=True,
        cwd=output.parent,
        env=environment,
        timeout=300,
    )
    if _is_link_or_reparse(output) or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("finalized AppImage output unavailable")


def _extract_appimage(appimage: Path, output: Path) -> Path:
    if output.exists():
        raise FileExistsError("AppImage verification directory already exists")
    output.mkdir()
    subprocess.run(
        [str(appimage), "--appimage-extract"],
        check=True,
        cwd=output,
        env=_appimage_tool_environment(),
        timeout=300,
    )
    extracted = output / "squashfs-root"
    if _is_link_or_reparse(extracted) or not extracted.is_dir():
        raise RuntimeError("finalized AppImage extraction unavailable")
    return extracted


def _verify_finalized_appimage(source_package: Path, extracted: Path, version: str) -> None:
    usr = extracted / "usr"
    extracted_package = usr / "bin"
    if (
        extracted.name != "squashfs-root"
        or _is_link_or_reparse(extracted)
        or _is_link_or_reparse(usr)
        or _is_link_or_reparse(extracted_package)
        or extracted_package.resolve(strict=True) != extracted_package
        or not extracted_package.is_dir()
    ):
        raise RuntimeError("finalized AppImage verification failed")

    names = ("desktop", "aiguard-native-broker", "aiguard", MANIFEST_NAME)
    for name in names:
        source = _checked_source(source_package / name)
        packaged = _checked_source(extracted_package / name)
        if _digest(source) != _digest(packaged):
            raise RuntimeError("finalized AppImage verification failed")

    manifest = json.loads((extracted_package / MANIFEST_NAME).read_text(encoding="utf-8"))
    desktop = _checked_source(extracted_package / "desktop", marker_version=version)
    broker = _checked_source(extracted_package / "aiguard-native-broker", marker_version=version)
    backend = _checked_source(extracted_package / "aiguard")
    _reject_legacy_desktop_authority(desktop)
    expected = _manifest_document(
        desktop=desktop,
        broker=broker,
        backend=backend,
        names={
            "desktop": "desktop",
            "broker": "aiguard-native-broker",
            "backend": "aiguard",
        },
        version=version,
    )
    if manifest != expected:
        raise RuntimeError("finalized AppImage verification failed")


def finalize_appimage(
    appimage: Path,
    *,
    appdir: Path,
    plugin: Path,
    arch: str,
    version: str,
) -> Path:
    """Seal final AppDir bytes, repack, and verify before replacing AppImage."""
    if arch not in APPIMAGE_PLUGIN_SHA256 or arch not in APPIMAGE_RUNTIME_PIN:
        raise ValueError("unsupported AppImage output plugin architecture")
    version = _checked_version(version)
    appimage = _checked_source(appimage)
    if appimage.suffix != ".AppImage":
        raise ValueError("invalid AppImage candidate")
    appdir, package = _checked_appimage_directory(appdir)
    if appdir.parent != appimage.parent:
        raise ValueError("AppImage candidate and AppDir must share a directory")
    plugin = _checked_source(plugin)
    if (
        plugin.name != f"linuxdeploy-plugin-appimage-{arch}.AppImage"
        or _digest(plugin) != APPIMAGE_PLUGIN_SHA256[arch]
    ):
        raise ValueError("AppImage output plugin digest mismatch")

    manifest = write_bundle_manifest(
        package / MANIFEST_NAME,
        desktop=package / "desktop",
        broker=package / "aiguard-native-broker",
        backend=package / "aiguard",
        version=version,
    )
    original_mode = stat.S_IMODE(appimage.stat().st_mode)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{appimage.name}.", dir=appimage.parent))
    try:
        runtime = temporary_root / "runtime"
        runtime_size = APPIMAGE_RUNTIME_PIN[arch][0]
        _copy_prefix(appimage, runtime, runtime_size)
        _verify_appimage_runtime_provenance(runtime, arch)
        repacked = temporary_root / appimage.name
        _repack_appimage(
            plugin=plugin,
            appdir=appdir,
            output=repacked,
            runtime=runtime,
            arch=arch,
        )
        try:
            repacked_runtime = temporary_root / "repacked-runtime"
            _copy_prefix(repacked, repacked_runtime, runtime_size)
            _verify_appimage_runtime_provenance(repacked_runtime, arch)
            _verify_appimage_runtime_prefix(runtime, repacked_runtime)
            if _appimage_runtime_offset(repacked) != runtime_size:
                raise RuntimeError("finalized AppImage runtime verification failed")
            extracted = _extract_appimage(repacked, temporary_root / "verification")
            _verify_finalized_appimage(manifest.parent, extracted, version)
        except (json.JSONDecodeError, OSError, RuntimeError, ValueError):
            raise RuntimeError("finalized AppImage verification failed") from None
        os.chmod(repacked, original_mode)
        os.replace(repacked, appimage)
    finally:
        try:
            shutil.rmtree(temporary_root)
        except OSError:
            raise RuntimeError("AppImage finalization cleanup failed") from None
    return appimage


def _host_bundle_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError("unsupported Tauri bundle platform")


def assemble_package(
    output: Path,
    *,
    desktop: Path,
    broker: Path,
    backend: Path,
    version: str,
) -> Path:
    version = _checked_version(version)
    desktop = _checked_source(desktop, marker_version=version)
    broker = _checked_source(broker, marker_version=version)
    backend = _checked_source(backend)
    _reject_legacy_desktop_authority(desktop)
    output = output.resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise FileExistsError(f"package output must be an empty directory: {output}")
    else:
        output.mkdir(parents=True)

    suffix = ".exe" if os.name == "nt" else ""
    names = {
        "desktop": f"AI Guard{suffix}",
        "broker": f"aiguard-native-broker{suffix}",
        "backend": f"aiguard{suffix}",
    }
    destinations = {
        "desktop": output / names["desktop"],
        "broker": output / names["broker"],
        "backend": output / names["backend"],
    }
    for key, source in {
        "desktop": desktop,
        "broker": broker,
        "backend": backend,
    }.items():
        shutil.copy2(source, destinations[key])

    manifest = _manifest_document(
        desktop=destinations["desktop"],
        broker=destinations["broker"],
        backend=destinations["backend"],
        names=names,
        version=version,
    )
    return _write_manifest(output / MANIFEST_NAME, manifest)


def _default_paths() -> tuple[Path, Path, Path]:
    triple = _host_triple()
    suffix = ".exe" if os.name == "nt" else ""
    desktop = ROOT / "desktop" / "src-tauri" / "target" / "release" / (f"desktop{suffix}")
    binaries = ROOT / "desktop" / "src-tauri" / "binaries"
    broker = binaries / f"aiguard-native-broker-{triple}{suffix}"
    backend = binaries / f"aiguard-{triple}{suffix}"
    return desktop, broker, backend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--bundle-manifest", action="store_true")
    mode.add_argument("--build-placeholders", action="store_true")
    mode.add_argument("--finalize-appimage", type=Path)
    parser.add_argument("--desktop", type=Path)
    parser.add_argument("--broker", type=Path)
    parser.add_argument("--backend", type=Path)
    parser.add_argument("--appdir", type=Path)
    parser.add_argument("--appimage-plugin", type=Path)
    parser.add_argument("--appimage-arch", choices=tuple(APPIMAGE_PLUGIN_SHA256))
    args = parser.parse_args()
    if args.build_placeholders:
        manifests = write_tauri_build_placeholders()
        prepared = ", ".join(str(manifest) for manifest in manifests)
        print(f"Desktop native build placeholders prepared: {prepared}")
        return 0

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if args.finalize_appimage:
        if not args.appdir or not args.appimage_plugin or not args.appimage_arch:
            parser.error(
                "--finalize-appimage requires --appdir, --appimage-plugin, and --appimage-arch"
            )
        finalized = finalize_appimage(
            args.finalize_appimage,
            appdir=args.appdir,
            plugin=args.appimage_plugin,
            arch=args.appimage_arch,
            version=version,
        )
        print(f"Desktop AppImage finalized: {finalized}")
        return 0

    desktop_default, broker_default, backend_default = _default_paths()
    desktop = args.desktop or desktop_default
    broker = args.broker or broker_default
    backend = args.backend or backend_default
    if args.bundle_manifest:
        manifests = write_tauri_bundle_manifests(
            BUNDLE_MANIFEST_DIRECTORY,
            platform=_host_bundle_platform(),
            desktop=desktop,
            broker=broker,
            backend=backend,
            version=version,
        )
        prepared = ", ".join(str(manifest) for manifest in manifests)
        print(f"Desktop native bundle manifests prepared: {prepared}")
    else:
        manifest = assemble_package(
            args.output,
            desktop=desktop,
            broker=broker,
            backend=backend,
            version=version,
        )
        print(f"Desktop native package assembled: {manifest.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
