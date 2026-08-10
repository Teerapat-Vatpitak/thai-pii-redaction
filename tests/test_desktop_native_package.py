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
import sys
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
        "manifest": package_dir / package.MANIFEST_NAME,
    }
    _component(paths["desktop"], marker=True)
    _component(paths["broker"], marker=True)
    _component(paths["backend"])
    paths["manifest"].write_text("{}\n", encoding="utf-8")
    return appdir, paths


def test_finalize_appimage_attests_post_linuxdeploy_bytes_before_atomic_replace(
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
        == hashlib.sha256(paths["backend"].read_bytes()).hexdigest()
    )


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
    ]
    assert base["build"]["beforeBundleCommand"] == (
        "python ../scripts/prepare_desktop_native_package.py --bundle-manifest"
    )
    windows_source = "binaries/native-components-v1.nsis.json"
    assert windows == {"bundle": {"resources": {windows_source: "native-components-v1.json"}}}
    macos_source = "binaries/native-components-v1.macos.json"
    assert macos == {
        "bundle": {"macOS": {"files": {"MacOS/native-components-v1.json": macos_source}}}
    }
    assert linux == {
        "bundle": {
            "linux": {
                "deb": {
                    "files": {
                        "/usr/bin/native-components-v1.json": (
                            "binaries/native-components-v1.deb.json"
                        )
                    }
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
        "clients": [
            {
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
    assert "NO_CLEANUP" not in warm


def test_appimage_smoke_execution_mode_describes_the_paths_actually_run():
    assert smoke_package._appimage_execution_mode(1) == "outer_appimage_extract_and_run"
    assert (
        smoke_package._appimage_execution_mode(2)
        == "outer_appimage_extract_and_run_then_verified_apprun"
    )


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
    expected_live_paths = {
        name: live_layout / "usr" / "bin" / path.name for name, path in _paths.items()
    }
    assert [entry[2] for entry in monitored] == [expected_live_paths, expected_live_paths]
    assert [entry[0] for entry in natural_checks] == [expected_live_paths]
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
            "app_ready",
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
            "bootstrap_import",
            "bootstrap_eval",
        }
    )


def test_packaged_smoke_never_projects_an_untrusted_failure_marker(tmp_path):
    marker = tmp_path / smoke_package.SMOKE_FAILURE
    marker.write_text("private provider body", encoding="utf-8")

    assert smoke_package._fixed_failure_stage(marker) is None

    marker.write_text("sanitize", encoding="utf-8")
    assert smoke_package._fixed_failure_stage(marker) == "sanitize"


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
        package_dir / name
        for name in (
            smoke_package.SMOKE_EVIDENCE,
            smoke_package.SMOKE_READY,
            smoke_package.SMOKE_FAILURE,
            smoke_package.SMOKE_NATIVE_START,
        )
    )
    real_popen = smoke_package.subprocess.Popen
    launched = []

    def fake_popen(*_args, **_kwargs):
        for marker in markers:
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
    monkeypatch.setattr(
        smoke_package,
        "_run_desktop",
        lambda *_args, **_kwargs: (
            1.0,
            dict.fromkeys(smoke_package.EXPECTED_SMOKE_METRICS, 1.0),
            dict.fromkeys(smoke_package.EXPECTED_RESOURCE_METRICS, 1.0),
        ),
    )

    smoke_package.smoke(package_dir, timeout=1)

    assert inspected == [paths["broker"], paths["backend"], paths["broker"], paths["backend"]]


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
    monkeypatch.setattr(
        smoke_package,
        "_run_desktop",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forced failure")),
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        smoke_package.smoke(package_dir, timeout=1)

    assert inspected == [paths["broker"], paths["backend"], paths["broker"], paths["backend"]]


def test_ci_and_release_build_both_tauri_native_components():
    for workflow_name in ("ci.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        assert "python scripts/build_sidecar.py" in workflow
        assert "python scripts/build_native_broker.py" in workflow


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
    assert workflow.count("scripts/smoke_desktop_native_package.py") >= 3
    linux_smoke_prefix = "dbus-run-session -- xvfb-run -a -e /dev/stderr sh -c"
    direct_inner_smoke = (
        '\'python scripts/smoke_desktop_native_package.py "$1" --repetitions 2 > "$2"\''
    )
    appimage_inner_smoke = (
        '\'python scripts/smoke_desktop_native_package.py "$1" --repetitions 2 '
        '--finalized-appimage "$3" --appimage-layout "$4" > "$2"\''
    )
    assert "dbus-daemon" in workflow
    assert workflow.count(linux_smoke_prefix) == 2
    assert workflow.count(direct_inner_smoke) == 1
    assert workflow.count(appimage_inner_smoke) == 1
    assert '"$GITHUB_WORKSPACE/$appimage" "$extracted_appimage/squashfs-root"' in workflow
    smoke_source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert '[str(attestation.candidate), "--appimage-extract-and-run"]' in smoke_source
    assert '[str(live_layout / "AppRun")]' in smoke_source
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


def test_tagged_installer_publication_is_fail_closed_until_slice6_recertification():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "blocked-until-phase-8-slice-6" in workflow
    assert "native-messaging registration and upgrade lifecycle are not certified" in workflow
    assert "native component manifest is not installed" not in workflow
    assert "build:\n    needs: preflight" in workflow
    assert "checksums-and-attest:\n" in workflow
    assert "needs: build" in workflow
