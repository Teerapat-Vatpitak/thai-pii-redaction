"""Internal worker-envelope contract and privacy-safe validation.

This is the local failure/retry emulator's versioned seam, not the AI for Thai
wire protocol. The current official integration uses HTTP/FastAPI and bypasses
this queue envelope.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = 1
DEFAULT_MAX_ENVELOPE_BYTES = 1024 * 1024

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Envelope:
    contract_version: int
    job_id: str
    operation: str
    payload: dict[str, Any]


class EnvelopeError(ValueError):
    """A public-safe envelope error with already-sanitized routing fields."""

    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        job_id: str = "",
        operation: str = "",
    ):
        self.error_type = error_type
        self.safe_message = message
        self.job_id = job_id
        self.operation = operation
        super().__init__(message)


def configured_max_envelope_bytes() -> int:
    raw = os.environ.get("AIGUARD_MAX_JOB_BYTES", "")
    if not raw:
        return DEFAULT_MAX_ENVELOPE_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_ENVELOPE_BYTES
    return value if value > 0 else DEFAULT_MAX_ENVELOPE_BYTES


def safe_job_id(value: object) -> str:
    return value if isinstance(value, str) and _IDENTIFIER_RE.fullmatch(value) else ""


def safe_operation(value: object) -> str:
    return value if isinstance(value, str) and _OPERATION_RE.fullmatch(value) else ""


def envelope_fingerprint(job: object) -> str | None:
    """Return a PII-opaque digest for duplicate comparison, never raw JSON."""

    try:
        encoded = json.dumps(
            job,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def validate_envelope(job: object, *, max_bytes: int | None = None) -> Envelope:
    if not isinstance(job, dict):
        raise EnvelopeError("invalid_envelope", "job must be an object")

    job_id = safe_job_id(job.get("job_id"))
    operation = safe_operation(job.get("operation"))
    if not job_id:
        raise EnvelopeError(
            "invalid_envelope",
            "job_id must be a safe opaque identifier",
            operation=operation,
        )
    if not operation:
        raise EnvelopeError(
            "invalid_envelope",
            "operation must be a safe identifier",
            job_id=job_id,
        )

    version = job.get("contract_version", CONTRACT_VERSION)
    if type(version) is not int or version != CONTRACT_VERSION:
        raise EnvelopeError(
            "unsupported_contract_version",
            "unsupported worker contract version",
            job_id=job_id,
            operation=operation,
        )

    payload = job.get("payload")
    if not isinstance(payload, dict):
        raise EnvelopeError(
            "invalid_envelope",
            "payload must be an object",
            job_id=job_id,
            operation=operation,
        )

    try:
        encoded = json.dumps(
            job,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EnvelopeError(
            "invalid_envelope",
            "job must be JSON serializable",
            job_id=job_id,
            operation=operation,
        ) from exc

    limit = configured_max_envelope_bytes() if max_bytes is None else max_bytes
    if len(encoded) > limit:
        raise EnvelopeError(
            "payload_too_large",
            "job exceeds the configured envelope limit",
            job_id=job_id,
            operation=operation,
        )

    return Envelope(
        contract_version=CONTRACT_VERSION,
        job_id=job_id,
        operation=operation,
        payload=payload,
    )
