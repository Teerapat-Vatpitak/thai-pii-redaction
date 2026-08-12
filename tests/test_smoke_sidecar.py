import importlib.util
import socket
from email.message import Message
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke_sidecar.py"
_spec = importlib.util.spec_from_file_location("smoke_sidecar", SPEC_PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

EXE_SPEC_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke_exe.py"
_exe_spec = importlib.util.spec_from_file_location("smoke_exe", EXE_SPEC_PATH)
smoke_exe = importlib.util.module_from_spec(_exe_spec)
_exe_spec.loader.exec_module(smoke_exe)


def test_port_is_free_false_when_bound():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert smoke.port_is_free("127.0.0.1", port) is False


def test_port_is_free_true_when_unbound():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert smoke.port_is_free("127.0.0.1", port) is True


def test_find_sidecar_raises_when_missing(monkeypatch):
    monkeypatch.setattr(smoke, "BIN_GLOB", "/no/such/dir/aiguard-*")
    with pytest.raises(FileNotFoundError):
        smoke.find_sidecar()


def test_find_sidecar_excludes_native_components_and_selects_backend(tmp_path, monkeypatch):
    backend = tmp_path / "aiguard-x86_64-unknown-linux-gnu"
    backend.write_bytes(b"backend")
    (tmp_path / "aiguard-native-broker-x86_64-unknown-linux-gnu").write_bytes(b"broker")
    (tmp_path / "aiguard-chrome-native-host-x86_64-unknown-linux-gnu").write_bytes(b"host")
    (tmp_path / "aiguard-native-host-manager-x86_64-unknown-linux-gnu").write_bytes(b"manager")
    monkeypatch.setattr(smoke, "BIN_GLOB", str(tmp_path / "aiguard-*"))

    assert smoke.find_sidecar() == str(backend)


def test_find_sidecar_rejects_ambiguous_backends(tmp_path, monkeypatch):
    (tmp_path / "aiguard-x86_64-unknown-linux-gnu").write_bytes(b"first")
    (tmp_path / "aiguard-aarch64-unknown-linux-gnu").write_bytes(b"second")
    monkeypatch.setattr(smoke, "BIN_GLOB", str(tmp_path / "aiguard-*"))

    with pytest.raises(RuntimeError, match="multiple packaged backend"):
        smoke.find_sidecar()


def test_find_windows_sidecar_excludes_native_components_and_selects_backend(tmp_path, monkeypatch):
    backend = tmp_path / "aiguard-x86_64-pc-windows-msvc.exe"
    backend.write_bytes(b"backend")
    (tmp_path / "aiguard-native-broker-x86_64-pc-windows-msvc.exe").write_bytes(b"broker")
    (tmp_path / "aiguard-chrome-native-host-x86_64-pc-windows-msvc.exe").write_bytes(b"host")
    (tmp_path / "aiguard-native-host-manager-x86_64-pc-windows-msvc.exe").write_bytes(b"manager")
    monkeypatch.setattr(smoke_exe, "STAGED_GLOB", str(tmp_path / "aiguard-*"))

    assert smoke_exe.find_sidecar() == str(backend)


def test_find_windows_sidecar_rejects_ambiguous_backends(tmp_path, monkeypatch):
    (tmp_path / "aiguard-x86_64-pc-windows-msvc.exe").write_bytes(b"first")
    (tmp_path / "aiguard-aarch64-pc-windows-msvc.exe").write_bytes(b"second")
    monkeypatch.setattr(smoke_exe, "STAGED_GLOB", str(tmp_path / "aiguard-*"))

    with pytest.raises(RuntimeError, match="multiple packaged backend"):
        smoke_exe.find_sidecar()


def test_main_refuses_on_win32(monkeypatch):
    monkeypatch.setattr(smoke.sys, "platform", "win32")
    with pytest.raises(SystemExit):
        smoke.main()


def _headers(*values: str) -> Message:
    headers = Message()
    for value in values:
        headers.add_header("X-AIGuard-Contract-Version", value)
    return headers


def _health() -> dict:
    return {
        "status": "ok",
        "version": "2.5.0",
        "contract_version": 2,
        "capabilities": {
            "control_token_required": True,
            "api_key_required": False,
        },
    }


def _sanitize() -> dict:
    return {
        "session_id": "synthetic-session",
        "sanitized_text": "[PHONE_1]",
        "detected_entity_count": 1,
        "replacement_count": 1,
        "entity_type_counts": {"PHONE": 1},
        "highlights": [
            {
                "start": 0,
                "end": 9,
                "data_type": "PHONE",
                "redact_type": "FP",
            }
        ],
        "section26_categories": [],
        "guard_findings": [],
        "warnings": [],
        "safety": {"status": "pass", "residual_count": 0},
    }


def test_health_smoke_requires_exact_v2_header_and_body():
    assert smoke._valid_health_response(200, _headers("2"), _health()) is True
    assert smoke._valid_health_response(200, _headers(), _health()) is False
    assert smoke._valid_health_response(200, _headers("2", "2"), _health()) is False

    extra = _health()
    extra["token_required"] = False
    assert smoke._valid_health_response(200, _headers("2"), extra) is False


def test_sanitize_smoke_requires_exact_safe_minimized_dto():
    assert smoke._valid_sanitize_response(200, _headers("2"), _sanitize()) is True

    extra = _sanitize()
    extra["original_text"] = "blocked"
    assert smoke._valid_sanitize_response(200, _headers("2"), extra) is False

    unsafe = _sanitize()
    unsafe["safety"] = {"status": "pass", "residual_count": 1}
    assert smoke._valid_sanitize_response(200, _headers("2"), unsafe) is False
