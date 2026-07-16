# Union NER in detect_tb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `AIGUARD_NER_ENGINE=union` mode to `detect_tb` that runs both thainer (CRF) and wangchanberta and unions their NER spans, per the strategy-comparison ADR.

**Architecture:** Replace the single `tb_detector._ner` singleton with a name-keyed `_ner_cache` so two engines can be held at once. Extract the sliding-window NER loop into a `_ner_candidates` helper; `detect_tb` runs it once (single mode) or twice (union), adds the name-context booster once, and dedupes. Default stays thainer; union fails loudly without transformers.

**Tech Stack:** Python 3.13, PyThaiNLP `NER`. WangchanBERTa (thainer-v2) needs `requirements-ml.txt` (torch/transformers), already installed in `.venv`.

## Global Constraints

- Set `$env:PYTHONUTF8='1'` before every Python run (add `$env:HF_HUB_DISABLE_PROGRESS_BARS='1'` for WangchanBERTa runs). Use `.\.venv\Scripts\python.exe`. Windows machine, PowerShell shell. Use a long timeout (300000-600000 ms) for any pytest that loads WangchanBERTa.
- Opt-in only: default `AIGUARD_NER_ENGINE` is `thainer`. Do NOT change the default. Do NOT modify `requirements.txt` (core stays CRF-only, no torch).
- `union` requires transformers; if absent it must raise `tb_detector.NEREngineUnavailableError` (fail loudly — no silent fallback to CRF).
- Do NOT change `benchmark/scorer.py`, `benchmark/corpus.py`, `benchmark/gold.py`, `benchmark/strategies.py`, or product callers (`app/server.py`, `ai_guard.py`, `pii_redactor/ai_client.py`, `pii_redactor/pipeline.py`) — `detect_tb` is the single chokepoint and its return contract is unchanged.
- Reuse the existing `_deduplicate` in `tb_detector.py` and `detect_name_context` from `pii_redactor/detectors/name_context.py` unchanged.

---

### Task 1: name-keyed engine cache (refactor, no behaviour change)

**Files:**
- Modify: `pii_redactor/detectors/tb_detector.py` (replace `_ner` singleton + `_get_ner`)
- Modify: `tests/test_ner_engine.py` (update `_reset`, add a cache-hit test)
- Modify: `benchmark/runner.py` (the two blocks that poke `tb_detector._ner`)

**Interfaces:**
- Produces: module attribute `_ner_cache: dict[str, NER]`; `_load_ner(name: str) -> NER`; `_get_ner() -> NER` (unchanged public behaviour — reads env, returns the engine).
- Consumes: existing `_ENGINE_CONFIG`, `NEREngineUnavailableError`, `NER`.

- [ ] **Step 1: Update the test reset + add a cache-hit test** in `tests/test_ner_engine.py`

Replace the `_reset` helper (currently `monkeypatch.setattr(tb_detector, "_ner", None)`) with:

```python
def _reset(monkeypatch):
    monkeypatch.setattr(tb_detector, "_ner_cache", {})
```

Append this test (proves the cache does not rebuild the engine on the second call):

```python
def test_engine_is_cached_after_first_load(monkeypatch):
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    _reset(monkeypatch)
    calls = {"n": 0}

    class _CountingNER:
        def __init__(self, engine):
            calls["n"] += 1
            self.engine = engine

    monkeypatch.setattr(tb_detector, "NER", _CountingNER)
    first = tb_detector._get_ner()
    second = tb_detector._get_ner()
    assert first is second
    assert calls["n"] == 1
```

- [ ] **Step 2: Run the engine tests to verify the reset break + new test fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_ner_engine.py -v`
Expected: FAIL — `AttributeError`/`AttributeError: <module ...> has no attribute '_ner_cache'` (the module still defines `_ner`, not `_ner_cache`), so the new test and the `_reset` monkeypatch target error out.

- [ ] **Step 3: Refactor the engine holder** in `pii_redactor/detectors/tb_detector.py`. Replace the current singleton block:

```python
# Lazy-initialized NER instance (first call triggers model load)
_ner: NER | None = None


