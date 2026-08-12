#!/usr/bin/env python3
"""Run the feature-gated packaged Desktop native-broker smoke path."""

from __future__ import annotations

import argparse
import ctypes
import errno
import functools
import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SMOKE_EVIDENCE = "desktop-smoke-evidence.json"
SMOKE_READY = "desktop-smoke-ready"
SMOKE_FAILURE = "desktop-smoke-failure"
SMOKE_NATIVE_START = "desktop-smoke-native-start"
APPIMAGE_EXTRACTED_PREFIX = "appimage_extracted_"
APPIMAGE_EXTRACTED_NAME = re.compile(r"appimage_extracted_[0-9a-f]{32}\Z")
PRODUCT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
EXPECTED_SMOKE_METRICS = frozenset(
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
EXPECTED_FAILURE_STAGES = frozenset(
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
        "bootstrap_import",
        "bootstrap_eval",
        "webview_process",
    }
)
EXPECTED_RESOURCE_METRICS = frozenset(
    f"{component}_{metric}"
    for component in ("desktop", "broker", "backend")
    for metric in ("rss_mb", "handles")
)


class AppImageAttestation:
    __slots__ = (
        "apprun_digest",
        "candidate",
        "candidate_digest",
        "component_digests",
        "extracted_name",
        "layout",
        "manifest_digest",
        "package",
        "product_version",
    )

    def __init__(
        self,
        *,
        candidate: Path,
        candidate_digest: str,
        extracted_name: str,
        layout: Path,
        package: Path,
        apprun_digest: str,
        manifest_digest: str,
        component_digests: dict[str, str],
        product_version: str,
    ) -> None:
        self.candidate = candidate
        self.candidate_digest = candidate_digest
        self.extracted_name = extracted_name
        self.layout = layout
        self.package = package
        self.apprun_digest = apprun_digest
        self.manifest_digest = manifest_digest
        self.component_digests = component_digests
        self.product_version = product_version


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _content_md5(path: Path) -> str:
    hasher = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_regular_marker(path: Path, maximum_size: int) -> bytes | None:
    try:
        metadata = path.lstat()
        if (
            _is_link_or_reparse(path)
            or not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= maximum_size
        ):
            return None
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                return None
            value = handle.read(maximum_size + 1)
    except OSError:
        return None
    return value if len(value) <= maximum_size else None


def _fixed_marker(path: Path, expected: bytes) -> bool:
    return _read_regular_marker(path, len(expected)) == expected


def _fixed_failure_stage(path: Path) -> str | None:
    encoded = _read_regular_marker(path, max(map(len, EXPECTED_FAILURE_STAGES)))
    if encoded is None or not encoded.isascii():
        return None
    stage = encoded.decode("ascii")
    return stage if stage in EXPECTED_FAILURE_STAGES else None


def _raise_for_smoke_failure(path: Path) -> None:
    failure_stage = _fixed_failure_stage(path)
    if failure_stage is not None:
        raise RuntimeError(f"packaged Desktop smoke failed at fixed stage: {failure_stage}")
    if _path_exists(path):
        raise RuntimeError("packaged Desktop smoke failure evidence invalid")


def _missing_smoke_evidence_error(returncode: int) -> str:
    if returncode == 0:
        return "packaged Desktop smoke evidence unavailable"
    if returncode == 75:
        return "packaged Desktop smoke bootstrap rejected"
    if returncode < 0:
        return "packaged Desktop smoke process terminated"
    return "packaged Desktop smoke process failed"


def _component(package: Path, entry: dict[str, object]) -> Path:
    relative = entry.get("path")
    digest = entry.get("sha256")
    if not isinstance(relative, str) or not isinstance(digest, str):
        raise RuntimeError("invalid package manifest")
    relative_path = Path(relative)
    if relative_path.is_absolute() or len(relative_path.parts) != 1:
        raise RuntimeError("package component verification failed")
    original = package / relative_path
    if _is_link_or_reparse(original):
        raise RuntimeError("package component verification failed")
    path = original.resolve(strict=True)
    if path.parent != package or not path.is_file() or _digest(path) != digest:
        raise RuntimeError("package component verification failed")
    return path


def _regular_executable(path: Path) -> Path:
    if _is_link_or_reparse(path):
        raise ValueError("invalid AppImage smoke input")
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        raise ValueError("invalid AppImage smoke input") from None
    if not stat.S_ISREG(metadata.st_mode) or (os.name != "nt" and not metadata.st_mode & 0o111):
        raise ValueError("invalid AppImage smoke input")
    return resolved


