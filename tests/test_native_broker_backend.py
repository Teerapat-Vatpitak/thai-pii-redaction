from __future__ import annotations

import array
import http.client
import os
import secrets
import select
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.private_backend_bootstrap import (
    PrivateBackendCredentials,
    consume_private_backend_credentials,
    install_private_backend_credentials,
)
from native_broker_backend import (
    BOOTSTRAP_MAGIC,
    BOOTSTRAP_MAX_BYTES,
    BOOTSTRAP_VERSION,
    BootstrapError,
    _parse_unix_descriptors,
    _validate_listener,
    decode_bootstrap_packet,
)

ROOT = Path(__file__).resolve().parent.parent
HEADER = struct.Struct(">8sHHHHI")


def _bootstrap_packet(
    *,
    product_version: bytes = b"2.5.0",
    api_key: bytes | None = None,
    control_token: bytes | None = None,
    socket_info: bytes = b"",
) -> tuple[bytes, bytes, bytes]:
    api_key = api_key or secrets.token_hex(32).encode("ascii")
    control_token = control_token or secrets.token_hex(32).encode("ascii")
    body = HEADER.pack(
        BOOTSTRAP_MAGIC,
        BOOTSTRAP_VERSION,
        len(product_version),
        len(api_key),
        len(control_token),
        len(socket_info),
    )
    body += product_version + api_key + control_token + socket_info
    return len(body).to_bytes(4, "big") + body, api_key, control_token


