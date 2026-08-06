"""Redact bearer-like session routes at the Uvicorn logging boundary."""

from __future__ import annotations

import logging
import re
from copy import deepcopy

_UVICORN_ACCESS_LOGGER = "uvicorn.access"
_FILTER_NAME = "aiguard_sensitive_route"
_SESSION_PATH_IN_MESSAGE = re.compile(r"/api/session/[^\s?\"']+(?:\?[^\s\"']*)?")
_REDACTED_SESSION_PATH = "/api/session/[redacted]"


def _redact_request_target(value: str) -> str:
    path, _separator, _query = value.partition("?")
    if path.startswith("/api/session/"):
        return _REDACTED_SESSION_PATH
    # Query values are not needed for operations and can contain credentials.
    return path


def _supported_uvicorn_args(args: object) -> bool:
    """Recognize the Uvicorn access-record contract that we can redact safely."""
    return (
        isinstance(args, tuple)
        and len(args) == 5
        and all(isinstance(args[index], str) for index in range(4))
        and type(args[4]) is int
    )


class UvicornAccessLogFilter(logging.Filter):
    """Redact supported access metadata and suppress unknown record shapes."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not _supported_uvicorn_args(args):
            # Uvicorn's tuple is private API. Suppress an unknown shape instead
            # of risking a raw request target after dependency drift.
            return False
        redacted_args = list(args)
        redacted_args[2] = _redact_request_target(args[2])
        record.args = tuple(redacted_args)
        if isinstance(record.msg, str):
            record.msg = _SESSION_PATH_IN_MESSAGE.sub(
                _REDACTED_SESSION_PATH,
                record.msg,
            )
        try:
            rendered = record.getMessage()
        except Exception:
            return False
        return _SESSION_PATH_IN_MESSAGE.sub(_REDACTED_SESSION_PATH, rendered) == rendered


_ACCESS_FILTER = UvicornAccessLogFilter()


def install_uvicorn_access_log_filter() -> None:
    """Protect CLI-created Uvicorn loggers before an HTTP response is logged."""
    logger = logging.getLogger(_UVICORN_ACCESS_LOGGER)
    if not any(isinstance(item, UvicornAccessLogFilter) for item in logger.filters):
        logger.addFilter(_ACCESS_FILTER)


def uvicorn_log_config() -> dict:
    """Return the launcher log configuration with sensitive-route redaction."""
    from uvicorn.config import LOGGING_CONFIG

    config = deepcopy(LOGGING_CONFIG)
    filters = config.setdefault("filters", {})
    filters[_FILTER_NAME] = {"()": UvicornAccessLogFilter}
    access_handler = config.get("handlers", {}).get("access")
    if not isinstance(access_handler, dict):
        raise RuntimeError("Uvicorn access logging configuration is unavailable")
    handler_filters = list(access_handler.get("filters", []))
    if _FILTER_NAME not in handler_filters:
        handler_filters.append(_FILTER_NAME)
    access_handler["filters"] = handler_filters
    return config