def _checked_appimage_layout(package: Path, layout: Path) -> tuple[Path, Path, Path]:
    try:
        package_absolute = package.absolute()
        layout_absolute = layout.absolute()
        usr = layout_absolute / "usr"
        expected_package = usr / "bin"
        if any(_is_link_or_reparse(path) for path in (layout_absolute, usr, expected_package)):
            raise ValueError
        layout_resolved = layout_absolute.resolve(strict=True)
        package_resolved = package_absolute.resolve(strict=True)
        if (
            not layout_resolved.is_dir()
            or not package_resolved.is_dir()
            or package_resolved != expected_package.resolve(strict=True)
            or package_absolute != expected_package
        ):
            raise ValueError
        apprun = _regular_executable(layout_absolute / "AppRun")
        if not apprun.is_relative_to(layout_resolved) or apprun.parent != layout_resolved:
            raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise ValueError("invalid AppImage smoke input") from None
    return layout_resolved, package_resolved, apprun


def _manifest_components(package: Path) -> tuple[dict[str, Path], str]:
    manifest_path = package / "native-components-v1.json"
    if _is_link_or_reparse(manifest_path):
        raise RuntimeError("package component verification failed")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        clients = manifest["clients"]
        if not isinstance(clients, list) or not clients:
            raise TypeError
        verified_clients: dict[str, Path] = {}
        for client in clients:
            role = client["role"]
            if role not in {"desktop", "extension", "maintenance"} or role in verified_clients:
                raise TypeError
            verified_clients[role] = _component(package, client)
        if "desktop" not in verified_clients:
            raise TypeError
        if "native_host" in manifest and set(verified_clients) != {
            "desktop",
            "extension",
            "maintenance",
        }:
            raise TypeError
        paths = {
            "desktop": verified_clients["desktop"],
            "broker": _component(package, manifest["broker"]),
            "backend": _component(package, manifest["backend"]),
        }
    except (IndexError, KeyError, OSError, TypeError, json.JSONDecodeError):
        raise RuntimeError("package component verification failed") from None
    return paths, _digest(manifest_path)


def _manifest_product_version(package: Path, expected_digest: str) -> str:
    manifest_path = package / "native-components-v1.json"
    try:
        if _is_link_or_reparse(manifest_path) or _digest(manifest_path) != expected_digest:
            raise ValueError
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        product_version = manifest["product_version"]
        if not isinstance(product_version, str) or not PRODUCT_VERSION.fullmatch(product_version):
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("package component verification failed") from None
    return product_version


def _attest_appimage_inputs(
    package: Path,
    *,
    appimage_layout: Path,
    finalized_appimage: Path,
) -> AppImageAttestation:
    try:
        layout, package, apprun = _checked_appimage_layout(package, appimage_layout)
        candidate = _regular_executable(finalized_appimage.absolute())
        if (
            candidate.suffix != ".AppImage"
            or candidate.parent != finalized_appimage.absolute().parent
        ):
            raise ValueError
        component_paths, manifest_digest = _manifest_components(package)
        product_version = _manifest_product_version(package, manifest_digest)
        for marker in (SMOKE_EVIDENCE, SMOKE_READY, SMOKE_FAILURE, SMOKE_NATIVE_START):
            if _path_exists(package / marker):
                raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise ValueError("invalid AppImage smoke input") from None
    return AppImageAttestation(
        candidate=candidate,
        candidate_digest=_digest(candidate),
        extracted_name=f"{APPIMAGE_EXTRACTED_PREFIX}{_content_md5(candidate)}",
        layout=layout,
        package=package,
        apprun_digest=_digest(apprun),
        manifest_digest=manifest_digest,
        component_digests={name: _digest(path) for name, path in component_paths.items()},
        product_version=product_version,
    )


def _verified_live_appimage(
    layout: Path,
    attestation: AppImageAttestation,
) -> tuple[dict[str, Path], Path]:
    try:
        if (
            layout.name != attestation.extracted_name
            or not APPIMAGE_EXTRACTED_NAME.fullmatch(layout.name)
            or _is_link_or_reparse(layout)
            or layout.resolve(strict=True) != layout
        ):
            raise ValueError
        live_layout, live_package, live_apprun = _checked_appimage_layout(
            layout / "usr" / "bin", layout
        )
        component_paths, manifest_digest = _manifest_components(live_package)
        if (
            live_layout != layout
            or manifest_digest != attestation.manifest_digest
            or _manifest_product_version(live_package, manifest_digest)
            != attestation.product_version
            or _digest(live_apprun) != attestation.apprun_digest
            or {name: _digest(path) for name, path in component_paths.items()}
            != attestation.component_digests
        ):
            raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError("live AppImage verification failed") from None
    return component_paths, live_layout


