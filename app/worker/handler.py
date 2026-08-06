"""Job handler for the internal v1 local failure/retry emulator.

This schema is ours and is not the official AI for Thai delivery contract.
The current hosted path uses HTTP/FastAPI and bypasses this queue envelope.

    job    = {"contract_version": 1, "job_id": str,
              "operation": <op>, "payload": {...}}
    result = {"contract_version": 1, "job_id": str,
              "operation": <op>, "status": "ok",
              "result": {...}}
           | {"contract_version": 1, "job_id": str,
              "operation": <op>, "status": "error",
              "error": {"type": str, "message": str}}

Missing ``contract_version`` is accepted as v1 for compatibility with the
original provisional fixtures. New adapters and fixtures must send it.

Declared errors are fixed and value-free. The generic v1 poison barrier still
exports an exception class name pending provider-orchestration cleanup; it does
not copy the exception message or payload text.
"""

from __future__ import annotations

import uuid

from app.worker.contract import CONTRACT_VERSION, EnvelopeError, validate_envelope
from pii_redactor.ai_client import (
    DEFAULT_SYSTEM_PROMPT,
    ProviderCallError,
    complete_provider_call,
    get_provider_factories,
)
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.ner_failure import NERFailureError, ner_failure_metadata
from pii_redactor.guard.injection import scan_injection, to_wire
from pii_redactor.ingest.text_cleaner import clean, clean_length_preserving
from pii_redactor.leak_guard import (
    OutboundPolicyError,
    enforce_outbound_policy,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.report import analyze_text
from pii_redactor.safe_errors import discard_exception_graph
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
    residual_failure = False
    try:
        out = sanitize_stateless(clean(text).text, mode=mode, salt=uuid.uuid4().hex)
    except (OutboundPolicyError, StatelessLeakError) as error:
        discard_exception_graph(error)
        residual_failure = True
    if residual_failure:
        payload = None
        text = ""
        out = None
        raise _SafeJobError("residual_pii", "outbound residual detected")
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


_PROVIDER_FACTORIES = get_provider_factories()


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
    provider_failure = None
    try:
        provider = factory()
    except ValueError as error:
        discard_exception_graph(error)
        provider_failure = ("provider_unavailable", "provider unavailable")
    except Exception as error:
        discard_exception_graph(error)
        provider_failure = ("provider_failed", "AI provider call failed")
    if provider_failure is not None:
        payload = None
        text = ""
        provider_name = ""
        factory = None
        provider = None
        raise _SafeJobError(*provider_failure)

    residual_failure = False
    try:
        masked = sanitize_stateless(clean(text).text, mode=mode, salt=uuid.uuid4().hex)
    except (OutboundPolicyError, StatelessLeakError) as error:
        discard_exception_graph(error)
        residual_failure = True
    if not residual_failure:
        try:
            enforce_outbound_policy(
                masked.sanitized_text,
                guard_context=masked.guard_context,
                scan_leaks=scan_outbound_leaks,
                scan_residual=scan_residual_signals,
            )
        except OutboundPolicyError as error:
            discard_exception_graph(error)
            residual_failure = True
    if residual_failure:
        payload = None
        text = ""
        provider_name = ""
        factory = None
        provider = None
        masked = None
        error = None
        raise _SafeJobError("residual_pii", "outbound residual detected")

    provider_failed = False
    try:
        ai_text = complete_provider_call(
            provider,
            DEFAULT_SYSTEM_PROMPT,
            masked.sanitized_text,
        )
    except ProviderCallError as error:
        discard_exception_graph(error)
        provider_failed = True
    if provider_failed:
        payload = None
        text = ""
        provider_name = ""
        factory = None
        provider = None
        masked = None
        ai_text = ""
        raise _SafeJobError("provider_failed", "AI provider call failed")

    restore_failed = False
    try:
        restored = restore_stateless(
            ai_text,
            mapping=masked.mapping,
            mode=mode,
        )
    except Exception as error:
        discard_exception_graph(error)
        restore_failed = True
    if restore_failed:
        # Restoration defects get their own category; the outer poison barrier
        # collapsing them into job_failed hides exactly the failures the
        # roundtrip exists to prevent.
        payload = None
        text = ""
        provider_name = ""
        factory = None
        provider = None
        masked = None
        ai_text = ""
        restored = None
        raise _SafeJobError("restore_failed", "restore failed")
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
    restore_failed = False
    try:
        out = restore_stateless(payload["text"], mapping=payload["mapping"])
    except Exception as error:
        discard_exception_graph(error)
        restore_failed = True
    if restore_failed:
        payload = None
        out = None
        raise _SafeJobError("restore_failed", "restore failed")
    return {
        "restored_text": out.restored_text,
        "replaced_count": out.replaced_count,
        "leftover_pseudonyms": out.leftover_pseudonyms,
        "warnings": out.warnings,
    }


def _op_analyze(payload: dict) -> dict:
    text = payload["text"]
    if not text or not text.strip():
        raise ValueError("empty text")
    return analyze_text(clean(text).text)


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


def _envelope_error_result(error: EnvelopeError) -> dict:
    result = {
        "contract_version": CONTRACT_VERSION,
        "job_id": error.job_id,
        "operation": error.operation,
        "status": "error",
        "error": {"type": error.error_type, "message": error.safe_message},
    }
    discard_exception_graph(error)
    return result


def handle_job(job: object) -> dict:
    """Run one job. Never raises (except process-signal exceptions like KeyboardInterrupt) — a poison job must not kill the worker."""
    try:
        envelope = validate_envelope(job)
    except EnvelopeError as error:
        return _envelope_error_result(error)

    operation = envelope.operation
    base = {
        "contract_version": CONTRACT_VERSION,
        "job_id": envelope.job_id,
        "operation": operation,
    }

    op = _OPERATIONS.get(operation)
    if op is None:
        return {
            **base,
            "status": "error",
            "error": {"type": "unknown_operation", "message": "unsupported operation"},
        }
    try:
        return {**base, "status": "ok", "result": op(envelope.payload)}
    except _SafeJobError as error:
        error_type = error.error_type
        safe_message = error.safe_message
        discard_exception_graph(error)
        return {
            **base,
            "status": "error",
            "error": {"type": error_type, "message": safe_message},
        }
    except (OutboundPolicyError, StatelessLeakError) as error:
        discard_exception_graph(error)
        return {
            **base,
            "status": "error",
            "error": {
                "type": "residual_pii",
                "message": "outbound residual detected",
            },
        }
    except NERFailureError as error:
        error_type, _category, _count = ner_failure_metadata(error)
        discard_exception_graph(error)
        safe_message = (
            "explicit TNER result incomplete"
            if error_type == "ner_incomplete"
            else "explicit TNER unavailable"
        )
        return {
            **base,
            "status": "error",
            "error": {"type": error_type, "message": safe_message},
        }
    except Exception as error:  # poison-job barrier, type name only
        error_type = type(error).__name__
        discard_exception_graph(error)
        return {
            **base,
            "status": "error",
            "error": {"type": "job_failed", "message": error_type},
        }