def _get_ner() -> NER:
    global _ner
    if _ner is None:
        name = os.environ.get("AIGUARD_NER_ENGINE", "thainer")
        if name not in _ENGINE_CONFIG:
            raise ValueError(
                f"Unknown AIGUARD_NER_ENGINE={name!r}; "
                f"supported: {sorted(_ENGINE_CONFIG)}"
            )
        config = _ENGINE_CONFIG[name]
        requires = config["requires"]
        if requires is not None:
            try:
                __import__(requires)
            except ImportError:
                raise NEREngineUnavailableError(
                    f"AIGUARD_NER_ENGINE={name!r} requires {requires!r}. "
                    f"Run: pip install -r requirements-ml.txt"
                ) from None
        _ner = NER(engine=config["ner_engine"])
    return _ner
```

with this:

```python
# Lazy NER cache, keyed by AIGUARD_NER_ENGINE value (first use per engine loads
# the model). A dict rather than a single slot so `union` can hold both engines.
_ner_cache: dict[str, "NER"] = {}


def _load_ner(name: str) -> NER:
    """Return the NER engine for a single engine name (thainer / wangchanberta),
    loading and caching it on first use. Raises ValueError for an unknown name
    and NEREngineUnavailableError if the engine's dependency is missing."""
    if name not in _ENGINE_CONFIG:
        raise ValueError(
            f"Unknown AIGUARD_NER_ENGINE={name!r}; "
            f"supported: {sorted(_ENGINE_CONFIG)} (or 'union')"
        )
    if name not in _ner_cache:
        config = _ENGINE_CONFIG[name]
        requires = config["requires"]
        if requires is not None:
            try:
                __import__(requires)
            except ImportError:
                raise NEREngineUnavailableError(
                    f"AIGUARD_NER_ENGINE={name!r} requires {requires!r}. "
                    f"Run: pip install -r requirements-ml.txt"
                ) from None
        _ner_cache[name] = NER(engine=config["ner_engine"])
    return _ner_cache[name]


def _get_ner() -> NER:
    """Select the single engine named by AIGUARD_NER_ENGINE (default thainer)."""
    name = os.environ.get("AIGUARD_NER_ENGINE", "thainer")
    return _load_ner(name)
```

- [ ] **Step 4: Update the benchmark's singleton reset** in `benchmark/runner.py`. There are two blocks that save/reset/restore `tb_detector._ner`. In `run_benchmark`, replace:

```python
    prev_ner = tb_detector._ner
```
```python
    tb_detector._ner = None
```
```python
        tb_detector._ner = prev_ner
```
with, respectively:
```python
    prev_ner = dict(tb_detector._ner_cache)
```
```python
    tb_detector._ner_cache = {}
```
```python
        tb_detector._ner_cache = prev_ner
```

In `run_strategy_comparison`'s `_run` closure, make the identical three substitutions (`prev_ner = dict(tb_detector._ner_cache)`, `tb_detector._ner_cache = {}`, `tb_detector._ner_cache = prev_ner`).

- [ ] **Step 5: Run the engine tests + the benchmark strategy test**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest tests/test_ner_engine.py tests/test_benchmark_strategies.py -v`
Expected: PASS — all six engine tests (default thainer, bogus→ValueError, wcb-without-transformers→NEREngineUnavailableError, wcb→thainer-v2, wcb real PERSON, new cache-hit) plus the strategy-comparison tests. (Loads WangchanBERTa; long timeout.)

- [ ] **Step 6: Commit**

```bash
git add pii_redactor/detectors/tb_detector.py tests/test_ner_engine.py benchmark/runner.py
git commit -m "refactor(detector): name-keyed NER cache (prep for union engine)"
```

---

### Task 2: union mode in detect_tb

**Files:**
- Modify: `pii_redactor/detectors/tb_detector.py` (extract `_ner_candidates`, add union branch in `detect_tb`)
- Modify: `tests/test_ner_engine.py` (union behaviour + fail-loudly tests)
- Modify: `CLAUDE.md` (document the new engine value)

