from __future__ import annotations

import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "prepare_desktop_native_package.py"
SPEC = importlib.util.spec_from_file_location("prepare_desktop_native_package", SCRIPT)
assert SPEC and SPEC.loader
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_desktop_native_package.py"
SMOKE_SPEC = importlib.util.spec_from_file_location("smoke_desktop_native_package", SMOKE_SCRIPT)
assert SMOKE_SPEC and SMOKE_SPEC.loader
smoke_package = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(smoke_package)


def _component(path: Path, *, marker: bool = False) -> None:
    body = b"synthetic component"
    if marker:
        body += b"AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0"
    path.write_bytes(body)


def _frozen_backend(path: Path) -> None:
    path.write_bytes(b"synthetic frozen backend" + b"MEI\x0c\x0b\x0a\x0b\x0e" + bytes(64))
    path.chmod(0o755)


def _synthetic_appimage_runtime(*, digest: bytes = b"0" * 16) -> bytes:
    assert len(digest) == 16
    section_names = b"\0.shstrtab\0.text\0.digest_md5\0"
    program_table_offset = 64
    section_table_offset = program_table_offset + (2 * 56)
    section_names_offset = section_table_offset + (4 * 64)
    text_offset = 480
    text = b"trusted-runtime-code"
    digest_offset = 512
    header = b"\x7fELF" + bytes((2, 1, 1, 0)) + (b"\0" * 8)
    header += struct.pack(
        "<HHIQQQIHHHHHH",
        2,
        62,
        1,
        0,
        program_table_offset,
        section_table_offset,
        0,
        64,
        56,
        2,
        64,
        4,
        1,
    )
    text_program = struct.pack(
        "<IIQQQQQQ",
        1,
        5,
        text_offset,
        0,
        0,
        len(text),
        len(text),
        16,
    )
    digest_program = struct.pack(
        "<IIQQQQQQ",
        1,
        6,
        digest_offset,
        0,
        0,
        len(digest),
        len(digest),
        16,
    )
    null_section = bytes(64)
    names_section = struct.pack(
        "<IIQQQQIIQQ",
        1,
        3,
        0,
        0,
        section_names_offset,
        len(section_names),
        0,
        0,
        1,
        0,
    )
    text_section = struct.pack(
        "<IIQQQQIIQQ",
        len(b"\0.shstrtab\0"),
        1,
        6,
        0,
        text_offset,
        len(text),
        0,
        0,
        16,
        0,
    )
    digest_section = struct.pack(
        "<IIQQQQIIQQ",
        len(b"\0.shstrtab\0.text\0"),
        1,
        3,
        0,
        digest_offset,
        len(digest),
        0,
        0,
        1,
        0,
    )
    runtime = (
        header
        + text_program
        + digest_program
        + null_section
        + names_section
        + text_section
        + digest_section
        + section_names
    )
    runtime += bytes(text_offset - len(runtime)) + text
    runtime += bytes(digest_offset - len(runtime))
    return runtime + digest + b"runtime-padding"


def _pin_synthetic_appimage_runtime(monkeypatch, runtime: bytes) -> None:
    mutable_start, mutable_size = package._appimage_runtime_section(
        runtime, package.APPIMAGE_DIGEST_SECTION
    )
    normalized = (
        runtime[:mutable_start] + bytes(mutable_size) + runtime[mutable_start + mutable_size :]
    )
    monkeypatch.setitem(
        package.APPIMAGE_RUNTIME_PIN,
        "x86_64",
        (len(runtime), hashlib.sha256(normalized).hexdigest()),
    )


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")


def test_portable_package_manifest_hashes_exact_attested_components(tmp_path):
    desktop = tmp_path / "desktop-source.exe"
    broker = tmp_path / "broker-source.exe"
    backend = tmp_path / "backend-source.exe"
    _component(desktop, marker=True)
    _component(broker, marker=True)
    _component(backend)
    output = tmp_path / "package"

    manifest_path = package.assemble_package(
        output,
        desktop=desktop,
        broker=broker,
        backend=backend,
        version="2.5.0",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    suffix = ".exe" if package.os.name == "nt" else ""
    desktop_name = f"AI Guard{suffix}"
    assert manifest["product_version"] == "2.5.0"
    assert manifest["clients"] == [
        {
            "component_id": "desktop",
            "role": "desktop",
            "path": desktop_name,
            "sha256": hashlib.sha256((output / desktop_name).read_bytes()).hexdigest(),
            "build_id": "2.5.0",
        }
    ]
    assert manifest["broker"]["path"] == f"aiguard-native-broker{suffix}"
    assert manifest["backend"]["path"] == f"aiguard{suffix}"
    assert manifest["backend"]["arguments"] == ["--native-broker-backend"]
    rendered = manifest_path.read_text(encoding="utf-8").lower()
    for forbidden in ("api_key", "boot_key", "127.0.0.1", "localhost"):
        assert forbidden not in rendered


@pytest.mark.parametrize("suffix", ["", ".exe"])
def test_bundle_manifest_hashes_final_bytes_with_tauri_destination_names(tmp_path, suffix):
    desktop = tmp_path / f"desktop{suffix}"
    broker = tmp_path / f"aiguard-native-broker-test-target{suffix}"
    backend = tmp_path / f"aiguard-test-target{suffix}"
    _component(desktop, marker=True)
    _component(broker, marker=True)
    _component(backend)
    manifest_path = tmp_path / "bundle-input" / "native-components-v1.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text("stale manifest", encoding="utf-8")

    written = package.write_bundle_manifest(
        manifest_path,
        desktop=desktop,
        broker=broker,
        backend=backend,
        version="2.5.0",
    )

    assert written == manifest_path.resolve()
    if os.name != "nt":
        assert stat.S_IMODE(written.stat().st_mode) == 0o644
    manifest = json.loads(written.read_text(encoding="utf-8"))
    assert manifest["clients"] == [
        {
            "component_id": "desktop",
            "role": "desktop",
            "path": f"desktop{suffix}",
            "sha256": hashlib.sha256(desktop.read_bytes()).hexdigest(),
            "build_id": "2.5.0",
        }
    ]
    assert manifest["broker"] == {
        "component_id": "native-broker",
        "path": f"aiguard-native-broker{suffix}",
        "sha256": hashlib.sha256(broker.read_bytes()).hexdigest(),
        "build_id": "2.5.0",
    }
    assert manifest["backend"] == {
        "component_id": "python-backend",
        "path": f"aiguard{suffix}",
        "sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
        "build_id": "2.5.0",
        "arguments": ["--native-broker-backend"],
    }
    assert not (manifest_path.parent / f"aiguard-test-target{suffix}").exists()


def test_bundle_manifest_rejects_nonfinal_or_inconsistent_components(tmp_path):
    desktop = tmp_path / "desktop.exe"
    broker = tmp_path / "aiguard-native-broker-test-target.exe"
    backend = tmp_path / "aiguard-test-target"
    _component(desktop, marker=True)
    _component(broker, marker=True)
    _component(backend)

    with pytest.raises(ValueError, match="extension"):
        package.write_bundle_manifest(
            tmp_path / "native-components-v1.json",
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )

    backend = tmp_path / "aiguard-test-target.exe"
    _component(backend)
    with desktop.open("ab") as handle:
        handle.write(b"http://localhost:8000")
    with pytest.raises(ValueError, match="legacy runtime authority"):
        package.write_bundle_manifest(
            tmp_path / "native-components-v1.json",
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )


def test_bundle_manifest_allows_a_credential_scrub_variable_name(tmp_path):
    desktop = tmp_path / "desktop.exe"
    broker = tmp_path / "aiguard-native-broker-test-target.exe"
    backend = tmp_path / "aiguard-test-target.exe"
    _component(desktop, marker=True)
    with desktop.open("ab") as handle:
        handle.write(b"AIGUARD_API_KEY")
    _component(broker, marker=True)
    _component(backend)

    package.write_bundle_manifest(
        tmp_path / "native-components-v1.json",
        desktop=desktop,
        broker=broker,
        backend=backend,
        version="2.5.0",
    )


def test_tauri_bundle_manifests_hash_final_direct_bundle_bytes_and_stage_invalid_appimage(
    tmp_path,
):
    desktop = tmp_path / "desktop"
    broker = tmp_path / "aiguard-native-broker-test-target"
    backend = tmp_path / "aiguard-test-target"
    _component(desktop, marker=True)
    with desktop.open("ab") as handle:
        handle.write(package.BUNDLE_TYPE_TOKEN)
    _component(broker, marker=True)
    _component(backend)
    outputs = {platform: tmp_path / platform for platform in ("windows", "linux", "macos")}
    for output in outputs.values():
        output.mkdir()

    windows = package.write_tauri_bundle_manifests(
        outputs["windows"],
        platform="windows",
        desktop=desktop,
        broker=broker,
        backend=backend,
        version="2.5.0",
    )
    linux = package.write_tauri_bundle_manifests(
        outputs["linux"],
        platform="linux",
        desktop=desktop,
        broker=broker,
        backend=backend,
        version="2.5.0",
    )
    macos = package.write_tauri_bundle_manifests(
        outputs["macos"],
        platform="macos",
        desktop=desktop,
        broker=broker,
        backend=backend,
        version="2.5.0",
    )

    assert [path.name for path in windows] == ["native-components-v1.nsis.json"]
    assert [path.name for path in linux] == [
        "native-components-v1.deb.json",
        "native-components-v1.appimage.json",
    ]
    assert [path.name for path in macos] == ["native-components-v1.macos.json"]
    original = desktop.read_bytes()
    expected_desktop_hashes = {
        windows[0]: hashlib.sha256(
            original.replace(package.BUNDLE_TYPE_TOKEN, package.BUNDLE_TYPE_PATCHES["nsis"])
        ).hexdigest(),
        linux[0]: hashlib.sha256(
            original.replace(package.BUNDLE_TYPE_TOKEN, package.BUNDLE_TYPE_PATCHES["deb"])
        ).hexdigest(),
        macos[0]: hashlib.sha256(original).hexdigest(),
    }
    for manifest_path, expected_hash in expected_desktop_hashes.items():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["clients"][0]["sha256"] == expected_hash
        assert manifest["clients"][0]["path"] == "desktop"
    assert json.loads(linux[1].read_text(encoding="utf-8")) == {}


def _final_appdir(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    appdir = tmp_path / "AI Guard.AppDir"
    package_dir = appdir / "usr" / "bin"
    package_dir.mkdir(parents=True)
    paths = {
        "desktop": package_dir / "desktop",
        "broker": package_dir / "aiguard-native-broker",
        "backend": package_dir / "aiguard",
        "backend_source": tmp_path / "staged-aiguard-backend",
        "manifest": package_dir / package.MANIFEST_NAME,
    }
    _component(paths["desktop"], marker=True)
    _component(paths["broker"], marker=True)
    _component(paths["backend"])
    _frozen_backend(paths["backend_source"])
    paths["manifest"].write_text("{}\n", encoding="utf-8")
    return appdir, paths


def test_finalize_appimage_restores_and_attests_staged_backend_before_atomic_replace(
    tmp_path, monkeypatch
):
    appdir, paths = _final_appdir(tmp_path)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    runtime = _synthetic_appimage_runtime(digest=b"original-md5-sum")
    repacked_runtime = _synthetic_appimage_runtime(digest=b"repacked-md5-sum")
    _pin_synthetic_appimage_runtime(monkeypatch, runtime)
    original = runtime + b"original-squashfs"
    appimage.write_bytes(original)
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"pinned synthetic plugin")
    plugin.chmod(0o755)
    monkeypatch.setitem(
        package.APPIMAGE_PLUGIN_SHA256,
        "x86_64",
        hashlib.sha256(plugin.read_bytes()).hexdigest(),
    )
    offset_calls = []

    def runtime_offset(path):
        offset_calls.append(path)
        return len(runtime)

    monkeypatch.setattr(package, "_appimage_runtime_offset", runtime_offset)

    observed = {}

    def repack(*, plugin, appdir, output, runtime, arch):
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        observed["manifest"] = manifest
        observed["runtime"] = runtime.read_bytes()
        observed["arch"] = arch
        output.write_bytes(repacked_runtime + b"verified-repacked-squashfs")
        output.chmod(0o755)

    def extract(_appimage, output):
        extracted = output / "squashfs-root"
        shutil.copytree(appdir, extracted)
        return extracted

    monkeypatch.setattr(package, "_repack_appimage", repack)
    monkeypatch.setattr(package, "_extract_appimage", extract)

    finalized = package.finalize_appimage(
        appimage,
        appdir=appdir,
        backend_source=paths["backend_source"],
        plugin=plugin,
        arch="x86_64",
        version="2.5.0",
    )

    assert finalized == appimage.resolve()
    assert appimage.read_bytes() == repacked_runtime + b"verified-repacked-squashfs"
    assert len(offset_calls) == 1
    assert offset_calls[0].name == appimage.name
    assert observed["runtime"] == runtime
    assert observed["arch"] == "x86_64"
    assert paths["backend"].read_bytes() == paths["backend_source"].read_bytes()
    assert (
        observed["manifest"]["clients"][0]["sha256"]
        == hashlib.sha256(paths["desktop"].read_bytes()).hexdigest()
    )
    assert (
        observed["manifest"]["broker"]["sha256"]
        == hashlib.sha256(paths["broker"].read_bytes()).hexdigest()
    )
    assert (
        observed["manifest"]["backend"]["sha256"]
        == hashlib.sha256(paths["backend_source"].read_bytes()).hexdigest()
    )


def test_finalize_appimage_rejects_backend_source_without_frozen_archive(tmp_path, monkeypatch):
    appdir, paths = _final_appdir(tmp_path)
    paths["backend_source"].write_bytes(b"stripped PyInstaller bootloader")
    paths["backend_source"].chmod(0o755)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    appimage.write_bytes(b"original AppImage")
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"pinned synthetic plugin")
    plugin.chmod(0o755)
    monkeypatch.setitem(
        package.APPIMAGE_PLUGIN_SHA256,
        "x86_64",
        hashlib.sha256(plugin.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        package,
        "_repack_appimage",
        lambda **_kwargs: pytest.fail("stripped backend must fail before repack"),
    )

    with pytest.raises(ValueError, match="invalid frozen backend archive"):
        package.finalize_appimage(
            appimage,
            appdir=appdir,
            backend_source=paths["backend_source"],
            plugin=plugin,
            arch="x86_64",
            version="2.5.0",
        )

    assert paths["manifest"].read_text(encoding="utf-8") == "{}\n"


def test_finalize_appimage_rejects_repacked_component_drift_without_replacing_candidate(
    tmp_path, monkeypatch
):
    appdir, _paths = _final_appdir(tmp_path)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    runtime = _synthetic_appimage_runtime(digest=b"original-md5-sum")
    repacked_runtime = _synthetic_appimage_runtime(digest=b"repacked-md5-sum")
    _pin_synthetic_appimage_runtime(monkeypatch, runtime)
    original = runtime + b"original-squashfs"
    appimage.write_bytes(original)
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"pinned synthetic plugin")
    plugin.chmod(0o755)
    monkeypatch.setitem(
        package.APPIMAGE_PLUGIN_SHA256,
        "x86_64",
        hashlib.sha256(plugin.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(package, "_appimage_runtime_offset", lambda _path: len(runtime))

    def repack(*, plugin, appdir, output, runtime, arch):
        output.write_bytes(repacked_runtime + b"untrusted-repacked-squashfs")
        output.chmod(0o755)

    def extract(_appimage, output):
        extracted = output / "squashfs-root"
        shutil.copytree(appdir, extracted)
        (extracted / "usr" / "bin" / "aiguard").write_bytes(b"mutated after manifest")
        return extracted

    monkeypatch.setattr(package, "_repack_appimage", repack)
    monkeypatch.setattr(package, "_extract_appimage", extract)

    with pytest.raises(RuntimeError, match="finalized AppImage verification failed"):
        package.finalize_appimage(
            appimage,
            appdir=appdir,
            backend_source=_paths["backend_source"],
            plugin=plugin,
            arch="x86_64",
            version="2.5.0",
        )

    assert appimage.read_bytes() == original


def test_finalize_appimage_rejects_repacked_runtime_drift_without_replacing_candidate(
    tmp_path, monkeypatch
):
    appdir, _paths = _final_appdir(tmp_path)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    runtime = _synthetic_appimage_runtime(digest=b"original-md5-sum")
    _pin_synthetic_appimage_runtime(monkeypatch, runtime)
    original = runtime + b"original-squashfs"
    appimage.write_bytes(original)
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"pinned synthetic plugin")
    plugin.chmod(0o755)
    monkeypatch.setitem(
        package.APPIMAGE_PLUGIN_SHA256,
        "x86_64",
        hashlib.sha256(plugin.read_bytes()).hexdigest(),
    )
    offset_calls = []

    def runtime_offset(path):
        offset_calls.append(path)
        return len(runtime)

    monkeypatch.setattr(package, "_appimage_runtime_offset", runtime_offset)

    def repack(*, plugin, appdir, output, runtime, arch):
        changed = bytearray(runtime.read_bytes())
        changed[480] ^= 0x01
        output.write_bytes(bytes(changed) + b"untrusted-repacked-squashfs")
        output.chmod(0o755)

    monkeypatch.setattr(package, "_repack_appimage", repack)
    monkeypatch.setattr(
        package,
        "_extract_appimage",
        lambda *_args, **_kwargs: pytest.fail("runtime drift must fail before extraction"),
    )

    with pytest.raises(RuntimeError, match="finalized AppImage verification failed"):
        package.finalize_appimage(
            appimage,
            appdir=appdir,
            backend_source=_paths["backend_source"],
            plugin=plugin,
            arch="x86_64",
            version="2.5.0",
        )

    assert appimage.read_bytes() == original
    assert offset_calls == []


def test_finalize_appimage_rejects_repacker_mutating_both_runtime_copies(tmp_path, monkeypatch):
    appdir, _paths = _final_appdir(tmp_path)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    runtime = _synthetic_appimage_runtime(digest=b"original-md5-sum")
    _pin_synthetic_appimage_runtime(monkeypatch, runtime)
    original = runtime + b"original-squashfs"
    appimage.write_bytes(original)
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"pinned synthetic plugin")
    plugin.chmod(0o755)
    monkeypatch.setitem(
        package.APPIMAGE_PLUGIN_SHA256,
        "x86_64",
        hashlib.sha256(plugin.read_bytes()).hexdigest(),
    )

    def repack(*, plugin, appdir, output, runtime, arch):
        changed = bytearray(runtime.read_bytes())
        changed[480] ^= 0x01
        runtime.write_bytes(changed)
        output.write_bytes(bytes(changed) + b"untrusted-repacked-squashfs")
        output.chmod(0o755)

    monkeypatch.setattr(package, "_repack_appimage", repack)
    monkeypatch.setattr(
        package,
        "_appimage_runtime_offset",
        lambda _path: pytest.fail("drifted AppImage runtime must not execute"),
    )
    monkeypatch.setattr(
        package,
        "_extract_appimage",
        lambda *_args, **_kwargs: pytest.fail("runtime drift must fail before extraction"),
    )

    with pytest.raises(RuntimeError, match="finalized AppImage verification failed"):
        package.finalize_appimage(
            appimage,
            appdir=appdir,
            backend_source=_paths["backend_source"],
            plugin=plugin,
            arch="x86_64",
            version="2.5.0",
        )

    assert appimage.read_bytes() == original


