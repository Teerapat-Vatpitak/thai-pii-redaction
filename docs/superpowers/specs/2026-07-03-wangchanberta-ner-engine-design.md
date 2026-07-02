# WangchanBERTa NER engine (opt-in, server-level) — design

## Context

`pii_redactor/detectors/tb_detector.py` uses PyThaiNLP's `NER(engine="thainer")`
(CRF-based) for text-based PII detection (names/addresses/dates). CLAUDE.md and
the contest submission docs list "WangchanBERTa NER engine" as roadmap/not
implemented. This is stale: PyThaiNLP 5.3.4 (already installed) bundles a
WangchanBERTa-based engine (`pythainlp.wangchanberta.NamedEntityRecognition`,
model `thainer-corpus-v2-base-model`) via `NER(engine="thainer-v2")`, requiring
only `transformers`/`torch` — already present via `requirements-ml.txt` (used
today by the MiniLM Section-26 semantic detector). Implementing this is a
config/wiring change, not a new model build.

Verified directly (not assumed):
- `NER(engine="thainer-v2").tag(text)` returns the same
  `list[tuple[word, "B-"/"I-"/"O"-tag]]` shape that `_bio_to_spans()` already
  decodes — no decoder changes needed.
- Label scheme matches for the types we care about: `PERSON`, `LOCATION`
  observed identical to the CRF engine's labels. (`PHONE` also appears as a
  label from this engine; harmless — `LABEL_MAP.get()` already skips unmapped
  labels, and `fp_detector.py`'s regex+checksum already covers phone numbers
  more reliably.)
- Load time ~8s (first run, includes tokenizer/config fetch); per-call
  `tag()` inference ~1.3s/sentence on CPU — a document with N sentences costs
  roughly `1.3 * N` seconds serially, vs near-instant for the CRF engine.

## Decisions (from brainstorming Q&A)

1. **Opt-in, not a replacement.** `thainer` (CRF) stays the default — fast,
   fully offline, no extra dependency. WangchanBERTa is an alternative engine
   an operator can switch to, mirroring how the MiniLM semantic detector is
   optional via `requirements-ml.txt`.
2. **Server-level config, not per-request.** Selected once via an environment
   variable, fixed for the lifetime of the process. No API parameter, no CLI
   flag per invocation — avoids loading two heavy models into memory to
   support per-request switching for a feature nobody asked to toggle live.
3. **Curated allow-list, not a raw pass-through.** Only `pythainlp` engines
   verified to emit the same `(word, tag)` shape are exposed. `thai-nner`
   (nested-entity output) and `tltk` are NOT exposed this way — their output
   shape hasn't been verified against `_bio_to_spans()` and likely differs.
4. **Fail loud, not silent fallback.** If the configured engine needs a
   package that isn't installed, raise a clear, actionable error rather than
   silently using the CRF engine. Unlike the MiniLM detector (a supplementary
   flag-only feature that's safe to no-op), the NER engine choice directly
   controls primary PII detection coverage — silently downgrading it could
   mask a real misconfiguration.
5. **Raise on first use, not an eager startup hook.** The check runs inside
   the existing lazy singleton (`_get_ner()`), on the first `detect_tb()`
   call. An eager FastAPI startup hook was considered and rejected: it would
   force every server boot to load a model even for requests that never call
   `detect_tb()`. Lazy-raise still satisfies "not silent" — the first real
   detection call fails clearly and immediately if misconfigured, rather than
   ever falling back unnoticed.

## Design

### `tb_detector.py` changes

```python
import os

class NEREngineUnavailableError(RuntimeError):
    """Configured AIGUARD_NER_ENGINE needs a package that isn't installed."""

_ENGINE_CONFIG = {
    "thainer": {"ner_engine": "thainer", "requires": None},
    "wangchanberta": {"ner_engine": "thainer-v2", "requires": "transformers"},
}

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
        if config["requires"] is not None:
            try:
                __import__(config["requires"])
            except ImportError:
                raise NEREngineUnavailableError(
                    f"AIGUARD_NER_ENGINE={name!r} requires {config['requires']!r}. "
                    f"Run: pip install -r requirements-ml.txt"
                ) from None
        _ner = NER(engine=config["ner_engine"])
    return _ner
```

Everything downstream of `_get_ner()` (`detect_tb()`, `_bio_to_spans()`, the
sliding window, the `name_context.py` recall booster, dedup) is unchanged —
the booster runs regardless of which NER engine is active, since it catches a
different failure mode (title/self-intro cues) than either NER model.

No changes to `LABEL_MAP` — `PERSON`/`LOCATION`/`DATE` already map correctly
for both engines; `PHONE` (wangchanberta-only label) is already silently
skipped like any other unmapped label.

### Call sites

None of `pipeline.py`, `app/server.py`, `ai_guard.py` need changes — they all
call `detect_tb(text)` today with no engine parameter, and will keep working
identically; the engine is selected purely by the `AIGUARD_NER_ENGINE`
environment variable at process start.

### Testing

New `tests/test_ner_engine.py`:
- Tier 1 (always runs, monkeypatched): unknown engine name raises `ValueError`
  listing supported names; missing `transformers` for `"wangchanberta"` raises
  `NEREngineUnavailableError` with the install hint; default (`"thainer"`, or
  env var unset) never requires `transformers`.
- Tier 2 (`pytest.importorskip("transformers")`, mirrors
  `test_step13_sensitive.py`): real `NER(engine="thainer-v2")` on a short Thai
  sentence, asserting a `PERSON` entity is recognized — proves the real
  integration works end-to-end, not just the dispatch logic.

Existing `tests/test_step2_detection.py`'s `detect_tb` tests are unaffected
(they exercise the default `thainer` engine, unchanged).

### Docs

- `CLAUDE.md`: remove WangchanBERTa from `Roadmap (not implemented): ...`;
  document `AIGUARD_NER_ENGINE` alongside the TB detector description and in
  Environment Setup; note the latency tradeoff explicitly so nobody sets it
  in a latency-sensitive path without knowing the cost.
- `docs/submission/README.md`: move WangchanBERTa from the forbidden-claims
  list to the allowed-claims list, phrased narrowly ("WangchanBERTa engine
  ทางเลือก เปิดผ่าน env var, แม่นกว่าแต่ช้ากว่า CRF ~1.3 วิ/ประโยคบน CPU" — no
  accuracy/F1 number, since none is benchmarked).

## Out of scope (explicitly)

- Presidio bridge — separate feature, separate spec (per user's decomposition
  choice), not touched here.
- Per-request engine selection (API param / CLI flag) — rejected in Q&A.
- Ensemble mode (running both engines and merging) — rejected in Q&A in favor
  of a simple opt-in switch.
- GPU acceleration / batching to reduce the ~1.3s/sentence cost — not raised
  as a requirement; documented as a known tradeoff instead.

## Verification plan

1. `pytest tests/test_ner_engine.py -v` — Tier 1 passes without
   `requirements-ml.txt`; Tier 2 skips cleanly without it, passes with it.
2. Full suite `pytest -q` — no regressions.
3. Manual: `AIGUARD_NER_ENGINE=wangchanberta` + a real Thai sentence with a
   name through `ai_guard.py report` or `/api/analyze`, confirm the name is
   detected and the process doesn't silently fall back to CRF results.
4. Manual: `AIGUARD_NER_ENGINE=bogus` and `AIGUARD_NER_ENGINE=wangchanberta`
   without `requirements-ml.txt` installed, confirm both fail loudly with the
   expected error messages.
