# WangchanBERTa NER Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `pii_redactor/detectors/tb_detector.py` switch its NER engine from
the default CRF (`thainer`) to a WangchanBERTa-based transformer engine
(`thainer-v2`), selected once per process via an `AIGUARD_NER_ENGINE`
environment variable, failing loudly (not silently falling back) if the
configured engine's dependency isn't installed.

**Architecture:** A curated `_ENGINE_CONFIG` dict in `tb_detector.py` maps two
supported names (`"thainer"`, `"wangchanberta"`) to the underlying
`pythainlp.tag.NER(engine=...)` string and an optional required package name.
`_get_ner()` (the existing lazy singleton) reads the env var once, validates
against the allow-list, checks the required package is importable, and raises
a clear error otherwise. Nothing downstream of `_get_ner()` changes.

**Tech Stack:** PyThaiNLP 5.3.4 (`pythainlp.tag.NER`, already a core dep),
`transformers` (already in `requirements-ml.txt`, no new dependency file).

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-03-wangchanberta-ner-engine-design.md`
- Default engine stays `"thainer"` (CRF) — no behavior change for anyone who
  doesn't set `AIGUARD_NER_ENGINE`.
- Only two engine names are ever exposed: `"thainer"` and `"wangchanberta"`.
  Do not add `thai-nner` or `tltk` — their `.tag()` output shape has not been
  verified against `_bio_to_spans()`.
- No per-request/per-API engine selection. No CLI flag. Env var only.
- No silent fallback to `"thainer"` when the configured engine's dependency
  is missing — raise `NEREngineUnavailableError`.
- No FastAPI startup hook — the check happens lazily inside `_get_ner()` on
  first `detect_tb()` call.
- `python -m pytest` (full suite) must pass both with and without
  `requirements-ml.txt` installed (Tier 2 tests skip cleanly without it).

---

### Task 1: Engine registry + dispatch logic in `tb_detector.py`

**Files:**
- Modify: `pii_redactor/detectors/tb_detector.py` (lines 1-39, the imports and
  `_get_ner()` block)
- Test: `tests/test_ner_engine.py` (new file)

**Interfaces:**
- Produces: `pii_redactor.detectors.tb_detector.NEREngineUnavailableError`
  (new exception class, subclasses `RuntimeError`), `pii_redactor.detectors.
  tb_detector._get_ner() -> NER` (existing function, same signature, new
  internal behavior), `pii_redactor.detectors.tb_detector._ENGINE_CONFIG`
  (module-level dict, used only by tests).

Current relevant content of `tb_detector.py` (lines 1-39) — read this first
to confirm nothing has drifted before editing:

```python
"""Text-based (TB) PII detector using PyThaiNLP NER (thainer CRF)."""
from __future__ import annotations

import uuid

from pythainlp import sent_tokenize
from pythainlp.tag import NER

from pii_redactor.models import Entity

# ---------------------------------------------------------------------------
# Label mapping: actual thainer labels -> PDPA data_type (None = skip)
# ---------------------------------------------------------------------------

LABEL_MAP: dict[str, str | None] = {
    "PERSON": "NAME",
    "ORGANIZATION": None,   # Not PII; skip
    "LOCATION": "ADDRESS",
    "DATE": "DATE_OF_BIRTH",
    "TIME": None,
    "MONEY": None,
    "PERCENT": None,
    "FACILITY": None,
    "PRODUCT": None,
    # Aliases from brief (kept for safety)
    "ORG": None,
    "GPE": "ADDRESS",
    "LOC": "ADDRESS",
}

# Lazy-initialized NER instance (first import triggers model load)
_ner: NER | None = None


def _get_ner() -> NER:
    global _ner
    if _ner is None:
        _ner = NER(engine="thainer")
    return _ner
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ner_engine.py`:

```python
"""Engine selection for tb_detector's NER (AIGUARD_NER_ENGINE env var)."""
import builtins

import pytest

from pii_redactor.detectors import tb_detector


class _FakeNER:
    def __init__(self, engine):
        self.engine = engine


def _reset(monkeypatch):
    monkeypatch.setattr(tb_detector, "_ner", None)


# --- Tier 1: always runs, no transformers required -------------------------


def test_default_engine_is_thainer_when_env_unset(monkeypatch):
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    _reset(monkeypatch)
    monkeypatch.setattr(tb_detector, "NER", _FakeNER)
    ner = tb_detector._get_ner()
    assert ner.engine == "thainer"


def test_unknown_engine_raises_value_error(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "bogus")
    _reset(monkeypatch)
    with pytest.raises(ValueError, match="bogus"):
        tb_detector._get_ner()


def test_wangchanberta_without_transformers_raises(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "wangchanberta")
    _reset(monkeypatch)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("mocked missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(tb_detector.NEREngineUnavailableError, match="requirements-ml.txt"):
        tb_detector._get_ner()


# --- Tier 2: requires transformers installed --------------------------------


def test_wangchanberta_maps_to_thainer_v2_engine(monkeypatch):
    pytest.importorskip("transformers")
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "wangchanberta")
    _reset(monkeypatch)
    monkeypatch.setattr(tb_detector, "NER", _FakeNER)
    ner = tb_detector._get_ner()
    assert ner.engine == "thainer-v2"