def _verified_stable_appimage(
    data_root: Path,
    attestation: AppImageAttestation,
) -> dict[str, Path]:
    try:
        data_root = data_root.absolute()
        if (
            _is_link_or_reparse(data_root)
            or not data_root.is_dir()
            or data_root.resolve(strict=True) != data_root
        ):
            raise ValueError
        stable_package = data_root / "aiguard" / "native-host-v1" / attestation.product_version
        current = data_root
        for part in stable_package.relative_to(data_root).parts:
            current = current / part
            if _is_link_or_reparse(current) or not current.is_dir():
                raise ValueError
        if stable_package.resolve(strict=True) != stable_package:
            raise ValueError
        component_paths, manifest_digest = _manifest_components(stable_package)
        if (
            manifest_digest != attestation.manifest_digest
            or _manifest_product_version(stable_package, manifest_digest)
            != attestation.product_version
            or {name: _digest(path) for name, path in component_paths.items()}
            != attestation.component_digests
        ):
            raise ValueError
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError("stable AppImage verification failed") from None
    return component_paths


def _linux_executable_path(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeError("Unix process executable inspection unavailable") from error


@functools.lru_cache(maxsize=1)
def _macos_proc_pidpath():
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError as error:
        raise RuntimeError("Unix process executable inspection unavailable") from error
    proc_pidpath = libproc.proc_pidpath
    proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    proc_pidpath.restype = ctypes.c_int
    return proc_pidpath


def _macos_executable_path(pid: int) -> str | None:
    buffer = ctypes.create_string_buffer(4096)
    ctypes.set_errno(0)
    length = _macos_proc_pidpath()(pid, buffer, len(buffer))
    if length <= 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.ENOENT, errno.ESRCH}:
            return None
        raise RuntimeError("Unix process executable inspection unavailable")
    if length >= len(buffer) or not buffer.value:
        raise RuntimeError("Unix process executable inspection unavailable")
    return os.fsdecode(buffer.value)


def _unix_executable_path(pid: int) -> str | None:
    if sys.platform.startswith("linux"):
        return _linux_executable_path(pid)
    if sys.platform == "darwin":
        return _macos_executable_path(pid)
    raise RuntimeError("Unix process executable inspection unsupported")


