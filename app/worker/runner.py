"""Run loop: poll -> handle -> submit, forever or until told to stop.

Logs carry job_id / operation / status / latency only — never payload text
(VAULT-4 applies to the worker too). A submit failure is logged and the
result dropped; the platform's retry story is unknown until the spec lands,
so we deliberately do NOT retry (at-most-once) rather than invent one.
"""

from __future__ import annotations

import logging
import threading
import time

from app.worker.handler import handle_job
from app.worker.transport import Transport

logger = logging.getLogger(__name__)


def run(
    transport: Transport,
    *,
    handler=handle_job,
    stop: threading.Event | None = None,
    max_jobs: int | None = None,
    idle_sleep_s: float = 2.0,
) -> int:
    """Process jobs until `stop` is set or `max_jobs` handled. Returns count."""
    stop = stop or threading.Event()
    processed = 0
    while not stop.is_set():
        if max_jobs is not None and processed >= max_jobs:
            break
        job = transport.poll()
        if job is None:
            if max_jobs is not None:
                break  # bounded runs never sleep-wait
            stop.wait(idle_sleep_s)
            continue
        start = time.time()
        result = handler(job)
        try:
            transport.submit(result)
        except Exception as e:  # keep the loop alive
            logger.error("submit failed job_id=%s error=%s", result.get("job_id"), type(e).__name__)
        processed += 1
        logger.info(
            "job done job_id=%s operation=%s status=%s latency_ms=%.0f",
            result.get("job_id"),
            result.get("operation"),
            result.get("status"),
            (time.time() - start) * 1000,
        )
    return processed
