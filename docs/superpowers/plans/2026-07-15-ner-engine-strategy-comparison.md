# NER Engine Strategy Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure four NER strategies (CRF, WangchanBERTa, union, route-ADDRESS→WCB) on the gold and synthetic benchmarks, then write an ADR recommending an engine strategy.

**Architecture:** Pure merge helpers in `benchmark/strategies.py` compose `union` and `route` predictions from per-sample CRF and WCB entity lists. `benchmark/runner.py` gains `run_strategy_comparison()` that runs both engines once each (process-global singleton reset, as `run_benchmark` already does), composes the four strategies, and scores each with the existing `benchmark.scorer.score`. A `--compare-strategies` CLI flag prints the comparison table. No product code (`detect_tb`/`detect_all`) changes.

**Tech Stack:** Python 3.13, stdlib only. Reuses `pii_redactor.detectors.aggregate` (`detect_all`, `dedupe_spans`), `benchmark.scorer`, `benchmark.corpus`, `benchmark.gold`.

## Global Constraints

- Set `$env:PYTHONUTF8='1'` before every Python run (Windows cp1252 breaks Thai). Use `.\.venv\Scripts\python.exe`.
- No new dependency. The WangchanBERTa path needs `requirements-ml.txt` (torch/transformers) which is already installed in `.venv`.
- Do NOT modify `pii_redactor/detectors/tb_detector.py`, `detect_all`, or `dedupe_spans`. This work is measurement-only.
- The NER engine is a process-global singleton (`tb_detector._ner`) selected from `AIGUARD_NER_ENGINE`. Reset it (and restore afterward) exactly as `run_benchmark` does.
- Reuse `benchmark.scorer.score` unchanged — do not write a new scorer.

---

### Task 1: pure strategy merge helpers

**Files:**
- Create: `benchmark/strategies.py`
- Test: `tests/test_benchmark_strategies.py`

**Interfaces:**
- Consumes: `pii_redactor.models.Entity` (fields: `entity_id, redact_type, data_type, span, score, original_text`); `pii_redactor.detectors.aggregate.dedupe_spans(list[Entity]) -> list[Entity]`.
- Produces: `union_entities(crf: list[Entity], wcb: list[Entity]) -> list[Entity]`; `route_entities(crf: list[Entity], wcb: list[Entity]) -> list[Entity]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark_strategies.py
"""Tests for NER-engine strategy merges (benchmark comparison)."""
from __future__ import annotations

from pii_redactor.models import Entity
from benchmark.strategies import union_entities, route_entities


def _ent(dtype, span, redact="TB", score=0.85):
    return Entity(entity_id="x", redact_type=redact, data_type=dtype,
                  span=span, score=score, original_text="v")


def test_union_superset_on_disjoint_spans():
    # Disjoint spans: union keeps every span from both engines.
    crf = [_ent("NAME", (0, 8))]
    wcb = [_ent("ADDRESS", (20, 35))]
    spans = {(e.data_type, e.span) for e in union_entities(crf, wcb)}
    assert ("NAME", (0, 8)) in spans
    assert ("ADDRESS", (20, 35)) in spans


def test_route_takes_address_from_wcb_and_name_from_crf():
    crf = [_ent("NAME", (0, 8)), _ent("ADDRESS", (9, 15))]   # CRF's weak address
    wcb = [_ent("ADDRESS", (9, 25))]                          # WCB's better address
    out = route_entities(crf, wcb)
    names = [e for e in out if e.data_type == "NAME"]
    addrs = [e for e in out if e.data_type == "ADDRESS"]
    assert names and names[0].span == (0, 8)     # NAME kept from CRF
    assert addrs and addrs[0].span == (9, 25)    # ADDRESS from WCB, not CRF's (9,15)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_strategies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'benchmark.strategies'`.

- [ ] **Step 3: Write minimal implementation**

