"""One-use in-memory credentials for broker-owned backend startup."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

_PRODUCT_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
_SECRET_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.Lock()
_pending: PrivateBackendCredentials | None = None
_installed = False


@dataclass(frozen=True, repr=False)
class PrivateBackendCredentials:
    """Broker-only boot state; repr deliberately omits every value."""

    product_version: str
    api_key: str
    control_token: str

    def __repr__(self) -> str:
        return "PrivateBackendCredentials(<redacted>)"


def _valid(credentials: PrivateBackendCredentials) -> bool:
    return (
        isinstance(credentials, PrivateBackendCredentials)
        and _PRODUCT_VERSION_RE.fullmatch(credentials.product_version) is not None
        and _SECRET_RE.fullmatch(credentials.api_key) is not None
        and _SECRET_RE.fullmatch(credentials.control_token) is not None
        and credentials.api_key != credentials.control_token
    )


def install_private_backend_credentials(credentials: PrivateBackendCredentials) -> None:
    """Install one bootstrap value before ``app.server`` is imported."""

    global _installed, _pending
    if not _valid(credentials):
        raise RuntimeError("private_backend_bootstrap_failed") from None
    with _LOCK:
        if _installed or _pending is not None:
            raise RuntimeError("private_backend_bootstrap_failed") from None
        _pending = credentials
        _installed = True


def consume_private_backend_credentials() -> PrivateBackendCredentials | None:
    """Return the pending value once and drop the bootstrap-module reference."""

    global _pending
    with _LOCK:
        credentials = _pending
        _pending = None
    return credentials


__all__ = [
    "PrivateBackendCredentials",
    "consume_private_backend_credentials",
    "install_private_backend_credentials",
]
