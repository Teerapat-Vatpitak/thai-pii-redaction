"""Private broker-owned entry point for the existing HTTP-v2 backend.

The native broker binds the listener first and sends a duplicated listener plus
independent data/control credentials through the child bootstrap channel. This
module never selects a port and never reads those credentials from argv or the
environment.
"""

from __future__ import annotations

import array
import os
import re
import socket
import struct
import sys
import threading
from collections.abc import Callable

from app.private_backend_bootstrap import (
    PrivateBackendCredentials,
    install_private_backend_credentials,
)

BOOTSTRAP_MAGIC = b"AIGB2IPC"
BOOTSTRAP_VERSION = 1
BOOTSTRAP_MAX_BYTES = 4096
_HEADER = struct.Struct(">8sHHHHI")
_PRODUCT_VERSION_RE = re.compile(rb"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
_SECRET_RE = re.compile(rb"^[0-9a-f]{64}$")


class BootstrapError(RuntimeError):
    """One fixed value-free bootstrap failure."""

    def __init__(self) -> None:
        super().__init__("backend_bootstrap_failed")

    def __repr__(self) -> str:
        return "BootstrapError('backend_bootstrap_failed')"


def _fail() -> None:
    raise BootstrapError() from None


def decode_bootstrap_packet(
    packet: bytes,
) -> tuple[PrivateBackendCredentials, bytes]:
    """Decode one complete bounded bootstrap packet without diagnostic detail."""

    if not isinstance(packet, bytes) or len(packet) < 4 + _HEADER.size:
        _fail()
    declared = int.from_bytes(packet[:4], "big")
    if declared <= 0 or declared > BOOTSTRAP_MAX_BYTES or declared != len(packet) - 4:
        _fail()
    body = packet[4:]
    try:
        magic, version, product_len, api_len, control_len, socket_info_len = _HEADER.unpack_from(
            body
        )
    except struct.error:
        _fail()
    if (
        magic != BOOTSTRAP_MAGIC
        or version != BOOTSTRAP_VERSION
        or not 1 <= product_len <= 64
        or api_len != 64
        or control_len != 64
        or socket_info_len > 2048
        or _HEADER.size + product_len + api_len + control_len + socket_info_len != len(body)
    ):
        _fail()
    offset = _HEADER.size
    product_version = body[offset : offset + product_len]
    offset += product_len
    api_key = body[offset : offset + api_len]
    offset += api_len
    control_token = body[offset : offset + control_len]
    offset += control_len
    socket_info = body[offset:]
    if (
        _PRODUCT_VERSION_RE.fullmatch(product_version) is None
        or _SECRET_RE.fullmatch(api_key) is None
        or _SECRET_RE.fullmatch(control_token) is None
        or api_key == control_token
    ):
        _fail()
    try:
        credentials = PrivateBackendCredentials(
            product_version=product_version.decode("ascii"),
            api_key=api_key.decode("ascii"),
            control_token=control_token.decode("ascii"),
        )
    except UnicodeError:
        _fail()
    return credentials, socket_info


def _read_windows_bootstrap() -> tuple[PrivateBackendCredentials, socket.socket]:
    prefix = sys.stdin.buffer.read(4)
    if len(prefix) != 4:
        _fail()
    declared = int.from_bytes(prefix, "big")
    if declared <= 0 or declared > BOOTSTRAP_MAX_BYTES:
        _fail()
    body = sys.stdin.buffer.read(declared)
    if len(body) != declared or sys.stdin.buffer.read(1):
        _fail()
    credentials, socket_info = decode_bootstrap_packet(prefix + body)
    if not socket_info:
        _fail()
    try:
        listener = socket.fromshare(socket_info)
    except (OSError, ValueError):
        _fail()
    return credentials, listener


def _parse_unix_descriptors(ancillary: list[tuple[int, int, bytes]], flags: int) -> list[int]:
    descriptor_values = array.array("i")
    descriptors: list[int] = []
    valid_control = len(ancillary) == 1
    try:
        for level, control_type, control_data in ancillary:
            if level != socket.SOL_SOCKET or control_type != socket.SCM_RIGHTS:
                valid_control = False
                continue
            complete = len(control_data) - (len(control_data) % descriptor_values.itemsize)
            received = array.array("i")
            received.frombytes(control_data[:complete])
            descriptors.extend(received)
            if len(control_data) != descriptor_values.itemsize:
                valid_control = False
        if flags or not valid_control or len(descriptors) != 1:
            _fail()
        return descriptors
    except (BootstrapError, OSError, ValueError):
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _fail()


def _read_unix_bootstrap() -> tuple[
    PrivateBackendCredentials,
    socket.socket,
    socket.socket,
]:
    channel = socket.socket(fileno=os.dup(sys.stdin.fileno()))
    descriptors: list[int] = []
    try:
        channel.settimeout(5.0)
        descriptor_size = array.array("i").itemsize
        packet, ancillary, flags, _address = channel.recvmsg(
            BOOTSTRAP_MAX_BYTES + 4,
            socket.CMSG_SPACE(descriptor_size),
        )
        descriptors = _parse_unix_descriptors(ancillary, flags)
        while len(packet) < 4:
            chunk = channel.recv(4 - len(packet))
            if not chunk:
                _fail()
            packet += chunk
        declared = int.from_bytes(packet[:4], "big")
        if declared <= 0 or declared > BOOTSTRAP_MAX_BYTES:
            _fail()
        expected = 4 + declared
        if len(packet) > expected:
            _fail()
        while len(packet) < expected:
            chunk = channel.recv(expected - len(packet))
            if not chunk:
                _fail()
            packet += chunk
        channel.setblocking(False)
        try:
            trailing = channel.recv(1, socket.MSG_PEEK)
        except BlockingIOError:
            trailing = None
        if trailing is not None:
            _fail()
        channel.setblocking(True)
        credentials, socket_info = decode_bootstrap_packet(packet)
        if socket_info:
            _fail()
    except (BootstrapError, OSError, ValueError):
        for descriptor in descriptors:
            os.close(descriptor)
        channel.close()
        _fail()
    try:
        listener = socket.socket(fileno=descriptors[0])
    except OSError:
        channel.close()
        os.close(descriptors[0])
        _fail()
    return credentials, listener, channel


def _listener_is_accepting(listener: socket.socket) -> bool:
    if sys.platform != "darwin":
        return listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1

    # Darwin rejects SO_ACCEPTCONN queries. A nonblocking accept proves the
    # state without calling listen; close one queued broker health probe.
    accepted: socket.socket | None = None
    try:
        listener.setblocking(False)
        try:
            accepted, _peer = listener.accept()
        except BlockingIOError:
            return True
        except OSError:
            return False
        return True
    finally:
        if accepted is not None:
            accepted.close()
        listener.setblocking(True)


def _validate_listener(listener: socket.socket) -> None:
    try:
        address = listener.getsockname()
        listener.set_inheritable(False)
        inheritable = listener.get_inheritable()
        accepting = _listener_is_accepting(listener)
    except OSError:
        _fail()
    if (
        listener.family != socket.AF_INET
        or listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM
        or not isinstance(address, tuple)
        or len(address) < 2
        or address[0] != "127.0.0.1"
        or type(address[1]) is not int
        or not 1 <= address[1] <= 65535
        or not accepting
        or inheritable
    ):
        _fail()


def _watch_broker_channel_and_exit(channel: socket.socket) -> None:
    try:
        channel.settimeout(None)
        channel.recv(1)
    except OSError:
        pass
    finally:
        channel.close()
        os._exit(0)


def _run(prepare: Callable[[], None] | None = None) -> int:
    if os.name == "nt":
        credentials, listener = _read_windows_bootstrap()
        broker_channel = None
    else:
        credentials, listener, broker_channel = _read_unix_bootstrap()
    sys.stdin.close()
    if broker_channel is not None:
        threading.Thread(
            target=_watch_broker_channel_and_exit,
            args=(broker_channel,),
            daemon=True,
        ).start()
    _validate_listener(listener)
    if prepare is not None:
        prepare()
    install_private_backend_credentials(credentials)

    import uvicorn

    from app.server import __version__, app

    if __version__ != credentials.product_version:
        listener.close()
        _fail()
    credentials = None
    config = uvicorn.Config(
        app,
        access_log=False,
        log_config=None,
        log_level="critical",
    )
    server = uvicorn.Server(config)
    server.run(sockets=[listener])
    listener.close()
    return 0


def main(prepare: Callable[[], None] | None = None) -> int:
    try:
        return _run(prepare)
    except BootstrapError as error:
        error.__traceback__ = None
        return 70
    except Exception as error:
        error.__traceback__ = None
        return 70


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BOOTSTRAP_MAGIC",
    "BOOTSTRAP_MAX_BYTES",
    "BOOTSTRAP_VERSION",
    "BootstrapError",
    "decode_bootstrap_packet",
    "main",
]
