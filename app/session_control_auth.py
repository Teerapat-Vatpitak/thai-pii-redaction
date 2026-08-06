"""Session-bound authorization for the trusted local control plane.

The boot secret stays in the native/backend trust domain. Browser, Office, and
extension code receive neither that secret nor a disposal authorization.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
from dataclasses import dataclass

_AUTH_VERSION = "v1"
_AUTH_CONTEXT = b"aiguard-session-disposal:v1"
_AUTH_NONCE_BYTES = 16
_AUTH_MAX_LIFETIME_MS = 60_000
_AUTH_TOKEN_MAX_LENGTH = 128
_AUTH_PART = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class VerifiedDisposalAuthorization:
    fingerprint: bytes
    expires_at_ms: int


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes | None:
    if not value or not _AUTH_PART.fullmatch(value):
        return None
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError):
        return None


def _signed_message(session_id: str, expires_at_ms: int, nonce: bytes) -> bytes:
    return b"\0".join(
        (
            _AUTH_CONTEXT,
            session_id.encode("utf-8"),
            str(expires_at_ms).encode("ascii"),
            nonce,
        )
    )


def make_session_disposal_authorization(
    control_secret: str,
    session_id: str,
    *,
    now: float,
    lifetime_s: float = 30.0,
    nonce: bytes | None = None,
) -> str:
    """Create one short-lived authorization in the trusted control process."""
    if not control_secret or not session_id:
        raise ValueError("control authority is unavailable")
    if not math.isfinite(now) or not math.isfinite(lifetime_s):
        raise ValueError("invalid authorization lifetime")
    lifetime_ms = int(lifetime_s * 1000)
    if lifetime_ms <= 0 or lifetime_ms > _AUTH_MAX_LIFETIME_MS:
        raise ValueError("invalid authorization lifetime")
    selected_nonce = secrets.token_bytes(_AUTH_NONCE_BYTES) if nonce is None else nonce
    if not isinstance(selected_nonce, bytes) or len(selected_nonce) != _AUTH_NONCE_BYTES:
        raise ValueError("invalid authorization nonce")

    expires_at_ms = math.floor(now * 1000) + lifetime_ms
    signature = hmac.new(
        control_secret.encode("utf-8"),
        _signed_message(session_id, expires_at_ms, selected_nonce),
        hashlib.sha256,
    ).digest()
    return ".".join(
        (
            _AUTH_VERSION,
            str(expires_at_ms),
            _encode(selected_nonce),
            _encode(signature),
        )
    )


def verify_session_disposal_authorization(
    control_secret: str | None,
    session_id: str,
    supplied: str | None,
    *,
    now: float,
) -> VerifiedDisposalAuthorization | None:
    """Verify target binding, lifetime, and signature without exposing detail."""
    if (
        not control_secret
        or not session_id
        or not supplied
        or len(supplied) > _AUTH_TOKEN_MAX_LENGTH
        or not math.isfinite(now)
    ):
        return None
    try:
        supplied.encode("ascii")
    except (UnicodeEncodeError, AttributeError):
        return None

    parts = supplied.split(".")
    if len(parts) != 4 or parts[0] != _AUTH_VERSION:
        return None
    expires_text, nonce_text, signature_text = parts[1:]
    if not re.fullmatch(r"[1-9][0-9]{0,15}", expires_text):
        return None
    expires_at_ms = int(expires_text)
    now_ms = now * 1000
    remaining_ms = expires_at_ms - now_ms
    if remaining_ms <= 0 or remaining_ms > _AUTH_MAX_LIFETIME_MS:
        return None

    nonce = _decode(nonce_text)
    signature = _decode(signature_text)
    if (
        nonce is None
        or len(nonce) != _AUTH_NONCE_BYTES
        or signature is None
        or len(signature) != hashlib.sha256().digest_size
    ):
        return None
    expected = hmac.new(
        control_secret.encode("utf-8"),
        _signed_message(session_id, expires_at_ms, nonce),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    return VerifiedDisposalAuthorization(
        fingerprint=hashlib.sha256(supplied.encode("ascii")).digest(),
        expires_at_ms=expires_at_ms,
    )
