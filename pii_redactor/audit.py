"""Audit logging for process and security events.

SECURITY-CRITICAL:
- Logs are written only to local disk
- Logs NEVER contain original PII, pseudonyms, or vault content
- Logs contain only: step names, timestamps, counts, safe flags, error types,
  non-authorizing correlation IDs, layer names, access counts, retry counts,
  and rollback flags
"""

import json
import os
import re
import time
from pathlib import Path

# Allowlist for characters permitted in the correlation-ID part of a log
# filename. `session_id` remains the legacy parameter/key name, but production
# callers pass a fresh operation ID, never a live session authority.
_SESSION_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")

# Hosted mode: AIGUARD_AUDIT_STDOUT=1 emits each entry as one JSON line on
# stdout instead of appending files. Container platforms rotate stdout
# (Docker json-file max-size) and surface it in their log viewers, while a
# bind-mounted file would grow unbounded with no rotation and stay invisible
# to stdout-tailing tools. Entries are PII-free by this module's contract, so
# stdout adds no exposure. Read dynamically so tests can flip it per-case.
_STDOUT_ENV = "AIGUARD_AUDIT_STDOUT"


def _stdout_mode() -> bool:
    return os.environ.get(_STDOUT_ENV) == "1"


def _emit(entry: dict, path: Path) -> Path:
    """Write one audit entry to stdout (hosted) or append to `path` (default).

    In stdout mode the returned path is where the entry WOULD have been
    written; no file is created or touched.
    """
    if _stdout_mode():
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        return path
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def _log_path(session_id: str, log_type: str, output_dir: str) -> Path:
    """
    Construct the path for an audit log file.

    Args:
        session_id: Non-authorizing correlation ID (legacy parameter name)
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
        session_id: Non-authorizing correlation ID (legacy parameter name)
        step: Step name (e.g., "step1_ingest", "step6_reverse")
        entity_count: Number of entities processed
        validation_result: Safe status such as "prepared", "blocked", "pass",
            "fail", or "warn"
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
    return _emit(entry, _log_path(session_id, "process", output_dir))


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
        session_id: Non-authorizing correlation ID (legacy parameter name)
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
    return _emit(entry, _log_path(session_id, "security", output_dir))