def _wait_for_health(address: tuple[str, int], timeout_s: float = 15.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        connection = http.client.HTTPConnection(*address, timeout=0.5)
        try:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            body = response.read()
            if response.status == 200:
                import json

                return json.loads(body)
        except OSError:
            time.sleep(0.05)
        finally:
            connection.close()
    raise AssertionError("private backend did not become healthy")


def _start_private_backend(
    listener: socket.socket,
    command: list[str] | None = None,
):
    environment = os.environ.copy()
    environment.pop("AIGUARD_API_KEY", None)
    environment.pop("AIGUARD_TOKEN", None)
    environment["AIGUARD_NO_BROWSER"] = "1"
    if command is None:
        command = [sys.executable, str(ROOT / "launcher.py"), "--native-broker-backend"]

    if os.name == "nt":
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        assert process.stdin is not None
        socket_info = listener.share(process.pid)
        packet, api_key, control_token = _bootstrap_packet(socket_info=socket_info)
        process.stdin.write(packet)
        process.stdin.close()
        return process, api_key.decode("ascii"), control_token.decode("ascii"), None

    parent_channel, child_channel = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        process = subprocess.Popen(
            command,
            stdin=child_channel.fileno(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            pass_fds=(child_channel.fileno(),),
            start_new_session=True,
        )
    finally:
        child_channel.close()
    packet, api_key, control_token = _bootstrap_packet()
    socket.send_fds(parent_channel, [packet], [listener.fileno()])
    return process, api_key.decode("ascii"), control_token.decode("ascii"), parent_channel


def _shutdown_private_backend(
    process: subprocess.Popen[bytes],
    address: tuple[str, int],
    control_token: str,
) -> tuple[bytes, bytes]:
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        connection.request(
            "POST",
            "/api/shutdown",
            headers={
                "X-AIGuard-Contract-Version": "2",
                "X-AIGuard-Token": control_token,
            },
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 200
    finally:
        connection.close()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


def test_bootstrap_packet_is_strict_bounded_and_value_free():
    packet, api_key, control_token = _bootstrap_packet()
    credentials, socket_info = decode_bootstrap_packet(packet)

    assert credentials.product_version == "2.5.0"
    assert credentials.api_key == api_key.decode("ascii")
    assert credentials.control_token == control_token.decode("ascii")
    assert socket_info == b""
    assert api_key.decode("ascii") not in repr(credentials)
    assert control_token.decode("ascii") not in repr(credentials)

    malformed = [
        b"",
        (BOOTSTRAP_MAX_BYTES + 1).to_bytes(4, "big"),
        packet[:-1],
        packet + b"trailing",
    ]
    for value in malformed:
        with pytest.raises(BootstrapError, match="backend_bootstrap_failed") as exc_info:
            decode_bootstrap_packet(value)
        assert api_key.decode("ascii") not in repr(exc_info.value)
        assert control_token.decode("ascii") not in repr(exc_info.value)


def test_bootstrap_rejects_reused_or_noncanonical_credentials():
    key = secrets.token_hex(32).encode("ascii")
    duplicate, _, _ = _bootstrap_packet(api_key=key, control_token=key)
    with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
        decode_bootstrap_packet(duplicate)

    noncanonical, _, _ = _bootstrap_packet(api_key=b"Z" * 64)
    with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
        decode_bootstrap_packet(noncanonical)


def test_prebound_listener_is_validated_and_sealed_before_backend_prepare():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.set_inheritable(True)
        _validate_listener(listener)
        assert listener.get_inheritable() is False
    finally:
        listener.close()


def test_darwin_listener_probe_accepts_only_a_live_prebound_listener(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    not_listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        _validate_listener(listener)

        client.connect(listener.getsockname())
        _validate_listener(listener)

        not_listening.bind(("127.0.0.1", 0))
        with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
            _validate_listener(not_listening)
    finally:
        not_listening.close()
        client.close()
        listener.close()


@pytest.mark.skipif(os.name == "nt", reason="SCM_RIGHTS is Unix-only")
def test_unix_bootstrap_control_rejects_ambiguous_rights_and_closes_descriptors():
    with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
        _parse_unix_descriptors([], 0)
    with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
        _parse_unix_descriptors([(socket.SOL_SOCKET, -1, b"")], 0)

    reader, writer = os.pipe()
    duplicated: list[int] = []
    truncated: int | None = None
    try:
        duplicated = [os.dup(writer), os.dup(writer)]
        encoded = array.array("i", duplicated).tobytes()
        with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
            _parse_unix_descriptors([(socket.SOL_SOCKET, socket.SCM_RIGHTS, encoded)], 0)
        for descriptor in duplicated:
            with pytest.raises(OSError):
                os.fstat(descriptor)

        truncated = os.dup(writer)
        encoded = array.array("i", [truncated]).tobytes()
        with pytest.raises(BootstrapError, match="backend_bootstrap_failed"):
            _parse_unix_descriptors(
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, encoded)],
                getattr(socket, "MSG_CTRUNC", 1),
            )
        with pytest.raises(OSError):
            os.fstat(truncated)
    finally:
        for descriptor in duplicated:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if truncated is not None:
            try:
                os.close(truncated)
            except OSError:
                pass
        os.close(reader)
        os.close(writer)


@pytest.mark.skipif(os.name == "nt", reason="SCM_RIGHTS is Unix-only")
def test_unix_malformed_packet_closes_received_descriptor_before_process_exit():
    parent_channel, child_channel = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader, writer = os.pipe()
    source = """
import time
from native_broker_backend import BootstrapError, _read_unix_bootstrap

try:
    _read_unix_bootstrap()
except BootstrapError:
    print("rejected", flush=True)
    time.sleep(30)
"""
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", source],
            cwd=ROOT,
            stdin=child_channel.fileno(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(child_channel.fileno(),),
        )
        child_channel.close()
        socket.send_fds(parent_channel, [b"\x00\x00\x00\x01x"], [writer])
        os.close(writer)
        writer = -1

        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 2)
        assert ready
        assert process.stdout.readline() == b"rejected\n"
        readable, _, _ = select.select([reader], [], [], 2)
        assert readable
        assert os.read(reader, 1) == b""
        assert process.poll() is None
    finally:
        parent_channel.close()
        child_channel.close()
        os.close(reader)
        if writer >= 0:
            os.close(writer)
        if process is not None:
            if process.poll() is None:
                process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            assert b"Traceback" not in stdout + stderr


def test_private_backend_credentials_install_once_without_environment(monkeypatch):
    monkeypatch.delenv("AIGUARD_API_KEY", raising=False)
    monkeypatch.delenv("AIGUARD_TOKEN", raising=False)
    first = PrivateBackendCredentials(
        product_version="2.5.0",
        api_key=secrets.token_hex(32),
        control_token=secrets.token_hex(32),
    )
    install_private_backend_credentials(first)

    assert "AIGUARD_API_KEY" not in os.environ
    assert "AIGUARD_TOKEN" not in os.environ
    assert consume_private_backend_credentials() == first
    assert consume_private_backend_credentials() is None
    with pytest.raises(RuntimeError, match="private_backend_bootstrap_failed"):
        install_private_backend_credentials(first)


def test_prebound_private_backend_health_and_direct_data_denial():
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    address = listener.getsockname()
    process, api_key, control_token, broker_guard = _start_private_backend(listener)
    try:
        health = _wait_for_health(address)
        assert health == {
            "status": "ok",
            "version": "2.5.0",
            "contract_version": 2,
            "capabilities": {
                "control_token_required": True,
                "api_key_required": True,
            },
        }

        connection = http.client.HTTPConnection(*address, timeout=2)
        try:
            connection.request(
                "POST",
                "/api/detect",
                body=b'{"text":"synthetic transport fixture"}',
                headers={
                    "Content-Type": "application/json",
                    "X-AIGuard-Contract-Version": "2",
                },
            )
            response = connection.getresponse()
            body = response.read()
        finally:
            connection.close()
        assert response.status == 401
        assert b"authentication_required" in body
        assert api_key.encode("ascii") not in body
        assert control_token.encode("ascii") not in body

        stdout, stderr = _shutdown_private_backend(process, address, control_token)
        assert api_key.encode("ascii") not in stdout + stderr
        assert control_token.encode("ascii") not in stdout + stderr
    finally:
        if broker_guard is not None:
            broker_guard.close()
        listener.close()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_malformed_bootstrap_exits_without_sentinel_or_exception_graph():
    sentinel = b"SYNTHETIC_BOOTSTRAP_SENTINEL"
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "launcher.py"), "--native-broker-backend"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(b"\x00\x00\x00\x20" + sentinel, timeout=5)

    assert process.returncode != 0
    assert sentinel not in stdout + stderr
    assert b"Traceback" not in stdout + stderr


def test_private_preparation_failure_is_silent_and_value_free():
    sentinel = "SYNTHETIC_PREPARATION_SENTINEL"
    source = (
        "from native_broker_backend import main; "
        f"failure=lambda: (_ for _ in ()).throw(RuntimeError('{sentinel}')); "
        "raise SystemExit(main(failure))"
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    process = None
    broker_guard = None
    try:
        process, _api_key, _control_token, broker_guard = _start_private_backend(
            listener,
            [sys.executable, "-c", source],
        )
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 70
        assert stdout == b""
        assert stderr == b""
    finally:
        if broker_guard is not None:
            broker_guard.close()
        listener.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
