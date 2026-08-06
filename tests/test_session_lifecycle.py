"""Deterministic Phase 7 session expiry and cleanup coverage."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

import pytest

import pii_redactor.session_service as service_module
from pii_redactor.models import VaultRecord
from pii_redactor.session_service import (
    DisposalAuthorizationError,
    RestoreTransactionError,
    SessionExpiredError,
    SessionService,
)
from pii_redactor.session_vault import SessionVault


@dataclass
class _ManualTimer:
    delay: float
    callback: object
    started: bool = False
    cancelled: bool = False
    fired: bool = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self, *, include_cancelled: bool = False) -> None:
        if not self.cancelled or include_cancelled:
            self.fired = True
            self.callback()


class _ManualTimerFactory:
    def __init__(self) -> None:
        self.timers: list[_ManualTimer] = []

    def __call__(self, delay: float, callback) -> _ManualTimer:
        timer = _ManualTimer(delay=delay, callback=callback)
        self.timers.append(timer)
        return timer

    @property
    def latest(self) -> _ManualTimer:
        return self.timers[-1]


def _service(*, ttl_s: int = 100):
    clock = {"now": 1000.0}
    timers = _ManualTimerFactory()
    service = SessionService(
        ttl_s=ttl_s,
        now_fn=lambda: clock["now"],
        timer_factory=timers,
    )
    return service, clock, timers


def _write_synthetic_mapping(session, *, suffix: str) -> None:
    session.vault.write(
        VaultRecord(
            entity_id=f"synthetic-entity-{suffix}",
            original=f"synthetic-original-{suffix}",
            pseudonym=f"[synthetic-token-{suffix}]",
            type="TB",
            data_type="NAME",
            span=(0, 1),
            timestamp=1000.0,
        )
    )


@pytest.mark.parametrize(
    ("elapsed", "available"),
    [
        (99.999, True),
        (100.0, False),
        (100.001, False),
    ],
)
def test_expiry_boundary_is_half_open(elapsed, available):
    service, clock, _timers = _service()
    session_id, _session = service._get_or_create(None, None)
    clock["now"] += elapsed

    if available:
        assert service._get_or_create(session_id, None)[0] == session_id
    else:
        with pytest.raises(SessionExpiredError):
            service._get_or_create(session_id, None)


def test_timer_expires_idle_session_without_another_request():
    service, clock, timers = _service()
    session_id, session = service._get_or_create(None, None)
    session.vault.write(
        VaultRecord(
            entity_id="synthetic-entity",
            original="synthetic-original",
            pseudonym="[synthetic-token]",
            type="TB",
            data_type="NAME",
            span=(0, 1),
            timestamp=clock["now"],
        )
    )

    clock["now"] += 100
    timers.latest.fire()

    assert service.session_count == 0
    assert session.vault._table == {}
    assert session.vault._reverse == {}
    with pytest.raises(SessionExpiredError):
        service._get_or_create(session_id, None)


@pytest.mark.parametrize("error_type", [RuntimeError, SessionExpiredError])
def test_timer_callback_clock_exception_closes_and_cleans_service(error_type):
    service, _clock, timers = _service(ttl_s=10)
    _first_id, first = service._get_or_create(None, None)
    _write_synthetic_mapping(first, suffix="first")
    _second_id, second = service._get_or_create(None, None)
    _write_synthetic_mapping(second, suffix="second")
    live_timer = timers.latest

    def fail_clock():
        raise error_type("synthetic callback clock failure")

    service._now = fail_clock

    live_timer.fire()

    assert service._closed is True
    assert service.session_count == 0
    assert service._expiry_timer is None
    for session in (first, second):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


def test_timer_callback_failure_closes_before_waiting_request_can_enter():
    service, _clock, timers = _service(ttl_s=10)
    session_id, _session = service._get_or_create(None, None)
    live_timer = timers.latest
    clock_entered = threading.Event()
    release_clock = threading.Event()
    request_started = threading.Event()
    request_finished = threading.Event()
    callback_errors: list[BaseException] = []
    request_results = []
    request_errors: list[BaseException] = []

    def fail_after_pause():
        clock_entered.set()
        assert release_clock.wait(timeout=5)
        raise RuntimeError("synthetic callback clock failure")

    service._now = fail_after_pause

    def fire_callback():
        try:
            live_timer.fire()
        except BaseException as error:
            callback_errors.append(error)

    def request_session():
        request_started.set()
        try:
            request_results.append(service._get_or_create(session_id, None))
        except BaseException as error:
            request_errors.append(error)
        finally:
            request_finished.set()

    callback_thread = threading.Thread(target=fire_callback)
    callback_thread.start()
    assert clock_entered.wait(timeout=5)
    request_thread = threading.Thread(target=request_session)
    request_thread.start()
    assert request_started.wait(timeout=5)
    assert request_finished.wait(timeout=0.1) is False

    release_clock.set()
    callback_thread.join(timeout=5)
    request_thread.join(timeout=5)

    assert not callback_thread.is_alive()
    assert not request_thread.is_alive()
    assert callback_errors == []
    assert request_results == []
    assert len(request_errors) == 1
    assert isinstance(request_errors[0], SessionExpiredError)
    assert service._closed is True
    assert service.session_count == 0


@pytest.mark.parametrize("invalid_now", [math.nan, math.inf])
def test_timer_callback_nonfinite_clock_closes_and_cleans_service(invalid_now):
    service, _clock, timers = _service(ttl_s=10)
    _first_id, first = service._get_or_create(None, None)
    _write_synthetic_mapping(first, suffix="first")
    _second_id, second = service._get_or_create(None, None)
    _write_synthetic_mapping(second, suffix="second")
    live_timer = timers.latest
    clock_values = iter((invalid_now, 1005.0))
    clock_reads = 0

    def stateful_clock():
        nonlocal clock_reads
        clock_reads += 1
        return next(clock_values)

    service._now = stateful_clock

    live_timer.fire()

    assert clock_reads == 1
    assert service._closed is True
    assert service.session_count == 0
    assert service._expiry_timer is None
    for session in (first, second):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


def test_timer_expires_only_due_sessions_and_reschedules_next_deadline():
    service, clock, timers = _service()
    first_id, _first = service._get_or_create(None, None)
    clock["now"] += 10
    second_id, second = service._get_or_create(None, None)
    second.vault.write(
        VaultRecord(
            entity_id="second-entity",
            original="second-original",
            pseudonym="[second-token]",
            type="TB",
            data_type="NAME",
            span=(0, 1),
            timestamp=clock["now"],
        )
    )
    first_deadline_timer = timers.latest

    clock["now"] = 1100.0
    first_deadline_timer.fire()

    assert service.session_count == 1
    with pytest.raises(SessionExpiredError):
        service._get_or_create(first_id, None)
    assert service._get_or_create(second_id, None)[0] == second_id
    assert second.vault.get_by_pseudonym("[second-token]") is not None

    second_deadline_timer = timers.latest
    clock["now"] = 1200.0
    second_deadline_timer.fire()
    assert service.session_count == 0


def test_request_started_before_expiry_wins_over_stale_timer(monkeypatch):
    service, clock, timers = _service(ttl_s=10)
    outcome = service.sanitize("โทร 081-234-5678")
    expiry_timer = timers.latest
    clock["now"] = 1009.999

    in_restore = threading.Event()
    release_restore = threading.Event()
    real_reverse = service_module.reverse_map

    def slow_reverse(*args, **kwargs):
        in_restore.set()
        assert release_restore.wait(timeout=5)
        return real_reverse(*args, **kwargs)

    monkeypatch.setattr(service_module, "reverse_map", slow_reverse)
    restored = {}
    restore_thread = threading.Thread(
        target=lambda: restored.setdefault(
            "value",
            service.restore(outcome.session_id, outcome.sanitized_text),
        )
    )
    restore_thread.start()
    assert in_restore.wait(timeout=5)

    timer_entered = threading.Event()

    def fire_expiry():
        timer_entered.set()
        expiry_timer.fire(include_cancelled=True)

    expiry_thread = threading.Thread(target=fire_expiry)
    expiry_thread.start()
    assert timer_entered.wait(timeout=5)

    # The request may run past the old deadline. Successful completion owns a
    # fresh TTL; the blocked stale callback must not remove it afterward.
    clock["now"] = 1015.0
    release_restore.set()
    restore_thread.join(timeout=5)
    expiry_thread.join(timeout=5)

    assert not restore_thread.is_alive()
    assert not expiry_thread.is_alive()
    assert restored["value"].restored_text == "โทร 081-234-5678"
    assert service.session_count == 1
    assert service._sessions[outcome.session_id].last_access == 1015.0


def test_successful_restore_refreshes_access_and_timer_once():
    service, clock, timers = _service(ttl_s=10)
    session_id, session = service._get_or_create(None, None)
    prior_timer = timers.latest
    prior_timer_count = len(timers.timers)
    clock["now"] = 1005.0

    restored = service.restore(session_id, "   ")

    assert restored.restored_text == "   "
    assert session.last_access == 1005.0
    assert len(timers.timers) == prior_timer_count + 1
    assert prior_timer.cancelled is True
    assert timers.latest.delay == 10.0


def test_failed_restore_does_not_refresh_access_or_timer(monkeypatch):
    service, clock, timers = _service(ttl_s=10)
    session_id, session = service._get_or_create(None, None)
    prior_access = session.last_access
    prior_timer = timers.latest
    prior_timer_count = len(timers.timers)
    clock["now"] = 1005.0

    def fail_restore(*_args, **_kwargs):
        raise RuntimeError("synthetic restore failure")

    monkeypatch.setattr(service_module, "reverse_map", fail_restore)
    with pytest.raises(RestoreTransactionError, match="^restore failed$"):
        service.restore(session_id, "synthetic reply")

    assert session.last_access == prior_access
    assert service._expiry_timer is prior_timer
    assert prior_timer.cancelled is False
    assert len(timers.timers) == prior_timer_count


def test_repeated_failed_restores_do_not_extend_expiry(monkeypatch):
    service, clock, timers = _service(ttl_s=10)
    session_id, session = service._get_or_create(None, None)
    original_deadline_timer = timers.latest
    original_access = session.last_access

    def fail_restore(*_args, **_kwargs):
        raise RuntimeError("synthetic restore failure")

    monkeypatch.setattr(service_module, "reverse_map", fail_restore)
    for attempt_time in (1005.0, 1009.0, 1009.999):
        clock["now"] = attempt_time
        with pytest.raises(RestoreTransactionError, match="^restore failed$"):
            service.restore(session_id, "synthetic reply")
        assert session.last_access == original_access
        assert service._expiry_timer is original_deadline_timer

    clock["now"] = 1010.0
    original_deadline_timer.fire()

    assert service.session_count == 0
    with pytest.raises(SessionExpiredError):
        service.restore(session_id, "synthetic reply")


def test_failed_restore_immediately_before_expiry_cannot_retain_session(monkeypatch):
    service, clock, timers = _service(ttl_s=10)
    session_id, _session = service._get_or_create(None, None)
    original_deadline_timer = timers.latest

    monkeypatch.setattr(
        service_module,
        "reverse_map",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic restore failure")),
    )
    clock["now"] = 1009.999
    with pytest.raises(RestoreTransactionError, match="^restore failed$"):
        service.restore(session_id, "synthetic reply")

    clock["now"] = 1010.0
    original_deadline_timer.fire()

    assert service.session_count == 0


def test_failed_restore_racing_eager_expiry_is_deterministic(monkeypatch):
    service, clock, timers = _service(ttl_s=10)
    session_id, _session = service._get_or_create(None, None)
    original_deadline_timer = timers.latest
    restore_entered = threading.Event()
    release_restore = threading.Event()
    restore_errors: list[BaseException] = []

    def fail_after_pause(*_args, **_kwargs):
        restore_entered.set()
        assert release_restore.wait(timeout=5)
        raise RuntimeError("synthetic restore failure")

    monkeypatch.setattr(service_module, "reverse_map", fail_after_pause)

    def restore():
        try:
            service.restore(session_id, "synthetic reply")
        except BaseException as error:
            restore_errors.append(error)

    restore_thread = threading.Thread(target=restore)
    restore_thread.start()
    assert restore_entered.wait(timeout=5)

    clock["now"] = 1010.0
    expiry_thread = threading.Thread(target=original_deadline_timer.fire)
    expiry_thread.start()
    release_restore.set()
    restore_thread.join(timeout=5)
    expiry_thread.join(timeout=5)

    assert not restore_thread.is_alive()
    assert not expiry_thread.is_alive()
    assert len(restore_errors) == 1
    assert isinstance(restore_errors[0], RestoreTransactionError)
    assert service.session_count == 0


def test_failed_restore_does_not_modify_another_session(monkeypatch):
    service, clock, timers = _service(ttl_s=10)
    first_id, first = service._get_or_create(None, None)
    clock["now"] = 1001.0
    second_id, second = service._get_or_create(None, None)
    timer_before_failure = timers.latest
    timer_count = len(timers.timers)
    first_access = first.last_access
    second_access = second.last_access

    monkeypatch.setattr(
        service_module,
        "reverse_map",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic restore failure")),
    )
    clock["now"] = 1005.0
    with pytest.raises(RestoreTransactionError, match="^restore failed$"):
        service.restore(first_id, "synthetic reply")

    assert first.last_access == first_access
    assert second.last_access == second_access
    assert service._sessions[second_id] is second
    assert service._expiry_timer is timer_before_failure
    assert len(timers.timers) == timer_count


def test_managed_vault_cannot_independently_expire_service_admission():
    service, clock, _timers = _service(ttl_s=10)
    outcome = service.sanitize("โทร 081-234-5678")
    session = service._sessions[outcome.session_id]
    session.vault._last_access = time.monotonic() - 1000
    clock["now"] = 1009.999

    restored = service.restore(outcome.session_id, outcome.sanitized_text)

    assert restored.restored_text == "โทร 081-234-5678"
    assert service.session_count == 1


def test_disposal_racing_expiry_cleans_once():
    service, clock, timers = _service(ttl_s=10)
    session_id, session = service._get_or_create(None, None)
    expiry_timer = timers.latest
    clock["now"] += 10
    clear_calls = 0
    real_clear = session.vault.clear

    def counted_clear():
        nonlocal clear_calls
        clear_calls += 1
        real_clear()

    session.vault.clear = counted_clear
    start = threading.Barrier(3)
    dispose_results: list[bool] = []

    def expire():
        start.wait(timeout=5)
        expiry_timer.fire(include_cancelled=True)

    def dispose():
        start.wait(timeout=5)
        dispose_results.append(service.drop(session_id))

    expiry_thread = threading.Thread(target=expire)
    dispose_thread = threading.Thread(target=dispose)
    expiry_thread.start()
    dispose_thread.start()
    start.wait(timeout=5)
    expiry_thread.join(timeout=5)
    dispose_thread.join(timeout=5)

    assert clear_calls == 1
    assert service.session_count == 0
    assert dispose_results in ([True], [False])


def test_shutdown_racing_expiry_is_idempotent_and_cancels_timer():
    service, clock, timers = _service(ttl_s=10)
    _session_id, session = service._get_or_create(None, None)
    expiry_timer = timers.latest
    clock["now"] += 10
    clear_calls = 0
    real_clear = session.vault.clear

    def counted_clear():
        nonlocal clear_calls
        clear_calls += 1
        real_clear()

    session.vault.clear = counted_clear
    start = threading.Barrier(3)

    expiry_thread = threading.Thread(
        target=lambda: (
            start.wait(timeout=5),
            expiry_timer.fire(include_cancelled=True),
        )
    )
    shutdown_thread = threading.Thread(
        target=lambda: (
            start.wait(timeout=5),
            service.close(),
        )
    )
    expiry_thread.start()
    shutdown_thread.start()
    start.wait(timeout=5)
    expiry_thread.join(timeout=5)
    shutdown_thread.join(timeout=5)
    service.close()

    assert clear_calls == 1
    assert service.session_count == 0
    assert expiry_timer.cancelled or expiry_timer.fired
    assert service._expiry_timer is None


def test_cleanup_drops_every_session_owned_reference():
    service, _clock, timers = _service()
    outcome = service.sanitize("โทร 081-234-5678")
    session = service._sessions[outcome.session_id]
    assert session.entities
    assert session.trusted_sanitized_digests
    assert session.salt

    assert service.drop(outcome.session_id) is True

    assert session.entities == []
    assert session.trusted_sanitized_digests == ()
    assert session.salt == ""
    assert session.vault._table == {}
    assert session.vault._reverse == {}
    assert timers.latest.cancelled is True


def test_expiry_callback_after_disposal_cannot_recreate_or_reclean_session():
    service, clock, timers = _service(ttl_s=10)
    session_id, session = service._get_or_create(None, None)
    stale_timer = timers.latest
    clear_calls = 0
    real_clear = session.vault.clear

    def counted_clear():
        nonlocal clear_calls
        clear_calls += 1
        real_clear()

    session.vault.clear = counted_clear
    assert service.drop(session_id) is True
    clock["now"] += 10
    stale_timer.fire(include_cancelled=True)

    assert service.session_count == 0
    assert clear_calls == 1
    with pytest.raises(SessionExpiredError):
        service._get_or_create(session_id, None)


def test_timer_start_failure_closes_and_cleans_service(caplog):
    clock = {"now": 1000.0}

    class _FailingTimer:
        def start(self):
            raise RuntimeError("synthetic timer start failure")

        def cancel(self):
            return None

    service = SessionService(
        now_fn=lambda: clock["now"],
        timer_factory=lambda _delay, _callback: _FailingTimer(),
    )

    with pytest.raises(SessionExpiredError):
        service._get_or_create(None, None)

    assert service.session_count == 0
    assert "Session expiry scheduling failed; service closed" in caplog.text
    assert "synthetic timer start failure" not in caplog.text
    with pytest.raises(SessionExpiredError):
        service._get_or_create(None, None)


def test_restore_scheduler_clock_failure_closes_and_cleans_service():
    service, _clock, timers = _service(ttl_s=10)
    target_id, target = service._get_or_create(None, None)
    _write_synthetic_mapping(target, suffix="target")
    _other_id, other = service._get_or_create(None, None)
    _write_synthetic_mapping(other, suffix="other")
    live_timer = timers.latest
    timer_count = len(timers.timers)
    calls = 0

    def fail_during_reschedule():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("synthetic scheduler clock failure")
        return 1006.0

    service._now = fail_during_reschedule

    with pytest.raises(SessionExpiredError, match="^Session not found or expired$"):
        service.restore(target_id, "   ")

    assert calls == 3
    assert service._closed is True
    assert service.session_count == 0
    assert service._expiry_timer is None
    assert live_timer.cancelled is True
    assert len(timers.timers) == timer_count
    for session in (target, other):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


@pytest.mark.parametrize("invalid_access", [math.nan, math.inf])
def test_restore_nonfinite_commit_clock_closes_and_cleans_service(invalid_access):
    service, _clock, timers = _service(ttl_s=10)
    _other_id, other = service._get_or_create(None, None)
    _write_synthetic_mapping(other, suffix="other")
    target_id, target = service._get_or_create(None, None)
    _write_synthetic_mapping(target, suffix="target")
    live_timer = timers.latest
    timer_count = len(timers.timers)
    clock_values = iter((1005.0, invalid_access, 1005.0))
    clock_reads = 0

    def stateful_clock():
        nonlocal clock_reads
        clock_reads += 1
        return next(clock_values)

    service._now = stateful_clock

    with pytest.raises(SessionExpiredError, match="^Session not found or expired$"):
        service.restore(target_id, "   ")

    assert clock_reads == 2
    assert service._closed is True
    assert service.session_count == 0
    assert service._expiry_timer is None
    assert live_timer.cancelled is True
    assert len(timers.timers) == timer_count
    for session in (target, other):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


def test_expiry_reschedule_failure_cleans_detached_and_remaining_sessions():
    clock = {"now": 1000.0}
    fail_start = {"value": False}

    class _SwitchableTimer(_ManualTimer):
        def start(self):
            if fail_start["value"]:
                raise RuntimeError("synthetic replacement timer failure")
            super().start()

    def factory(delay, callback):
        return _SwitchableTimer(delay, callback)

    service = SessionService(
        ttl_s=10,
        now_fn=lambda: clock["now"],
        timer_factory=factory,
    )
    _first_id, first = service._get_or_create(None, None)
    _write_synthetic_mapping(first, suffix="first")
    clock["now"] += 1
    _second_id, second = service._get_or_create(None, None)
    _write_synthetic_mapping(second, suffix="second")
    fail_start["value"] = True
    clock["now"] = 1010.0

    with pytest.raises(SessionExpiredError):
        service.expire_due()

    assert service.session_count == 0
    assert service._lifecycle_tombstones == {}
    for session in (first, second):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


def test_disposal_reschedule_failure_cleans_target_and_remaining_session():
    fail_start = {"value": False}

    class _SwitchableTimer(_ManualTimer):
        def start(self):
            if fail_start["value"]:
                raise RuntimeError("synthetic replacement timer failure")
            super().start()

    service = SessionService(
        timer_factory=lambda delay, callback: _SwitchableTimer(delay, callback),
    )
    first_id, first = service._get_or_create(None, None)
    _write_synthetic_mapping(first, suffix="first")
    _second_id, second = service._get_or_create(None, None)
    _write_synthetic_mapping(second, suffix="second")
    fail_start["value"] = True

    with pytest.raises(SessionExpiredError):
        service.dispose_authenticated(
            first_id,
            authorization_fingerprint=b"a" * 32,
            authorization_expires_at_ms=10_000,
            authorization_now_ms_fn=lambda: 0,
        )

    assert service.session_count == 0
    assert service._used_disposal_authorizations == {}
    assert service._lifecycle_tombstones == {}
    for session in (first, second):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


def test_sanitize_eviction_reschedule_failure_cleans_old_and_staged_sessions(
    monkeypatch,
):
    fail_start = {"value": False}

    class _SwitchableTimer(_ManualTimer):
        def start(self):
            if fail_start["value"]:
                raise RuntimeError("synthetic replacement timer failure")
            super().start()

    service = SessionService(
        cap=1,
        timer_factory=lambda delay, callback: _SwitchableTimer(delay, callback),
    )
    first_outcome = service.sanitize("โทร 081-234-5678")
    first = service._sessions[first_outcome.session_id]
    staged_sessions = []
    real_stage = service._stage_sanitize_locked

    def capture_stage(*args, **kwargs):
        result = real_stage(*args, **kwargs)
        staged_sessions.append(result[1])
        return result

    monkeypatch.setattr(service, "_stage_sanitize_locked", capture_stage)
    fail_start["value"] = True

    with pytest.raises(SessionExpiredError):
        service.sanitize("โทร 089-876-5432")

    assert len(staged_sessions) == 1
    assert service.session_count == 0
    assert service._lifecycle_tombstones == {}
    for session in (first, staged_sessions[0]):
        assert session.vault._table == {}
        assert session.vault._reverse == {}
        assert session.entities == []
        assert session.trusted_sanitized_digests == ()
        assert session.salt == ""


def test_authenticated_disposal_waits_for_active_restore(monkeypatch):
    service = SessionService()
    outcome = service.sanitize("โทร 081-234-5678")
    session = service._sessions[outcome.session_id]
    clear_calls = 0
    real_clear = session.vault.clear

    def counted_clear():
        nonlocal clear_calls
        clear_calls += 1
        real_clear()

    session.vault.clear = counted_clear
    in_restore = threading.Event()
    release_restore = threading.Event()
    real_reverse = service_module.reverse_map

    def slow_reverse(*args, **kwargs):
        in_restore.set()
        assert release_restore.wait(timeout=5)
        return real_reverse(*args, **kwargs)

    monkeypatch.setattr(service_module, "reverse_map", slow_reverse)
    restored = {}
    disposed: list[bool] = []
    dispose_started = threading.Event()

    def dispose():
        dispose_started.set()
        disposed.append(
            service.dispose_authenticated(
                outcome.session_id,
                authorization_fingerprint=b"b" * 32,
                authorization_expires_at_ms=10_000,
                authorization_now_ms_fn=lambda: 0,
            )
        )

    restore_thread = threading.Thread(
        target=lambda: restored.setdefault(
            "value",
            service.restore(outcome.session_id, outcome.sanitized_text),
        )
    )
    dispose_thread = threading.Thread(target=dispose)
    restore_thread.start()
    assert in_restore.wait(timeout=5)
    dispose_thread.start()
    assert dispose_started.wait(timeout=5)
    assert disposed == []
    release_restore.set()
    restore_thread.join(timeout=5)
    dispose_thread.join(timeout=5)

    assert restored["value"].restored_text == "โทร 081-234-5678"
    assert disposed == [True]
    assert clear_calls == 1
    assert service.session_count == 0
    with pytest.raises(SessionExpiredError):
        service.restore(outcome.session_id, outcome.sanitized_text)


@pytest.mark.parametrize(
    ("final_now_ms", "expected"),
    [
        (999.0, True),
        (1000.0, False),
    ],
)
def test_disposal_authorization_is_validated_after_lock_wait(final_now_ms, expected):
    service = SessionService()
    target_id, _target = service._get_or_create(None, None)
    other_id, _other = service._get_or_create(None, None)
    auth_clock = {"now": 900.0}
    entered = threading.Event()
    results: list[bool] = []
    errors: list[BaseException] = []

    service._lock.acquire()

    def dispose():
        entered.set()
        try:
            results.append(
                service.dispose_authenticated(
                    target_id,
                    authorization_fingerprint=b"c" * 32,
                    authorization_expires_at_ms=1000,
                    authorization_now_ms_fn=lambda: auth_clock["now"],
                )
            )
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=dispose)
    thread.start()
    assert entered.wait(timeout=5)
    auth_clock["now"] = final_now_ms
    service._lock.release()
    thread.join(timeout=5)

    assert not thread.is_alive()
    if expected:
        assert results == [True]
        assert errors == []
        assert target_id not in service._sessions
    else:
        assert results == []
        assert len(errors) == 1
        assert isinstance(errors[0], DisposalAuthorizationError)
        assert target_id in service._sessions
        assert service._used_disposal_authorizations == {}
    assert service._get_or_create(other_id, None)[0] == other_id


def test_concurrent_same_authorization_cannot_both_succeed():
    service = SessionService()
    session_id, _session = service._get_or_create(None, None)
    start = threading.Barrier(3)
    results: list[bool] = []
    errors: list[BaseException] = []
    result_lock = threading.Lock()

    def dispose():
        start.wait(timeout=5)
        try:
            result = service.dispose_authenticated(
                session_id,
                authorization_fingerprint=b"d" * 32,
                authorization_expires_at_ms=1000,
                authorization_now_ms_fn=lambda: 900.0,
            )
            with result_lock:
                results.append(result)
        except BaseException as error:
            with result_lock:
                errors.append(error)

    threads = [threading.Thread(target=dispose) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert results == [True]
    assert len(errors) == 1
    assert isinstance(errors[0], DisposalAuthorizationError)
    assert service.session_count == 0


def test_shutdown_waits_for_active_sanitize_and_cleans_once(monkeypatch):
    service = SessionService()
    in_finalize = threading.Event()
    release_finalize = threading.Event()
    clear_calls = 0
    real_clear = SessionVault.clear

    def counted_clear(vault):
        nonlocal clear_calls
        clear_calls += 1
        real_clear(vault)

    monkeypatch.setattr(SessionVault, "clear", counted_clear)

    def finalize(outcome):
        in_finalize.set()
        assert release_finalize.wait(timeout=5)
        return outcome

    sanitized = {}
    shutdown_started = threading.Event()

    def shutdown():
        shutdown_started.set()
        service.close()

    sanitize_thread = threading.Thread(
        target=lambda: sanitized.setdefault(
            "value",
            service.sanitize_transaction(
                "โทร 081-234-5678",
                finalize=finalize,
            ),
        )
    )
    shutdown_thread = threading.Thread(target=shutdown)
    sanitize_thread.start()
    assert in_finalize.wait(timeout=5)
    shutdown_thread.start()
    assert shutdown_started.wait(timeout=5)
    assert shutdown_thread.is_alive()
    release_finalize.set()
    sanitize_thread.join(timeout=5)
    shutdown_thread.join(timeout=5)
    service.close()

    assert sanitized["value"].sanitized_text
    assert clear_calls == 1
    assert service.session_count == 0
    with pytest.raises(SessionExpiredError):
        service._get_or_create(None, None)


def test_restart_cannot_revive_expired_or_disposed_session():
    service, clock, timers = _service(ttl_s=10)
    expired_id, _expired = service._get_or_create(None, None)
    clock["now"] += 10
    timers.latest.fire()

    disposed_id, _disposed = service._get_or_create(None, None)
    assert service.drop(disposed_id) is True
    service.close()

    restarted, _new_clock, _new_timers = _service(ttl_s=10)
    for stale_id in (expired_id, disposed_id):
        with pytest.raises(SessionExpiredError):
            restarted._get_or_create(stale_id, None)
