import importlib.util
import socket
from pathlib import Path

import pytest

SPEC_PATH = Path(__file__).resolve().parent.parent / "scripts" / "smoke_sidecar.py"
_spec = importlib.util.spec_from_file_location("smoke_sidecar", SPEC_PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


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


def test_main_refuses_on_win32(monkeypatch):
    monkeypatch.setattr(smoke.sys, "platform", "win32")
    with pytest.raises(SystemExit):
        smoke.main()
