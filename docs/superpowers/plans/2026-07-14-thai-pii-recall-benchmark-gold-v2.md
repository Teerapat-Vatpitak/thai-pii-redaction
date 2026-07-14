# Thai PII Recall Benchmark v2 (gold) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) tracking.

**Goal:** A hand-authored gold corpus of realistic Thai documents (fake PII, inline-labeled) that stresses v1's blind spots, scored with the v1 scorer; plus a context fix for the BANK-vs-PHONE ambiguity.

**Architecture:** `benchmark/gold.py` holds annotated documents (`[[TYPE|value]]`) parsed to exact-span `Sample`s. `runner.run_benchmark(source="gold")` swaps the corpus source; the scorer is reused unchanged. `detect_fp` gains a small context disambiguation so a 10-digit number next to a bank cue is BANK, next to a phone cue is PHONE.

**Tech Stack:** Python 3.13, stdlib only. Reuses `benchmark.scorer`, `benchmark.types`, `pii_redactor.detectors`.

## Global Constraints

- `$env:PYTHONUTF8='1'` before every Python run; use `.\.venv\Scripts\python.exe`.
- No new dependency. Fake PII only (privacy-safe, committable).
- Gold entity-type names match detector `data_type`.
- Gold is diagnostic — no hard recall floors for NAME/ADDRESS.

---

### Task 1: gold parser + round-trip test

**Files:** Create `benchmark/gold.py`; Test `tests/test_benchmark_gold.py`.

**Interfaces:** Produces `GOLD_SLICES: list[str]`, `parse_gold(doc_id, slice, annotated) -> Sample`, `GOLD_DOCS: list[tuple]`, `load_gold() -> list[Sample]`.

- [ ] Write failing test: for a small annotated string, `parse_gold` yields text with markup stripped and a span whose `text[start:end]` equals the labeled value.
- [ ] Run, see fail (no module).
- [ ] Implement `parse_gold` with `re.compile(r"\[\[([A-Z_]+)\|(.*?)\]\]")`, walking matches to build plain text + `GoldSpan`s. `load_gold()` parses all `GOLD_DOCS`.
- [ ] Run, see pass.
- [ ] Commit.

### Task 2: author the gold corpus (~60-80 docs, 4 slices)

**Files:** `benchmark/gold.py` (`GOLD_DOCS`); Test `tests/test_benchmark_gold.py`.

- [ ] Write tests: every parsed sample round-trips (`text[span]==value`); each slice in `GOLD_SLICES` is non-empty; `name_no_cue` docs contain NAME spans with no นาย/นาง/นางสาว immediately before the span; `bank_phone` has both BANK_ACCOUNT and PHONE.
- [ ] Author ~15-20 docs per slice (`name_no_cue`, `address_varied`, `messy`, `bank_phone`) with `[[TYPE|value]]` markup, fake PII.
- [ ] Run tests, see pass (fix docs until green).
- [ ] Commit.

### Task 3: runner + CLI `--source gold`

**Files:** Modify `benchmark/runner.py`, `benchmark/__main__.py`; Test `tests/test_benchmark_gold.py`.

**Interfaces:** `run_benchmark(engine="crf", seed=42, size=200, source="synthetic")`; when `source=="gold"` use `load_gold()`.

- [ ] Write failing test: `run_benchmark(engine="crf", source="gold")` returns a report whose `corpus.samples == len(load_gold())` and includes `by_slice` for all `GOLD_SLICES`.
- [ ] Run, see fail.
- [ ] Add `source` param to `run_benchmark` (branch on it); add `--source` to CLI; put `source` in the report.
- [ ] Run, see pass.
- [ ] Commit.

### Task 4: BANK-vs-PHONE context disambiguation

**Files:** Modify `pii_redactor/detectors/fp_detector.py`; Test `tests/test_benchmark_gold.py`.

**Interfaces:** internal `_disambiguate_bank_phone(text, candidates) -> candidates`, called in `detect_fp` before `_deduplicate`.

- [ ] Write failing tests: `detect_fp("เลขบัญชี 0612345678")` yields a BANK_ACCOUNT covering those digits; `detect_fp("โทร 0612345678")` yields PHONE; a bare `detect_fp("0612345678")` stays PHONE (unchanged default).
- [ ] Run, see the bank-cue case fail (currently PHONE wins).
- [ ] Implement `_disambiguate_bank_phone`: for PHONE+BANK candidates sharing a span, look ~15 chars before; bank cue (`บัญชี|ธนาคาร|เลขที่บัญชี|เลขบัญชี`) drops PHONE, phone cue (`โทร|เบอร์|มือถือ|ติดต่อ`) drops BANK, else unchanged. Call it in `detect_fp`.
- [ ] Run, see pass. Run full suite to confirm no regression (`pytest -q`).
- [ ] Commit.

### Task 5: gold diagnostic tests + run the comparison

**Files:** `tests/test_benchmark_gold.py`.

- [ ] Add: `run_benchmark(source="gold", engine="crf")` gives THAI_ID and EMAIL recall >= 0.9 on gold (clear-format structured stays strong) — a light sanity gate, NOT a NAME/ADDRESS floor. Opt-in `@pytest.mark.skipif(transformers missing)` test that the wangchanberta gold run produces a report.
- [ ] Run `python -m benchmark --source gold --engine crf --json benchmark/reports/gold-crf.json` and `--engine wangchanberta ... gold-wcb.json`; record the per-slice CRF vs WangchanBERTa table in the v2 spec's results section.
- [ ] Commit.

## Notes

- If detection genuinely misses a gold case (e.g. bare name CRF can't tag), that is the POINT — report it, don't weaken the gold. Only structured clear-format types get a sanity floor.
- `detect_tb` engine is process-global; the CRF vs WangchanBERTa gold numbers come from two separate CLI runs (same as v1).