```python
# benchmark/strategies.py
"""Pure NER-engine strategy merges for the benchmark comparison.

Given one sample's CRF and WangchanBERTa entity lists, compose the `union` and
`route` strategy predictions. Model-free so the merge logic is unit-testable
without loading any NER model.
"""
from __future__ import annotations

from pii_redactor.models import Entity
from pii_redactor.detectors.aggregate import dedupe_spans


def union_entities(crf: list[Entity], wcb: list[Entity]) -> list[Entity]:
    """CRF ∪ WCB: keep every span from both engines, then drop overlaps via
    dedupe_spans (FP-first, earlier-start-then-longer). Recall-first."""
    return dedupe_spans(list(crf) + list(wcb))


def route_entities(crf: list[Entity], wcb: list[Entity]) -> list[Entity]:
    """ADDRESS from WangchanBERTa, everything else from CRF, then dedupe.
    Encodes the gold finding: WCB wins ADDRESS, CRF wins NAME-without-cue."""
    picked = [e for e in crf if e.data_type != "ADDRESS"]
    picked += [e for e in wcb if e.data_type == "ADDRESS"]
    return dedupe_spans(picked)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_strategies.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add benchmark/strategies.py tests/test_benchmark_strategies.py
git commit -m "feat(benchmark): pure union/route NER strategy merge helpers"
```

---

### Task 2: run_strategy_comparison in the runner

**Files:**
- Modify: `benchmark/runner.py`
- Test: `tests/test_benchmark_strategies.py`

**Interfaces:**
- Consumes: `benchmark.strategies.union_entities`, `route_entities` (Task 1); `benchmark.corpus.build_corpus`; `benchmark.gold.load_gold`; `benchmark.scorer.score`; `pii_redactor.detectors.aggregate.detect_all`; `pii_redactor.detectors.tb_detector` (for `_ner` reset).
- Produces: `run_strategy_comparison(source: str = "synthetic", seed: int = 42, size: int = 200) -> dict[str, dict]` — keys `crf`, `wcb`, `union`, `route`; each value is a `score()` report with added `strategy`, `source`, `seed`, `size`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_benchmark_strategies.py
import importlib.util
import pytest
from benchmark.runner import run_strategy_comparison
from benchmark.gold import load_gold


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="requires requirements-ml.txt",
)
def test_run_strategy_comparison_returns_four_reports():
    reports = run_strategy_comparison(source="gold")
    assert set(reports) == {"crf", "wcb", "union", "route"}
    for name, rep in reports.items():
        assert rep["strategy"] == name
        assert rep["source"] == "gold"
        assert rep["corpus"]["samples"] == len(load_gold())
        assert "by_type" in rep and "overall" in rep
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_strategies.py::test_run_strategy_comparison_returns_four_reports -v`
Expected: FAIL with `ImportError: cannot import name 'run_strategy_comparison'`.

- [ ] **Step 3: Write minimal implementation**

Append to `benchmark/runner.py` (after the existing `run_benchmark`):

```python
def run_strategy_comparison(
    source: str = "synthetic", seed: int = 42, size: int = 200
) -> dict:
    """Score four NER strategies (crf, wcb, union, route) on one corpus.

    Runs each engine once over the corpus (resetting the process-global NER
    singleton, as run_benchmark does), composes union/route per sample, and
    scores all four with the shared scorer.
    """
    from pii_redactor.detectors import tb_detector
    from pii_redactor.detectors.aggregate import detect_all
    from .strategies import union_entities, route_entities

    samples = load_gold() if source == "gold" else build_corpus(seed=seed, size=size)

    def _run(engine_env: str):
        prev_ner = tb_detector._ner
        prev_env = os.environ.get("AIGUARD_NER_ENGINE")
        os.environ["AIGUARD_NER_ENGINE"] = engine_env
        tb_detector._ner = None
        try:
            return [detect_all(s.text) for s in samples]
        finally:
            tb_detector._ner = prev_ner
            if prev_env is None:
                os.environ.pop("AIGUARD_NER_ENGINE", None)
            else:
                os.environ["AIGUARD_NER_ENGINE"] = prev_env

    crf_ents = _run("thainer")
    wcb_ents = _run("wangchanberta")

    strat_ents = {
        "crf": crf_ents,
        "wcb": wcb_ents,
        "union": [union_entities(c, w) for c, w in zip(crf_ents, wcb_ents)],
        "route": [route_entities(c, w) for c, w in zip(crf_ents, wcb_ents)],
    }

    reports: dict[str, dict] = {}
    for name, ents_list in strat_ents.items():
        preds = [[(e.span[0], e.span[1], e.data_type) for e in ents] for ents in ents_list]
        rep = score(samples, preds)
        rep["strategy"] = name
        rep["source"] = source
        rep["seed"] = seed
        rep["size"] = size
        reports[name] = rep
    return reports
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_strategies.py -v`
Expected: PASS (3 passed — the two Task 1 tests plus this one; the WCB model loads once, may take ~30-60s).

- [ ] **Step 5: Commit**

```bash
git add benchmark/runner.py tests/test_benchmark_strategies.py
git commit -m "feat(benchmark): run_strategy_comparison scores crf/wcb/union/route"
```

---

### Task 3: CLI --compare-strategies + render table

**Files:**
- Modify: `benchmark/runner.py` (add `render_strategy_table`)
- Modify: `benchmark/__main__.py` (add `--compare-strategies`)
- Test: `tests/test_benchmark_strategies.py`

**Interfaces:**
- Consumes: `run_strategy_comparison` (Task 2).
- Produces: `render_strategy_table(reports: dict) -> str`; CLI flag `--compare-strategies`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_benchmark_strategies.py
from benchmark.runner import render_strategy_table


def test_render_strategy_table_has_all_strategy_columns():
    def _rep():
        return {
            "by_type": {"NAME": {"recall": 0.5, "precision": 1.0}},
            "overall": {"recall": 0.5, "precision": 1.0, "coverage_recall": 0.6},
            "seed": 42, "size": 10, "source": "gold",
        }
    reports = {k: _rep() for k in ["crf", "wcb", "union", "route"]}
    out = render_strategy_table(reports)
    for col in ["crf_R", "wcb_R", "union_R", "route_R"]:
        assert col in out
    assert "NAME" in out
    assert "OVERALL_R" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_strategies.py::test_render_strategy_table_has_all_strategy_columns -v`
