"""Deterministic transport emulator for local failure/retry checks.

It models delivery and result-submission failures at AI Guard's transport seam.
It is not the official AI for Thai delivery path and does not reproduce a
platform queue protocol.
"""

from __future__ import annotations

from collections.abc import Iterable


class EmulatedTransport:
    def __init__(
        self,
        jobs: Iterable[dict],
        *,
        fail_submit_attempts: Iterable[int] = (),
    ):
        self._jobs = list(jobs)
        self._fail_submit_attempts = set(fail_submit_attempts)
        self.results: list[dict] = []
        self.poll_count = 0
        self.submit_count = 0

    def poll(self) -> dict | None:
        self.poll_count += 1
        return self._jobs.pop(0) if self._jobs else None

    def submit(self, result: dict) -> None:
        self.submit_count += 1
        if self.submit_count in self._fail_submit_attempts:
            raise RuntimeError("emulated result submission failure")
        self.results.append(result)
