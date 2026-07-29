"""The performance gate's comparison logic.

`scripts/measure_perf.py` measures; this file pins the part that decides
whether a measurement is a regression. Timing on a shared machine is noisy, so
the decision rule has to tolerate drift without tolerating a real slowdown --
and it must fail loudly when a baseline entry disappears, because a silently
dropped metric looks exactly like a passing gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_perf import DEFAULT_MEMORY_TOLERANCE, DEFAULT_TIME_TOLERANCE, compare


def _sample(detect_ms: float = 10.0, rss_mb: float = 200.0) -> dict:
    return {
        "operations": {
            "detect": {"median_ms": detect_ms},
            "sanitize": {"median_ms": 30.0},
        },
        "peak_rss_mb": rss_mb,
    }


def test_identical_measurements_are_not_a_regression():
    assert compare(_sample(), _sample()) == []


def test_getting_faster_is_never_a_regression():
    findings = compare(_sample(detect_ms=10.0), _sample(detect_ms=1.0))
    assert findings == []


def test_slowdown_inside_the_tolerance_passes():
    # +19% with a 20% tolerance: noise on a shared machine, not a finding.
    findings = compare(_sample(detect_ms=10.0), _sample(detect_ms=11.9))
    assert findings == []


def test_slowdown_past_the_tolerance_is_reported():
    findings = compare(_sample(detect_ms=10.0), _sample(detect_ms=13.0))
    assert [f.metric for f in findings] == ["detect"]
    assert findings[0].baseline == pytest.approx(10.0)
    assert findings[0].current == pytest.approx(13.0)
    assert findings[0].ratio == pytest.approx(1.3)


def test_memory_growth_uses_its_own_tighter_tolerance():
    # +16% RSS trips the 15% memory tolerance even though 16% would pass the
    # 20% time tolerance. The two budgets are deliberately different.
    findings = compare(_sample(rss_mb=200.0), _sample(rss_mb=232.0))
    assert [f.metric for f in findings] == ["peak_rss_mb"]


def test_memory_growth_inside_its_tolerance_passes():
    assert compare(_sample(rss_mb=200.0), _sample(rss_mb=228.0)) == []


def test_tolerances_are_configurable():
    findings = compare(_sample(detect_ms=10.0), _sample(detect_ms=11.0), time_tolerance=0.05)
    assert [f.metric for f in findings] == ["detect"]


def test_a_metric_missing_from_the_run_is_reported_not_ignored():
    current = _sample()
    del current["operations"]["detect"]
    findings = compare(_sample(), current)
    assert [f.metric for f in findings] == ["detect"]
    assert findings[0].current is None


def test_a_new_metric_absent_from_the_baseline_is_not_a_regression():
    current = _sample()
    current["operations"]["guard"] = {"median_ms": 5.0}
    assert compare(_sample(), current) == []


def test_missing_rss_in_either_side_is_skipped_rather_than_failing():
    # RSS needs psutil; on a machine without it the run still produces timings
    # and must not report a phantom memory regression.
    baseline = _sample()
    current = _sample()
    current["peak_rss_mb"] = None
    assert compare(baseline, current) == []


def test_findings_are_ordered_worst_first():
    baseline = {
        "operations": {"a": {"median_ms": 10.0}, "b": {"median_ms": 10.0}},
        "peak_rss_mb": None,
    }
    current = {
        "operations": {"a": {"median_ms": 14.0}, "b": {"median_ms": 30.0}},
        "peak_rss_mb": None,
    }
    assert [f.metric for f in compare(baseline, current)] == ["b", "a"]


def test_default_tolerances_match_the_documented_agreement():
    # AGENTS.md states 20% on time and 15% on memory. If these move, that
    # document moves with them.
    assert DEFAULT_TIME_TOLERANCE == 0.20
    assert DEFAULT_MEMORY_TOLERANCE == 0.15
