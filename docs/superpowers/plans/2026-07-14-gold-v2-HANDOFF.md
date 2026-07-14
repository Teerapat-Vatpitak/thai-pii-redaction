# HANDOFF — Thai PII benchmark v2 (gold set) — resume state 2026-07-14

Read this first, then the spec `2026-07-14-thai-pii-recall-benchmark-gold-v2-design.md`
and plan `2026-07-14-thai-pii-recall-benchmark-gold-v2.md` (same folder).

## Where we are

Building v2: a hand-authored Thai PII **gold** corpus that stresses v1's blind
spots (names without title cues, varied addresses, messy text) + a **BANK-vs-PHONE**
disambiguation fix. Executing the plan task-by-task with TDD.

| Task | Status |
|---|---|
| 1. gold parser (`benchmark/gold.py` `parse_gold`/`load_gold`) | DONE, tests green |
| 2. author 64 gold docs (16 per slice) | DONE, corpus validated (all spans round-trip) |
| 3. runner + CLI `--source gold` | DONE, tests green |
| 4. BANK-vs-PHONE fix in `fp_detector.py` | **IN PROGRESS — test written & RED (TDD), fix NOT yet implemented** |
| 5. gold diagnostic tests + run CRF vs WangchanBERTa comparison | NOT STARTED |

Everything except Task 4's fix and Task 5 is done and passing.

## Git state (IMPORTANT)

On branch **`main`** (switched back after PR #26 merged). v2 work is **uncommitted**.
Before committing, **create a branch** (e.g. `feat/gold-benchmark-v2`) then commit in
chunks. Uncommitted files:

- New: `benchmark/gold.py`, `tests/test_benchmark_gold.py`, the two v2 docs above, this handoff.
- Modified: `benchmark/runner.py` (added `source` param), `benchmark/__main__.py` (added `--source`).
- `benchmark/reports/*.json` exist locally but are gitignored — ignore them.

main tip is `7f5a054` (PR #26). `requirements-ml.txt` (torch/transformers) IS installed
in `.venv`, so the WangchanBERTa comparison runs live.

## RESUME HERE — Task 4: implement the BANK/PHONE fix

The failing (intended) test:
`tests/test_benchmark_gold.py::test_bank_cue_makes_10digit_a_bank_account` — a
10-digit number starting 06-09 after "เลขที่บัญชี" is currently labeled PHONE
(mobile pattern wins the dedup tie), should be BANK_ACCOUNT.

**Fix:** add to `pii_redactor/detectors/fp_detector.py` (near the other compiled
regexes and the main detector):

```python
_BANK_CUE_RE = re.compile(r"บัญชี|ธนาคาร|เลขที่บัญชี|เลขบัญชี")
_PHONE_CUE_RE = re.compile(r"โทรศัพท์|โทร|เบอร์|มือถือ|ติดต่อ")


def _disambiguate_bank_phone(text: str, candidates: list[Entity]) -> list[Entity]:
    """A 10-digit number starting 06-09 matches both the mobile PHONE and the
    BANK_ACCOUNT patterns. When PHONE and BANK_ACCOUNT candidates share a span,
    a bank cue in the ~15 chars before it drops the PHONE (keep BANK); a phone
    cue drops the BANK (keep PHONE); no cue -> unchanged (PHONE still wins dedup)."""
    types_by_span: dict[tuple[int, int], set[str]] = {}
    for e in candidates:
        types_by_span.setdefault(e.span, set()).add(e.data_type)
    drop_phone: set[tuple[int, int]] = set()
    drop_bank: set[tuple[int, int]] = set()
    for span, types in types_by_span.items():
        if "PHONE" in types and "BANK_ACCOUNT" in types:
            ctx = text[max(0, span[0] - 15):span[0]]
            if _BANK_CUE_RE.search(ctx):
                drop_phone.add(span)
            elif _PHONE_CUE_RE.search(ctx):
                drop_bank.add(span)
    out = []
    for e in candidates:
        if e.data_type == "PHONE" and e.span in drop_phone:
            continue
        if e.data_type == "BANK_ACCOUNT" and e.span in drop_bank:
            continue
        out.append(e)
    return out
```

Then in `detect_fp`, change the final line from `return _deduplicate(candidates)` to:

```python
    candidates = _disambiguate_bank_phone(text, candidates)
    return _deduplicate(candidates)
```

Note: `_PHONE_CUE_RE` lists `โทรศัพท์` before `โทร` on purpose (longest-first so the
alternation matches the fuller cue; harmless either way since we only test presence).

Verify:
```
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_gold.py -k "cue or defaults" -v
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q   # full suite must stay green
```
Then commit (on the new branch).

## Then Task 5 — diagnostic + comparison

1. Gold sanity tests already written (`test_gold_structured_clearformat_still_strong`,
   `test_wangchanberta_gold_runs`) — confirm green.
2. Run the comparison and record numbers in the v2 spec's (to-be-added) results section:
```
$env:PYTHONUTF8='1'; $env:HF_HUB_DISABLE_PROGRESS_BARS='1'
.\.venv\Scripts\python.exe -m benchmark --source gold --engine crf --json benchmark/reports/gold-crf.json
.\.venv\Scripts\python.exe -m benchmark --source gold --engine wangchanberta --json benchmark/reports/gold-wcb.json
```
   Expect the interesting result: on `name_no_cue` and `address_varied` slices, CRF
   recall should drop (no title cues for name_context to exploit) and WangchanBERTa
   should show a real gap — the external-validity payoff v1 couldn't demonstrate.
3. Append a "ผลรัน v2 (gold)" section to the v2 spec with the per-slice CRF vs
   WangchanBERTa table, mirroring v1's results section.
4. Commit; branch; push; open PR into main (only if the user asks — they drive merges).

## Gotchas

- `$env:PYTHONUTF8='1'` before every Python run (Windows cp1252 breaks Thai).
- `detect_tb` NER engine is a process-global singleton; `run_benchmark` resets it, so
  CRF and WangchanBERTa can both run in one process, but the source-of-truth comparison
  numbers come from two separate CLI runs.
- Gold is a DIAGNOSTIC — do NOT add hard NAME/ADDRESS recall floors; low recall there is
  the finding, not a bug. Only clear-format structured types get a sanity floor.
- The user reviews/merges PRs themselves; commit only when asked, branch off main first.