def test_wangchanberta_real_engine_detects_person(monkeypatch):
    pytest.importorskip("transformers")
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "wangchanberta")
    _reset(monkeypatch)
    ner = tb_detector._get_ner()
    tagged = ner.tag("นายสมชาย ใจดี อาศัยอยู่ที่กรุงเทพมหานคร")
    labels = {tag.split("-", 1)[1] for _, tag in tagged if tag != "O"}
    assert "PERSON" in labels
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_ner_engine.py -v`
Expected: `ImportError`/`AttributeError` — `NEREngineUnavailableError` doesn't
exist yet, `_get_ner()` doesn't read the env var yet. All 5 tests fail or error.

- [ ] **Step 3: Implement the engine registry and dispatch logic**

Replace the header block of `pii_redactor/detectors/tb_detector.py` (from
`"""Text-based..."""` through the `_get_ner()` function, i.e. lines 1-39)
with:

```python
"""Text-based (TB) PII detector using PyThaiNLP NER (thainer CRF by default;
WangchanBERTa opt-in via AIGUARD_NER_ENGINE)."""
from __future__ import annotations

import os
import uuid

from pythainlp import sent_tokenize
from pythainlp.tag import NER

from pii_redactor.models import Entity

# ---------------------------------------------------------------------------
# Label mapping: actual thainer labels -> PDPA data_type (None = skip)
# ---------------------------------------------------------------------------

LABEL_MAP: dict[str, str | None] = {
    "PERSON": "NAME",
    "ORGANIZATION": None,   # Not PII; skip
    "LOCATION": "ADDRESS",
    "DATE": "DATE_OF_BIRTH",
    "TIME": None,
    "MONEY": None,
    "PERCENT": None,
    "FACILITY": None,
    "PRODUCT": None,
    # Aliases from brief (kept for safety)
    "ORG": None,
    "GPE": "ADDRESS",
    "LOC": "ADDRESS",
}


class NEREngineUnavailableError(RuntimeError):
    """AIGUARD_NER_ENGINE is set to an engine whose dependency isn't installed."""


# Curated allow-list: only engines verified to emit the same (word, "B-"/"I-"/
# "O"-tag) shape that _bio_to_spans() below decodes. Do NOT add thai-nner or
# tltk here without first verifying their .tag() output shape -- they are
# known to differ (nested entities / different tuple layout).
_ENGINE_CONFIG: dict[str, dict[str, str | None]] = {
    "thainer": {"ner_engine": "thainer", "requires": None},
    "wangchanberta": {"ner_engine": "thainer-v2", "requires": "transformers"},
}

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

Leave everything below `_get_ner()` (`_bio_to_spans`, `_deduplicate`,
`detect_tb`) untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_ner_engine.py -v`
Expected: the 3 Tier-1 tests PASS; the 2 Tier-2 tests PASS if
`requirements-ml.txt` is installed in this venv (it is, per this project's
current state), or SKIP cleanly if not.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q`
Expected: all previously-passing tests still pass (254 before this task);
count increases by the new tests in `test_ner_engine.py`.

- [ ] **Step 6: Commit**

```bash
git add pii_redactor/detectors/tb_detector.py tests/test_ner_engine.py
git commit -m "add opt-in WangchanBERTa NER engine via AIGUARD_NER_ENGINE"
```

---

### Task 2: Manual verification of both failure/success paths

**Files:** none (verification only, no code changes)

**Interfaces:**
- Consumes: `tb_detector._get_ner()`, `tb_detector.NEREngineUnavailableError`
  from Task 1.

- [ ] **Step 1: Verify default behavior is unchanged**

Run:
```
PYTHONUTF8=1 .venv/Scripts/python.exe -c "from pii_redactor.detectors.tb_detector import detect_tb; print(detect_tb('นายสมชาย ใจดี'))"
```
Expected: runs instantly (CRF engine), prints a list with at least one `NAME`
entity, no errors.

- [ ] **Step 2: Verify wangchanberta engine detects a name**

Run (PowerShell):
```
$env:AIGUARD_NER_ENGINE = "wangchanberta"; PYTHONUTF8=1 .venv/Scripts/python.exe -c "from pii_redactor.detectors.tb_detector import detect_tb; r = detect_tb('นายสมชาย ใจดี อาศัยอยู่ที่กรุงเทพมหานคร'); print(r)"
```
Expected: takes several seconds (model load + inference), prints at least one
`NAME` and one `ADDRESS` entity. Unset `$env:AIGUARD_NER_ENGINE` afterward
(`Remove-Item Env:\AIGUARD_NER_ENGINE`) so it doesn't leak into later steps.

- [ ] **Step 3: Verify unknown engine name fails loudly**

