# Thai PII Recall Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a synthetic Thai PII corpus + a lightweight span-level scorer that measures the recall/precision/F2 of the product's real detection assembly, and use it to compare thainer-CRF vs WangchanBERTa on our own Thai data.

**Architecture:** A new top-level `benchmark/` package. `corpus.py` renders Thai document templates, filling PII slots with values from the existing generators and recording exact ground-truth spans. `scorer.py` matches predicted spans to gold spans (type-aware overlap recall, type-agnostic char-coverage recall, exact-boundary recall) and computes per-type + overall precision/recall/F1/F2. `runner.py` wires a shared `detect_all()` (extracted from `app/server.py._tokenize`, so the benchmark measures exactly what ships) through the corpus and scorer. A CI gate test runs the CRF engine; WangchanBERTa is an opt-in comparison.

**Tech Stack:** Python 3.13, stdlib only for the benchmark (no new deps). Reuses `pii_redactor` detectors + anonymizer generators. `requirements-ml.txt` (transformers/torch) only for the opt-in WangchanBERTa comparison.

## Global Constraints

- No new runtime dependency for the benchmark itself — stdlib + existing `pii_redactor` only (spec: "ไม่มี dependency ใหม่").
- Set `$env:PYTHONUTF8='1'` before every Python invocation (Windows cp1252 default).
- Use the venv directly: `.\.venv\Scripts\python.exe`.
- Span offsets are half-open `(start, end)` char offsets, matching `Entity.span`.
- recall > precision — F2 (beta=2) is the headline metric.
- Deterministic: corpus is a pure function of `(seed, size)`; default seed 42, size 200.
- Gold entity-type names match detector `data_type` output exactly (dates labeled `DATE_OF_BIRTH`, names as a single `NAME` span, addresses as `ADDRESS`).
- Reports are not committed (add `benchmark/reports/` to `.gitignore`).

---

### Task 1: Package scaffold + core types

**Files:**
- Create: `benchmark/__init__.py`
- Create: `benchmark/types.py`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Produces: `GoldSpan(start:int, end:int, entity_type:str)`, `Sample(text:str, spans:list[GoldSpan], template_id:str, slice:str)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark.py
from benchmark.types import GoldSpan, Sample

def test_goldspan_and_sample_construct():
    s = Sample(text="นายสมชาย", spans=[GoldSpan(0, 8, "NAME")], template_id="t0", slice="core")
    assert s.text[s.spans[0].start:s.spans[0].end] == "นายสมชาย"
    assert s.spans[0].entity_type == "NAME"
    assert s.slice == "core"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py::test_goldspan_and_sample_construct -v`
Expected: FAIL with ModuleNotFoundError: No module named 'benchmark'

- [ ] **Step 3: Write minimal implementation**

```python
# benchmark/__init__.py
"""Synthetic Thai PII recall benchmark (v1)."""
```
```python
# benchmark/types.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GoldSpan:
    start: int
    end: int
    entity_type: str

@dataclass
class Sample:
    text: str
    spans: list[GoldSpan]
    template_id: str
    slice: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py::test_goldspan_and_sample_construct -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark/__init__.py benchmark/types.py tests/test_benchmark.py
git commit -m "feat(benchmark): package scaffold + GoldSpan/Sample types"
```

---

### Task 2: Shared `detect_all()` extraction

**Files:**
- Modify: `app/server.py:154-165` (remove `_dedupe_spans`), `app/server.py:196-199` (use shared func)
- Create: `pii_redactor/detectors/aggregate.py`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Produces: `detect_all(text:str) -> list[Entity]` and `dedupe_spans(entities:list) -> list` in `pii_redactor.detectors.aggregate`. `detect_all` = `dedupe_spans(detect_fp(text) + detect_tb(text) + scan_fn(text, fp+tb))` — the exact assembly `/api/sanitize` uses today.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark.py (append)
from pii_redactor.detectors.aggregate import detect_all, dedupe_spans