def _unix_process_count(executable: Path) -> int:
    is_linux = sys.platform.startswith("linux")
    command = ["ps", "-A", "-o", "pid=", "-o", "uid="]
    if is_linux:
        command.extend(("-o", "comm="))
    try:
        output = subprocess.check_output(
            command,
            text=True,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise RuntimeError("Unix process inspection unavailable") from error

    current_uid = os.getuid()
    current_pid = os.getpid()
    processes: list[tuple[int, str | None]] = []
    seen_process_ids: set[int] = set()
    for line in output.splitlines():
        fields = line.split(maxsplit=2 if is_linux else 1)
        if not fields:
            continue
        if len(fields) != (3 if is_linux else 2):
            raise RuntimeError("Unix process inspection unavailable")
        try:
            pid, uid = (int(field) for field in fields[:2])
        except ValueError:
            raise RuntimeError("Unix process inspection unavailable") from None
        if pid <= 0 or uid < 0 or pid in seen_process_ids:
            raise RuntimeError("Unix process inspection unavailable")
        seen_process_ids.add(pid)
        if uid == current_uid:
            processes.append((pid, fields[2] if is_linux else None))
    if current_pid not in {pid for pid, _comm in processes}:
        raise RuntimeError("Unix process inspection omitted the current process")

    expected = executable.resolve(strict=True)
    # Linux comm is value-free and limited to 15 visible bytes for these ASCII names.
    expected_comm = expected.name[:15] if is_linux else None
    count = 0
    for pid, comm in processes:
        if pid != current_pid and expected_comm is not None and comm != expected_comm:
            continue
        raw_path = _unix_executable_path(pid)
        if raw_path is None:
            if pid == current_pid:
                raise RuntimeError("Unix process executable inspection unavailable")
            continue
        deleted_suffix = " (deleted)"
        if raw_path.endswith(deleted_suffix):
            raw_path = raw_path[: -len(deleted_suffix)]
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            raise RuntimeError("Unix process executable inspection unavailable")
        try:
            candidate = candidate.resolve(strict=False)
        except OSError as error:
            raise RuntimeError("Unix process executable inspection unavailable") from error
        if candidate.name == expected.name and candidate == expected:
            count += 1
    return count


def _process_count(executable: Path) -> int:
    if os.name == "nt":
        return _windows_process_count(executable)
    return _unix_process_count(executable)


def _load_psutil():
    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("resource sampling unavailable") from error
    return psutil


def _windows_process_count(executable: Path) -> int:
    psutil = _load_psutil()
    expected = executable.resolve(strict=True)
    expected_key = os.path.normcase(os.path.abspath(expected)).casefold()
    count = 0
    for process in psutil.process_iter(["name", "exe"]):
        try:
            name = process.info["name"]
            if not name or name.casefold() != expected.name.casefold():
                continue
            raw_path = process.info["exe"]
            if not raw_path:
                raise RuntimeError("Windows process executable inspection unavailable")
            candidate = Path(raw_path).resolve(strict=False)
            candidate_key = os.path.normcase(os.path.abspath(candidate)).casefold()
            if candidate_key == expected_key:
                count += 1
        except psutil.NoSuchProcess:
            continue
        except (OSError, psutil.AccessDenied, psutil.Error) as error:
            raise RuntimeError("Windows process executable inspection unavailable") from error
    return count


def _sample_resources(paths: dict[str, Path]) -> dict[str, float]:
    psutil = _load_psutil()
    totals = {f"{name}_rss_mb": 0.0 for name in paths}
    totals.update({f"{name}_handles": 0.0 for name in paths})
    expected = {os.path.normcase(os.path.abspath(path)): name for name, path in paths.items()}
    for process in psutil.process_iter(["exe"]):
        try:
            executable = process.info["exe"]
            name = (
                expected.get(os.path.normcase(os.path.abspath(executable))) if executable else None
            )
            if name is None:
                continue
            totals[f"{name}_rss_mb"] += process.memory_info().rss / (1024 * 1024)
            counter = process.num_handles() if os.name == "nt" else process.num_fds()
            totals[f"{name}_handles"] += float(counter)
        except (OSError, psutil.Error):
            continue
    return totals


def _validated_resource_peaks(peaks: dict[str, float]) -> dict[str, float]:
    if set(peaks) != EXPECTED_RESOURCE_METRICS or not all(
        isinstance(value, (int, float)) and math.isfinite(value) and value > 0
        for value in peaks.values()
    ):
        raise RuntimeError("packaged Desktop resource evidence unavailable")
    return {name: round(value, 3) for name, value in sorted(peaks.items())}


def _marker_paths(root: Path) -> tuple[Path, Path, Path, Path]:
    return tuple(
        root / name for name in (SMOKE_EVIDENCE, SMOKE_READY, SMOKE_FAILURE, SMOKE_NATIVE_START)
    )


def _clear_markers(root: Path) -> None:
    for path in _marker_paths(root):
        path.unlink(missing_ok=True)


def _terminate_process(process: subprocess.Popen, *, process_group: bool) -> None:
    if process_group:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            raise RuntimeError("AppImage smoke process cleanup failed") from None
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                raise RuntimeError("AppImage smoke process cleanup failed") from None
            process.wait(timeout=5)
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    except OSError:
        raise RuntimeError("packaged Desktop process cleanup failed") from None


def _run_started_process(
    process: subprocess.Popen,
    marker_root: Path,
    component_paths: dict[str, Path],
    timeout: float,
    *,
    started: float,
    process_group: bool,
) -> tuple[float, dict[str, float], dict[str, float]]:
    evidence_path, ready_path, failure_path, native_start_path = _marker_paths(marker_root)
    peaks: dict[str, float] = {}
    sample_stop = threading.Event()
    sample_failures: list[Exception] = []

    def sample_until_stopped() -> None:
        try:
            while not sample_stop.is_set():
                for name, value in _sample_resources(component_paths).items():
                    peaks[name] = max(peaks.get(name, 0.0), value)
                sample_stop.wait(0.05)
        except Exception as error:
            sample_failures.append(error)
            sample_stop.set()

    sampler = threading.Thread(
        target=sample_until_stopped,
        name="desktop-package-resource-sampler",
        daemon=True,
    )
    sampler_started = False
    try:
        sampler.start()
        sampler_started = True
        ready_ms: float | None = None
        deadline = started + timeout
        while process.poll() is None:
            _raise_for_smoke_failure(failure_path)
            if sample_failures:
                raise RuntimeError("resource sampling unavailable") from None
            if ready_ms is None and _fixed_marker(ready_path, b"ready"):
                ready_ms = (time.monotonic() - started) * 1000.0
            if time.monotonic() >= deadline:
                raise RuntimeError("packaged Desktop smoke timed out")
            time.sleep(0.02)
        elapsed = time.monotonic() - started
        sample_stop.set()
        sampler.join(timeout=5)
        if sampler.is_alive() or sample_failures:
            raise RuntimeError("resource sampling unavailable") from None
        if ready_ms is None and _fixed_marker(ready_path, b"ready"):
            ready_ms = elapsed * 1000.0
        _raise_for_smoke_failure(failure_path)
        encoded_evidence = _read_regular_marker(evidence_path, 4096)
        if process.returncode != 0 or encoded_evidence is None:
            raise RuntimeError(_missing_smoke_evidence_error(process.returncode))
        try:
            evidence = json.loads(encoded_evidence.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("packaged Desktop smoke evidence unavailable") from None
        if set(evidence) != EXPECTED_SMOKE_METRICS or not all(
            isinstance(value, (int, float)) and 0 <= value <= timeout * 1000
            for value in evidence.values()
        ):
            raise RuntimeError("packaged Desktop smoke evidence invalid")
        if ready_ms is None or not _fixed_marker(native_start_path, b"started"):
            raise RuntimeError("packaged Desktop readiness evidence unavailable")
        evidence["desktop_ready_ms"] = ready_ms
        return elapsed * 1000.0, evidence, peaks
    finally:
        if process.poll() is None:
            _terminate_process(process, process_group=process_group)
        sample_stop.set()
        if sampler_started:
            sampler.join(timeout=5)
        try:
            _clear_markers(marker_root)
        except OSError:
            raise RuntimeError("packaged Desktop smoke marker cleanup failed") from None


def _run_desktop(
    desktop: Path,
    package: Path,
    marker_root: Path,
    environment: dict[str, str],
    component_paths: dict[str, Path],
    timeout: float,
) -> tuple[float, dict[str, float], dict[str, float]]:
    _clear_markers(marker_root)
    process = subprocess.Popen(
        [str(desktop)],
        cwd=package,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return _run_started_process(
        process,
        marker_root,
        component_paths,
        timeout,
        started=time.monotonic(),
        process_group=False,
    )


def _wait_for_native_baseline(
    broker: Path,
    backend: Path,
    *,
    baseline_broker: int,
    baseline_backend: int,
) -> tuple[int, int]:
    cleanup_deadline = time.monotonic() + 40
    while time.monotonic() < cleanup_deadline:
        broker_count = _process_count(broker)
        backend_count = _process_count(backend)
        if broker_count <= baseline_broker and backend_count <= baseline_backend:
            return broker_count, backend_count
        time.sleep(0.25)
    raise RuntimeError("packaged Desktop left native resources running")


def _acceptance_environment() -> dict[str, str]:
    environment = os.environ.copy()
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
        environment.pop(name, None)
    environment.update(
        {
            "AIGUARD_DESKTOP_PACKAGE_SMOKE": "1",
            "AIGUARD_NER_ENGINE": "thainer",
            "AIGUARD_PROVIDERS": "fake",
            "PYTHONUTF8": "1",
        }
    )
    # Xvfb has neither a compositor nor a DMA-BUF renderer.
    if sys.platform.startswith("linux"):
        environment["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
        environment["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"
    return environment


def _private_package_smoke_root() -> tuple[Path, tuple[int, int]]:
    try:
        root = Path(tempfile.mkdtemp(prefix="aiguard-package-smoke-")).resolve(strict=True)
        os.chmod(root, 0o700)
        metadata = root.lstat()
        if _is_link_or_reparse(root) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o700:
            raise OSError
    except OSError:
        raise RuntimeError("packaged Desktop smoke isolation unavailable") from None
    return root, (metadata.st_dev, metadata.st_ino)


def _cleanup_private_package_smoke_root(root: Path, identity: tuple[int, int]) -> None:
    try:
        metadata = root.lstat()
        if (
            _is_link_or_reparse(root)
            or not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != identity
            or root.resolve(strict=True) != root
        ):
            raise OSError
        shutil.rmtree(root)
        if root.exists():
            raise OSError
    except OSError:
        raise RuntimeError("packaged Desktop smoke isolation cleanup failed") from None


def _private_appimage_root() -> tuple[Path, tuple[int, int], dict[str, Path]]:
    try:
        root = Path(tempfile.mkdtemp(prefix="aiguard-appimage-smoke-")).resolve(strict=True)
        os.chmod(root, 0o700)
        metadata = root.lstat()
        if _is_link_or_reparse(root) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o700:
            raise OSError
        directories = {}
        for name in ("evidence", "home", "config", "cache", "data", "state", "runtime"):
            path = root / name
            path.mkdir(mode=0o700)
            os.chmod(path, 0o700)
            directories[name] = path
    except OSError:
        raise RuntimeError("AppImage smoke isolation unavailable")
    return root, (metadata.st_dev, metadata.st_ino), directories


def _appimage_environment(
    root: Path,
    directories: dict[str, Path],
    *,
    layout: Path | None = None,
    candidate: Path | None = None,
) -> dict[str, str]:
    environment = {
        name: value
        for name in (
            "DBUS_SESSION_BUS_ADDRESS",
            "DISPLAY",
            "LANG",
            "LANGUAGE",
            "LC_ALL",
            "PATH",
            "WAYLAND_DISPLAY",
            "XAUTHORITY",
        )
        if (value := os.environ.get(name))
    }
    environment.update(
        {
            "AIGUARD_DESKTOP_PACKAGE_SMOKE": "1",
            "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT": str(directories["evidence"]),
            "AIGUARD_NER_ENGINE": "thainer",
            "AIGUARD_PROVIDERS": "fake",
            "HOME": str(directories["home"]),
            "PYTHONUTF8": "1",
            "TMPDIR": str(root),
            "XDG_CACHE_HOME": str(directories["cache"]),
            "XDG_CONFIG_HOME": str(directories["config"]),
            "XDG_DATA_HOME": str(directories["data"]),
            "XDG_RUNTIME_DIR": str(directories["runtime"]),
            "XDG_STATE_HOME": str(directories["state"]),
        }
    )
    # Xvfb has neither a compositor nor a DMA-BUF renderer.
    if sys.platform.startswith("linux"):
        environment["WEBKIT_DISABLE_COMPOSITING_MODE"] = "1"
        environment["WEBKIT_DISABLE_DMABUF_RENDERER"] = "1"
    if layout is None or candidate is None:
        environment["NO_CLEANUP"] = "1"
    else:
        environment.update(
            {
                "APPDIR": str(layout),
                "APPIMAGE": str(candidate),
                "ARGV0": str(candidate),
            }
        )
    return environment


def _group_exists(process: subprocess.Popen) -> bool:
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        raise RuntimeError("AppImage smoke process cleanup failed") from None
    return True


def _stop_process_groups(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if _group_exists(process):
            _terminate_process(process, process_group=True)
    deadline = time.monotonic() + 5
    while any(_group_exists(process) for process in processes):
        if time.monotonic() >= deadline:
            for process in processes:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    raise RuntimeError("AppImage smoke process cleanup failed") from None
            break
        time.sleep(0.05)
    if any(_group_exists(process) for process in processes):
        raise RuntimeError("AppImage smoke process cleanup failed")


def _wait_for_live_appimage(
    layout: Path,
    data_root: Path,
    marker_root: Path,
    attestation: AppImageAttestation,
    process: subprocess.Popen,
    deadline: float,
) -> dict[str, Path]:
    marker = marker_root / SMOKE_NATIVE_START
    failure_marker = marker_root / SMOKE_FAILURE
    while True:
        failure_stage = _fixed_failure_stage(failure_marker)
        if failure_stage is not None:
            raise RuntimeError(f"packaged Desktop smoke failed at fixed stage: {failure_stage}")
        if _path_exists(failure_marker):
            raise RuntimeError("AppImage bootstrap failure evidence invalid")
        if _fixed_marker(marker, b"started"):
            _component_paths, verified_layout = _verified_live_appimage(layout, attestation)
            if verified_layout != layout:
                raise RuntimeError("live AppImage verification failed")
            return _verified_stable_appimage(data_root, attestation)
        try:
            marker.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            raise RuntimeError("AppImage native start evidence invalid") from None
        else:
            raise RuntimeError("AppImage native start evidence invalid")
        if process.poll() is not None:
            failure_stage = _fixed_failure_stage(failure_marker)
            if failure_stage is not None:
                raise RuntimeError(f"packaged Desktop smoke failed at fixed stage: {failure_stage}")
            if _path_exists(failure_marker):
                raise RuntimeError("AppImage bootstrap failure evidence invalid")
            raise RuntimeError("AppImage native start evidence unavailable")
        if time.monotonic() >= deadline:
            raise RuntimeError("packaged Desktop smoke timed out")
        time.sleep(0.02)


def _wait_for_components_zero(component_paths: dict[str, Path]) -> dict[str, int]:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        counts = {name: _process_count(path) for name, path in component_paths.items()}
        if not any(counts.values()):
            return counts
        time.sleep(0.25)
    raise RuntimeError("packaged Desktop left native resources running")


def _wait_for_appimage_zero(
    component_paths: dict[str, Path], processes: list[subprocess.Popen]
) -> None:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        counts = {name: _process_count(path) for name, path in component_paths.items()}
        if not any(counts.values()) and not any(_group_exists(process) for process in processes):
            return
        time.sleep(0.25)
    raise RuntimeError("packaged Desktop left native resources running")


def _cleanup_private_appimage_root(root: Path, identity: tuple[int, int]) -> None:
    try:
        metadata = root.lstat()
        if (
            _is_link_or_reparse(root)
            or not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != identity
            or root.resolve(strict=True) != root
        ):
            raise OSError
        shutil.rmtree(root)
        if root.exists():
            raise OSError
    except OSError:
        raise RuntimeError("AppImage smoke isolation cleanup failed") from None


def _smoke_result(
    runs: list[dict[str, float]],
    peaks: dict[str, float],
    *,
    broker_delta: int,
    backend_delta: int,
    execution_mode: str,
) -> dict[str, object]:
    return {
        "execution_mode": execution_mode,
        "broker_process_delta": broker_delta,
        "backend_process_delta": backend_delta,
        "cold_process_elapsed_ms": runs[0]["process_elapsed_ms"],
        "warm_process_elapsed_median_ms": (
            round(statistics.median(run["process_elapsed_ms"] for run in runs[1:]), 3)
            if len(runs) > 1
            else None
        ),
        "resource_peaks": _validated_resource_peaks(peaks),
        "runs": runs,
    }


def _appimage_host_supported() -> bool:
    return os.name != "nt" and sys.platform.startswith("linux")


def _appimage_execution_mode(repetitions: int) -> str:
    if repetitions == 1:
        return "outer_appimage_extract_and_run"
    return "outer_appimage_extract_and_run_then_verified_apprun"


def _run_appimage_smoke(
    attestation: AppImageAttestation,
    timeout: float,
    repetitions: int,
) -> dict[str, object]:
    if not _appimage_host_supported():
        raise ValueError("AppImage smoke requires Linux")
    root, identity, directories = _private_appimage_root()
    live_layout = root / attestation.extracted_name
    try:
        live_layout.lstat()
    except FileNotFoundError:
        pass
    else:
        _cleanup_private_appimage_root(root, identity)
        raise RuntimeError("AppImage smoke isolation unavailable")
    marker_root = directories["evidence"]
    processes: list[subprocess.Popen] = []
    live_paths: dict[str, Path] | None = None
    runs: list[dict[str, float]] = []
    peaks: dict[str, float] = {}
    completed = False
    try:
        if _digest(attestation.candidate) != attestation.candidate_digest:
            raise RuntimeError("finalized AppImage changed during smoke")
        try:
            _clear_markers(marker_root)
        except OSError:
            raise RuntimeError("AppImage smoke marker cleanup failed") from None
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                [str(attestation.candidate), "--appimage-extract-and-run"],
                cwd=attestation.candidate.parent,
                env=_appimage_environment(root, directories),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            raise RuntimeError("AppImage runtime launch unavailable") from None
        processes.append(process)
        live_paths = _wait_for_live_appimage(
            live_layout,
            directories["data"],
            marker_root,
            attestation,
            process,
            started + timeout,
        )
        elapsed_ms, evidence, run_peaks = _run_started_process(
            process,
            marker_root,
            live_paths,
            timeout,
            started=started,
            process_group=True,
        )
        runs.append({"process_elapsed_ms": round(elapsed_ms, 3), **evidence})
        peaks.update(run_peaks)

        for _ in range(1, repetitions):
            _verified_paths, verified_layout = _verified_live_appimage(live_layout, attestation)
            verified_stable_paths = _verified_stable_appimage(directories["data"], attestation)
            if verified_stable_paths != live_paths or verified_layout != live_layout:
                raise RuntimeError("live AppImage verification failed")
            try:
                _clear_markers(marker_root)
            except OSError:
                raise RuntimeError("AppImage smoke marker cleanup failed") from None
            started = time.monotonic()
            try:
                process = subprocess.Popen(
                    [str(live_layout / "AppRun")],
                    cwd=live_layout,
                    env=_appimage_environment(
                        root,
                        directories,
                        layout=live_layout,
                        candidate=attestation.candidate,
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError:
                raise RuntimeError("AppImage AppRun launch unavailable") from None
            processes.append(process)
            elapsed_ms, evidence, run_peaks = _run_started_process(
                process,
                marker_root,
                live_paths,
                timeout,
                started=started,
                process_group=True,
            )
            runs.append({"process_elapsed_ms": round(elapsed_ms, 3), **evidence})
            for name, value in run_peaks.items():
                peaks[name] = max(peaks.get(name, 0.0), value)
        _validated_resource_peaks(peaks)
        completed = True
    finally:
        cleanup_error: Exception | None = None
        safe_to_remove = False
        if completed and live_paths is not None:
            try:
                _wait_for_appimage_zero(live_paths, processes)
            except (OSError, RuntimeError) as error:
                cleanup_error = error
        try:
            if not completed or cleanup_error is not None:
                _stop_process_groups(processes)
                if live_paths is not None:
                    _wait_for_components_zero(live_paths)
            safe_to_remove = True
            if (
                _regular_executable(attestation.candidate) != attestation.candidate
                or _digest(attestation.candidate) != attestation.candidate_digest
            ):
                raise RuntimeError("finalized AppImage changed during smoke")
            if live_paths is not None:
                _verified_paths, verified_layout = _verified_live_appimage(live_layout, attestation)
                verified_stable_paths = _verified_stable_appimage(directories["data"], attestation)
                if verified_stable_paths != live_paths or verified_layout != live_layout:
                    raise RuntimeError("live AppImage verification failed")
        except OSError:
            cleanup_error = RuntimeError("AppImage smoke verification unavailable")
        except (RuntimeError, ValueError) as error:
            cleanup_error = error
        if safe_to_remove:
            try:
                _cleanup_private_appimage_root(root, identity)
            except RuntimeError as error:
                cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise cleanup_error
    return _smoke_result(
        runs,
        peaks,
        broker_delta=0,
        backend_delta=0,
        execution_mode=_appimage_execution_mode(repetitions),
    )


def smoke(
    package: Path,
    timeout: float,
    repetitions: int = 1,
    *,
    finalized_appimage: Path | None = None,
    appimage_layout: Path | None = None,
) -> dict[str, object]:
    if not 1 <= repetitions <= 20:
        raise ValueError("repetitions must be between 1 and 20")
    if (finalized_appimage is None) != (appimage_layout is None):
        raise ValueError("AppImage smoke requires both finalized image and layout")
    if finalized_appimage is not None and appimage_layout is not None:
        attestation = _attest_appimage_inputs(
            package,
            appimage_layout=appimage_layout,
            finalized_appimage=finalized_appimage,
        )
        return _run_appimage_smoke(attestation, timeout, repetitions)

    package = package.resolve(strict=True)
    component_paths, _manifest_digest = _manifest_components(package)
    desktop = component_paths["desktop"]
    broker = component_paths["broker"]
    backend = component_paths["backend"]
    baseline_broker = _process_count(broker)
    baseline_backend = _process_count(backend)
    marker_root, marker_identity = _private_package_smoke_root()
    environment = _acceptance_environment()
    environment["AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT"] = str(marker_root)
    runs = []
    peaks: dict[str, float] = {}
    try:
        for _ in range(repetitions):
            elapsed_ms, evidence, run_peaks = _run_desktop(
                desktop,
                package,
                marker_root,
                environment,
                component_paths,
                timeout,
            )
            runs.append({"process_elapsed_ms": round(elapsed_ms, 3), **evidence})
            for name, value in run_peaks.items():
                peaks[name] = max(peaks.get(name, 0.0), value)
    finally:
        cleanup_error: Exception | None = None
        try:
            broker_count, backend_count = _wait_for_native_baseline(
                broker,
                backend,
                baseline_broker=baseline_broker,
                baseline_backend=baseline_backend,
            )
        except (OSError, RuntimeError) as error:
            cleanup_error = error
        try:
            _cleanup_private_package_smoke_root(marker_root, marker_identity)
        except RuntimeError as error:
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise cleanup_error
    return _smoke_result(
        runs,
        peaks,
        broker_delta=broker_count - baseline_broker,
        backend_delta=backend_count - baseline_backend,
        execution_mode="direct_package_layout",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--finalized-appimage", type=Path)
    parser.add_argument("--appimage-layout", type=Path)
    args = parser.parse_args()
    evidence = smoke(
        args.package,
        args.timeout,
        args.repetitions,
        finalized_appimage=args.finalized_appimage,
        appimage_layout=args.appimage_layout,
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