**Interfaces:**
- Consumes: `_load_ner` and `_get_ner` (Task 1); existing `_bio_to_spans`, `LABEL_MAP`, `_deduplicate`, `detect_name_context`.
- Produces: internal `_ner_candidates(text: str, ner, sentence_offsets: list[tuple[str, int]], window_size: int) -> list[Entity]`; `detect_tb` honours `AIGUARD_NER_ENGINE=union`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ner_engine.py`

```python
def test_union_without_transformers_raises(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    _reset(monkeypatch)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("mocked missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from pii_redactor.detectors.tb_detector import detect_tb
    with pytest.raises(tb_detector.NEREngineUnavailableError, match="requirements-ml.txt"):
        detect_tb("นายสมชาย ใจดี อยู่กรุงเทพมหานคร")


def test_union_runs_both_engines_and_merges(monkeypatch):
    pytest.importorskip("transformers")
    _reset(monkeypatch)
    from pii_redactor.detectors.tb_detector import detect_tb

    # Name (title-cued, so it is caught regardless of engine) and a clearly
    # separate address -- disjoint spans, so dedup never drops one for the other.
    text = "นายวิชัย ประสงค์ดี อยู่บ้านเลขที่ 45/12 หมู่ 3 ตำบลบางพระ อำเภอศรีราชา จังหวัดชลบุรี"

    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    crf_types = {e.data_type for e in detect_tb(text)}
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    uni_types = {e.data_type for e in detect_tb(text)}

    # Union mode ran and produced a person + a location.
    assert "NAME" in uni_types
    assert "ADDRESS" in uni_types
    # Union keeps everything CRF alone found (it is a superset here; the two
    # entities are disjoint so no cross-engine overlap can drop a type).
    assert crf_types <= uni_types
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest tests/test_ner_engine.py -k "union" -v`
Expected: FAIL — `detect_tb` does not yet understand `union`; the pre-Task-2 body calls `_get_ner()` which runs `_load_ner("union")` and raises `ValueError: Unknown ... 'union'`, so `test_union_runs_both_engines_and_merges` errors and `test_union_without_transformers_raises` raises ValueError instead of NEREngineUnavailableError.

- [ ] **Step 3: Extract the sliding-window loop into a helper.** In `pii_redactor/detectors/tb_detector.py`, add this function just above `detect_tb`:

```python
def _ner_candidates(
    text: str, ner: NER, sentence_offsets: list[tuple[str, int]], window_size: int
) -> list[Entity]:
    """Run one NER engine over the sliding-sentence windows and return TB
    Entity candidates mapped to original-text offsets (pre-dedup)."""
    candidates: list[Entity] = []
    for i, (sent_text, sent_offset) in enumerate(sentence_offsets):
        window_start = max(0, i - window_size)
        window_end = min(len(sentence_offsets), i + window_size + 1)
        context_sents = sentence_offsets[window_start:window_end]

        context_text = "".join(s for s, _ in context_sents)
        context_sent_start = sum(len(s) for s, _ in context_sents[: i - window_start])
        context_sent_end = context_sent_start + len(sent_text)

        try:
            tagged: list[tuple[str, str]] = ner.tag(context_text)
        except Exception:
            continue
        if not tagged:
            continue

        raw_spans = _bio_to_spans(tagged, context_text)
        for ent_text, ctx_start, ctx_end, label in raw_spans:
            if ctx_start < context_sent_start or ctx_end > context_sent_end:
                continue
            data_type = LABEL_MAP.get(label)
            if data_type is None:
                continue
            orig_start = sent_offset + (ctx_start - context_sent_start)
            orig_end = sent_offset + (ctx_end - context_sent_start)
            if (orig_end - orig_start) < 2:
                continue
            candidates.append(Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="TB",
                data_type=data_type,
                span=(orig_start, orig_end),
                score=0.85,
                original_text=text[orig_start:orig_end],
            ))
    return candidates
```

- [ ] **Step 4: Rewrite `detect_tb` to use the helper + union branch.** Replace the body of `detect_tb` (everything after its docstring) with:

```python
    if not text or not text.strip():
        return []

    # Step 1: Sentence tokenization with cumulative offsets
    raw_sentences = sent_tokenize(text, engine="crfcut")
    if not raw_sentences:
        return []

    sentence_offsets: list[tuple[str, int]] = []
    pos = 0
    for sent in raw_sentences:
        idx = text.find(sent, pos)
        if idx == -1:
            idx = pos
        sentence_offsets.append((sent, idx))
        pos = idx + len(sent)

    # Engine selection: union runs both, everything else is a single engine.
    name = os.environ.get("AIGUARD_NER_ENGINE", "thainer")
    if name == "union":
        ners = [_load_ner("thainer"), _load_ner("wangchanberta")]
    else:
        ners = [_get_ner()]

    candidates: list[Entity] = []
    for ner in ners:
        candidates.extend(_ner_candidates(text, ner, sentence_offsets, window_size))

    # Recall booster: title/label-cued names the NER missed or clipped
    # (engine-independent, added once).
    from pii_redactor.detectors.name_context import detect_name_context
    candidates.extend(detect_name_context(text))

    # Deduplication
    return _deduplicate(candidates)
```

- [ ] **Step 5: Run the union tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest tests/test_ner_engine.py -v`
Expected: PASS (all engine tests including the two new union tests). Long timeout.

- [ ] **Step 6: Document the new engine value** in `CLAUDE.md`. Find the sentence describing the WangchanBERTa engine option (contains `AIGUARD_NER_ENGINE=wangchanberta`) and append after it, in the same paragraph:

```
A third value `AIGUARD_NER_ENGINE=union` runs thainer (CRF) and WangchanBERTa together and unions their NER spans (highest recall per the strategy ADR `docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md`); opt-in, needs `requirements-ml.txt`, and pays the WangchanBERTa cost on every sentence.
```

- [ ] **Step 7: Commit**

```bash
git add pii_redactor/detectors/tb_detector.py tests/test_ner_engine.py CLAUDE.md
git commit -m "feat(detector): AIGUARD_NER_ENGINE=union runs CRF+WangchanBERTa"
```

---

### Task 3: validate the product union reproduces the ADR recall on gold

**Files:**
- Test: `tests/test_union_gold_validation.py` (new)

**Interfaces:**
- Consumes: `detect_tb`/`detect_all` union mode (Task 2); `benchmark.gold.load_gold`; `benchmark.scorer.score`.

- [ ] **Step 1: Write the validation test** — create `tests/test_union_gold_validation.py`

```python
"""Confirm the product union mode delivers the recall the strategy ADR measured.

The ADR (docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md)
recommended `union` from gold numbers: ADDRESS recall 1.000, NAME 0.643,
OVERALL recall 0.852. This gates that the shipped detect_all + union path
reproduces that recall-first win (floors sit just under the measured values so
the gate is not flaky). Exact per-sample span equality with the benchmark's
union_entities oracle is NOT asserted -- the false-negative scan and dedup
nesting differ slightly between the two paths; recall is what the ADR promised.
"""
from __future__ import annotations

import importlib.util

import pytest

from benchmark.gold import load_gold
from benchmark.scorer import score
from pii_redactor.detectors.aggregate import detect_all


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="requires requirements-ml.txt",
)
def test_product_union_reproduces_adr_recall_on_gold(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    samples = load_gold()
    preds = [
        [(e.span[0], e.span[1], e.data_type) for e in detect_all(s.text)]
        for s in samples
    ]
    rep = score(samples, preds)
    assert rep["by_type"]["ADDRESS"]["recall"] >= 0.99, rep["by_type"]["ADDRESS"]
    assert rep["by_type"]["NAME"]["recall"] >= 0.60, rep["by_type"]["NAME"]
    assert rep["overall"]["recall"] >= 0.83, rep["overall"]
```

- [ ] **Step 2: Run the validation test to verify it passes**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest tests/test_union_gold_validation.py -v`
Expected: PASS (union on gold: ADDRESS 1.000 ≥ 0.99, NAME 0.643 ≥ 0.60, OVERALL 0.852 ≥ 0.83). Long timeout — loads WangchanBERTa.

- [ ] **Step 3: Run the full suite to confirm no regression**

Run: `$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'; .\.venv\Scripts\python.exe -m pytest -q`
Expected: all pass, only the pre-existing optional-dependency skips. Long timeout (600000 ms).

- [ ] **Step 4: Commit**

```bash
git add tests/test_union_gold_validation.py
git commit -m "test(detector): union mode reproduces ADR union recall on gold"
```

---

## Notes

- `detect_tb` is the single chokepoint — once union mode works there, every caller (web `/api/sanitize`, CLI, pre-send leak guard, `detect_all`, pipeline) gets union by setting `AIGUARD_NER_ENGINE=union`, with no change to those files.
- Latency is not measured in code; the ADR records the ~1.3s/sentence WangchanBERTa cost that union pays on every sentence.
- Implementing `union` in the benchmark's own `--engine` option (so future benchmark runs can measure the product path directly) is intentionally out of scope — the validation test covers the consistency check.
