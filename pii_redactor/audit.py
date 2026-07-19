"""Audit logging for process and security events.

SECURITY-CRITICAL:
- Logs are written only to local disk
- Logs NEVER contain original PII, pseudonyms, or vault content
- Logs contain only: step names, timestamps, counts, flags (which may contain entity_ids),
  error types, session_id, layer names, access counts, retry counts, rollback flags
"""

import json
import re
import time
from pathlib import Path

# Allowlist for characters permitted in the session_id part of a log filename;
# anything else (path separators, dots, ...) is replaced so a hostile
# session_id cannot traverse out of output_dir.
_SESSION_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _log_path(session_id: str, log_type: str, output_dir: str) -> Path:
    """
    Construct the path for an audit log file.

    Args:
        session_id: The session identifier (sanitized before use in the filename)
        log_type: Type of log ("process" or "security")
        output_dir: Directory to write logs to

    Returns:
        Path object for the audit log file
    """
    safe_id = _SESSION_ID_UNSAFE.sub("_", session_id)
    return Path(output_dir) / f"audit_{safe_id}_{log_type}.jsonl"


def write_process_log(
    session_id: str,
    step: str,
    entity_count: int,
    validation_result: str,
    flags: list[str],
    latency_ms: float,
    output_dir: str = ".",
) -> Path:
    """
    Write a process audit log entry.

    SECURITY: Never log original PII, pseudonyms, or vault content.
    Only: step name, timestamp, entity count, result, flags, latency.

    Args:
        session_id: The session identifier
        step: Step name (e.g., "step1_ingest", "step6_reverse")
        entity_count: Number of entities processed
        validation_result: "pass" | "fail" | "warn"
        flags: List of flag strings (may contain entity_ids only, never PII values)
        latency_ms: Processing time in milliseconds
        output_dir: Directory to write logs to (default: current directory)

    Returns:
        Path to the written log file
    """
    entry = {
        "type": "process",
        "session_id": session_id,
        "step": step,
        "timestamp": time.time(),
        "entity_count": entity_count,
        "validation_result": validation_result,
        "flags": flags,
        "latency_ms": latency_ms,
    }
    path = _log_path(session_id, "process", output_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def write_security_log(
    session_id: str,
    layer: str,
    pii_scan_result: str,
    mapping_table_access_count: int,
    retry_count: int,
    error_type: str | None,
    rollback_occurred: bool,
    output_dir: str = ".",
) -> Path:
    """
    Write a security audit log entry.

    SECURITY: Never log original PII, pseudonyms, or vault content.

    Args:
        session_id: The session identifier
        layer: Layer name (e.g., "layer1", "layer2", "layer3")
        pii_scan_result: "clean" | "unexpected_pii" | "expected_pii"
        mapping_table_access_count: Number of times vault was accessed
        retry_count: Number of retries attempted
        error_type: Type of error if any occurred (e.g., "encoding_error", "truncation")
        rollback_occurred: Whether a rollback was performed
        output_dir: Directory to write logs to (default: current directory)

    Returns:
        Path to the written log file
    """
    entry = {
        "type": "security",
        "session_id": session_id,
        "layer": layer,
        "timestamp": time.time(),
        "pii_scan_result": pii_scan_result,
        "mapping_table_access_count": mapping_table_access_count,
        "retry_count": retry_count,
        "error_type": error_type,
        "rollback_occurred": rollback_occurred,
    }
    path = _log_path(session_id, "security", output_dir)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path