def test_appimage_runtime_verifier_allows_only_the_embedded_md5_value(tmp_path):
    expected = tmp_path / "expected-runtime"
    repacked = tmp_path / "repacked-runtime"
    expected.write_bytes(_synthetic_appimage_runtime(digest=b"original-md5-sum"))
    repacked.write_bytes(_synthetic_appimage_runtime(digest=b"repacked-md5-sum"))

    package._verify_appimage_runtime_prefix(expected, repacked)

    changed = bytearray(repacked.read_bytes())
    changed[-1] ^= 0x01
    repacked.write_bytes(changed)
    with pytest.raises(RuntimeError, match="runtime verification failed"):
        package._verify_appimage_runtime_prefix(expected, repacked)


def test_appimage_runtime_provenance_allows_only_the_embedded_md5_value(tmp_path, monkeypatch):
    expected_runtime = _synthetic_appimage_runtime(digest=b"original-md5-sum")
    _pin_synthetic_appimage_runtime(monkeypatch, expected_runtime)
    runtime = tmp_path / "runtime"
    runtime.write_bytes(_synthetic_appimage_runtime(digest=b"repacked-md5-sum"))

    package._verify_appimage_runtime_provenance(runtime, "x86_64")

    changed = bytearray(runtime.read_bytes())
    changed[480] ^= 0x01
    runtime.write_bytes(changed)
    with pytest.raises(RuntimeError, match="provenance verification failed"):
        package._verify_appimage_runtime_provenance(runtime, "x86_64")


def test_appimage_runtime_provenance_pin_is_exact_type2_runtime_asset():
    assert package.APPIMAGE_RUNTIME_PIN == {
        "x86_64": (
            944_632,
            "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
        )
    }


def test_finalize_appimage_rejects_unpinned_runtime_before_executing_it(tmp_path, monkeypatch):
    appdir, _paths = _final_appdir(tmp_path)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    runtime = _synthetic_appimage_runtime(digest=b"original-md5-sum")
    appimage.write_bytes(runtime + b"original-squashfs")
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"pinned synthetic plugin")
    plugin.chmod(0o755)
    monkeypatch.setitem(
        package.APPIMAGE_PLUGIN_SHA256,
        "x86_64",
        hashlib.sha256(plugin.read_bytes()).hexdigest(),
    )
    monkeypatch.setitem(
        package.APPIMAGE_RUNTIME_PIN,
        "x86_64",
        (len(runtime), "0" * 64),
    )
    monkeypatch.setattr(
        package,
        "_appimage_runtime_offset",
        lambda _path: pytest.fail("unattested AppImage runtime must not execute"),
    )
    monkeypatch.setattr(
        package,
        "_repack_appimage",
        lambda **_kwargs: pytest.fail("unattested AppImage runtime must not be repacked"),
    )

    with pytest.raises(RuntimeError, match="provenance verification failed"):
        package.finalize_appimage(
            appimage,
            appdir=appdir,
            backend_source=_paths["backend_source"],
            plugin=plugin,
            arch="x86_64",
            version="2.5.0",
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda runtime: runtime.__setitem__(slice(0, 4), b"NOPE"),
        lambda runtime: runtime.__setitem__(60, 0),
        lambda runtime: runtime.__setitem__(62, 0),
        lambda runtime: runtime.__setitem__(slice(264, 272), struct.pack("<Q", 10_000)),
    ],
)
def test_appimage_runtime_verifier_rejects_malformed_elf_metadata(tmp_path, mutate):
    expected = tmp_path / "expected-runtime"
    repacked = tmp_path / "repacked-runtime"
    runtime = bytearray(_synthetic_appimage_runtime())
    mutate(runtime)
    expected.write_bytes(runtime)
    repacked.write_bytes(runtime)

    with pytest.raises(RuntimeError, match="runtime verification failed"):
        package._verify_appimage_runtime_prefix(expected, repacked)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda runtime: runtime.__setitem__(184, 1),
        lambda runtime: runtime.__setitem__(slice(304, 308), struct.pack("<I", 17)),
        lambda runtime: runtime.__setitem__(slice(368, 372), struct.pack("<I", 11)),
        lambda runtime: runtime.__setitem__(slice(372, 376), struct.pack("<I", 3)),
        lambda runtime: runtime.__setitem__(slice(376, 384), struct.pack("<Q", 7)),
        lambda runtime: runtime.__setitem__(slice(400, 408), struct.pack("<Q", 15)),
        lambda runtime: runtime.__setitem__(slice(400, 408), struct.pack("<Q", 17)),
        lambda runtime: runtime.__setitem__(slice(392, 400), struct.pack("<Q", 480)),
        lambda runtime: runtime.__setitem__(460, ord("x")),
        lambda runtime: runtime.__setitem__(slice(124, 128), struct.pack("<I", 7)),
    ],
)
def test_appimage_runtime_verifier_rejects_unsafe_digest_section(tmp_path, mutate):
    expected = tmp_path / "expected-runtime"
    repacked = tmp_path / "repacked-runtime"
    runtime = bytearray(_synthetic_appimage_runtime())
    mutate(runtime)
    expected.write_bytes(runtime)
    repacked.write_bytes(runtime)

    with pytest.raises(RuntimeError, match="runtime verification failed"):
        package._verify_appimage_runtime_prefix(expected, repacked)


def test_finalize_appimage_rejects_unpinned_plugin_before_staging_manifest(
    tmp_path,
):
    appdir, paths = _final_appdir(tmp_path)
    appimage = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    appimage.write_bytes(b"runtime-original-appimage")
    appimage.chmod(0o755)
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    plugin.write_bytes(b"not the pinned plugin")
    plugin.chmod(0o755)

    with pytest.raises(ValueError, match="AppImage output plugin digest"):
        package.finalize_appimage(
            appimage,
            appdir=appdir,
            backend_source=paths["backend_source"],
            plugin=plugin,
            arch="x86_64",
            version="2.5.0",
        )

    assert paths["manifest"].read_text(encoding="utf-8") == "{}\n"


def test_appimage_repack_uses_fixed_inputs_and_scrubs_inherited_authority(tmp_path, monkeypatch):
    plugin = tmp_path / "linuxdeploy-plugin-appimage-x86_64.AppImage"
    appdir = tmp_path / "AI Guard.AppDir"
    output = tmp_path / "final.AppImage"
    runtime = tmp_path / "runtime"
    _component(plugin)
    appdir.mkdir()
    _component(runtime)
    monkeypatch.setenv("AIFORTHAI_API_KEY", "must-not-reach-tool")
    monkeypatch.setenv("LDAI_SIGN", "must-be-removed")
    monkeypatch.setenv("UPDATE_INFORMATION", "must-be-removed")
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        output.write_bytes(b"synthetic AppImage")

    monkeypatch.setattr(package.subprocess, "run", run)

    package._repack_appimage(
        plugin=plugin,
        appdir=appdir,
        output=output,
        runtime=runtime,
        arch="x86_64",
    )

    assert observed["command"] == [
        str(plugin),
        "--appimage-extract-and-run",
        "--appdir",
        str(appdir),
    ]
    assert observed["check"] is True
    assert observed["cwd"] == tmp_path
    assert observed["timeout"] == 300
    assert observed["env"]["APPIMAGE_EXTRACT_AND_RUN"] == "1"
    assert observed["env"]["ARCH"] == "x86_64"
    assert observed["env"]["LDAI_OUTPUT"] == str(output)
    assert observed["env"]["LDAI_RUNTIME_FILE"] == str(runtime)
    assert "AIFORTHAI_API_KEY" not in observed["env"]
    assert "LDAI_SIGN" not in observed["env"]
    assert "UPDATE_INFORMATION" not in observed["env"]


def test_build_placeholder_cli_atomically_replaces_only_allowed_manifests(tmp_path, monkeypatch):
    binaries = tmp_path / "binaries"
    binaries.mkdir()
    expected_names = set(package.BUNDLE_MANIFEST_NAMES.values())
    for name in expected_names:
        (binaries / name).write_text('{"stale": true}\n', encoding="utf-8")
    runtime_manifest = binaries / package.MANIFEST_NAME
    runtime_manifest.write_text('{"preserve": true}\n', encoding="utf-8")
    unrelated = binaries / "unrelated.json"
    unrelated.write_text('{"preserve": true}\n', encoding="utf-8")

    replacements = []
    real_replace = package.os.replace

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(package, "BUNDLE_MANIFEST_DIRECTORY", binaries)
    monkeypatch.setattr(package.os, "replace", record_replace)
    monkeypatch.setattr(
        package,
        "_default_paths",
        lambda: pytest.fail("placeholder mode must not inspect component paths"),
    )
    monkeypatch.setattr(package.sys, "argv", [str(SCRIPT), "--build-placeholders"])

    assert package.main() == 0
    assert {destination.name for _source, destination in replacements} == expected_names
    assert all(source.parent == binaries for source, _destination in replacements)
    assert all((binaries / name).read_text(encoding="utf-8") == "{}\n" for name in expected_names)
    assert runtime_manifest.read_text(encoding="utf-8") == '{"preserve": true}\n'
    assert unrelated.read_text(encoding="utf-8") == '{"preserve": true}\n'


def test_build_placeholder_cli_rejects_linked_fixed_directory(tmp_path, monkeypatch):
    real_output = tmp_path / "real-binaries"
    real_output.mkdir()
    linked_output = tmp_path / "linked-binaries"
    _symlink_or_skip(linked_output, real_output, directory=True)
    monkeypatch.setattr(package, "BUNDLE_MANIFEST_DIRECTORY", linked_output)
    monkeypatch.setattr(package.sys, "argv", [str(SCRIPT), "--build-placeholders"])

    with pytest.raises(ValueError, match="manifest directory"):
        package.main()

    assert list(real_output.iterdir()) == []


