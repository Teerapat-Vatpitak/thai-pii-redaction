"""Pre-download the offline thainer NER model, retrying transient failures.

CI runs this before setting the offline flag so the pinned model is on disk
when tests run. The download comes from an upstream host that occasionally
times out; a bare one-shot `NER(engine='thainer')` turned any such hiccup
into a red pytest job, so this retries with a delay instead.

Usage: python scripts/prewarm_ner.py
"""

from __future__ import annotations

import time
from collections.abc import Callable


def _load_ner() -> None:
    from pythainlp.tag import NER

    NER(engine="thainer")


def prewarm(
    *,
    attempts: int = 5,
    delay_s: float = 15,
    loader: Callable[[], None] = _load_ner,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run ``loader`` until it succeeds, sleeping ``delay_s`` between attempts.

    Re-raises the last error once ``attempts`` runs are exhausted — CI must
    still fail loudly when the host is genuinely down, not proceed to a
    guaranteed-worse failure at test time.
    """
    for attempt in range(1, attempts + 1):
        try:
            loader()
            return
        except Exception as e:
            if attempt == attempts:
                raise
            print(f"prewarm attempt {attempt}/{attempts} failed ({e!r}); retrying in {delay_s}s")
            sleep(delay_s)


if __name__ == "__main__":
    prewarm()
