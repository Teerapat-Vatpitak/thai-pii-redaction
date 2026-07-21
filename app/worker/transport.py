"""Transport seam — the worker's GUESSED half, deliberately swappable.

The AI for Thai queue spec is unpublished (2026-07-21). HttpPollTransport is
our best guess: poll an endpoint for a job, POST the result back, Apikey
header like every other AI for Thai API. When the real spec arrives, write a
new Transport implementation in THIS file and touch nothing else — runner
and handler depend only on the two-method protocol below.

InMemoryTransport exists for tests and local dry-runs.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class Transport(Protocol):
    def poll(self) -> dict | None:
        """Return the next job, or None when the queue is empty/unreachable."""

    def submit(self, result: dict) -> None:
        """Deliver one result. Exceptions are the runner's problem."""


class InMemoryTransport:
    """Feed a fixed job list; collect results. For tests and dry-runs."""

    def __init__(self, jobs: list[dict]):
        self._jobs = list(jobs)
        self.results: list[dict] = []

    def poll(self) -> dict | None:
        return self._jobs.pop(0) if self._jobs else None

    def submit(self, result: dict) -> None:
        self.results.append(result)


class HttpPollTransport:
    """GET a job, POST the result. Every knob is a constructor arg with an
    env-var default so a deployed container can be repointed without a build.
    """

    def __init__(
        self,
        poll_url: str | None = None,
        result_url: str | None = None,
        timeout_s: float = 30.0,
    ):
        self._poll_url = poll_url or os.environ.get("AIGUARD_QUEUE_POLL_URL", "")
        self._result_url = result_url or os.environ.get("AIGUARD_QUEUE_RESULT_URL", "")
        if not self._poll_url or not self._result_url:
            raise ValueError(
                "queue URLs not configured; set AIGUARD_QUEUE_POLL_URL and AIGUARD_QUEUE_RESULT_URL"
            )
        self._timeout_s = timeout_s

    def _headers(self) -> dict:
        headers = {"X-lib": "aiguard-worker"}
        key = os.environ.get("AIFORTHAI_API_KEY", "")
        if key:
            headers["Apikey"] = key
        return headers

    def poll(self) -> dict | None:
        try:
            resp = httpx.get(self._poll_url, headers=self._headers(), timeout=self._timeout_s)
        except httpx.HTTPError as e:
            logger.warning("poll failed: %s", type(e).__name__)
            return None
        if resp.status_code != 200:
            if resp.status_code != 204:  # 204 = normal empty queue, stays quiet
                logger.warning("poll returned HTTP %s", resp.status_code)
            return None
        try:
            job = resp.json()
        except ValueError:
            logger.warning("poll returned non-JSON body")
            return None
        return job if isinstance(job, dict) else None

    def submit(self, result: dict) -> None:
        resp = httpx.post(
            self._result_url, json=result, headers=self._headers(), timeout=self._timeout_s
        )
        resp.raise_for_status()