def test_tauri_bundle_manifest_fails_closed_without_patch_token(tmp_path):
    desktop = tmp_path / "desktop.exe"
    broker = tmp_path / "aiguard-native-broker-test-target.exe"
    backend = tmp_path / "aiguard-test-target.exe"
    _component(desktop, marker=True)
    _component(broker, marker=True)
    _component(backend)

    with pytest.raises(ValueError, match="bundle type token"):
        package.write_tauri_bundle_manifests(
            tmp_path,
            platform="windows",
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )


def test_package_component_rejects_symlink_before_resolution(tmp_path):
    target = tmp_path / "desktop-real"
    _component(target, marker=True)
    link = tmp_path / "desktop"
    _symlink_or_skip(link, target)

    with pytest.raises(ValueError, match="invalid package component"):
        package._checked_source(link, marker_version="2.5.0")


def test_tauri_bundle_manifest_rejects_symlink_output_directory(tmp_path):
    output = tmp_path / "real-output"
    output.mkdir()
    link = tmp_path / "linked-output"
    _symlink_or_skip(link, output, directory=True)

    desktop = tmp_path / "desktop"
    broker = tmp_path / "aiguard-native-broker-test-target"
    backend = tmp_path / "aiguard-test-target"
    _component(desktop, marker=True)
    with desktop.open("ab") as handle:
        handle.write(package.BUNDLE_TYPE_TOKEN)
    _component(broker, marker=True)
    _component(backend)

    with pytest.raises(ValueError, match="manifest directory"):
        package.write_tauri_bundle_manifests(
            link,
            platform="macos",
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )


def test_tauri_bundle_configs_place_manifest_beside_native_components():
    tauri = ROOT / "desktop" / "src-tauri"
    base = json.loads((tauri / "tauri.conf.json").read_text(encoding="utf-8"))
    windows = json.loads((tauri / "tauri.windows.conf.json").read_text(encoding="utf-8"))
    macos = json.loads((tauri / "tauri.macos.conf.json").read_text(encoding="utf-8"))
    linux = json.loads((tauri / "tauri.linux.conf.json").read_text(encoding="utf-8"))

    assert base["bundle"]["externalBin"] == [
        "binaries/aiguard",
        "binaries/aiguard-native-broker",
        "binaries/aiguard-chrome-native-host",
        "binaries/aiguard-native-host-manager",
    ]
    assert base["build"]["beforeBundleCommand"] == (
        "python ../scripts/prepare_desktop_native_package.py --bundle-manifest"
    )
    windows_source = "binaries/native-components-v1.nsis.json"
    assert windows["bundle"]["resources"] == {windows_source: "native-components-v1.json"}
    assert windows["bundle"]["windows"]["nsis"]["installerHooks"] == (
        "windows/native-host-hooks.nsh"
    )
    macos_source = "binaries/native-components-v1.macos.json"
    assert macos == {
        "bundle": {"macOS": {"files": {"MacOS/native-components-v1.json": macos_source}}}
    }
    assert linux == {
        "bundle": {
            "linux": {
                "deb": {
                    "preInstallScript": "linux/deb-preinst.sh",
                    "postInstallScript": "linux/deb-postinst.sh",
                    "preRemoveScript": "linux/deb-prerm.sh",
                    "postRemoveScript": "linux/deb-postrm.sh",
                    "files": {
                        "/usr/bin/native-components-v1.json": (
                            "binaries/native-components-v1.deb.json"
                        )
                    },
                },
                "appimage": {
                    "files": {
                        "/usr/bin/native-components-v1.json": (
                            "binaries/native-components-v1.appimage.json"
                        )
                    }
                },
            }
        }
    }
    preinst = (tauri / "linux" / "deb-preinst.sh").read_text(encoding="utf-8")
    postinst = (tauri / "linux" / "deb-postinst.sh").read_text(encoding="utf-8")
    prerm = (tauri / "linux" / "deb-prerm.sh").read_text(encoding="utf-8")
    postrm = (tauri / "linux" / "deb-postrm.sh").read_text(encoding="utf-8")
    assert '"$manager" complete deb "$transaction"' in postinst
    assert '"$manager" complete-legacy deb' in postinst
    assert '[ "$(wc -c < "$receipt")" -eq 65 ]' in postinst
    assert '"$manager" drain deb' in preinst
    assert "wait_for_component_exit" in preinst
    assert "adapter=/usr/bin/aiguard-chrome-native-host" in preinst
    assert 'adapter_identity=$(component_identity "$adapter")' in preinst
    assert "/proc/[0-9]*/exe" in preinst
    assert "kill " not in preinst
    assert preinst.rindex("wait_for_component_exit") < preinst.index(
        'rm -f -- "$desktop" "$adapter" "$broker" "$backend" "$manager"'
    )
    assert (
        'wait_for_component_exit "$broker_identity" "$backend_identity" "$adapter_identity" "" 1'
        in preinst
    )
    assert "quarantine_legacy_launchers" in preinst
    assert "restore_legacy_launchers" in preinst
    assert "restore_legacy_registration" in preinst
    assert "remove_legacy_registration_quarantine" in preinst
    assert "restore_legacy_state" in preinst
    assert "flock -n 9" in preinst
    assert '"$manager" remove deb' in prerm
    assert '"$manager" cleanup deb' in prerm
    assert 'adapter_identity=$(component_identity "$adapter")' in prerm
    assert '[ "${1:-}" = remove ] && identity_is_running "$desktop_identity"' in prerm
    assert prerm.index('"$manager" cleanup deb') < prerm.rindex(
        'rm -f -- "$desktop" "$adapter" "$broker" "$backend" "$manager"'
    )
    assert prerm.index('while [ "$clear_attempts" -lt 10 ]') < prerm.index(
        'rm -f -- "$desktop" "$adapter" "$broker" "$backend" "$manager"'
    )
    assert "flock -n 9" in prerm
    assert "/proc/[0-9]*/exe" in prerm
    assert 'if [ "$partial" -eq 1 ]' in prerm
    assert "validate_receipt" in prerm
    assert "validate_marker" in prerm
    assert '[ ! -e "$registration" ]' in prerm
    assert '"$manager" cleanup deb' in prerm
    assert "The manager is the final rm operand" in prerm
    assert "kill " not in prerm
    assert "remove|purge)" in postrm
    assert 'rm -f -- "$marker"' in postrm
    assert 'rm -f -- "$receipt"' in postrm
    assert '[ "$(wc -c < "$marker")" -eq 33 ]' in preinst
    assert '[ "$(wc -c < "$marker")" -eq 33 ]' in postrm
    assert "printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\\n' | cmp -s - \"$marker\"" in preinst
    assert "printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\\n' | cmp -s - \"$marker\"" in postrm
    assert '$(cat "$marker")' not in preinst
    assert '$(cat "$marker")' not in postrm


def test_deb_marker_contract_distinguishes_terminal_newline_from_nul(tmp_path):
    expected = b"AIGUARD_COMPONENT_MAINTENANCE_V1\n"
    malformed = b"AIGUARD_COMPONENT_MAINTENANCE_V1\0"
    assert len(expected) == len(malformed) == 33
    assert expected != malformed
    if os.name != "nt":
        marker = tmp_path / "marker"
        marker.write_bytes(malformed)
        rejected = subprocess.run(
            [
                "sh",
                "-c",
                "printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\\n' | cmp -s - \"$1\"",
                "sh",
                str(marker),
            ],
            check=False,
        )
        assert rejected.returncode != 0
        marker.write_bytes(expected)
        accepted = subprocess.run(
            [
                "sh",
                "-c",
                "printf 'AIGUARD_COMPONENT_MAINTENANCE_V1\\n' | cmp -s - \"$1\"",
                "sh",
                str(marker),
            ],
            check=False,
        )
        assert accepted.returncode == 0


def test_live_upgrade_smoke_callback_is_single_run_and_private_marker_scoped(tmp_path):
    with pytest.raises(ValueError, match="exactly one repetition"):
        smoke_package.smoke(tmp_path, 1.0, repetitions=2, ready_callback=lambda: None)
    with pytest.raises(ValueError, match="requires upgrade invalidation smoke"):
        smoke_package.smoke(tmp_path, 1.0, ready_callback=lambda: None)
    marker_root = tmp_path / "marker-root"
    marker_root.mkdir()
    smoke_package._publish_release_marker(marker_root)
    assert (marker_root / smoke_package.SMOKE_RELEASE).read_bytes() == b"release"
    assert not any(".pending-" in path.name for path in marker_root.iterdir())
    with pytest.raises(RuntimeError, match="release marker publication failed"):
        smoke_package._publish_release_marker(marker_root)
    assert (marker_root / smoke_package.SMOKE_RELEASE).read_bytes() == b"release"
    assert not any(".pending-" in path.name for path in marker_root.iterdir())
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    live_upgrade = (ROOT / "scripts" / "smoke_live_deb_upgrade.py").read_text(encoding="utf-8")
    package_smoke = (ROOT / "desktop" / "src-tauri" / "src" / "package_smoke.rs").read_text(
        encoding="utf-8"
    )
    assert "AIGUARD_DESKTOP_PACKAGE_SMOKE_RELEASE" in source
    assert "os.link(pending_release, marker_root / SMOKE_RELEASE)" in source
    assert "ready_callback()" in source
    assert '["sudo", "dpkg", "-i", str(deb)]' in live_upgrade
    assert live_upgrade.index("smoke_upgrade_invalidation(") < live_upgrade.index(
        "installed = smoke(package"
    )
    assert "live_nonroot_deb_upgrade" in live_upgrade
    assert "wait_for_optional_release" in package_smoke
    assert 'Some(b"release")' in package_smoke
    assert "PACKAGE_SMOKE_RELEASE_WAIT_SECONDS: u64 = 90" in package_smoke


def test_live_deb_upgrade_invalidates_old_desktop_before_smoking_new_install(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    monkeypatch.setitem(sys.modules, "smoke_desktop_native_package", smoke_package)
    live_script = ROOT / "scripts" / "smoke_live_deb_upgrade.py"
    spec = importlib.util.spec_from_file_location("smoke_live_deb_upgrade_test", live_script)
    assert spec and spec.loader
    live_upgrade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_upgrade)
    events = []
    package_root = tmp_path / "installed"
    package_root.mkdir()
    deb = tmp_path / "candidate.deb"
    deb.write_bytes(b"synthetic DEB")

    def upgrade_invalidation(package, timeout, *, ready_callback):
        assert package == package_root
        assert timeout == live_upgrade.OLD_DESKTOP_INVALIDATION_TIMEOUT_SECONDS
        events.append("old-ready")
        ready_callback()
        events.append("old-invalidated")
        return {"stale_session_invalidated": True}

    def installed_smoke(package, timeout):
        assert package == package_root
        assert timeout == live_upgrade.NEW_DESKTOP_SMOKE_TIMEOUT_SECONDS
        assert events == ["old-ready", "upgrade", "old-invalidated"]
        events.append("new-attested")
        return {"execution_mode": "direct_install"}

    def run_upgrade(command, **kwargs):
        assert command == ["sudo", "dpkg", "-i", str(deb)]
        assert kwargs["timeout"] == live_upgrade.DEB_UPGRADE_TIMEOUT_SECONDS
        events.append("upgrade")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(live_upgrade, "smoke_upgrade_invalidation", upgrade_invalidation)
    monkeypatch.setattr(live_upgrade, "smoke", installed_smoke)
    monkeypatch.setattr(live_upgrade.subprocess, "run", run_upgrade)

    evidence = live_upgrade.smoke_live_upgrade(package_root, deb)

    assert events == ["old-ready", "upgrade", "old-invalidated", "new-attested"]
    assert evidence == {
        "lifecycle": "live_nonroot_deb_upgrade",
        "old_desktop": {"stale_session_invalidated": True},
        "new_desktop": {"execution_mode": "direct_install"},
    }


