"""scripts/prewarm_ner.py — retrying NER model pre-download for CI.

The bare one-shot `NER(engine='thainer')` prewarm step died on a single
upstream timeout (urlopen error) and took the whole pytest job with it.
The script retries with a delay so one network hiccup does not fail CI.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("prewarm_ner", ROOT / "scripts" / "prewarm_ner.py")
prewarm_ner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prewarm_ner)


def test_transient_failures_are_retried_until_success():
    calls = {"load": 0, "sleep": []}

    def flaky_loader():
        calls["load"] += 1
        if calls["load"] < 3:
            raise OSError("timed out")

    prewarm_ner.prewarm(attempts=5, delay_s=7, loader=flaky_loader, sleep=calls["sleep"].append)
    assert calls["load"] == 3
    assert calls["sleep"] == [7, 7]  # slept between attempts, not after success


def test_persistent_failure_raises_after_all_attempts():
    calls = {"load": 0, "sleep": []}

    def dead_loader():
        calls["load"] += 1
        raise OSError("timed out")

    with pytest.raises(OSError):
        prewarm_ner.prewarm(attempts=4, delay_s=1, loader=dead_loader, sleep=calls["sleep"].append)
    assert calls["load"] == 4
    assert calls["sleep"] == [1, 1, 1]  # no sleep after the final failure
