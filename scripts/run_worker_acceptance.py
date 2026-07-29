"""Repeatable, PII-free acceptance runner for the provisional queue worker.

This validates AI Guard's internal contract and transport seam only. It is not
official AI for Thai deployment evidence.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.worker import handler as worker_handler  # noqa: E402
from app.worker.contract import CONTRACT_VERSION  # noqa: E402
from app.worker.emulator import EmulatedTransport  # noqa: E402
from app.worker.handler import handle_job  # noqa: E402
from app.worker.runner import run  # noqa: E402

SYNTHETIC_TEXT = "ผมชื่อ นายสมชาย ใจดี โทร 081-234-5678"
HONEYTOKEN = "AIGUARD-HONEYTOKEN-DO-NOT-LOG-0812345678"


class _CountingIdentityProvider:
    calls = 0

    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        type(self).calls += 1
        return user


def _job(job_id: str, operation: str, payload: dict) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "job_id": job_id,
        "operation": operation,
        "payload": payload,
    }


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _run_contract_operations() -> dict:
    planned = [
        ("detect", {"text": SYNTHETIC_TEXT}),
        ("sanitize", {"text": SYNTHETIC_TEXT, "mode": "token"}),
        ("analyze", {"text": SYNTHETIC_TEXT}),
        ("roundtrip", {"text": SYNTHETIC_TEXT, "mode": "token", "provider": "fake"}),
    ]
    # Nothing is conditional any more: analyze moved into the core, so every
    # operation runs on a core-only install. The key stays in the record
    # shape so consumers of this JSON do not have to change.
    skipped: list[str] = []
    exercised = [operation for operation, _ in planned if operation not in skipped]
    jobs = [
        _job(f"accept-{operation}", operation, payload)
        for operation, payload in planned
        if operation not in skipped
    ]
    transport = EmulatedTransport(jobs)
    processed = run(transport, max_jobs=len(jobs))
    _check(processed == len(jobs), "not every contract operation was processed")
    for result in transport.results:
        # Name the operation and its error type: this runs in CI, where the
        # only artifact is the log line and a bare "operation failed" costs a
        # local reproduction to learn which of the four broke.
        _check(
            result["status"] == "ok",
            f"operation {result['operation']} failed with "
            f"{result.get('error', {}).get('type', 'unknown')}",
        )
    _check(
        all(result["contract_version"] == CONTRACT_VERSION for result in transport.results),
        "contract version drift",
    )
    _check(
        "mapping" not in json.dumps(transport.results, ensure_ascii=False),
        "mapping crossed the result boundary",
    )
    return {
        "processed": processed,
        "exercised": exercised,
        "skipped": skipped,
        "statuses": ["ok"] * processed,
    }


def _run_duplicate_after_submit_failure() -> dict:
    _CountingIdentityProvider.calls = 0
    worker_handler._PROVIDER_FACTORIES["acceptance_identity"] = _CountingIdentityProvider
    try:
        job = _job(
            "accept-duplicate",
            "roundtrip",
            {
                "text": SYNTHETIC_TEXT,
                "mode": "token",
                "provider": "acceptance_identity",
            },
        )
        transport = EmulatedTransport([job, dict(job)], fail_submit_attempts={1})
        processed = run(transport, max_jobs=2)
    finally:
        worker_handler._PROVIDER_FACTORIES.pop("acceptance_identity", None)
    _check(processed == 2, "duplicate deliveries were not processed")
    _check(_CountingIdentityProvider.calls == 1, "duplicate repeated the provider side effect")
    _check(len(transport.results) == 1, "redelivery did not resubmit the cached result")
    _check(transport.results[0]["status"] == "ok", "cached result was not successful")
    return {
        "deliveries": processed,
        "provider_calls": _CountingIdentityProvider.calls,
        "successful_submissions": len(transport.results),
    }


def _run_failure_matrix() -> dict:
    conflict_a = _job("accept-conflict", "detect", {"text": SYNTHETIC_TEXT})
    conflict_b = _job("accept-conflict", "detect", {"text": SYNTHETIC_TEXT + " changed"})
    conflict_transport = EmulatedTransport([conflict_a, conflict_b])
    run(conflict_transport, max_jobs=2)
    _check(
        conflict_transport.results[1]["error"]["type"] == "duplicate_conflict",
        "conflicting duplicate was not rejected",
    )

    malformed = handle_job({"job_id": "accept-malformed", "operation": "detect", "payload": []})
    _check(malformed["error"]["type"] == "invalid_envelope", "malformed payload was accepted")

    unsupported = handle_job(
        {
            "contract_version": CONTRACT_VERSION + 1,
            "job_id": "accept-version",
            "operation": "detect",
            "payload": {"text": SYNTHETIC_TEXT},
        }
    )
    _check(
        unsupported["error"]["type"] == "unsupported_contract_version",
        "unsupported contract version was accepted",
    )

    previous_limit = os.environ.get("AIGUARD_MAX_JOB_BYTES")
    os.environ["AIGUARD_MAX_JOB_BYTES"] = "128"
    try:
        oversized = handle_job(_job("accept-oversized", "detect", {"text": SYNTHETIC_TEXT * 10}))
    finally:
        if previous_limit is None:
            os.environ.pop("AIGUARD_MAX_JOB_BYTES", None)
        else:
            os.environ["AIGUARD_MAX_JOB_BYTES"] = previous_limit
    _check(oversized["error"]["type"] == "payload_too_large", "oversized job was accepted")

    class TimeoutProvider:
        def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
            raise TimeoutError("synthetic provider timeout with private response body")

    worker_handler._PROVIDER_FACTORIES["acceptance_timeout"] = TimeoutProvider
    try:
        timed_out = handle_job(
            _job(
                "accept-timeout",
                "roundtrip",
                {
                    "text": SYNTHETIC_TEXT,
                    "mode": "token",
                    "provider": "acceptance_timeout",
                },
            )
        )
    finally:
        worker_handler._PROVIDER_FACTORIES.pop("acceptance_timeout", None)
    _check(timed_out["error"]["type"] == "provider_failed", "provider timeout was not contained")
    _check(SYNTHETIC_TEXT not in json.dumps(timed_out, ensure_ascii=False), "timeout leaked input")

    crashing_transport = EmulatedTransport(
        [_job("accept-handler-crash", "detect", {"text": SYNTHETIC_TEXT})]
    )

    def crashing_handler(job: object) -> dict:
        raise RuntimeError("synthetic worker crash with private payload")

    run(crashing_transport, handler=crashing_handler, max_jobs=1)
    crashed = crashing_transport.results[0]
    _check(crashed["error"]["type"] == "handler_crashed", "handler crash escaped the runner")
    _check(SYNTHETIC_TEXT not in json.dumps(crashed, ensure_ascii=False), "crash leaked input")

    return {
        "duplicate_conflict": "pass",
        "malformed": "pass",
        "unsupported_version": "pass",
        "oversized": "pass",
        "provider_timeout": "pass",
        "handler_crash": "pass",
    }


def _run_concurrency() -> dict:
    jobs = [
        _job(f"accept-concurrent-{index}", "detect", {"text": SYNTHETIC_TEXT}) for index in range(8)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(handle_job, jobs))
    _check(all(result["status"] == "ok" for result in results), "concurrent handler failed")
    return {"jobs": len(results), "workers": 8, "statuses": ["ok"] * len(results)}


def _run_honeytoken_log_check() -> dict:
    stream = io.StringIO()
    capture = logging.StreamHandler(stream)
    logger = logging.getLogger("app.worker.runner")
    previous_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        transport = EmulatedTransport([_job("accept-honeytoken", "unknown", {"text": HONEYTOKEN})])
        run(transport, max_jobs=1)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)
    rendered_logs = stream.getvalue()
    rendered_result = json.dumps(transport.results, ensure_ascii=False)
    _check(HONEYTOKEN not in rendered_logs, "honeytoken entered worker logs")
    _check(HONEYTOKEN not in rendered_result, "honeytoken entered public error result")
    return {
        "application_logs": "pass",
        "public_error": "pass",
        "raw_log_content_recorded": False,
    }


def run_acceptance() -> dict:
    started = time.perf_counter()
    checks = {
        "operations": _run_contract_operations(),
        "duplicate_delivery": _run_duplicate_after_submit_failure(),
        "failure_matrix": _run_failure_matrix(),
        "concurrency": _run_concurrency(),
        "honeytoken": _run_honeytoken_log_check(),
    }
    return {
        "schema_version": 1,
        "evidence_level": "local_platform_emulator",
        "official_platform_acceptance": False,
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "checks": checks,
        "external_blockers": [
            "official_account",
            "official_job_envelope",
            "official_ack_retry_semantics",
            "official_limits_and_log_policy",
            "cross_process_crash_idempotency",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts" / "acceptance" / "worker-emulator.json",
    )
    args = parser.parse_args()
    evidence = run_acceptance()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"PASS: provisional worker acceptance ({evidence['elapsed_ms']} ms)")
    print(f"evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