Expected: FAIL with `ImportError: cannot import name 'render_strategy_table'`.

- [ ] **Step 3: Write minimal implementation**

Append to `benchmark/runner.py`:

```python
def render_strategy_table(reports: dict) -> str:
    order = ["crf", "wcb", "union", "route"]
    base = reports[order[0]]
    types = sorted(base["by_type"])
    lines = [
        f"strategy comparison source={base.get('source', 'synthetic')} "
        f"seed={base['seed']} size={base['size']}  (values = recall)",
        f"{'type':<16}" + "".join(f"{s + '_R':>10}" for s in order),
    ]
    for t in types:
        row = f"{t:<16}"
        for s in order:
            c = reports[s]["by_type"].get(t)
            row += f"{c['recall']:>10.3f}" if c else f"{'-':>10}"
        lines.append(row)
    lines.append(f"{'OVERALL_R':<16}" + "".join(f"{reports[s]['overall']['recall']:>10.3f}" for s in order))
    lines.append(f"{'OVERALL_P':<16}" + "".join(f"{reports[s]['overall']['precision']:>10.3f}" for s in order))
    lines.append(f"{'coverage':<16}" + "".join(f"{reports[s]['overall']['coverage_recall']:>10.3f}" for s in order))
    return "\n".join(lines)
```

Replace the body of `main()` in `benchmark/__main__.py` with (adds the flag and branch; keeps the existing single-engine path):

