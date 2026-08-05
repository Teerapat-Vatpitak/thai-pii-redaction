"""Helpers for severing sensitive exception object graphs."""

from __future__ import annotations

import traceback


def _exception_attr(error: BaseException, name: str, default=None):
    """Read a built-in exception field without trusting subclass overrides."""
    try:
        return BaseException.__getattribute__(error, name)
    except BaseException:
        return default


def _clear_exception_attr(error: BaseException, name: str) -> None:
    """Best-effort built-in field clear that cannot replace the original error."""
    try:
        BaseException.__setattr__(error, name, None)
    except BaseException:
        pass


def _set_payload_attr(error: BaseException, name: str, value) -> None:
    """Best-effort clear for built-in exception payload slots."""
    try:
        object.__setattr__(error, name, value)
    except BaseException:
        pass


def _clear_exception_payload(error: BaseException) -> None:
    """Remove messages and common fields that can retain request data."""
    if isinstance(error, UnicodeDecodeError):
        _set_payload_attr(error, "object", b"")
        _set_payload_attr(error, "encoding", "unknown")
        _set_payload_attr(error, "reason", "decoding failed")
        _set_payload_attr(error, "start", 0)
        _set_payload_attr(error, "end", 0)
    elif isinstance(error, (UnicodeEncodeError, UnicodeTranslateError)):
        _set_payload_attr(error, "object", "")
        _set_payload_attr(error, "reason", "encoding failed")
        _set_payload_attr(error, "start", 0)
        _set_payload_attr(error, "end", 0)
        if isinstance(error, UnicodeEncodeError):
            _set_payload_attr(error, "encoding", "unknown")

    if isinstance(error, OSError):
        _set_payload_attr(error, "filename", None)
        _set_payload_attr(error, "filename2", None)
        _set_payload_attr(error, "strerror", "operation failed")
    if isinstance(error, SyntaxError):
        _set_payload_attr(error, "filename", None)
        _set_payload_attr(error, "text", None)
        _set_payload_attr(error, "msg", "syntax error")
    if isinstance(error, ImportError):
        _set_payload_attr(error, "name", None)
        _set_payload_attr(error, "path", None)
    if isinstance(error, AttributeError):
        _set_payload_attr(error, "name", None)
        _set_payload_attr(error, "obj", None)
    if isinstance(error, NameError):
        _set_payload_attr(error, "name", None)
    if isinstance(error, StopIteration):
        _set_payload_attr(error, "value", None)
    if isinstance(error, SystemExit):
        _set_payload_attr(error, "code", None)

    try:
        payload = BaseException.__getattribute__(error, "__dict__")
        if isinstance(payload, dict):
            payload.clear()
    except BaseException:
        pass
    # BaseExceptionGroup keeps `message` and `exceptions` in read-only C-level
    # fields. Replacing only `args` corrupts repr() on Python 3.13. Leave that
    # immutable shell intact; its member errors have already been queued for
    # recursive scrubbing and callers must drop the original group.
    if isinstance(error, BaseExceptionGroup):
        return
    try:
        BaseException.__setattr__(error, "args", ())
    except BaseException:
        pass


def discard_exception_graph(error: BaseException) -> None:
    """Drop mutable traceback, chaining, and common payloads before translation."""
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)

        cause = _exception_attr(current, "__cause__")
        context = _exception_attr(current, "__context__")
        if isinstance(cause, BaseException):
            pending.append(cause)
        if isinstance(context, BaseException):
            pending.append(context)
        members = _exception_attr(current, "exceptions", ())
        if isinstance(members, tuple):
            pending.extend(member for member in members if isinstance(member, BaseException))

        current_traceback = _exception_attr(current, "__traceback__")
        if current_traceback is not None:
            try:
                traceback.clear_frames(current_traceback)
            except BaseException:
                pass
        _clear_exception_payload(current)
        _clear_exception_attr(current, "__traceback__")
        _clear_exception_attr(current, "__cause__")
        _clear_exception_attr(current, "__context__")
        try:
            BaseException.__setattr__(current, "__suppress_context__", True)
        except BaseException:
            pass