Run:
```
$env:AIGUARD_NER_ENGINE = "bogus"; PYTHONUTF8=1 .venv/Scripts/python.exe -c "from pii_redactor.detectors.tb_detector import detect_tb; detect_tb('test')"
```
Expected: `ValueError: Unknown AIGUARD_NER_ENGINE='bogus'; supported: ['thainer', 'wangchanberta']`.
Then `Remove-Item Env:\AIGUARD_NER_ENGINE`.

- [ ] **Step 4: Verify missing-dependency error message (only meaningful if `transformers` can be temporarily made unavailable; otherwise rely on the Tier-1 mocked test from Task 1 as sufficient coverage — do not uninstall `transformers` from the working venv to test this, since it's also required by the existing MiniLM detector)**

Skip actual uninstall/reinstall churn. The mocked Tier-1 test
(`test_wangchanberta_without_transformers_raises`) already exercises this
exact path deterministically; re-verifying manually would require breaking
a working venv for no additional signal.

---

### Task 3: Update docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/submission/README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `CLAUDE.md`'s TB detector description**

Find this line (in the Step 2 - PII Detection section):
```
  - PyThaiNLP thainer-CRF (`NER(engine="thainer")`) — the model that actually runs. A WangchanBERTa engine is **roadmap**, not implemented.
```
Replace with:
```
  - PyThaiNLP thainer-CRF (`NER(engine="thainer")`) — the default, fast, fully offline. An opt-in WangchanBERTa engine (`AIGUARD_NER_ENGINE=wangchanberta`, maps to `NER(engine="thainer-v2")`) is available for higher recall at a real cost: ~1.3s/sentence on CPU vs near-instant for CRF. Selected once per process via env var, not per-request; fails loudly (`NEREngineUnavailableError`) rather than silently falling back if `transformers` isn't installed.
```

- [ ] **Step 2: Update `CLAUDE.md`'s Roadmap line**

Find:
```
Roadmap (not implemented): WangchanBERTa NER engine, Presidio bridge.
```
Replace with:
```
Roadmap (not implemented): Presidio bridge.
```

- [ ] **Step 3: Update `docs/submission/README.md`'s claims lists**

Find:
```
เคลมเฉพาะที่ระบบทำได้จริง: regex+checksum, thainer-CRF NER + กฎบริบท, token/surrogate, vault ในเครื่อง,
true PDF redaction (bbox), OCR ภาพสแกนด้วย PaddleOCR ต่อหน้า (พร้อม retry + human-review flag; ต้องรันจาก source พร้อม `requirements-ocr.txt` — ไม่ได้บันเดิลใน .exe), ธง ม.26, re-id risk, extension + .exe
**ของที่เป็น roadmap (ห้ามเคลมว่าทำแล้ว):** WangchanBERTa, Presidio bridge, การวัด F1 ทางการ (ไม่มีตัวเลข accuracy ของ OCR ที่ผ่านการวัดจริง — อย่าเคลมตัวเลข)
```
Replace with:
```
เคลมเฉพาะที่ระบบทำได้จริง: regex+checksum, thainer-CRF NER + กฎบริบท (default) หรือ WangchanBERTa engine ทางเลือก (เปิดผ่าน `AIGUARD_NER_ENGINE=wangchanberta`, แม่นกว่าแต่ช้ากว่า CRF ~1.3 วินาที/ประโยคบน CPU), token/surrogate, vault ในเครื่อง,
true PDF redaction (bbox), OCR ภาพสแกนด้วย PaddleOCR ต่อหน้า (พร้อม retry + human-review flag; ต้องรันจาก source พร้อม `requirements-ocr.txt` — ไม่ได้บันเดิลใน .exe), ธง ม.26, re-id risk, extension + .exe
**ของที่เป็น roadmap (ห้ามเคลมว่าทำแล้ว):** Presidio bridge, การวัด F1 ทางการ (ไม่มีตัวเลข accuracy ที่ผ่านการวัดจริงทั้ง OCR และ WangchanBERTa — อย่าเคลมตัวเลข)
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/submission/README.md
git commit -m "docs: WangchanBERTa NER engine is implemented (opt-in), out of roadmap"
```

---

## Self-Review Notes

- **Spec coverage:** all 5 numbered decisions in the spec (opt-in default,
  server-level env var, curated allow-list, fail-loud, lazy-raise) are
  implemented in Task 1's `_get_ner()`. Testing section of the spec (Tier 1 +
  Tier 2) is covered by Task 1's test file. Docs section covered by Task 3.
  Out-of-scope items (Presidio, per-request selection, ensemble, GPU) are not
  touched anywhere in this plan — correct.
- **Placeholder scan:** no TBD/TODO; every step has complete, literal code.
- **Type consistency:** `NEREngineUnavailableError` name matches between
  Task 1's implementation and its test; `_ENGINE_CONFIG`/`_get_ner`/`_ner`
  names match the existing module's current names (verified against the
  actual file content quoted at the top of Task 1) — no renames introduced.