def test_native_package_hooks_drain_before_replacement_and_keep_fixed_diagnostics():
    tauri = ROOT / "desktop" / "src-tauri"
    nsis = (tauri / "windows" / "native-host-hooks.nsh").read_text(encoding="utf-8")
    updater = (tauri / "src" / "updater.rs").read_text(encoding="utf-8")
    manager = (ROOT / "native-broker" / "src" / "bin" / "native_host_manager.rs").read_text(
        encoding="utf-8"
    )
    adapter = (ROOT / "native-broker" / "src" / "bin" / "chrome_native_host.rs").read_text(
        encoding="utf-8"
    )

    assert nsis.index("!macro NSIS_HOOK_PREINSTALL") < nsis.index("!macro NSIS_HOOK_POSTINSTALL")
    assert nsis.index(
        "nsExec::ExecToStack '\"$INSTDIR\\aiguard-native-host-manager.exe\" drain nsis'"
    ) < nsis.index('complete nsis "$AIGUARD_TRANSACTION_TOKEN"')
    assert updater.index(".download(") < updater.index("update.install(bytes)")
    assert updater.index("in_app_update_supported") < updater.index(".updater()")
    assert "UPDATE_INSTALL_ACTIVE" in updater
    assert "Action::Drain" not in updater
    assert "Action::Complete" not in updater
    assert updater.index("update.install(bytes)") < updater.index("app.restart()")
    assert "UpdateInstallGuard::acquire()" in updater
    desktop_lifecycle = (tauri / "src" / "native_host_lifecycle.rs").read_text(encoding="utf-8")
    assert "#[cfg(windows)]" in desktop_lifecycle
    assert "#[cfg(not(windows))]" in desktop_lifecycle
    assert "release_appimage_update_handoff" not in desktop_lifecycle
    for operation in (
        '"capability"',
        '"install"',
        '"repair"',
        '"complete"',
        '"complete-legacy"',
        '"resume-package"',
        '"uninstall"',
        '"remove"',
        '"drain"',
        '"cleanup"',
    ):
        assert operation in manager
    assert "PackageShape::Nsis | PackageShape::Deb | PackageShape::AppImage" in manager
    assert "operation_supports_shape(operation, shape)" in manager
    assert "capability nsis" in nsis
    assert "AIGUARD_ACQUIRE_PACKAGE_LOCK" in nsis
    assert "CreateFileW" in nsis
    assert "$LOCALAPPDATA\\AI Guard.aiguard-package-lifecycle-v1.lock" in nsis
    assert "0x04200002" in nsis  # hidden, open-reparse-point, delete-on-close
    assert "CreateMutexW" not in nsis
    assert "Local\\th.ac.psu.aiguard.package-lifecycle-v1" not in nsis
    assert nsis.count("$INSTDIR\\th.ac.psu.aiguard.native_host.json") == 8
    assert (
        nsis.count(
            'DeleteRegKey HKCU "Software\\Google\\Chrome\\NativeMessagingHosts\\th.ac.psu.aiguard.native_host"'
        )
        == 4
    )
    assert (
        nsis.count(
            'DeleteRegKey HKCU "Software\\Chromium\\NativeMessagingHosts\\th.ac.psu.aiguard.native_host"'
        )
        == 4
    )
    assert "$INSTDIR\\native-host-manifest.json" not in nsis
    drain_script = (tauri / "windows" / "native-component-drain.ps1").read_text(encoding="utf-8")
    assert "Get-CimInstance Win32_Process" in drain_script
    assert drain_script.count("-Filter $processFilter") == 2
    for name in (
        "desktop.exe",
        "aiguard-chrome-native-host.exe",
        "aiguard-native-broker.exe",
        "aiguard.exe",
        "aiguard-native-host-manager.exe",
    ):
        assert f"Name = '{name}'" in drain_script
    assert "-OperationTimeoutSec 2" in drain_script
    assert '$ErrorActionPreference = "Stop"' in drain_script
    assert "[Diagnostics.Stopwatch]::StartNew()" in drain_script
    assert "Elapsed.TotalSeconds -lt 30" in drain_script
    assert "clearSamples -ge 10" in drain_script
    assert "[IO.File]::Move" in drain_script
    assert "[IO.File]::Delete" in drain_script
    assert "Get-NormalizedProcessPath" in drain_script
    assert "Substring(8)" in drain_script
    assert "return '\\\\' + $path.Substring(8)" in drain_script
    assert "Substring(4)" in drain_script
    assert "Keep every completed quarantine in place" in drain_script
    assert drain_script.count("Stop-Process -Id $process.ProcessId -Force") == 2
    assert "$INSTDIR" not in drain_script
    assert "AIGUARD_INTERNAL_INSTALL_ROOT" in nsis
    assert "AIGUARD_INTERNAL_INSTALL_ROOT" in drain_script
    assert "IsPathFullyQualified" not in drain_script
    assert "driveAbsolute" in drain_script
    assert "uncAbsolute" in drain_script
    assert "AiGuardPackageFileIdentity" in drain_script
    assert "GetFileInformationByHandle" in drain_script
    assert "NumberOfLinks == 1" in drain_script
    assert "BytesEqual(byte[] left, byte[] right)" in drain_script
    assert "IsOwnedByCurrentUser(string path)" in drain_script
    assert "SetOwnerToCurrentUser(string path)" in drain_script
    assert "NormalizePayloadOwners(string[] paths)" in drain_script
    assert "private const int TokenOwner = 4" in drain_script
    assert "SetSecurityInfo(" in drain_script
    assert "FileShareRead" in drain_script
    assert "-not (Test-Path -LiteralPath $receipt)" in drain_script
    assert "File.GetAccessControl" in drain_script
    assert "SequenceEqual[byte]" not in drain_script
    assert "Get-Acl" not in drain_script
    assert "AIGUARD_COMPONENT_MAINTENANCE_V1`n" in drain_script
    drain_macro = nsis.split("!macro AIGUARD_WAIT_AND_REMOVE_LAUNCHERS", 1)[1].split(
        "!macroend", 1
    )[0]
    assert drain_macro.index('SetOutPath "$PLUGINSDIR"') < drain_macro.index(
        "File /oname=aiguard-native-component-drain.ps1"
    )
    assert drain_macro.index("File /oname=aiguard-native-component-drain.ps1") < (
        drain_macro.index('SetOutPath "$INSTDIR"')
    )
    assert drain_macro.index('SetOutPath "$INSTDIR"') < drain_macro.index("ExecWait")
    assert "NSIS System.dll" in drain_macro
    assert ".aiguard-component-transaction-v1" in nsis
    assert "resume-package nsis" in nsis
    assert "AIGUARD_NORMALIZE_PACKAGE_PAYLOAD" in nsis
    postinstall = nsis.split("!macro NSIS_HOOK_POSTINSTALL", 1)[1].split("!macroend", 1)[0]
    assert postinstall.index("AIGUARD_NORMALIZE_PACKAGE_PAYLOAD") < postinstall.index(
        "resume-package nsis"
    )
    assert "-Mode NormalizePayload" in nsis
    assert "ExecutionPolicy" not in nsis
    assert "aiguard_recover_remove" in nsis
    assert 'StrCmp $5 "f" aiguard_uninstall_token_character' in nsis
    assert nsis.count("!insertmacro AIGUARD_WAIT_AND_REMOVE_LAUNCHERS") == 2
    preuninstall = nsis.split("!macro NSIS_HOOK_PREUNINSTALL", 1)[1]
    assert preuninstall.index("remove nsis") < preuninstall.index(
        "AIGUARD_WAIT_AND_REMOVE_LAUNCHERS"
    )
    postuninstall = nsis.split("!macro NSIS_HOOK_POSTUNINSTALL", 1)[1]
    assert postuninstall.index('SetOutPath "$PLUGINSDIR"') < postuninstall.index('RMDir "$INSTDIR"')
    assert "AI Guard native component cleanup failed." in postuninstall
    assert "isolate_legacy_registration" in (tauri / "linux" / "deb-preinst.sh").read_text(
        encoding="utf-8"
    )
    assert "aiguard-chrome-native-host.exe" in drain_script
    assert "component_replacement_active" in adapter
    assert "start_component_replacement_monitor" in adapter
    for source in (nsis, updater, manager, adapter):
        assert "AIFORTHAI_API_KEY" not in source
        assert "TOKENMIND_API_KEY" not in source


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell")
def test_native_component_drain_executes_in_windows_powershell_51(request):
    from ctypes import wintypes

    class Trustee(ctypes.Structure):
        pass

    Trustee._fields_ = [
        ("multiple_trustee", ctypes.POINTER(Trustee)),
        ("multiple_trustee_operation", ctypes.c_int),
        ("trustee_form", ctypes.c_int),
        ("trustee_type", ctypes.c_int),
        ("name", ctypes.c_void_p),
    ]

    class ExplicitAccess(ctypes.Structure):
        pass

    ExplicitAccess._fields_ = [
        ("permissions", wintypes.DWORD),
        ("access_mode", ctypes.c_int),
        ("inheritance", wintypes.DWORD),
        ("trustee", Trustee),
    ]

    tmp_path = Path(
        tempfile.mkdtemp(
            prefix="aiguard-ps5-drain-",
            dir=Path(os.environ["LOCALAPPDATA"]).resolve(strict=True),
        )
    )
    request.addfinalizer(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.SetEntriesInAclW.argtypes = [
        wintypes.ULONG,
        ctypes.POINTER(ExplicitAccess),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.SetEntriesInAclW.restype = wintypes.DWORD

    def set_current_access(path: Path, *, change_owner: bool) -> None:
        token = wintypes.HANDLE()
        assert advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token))
        try:
            required = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
            assert required.value > 0
            token_user = ctypes.create_string_buffer(required.value)
            assert advapi32.GetTokenInformation(
                token,
                1,
                token_user,
                required,
                ctypes.byref(required),
            )
            user_sid = ctypes.cast(token_user, ctypes.POINTER(ctypes.c_void_p))[0]
            access = ExplicitAccess(
                0x001F01FF,
                2,
                0,
                Trustee(None, 0, 0, 1, user_sid),
            )
            acl = ctypes.c_void_p()
            assert advapi32.SetEntriesInAclW(1, ctypes.byref(access), None, ctypes.byref(acl)) == 0
            try:
                assert (
                    advapi32.SetNamedSecurityInfoW(
                        str(path),
                        1,
                        0x00000004 | (0x00000001 if change_owner else 0),
                        user_sid if change_owner else None,
                        None,
                        acl,
                        None,
                    )
                    == 0
                )
            finally:
                kernel32.LocalFree(acl)
        finally:
            kernel32.CloseHandle(token)

    def is_current_owner(path: Path) -> bool:
        owner = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        assert (
            advapi32.GetNamedSecurityInfoW(
                str(path),
                1,
                0x00000001,
                ctypes.byref(owner),
                None,
                None,
                None,
                ctypes.byref(descriptor),
            )
            == 0
        )
        token = wintypes.HANDLE()
        assert advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token))
        try:
            required = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
            token_user = ctypes.create_string_buffer(required.value)
            assert advapi32.GetTokenInformation(
                token,
                1,
                token_user,
                required,
                ctypes.byref(required),
            )
            user_sid = ctypes.cast(token_user, ctypes.POINTER(ctypes.c_void_p))[0]
            return bool(advapi32.EqualSid(owner, user_sid))
        finally:
            kernel32.CloseHandle(token)
            kernel32.LocalFree(descriptor)

    def token_owner_matches_user() -> bool:
        token = wintypes.HANDLE()
        assert advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token))
        try:
            buffers = []
            sids = []
            for information_class in (1, 4):
                required = wintypes.DWORD()
                advapi32.GetTokenInformation(
                    token,
                    information_class,
                    None,
                    0,
                    ctypes.byref(required),
                )
                buffer = ctypes.create_string_buffer(required.value)
                assert advapi32.GetTokenInformation(
                    token,
                    information_class,
                    buffer,
                    required,
                    ctypes.byref(required),
                )
                buffers.append(buffer)
                sids.append(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0])
            return bool(advapi32.EqualSid(sids[0], sids[1]))
        finally:
            kernel32.CloseHandle(token)

    def set_current_owner(path: Path) -> None:
        set_current_access(path, change_owner=True)

    powershell = (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    environment = os.environ.copy()
    environment["AIGUARD_INTERNAL_INSTALL_ROOT"] = str(tmp_path)
    command = [
        str(powershell),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(ROOT / "desktop" / "src-tauri" / "windows" / "native-component-drain.ps1"),
    ]
    normalize_command = [*command, "-Mode", "NormalizePayload"]

    def run_marker_only(
        label: str,
        marker_bytes: bytes = b"AIGUARD_COMPONENT_MAINTENANCE_V1\n",
        *,
        hardlink: bool = False,
        reparse: bool = False,
        command_cwd: Path | None = None,
        use_install_root_cwd: bool = False,
    ):
        root = tmp_path / label
        root.mkdir()
        marker = root / ".aiguard-component-maintenance-v1"
        if reparse:
            target = root / "marker-target"
            target.write_bytes(marker_bytes)
            os.symlink(target, marker)
        else:
            marker.write_bytes(marker_bytes)
        if hardlink:
            os.link(marker, root / "marker-hardlink-probe")
        environment["AIGUARD_INTERNAL_INSTALL_ROOT"] = str(root)
        return (
            subprocess.run(
                command,
                cwd=root if use_install_root_cwd else (command_cwd or ROOT),
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            ),
            marker,
        )

    def run_with_controls(
        label: str,
        receipt_bytes: bytes,
        *,
        hardlink_marker: bool = False,
        hardlink_receipt: bool = False,
    ):
        root = tmp_path / label
        root.mkdir()
        marker = root / ".aiguard-component-maintenance-v1"
        receipt = root / ".aiguard-component-transaction-v1"
        marker.write_bytes(b"AIGUARD_COMPONENT_MAINTENANCE_V1\n")
        receipt.write_bytes(receipt_bytes)
        set_current_owner(marker)
        set_current_owner(receipt)
        if hardlink_marker:
            os.link(marker, root / "marker-hardlink-probe")
        if hardlink_receipt:
            os.link(receipt, root / "receipt-hardlink-probe")
        environment["AIGUARD_INTERNAL_INSTALL_ROOT"] = str(root)
        return subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    payload_bytes = {
        "desktop.exe": b"desktop-package-fixture",
        "aiguard-chrome-native-host.exe": b"adapter-package-fixture",
        "aiguard-native-broker.exe": b"broker-package-fixture",
        "aiguard.exe": b"backend-package-fixture",
        "aiguard-native-host-manager.exe": b"manager-package-fixture",
        "native-components-v1.json": b'{"schema_version":1}',
        "uninstall.exe": b"uninstaller-package-fixture",
    }

    def run_payload_normalization(
        label: str,
        *,
        missing: str | None = None,
        empty: str | None = None,
        hardlink: str | None = None,
        reparse: str | None = None,
        marker_present: bool = True,
        receipt_bytes: bytes | None = None,
        receipt_current_owner: bool = True,
    ):
        root = tmp_path / label
        root.mkdir()
        marker = root / ".aiguard-component-maintenance-v1"
        if marker_present:
            marker.write_bytes(b"AIGUARD_COMPONENT_MAINTENANCE_V1\n")
        if receipt_bytes is not None:
            assert marker_present
            set_current_owner(marker)
            receipt = root / ".aiguard-component-transaction-v1"
            receipt.write_bytes(receipt_bytes)
            if receipt_current_owner:
                set_current_owner(receipt)
        for name, content in payload_bytes.items():
            if name == missing:
                continue
            path = root / name
            if name == reparse:
                target = root / f"{name}.target"
                target.write_bytes(content)
                set_current_access(target, change_owner=False)
                os.symlink(target, path)
            else:
                path.write_bytes(b"" if name == empty else content)
                set_current_access(path, change_owner=False)
        if hardlink is not None:
            os.link(root / hardlink, root / f"{hardlink}.hardlink-probe")
        owner_probe = next(
            root / name for name in payload_bytes if name != missing and name != reparse
        )
        source_owner_mismatch = not is_current_owner(owner_probe)
        before = {
            name: (root / name).read_bytes()
            for name in payload_bytes
            if name != missing and name != reparse
        }
        environment["AIGUARD_INTERNAL_INSTALL_ROOT"] = str(root)
        result = subprocess.run(
            normalize_command,
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        return result, root, before, source_owner_mismatch

    valid = run_with_controls("valid", (b"0" * 64) + b"\n")
    assert valid.returncode == 0, valid.stderr
    assert (
        run_with_controls(
            "hardlink-marker",
            (b"0" * 64) + b"\n",
            hardlink_marker=True,
        ).returncode
        == 1
    )
    assert (
        run_with_controls(
            "hardlink-receipt",
            (b"0" * 64) + b"\n",
            hardlink_receipt=True,
        ).returncode
        == 1
    )
    for label, malformed in (
        ("extra-lf", (b"0" * 64) + b"\n\n"),
        ("crlf", (b"0" * 64) + b"\r\n"),
        ("nul-byte", (b"0" * 64) + b"\x00"),
        ("uppercase", (b"A" * 64) + b"\n"),
    ):
        assert run_with_controls(label, malformed).returncode == 1

    marker_only, normalized_marker = run_marker_only("marker-only")
    assert marker_only.returncode == 0, marker_only.stderr
    assert normalized_marker.read_bytes() == b"AIGUARD_COMPONENT_MAINTENANCE_V1\n"
    assert is_current_owner(normalized_marker)

    normalized, payload_root, payload_before, source_owner_mismatch = run_payload_normalization(
        "payload-normalization"
    )
    assert normalized.returncode == 0, normalized.stderr
    assert source_owner_mismatch == (not token_owner_matches_user())
    for name, expected in payload_before.items():
        path = payload_root / name
        assert path.read_bytes() == expected
        assert is_current_owner(path)
    assert (payload_root / ".aiguard-component-maintenance-v1").is_file()

    resumed, resumed_root, resumed_before, _ = run_payload_normalization(
        "payload-resume",
        receipt_bytes=(b"1" * 64) + b"\n",
    )
    assert resumed.returncode == 0, resumed.stderr
    for name, expected in resumed_before.items():
        assert (resumed_root / name).read_bytes() == expected

    assert run_payload_normalization("payload-missing", missing="desktop.exe")[0].returncode == 1
    assert (
        run_payload_normalization("payload-missing-marker", marker_present=False)[0].returncode == 1
    )
    assert run_payload_normalization("payload-empty", empty="aiguard.exe")[0].returncode == 1
    assert (
        run_payload_normalization(
            "payload-malformed-receipt",
            receipt_bytes=(b"A" * 64) + b"\n",
        )[0].returncode
        == 1
    )
    assert (
        run_payload_normalization(
            "payload-hardlink",
            hardlink="aiguard-native-host-manager.exe",
        )[0].returncode
        == 1
    )
    if not token_owner_matches_user():
        assert (
            run_payload_normalization(
                "payload-wrong-receipt-owner",
                receipt_bytes=(b"2" * 64) + b"\n",
                receipt_current_owner=False,
            )[0].returncode
            == 1
        )
    try:
        payload_reparse = run_payload_normalization(
            "payload-reparse",
            reparse="aiguard-native-broker.exe",
        )[0]
    except OSError:
        pass
    else:
        assert payload_reparse.returncode == 1

    collision_directory = tmp_path / "nsis-plugin-collision"
    collision_directory.mkdir()
    shutil.copy2(
        Path(os.environ["SystemRoot"]) / "System32" / "kernel32.dll",
        collision_directory / "System.dll",
    )
    collision_result, _ = run_marker_only(
        "plugin-system-collision",
        command_cwd=collision_directory,
    )
    assert collision_result.returncode == 1
    isolated_result, _ = run_marker_only(
        "plugin-system-isolated",
        use_install_root_cwd=True,
    )
    assert isolated_result.returncode == 0, isolated_result.stderr

    assert run_marker_only("marker-hardlink", hardlink=True)[0].returncode == 1
    for label, malformed in (
        ("marker-extra-lf", b"AIGUARD_COMPONENT_MAINTENANCE_V1\n\n"),
        ("marker-altered", b"AIGUARD_COMPONENT_MAINTENANCE_V2\n"),
    ):
        assert run_marker_only(label, malformed)[0].returncode == 1
    try:
        reparse_result, _ = run_marker_only("marker-reparse", reparse=True)
    except OSError:
        pass
    else:
        assert reparse_result.returncode == 1


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows PowerShell")
def test_native_component_drain_normalizes_extended_drive_and_unc_paths():
    script = (ROOT / "desktop" / "src-tauri" / "windows" / "native-component-drain.ps1").read_text(
        encoding="utf-8"
    )
    start = script.index("function Get-NormalizedProcessPath")
    end = script.index("$deadline =", start)
    normalize_function = script[start:end]
    command = f"""
{normalize_function}
@(
    $env:AIGUARD_TEST_EXTENDED_DRIVE,
    $env:AIGUARD_TEST_EXTENDED_UNC,
    $env:AIGUARD_TEST_PLAIN_UNC
) | ForEach-Object {{ Get-NormalizedProcessPath $_ }}
"""
    environment = os.environ.copy()
    environment.update(
        {
            "AIGUARD_TEST_EXTENDED_DRIVE": r"\\?\C:\AI Guard\desktop.exe",
            "AIGUARD_TEST_EXTENDED_UNC": (r"\\?\UNC\server\share\AI Guard\desktop.exe"),
            "AIGUARD_TEST_PLAIN_UNC": r"\\server\share\AI Guard\desktop.exe",
        }
    )
    result = subprocess.run(
        [
            str(
                Path(os.environ["SystemRoot"])
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            ),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        r"C:\AI Guard\desktop.exe",
        r"\\server\share\AI Guard\desktop.exe",
        r"\\server\share\AI Guard\desktop.exe",
    ]


def test_portable_package_rejects_unmarked_or_nonempty_outputs(tmp_path):
    desktop = tmp_path / "desktop.exe"
    broker = tmp_path / "broker.exe"
    backend = tmp_path / "backend.exe"
    _component(desktop)
    _component(broker, marker=True)
    _component(backend)
    with pytest.raises(ValueError, match="marker"):
        package.assemble_package(
            tmp_path / "first",
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )

    _component(desktop, marker=True)
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "existing").write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        package.assemble_package(
            output,
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )


def test_portable_package_rejects_legacy_desktop_runtime_authority(tmp_path):
    desktop = tmp_path / "desktop.exe"
    broker = tmp_path / "broker.exe"
    backend = tmp_path / "backend.exe"
    _component(desktop, marker=True)
    with desktop.open("ab") as handle:
        handle.write(b"http://127.0.0.1:8000")
    _component(broker, marker=True)
    _component(backend)

    with pytest.raises(ValueError, match="legacy runtime authority"):
        package.assemble_package(
            tmp_path / "package",
            desktop=desktop,
            broker=broker,
            backend=backend,
            version="2.5.0",
        )


def test_packaged_smoke_bounds_repetition_count(tmp_path):
    with pytest.raises(ValueError, match="repetitions"):
        smoke_package.smoke(tmp_path, timeout=1, repetitions=0)
    with pytest.raises(ValueError, match="repetitions"):
        smoke_package.smoke(tmp_path, timeout=1, repetitions=21)


def test_packaged_smoke_requires_both_appimage_inputs(tmp_path):
    with pytest.raises(ValueError, match="requires both"):
        smoke_package.smoke(tmp_path, timeout=1, finalized_appimage=tmp_path / "x.AppImage")
    with pytest.raises(ValueError, match="requires both"):
        smoke_package.smoke(tmp_path, timeout=1, appimage_layout=tmp_path / "squashfs-root")


def _appimage_smoke_layout(root: Path) -> tuple[Path, dict[str, Path]]:
    package_dir = root / "usr" / "bin"
    package_dir.mkdir(parents=True)
    paths = {
        "desktop": package_dir / "desktop",
        "broker": package_dir / "aiguard-native-broker",
        "backend": package_dir / "aiguard",
    }
    for path in paths.values():
        path.write_bytes(path.name.encode("ascii"))
        path.chmod(0o755)
    manifest = {
        "product_version": "2.5.0",
        "clients": [
            {
                "role": "desktop",
                "path": paths["desktop"].name,
                "sha256": hashlib.sha256(paths["desktop"].read_bytes()).hexdigest(),
            }
        ],
        "broker": {
            "path": paths["broker"].name,
            "sha256": hashlib.sha256(paths["broker"].read_bytes()).hexdigest(),
        },
        "backend": {
            "path": paths["backend"].name,
            "sha256": hashlib.sha256(paths["backend"].read_bytes()).hexdigest(),
        },
    }
    (package_dir / "native-components-v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    apprun = root / "AppRun"
    apprun.write_bytes(b"#!/bin/sh\nexec usr/bin/desktop\n")
    apprun.chmod(0o755)
    return package_dir, paths


def test_package_smoke_verifies_every_native_host_client_digest(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {
        "desktop": package_dir / "desktop",
        "extension": package_dir / "aiguard-chrome-native-host",
        "maintenance": package_dir / "aiguard-native-host-manager",
        "broker": package_dir / "aiguard-native-broker",
        "backend": package_dir / "aiguard",
    }
    for path in paths.values():
        path.write_bytes(path.name.encode("ascii"))
    manifest = {
        "clients": [
            {
                "role": role,
                "path": paths[role].name,
                "sha256": hashlib.sha256(paths[role].read_bytes()).hexdigest(),
            }
            for role in ("desktop", "extension", "maintenance")
        ],
        "broker": {
            "path": paths["broker"].name,
            "sha256": hashlib.sha256(paths["broker"].read_bytes()).hexdigest(),
        },
        "backend": {
            "path": paths["backend"].name,
            "sha256": hashlib.sha256(paths["backend"].read_bytes()).hexdigest(),
        },
        "native_host": {},
    }
    (package_dir / "native-components-v1.json").write_text(json.dumps(manifest), encoding="utf-8")

    smoke_package._manifest_components(package_dir)
    paths["extension"].write_bytes(b"tampered adapter")

    with pytest.raises(RuntimeError, match="component verification"):
        smoke_package._manifest_components(package_dir)


def test_appimage_smoke_attests_exact_independent_layout_and_candidate(tmp_path):
    layout = tmp_path / "squashfs-root"
    package_dir, paths = _appimage_smoke_layout(layout)
    candidate = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    candidate.write_bytes(b"finalized appimage")
    candidate.chmod(0o755)

    attestation = smoke_package._attest_appimage_inputs(
        package_dir,
        appimage_layout=layout,
        finalized_appimage=candidate,
    )

    assert attestation.package == package_dir.resolve()
    assert attestation.layout == layout.resolve()
    assert attestation.candidate == candidate.resolve()
    assert attestation.product_version == "2.5.0"
    assert attestation.extracted_name == (
        smoke_package.APPIMAGE_EXTRACTED_PREFIX
        + hashlib.md5(candidate.read_bytes(), usedforsecurity=False).hexdigest()
    )
    assert attestation.component_digests == {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
    }
    assert (
        attestation.manifest_digest
        == hashlib.sha256((package_dir / "native-components-v1.json").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "wrong-package",
        "candidate-name",
        "candidate-link",
        "apprun-link",
        "apprun-mode",
        "native-start-marker",
    ],
)
def test_appimage_smoke_rejects_unattested_paths(tmp_path, monkeypatch, invalid):
    layout = tmp_path / "squashfs-root"
    package_dir, _paths = _appimage_smoke_layout(layout)
    candidate = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    candidate.write_bytes(b"finalized appimage")
    candidate.chmod(0o755)
    supplied_package = package_dir
    if invalid == "wrong-package":
        supplied_package = tmp_path / "other"
        supplied_package.mkdir()
    elif invalid == "candidate-name":
        candidate = candidate.with_suffix(".bin")
        candidate.write_bytes(b"finalized appimage")
        candidate.chmod(0o755)
    elif invalid in {"candidate-link", "apprun-link"}:
        linked = candidate if invalid == "candidate-link" else layout / "AppRun"
        original = smoke_package._is_link_or_reparse
        monkeypatch.setattr(
            smoke_package,
            "_is_link_or_reparse",
            lambda path: Path(path) == linked or original(path),
        )
    elif invalid == "native-start-marker":
        (package_dir / smoke_package.SMOKE_NATIVE_START).write_bytes(b"started")
    else:
        if os.name == "nt":
            pytest.skip("Windows does not preserve Unix executable mode bits")
        (layout / "AppRun").chmod(0o644)

    with pytest.raises(ValueError, match="invalid AppImage smoke input"):
        smoke_package._attest_appimage_inputs(
            supplied_package,
            appimage_layout=layout,
            finalized_appimage=candidate,
        )


def test_appimage_smoke_verifies_live_runtime_extraction_against_attestation(tmp_path):
    attested_layout = tmp_path / "attested" / "squashfs-root"
    package_dir, _paths = _appimage_smoke_layout(attested_layout)
    candidate = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    candidate.write_bytes(b"finalized appimage")
    candidate.chmod(0o755)
    attestation = smoke_package._attest_appimage_inputs(
        package_dir,
        appimage_layout=attested_layout,
        finalized_appimage=candidate,
    )
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    live_layout = private_root / attestation.extracted_name
    shutil.copytree(attested_layout, live_layout)

    component_paths, verified_layout = smoke_package._verified_live_appimage(
        live_layout, attestation
    )

    assert verified_layout == live_layout
    assert component_paths == {
        name: live_layout / "usr" / "bin" / path.name for name, path in _paths.items()
    }


@pytest.mark.parametrize(
    "invalid", ["name", "link", "component-link", "component-drift", "manifest-drift"]
)
def test_appimage_smoke_rejects_unverified_live_runtime_extraction(tmp_path, monkeypatch, invalid):
    attested_layout = tmp_path / "attested" / "squashfs-root"
    package_dir, _paths = _appimage_smoke_layout(attested_layout)
    candidate = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    candidate.write_bytes(b"finalized appimage")
    candidate.chmod(0o755)
    attestation = smoke_package._attest_appimage_inputs(
        package_dir,
        appimage_layout=attested_layout,
        finalized_appimage=candidate,
    )
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    live_layout = private_root / attestation.extracted_name
    shutil.copytree(attested_layout, live_layout)
    if invalid == "name":
        wrong = private_root / f"{smoke_package.APPIMAGE_EXTRACTED_PREFIX}{'b' * 32}"
        live_layout.rename(wrong)
        live_layout = wrong
    elif invalid == "link":
        original = smoke_package._is_link_or_reparse
        monkeypatch.setattr(
            smoke_package,
            "_is_link_or_reparse",
            lambda path: Path(path) == live_layout / "AppRun" or original(path),
        )
    elif invalid == "component-link":
        linked = live_layout / "usr" / "bin" / "aiguard"
        original = smoke_package._is_link_or_reparse
        monkeypatch.setattr(
            smoke_package,
            "_is_link_or_reparse",
            lambda path: Path(path) == linked or original(path),
        )
    elif invalid == "component-drift":
        (live_layout / "usr" / "bin" / "aiguard").write_bytes(b"drift")
    else:
        (live_layout / "usr" / "bin" / "native-components-v1.json").write_text(
            "{}", encoding="utf-8"
        )

    with pytest.raises(RuntimeError, match="live AppImage verification failed"):
        smoke_package._verified_live_appimage(live_layout, attestation)


def test_appimage_smoke_environment_is_private_and_scrubs_injection(monkeypatch, tmp_path):
    for name in (
        "APPDIR",
        "APPIMAGE",
        "APPIMAGE_EXTRACT_AND_RUN",
        "ARGV0",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "NO_CLEANUP",
        "PYTHONHOME",
        "PYTHONPATH",
        "TARGET_APPIMAGE",
        "TMPDIR",
    ):
        monkeypatch.setenv(name, "must-not-cross")
    monkeypatch.setenv("DISPLAY", ":99")
    root = tmp_path / "private"
    directories = {
        name: root / name
        for name in ("evidence", "home", "config", "cache", "data", "state", "runtime")
    }

    outer = smoke_package._appimage_environment(root, directories)

    assert outer["DISPLAY"] == ":99"
    assert outer["TMPDIR"] == str(root)
    assert outer["NO_CLEANUP"] == "1"
    assert outer["AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT"] == str(directories["evidence"])
    if smoke_package.sys.platform.startswith("linux"):
        assert outer["WEBKIT_DISABLE_COMPOSITING_MODE"] == "1"
        assert outer["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"
    for name in (
        "APPDIR",
        "APPIMAGE",
        "APPIMAGE_EXTRACT_AND_RUN",
        "ARGV0",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "PYTHONHOME",
        "PYTHONPATH",
        "TARGET_APPIMAGE",
    ):
        assert name not in outer

    layout = root / "appimage_extracted_deadbeef"
    candidate = tmp_path / "final.AppImage"
    warm = smoke_package._appimage_environment(
        root, directories, layout=layout, candidate=candidate
    )
    assert warm["APPDIR"] == str(layout)
    assert warm["APPIMAGE"] == str(candidate)
    assert warm["ARGV0"] == str(candidate)
    assert warm["TMPDIR"] == outer["TMPDIR"]
    assert warm["HOME"] == outer["HOME"]
    assert warm["AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT"] == outer["AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT"]
    if smoke_package.sys.platform.startswith("linux"):
        assert warm["WEBKIT_DISABLE_COMPOSITING_MODE"] == "1"
        assert warm["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"
    assert "NO_CLEANUP" not in warm

    fuse_outer = smoke_package._appimage_environment(root, directories, retain_outer_layout=False)
    assert "NO_CLEANUP" not in fuse_outer
    assert "APPIMAGE_EXTRACT_AND_RUN" not in fuse_outer


def test_appimage_smoke_execution_mode_describes_the_paths_actually_run():
    assert smoke_package._appimage_execution_mode("extract", 1) == "outer_appimage_extract_and_run"
    assert (
        smoke_package._appimage_execution_mode("extract", 2)
        == "outer_appimage_extract_and_run_then_verified_apprun"
    )
    assert smoke_package._appimage_execution_mode("fuse", 1) == "outer_appimage_fuse"
    assert smoke_package._appimage_outer_command(Path("candidate.AppImage"), "fuse") == [
        "candidate.AppImage"
    ]
    assert smoke_package._appimage_outer_command(Path("candidate.AppImage"), "extract") == [
        "candidate.AppImage",
        "--appimage-extract-and-run",
    ]
    with pytest.raises(ValueError, match="FUSE AppImage smoke requires one repetition"):
        smoke_package._validate_appimage_outer_mode("fuse", 2)


@pytest.mark.parametrize("invalid", ["link", "nonregular", "oversized", "malformed"])
def test_packaged_smoke_rejects_unsafe_marker_files(tmp_path, monkeypatch, invalid):
    marker = tmp_path / smoke_package.SMOKE_READY
    marker.write_bytes(b"ready")
    if invalid == "link":
        monkeypatch.setattr(
            smoke_package,
            "_is_link_or_reparse",
            lambda path: Path(path) == marker,
        )
    elif invalid == "nonregular":
        marker.unlink()
        marker.mkdir()
    elif invalid == "oversized":
        marker.write_bytes(b"readyx")
    else:
        marker.write_bytes(b"other")

    assert not smoke_package._fixed_marker(marker, b"ready")


@pytest.mark.parametrize("leaked_component", [False, True])
def test_appimage_smoke_outer_then_verified_apprun_uses_one_private_layout(
    tmp_path, monkeypatch, leaked_component
):
    attested_layout = tmp_path / "attested" / "squashfs-root"
    package_dir, _paths = _appimage_smoke_layout(attested_layout)
    candidate = tmp_path / "AI_Guard_2.5.0_amd64.AppImage"
    candidate.write_bytes(b"finalized appimage")
    candidate.chmod(0o755)
    attestation = smoke_package._attest_appimage_inputs(
        package_dir,
        appimage_layout=attested_layout,
        finalized_appimage=candidate,
    )
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    identity = (root.lstat().st_dev, root.lstat().st_ino)
    directories = {}
    for name in ("evidence", "home", "config", "cache", "data", "state", "runtime"):
        directories[name] = root / name
        directories[name].mkdir(mode=0o700)
    live_layout = root / attestation.extracted_name
    launches = []

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.returncode = 0

        def poll(self):
            return self.returncode

    def popen(command, **kwargs):
        launches.append((command, kwargs))
        if len(launches) == 1:
            shutil.copytree(attested_layout, live_layout)
        stable_package = (
            directories["data"] / "aiguard" / "native-host-v1" / attestation.product_version
        )
        if stable_package.exists():
            shutil.rmtree(stable_package)
        stable_package.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(live_layout / "usr" / "bin", stable_package)
        (directories["evidence"] / smoke_package.SMOKE_NATIVE_START).write_bytes(b"started")
        return FakeProcess(1000 + len(launches))

    monitored = []

    def run_started(process, marker_root, paths, _timeout, **kwargs):
        monitored.append((process, marker_root, paths, kwargs))
        smoke_package._clear_markers(marker_root)
        return (
            1.0,
            dict.fromkeys(smoke_package.EXPECTED_SMOKE_METRICS, 1.0),
            dict.fromkeys(smoke_package.EXPECTED_RESOURCE_METRICS, 1.0),
        )

    natural_checks = []
    recovery_stops = []
    zero_checks = []

    def wait_natural(paths, processes):
        natural_checks.append((paths, processes))
        if leaked_component:
            raise RuntimeError("packaged Desktop left native resources running")

    monkeypatch.setattr(smoke_package, "_appimage_host_supported", lambda: True)
    monkeypatch.setattr(
        smoke_package, "_private_appimage_root", lambda: (root, identity, directories)
    )
    monkeypatch.setattr(smoke_package.subprocess, "Popen", popen)
    monkeypatch.setattr(smoke_package, "_run_started_process", run_started)
    monkeypatch.setattr(smoke_package, "_wait_for_appimage_zero", wait_natural)
    monkeypatch.setattr(
        smoke_package,
        "_stop_process_groups",
        lambda processes: recovery_stops.append(processes),
    )
    monkeypatch.setattr(
        smoke_package,
        "_wait_for_components_zero",
        lambda paths: zero_checks.append(paths) or dict.fromkeys(paths, 0),
    )

    if leaked_component:
        with pytest.raises(RuntimeError, match="left native resources running"):
            smoke_package._run_appimage_smoke(attestation, timeout=2, repetitions=2)
        assert len(recovery_stops) == 1
        assert len(zero_checks) == 1
        assert not root.exists()
        return

    result = smoke_package._run_appimage_smoke(attestation, timeout=2, repetitions=2)

    assert result["execution_mode"] == "outer_appimage_extract_and_run_then_verified_apprun"
    assert launches[0][0] == [str(candidate.resolve()), "--appimage-extract-and-run"]
    assert launches[1][0] == [str(live_layout / "AppRun")]
    assert all(kwargs["start_new_session"] is True for _command, kwargs in launches)
    assert "APPIMAGE_EXTRACT_AND_RUN" not in launches[0][1]["env"]
    assert launches[0][1]["env"]["NO_CLEANUP"] == "1"
    assert launches[1][1]["env"]["APPDIR"] == str(live_layout)
    assert launches[1][1]["env"]["APPIMAGE"] == str(candidate.resolve())
    stable_package = (
        directories["data"] / "aiguard" / "native-host-v1" / attestation.product_version
    )
    expected_stable_paths = {name: stable_package / path.name for name, path in _paths.items()}
    assert [entry[2] for entry in monitored] == [expected_stable_paths, expected_stable_paths]
    assert [entry[0] for entry in natural_checks] == [expected_stable_paths]
    assert recovery_stops == []
    assert zero_checks == []
    assert not root.exists()


def test_packaged_smoke_accepts_only_webview_boundary_metrics():
    assert smoke_package.EXPECTED_SMOKE_METRICS == frozenset(
        {
            "health_connect_ms",
            "analyze_ms",
            "sanitize_ms",
            "continuation_ms",
            "copy_ms",
            "reidentify_ms",
            "report_ms",
            "pdf_ms",
            "audit_ms",
            "cleanup_ms",
            "workflow_ms",
        }
    )


def test_packaged_smoke_resource_sampling_fails_closed_without_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)

    with pytest.raises(RuntimeError, match="resource sampling unavailable"):
        smoke_package._sample_resources({})


def test_resource_sampling_reads_expensive_metrics_only_for_attested_paths(tmp_path, monkeypatch):
    paths = {
        name: tmp_path / executable
        for name, executable in {
            "desktop": "desktop",
            "broker": "aiguard-native-broker",
            "backend": "aiguard",
        }.items()
    }
    unrelated = tmp_path / "elsewhere" / paths["desktop"].name
    metric_reads = []

    class ProcessError(Exception):
        pass

    class FakeMemoryInfo:
        rss = 2 * 1024 * 1024

    class FakeProcess:
        def __init__(self, executable, *, fail=False):
            self.info = {"exe": str(executable)}
            self.fail = fail

        def memory_info(self):
            metric_reads.append((Path(self.info["exe"]), "memory"))
            if self.fail:
                raise ProcessError("process exited")
            return FakeMemoryInfo()

        def num_handles(self):
            metric_reads.append((Path(self.info["exe"]), "handles"))
            return 3

        def num_fds(self):
            metric_reads.append((Path(self.info["exe"]), "handles"))
            return 3

    class FakePsutil:
        Error = ProcessError

        @staticmethod
        def process_iter(attributes):
            assert attributes == ["exe"]
            return [
                FakeProcess(unrelated),
                FakeProcess(paths["desktop"], fail=True),
                *(FakeProcess(path) for path in paths.values()),
            ]

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)

    sampled = smoke_package._sample_resources(paths)

    assert sampled == {
        "desktop_rss_mb": 2.0,
        "broker_rss_mb": 2.0,
        "backend_rss_mb": 2.0,
        "desktop_handles": 3.0,
        "broker_handles": 3.0,
        "backend_handles": 3.0,
    }
    assert not any(path == unrelated for path, _metric in metric_reads)


def test_packaged_smoke_requires_complete_finite_positive_resource_evidence():
    complete = dict.fromkeys(smoke_package.EXPECTED_RESOURCE_METRICS, 1.23456)
    assert smoke_package._validated_resource_peaks(complete) == dict.fromkeys(
        sorted(smoke_package.EXPECTED_RESOURCE_METRICS), 1.235
    )

    for invalid in (
        {},
        {**complete, "desktop_rss_mb": 0.0},
        {**complete, "desktop_rss_mb": float("nan")},
        {**complete, "unexpected": 1.0},
    ):
        with pytest.raises(RuntimeError, match="resource evidence unavailable"):
            smoke_package._validated_resource_peaks(invalid)


def test_packaged_smoke_failure_diagnostics_are_a_fixed_nonpayload_enum():
    assert smoke_package.EXPECTED_FAILURE_STAGES == frozenset(
        {
            "app_build",
            "app_exit",
            "app_ready",
            "app_runtime",
            "appimage_desktop",
            "appimage_environment",
            "appimage_executable",
            "appimage_exec",
            "appimage_manifest",
            "appimage_repair",
            "appimage_root",
            "health",
            "ready_signal",
            "analyze",
            "sanitize",
            "continuation",
            "copy",
            "reidentify",
            "report",
            "pdf",
            "audit",
            "cleanup",
            "finish",
            "upgrade_invalidation",
            "bootstrap_import",
            "bootstrap_eval",
            "webview_process",
        }
    )


def test_packaged_smoke_never_projects_an_untrusted_failure_marker(tmp_path):
    marker = tmp_path / smoke_package.SMOKE_FAILURE
    marker.write_text("private provider body", encoding="utf-8")

    assert smoke_package._fixed_failure_stage(marker) is None

    marker.write_text("sanitize", encoding="utf-8")
    assert smoke_package._fixed_failure_stage(marker) == "sanitize"


def test_packaged_smoke_stops_on_fixed_runtime_failure(tmp_path):
    marker = tmp_path / smoke_package.SMOKE_FAILURE
    marker.write_bytes(b"webview_process")

    with pytest.raises(
        RuntimeError,
        match="packaged Desktop smoke failed at fixed stage: webview_process",
    ):
        smoke_package._raise_for_smoke_failure(marker)

    marker.write_bytes(b"untrusted")
    with pytest.raises(RuntimeError, match="smoke failure evidence invalid"):
        smoke_package._raise_for_smoke_failure(marker)


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [
        (0, "packaged Desktop smoke evidence unavailable"),
        (75, "packaged Desktop smoke bootstrap rejected"),
        (1, "packaged Desktop smoke process failed"),
        (-11, "packaged Desktop smoke process terminated"),
    ],
)
def test_packaged_smoke_projects_only_fixed_missing_evidence_categories(returncode, expected):
    assert smoke_package._missing_smoke_evidence_error(returncode) == expected


def test_appimage_prestart_waiter_projects_a_fixed_bootstrap_failure(tmp_path):
    marker_root = tmp_path / "evidence"
    marker_root.mkdir()
    (marker_root / smoke_package.SMOKE_FAILURE).write_bytes(b"appimage_manifest")

    class ExitedProcess:
        @staticmethod
        def poll():
            return 75

    with pytest.raises(
        RuntimeError,
        match="packaged Desktop smoke failed at fixed stage: appimage_manifest",
    ):
        smoke_package._wait_for_live_appimage(
            tmp_path / "layout",
            tmp_path / "data",
            marker_root,
            None,
            ExitedProcess(),
            float("inf"),
        )


def test_appimage_prestart_waiter_rechecks_failure_after_process_exit(tmp_path):
    marker_root = tmp_path / "evidence"
    marker_root.mkdir()
    failure_marker = marker_root / smoke_package.SMOKE_FAILURE

    class ExitsAfterFirstMarkerCheck:
        @staticmethod
        def poll():
            failure_marker.write_bytes(b"app_runtime")
            return 1

    with pytest.raises(
        RuntimeError,
        match="packaged Desktop smoke failed at fixed stage: app_runtime",
    ):
        smoke_package._wait_for_live_appimage(
            tmp_path / "layout",
            tmp_path / "data",
            marker_root,
            None,
            ExitsAfterFirstMarkerCheck(),
            float("inf"),
        )


def test_packaged_smoke_scrubs_remote_credentials_and_pins_fake_local_path(monkeypatch):
    for name in (
        "AIFORTHAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AIGUARD_API_KEY",
        "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT",
        "AIGUARD_TOKEN",
        "TOKENMIND_API_KEY",
        "TOKENMIND_BASE_URL",
        "TOKENMIND_ALLOW_HTTP",
        "AIGUARD_FINETUNED_MODEL_DIR",
    ):
        monkeypatch.setenv(name, "must-not-cross")
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "tner")
    monkeypatch.setenv("AIGUARD_PROVIDERS", "pathumma")

    environment = smoke_package._acceptance_environment()

    assert environment["AIGUARD_NER_ENGINE"] == "thainer"
    assert environment["AIGUARD_PROVIDERS"] == "fake"
    assert environment["AIGUARD_DESKTOP_PACKAGE_SMOKE"] == "1"
    if smoke_package.sys.platform.startswith("linux"):
        assert environment["WEBKIT_DISABLE_COMPOSITING_MODE"] == "1"
        assert environment["WEBKIT_DISABLE_DMABUF_RENDERER"] == "1"
    for name in (
        "AIFORTHAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AIGUARD_API_KEY",
        "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT",
        "AIGUARD_TOKEN",
        "TOKENMIND_API_KEY",
        "TOKENMIND_BASE_URL",
        "TOKENMIND_ALLOW_HTTP",
        "AIGUARD_FINETUNED_MODEL_DIR",
    ):
        assert name not in environment


def test_unix_process_count_matches_full_path_for_long_component_names(tmp_path, monkeypatch):
    expected = tmp_path / "package" / "aiguard-native-broker"
    same_name = tmp_path / "other" / expected.name
    expected.parent.mkdir()
    same_name.parent.mkdir()
    expected.write_bytes(b"expected")
    same_name.write_bytes(b"other")
    current_pid = 101
    process_paths = {
        current_pid: ROOT / ".venv" / "Scripts" / "python.exe",
        202: expected,
        303: same_name,
    }
    commands = []

    def fake_check_output(command, **_kwargs):
        commands.append(command)
        return (
            f"{current_pid} 1000 python\n"
            "202 1000 aiguard-native-\n"
            "303 1000 aiguard-native-\n"
            "404 0 root-worker\n"
        )

    monkeypatch.setattr(smoke_package.sys, "platform", "linux")
    monkeypatch.setattr(smoke_package.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(smoke_package.os, "getpid", lambda: current_pid)
    monkeypatch.setattr(smoke_package.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(
        smoke_package,
        "_unix_executable_path",
        lambda pid: str(process_paths[pid]),
    )

    assert smoke_package._unix_process_count(expected) == 1
    assert commands == [["ps", "-A", "-o", "pid=", "-o", "uid=", "-o", "comm="]]


def test_linux_process_count_skips_uninspectable_unrelated_same_user_process(tmp_path, monkeypatch):
    expected = tmp_path / "aiguard-native-broker"
    expected.write_bytes(b"expected")
    current_pid = 101
    inspected = []

    monkeypatch.setattr(smoke_package.sys, "platform", "linux")
    monkeypatch.setattr(smoke_package.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(smoke_package.os, "getpid", lambda: current_pid)
    monkeypatch.setattr(
        smoke_package.subprocess,
        "check_output",
        lambda *_args, **_kwargs: (f"{current_pid} 1000 python\n202 1000 protected-worker\n"),
    )

    def executable_path(pid):
        inspected.append(pid)
        if pid == current_pid:
            return str(ROOT / ".venv" / "Scripts" / "python.exe")
        raise RuntimeError("Unix process executable inspection unavailable")

    monkeypatch.setattr(smoke_package, "_unix_executable_path", executable_path)

    assert smoke_package._unix_process_count(expected) == 0
    assert inspected == [current_pid]


def test_unix_process_count_fails_closed_when_executable_path_is_unavailable(tmp_path, monkeypatch):
    expected = tmp_path / "aiguard-native-broker"
    expected.write_bytes(b"expected")
    current_pid = 101

    monkeypatch.setattr(smoke_package.sys, "platform", "linux")
    monkeypatch.setattr(smoke_package.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(smoke_package.os, "getpid", lambda: current_pid)
    monkeypatch.setattr(
        smoke_package.subprocess,
        "check_output",
        lambda *_args, **_kwargs: (f"{current_pid} 1000 python\n202 1000 aiguard-native-\n"),
    )

    def executable_path(pid):
        if pid == current_pid:
            return str(ROOT / ".venv" / "Scripts" / "python.exe")
        raise RuntimeError("Unix process executable inspection unavailable")

    monkeypatch.setattr(smoke_package, "_unix_executable_path", executable_path)

    with pytest.raises(RuntimeError, match="executable inspection unavailable"):
        smoke_package._unix_process_count(expected)


def test_unix_process_count_fails_closed_without_inspector_pid(tmp_path, monkeypatch):
    expected = tmp_path / "aiguard-native-broker"
    expected.write_bytes(b"expected")

    monkeypatch.setattr(smoke_package.sys, "platform", "linux")
    monkeypatch.setattr(smoke_package.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(smoke_package.os, "getpid", lambda: 101)
    monkeypatch.setattr(
        smoke_package.subprocess,
        "check_output",
        lambda *_args, **_kwargs: "202 1000 aiguard-native-\n",
    )

    with pytest.raises(RuntimeError, match="current process"):
        smoke_package._unix_process_count(expected)


def test_linux_executable_path_keeps_untruncated_broker_name(monkeypatch):
    expected = "/opt/ai-guard/aiguard-native-broker"
    inspected = []

    def fake_readlink(path):
        inspected.append(path)
        return expected

    monkeypatch.setattr(smoke_package.os, "readlink", fake_readlink)

    assert smoke_package._linux_executable_path(202) == expected
    assert inspected == ["/proc/202/exe"]


def test_macos_executable_path_uses_full_proc_pidpath(monkeypatch):
    expected = b"/Applications/AI Guard.app/Contents/MacOS/aiguard-native-broker"
    inspected = []

    def fake_proc_pidpath(pid, buffer, size):
        inspected.append((pid, size))
        ctypes.memmove(buffer, expected + b"\0", len(expected) + 1)
        return len(expected)

    monkeypatch.setattr(smoke_package, "_macos_proc_pidpath", lambda: fake_proc_pidpath)

    assert smoke_package._macos_executable_path(202) == os.fsdecode(expected)
    assert inspected == [(202, 4096)]


def test_macos_executable_path_treats_vanished_process_as_absent(monkeypatch):
    def fake_proc_pidpath(_pid, _buffer, _size):
        ctypes.set_errno(errno.ESRCH)
        return 0

    monkeypatch.setattr(smoke_package, "_macos_proc_pidpath", lambda: fake_proc_pidpath)

    assert smoke_package._macos_executable_path(202) is None


def test_windows_process_count_requires_exact_installed_executable_path(tmp_path, monkeypatch):
    expected = tmp_path / "installed" / "aiguard-native-broker.exe"
    other = tmp_path / "other" / expected.name
    expected.parent.mkdir()
    other.parent.mkdir()
    expected.write_bytes(b"expected")
    other.write_bytes(b"other")

    class FakeProcess:
        def __init__(self, name, executable):
            self.info = {"name": name, "exe": str(executable) if executable else None}

    class FakePsutil:
        class Error(Exception):
            pass

        NoSuchProcess = Error
        AccessDenied = Error

        @staticmethod
        def process_iter(attributes):
            assert attributes == ["name", "exe"]
            return iter(
                (
                    FakeProcess(expected.name.upper(), expected),
                    FakeProcess(expected.name, other),
                    FakeProcess("aiguard.exe", expected),
                )
            )

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)

    assert smoke_package._windows_process_count(expected) == 1


@pytest.mark.parametrize("failure", ["timeout", "sampler"])
def test_run_desktop_failure_reaps_process_and_removes_markers(tmp_path, monkeypatch, failure):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    marker_root = tmp_path / "markers"
    marker_root.mkdir()
    component_paths = {
        name: package_dir / filename
        for name, filename in {
            "desktop": "desktop.exe",
            "broker": "aiguard-native-broker.exe",
            "backend": "aiguard.exe",
        }.items()
    }
    for path in component_paths.values():
        path.write_bytes(b"synthetic component")

    markers = tuple(
        marker_root / name
        for name in (
            smoke_package.SMOKE_EVIDENCE,
            smoke_package.SMOKE_READY,
            smoke_package.SMOKE_FAILURE,
            smoke_package.SMOKE_INVALIDATED,
            smoke_package.SMOKE_NATIVE_START,
        )
    )
    real_popen = smoke_package.subprocess.Popen
    launched = []

    def fake_popen(*_args, **_kwargs):
        for marker in markers:
            if marker.name != smoke_package.SMOKE_FAILURE:
                marker.write_text("health", encoding="utf-8")
        process = real_popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=smoke_package.subprocess.DEVNULL,
            stdout=smoke_package.subprocess.DEVNULL,
            stderr=smoke_package.subprocess.DEVNULL,
        )
        launched.append(process)
        return process

    monkeypatch.setattr(smoke_package.subprocess, "Popen", fake_popen)
    if failure == "sampler":
        monkeypatch.setattr(
            smoke_package,
            "_sample_resources",
            lambda _paths: (_ for _ in ()).throw(RuntimeError("sampler unavailable")),
        )
        expected_error = "resource sampling unavailable"
        timeout = 2
    else:
        monkeypatch.setattr(
            smoke_package,
            "_sample_resources",
            lambda _paths: dict.fromkeys(smoke_package.EXPECTED_RESOURCE_METRICS, 1.0),
        )
        expected_error = "timed out"
        timeout = 0.05

    with pytest.raises(RuntimeError, match=expected_error):
        smoke_package._run_desktop(
            component_paths["desktop"],
            package_dir,
            marker_root,
            {},
            component_paths,
            timeout,
        )

    assert len(launched) == 1
    assert launched[0].poll() is not None
    assert not any(marker.exists() for marker in markers)


def test_packaged_smoke_process_checks_use_attested_component_paths(tmp_path, monkeypatch):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {
        "desktop": package_dir / "AI Guard",
        "broker": package_dir / "aiguard-native-broker",
        "backend": package_dir / "aiguard",
    }
    for path in paths.values():
        path.write_bytes(path.name.encode("utf-8"))
    manifest = {
        "clients": [
            {
                "role": "desktop",
                "path": paths["desktop"].name,
                "sha256": hashlib.sha256(paths["desktop"].read_bytes()).hexdigest(),
            }
        ],
        "broker": {
            "path": paths["broker"].name,
            "sha256": hashlib.sha256(paths["broker"].read_bytes()).hexdigest(),
        },
        "backend": {
            "path": paths["backend"].name,
            "sha256": hashlib.sha256(paths["backend"].read_bytes()).hexdigest(),
        },
    }
    (package_dir / "native-components-v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    inspected = []

    def process_count(path):
        inspected.append(path)
        return 0

    monkeypatch.setattr(smoke_package, "_process_count", process_count)
    runs = []

    def run_desktop(
        desktop,
        package,
        marker_root,
        environment,
        component_paths,
        timeout,
        **kwargs,
    ):
        runs.append((desktop, package, marker_root, environment, component_paths, timeout))
        assert kwargs == {"ready_callback": None}
        assert marker_root.is_dir()
        assert marker_root != package
        assert package not in marker_root.parents
        assert environment["AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT"] == str(marker_root)
        return (
            1.0,
            dict.fromkeys(smoke_package.EXPECTED_SMOKE_METRICS, 1.0),
            dict.fromkeys(smoke_package.EXPECTED_RESOURCE_METRICS, 1.0),
        )

    monkeypatch.setattr(smoke_package, "_run_desktop", run_desktop)
    package_before = {
        path.relative_to(package_dir): path.read_bytes() for path in package_dir.iterdir()
    }

    smoke_package.smoke(package_dir, timeout=1)

    assert inspected == [paths["broker"], paths["backend"], paths["broker"], paths["backend"]]
    assert len(runs) == 1
    assert not runs[0][2].exists()
    assert {path.relative_to(package_dir): path.read_bytes() for path in package_dir.iterdir()} == (
        package_before
    )


def test_upgrade_invalidation_smoke_attests_old_paths_and_uses_a_separate_result(
    tmp_path, monkeypatch
):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {
        "desktop": package_dir / "desktop",
        "broker": package_dir / "aiguard-native-broker",
        "backend": package_dir / "aiguard",
    }
    for path in paths.values():
        path.write_bytes(path.name.encode("utf-8"))
    manifest = {
        "clients": [
            {
                "role": "desktop",
                "path": paths["desktop"].name,
                "sha256": hashlib.sha256(paths["desktop"].read_bytes()).hexdigest(),
            }
        ],
        "broker": {
            "path": paths["broker"].name,
            "sha256": hashlib.sha256(paths["broker"].read_bytes()).hexdigest(),
        },
        "backend": {
            "path": paths["backend"].name,
            "sha256": hashlib.sha256(paths["backend"].read_bytes()).hexdigest(),
        },
    }
    (package_dir / "native-components-v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(smoke_package, "_process_count", lambda _path: 0)
    callbacks = []
    marker_roots = []

    def run_desktop(
        desktop,
        package,
        marker_root,
        environment,
        component_paths,
        timeout,
        **kwargs,
    ):
        assert desktop == paths["desktop"]
        assert package == package_dir
        assert component_paths == paths
        assert timeout == 120
        assert kwargs["expect_upgrade_invalidation"] is True
        callbacks.append(kwargs["ready_callback"])
        marker_roots.append(marker_root)
        assert environment["AIGUARD_DESKTOP_PACKAGE_SMOKE_RELEASE"] == str(
            marker_root / smoke_package.SMOKE_RELEASE
        )
        kwargs["ready_callback"]()
        return (
            7.0,
            {},
            dict.fromkeys(smoke_package.EXPECTED_RESOURCE_METRICS, 1.0),
        )

    monkeypatch.setattr(smoke_package, "_run_desktop", run_desktop)
    callback_calls = []

    evidence = smoke_package.smoke_upgrade_invalidation(
        package_dir,
        120,
        ready_callback=lambda: callback_calls.append("upgrade"),
    )

    assert len(callbacks) == 1
    assert callback_calls == ["upgrade"]
    assert len(marker_roots) == 1 and not marker_roots[0].exists()
    assert evidence["execution_mode"] == "old_desktop_upgrade_invalidation"
    assert evidence["stale_session_invalidated"] is True
    assert evidence["broker_process_delta"] == 0
    assert evidence["backend_process_delta"] == 0


def test_packaged_smoke_failure_still_waits_for_native_process_baseline(tmp_path, monkeypatch):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    paths = {
        "desktop": package_dir / "desktop.exe",
        "broker": package_dir / "aiguard-native-broker.exe",
        "backend": package_dir / "aiguard.exe",
    }
    for path in paths.values():
        path.write_bytes(path.name.encode("utf-8"))
    manifest = {
        "clients": [
            {
                "role": "desktop",
                "path": paths["desktop"].name,
                "sha256": hashlib.sha256(paths["desktop"].read_bytes()).hexdigest(),
            }
        ],
        "broker": {
            "path": paths["broker"].name,
            "sha256": hashlib.sha256(paths["broker"].read_bytes()).hexdigest(),
        },
        "backend": {
            "path": paths["backend"].name,
            "sha256": hashlib.sha256(paths["backend"].read_bytes()).hexdigest(),
        },
    }
    (package_dir / "native-components-v1.json").write_text(json.dumps(manifest), encoding="utf-8")
    inspected = []

    def process_count(path):
        inspected.append(path)
        return 0

    monkeypatch.setattr(smoke_package, "_process_count", process_count)
    marker_roots = []

    def fail_desktop(_desktop, _package, marker_root, *_args, **_kwargs):
        marker_roots.append(marker_root)
        raise RuntimeError("forced failure")

    monkeypatch.setattr(smoke_package, "_run_desktop", fail_desktop)

    with pytest.raises(RuntimeError, match="forced failure"):
        smoke_package.smoke(package_dir, timeout=1)

    assert inspected == [paths["broker"], paths["backend"], paths["broker"], paths["backend"]]
    assert len(marker_roots) == 1
    assert not marker_roots[0].exists()


def test_ci_and_release_build_both_tauri_native_components():
    for workflow_name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "python scripts/build_sidecar.py" in workflow
        assert "python scripts/build_native_broker.py" in workflow


def test_windows_ci_uses_default_path_and_full_install_upgrade_reinstall_lifecycle():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    windows = workflow.split("  windows-exe-smoke:", 1)[1]

    assert '$productVersion = (Get-Content -LiteralPath "VERSION" -Raw).Trim()' in windows
    assert "$installed.DisplayVersion -ne $productVersion" in windows
    assert (
        "Set-ItemProperty -LiteralPath $uninstallKey -Name DisplayVersion "
        "-Value $predecessorVersion"
    ) in windows
    assert "DisplayVersion -ne $productVersion" in windows
    assert '$installRoot = Join-Path $env:LOCALAPPDATA "AI Guard"' in windows
    assert '$installLocationKey = "HKCU:\\Software\\Teerapat Vatpitak\\AI Guard"' in windows
    assert (
        '$uninstallKey = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AI Guard"'
        in windows
    )
    assert "if (Test-Path -LiteralPath $uninstallKey)" in windows
    assert '(Get-Item -LiteralPath $installLocationKey).GetValue("")' in windows
    assert "if ($rememberedRoot -and $rememberedRoot -ne $installRoot)" in windows
    assert "InstallLocation.Trim('\"')" in windows
    assert "if ($registeredRoot -ne $installRoot -or $rememberedRoot -ne $installRoot)" in windows
    assert "NSIS installer did not use the default Desktop install root" in windows
    assert '"/D=$customLockProbeRoot"' in windows
    assert '"clean-install"' in windows
    assert '"repair"' in windows
    assert '"deterministic-predecessor-upgrade"' in windows
    assert '"uninstall"' in windows
    assert '"reinstall"' in windows
    assert '"final-cleanup"' in windows
    assert '"concurrent-transaction-rejected"' in windows
    assert '"foreign-repair-rejected"' in windows
    assert '"interrupted-package-retry"' in windows
    assert '"interrupted-uninstall-retry"' in windows
    assert "function Assert-PackageLockEnforced" in windows
    assert "[System.IO.FileShare]::None" in windows
    assert "$packageLockPath = Join-Path $env:LOCALAPPDATA" in windows
    assert "distinct-root NSIS package transaction was not rejected" in windows
    assert "blocked distinct-root NSIS transaction created package state" in windows
    assert "custom_root_state = $customRootState" in windows
    assert '"empty_directory"' in windows
    assert "[System.IO.Directory]::Delete($customLockProbeRoot, $false)" in windows
    assert "distinct-root package-lock probe cleanup was unsafe" in windows
    assert "package-lock-contention.json" in windows
    assert 'Write-RegistrationEvidence "present" "lock-rejection-registration-present"' in windows
    assert "blocked package transactions changed default product registration" in windows
    assert "fresh installer process did not complete the retained transaction" in windows
    assert windows.count("Invoke-ExactInstaller") == 5  # declaration + four lifecycle calls
    assert windows.count("Invoke-ExactUninstaller") == 3  # declaration + two lifecycle calls
    assert "NSIS uninstall left the product registration" in windows
    assert "NSIS installer left the cross-session package lock" in windows
    assert "NSIS uninstaller left the cross-session package lock" in windows
    assert '"retained_default_path_preference"' in windows
    assert "final-registry-state.json" in windows
    assert '$cleanupFailures.Add("install-location-presence")' in windows
    assert '$cleanupFailures.Add("install-location-restore")' in windows
    assert "residual-install-tree.json" in windows
    assert "failure-classification.json" in windows
    assert "if: always()" in windows
    assert "installer-sha256.txt" in windows
    assert "process-owner-classification.json" in windows
    assert "token_owner_differs_from_user" in windows
    assert "component-sha256" in windows
    assert 'Invoke-Smoke "reinstall"' in windows
    assert 'Write-RegistrationEvidence "absent" "final-registration-absent"' in windows


def test_cross_platform_workflow_builds_and_smokes_native_packages():
    workflow = (ROOT / ".github" / "workflows" / "smoke-crossplatform.yml").read_text(
        encoding="utf-8"
    )

    assert 'branches: ["**"]' in workflow
    assert "npm run tauri -- build --bundles app" in workflow
    assert "npm run tauri -- build --bundles deb,appimage" in workflow
    placeholder_command = "python scripts/prepare_desktop_native_package.py --build-placeholders"
    assert workflow.count(placeholder_command) == 1
    placeholder_index = workflow.index(placeholder_command)
    assert workflow.index("python scripts/build_native_broker.py") < placeholder_index
    assert placeholder_index < workflow.index("npm run tauri -- build --bundles app")
    assert placeholder_index < workflow.index("npm run tauri -- build --bundles deb,appimage")
    appimage_build_index = workflow.index("npm run tauri -- build --bundles deb,appimage")
    backend_preserve_index = workflow.index("Preserve the exact pre-linuxdeploy AppImage backend")
    assert workflow.index("python scripts/build_sidecar.py") < backend_preserve_index
    assert backend_preserve_index < appimage_build_index
    assert 'source="desktop/src-tauri/binaries/aiguard-$triple"' in workflow
    assert 'preserved="$RUNNER_TEMP/aiguard-appimage-backend"' in workflow
    assert '--appimage-backend-source "$RUNNER_TEMP/aiguard-appimage-backend"' in workflow
    appimage_finalize = "scripts/prepare_desktop_native_package.py --finalize-appimage"
    assert appimage_finalize in workflow
    appimage_finalize_index = workflow.index(appimage_finalize)
    assert (
        appimage_build_index
        < appimage_finalize_index
        < workflow.index('"$GITHUB_WORKSPACE/$appimage" --appimage-extract')
    )
    assert "linuxdeploy-plugin-appimage-x86_64.AppImage" in workflow
    assert package.APPIMAGE_PLUGIN_SHA256["x86_64"] in workflow
    assert "releases/assets/497460911" in workflow
    assert "releases/download/continuous" not in workflow
    assert "find \"$appimage_root\" -maxdepth 1 -type d -name '*.AppDir'" in workflow
    assert "Contents/MacOS" in workflow
    assert "dpkg-deb -x" in workflow
    assert "--appimage-extract" in workflow
    assert workflow.count("scripts/smoke_desktop_native_package.py") >= 2
    assert "scripts/smoke_live_deb_upgrade.py" in workflow
    linux_smoke_prefix = "xvfb-run -a -e /dev/stderr dbus-run-session -- sh -c"
    direct_inner_smoke = (
        "'python scripts/smoke_desktop_native_package.py /usr/bin --repetitions 2 > \"$1\"'"
    )
    appimage_inner_smoke = (
        '\'python scripts/smoke_desktop_native_package.py "$1" --repetitions 2 '
        '--finalized-appimage "$3" --appimage-layout "$4" > "$2"\''
    )
    assert "dbus-daemon" in workflow
    assert workflow.count(linux_smoke_prefix) >= 6
    assert "dbus-run-session -- xvfb-run" not in workflow
    assert workflow.count(direct_inner_smoke) >= 2
    assert workflow.count(appimage_inner_smoke) == 1
    assert '"$GITHUB_WORKSPACE/$appimage" "$extracted_appimage/squashfs-root"' in workflow
    assert workflow.count('sudo dpkg -i "$deb"') >= 2
    assert workflow.count('sudo dpkg -r "$deb_name"') >= 2
    assert "aiguard-native-host-manager remove deb" in workflow
    assert workflow.count('deb-prerm.sh" remove') == 2
    assert "interrupted-prerm-recovery" in workflow
    for phase in (
        "deb-interrupted-remove-manager",
        "deb-interrupted-remove-first-prerm",
        "deb-interrupted-remove-second-prerm",
        "deb-interrupted-remove-reinstall",
        "deb-interrupted-remove-final-remove",
    ):
        assert f"record_phase {phase}" in workflow
    interrupted_remove = workflow.split("record_phase deb-interrupted-remove-manager", 1)[1].split(
        "record_phase appimage-register", 1
    )[0]
    assert interrupted_remove.count("timeout --signal=TERM --kill-after=5s 60s") == 3
    assert "interrupted DEB retry left a product runtime root" in workflow
    assert '"$GITHUB_WORKSPACE/$appimage" --register-native-host' in workflow
    assert '"$GITHUB_WORKSPACE/$appimage" --unregister-native-host' in workflow
    assert "appimage-lease-contention" in workflow
    assert '"$stable_root/aiguard-native-host-manager" repair appimage' in workflow
    assert 'test "$contender_status" = 75' in workflow
    assert "fingerprint_stable_root" in workflow
    assert "stable_root_unchanged" in workflow
    assert "registration_unchanged" in workflow
    assert "timeout --signal=TERM --kill-after=5s 60s" in workflow
    assert "timeout --signal=TERM --kill-after=2s 10s" in workflow
    assert "repair_one" not in workflow
    assert "repair_two" not in workflow
    assert "last-started-phase.json" in workflow
    assert "Require complete exact Linux evidence on success" in workflow
    assert 'grep -Fxq \'{"phase":"complete"}\'' in workflow
    assert "if: always() && matrix.os == 'ubuntu-latest'" in workflow
    assert workflow.count("scripts/verify_native_host_registration.py") >= 12
    smoke_source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert '[str(candidate), "--appimage-extract-and-run"]' in smoke_source
    assert '[str(live_layout / "AppRun")]' in smoke_source
    assert "--appimage-outer-mode fuse" in workflow
    assert '"status":"unavailable_on_runner"' in workflow
    assert "appimage-fuse-smoke-evidence.json" in workflow
    assert "macos-reinstall-smoke-evidence.json" in workflow
    assert "deb-reinstall-smoke-evidence.json" in workflow
    assert "appimage-reinstall-smoke-evidence.json" in workflow
    assert "appimage-outer-final-registration-absent.json" in workflow
    outer_smoke = workflow.index("--appimage-outer-mode fuse")
    outer_cleanup = workflow.index("appimage-outer-final-registration-absent.json")
    assert outer_smoke < outer_cleanup
    assert workflow.count('test ! -e "/tmp/aiguard-native-broker-$(id -u)-v1"') >= 2
    assert "AppImage outer smoke cleanup left a product runtime root" in workflow
    assert "xvfb-run -a python" not in workflow
    assert "AI-Guard-macos-tested-app.tar.gz" in workflow
    assert "AI-Guard-linux-tested-packages.tar.gz" in workflow
    assert 'tar -C "$(dirname "$relocated")" -czf' in workflow
    assert 'tar -czf "$archive" -C "$deb_root"' in workflow
    mac_upload = workflow.split("Upload the exact tested macOS app", 1)[1].split(
        "Build the feature-gated Linux", 1
    )[0]
    linux_upload = workflow.split("Upload the exact tested Linux packages", 1)[1]
    assert "AI Guard.app" not in mac_upload
    assert "*.AppImage" not in linux_upload
    assert "*.deb" not in linux_upload
    assert "--no-bundle" not in workflow


def test_tagged_installer_publication_uses_the_owner_authorized_release_path():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "blocked-until-owner-release-preparation" not in workflow
    assert "release preparation has not been authorized" not in workflow
    assert "blocked-until-phase-8-slice-6" not in workflow
    assert "native component manifest is not installed" not in workflow
    assert "build:\n    needs: preflight" in workflow
    assert "checksums-and-attest:\n" in workflow
    assert "needs: build" in workflow


def test_release_workflow_finalizes_and_resigns_appimage_before_upload():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    linux_tools = (ROOT / "scripts" / "fetch_tauri_linux_tools.py").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "candidate_sha:" in workflow
    assert "Verify the exact candidate commit and clean tree" in workflow
    assert "AIGUARD_EXTENSION_IDENTITY" in workflow
    assert "python scripts/prewarm_ner.py" in workflow
    assert "python scripts/prepare_desktop_native_package.py --build-placeholders" in workflow
    assert "linuxdeploy-plugin-appimage-x86_64.AppImage" in workflow
    assert "scripts/fetch_tauri_linux_tools.py" in workflow
    assert package.APPIMAGE_PLUGIN_SHA256["x86_64"] in linux_tools
    assert "releases/assets/497460911" in linux_tools
    assert "tauriScript: python ../scripts/release_tauri_build.py" in workflow
    assert "release_tauri_build.py" in workflow
    assert "extract_release_notes.py" in workflow
    assert "python scripts/stage_release_candidate_assets.py" in workflow
    assert workflow.count("release-candidate-assets/*") == 3
    assert "Create the exact candidate artifact manifest" in workflow
    assert "create_release_candidate_manifest.py" in workflow
    assert "if: github.event_name == 'push'" in workflow


def test_ci_packages_the_exact_production_extension_candidate():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "extension-package:" in workflow
    extension_job = workflow.split("  extension-package:", 1)[1].split("\n  pytest:", 1)[0]
    assert "python scripts/package_extension.py" in extension_job
    assert "config/chrome-extension-identity.json" in extension_job
    assert "aiguard-extension-${{ github.sha }}" in extension_job
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in extension_job
