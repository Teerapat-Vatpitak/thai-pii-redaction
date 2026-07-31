#!/usr/bin/env python3
r"""Measure the hot paths and compare against a committed baseline.

This is the performance half of the working agreement in AGENTS.md: a change
that touches `pii_redactor/` or `app/` has to show what it did to speed and
memory, not just that the tests still pass.

Measured in-process, deliberately not over HTTP, so the numbers describe the
pipeline rather than the network stack:

    detect       detect_all() on a Thai fixture
    sanitize     SessionService.sanitize() in token mode
    restore      SessionService.restore() of that same session
    pdf_redact   detect_source_type -> extract -> detect -> redact_pdf

Usage:

    $env:PYTHONUTF8='1'
    .\.venv\Scripts\python.exe scripts\measure_perf.py                  # compare
    .\.venv\Scripts\python.exe scripts\measure_perf.py --update-baseline
    .\.venv\Scripts\python.exe scripts\measure_perf.py --json out.json

Exits 1 when a measurement regresses past tolerance, 0 otherwise.

Two honest limits. Timing on a machine that is also running a browser is
noisy, which is why the tolerances are wide and why this is a local gate
rather than a CI job -- a perf gate that cries wolf on a shared runner is a
gate everyone learns to ignore. And `peak_rss_mb` is sampled after each
operation, not continuously, so it tracks the resident set the pipeline
settles at, not a true instantaneous peak.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_PATH = ROOT / "perf" / "baseline.json"
SAMPLE_TEXT_PATH = ROOT / "tests" / "fixtures" / "demo_sample_th.txt"
SAMPLE_PDF_PATH = ROOT / "examples" / "sample_document.pdf"

DEFAULT_TIME_TOLERANCE = 0.20
DEFAULT_MEMORY_TOLERANCE = 0.15
DEFAULT_ITERATIONS = 5


@dataclass(frozen=True)
class Finding:
    """One metric that moved the wrong way.

    `current` is None when the metric vanished from the run entirely, which is
    reported rather than skipped: a baseline entry with no measurement behind
    it is indistinguishable from a pass unless someone says so.
    """

    metric: str
    baseline: float
    current: float | None
    ratio: float | None
    tolerance: float

    def describe(self) -> str:
        if self.current is None:
            return f"{self.metric}: missing from this run (baseline {self.baseline:.1f})"
        pct = (self.ratio - 1.0) * 100.0
        return (
            f"{self.metric}: {self.baseline:.1f} -> {self.current:.1f} "
            f"(+{pct:.0f}%, tolerance +{self.tolerance * 100:.0f}%)"
        )


def compare(
    baseline: dict,
    current: dict,
    *,
    time_tolerance: float = DEFAULT_TIME_TOLERANCE,
    memory_tolerance: float = DEFAULT_MEMORY_TOLERANCE,
) -> list[Finding]:
    """Findings worst-first. An empty list means the run is within budget.

    Only the baseline's own metrics are checked. A metric the baseline never
    had is new work, not a regression, and getting faster is never reported.
    """
    findings: list[Finding] = []

    base_ops = baseline.get("operations", {})
    cur_ops = current.get("operations", {})
    for name, base_entry in base_ops.items():
        base_ms = base_entry.get("median_ms")
        if base_ms is None or base_ms <= 0:
            continue
        cur_entry = cur_ops.get(name)
        cur_ms = None if cur_entry is None else cur_entry.get("median_ms")
        if cur_ms is None:
            findings.append(Finding(name, base_ms, None, None, time_tolerance))
            continue
        ratio = cur_ms / base_ms
        if ratio > 1.0 + time_tolerance:
            findings.append(Finding(name, base_ms, cur_ms, ratio, time_tolerance))

    base_rss = baseline.get("peak_rss_mb")
    cur_rss = current.get("peak_rss_mb")
    if base_rss and cur_rss:
        ratio = cur_rss / base_rss
        if ratio > 1.0 + memory_tolerance:
            findings.append(Finding("peak_rss_mb", base_rss, cur_rss, ratio, memory_tolerance))

    findings.sort(key=lambda f: float("inf") if f.ratio is None else f.ratio, reverse=True)
    return findings


def _rss_mb() -> float | None:
    """Resident set in MiB, or None when psutil is not installed.

    psutil is not a declared dependency -- the gate degrades to timings-only
    rather than forcing an install on anyone who just wants to run the suite.
    """
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().memory_info().rss / (1024 * 1024)


def _time_it(fn, iterations: int) -> tuple[float, list[float]]:
    """Median milliseconds over `iterations` runs, after one warm-up.

    The warm-up is not optional: the first detect() call pays for loading the
    CRF model, which would otherwise dominate every measurement.
    """
    fn()
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(samples), samples


def measure(iterations: int = DEFAULT_ITERATIONS) -> dict:
    """Run every hot path and return the raw measurement document."""
    # Imported here, not at module scope, so the comparison logic stays
    # importable (and unit-testable) without loading the NER model.
    from pii_redactor.detectors.aggregate import detect_all
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_cleaner import clean_length_preserving
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.models import EntityRegistry
    from pii_redactor.redactor import redact_pdf
    from pii_redactor.session_service import SessionService

    text = clean_length_preserving(SAMPLE_TEXT_PATH.read_text(encoding="utf-8"))
    service = SessionService()
    operations: dict[str, dict] = {}
    rss_samples: list[float] = []

    def record(name: str, fn) -> None:
        median_ms, samples = _time_it(fn, iterations)
        operations[name] = {
            "median_ms": round(median_ms, 2),
            "min_ms": round(min(samples), 2),
            "max_ms": round(max(samples), 2),
        }
        sample = _rss_mb()
        if sample is not None:
            rss_samples.append(sample)

    record("detect", lambda: detect_all(text))

    seeded = service.sanitize(text, mode="token")
    record("sanitize", lambda: service.sanitize(text, mode="token"))
    record("restore", lambda: service.restore(seeded.session_id, seeded.sanitized_text))

    if SAMPLE_PDF_PATH.is_file():
        out_path = ROOT / "tmp" / "perf-redacted.pdf"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        def redact_once() -> None:
            # Use the same detector as the PDF endpoint.
            source_type = detect_source_type(str(SAMPLE_PDF_PATH))
            raw_text, word_bboxes, _meta = extract(str(SAMPLE_PDF_PATH), source_type)
            detect_text = clean_length_preserving(raw_text)
            entities = detect_all(detect_text)
            fp_count = sum(entity.redact_type == "FP" for entity in entities)
            redact_pdf(
                str(SAMPLE_PDF_PATH),
                EntityRegistry(
                    entities=entities,
                    fp_count=fp_count,
                    tb_count=len(entities) - fp_count,
                ),
                word_bboxes,
                str(out_path),
            )

        record("pdf_redact", redact_once)
        out_path.unlink(missing_ok=True)

    return {
        "operations": operations,
        "peak_rss_mb": round(max(rss_samples), 1) if rss_samples else None,
        "iterations": iterations,
    }


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline", action="store_true", help="overwrite perf/baseline.json"
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--json", type=Path, help="also write the raw measurement here")
    parser.add_argument("--time-tolerance", type=float, default=DEFAULT_TIME_TOLERANCE)
    parser.add_argument("--memory-tolerance", type=float, default=DEFAULT_MEMORY_TOLERANCE)
    args = parser.parse_args(argv)

    current = measure(args.iterations)

    for name, entry in current["operations"].items():
        print(
            f"{name:<12} {entry['median_ms']:>9.2f} ms  (min {entry['min_ms']:.2f} max {entry['max_ms']:.2f})"
        )
    if current["peak_rss_mb"] is None:
        print("peak_rss_mb  not measured (psutil not installed)")
    else:
        print(f"peak_rss_mb  {current['peak_rss_mb']:>9.1f} MiB")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print(f"\nbaseline written to {BASELINE_PATH.relative_to(ROOT)}")
        return 0

    baseline = _load(BASELINE_PATH)
    if baseline is None:
        print(f"\nno baseline at {BASELINE_PATH.relative_to(ROOT)}; run with --update-baseline")
        return 0

    findings = compare(
        baseline,
        current,
        time_tolerance=args.time_tolerance,
        memory_tolerance=args.memory_tolerance,
    )
    if not findings:
        print("\nwithin budget")
        return 0

    print("\nREGRESSION")
    for finding in findings:
        print(f"  {finding.describe()}")
    print("\nExplain the trade in the commit, or fix it. Do not merge unexplained.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
