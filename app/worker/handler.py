"""Job handler — the platform queue worker's declared contract.

PLATFORM JOB SCHEMA (contract v1, 2026-07-22): this wire schema is ours rather
than a guess at a platform-owned contract. If an external queue uses a
different envelope, adapt that boundary in the transport/schema adapter; the
operations and privacy rules below remain the product contract.

    job    = {"job_id": str, "operation": <op>, "payload": {...}}
    result = {"job_id": str, "operation": <op>, "status": "ok",
              "result": {...}}
           | {"job_id": str, "operation": <op>, "status": "error",
              "error": {"type": str, "message": str}}

Error messages NEVER echo payload text — a queue result may be logged by the
platform, and payload text is PII by assumption (VAULT-4 applies here too).
"""

from __future__ import annotations

import uuid

from pii_redactor.ai_client import (
    DEFAULT_SYSTEM_PROMPT,
    ClaudeProvider,
    FakeLLMProvider,
    OllamaProvider,
    PathummaProvider,
)
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.guard.injection import scan_injection, to_wire
from pii_redactor.ingest.text_cleaner import clean, clean_length_preserving
from pii_redactor.stateless import (
    StatelessLeakError,
    restore_stateless,
    sanitize_stateless,
)


class _SafeJobError(Exception):
    """Expected job failure whose public fields contain no payload data."""

    def __init__(self, error_type: str, message: str):
        self.error_type = error_type
        self.safe_message = message
        super().__init__(message)


def _require_text(payload: dict) -> str:
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _SafeJobError("invalid_input", "text must be a non-empty string")
    return text


def _require_mode(payload: dict) -> str:
    mode = payload.get("mode", "token")
    if mode not in ("token", "surrogate"):
        raise _SafeJobError("invalid_input", "unsupported mode")
    return mode


def _op_sanitize(payload: dict) -> dict:
    text = _require_text(payload)
    mode = _require_mode(payload)
    out = sanitize_stateless(clean(text).text, mode=mode, salt=uuid.uuid4().hex)
    result = {
        "sanitized_text": out.sanitized_text,
        "entities": out.entities,
        "entity_type_counts": out.entity_type_counts,
        "section26": out.section26,
        "warnings": out.warnings,
    }
    # Mapping carries the originals. It must cross the queue result boundary
    # only after an exact JSON boolean opt-in; truthy strings/numbers are not
    # sufficient for this security-sensitive switch.
    if payload.get("include_mapping") is True:
        result["mapping"] = out.mapping
    return result


_PROVIDER_FACTORIES = {
    "fake": FakeLLMProvider,
    "pathumma": PathummaProvider,
    "ollama": OllamaProvider,
    "claude": ClaudeProvider,
}


def _op_roundtrip(payload: dict) -> dict:
    """Mask -> provider -> restore without exporting the transient mapping."""

    text = _require_text(payload)
    mode = _require_mode(payload)
    provider_name = payload.get("provider", "fake")
    if not isinstance(provider_name, str):
        raise _SafeJobError("invalid_provider", "unsupported provider")
    factory = _PROVIDER_FACTORIES.get(provider_name)
    if factory is None:
        raise _SafeJobError("invalid_provider", "unsupported provider")
    try:
        provider = factory()
    except ValueError as e:
        # Provider constructors use ValueError for missing credentials. Do not
        # expose their message: queue error results may be retained in logs.
        raise _SafeJobError("provider_unavailable", "provider unavailable") from e

    masked = sanitize_stateless(clean(text).text, mode=mode, salt=uuid.uuid4().hex)
    try:
        ai_text = provider.complete(DEFAULT_SYSTEM_PROMPT, masked.sanitized_text)
        if not isinstance(ai_text, str):
            raise TypeError("provider response is not text")
    except Exception as e:
        # Provider response bodies and exception messages are not safe for a
        # platform result. Preserve only a stable, non-sensitive category.
        raise _SafeJobError("provider_failed", "AI provider call failed") from e

    restored = restore_stateless(ai_text, mapping=masked.mapping)
    return {
        "sanitized_text": masked.sanitized_text,
        "ai_response_masked": ai_text,
        "restored_text": restored.restored_text,
        "entities": masked.entities,
        "entity_type_counts": masked.entity_type_counts,
        "provider_used": provider_name,
        "warnings": masked.warnings + restored.warnings,
        "guard": to_wire(scan_injection(text)),
    }


def _op_restore(payload: dict) -> dict:
    out = restore_stateless(payload["text"], mapping=payload["mapping"])
    return {
        "restored_text": out.restored_text,
        "replaced_count": out.replaced_count,
        "leftover_pseudonyms": out.leftover_pseudonyms,
        "warnings": out.warnings,
    }


def _op_analyze(payload: dict) -> dict:
    # late import: app.server pulls fastapi, which stays optional for a
    # worker-only deployment until the real spec says otherwise
    from app.server import _analyze_text

    text = payload["text"]
    if not text or not text.strip():
        raise ValueError("empty text")
    return _analyze_text(clean(text).text)


def _op_detect(payload: dict) -> dict:
    text = payload["text"]
    if not text or not text.strip():
        raise ValueError("empty text")
    entities = detect_all(clean_length_preserving(text))
    out = [
        {
            "start": e.span[0],
            "end": e.span[1],
            "data_type": e.data_type,
            "redact_type": e.redact_type,
        }
        for e in entities
    ]
    counts: dict[str, int] = {}
    for e in out:
        counts[e["data_type"]] = counts.get(e["data_type"], 0) + 1
    return {"entities": out, "entity_type_counts": counts}


_OPERATIONS = {
    "sanitize": _op_sanitize,
    "roundtrip": _op_roundtrip,
    "restore": _op_restore,
    "analyze": _op_analyze,
    "detect": _op_detect,
}


def handle_job(job: dict) -> dict:
    """Run one job. Never raises (except process-signal exceptions like KeyboardInterrupt) — a poison job must not kill the worker."""
    job_id = str(job.get("job_id", ""))
    operation = str(job.get("operation", ""))
    base = {"job_id": job_id, "operation": operation}

    op = _OPERATIONS.get(operation)
    if op is None:
        return {
            **base,
            "status": "error",
            "error": {"type": "unknown_operation", "message": "unsupported operation"},
        }
    try:
        return {**base, "status": "ok", "result": op(dict(job.get("payload") or {}))}
    except _SafeJobError as e:
        return {
            **base,
            "status": "error",
            "error": {"type": e.error_type, "message": e.safe_message},
        }
    except StatelessLeakError as e:
        return {
            **base,
            "status": "error",
            "error": {"type": "pii_leak_risk", "message": ",".join(e.leak_types)},
        }
    except Exception as e:  # poison-job barrier, type name only
        return {
            **base,
            "status": "error",
            "error": {"type": "job_failed", "message": type(e).__name__},
        }
