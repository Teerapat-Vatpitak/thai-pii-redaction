"""Broker-private operation limits at authoritative detector boundaries."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")


class NativeBrokerOperationError(Exception):
    """Fixed internal marker that must cross core containment unchanged."""


class NativeBrokerPayloadTooLarge(NativeBrokerOperationError):
    """An intermediate detector input exceeded the broker protocol cap."""


WatchdogScheduler = Callable[[int, threading.Event, Callable[[], None]], None]


def _terminate_backend() -> None:
    os._exit(70)


def _schedule_watchdog(
    timeout_ms: int,
    done: threading.Event,
    expire: Callable[[], None],
) -> None:
    def wait() -> None:
        if not done.wait(timeout_ms / 1000):
            expire()

    threading.Thread(target=wait, daemon=True, name="aiguard-broker-deadline").start()


class BrokerOperationContext:
    """One authenticated private-backend request's fixed broker limits."""

    def __init__(
        self,
        *,
        outer_deadline_ms: int,
        local_detection_phases: int | None,
        intermediate_text_chars: int | None,
        local_phase_deadline_ms: int | None,
        terminate: Callable[[], None] = _terminate_backend,
        schedule_watchdog: WatchdogScheduler = _schedule_watchdog,
    ) -> None:
        if type(outer_deadline_ms) is not int or outer_deadline_ms <= 0:
            raise ValueError("invalid broker operation context")
        if local_detection_phases is None:
            valid_detection = intermediate_text_chars is None and local_phase_deadline_ms is None
        elif type(local_detection_phases) is int and local_detection_phases == 0:
            valid_detection = intermediate_text_chars is None and local_phase_deadline_ms is None
        else:
            valid_detection = (
                type(local_detection_phases) is int
                and 0 < local_detection_phases <= 6
                and type(intermediate_text_chars) is int
                and intermediate_text_chars > 0
                and type(local_phase_deadline_ms) is int
                and local_phase_deadline_ms > 0
            )
        if not valid_detection or not callable(terminate) or not callable(schedule_watchdog):
            raise ValueError("invalid broker operation context")
        self._outer_deadline_ms = outer_deadline_ms
        self._local_detection_phases = local_detection_phases
        self._intermediate_text_chars = intermediate_text_chars
        self._local_phase_deadline_ms = local_phase_deadline_ms
        self._terminate = terminate
        self._schedule_watchdog = schedule_watchdog
        self._outer_done = threading.Event()
        self._termination_started = False
        self._lock = threading.Lock()
        self._phase_count = 0
        self._active = False

    def __repr__(self) -> str:
        return "BrokerOperationContext(<redacted>)"

    def _terminate_once(self) -> None:
        with self._lock:
            if self._termination_started:
                return
            self._termination_started = True
        self._terminate()

    def _expire_unless_done(self, done: threading.Event) -> None:
        if not done.is_set():
            self._terminate_once()

    def start(self) -> None:
        with self._lock:
            if self._active:
                raise NativeBrokerOperationError("broker operation context failed")
            self._active = True
        self._schedule_watchdog(
            self._outer_deadline_ms,
            self._outer_done,
            lambda: self._expire_unless_done(self._outer_done),
        )

    def finish(self) -> None:
        self._outer_done.set()
        with self._lock:
            self._active = False

    @contextmanager
    def detector_phase(self, text: str) -> Iterator[None]:
        if self._local_detection_phases is None:
            yield
            return
        with self._lock:
            self._phase_count += 1
            phase_count = self._phase_count
        if phase_count > self._local_detection_phases:
            self._terminate_once()
            raise NativeBrokerOperationError("broker detector phase failed")
        if (
            type(text) is not str
            or self._intermediate_text_chars is None
            or len(text) > self._intermediate_text_chars
        ):
            raise NativeBrokerPayloadTooLarge("broker detector input rejected")
        if self._local_phase_deadline_ms is None:
            self._terminate_once()
            raise NativeBrokerOperationError("broker detector phase failed")
        done = threading.Event()
        self._schedule_watchdog(
            self._local_phase_deadline_ms,
            done,
            lambda: self._expire_unless_done(done),
        )
        try:
            yield
        finally:
            done.set()


_CURRENT: ContextVar[BrokerOperationContext | None] = ContextVar(
    "aiguard_native_broker_operation",
    default=None,
)


@contextmanager
def activate_broker_operation(context: BrokerOperationContext) -> Iterator[None]:
    if _CURRENT.get() is not None:
        raise NativeBrokerOperationError("broker operation context failed")
    token = _CURRENT.set(context)
    try:
        context.start()
        yield
    finally:
        context.finish()
        _CURRENT.reset(token)


def native_broker_detector_phase(
    function: Callable[_P, _R],
) -> Callable[_P, _R]:
    """Apply active broker limits without changing non-broker core callers."""

    @wraps(function)
    def wrapped(text: str, *args, **kwargs):
        context = _CURRENT.get()
        if context is None:
            return function(text, *args, **kwargs)
        with context.detector_phase(text):
            return function(text, *args, **kwargs)

    return wrapped


__all__ = [
    "BrokerOperationContext",
    "NativeBrokerOperationError",
    "NativeBrokerPayloadTooLarge",
    "activate_broker_operation",
    "native_broker_detector_phase",
]
