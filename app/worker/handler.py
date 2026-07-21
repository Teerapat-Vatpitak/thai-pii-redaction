"""Job handler — the platform queue worker's KNOWN half.

PROVISIONAL JOB SCHEMA (2026-07-21, pre-spec): the AI for Thai deployment
spec was not yet published when this was written, so the wire schema below is
OURS. When the real spec lands, adapt `parse_job` / `format_result` (and the
transport) — nothing below `_OPERATIONS` should need to change.

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

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.ingest.text_cleaner import clean, clean_length_preserving
from pii_redactor.stateless import (
    StatelessLeakError,
    restore_stateless,
    sanitize_stateless,
)


def _op_sanitize(payload: dict) -> dict:
    text = payload["text"]
    if not text or not text.strip():
        raise ValueError("empty text")
    mode = payload.get("mode", "token")
    out = sanitize_stateless(clean(text).text, mode=mode, salt=uuid.uuid4().hex)
    return {
        "sanitized_text": out.sanitized_text,
        "mapping": out.mapping,
        "entities": out.entities,
        "entity_type_counts": out.entity_type_counts,
        "section26": out.section26,
        "warnings": out.warnings,
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
    "restore": _op_restore,
    "analyze": _op_analyze,
    "detect": _op_detect,
}


def handle_job(job: dict) -> dict:
    """Run one job. Never raises — a poison job must not kill the worker."""
    job_id = str(job.get("job_id", ""))
    operation = str(job.get("operation", ""))
    base = {"job_id": job_id, "operation": operation}

    op = _OPERATIONS.get(operation)
    if op is None:
        return {
            **base,
            "status": "error",
            "error": {"type": "unknown_operation", "message": f"unsupported: {operation}"},
        }
    try:
        return {**base, "status": "ok", "result": op(dict(job.get("payload") or {}))}
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
