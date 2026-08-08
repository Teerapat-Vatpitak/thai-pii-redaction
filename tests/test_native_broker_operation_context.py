from __future__ import annotations

from collections.abc import Callable
from threading import Event

import pytest

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.native_broker_context import (
    BrokerOperationContext,
    NativeBrokerOperationError,
    NativeBrokerPayloadTooLarge,
    activate_broker_operation,
)
from pii_redactor.session_service import SessionService


class _GuardContext:
    def trusted_pseudonyms(self) -> set[str]:
        return set()


def _manual_watchdogs():
    scheduled: list[tuple[int, Event, Callable[[], None]]] = []

    def schedule(timeout_ms: int, done: Event, expire: Callable[[], None]) -> None:
        scheduled.append((timeout_ms, done, expire))

    return scheduled, schedule


def test_intermediate_cap_is_checked_at_both_authoritative_detector_entries():
    for detector in (
        lambda: detect_all("synthetic-intermediate"),
        lambda: scan_outbound_leaks("synthetic-intermediate", _GuardContext()),
    ):
        scheduled, schedule = _manual_watchdogs()
        context = BrokerOperationContext(
            outer_deadline_ms=60_000,
            local_detection_phases=1,
            intermediate_text_chars=4,
            local_phase_deadline_ms=360_000,
            terminate=lambda: None,
            schedule_watchdog=schedule,
        )
        with activate_broker_operation(context):
            with pytest.raises(NativeBrokerPayloadTooLarge):
                detector()
        assert [timeout for timeout, _done, _expire in scheduled] == [60_000]


def test_phase_and_outer_deadlines_are_independently_cancellable_without_values():
    scheduled, schedule = _manual_watchdogs()
    terminations: list[str] = []
    context = BrokerOperationContext(
        outer_deadline_ms=725_000,
        local_detection_phases=2,
        intermediate_text_chars=200_000,
        local_phase_deadline_ms=360_000,
        terminate=lambda: terminations.append("terminated"),
        schedule_watchdog=schedule,
    )
    with activate_broker_operation(context):
        assert detect_all("synthetic") == []
        assert [timeout for timeout, _done, _expire in scheduled] == [725_000, 360_000]
        scheduled[1][2]()
        assert terminations == []
        scheduled[0][2]()
        assert terminations == ["terminated"]
    assert "synthetic" not in repr(context)


def test_phase_budget_overrun_fails_closed_if_termination_returns_in_a_test():
    scheduled, schedule = _manual_watchdogs()
    context = BrokerOperationContext(
        outer_deadline_ms=60_000,
        local_detection_phases=0,
        intermediate_text_chars=None,
        local_phase_deadline_ms=None,
        terminate=lambda: None,
        schedule_watchdog=schedule,
    )
    with activate_broker_operation(context):
        with pytest.raises(NativeBrokerOperationError):
            detect_all("synthetic")


def _context_with_cap(*, phases: int, cap: int) -> BrokerOperationContext:
    _scheduled, schedule = _manual_watchdogs()
    return BrokerOperationContext(
        outer_deadline_ms=2_348_000,
        local_detection_phases=phases,
        intermediate_text_chars=cap,
        local_phase_deadline_ms=360_000,
        terminate=lambda: None,
        schedule_watchdog=schedule,
    )


def test_expanded_masked_text_is_rejected_before_rescan_and_never_published():
    service = SessionService()
    source = "1101700230708"
    with activate_broker_operation(_context_with_cap(phases=2, cap=len(source))):
        with pytest.raises(NativeBrokerPayloadTooLarge):
            service.sanitize_transaction(
                source,
                mode="token",
                finalize=lambda outcome: outcome,
            )
    assert service.session_count == 0


def test_expanded_restored_text_is_rejected_before_detector_and_keeps_prior_session():
    service = SessionService()
    source = "1101700230708"
    sanitized = service.sanitize_transaction(
        source,
        mode="token",
        finalize=lambda outcome: outcome,
    )
    with activate_broker_operation(_context_with_cap(phases=1, cap=len(source))):
        with pytest.raises(NativeBrokerPayloadTooLarge):
            service.restore(sanitized.session_id, sanitized.sanitized_text + "x")
    assert service.session_count == 1


def test_oversized_provider_output_is_rejected_before_restore_scan(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    import app.server as server

    calls: list[str] = []

    class OversizedProvider:
        def complete(self, _system: str, user: str, *, timeout: float = 60.0) -> str:
            calls.append(user)
            return "x" * 10

    monkeypatch.setitem(server._PROVIDER_FACTORIES, "broker-cap", OversizedProvider)
    with activate_broker_operation(_context_with_cap(phases=6, cap=9)):
        with pytest.raises(HTTPException) as error:
            server.roundtrip(
                server.RoundtripRequest(
                    text="synthetic",
                    mode="token",
                    provider="broker-cap",
                )
            )
    assert error.value.status_code == 413
    assert error.value.detail == "payload_too_large"
    assert calls == ["synthetic"]


def test_private_http_context_reaches_sync_detector_thread(monkeypatch):
    pytest.importorskip("fastapi")
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    import app.server as server

    observed: list[int] = []
    original = BrokerOperationContext.detector_phase

    @contextmanager
    def record_phase(self, text):
        observed.append(len(text))
        with original(self, text):
            yield

    monkeypatch.setattr(BrokerOperationContext, "detector_phase", record_phase)
    monkeypatch.setattr(server.app.state, "private_backend", True)
    monkeypatch.setattr(server, "_API_KEY", "synthetic-private-authority")
    client = TestClient(server.app, base_url="http://localhost")
    response = client.post(
        "/api/detect",
        json={"text": "synthetic"},
        headers={
            "X-AIGuard-Contract-Version": "2",
            "X-AIGuard-Key": "synthetic-private-authority",
            "X-AIGuard-Broker-Deadline-Ms": "360000",
            "X-AIGuard-Broker-Local-Detection-Phases": "1",
            "X-AIGuard-Broker-Intermediate-Text-Chars": "200000",
            "X-AIGuard-Broker-Local-Phase-Deadline-Ms": "360000",
        },
    )
    assert response.status_code == 200
    assert observed == [len("synthetic")]