```python
from __future__ import annotations

import argparse
import json
import sys

from .runner import run_benchmark, render_table, run_strategy_comparison, render_strategy_table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="benchmark")
    ap.add_argument("--engine", default="crf", choices=["crf", "wangchanberta"])
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "gold"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--compare-strategies", action="store_true",
                    help="score crf/wcb/union/route on one corpus")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    if args.compare_strategies:
        reports = run_strategy_comparison(source=args.source, seed=args.seed, size=args.size)
        print(render_strategy_table(reports))
        report_out = reports
    else:
        report_out = run_benchmark(
            engine=args.engine, seed=args.seed, size=args.size, source=args.source
        )
        print(render_table(report_out))

    if args.json:
        import os
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report_out, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_strategies.py::test_render_strategy_table_has_all_strategy_columns -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass, only the pre-existing optional-dependency skips.

- [ ] **Step 6: Commit**

```bash
git add benchmark/runner.py benchmark/__main__.py tests/test_benchmark_strategies.py
git commit -m "feat(benchmark): --compare-strategies CLI + strategy table renderer"
```

---

### Task 4: run the comparison and write the ADR

**Files:**
- Create: `docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md`
- (Writes gitignored JSON to `benchmark/reports/` — do not commit those.)

**Interfaces:**
- Consumes: the `--compare-strategies` CLI (Task 3).
- Produces: the ADR decision document.

- [ ] **Step 1: Run the gold comparison**

Run:
```
$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'
.\.venv\Scripts\python.exe -m benchmark --compare-strategies --source gold --json benchmark/reports/strategies-gold.json
```
Expected: a printed 4-column recall table; capture the numbers.

- [ ] **Step 2: Run the synthetic comparison**

Run:
```
$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'
.\.venv\Scripts\python.exe -m benchmark --compare-strategies --source synthetic --seed 42 --size 200 --json benchmark/reports/strategies-syn.json
```
Expected: a printed 4-column recall table; capture the numbers.

- [ ] **Step 3: Write the ADR**

Create `docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md` with these sections (fill tables from Steps 1-2 JSON; write prose in Thai per repo style — spaces, no `:`/`;`/`—`):

1. **หัวเรื่อง + สถานะ + วันที่ 2026-07-15** — ADR NER engine strategy, status "ตัดสินแล้ว".
2. **บริบท** — link the strategy-comparison design, the gold-v2 design, and the stack-selection doc. State the conflict (stack doc says WCB-primary; gold says WCB loses NAME-without-cue).
3. **ตารางผล gold** — per-type recall for crf/wcb/union/route + overall recall/precision/coverage. Focus rows: NAME, ADDRESS, per-slice name_no_cue/address_varied.
4. **ตารางผล synthetic** — same shape.
5. **การตัดสิน** — pick a strategy under the invariant recall > precision. State it explicitly (one of crf/wcb/union/route) and why, citing the two tables.
6. **Trade-off** — crf fastest/lowest recall; wcb lifts ADDRESS but drops NAME-without-cue; union highest recall but 2× NER cost + precision drop; route balances but still 2× cost (WCB ~1.3s/sentence CPU). union and route both pay the WCB cost.
7. **Reconcile กับ stack-selection doc** — does the WCB-primary recommendation still stand, change to the chosen strategy, or get qualified.
8. **นัยต่อ Rust rewrite** — whether the chosen strategy forces carrying two engines (affects the ort/ONNX plan).
9. **สิ่งที่ยังไม่ทำ** — implementing the chosen strategy in `detect_tb` is a separate follow-up; weighted-vote/confidence-gate not evaluated.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md
git commit -m "docs(benchmark): ADR - NER engine strategy decision from 4-way comparison"
```

---

## Notes

- The comparison numbers come from a single process running both engines back-to-back (the singleton reset makes this valid, same as v1/v2). `benchmark/reports/*.json` is gitignored — the ADR carries the recorded numbers.
- Gold is a DIAGNOSTIC — the ADR reports numbers straight; do not add recall floors here.
- After the ADR lands, implementing the chosen strategy in the product (`detect_tb`/`detect_all`) is a separate spec → plan → implement cycle.
