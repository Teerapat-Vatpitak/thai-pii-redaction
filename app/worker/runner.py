"""Run loop: poll -> handle -> submit, forever or until told to stop.

Logs carry a one-way job reference, operation, status, latency, and on failure
an exception class name—never the raw job ID, exception message, or payload
text. The v1 class-name field remains open cleanup work. A bounded in-memory
result cache prevents a same-process redelivery from repeating a provider side
effect after result submission fails. This local emulator does not claim
official delivery, retry, or acknowledgement semantics.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.worker.contract import (
    CONTRACT_VERSION,
    envelope_fingerprint,
    safe_job_id,
    safe_operation,
)
from app.worker.handler import handle_job
from app.worker.transport import Transport
from pii_redactor.safe_errors import discard_exception_graph

logger = logging.getLogger(__name__)

DEFAULT_IDEMPOTENCY_CAPACITY = 256


@dataclass
class _CachedResult:
    fingerprint: str
    result: dict


class _ResultCache:
    """Bounded, process-local duplicate protection; never persisted."""

    def __init__(self, capacity: int):
        self._capacity = max(0, capacity)
        self._entries: OrderedDict[str, _CachedResult] = OrderedDict()

    def lookup(self, job_id: str, fingerprint: str) -> tuple[str, dict | None]:
        entry = self._entries.get(job_id)
        if entry is None:
            return "miss", None
        self._entries.move_to_end(job_id)
        if entry.fingerprint != fingerprint:
            return "conflict", None
        return "hit", copy.deepcopy(entry.result)

    def store(self, job_id: str, fingerprint: str, result: dict) -> None:
        if self._capacity == 0:
            return
        self._entries[job_id] = _CachedResult(fingerprint, copy.deepcopy(result))
        self._entries.move_to_end(job_id)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


def _job_ref(job_id: object) -> str:
    if not isinstance(job_id, str) or not job_id:
        return "missing"
    return hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:12]


def _duplicate_conflict(job: object) -> dict:
    job_dict = job if isinstance(job, dict) else {}
    return {
        "contract_version": CONTRACT_VERSION,
        "job_id": safe_job_id(job_dict.get("job_id")),
        "operation": safe_operation(job_dict.get("operation")),
        "status": "error",
        "error": {
            "type": "duplicate_conflict",
            "message": "job_id was reused with a different envelope",
        },
    }


def run(
    transport: Transport,
    *,
    handler=handle_job,
    stop: threading.Event | None = None,
    max_jobs: int | None = None,
    idle_sleep_s: float = 2.0,
    idempotency_capacity: int = DEFAULT_IDEMPOTENCY_CAPACITY,
) -> int:
    """Process jobs until `stop` is set or `max_jobs` handled. Returns count."""
    stop = stop or threading.Event()
    processed = 0
    cache = _ResultCache(idempotency_capacity)
    try:
        while not stop.is_set():
            if max_jobs is not None and processed >= max_jobs:
                break
            try:
                job = transport.poll()
            except Exception as error:  # defense in depth — keep the worker alive
                error_type = type(error).__name__
                discard_exception_graph(error)
                error = None
                logger.warning("poll raised %s", error_type)
                job = None
            if job is None:
                if max_jobs is not None:
                    break  # bounded runs never sleep-wait
                stop.wait(idle_sleep_s)
                continue
            start = time.time()
            job_dict = job if isinstance(job, dict) else {}
            cache_job_id = safe_job_id(job_dict.get("job_id"))
            fingerprint = envelope_fingerprint(job)
            cache_state = "miss"
            result = None
            if cache_job_id and fingerprint:
                cache_state, result = cache.lookup(cache_job_id, fingerprint)
            if cache_state == "conflict":
                result = _duplicate_conflict(job)
            elif cache_state == "miss":
                try:
                    result = handler(job)
                except Exception as error:  # substituted handler may break the promise
                    error_type = type(error).__name__
                    discard_exception_graph(error)
                    error = None
                    logger.error("handler raised %s", error_type)
                    result = {
                        "contract_version": CONTRACT_VERSION,
                        "job_id": cache_job_id,
                        "operation": safe_operation(job_dict.get("operation")),
                        "status": "error",
                        "error": {"type": "handler_crashed", "message": error_type},
                    }
                if cache_job_id and fingerprint:
                    cache.store(cache_job_id, fingerprint, result)
            try:
                transport.submit(result)
            except Exception as error:  # keep the loop alive
                error_type = type(error).__name__
                job_ref = _job_ref(result.get("job_id"))
                discard_exception_graph(error)
                error = None
                logger.error(
                    "submit failed job_ref=%s error=%s",
                    job_ref,
                    error_type,
                )
            processed += 1
            logger.info(
                "job done job_ref=%s operation=%s status=%s replayed=%s latency_ms=%.0f",
                _job_ref(result.get("job_id")),
                result.get("operation"),
                result.get("status"),
                cache_state == "hit",
                (time.time() - start) * 1000,
            )
        return processed
    finally:
        cache.clear()