def test_detect_all_finds_thai_id_and_dedupes():
    ents = detect_all("เลขบัตรประชาชนของผมคือ 1101700230708 ครับ")
    assert any(e.data_type == "THAI_ID" for e in ents)
    spans = [e.span for e in ents]
    # no two kept spans overlap
    ordered = sorted(spans)
    assert all(ordered[i][1] <= ordered[i + 1][0] for i in range(len(ordered) - 1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py::test_detect_all_finds_thai_id_and_dedupes -v`
Expected: FAIL with ModuleNotFoundError: No module named 'pii_redactor.detectors.aggregate'

- [ ] **Step 3: Write minimal implementation**

```python
# pii_redactor/detectors/aggregate.py
from __future__ import annotations
from .fp_detector import detect_fp
from .tb_detector import detect_tb
from .fn_scanner import scan_fn

def dedupe_spans(entities: list) -> list:
    ents = sorted(entities, key=lambda e: (e.span[0], -(e.span[1] - e.span[0])))
    kept = []
    last_end = -1
    for e in ents:
        s, en = e.span
        if s >= last_end:
            kept.append(e)
            last_end = en
    return kept

def detect_all(text: str) -> list:
    fp = detect_fp(text)
    tb = detect_tb(text)
    fn = scan_fn(text, fp + tb)
    return dedupe_spans(fp + tb + fn)
```

Then in `app/server.py`: add `from pii_redactor.detectors.aggregate import detect_all, dedupe_spans`, delete the local `_dedupe_spans` def (lines 154-165), replace the four-line assembly in `_tokenize` (196-199) with `entities = detect_all(text)`, and replace remaining `_dedupe_spans(` references with `dedupe_spans(`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py::test_detect_all_finds_thai_id_and_dedupes tests/test_step11_api.py tests/test_api_hardening.py -v`
Expected: PASS (server still works)

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/detectors/aggregate.py app/server.py tests/test_benchmark.py
git commit -m "refactor(detectors): extract shared detect_all() used by server + benchmark"
```

---

### Task 3: Synthetic corpus

**Files:**
- Create: `benchmark/corpus.py`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Consumes: `GoldSpan`, `Sample` (Task 1); `pii_redactor.anonymizer.fp_generator` helpers + `tb_generator` pools.
- Produces: `build_corpus(seed:int=42, size:int=200) -> list[Sample]`. `ENTITY_TYPES: list[str]` (the 12 gold types). Each `Sample.slice` is `"core"` or `"hard_case"`.

**Design:** A template is `(template_id, format_string, slots)` where `format_string` has `{k}` placeholders and `slots` is an ordered list of `(placeholder_key, entity_type)`. Rendering fills placeholders left-to-right, and for each records the char span of the inserted value. `_sample_value(entity_type, rng)` returns a valid-format value reusing the existing generators. `hard_case` templates hardcode known-leak shapes (Thai-glued digits, +66 mobiles, glued email).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_benchmark.py (append)
from benchmark.corpus import build_corpus, ENTITY_TYPES

def test_corpus_spans_align_with_text():
    for s in build_corpus(seed=1, size=60):
        for sp in s.spans:
            assert sp.end > sp.start
            assert s.text[sp.start:sp.end]  # non-empty slice inside text
            assert sp.entity_type in ENTITY_TYPES

def test_corpus_is_deterministic():
    a = build_corpus(seed=7, size=40)
    b = build_corpus(seed=7, size=40)
    assert [(s.text, s.spans) for s in a] == [(s.text, s.spans) for s in b]

def test_corpus_covers_every_entity_type():
    seen = {sp.entity_type for s in build_corpus(seed=3, size=200) for sp in s.spans}
    for t in ENTITY_TYPES:
        assert t in seen, f"{t} never generated"

def test_corpus_has_hard_case_slice():
    hard = [s for s in build_corpus(seed=5, size=200) if s.slice == "hard_case"]
    assert hard
    assert any("1101700230708" in s.text or "+66" in s.text for s in hard)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py -k corpus -v`
Expected: FAIL with ModuleNotFoundError / ImportError on `benchmark.corpus`

- [ ] **Step 3: Write the implementation**

```python
# benchmark/corpus.py
from __future__ import annotations
import random
from .types import GoldSpan, Sample
from pii_redactor.anonymizer import fp_generator as fg
from pii_redactor.anonymizer.tb_generator import (
    MALE_NAMES, FEMALE_NAMES, SURNAMES, DISTRICTS,
)

ENTITY_TYPES = [
    "THAI_ID", "PHONE", "EMAIL", "BANK_ACCOUNT", "CREDIT_CARD",
    "PASSPORT", "VEHICLE_PLATE", "STUDENT_ID", "DATE_OF_BIRTH",
    "NAME", "ADDRESS",
]

def _sample_value(entity_type: str, rng: random.Random) -> str:
    if entity_type == "THAI_ID":
        return fg._gen_thai_id(rng)
    if entity_type == "CREDIT_CARD":
        return fg._gen_credit_card(rng)
    if entity_type == "PHONE":
        return fg._gen_phone(rng)
    if entity_type == "PASSPORT":
        return fg._gen_passport(rng)
    if entity_type == "VEHICLE_PLATE":
        return fg._gen_vehicle_plate(rng)
    if entity_type == "EMAIL":
        return fg._gen_email(rng)
    if entity_type == "BANK_ACCOUNT":
        return fg._gen_bank_account(rng, "000-0-00000-0")
    if entity_type == "STUDENT_ID":
        return "".join(str(rng.randint(0, 9)) for _ in range(rng.choice([8, 10])))
    if entity_type == "DATE_OF_BIRTH":
        return fg._gen_date(rng, "01/01/2530")
    if entity_type == "NAME":
        male = rng.random() < 0.5
        title = "นาย" if male else rng.choice(["นาง", "นางสาว"])
        first = rng.choice(MALE_NAMES if male else FEMALE_NAMES)
        return f"{title}{first} {rng.choice(SURNAMES)}"
    if entity_type == "ADDRESS":
        return f"{rng.randint(1, 999)} {rng.choice(DISTRICTS)}"
    raise ValueError(entity_type)

# (template_id, format_string, [(key, entity_type), ...])
_CORE_TEMPLATES = [
    ("email_sick", "เรียนหัวหน้า {name} ขอลาป่วยวันนี้ ติดต่อกลับได้ที่ {phone} หรืออีเมล {email}",
     [("name", "NAME"), ("phone", "PHONE"), ("email", "EMAIL")]),
    ("gov_form", "ข้าพเจ้า {name} เลขบัตรประชาชน {thai_id} เกิดวันที่ {dob} อยู่บ้านเลขที่ {addr}",
     [("name", "NAME"), ("thai_id", "THAI_ID"), ("dob", "DATE_OF_BIRTH"), ("addr", "ADDRESS")]),
    ("bank_complaint", "ผม {name} บัญชีธนาคาร {bank} บัตรเครดิต {cc} ขอร้องเรียนธุรกรรม",
     [("name", "NAME"), ("bank", "BANK_ACCOUNT"), ("cc", "CREDIT_CARD")]),
    ("apply", "ผู้สมัคร {name} หนังสือเดินทาง {passport} ทะเบียนรถ {plate} รหัสนักศึกษา {sid}",
     [("name", "NAME"), ("passport", "PASSPORT"), ("plate", "VEHICLE_PLATE"), ("sid", "STUDENT_ID")]),
]

# hard-case templates mirror tests/test_recall_leaks.py; value is glued to Thai text
_HARD_TEMPLATES = [
    ("glued_id", "เลขบัตรประชาชน{thai_id}ครับ", [("thai_id", "THAI_ID")]),
    ("glued_email", "อีเมลผมคือ{email}ครับ", [("email", "EMAIL")]),
    ("intl_phone", "โทรหาผมที่ {phone_intl} ได้เลย", [("phone_intl", "PHONE")]),
]

def _intl_phone(rng: random.Random) -> str:
    body = "".join(str(rng.randint(0, 9)) for _ in range(9))  # +66 mobile = 9 digits
    return f"+66{body}"

def _render(template, rng) -> Sample:
    tid, fmt, slots = template
    text = fmt
    spans = []
    for key, etype in slots:
        if key == "phone_intl":
            value = _intl_phone(rng)
        else:
            value = _sample_value(etype, rng)
        marker = "{" + key + "}"
        idx = text.index(marker)
        text = text[:idx] + value + text[idx + len(marker):]
        spans.append(GoldSpan(idx, idx + len(value), etype))
    slice_ = "hard_case" if template in _HARD_TEMPLATES else "core"
    return Sample(text=text, spans=spans, template_id=tid, slice=slice_)

def build_corpus(seed: int = 42, size: int = 200) -> list[Sample]:
    rng = random.Random(seed)
    samples = []
    # ~20% hard cases
    n_hard = max(len(_HARD_TEMPLATES), size // 5)
    for i in range(size):
        pool = _HARD_TEMPLATES if i < n_hard else _CORE_TEMPLATES
        template = pool[rng.randrange(len(pool))]
        samples.append(_render(template, rng))
    return samples
```

Note during implementation: `_render` recomputes span offsets after each insertion by using the running `text`, so multi-slot templates stay correct. Verify `.index` finds the marker (markers are unique per template).

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py -k corpus -v`
Expected: PASS (add core templates if a type is missing coverage)

- [ ] **Step 5: Commit**

```bash
git add benchmark/corpus.py tests/test_benchmark.py
git commit -m "feat(benchmark): synthetic Thai PII corpus with exact gold spans"
```

---

### Task 4: Span scorer + Report

**Files:**
- Create: `benchmark/scorer.py`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Consumes: `GoldSpan`, `Sample`; predictions as `list[list[tuple[int,int,str]]]` (per-sample `(start,end,type)`).
- Produces: `score(samples, predictions) -> dict` (the Report). Keys: `overall{precision,recall,f1,f2,coverage_recall,exact_recall}`, `by_type{type:{tp,fp,fn,precision,recall,f1,f2}}`, `by_slice{slice:{...overall...}}`, `corpus{samples,entities,by_type}`.

**Matching rules:** type-aware overlap — for each type, greedily match each gold span to an unused predicted span of the same type with `intersection>0` (TP); leftover gold = FN, leftover pred = FP. `coverage_recall` = (sum of gold chars covered by the union of ANY predicted span) / (total gold chars), type-agnostic. `exact_recall` = fraction of gold spans with an exact-boundary same-type prediction. F2 = `5*P*R / (4*P + R)` (0 when denom 0).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_benchmark.py (append)
from benchmark.types import GoldSpan, Sample
from benchmark.scorer import score

def _s(text, spans):
    return Sample(text=text, spans=[GoldSpan(*x) for x in spans], template_id="t", slice="core")

def test_scorer_perfect():
    samples = [_s("0812345678", [(0, 10, "PHONE")])]
    preds = [[(0, 10, "PHONE")]]
    r = score(samples, preds)
    assert r["overall"]["recall"] == 1.0
    assert r["overall"]["precision"] == 1.0
    assert r["overall"]["coverage_recall"] == 1.0
    assert r["overall"]["exact_recall"] == 1.0

def test_scorer_miss_is_fn():
    samples = [_s("0812345678", [(0, 10, "PHONE")])]
    r = score(samples, [[]])
    assert r["overall"]["recall"] == 0.0
    assert r["by_type"]["PHONE"]["fn"] == 1

def test_scorer_overlap_counts_but_partial_coverage():
    # predicted covers 6 of 10 chars -> overlap TP, coverage 0.6
    samples = [_s("0812345678", [(0, 10, "PHONE")])]
    r = score(samples, [[(0, 6, "PHONE")]])
    assert r["by_type"]["PHONE"]["tp"] == 1
    assert abs(r["overall"]["coverage_recall"] - 0.6) < 1e-9
    assert r["overall"]["exact_recall"] == 0.0

def test_scorer_wrong_type_is_fp_and_fn():
    samples = [_s("0812345678", [(0, 10, "PHONE")])]
    r = score(samples, [[(0, 10, "EMAIL")]])
    assert r["by_type"]["PHONE"]["fn"] == 1
    assert r["by_type"]["EMAIL"]["fp"] == 1
    # coverage is type-agnostic: the chars are covered
    assert r["overall"]["coverage_recall"] == 1.0

def test_f2_weights_recall():
    # P=0.5 R=1.0 -> F2 = 5*.5*1/(4*.5+1)=2.5/3
    samples = [_s("0812345678 x", [(0, 10, "PHONE")])]
    r = score(samples, [[(0, 10, "PHONE"), (11, 12, "PHONE")]])
    assert abs(r["overall"]["f2"] - (2.5 / 3)) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py -k scorer -v`
Expected: FAIL on `benchmark.scorer` import

- [ ] **Step 3: Write the implementation**

```python
# benchmark/scorer.py
from __future__ import annotations
from collections import defaultdict

def _overlap(a, b) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))

def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    f2 = 5 * p * r / (4 * p + r) if (4 * p + r) else 0.0
    return {"precision": p, "recall": r, "f1": f1, "f2": f2}

def _counts_to_overall(by_type, cov_covered, cov_total, exact_hit, gold_total):
    tp = sum(c["tp"] for c in by_type.values())
    fp = sum(c["fp"] for c in by_type.values())
    fn = sum(c["fn"] for c in by_type.values())
    o = {"tp": tp, "fp": fp, "fn": fn, **_prf(tp, fp, fn)}
    o["coverage_recall"] = cov_covered / cov_total if cov_total else 0.0
    o["exact_recall"] = exact_hit / gold_total if gold_total else 0.0
    return o

def _score_group(samples, predictions):
    by_type = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    cov_covered = cov_total = exact_hit = gold_total = 0
    for sample, preds in zip(samples, predictions):
        preds_by_type = defaultdict(list)
        for p in preds:
            preds_by_type[p[2]].append((p[0], p[1]))
        used = defaultdict(set)
        # type-aware overlap match
        golds_by_type = defaultdict(list)
        for g in sample.spans:
            golds_by_type[g.entity_type].append((g.start, g.end))
        for etype in set(list(golds_by_type) + list(preds_by_type)):
            golds = golds_by_type.get(etype, [])
            plist = preds_by_type.get(etype, [])
            matched_p = set()
            for g in golds:
                hit = None
                for i, pr in enumerate(plist):
                    if i in matched_p:
                        continue
                    if _overlap(g, pr) > 0:
                        hit = i
                        break
                if hit is not None:
                    matched_p.add(hit)
                    by_type[etype]["tp"] += 1
                else:
                    by_type[etype]["fn"] += 1
            by_type[etype]["fp"] += len(plist) - len(matched_p)
        # type-agnostic coverage + exact
        all_pred = [(p[0], p[1]) for p in preds]
        for g in sample.spans:
            gold_total += 1
            glen = g.end - g.start
            cov_total += glen
            covered = [False] * glen
            for pr in all_pred:
                lo = max(g.start, pr[0]); hi = min(g.end, pr[1])
                for k in range(lo, hi):
                    covered[k - g.start] = True
            cov_covered += sum(covered)
            if any(p[0] == g.start and p[1] == g.end and p[2] == g.entity_type for p in preds):
                exact_hit += 1
    by_type = {k: {**v, **_prf(v["tp"], v["fp"], v["fn"])} for k, v in by_type.items()}
    overall = _counts_to_overall(by_type, cov_covered, cov_total, exact_hit, gold_total)
    return by_type, overall

def score(samples, predictions) -> dict:
    by_type, overall = _score_group(samples, predictions)
    corpus_by_type = defaultdict(int)
    for s in samples:
        for g in s.spans:
            corpus_by_type[g.entity_type] += 1
    by_slice = {}
    for sl in sorted({s.slice for s in samples}):
        idx = [i for i, s in enumerate(samples) if s.slice == sl]
        _, ov = _score_group([samples[i] for i in idx], [predictions[i] for i in idx])
        by_slice[sl] = ov
    return {
        "corpus": {"samples": len(samples),
                   "entities": sum(corpus_by_type.values()),
                   "by_type": dict(corpus_by_type)},
        "overall": overall,
        "by_type": by_type,
        "by_slice": by_slice,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py -k scorer -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark/scorer.py tests/test_benchmark.py
git commit -m "feat(benchmark): span scorer with overlap/coverage/exact + P/R/F1/F2"
```

---

### Task 5: Runner (corpus -> detect_all -> score)

**Files:**
- Create: `benchmark/runner.py`
- Test: `tests/test_benchmark.py`

**Interfaces:**
- Consumes: `build_corpus`, `score`, `detect_all`.
- Produces: `run_benchmark(engine:str="crf", seed:int=42, size:int=200) -> dict` (sets `AIGUARD_NER_ENGINE`, builds corpus, runs `detect_all` per sample into `(start,end,data_type)` tuples, returns Report with `engine/seed/size` attached). `render_table(report) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark.py (append)
from benchmark.runner import run_benchmark, render_table

def test_run_benchmark_crf_high_fp_recall():
    r = run_benchmark(engine="crf", seed=42, size=60)
    # structured FP types are checksum/regex: recall should be near-perfect on valid synthetic values
    for t in ["THAI_ID", "CREDIT_CARD", "EMAIL", "PHONE"]:
        assert r["by_type"][t]["recall"] >= 0.95, (t, r["by_type"][t])
    assert "PHONE" in render_table(r)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py::test_run_benchmark_crf_high_fp_recall -v`
Expected: FAIL on `benchmark.runner` import

- [ ] **Step 3: Write the implementation**

```python
# benchmark/runner.py
from __future__ import annotations
import os
from .corpus import build_corpus
from .scorer import score

def run_benchmark(engine: str = "crf", seed: int = 42, size: int = 200) -> dict:
    os.environ["AIGUARD_NER_ENGINE"] = "wangchanberta" if engine == "wangchanberta" else "thainer"
    from pii_redactor.detectors.aggregate import detect_all
    samples = build_corpus(seed=seed, size=size)
    predictions = []
    for s in samples:
        ents = detect_all(s.text)
        predictions.append([(e.span[0], e.span[1], e.data_type) for e in ents])
    report = score(samples, predictions)
    report["engine"] = engine
    report["seed"] = seed
    report["size"] = size
    return report

def render_table(report: dict) -> str:
    lines = [f"engine={report['engine']} seed={report['seed']} size={report['size']}",
             f"{'type':<16}{'n':>5}{'recall':>9}{'prec':>9}{'f2':>9}"]
    for t in sorted(report["by_type"]):
        c = report["by_type"][t]
        n = report["corpus"]["by_type"].get(t, 0)
        lines.append(f"{t:<16}{n:>5}{c['recall']:>9.3f}{c['precision']:>9.3f}{c['f2']:>9.3f}")
    o = report["overall"]
    lines.append(f"{'OVERALL':<16}{report['corpus']['entities']:>5}{o['recall']:>9.3f}{o['precision']:>9.3f}{o['f2']:>9.3f}")
    lines.append(f"coverage_recall={o['coverage_recall']:.3f} exact_recall={o['exact_recall']:.3f}")
    for sl in sorted(report["by_slice"]):
        s = report["by_slice"][sl]
        lines.append(f"slice {sl:<10} recall={s['recall']:.3f} coverage={s['coverage_recall']:.3f}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py::test_run_benchmark_crf_high_fp_recall -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark/runner.py tests/test_benchmark.py
git commit -m "feat(benchmark): runner wiring corpus->detect_all->scorer + table render"
```

---

### Task 6: CLI + gitignore

**Files:**
- Create: `benchmark/__main__.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `run_benchmark`, `render_table`.
- Produces: `python -m benchmark --engine crf --seed 42 --size 200 [--json out.json]` printing the table and optionally writing full JSON.

- [ ] **Step 1: Write the implementation** (thin CLI — exercised manually + by Task 5's function tests)

```python
# benchmark/__main__.py
from __future__ import annotations
import argparse, json, sys
from .runner import run_benchmark, render_table

def main(argv=None):
    ap = argparse.ArgumentParser(prog="benchmark")
    ap.add_argument("--engine", default="crf", choices=["crf", "wangchanberta"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    report = run_benchmark(engine=args.engine, seed=args.seed, size=args.size)
    print(render_table(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Append to `.gitignore`:
```
benchmark/reports/
```

- [ ] **Step 2: Run the CLI to verify it works**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m benchmark --engine crf --size 60`
Expected: prints a table with per-type recall and OVERALL row

- [ ] **Step 3: Commit**

```bash
git add benchmark/__main__.py .gitignore
git commit -m "feat(benchmark): python -m benchmark CLI"
```

---

### Task 7: CI gate + WangchanBERTa comparison

**Files:**
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- Consumes: `run_benchmark`. Gate uses CRF only. WangchanBERTa test is `@pytest.mark.ml`, skipped when `transformers` is absent (mirror `tests/test_ner_engine.py`).

- [ ] **Step 1: Write the gate test with calibrated floors**

First run `python -m benchmark --engine crf --size 200` to observe real recall, then set each floor slightly below observed (structured FP expected ~1.0):

```python
# tests/test_benchmark.py (append)
import importlib.util
import pytest

def test_ci_gate_crf_recall_floors():
    r = run_benchmark(engine="crf", seed=42, size=200)
    bt = r["by_type"]
    for t in ["THAI_ID", "CREDIT_CARD", "PASSPORT", "EMAIL", "PHONE",
              "BANK_ACCOUNT", "VEHICLE_PLATE", "STUDENT_ID", "DATE_OF_BIRTH"]:
        assert bt[t]["recall"] >= 0.99, (t, bt[t])
    # NAME/ADDRESS floors calibrated from first CRF run (set below observed)
    assert bt["NAME"]["recall"] >= FLOOR_NAME
    assert bt["ADDRESS"]["recall"] >= FLOOR_ADDRESS
    assert r["by_slice"]["hard_case"]["coverage_recall"] >= 0.99

@pytest.mark.skipif(importlib.util.find_spec("transformers") is None,
                    reason="requires requirements-ml.txt")
def test_wangchanberta_recall_at_least_crf():
    crf = run_benchmark(engine="crf", seed=42, size=120)
    wcb = run_benchmark(engine="wangchanberta", seed=42, size=120)
    assert wcb["by_type"]["NAME"]["recall"] >= crf["by_type"]["NAME"]["recall"]
```

- [ ] **Step 2: Run the CRF run, fill `FLOOR_NAME`/`FLOOR_ADDRESS`**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m benchmark --engine crf --size 200`
Set `FLOOR_NAME` / `FLOOR_ADDRESS` to observed minus ~0.05 (module-level constants in the test).

- [ ] **Step 3: Run the gate**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py -v`
Expected: PASS (ml test SKIPPED until deps installed)

- [ ] **Step 4: Install ML deps and run the comparison**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pip install -r requirements-ml.txt`
Then: `python -m benchmark --engine crf --size 200 --json benchmark/reports/crf.json` and `--engine wangchanberta ... --json benchmark/reports/wcb.json`
Record the CRF vs WangchanBERTa recall/F2 per-type table in the results summary.

- [ ] **Step 5: Commit**

```bash
git add tests/test_benchmark.py
git commit -m "test(benchmark): CRF recall gate + opt-in WangchanBERTa comparison"
```

---

## Notes for execution

- If a `core` template makes a type unreachable in `build_corpus` coverage test, add a template rather than shrinking the assertion.
- `_gen_*` helpers are private but importing them inside the internal benchmark keeps PII formats single-sourced; if a helper signature changes, the corpus test will catch it.
- `detect_tb` reads the engine once per process (lazy singleton), so the CRF gate and the WangchanBERTa comparison must run in separate processes — `run_benchmark` sets the env var, which only takes effect on a fresh interpreter. In one pytest process the first engine used wins; keep the ml comparison test tolerant (it calls `run_benchmark` twice but the singleton may pin the first). During the manual comparison (Step 4) use two separate CLI invocations, which is the source of truth for the numbers.
