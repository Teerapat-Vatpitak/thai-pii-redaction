#!/usr/bin/env python3
"""Headless packaged-backend and Office HTTP v2 composition check.

The default path builds the packaged sidecar and Office bundle, boots the
sidecar, and verifies health/sanitize/reidentify with synthetic data. When the
standard Office development certificate already exists and is trusted, the
same checks run through the Vite HTTPS proxy. This script never provisions,
installs, trusts, or removes certificates and never opens an Office host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.http_v2_client import (
        CONTRACT_HEADER,
        CONTRACT_VERSION,
        ContractError,
        require_contract_header,
        validate_health,
        validate_reidentify,
        validate_sanitize,
    )
    from scripts.smoke_exe import find_sidecar, taskkill_tree
except ModuleNotFoundError:  # Direct ``python scripts/office_v2_composition.py``.
    from http_v2_client import (  # type: ignore[no-redef]
        CONTRACT_HEADER,
        CONTRACT_VERSION,
        ContractError,
        require_contract_header,
        validate_health,
        validate_reidentify,
        validate_sanitize,
    )
    from smoke_exe import find_sidecar, taskkill_tree  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parent.parent
OFFICE_ROOT = ROOT / "office-addin"
BACKEND_BASE = "http://127.0.0.1:8000"
OFFICE_BASE = "https://localhost:3000"
CERTIFICATE_NAMES = ("ca.crt", "localhost.crt", "localhost.key")
SYNTHETIC_TEXT = "ผู้ติดต่อทดสอบ โทร 081-234-5678"
SYNTHETIC_RAW_MARKERS = ("081-234-5678",)
PRODUCT_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
_PROBE_REASONS = {
    "certificate-files-missing",
    "not-trusted-or-invalid",
    "verification-error",
}


class CompositionError(RuntimeError):
    """A fixed, value-free composition failure."""


class CertificateState(str, Enum):
    READY = "ready"
    PENDING = "pending"
    ERROR = "error"


@dataclass(frozen=True)
class CertificateProbe:
    state: CertificateState
    reason: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {"status": self.state.value}
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class ApiEvidence:
    detected_entity_count: int
    replacement_count: int
    restored_count: int


RequestJson = Callable[..., tuple[int, Any, Any]]
CertificateSnapshot = dict[str, tuple[str, int]]


def assert_packaged_health(value: Any) -> dict[str, Any]:
    try:
        health = validate_health(value)
    except ContractError:
        raise CompositionError("packaged health mismatch") from None
    if (
        health["capabilities"]
        != {
            "control_token_required": True,
            "api_key_required": False,
        }
        or health["version"] != PRODUCT_VERSION
    ):
        raise CompositionError("packaged health mismatch")
    return health


def parse_certificate_probe(returncode: int, stdout: str) -> CertificateProbe:
    try:
        value = json.loads(stdout)
    except (TypeError, ValueError):
        raise CompositionError("certificate probe failed") from None
    if not isinstance(value, dict):
        raise CompositionError("certificate probe failed")
    status = value.get("status")
    reason = value.get("reason")
    if returncode == 0 and value == {"status": "ready"}:
        return CertificateProbe(CertificateState.READY)
    if (
        returncode == 3
        and set(value) == {"status", "reason"}
        and status == "pending"
        and reason in _PROBE_REASONS - {"verification-error"}
    ):
        return CertificateProbe(CertificateState.PENDING, reason)
    if returncode == 1 and value == {"status": "error", "reason": "verification-error"}:
        return CertificateProbe(CertificateState.ERROR, "verification-error")
    raise CompositionError("certificate probe failed")


def probe_existing_certificates() -> CertificateProbe:
    command = [
        _npm_program("node"),
        str(OFFICE_ROOT / "scripts" / "existing-dev-certs.mjs"),
        "--json",
    ]
    environment = os.environ.copy()
    environment.pop("AIGUARD_OFFICE_CERT_DIR", None)
    completed = subprocess.run(
        command,
        cwd=OFFICE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return parse_certificate_probe(completed.returncode, completed.stdout.strip())


def certificate_directory() -> Path:
    return Path.home() / ".office-addin-dev-certs"


def certificate_snapshot(directory: Path) -> CertificateSnapshot:
    snapshot: CertificateSnapshot = {}
    for name in CERTIFICATE_NAMES:
        path = directory / name
        try:
            payload = path.read_bytes()
            modified = path.stat().st_mtime_ns
        except OSError:
            raise CompositionError("certificate files unavailable") from None
        snapshot[name] = (hashlib.sha256(payload).hexdigest(), modified)
    return snapshot


def assert_certificate_snapshot_unchanged(
    before: CertificateSnapshot,
    after: CertificateSnapshot,
) -> None:
    if before != after:
        raise CompositionError("certificate files changed")


def _direct_opener(
    ssl_context: ssl.SSLContext | None = None,
) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [urllib.request.ProxyHandler({})]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    return urllib.request.build_opener(*handlers)


def _request_json(
    method: str,
    url: str,
    *,
    payload: Mapping[str, Any] | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, Any, Any]:
    headers: dict[str, str] = {}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            CONTRACT_HEADER: CONTRACT_VERSION,
        }
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with _direct_opener(ssl_context).open(
            request,
            timeout=60,
        ) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise CompositionError("composition response too large")
            body = json.loads(raw)
            return response.status, response.headers, body
    except CompositionError:
        raise
    except Exception:
        raise CompositionError("composition request failed") from None


def exercise_v2_api(
    base_url: str,
    *,
    source_text: str = SYNTHETIC_TEXT,
    request_json: RequestJson = _request_json,
    ssl_context: ssl.SSLContext | None = None,
) -> ApiEvidence:
    try:
        status, headers, health_body = request_json(
            "GET",
            f"{base_url}/api/health",
            ssl_context=ssl_context,
        )
        require_contract_header(headers)
        if status != 200:
            raise CompositionError("HTTP v2 composition mismatch")
        assert_packaged_health(health_body)

        status, headers, sanitize_body = request_json(
            "POST",
            f"{base_url}/api/sanitize",
            payload={"text": source_text, "mode": "token"},
            ssl_context=ssl_context,
        )
        require_contract_header(headers)
        sanitized = validate_sanitize(sanitize_body)
        if (
            status != 200
            or sanitized["detected_entity_count"] < 1
            or sanitized["replacement_count"] < 1
            or sanitized["sanitized_text"] == source_text
            or any(marker in sanitized["sanitized_text"] for marker in SYNTHETIC_RAW_MARKERS)
        ):
            raise CompositionError("HTTP v2 composition mismatch")

        status, headers, restore_body = request_json(
            "POST",
            f"{base_url}/api/reidentify",
            payload={
                "session_id": sanitized["session_id"],
                "text": sanitized["sanitized_text"],
            },
            ssl_context=ssl_context,
        )
        require_contract_header(headers)
        restored = validate_reidentify(restore_body)
        if (
            status != 200
            or restored["restored_text"] != source_text
            or restored["replaced_count"] != sanitized["replacement_count"]
            or restored["leftover_count"] != 0
            or restored["warnings"]
        ):
            raise CompositionError("HTTP v2 composition mismatch")
    except ContractError:
        raise CompositionError("HTTP v2 composition mismatch") from None

    return ApiEvidence(
        detected_entity_count=sanitized["detected_entity_count"],
        replacement_count=sanitized["replacement_count"],
        restored_count=restored["replaced_count"],
    )


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return False


def _backend_health_ready() -> bool:
    try:
        status, headers, body = _request_json(
            "GET",
            f"{BACKEND_BASE}/api/health",
        )
        require_contract_header(headers)
        assert_packaged_health(body)
        return status == 200
    except (CompositionError, ContractError):
        return False


def _office_page_ready(context: ssl.SSLContext) -> bool:
    try:
        with _direct_opener(context).open(
            f"{OFFICE_BASE}/taskpane.html",
            timeout=3,
        ) as response:
            body = response.read(1024 * 1024 + 1)
        return (
            response.status == 200
            and len(body) <= 1024 * 1024
            and b'<section id="backend-banner"' in body
        )
    except Exception:
        return False


def _npm_program(program: str = "npm") -> str:
    if os.name == "nt" and program == "npm":
        return "npm.cmd"
    return program


def _run_builds(*, build_sidecar: bool, build_office: bool) -> None:
    if build_office:
        subprocess.check_call([_npm_program(), "run", "build"], cwd=OFFICE_ROOT)
    elif not (OFFICE_ROOT / "dist" / "taskpane.html").is_file():
        raise CompositionError("Office bundle unavailable")
    if build_sidecar:
        subprocess.check_call(
            [sys.executable, str(ROOT / "scripts" / "build_sidecar.py")],
            env=_packaged_environment(os.environ),
        )
    try:
        find_sidecar()
    except FileNotFoundError:
        raise CompositionError("packaged sidecar unavailable") from None


def _kill_tree(process: subprocess.Popen[Any]) -> None:
    if os.name == "nt":
        # Start-Process -Wait keeps this supervisor alive while any descendant
        # remains, so taskkill /T always has a live root for tree traversal.
        taskkill_tree(process.pid)
    elif process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            taskkill_tree(process.pid)
        else:
            process.kill()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            raise CompositionError("composition process did not stop") from None


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _supervisor_command(
    program: str,
    arguments: tuple[str, ...],
    working_directory: Path,
) -> list[str]:
    start_process = [
        "Start-Process",
        f"-FilePath {_powershell_literal(program)}",
    ]
    if arguments:
        argument_list = ", ".join(_powershell_literal(value) for value in arguments)
        start_process.append(f"-ArgumentList @({argument_list})")
    start_process.extend(
        [
            f"-WorkingDirectory {_powershell_literal(str(working_directory))}",
            "-WindowStyle Hidden",
            "-Wait",
        ]
    )
    return [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        " ".join(start_process),
    ]


def _start_supervised(
    program: str,
    *,
    arguments: tuple[str, ...] = (),
    working_directory: Path,
    environment: Mapping[str, str],
) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        _supervisor_command(program, arguments, working_directory),
        cwd=working_directory,
        env=dict(environment),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _start_sidecar() -> subprocess.Popen[Any]:
    environment = _packaged_environment(os.environ)
    return _start_supervised(
        find_sidecar(),
        working_directory=ROOT,
        environment=environment,
    )


def _packaged_environment(
    source: Mapping[str, str],
) -> dict[str, str]:
    environment = dict(source)
    for name in (
        "AIGUARD_ALLOWED_HOSTS",
        "AIGUARD_API_KEY",
        "AIGUARD_DEMO",
        "AIGUARD_FINETUNED_MODEL_DIR",
        "AIGUARD_PROVIDERS",
        "AIGUARD_TOKEN",
        "AIFORTHAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "PYTHAINLP_ALLOW_UNSAFE_PICKLE",
        "PYTHAINLP_DATA",
        "PYTHAINLP_DATA_DIR",
        "PYTHAINLP_OFFLINE",
        "PYTHAINLP_READ_MODE",
        "PYTHAINLP_READ_ONLY",
        "TOKENMIND_ALLOW_HTTP",
        "TOKENMIND_API_KEY",
        "TOKENMIND_BASE_URL",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "AIGUARD_AUDIT_STDOUT": "1",
            "AIGUARD_NER_ENGINE": "thainer",
            "AIGUARD_NO_BROWSER": "1",
            "PYTHAINLP_OFFLINE": "1",
        }
    )
    return environment


def _start_office_proxy() -> subprocess.Popen[Any]:
    environment = os.environ.copy()
    environment["AIGUARD_OFFICE_EXISTING_CERTS_ONLY"] = "1"
    environment["NO_COLOR"] = "1"
    return _start_supervised(
        _npm_program(),
        arguments=("run", "dev"),
        working_directory=OFFICE_ROOT,
        environment=environment,
    )


def _office_ssl_context(cert_dir: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(cert_dir / "ca.crt"))
    # office-addin-dev-certs 2.0.10 emits a valid chain without an Authority Key
    # Identifier. Python 3.13's strict flag rejects that legacy omission even
    # though the OS trust check and hostname validation pass. Keep all ordinary
    # CA, signature, validity, and hostname checks while allowing this certificate.
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return context


def _cleanup_composition(
    *,
    sidecar: subprocess.Popen[Any],
    proxy: subprocess.Popen[Any] | None,
    cert_dir: Path | None,
    certificate_before: CertificateSnapshot | None,
) -> None:
    failures: list[str] = []

    for process in (proxy, sidecar):
        if process is None:
            continue
        try:
            _kill_tree(process)
        except Exception:
            # Cleanup must continue so one failed wrapper does not leave the
            # other process tree running.
            failures.append("composition process cleanup failed")

    for port, message, required in (
        (8000, "backend port remained bound", True),
        (3000, "Office proxy port remained bound", proxy is not None),
    ):
        if not required:
            continue
        try:
            port_freed = _wait_for(lambda port=port: _port_is_free(port), 20)
        except Exception:
            port_freed = False
        if not port_freed:
            failures.append(message)

    if cert_dir is not None and certificate_before is not None:
        try:
            assert_certificate_snapshot_unchanged(
                certificate_before,
                certificate_snapshot(cert_dir),
            )
        except CompositionError as error:
            failures.append(str(error))
        except Exception:
            failures.append("certificate verification failed")

    if failures:
        raise CompositionError(failures[0])


def run_composition(
    *,
    build_sidecar: bool,
    build_office: bool,
    require_https: bool,
) -> CertificateState:
    if sys.platform != "win32":
        raise CompositionError("Office packaged composition is Windows-only")
    if not _port_is_free(8000):
        raise CompositionError("backend port is unavailable")

    _run_builds(build_sidecar=build_sidecar, build_office=build_office)
    sidecar = _start_sidecar()
    proxy: subprocess.Popen[Any] | None = None
    cert_dir: Path | None = None
    before: CertificateSnapshot | None = None
    try:
        if not _wait_for(_backend_health_ready, 90):
            raise CompositionError("packaged backend did not become ready")
        direct = exercise_v2_api(BACKEND_BASE)
        print(
            "PASS: packaged backend v2 health/sanitize/reidentify "
            f"({direct.detected_entity_count} detected, "
            f"{direct.restored_count} restored)"
        )

        cert_dir = certificate_directory()
        probe = probe_existing_certificates()
        if probe.state is CertificateState.ERROR:
            raise CompositionError("certificate verification failed")
        if probe.state is CertificateState.PENDING:
            if require_https:
                raise CompositionError("trusted Office certificate required")
            print(
                "PENDING: Office HTTPS development-proxy composition "
                "(no certificate trust was changed)"
            )
            return CertificateState.PENDING

        before = certificate_snapshot(cert_dir)
        if not _port_is_free(3000):
            raise CompositionError("Office proxy port is unavailable")
        context = _office_ssl_context(cert_dir)
        proxy = _start_office_proxy()
        if not _wait_for(lambda: _office_page_ready(context), 45):
            raise CompositionError("Office HTTPS proxy did not become ready")
        proxied = exercise_v2_api(OFFICE_BASE, ssl_context=context)
        print(
            "PASS: Office HTTPS development-proxy v2 health/sanitize/reidentify "
            f"({proxied.detected_entity_count} detected, "
            f"{proxied.restored_count} restored)"
        )
        return CertificateState.READY
    finally:
        _cleanup_composition(
            sidecar=sidecar,
            proxy=proxy,
            cert_dir=cert_dir,
            certificate_before=before,
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-sidecar-build",
        action="store_true",
        help="Use the already staged packaged sidecar.",
    )
    parser.add_argument(
        "--skip-office-build",
        action="store_true",
        help="Use the already built Office bundle.",
    )
    parser.add_argument(
        "--require-https",
        action="store_true",
        help="Fail instead of recording pending when no trusted certificate exists.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run_composition(
            build_sidecar=not args.skip_sidecar_build,
            build_office=not args.skip_office_build,
            require_https=args.require_https,
        )
    except CompositionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError:
        print("FAIL: composition build command failed", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print("FAIL: composition runtime failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
