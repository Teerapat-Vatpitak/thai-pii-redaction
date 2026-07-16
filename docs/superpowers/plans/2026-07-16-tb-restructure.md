# TB Restructure + Honest Type Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ~7x-retag sliding NER window with stride chunks (~1.2x) and make detector type labels honest (DATE/LOCATION/ORGANIZATION/ID_NUMBER with cue-based upgrades) without unmasking anything that is masked today.

**Architecture:** Two independent halves in `pii_redactor/detectors/`: (1) semantics — new `LABEL_MAP` targets + cue-window upgrades (same mechanism as `_disambiguate_bank_phone`) in both `tb_detector.py` and `fp_detector.py`, with new generator branches + token labels; (2) performance — `_ner_candidates` rewritten to tag consecutive-sentence chunks (core ≤500 chars, 1-sentence margins) sliced from the ORIGINAL text (not sentence joins) so offsets stay exact. Benchmark floors are the regression net. Spec: `docs/superpowers/specs/2026-07-16-tb-restructure-design.md`.

**Tech Stack:** Python 3.13, PyThaiNLP (thainer CRF / thainer-v2), pytest. No new dependencies.

## Global Constraints

- Run every Python command as PowerShell `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ...` or bash `PYTHONUTF8=1 ./.venv/Scripts/python.exe ...` from repo root `C:\Users\teera\dev\thai-pii-redaction`.
- **Commit messages MUST NOT contain any `Co-Authored-By: Claude ...` trailer.**
- **"Mask เท่าเดิม label ซื่อสัตย์"**: nothing that is masked today may become unmasked. Every regex keeps matching the same strings; only `data_type` labels change.
- Benchmark floors are NEVER lowered to pass. A floor row whose TYPE legitimately migrates (e.g. a `DATE_OF_BIRTH` floor for cue-less dates) may be RELABELED to the new type, threshold unchanged, with justification in the commit message.
- Do not modify: `CLAUDE.md`, `tests/test_step11_api.py`, `tests/test_api_hardening.py`.
- Work on branch `feat/tb-restructure` (exists; contains the spec commit).
- Existing tests that assert the OLD labels (e.g. a bare date → `DATE_OF_BIRTH`) are expected casualties of the semantic change: update the assertion to the new label and say so in the commit message. Frozen files above are the exception — nothing in them asserts TB labels.

---

### Task 1: New-type plumbing (token labels + generators)

**Files:**
- Modify: `pii_redactor/anonymizer/token_generator.py` (TOKEN_LABEL dict)
- Modify: `pii_redactor/anonymizer/tb_generator.py`
- Modify: `pii_redactor/anonymizer/fp_generator.py:129-152` (dispatch)
- Test: `tests/test_step3_pseudonymize.py`

**Interfaces:**
- Consumes: existing `_seeded_rng(salt, original, attempt)`, `MALE_NAMES`/`DISTRICTS` pools, `_gen_date(rng, original)`.
- Produces: `TOKEN_LABEL` gains exactly 4 keys: `"LOCATION": "สถานที่"`, `"DATE": "วันที่"`, `"ORGANIZATION": "องค์กร"`, `"ID_NUMBER": "รหัสอ้างอิง"` (total 17). `generate_tb` handles `LOCATION` / `ORGANIZATION` / `DATE`; `generate_fp` handles `DATE` and `ID_NUMBER`. Detector tasks (2, 3) emit these data_types.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_step3_pseudonymize.py`:

```python
def test_generate_tb_new_types():
    loc = generate_tb("LOCATION", "ไปเที่ยว ___", salt=SALT, original="เชียงใหม่")
    assert loc and not loc[0].isdigit()          # a place name, no house number
    org = generate_tb("ORGANIZATION", "ทำงานที่ ___", salt=SALT, original="ธนาคารกสิกรไทย")
    assert org and "[REDACTED" not in org
    date = generate_tb("DATE", "ประชุมวันที่ ___", salt=SALT, original="12 มกราคม 2560")
    assert "/" in date and "[REDACTED" not in date


def test_generate_fp_new_types():
    idnum = generate_fp("ID_NUMBER", "1234567890", salt=SALT)
    assert len(idnum) == 10 and idnum.isdigit()
    date = generate_fp("DATE", "12/05/2560", salt=SALT)
    assert "/" in date or "-" in date
```

Also UPDATE the existing `test_token_label_map_matches_v2_contract` in the same file: change `assert len(TOKEN_LABEL) == 13` to `== 17` and add `assert TOKEN_LABEL["ORGANIZATION"] == "องค์กร"` and `assert TOKEN_LABEL["ID_NUMBER"] == "รหัสอ้างอิง"`.

- [ ] **Step 2: Run to verify RED**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_step3_pseudonymize.py -q -k "new_types or token_label"`
Expected: 3 FAIL (`[REDACTED_LOCATION]` from generate_tb fallback, KeyError-free but wrong len for the label test, ID_NUMBER falls into `_gen_generic` char-class path which for all-digits actually returns digits — check: `_gen_generic` preserves char classes, so digits stay digits and that assert may PASS; the label-map and tb asserts still fail).

- [ ] **Step 3: Implement**

`token_generator.py` — add to `TOKEN_LABEL` after `"IBAN": "ไอแบน"`:

```python
    "LOCATION": "สถานที่", "DATE": "วันที่",
    "ORGANIZATION": "องค์กร", "ID_NUMBER": "รหัสอ้างอิง",
```

`tb_generator.py` — add pool after `DISTRICTS`:

```python
ORGANIZATIONS = [
    "บริษัท เจริญวัฒนาการค้า จำกัด", "บริษัท สินทรัพย์รุ่งเรือง จำกัด",
    "บริษัท พัฒนกิจไทย จำกัด (มหาชน)", "ห้างหุ้นส่วนจำกัด ทองดีพาณิชย์",
    "บริษัท เมืองทองอุตสาหกรรม จำกัด", "บริษัท ศรีสยามเทรดดิ้ง จำกัด",
    "บริษัท ก้าวหน้าเอ็นจิเนียริ่ง จำกัด", "บริษัท ไทยสมบูรณ์กรุ๊ป จำกัด",
    "บริษัท แสงทองพลาสติก จำกัด", "บริษัท นครหลวงโลจิสติกส์ จำกัด",
    "บริษัท บ้านสวนอาหาร จำกัด", "บริษัท คลังสินค้าไทย จำกัด",
    "บริษัท อรุณรุ่งการพิมพ์ จำกัด", "บริษัท วารีเทคโนโลยี จำกัด",
    "บริษัท ปัญญาซอฟต์แวร์ จำกัด",
]
```

and in `generate_tb`, add branches BEFORE the final `else` (keep `[REDACTED_...]` as the unknown-type fallback):

```python
    elif data_type == "LOCATION":
        return rng.choice(DISTRICTS)

    elif data_type == "ORGANIZATION":
        return rng.choice(ORGANIZATIONS)

    elif data_type == "DATE":
        # generic date, same shape as DATE_OF_BIRTH but recent-past years
        day = rng.randint(1, 28)
        month = rng.randint(1, 12)
        year = rng.randint(2560, 2568)
        return f"{day:02d}/{month:02d}/{year}"
```

`fp_generator.py` — in `generate_fp`'s dispatch, add before the final `else` (ID_NUMBER mirrors the STUDENT_ID branch — digits, same length as the original):

```python
    elif data_type == "DATE":
        return _gen_date(rng, original)
    elif data_type == "ID_NUMBER":
        return "".join(str(rng.randint(0, 9)) for _ in range(len(original)))
```

- [ ] **Step 4: Run to verify GREEN**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_step3_pseudonymize.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/anonymizer/token_generator.py pii_redactor/anonymizer/tb_generator.py pii_redactor/anonymizer/fp_generator.py tests/test_step3_pseudonymize.py
git commit -m "feat(anonymizer): generators + token labels for LOCATION/DATE/ORGANIZATION/ID_NUMBER"
```

---

### Task 2: fp_detector honest labels (DATE, ID_NUMBER, cue-gated STUDENT_ID/PASSPORT)

**Files:**
- Modify: `pii_redactor/detectors/fp_detector.py` (cue regexes near line 213; emission blocks 7/9/10 at lines 279-313)
- Modify: `pii_redactor/detectors/fn_scanner.py` (loose date pattern label)
- Test: `tests/test_step2_detection.py`

**Interfaces:**
- Consumes: `_CUE_WINDOW = 30`, `_make_entity(data_type, m, text, score)`, existing regexes (UNCHANGED — matching set must not shrink).
- Produces: helper `_cue_before(cue_re: re.Pattern, text: str, start: int) -> bool` (True when the cue appears in the `_CUE_WINDOW` chars before `start`); cue regexes `_BIRTH_CUE_RE = re.compile(r"เกิด")`, `_STUDENT_CUE_RE = re.compile(r"รหัสนักศึกษา|รหัสนิสิต|นักศึกษา|นิสิต|student", re.IGNORECASE)`, `_PASSPORT_CUE_RE = re.compile(r"พาสปอร์ต|หนังสือเดินทาง|passport", re.IGNORECASE)`. Label behavior used by Tasks 5-6: bare date → `DATE`; date with เกิด cue → `DATE_OF_BIRTH`; bare 8-12 digits → `ID_NUMBER`; with student cue → `STUDENT_ID`; `[A-Z]{2}\d{7}` → `PASSPORT` always; general `[A-Z]{1,2}\d{6,9}` → `PASSPORT` only with passport cue, else `ID_NUMBER`. Scores: DATE/DATE_OF_BIRTH 1.0 (unchanged), ID_NUMBER 0.8, STUDENT_ID 0.8 (unchanged), cue-gated general passport 1.0 / ID_NUMBER fallback 0.8.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_step2_detection.py`:

```python
def test_fp_bare_date_is_generic_date():
    ents = detect_fp("นัดประชุมวันที่ 12/05/2569 ที่สำนักงานใหญ่")
    dates = [e for e in ents if e.data_type in ("DATE", "DATE_OF_BIRTH")]
    assert dates and all(e.data_type == "DATE" for e in dates)


def test_fp_birth_cue_date_is_dob():
    ents = detect_fp("ผมเกิดวันที่ 12/05/2530 ครับ")
    assert any(e.data_type == "DATE_OF_BIRTH" for e in ents)


def test_fp_bare_long_number_is_id_number():
    # 8 digits ON PURPOSE: a 10-digit value is claimed by the BANK_ACCOUNT
    # pattern (\d{7}\d{3}) at score 1.0 and would never reach ID_NUMBER.
    ents = detect_fp("เลขที่ใบแจ้งหนี้ 12345678 ออกเมื่อวานนี้")
    assert any(e.data_type == "ID_NUMBER" and e.original_text == "12345678" for e in ents)
    assert not any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_student_cue_keeps_student_id():
    ents = detect_fp("รหัสนักศึกษา 6412345678 คณะวิศวกรรมศาสตร์")
    assert any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_general_passport_without_cue_is_id_number():
    ents = detect_fp("เลขที่ใบสั่งซื้อ P1234567 จัดส่งแล้ว")
    assert any(e.data_type == "ID_NUMBER" and e.original_text == "P1234567" for e in ents)
    assert not any(e.data_type == "PASSPORT" for e in ents)


def test_fp_passport_cue_or_thai_format_stays_passport():
    ents = detect_fp("หนังสือเดินทางเลขที่ P1234567")
    assert any(e.data_type == "PASSPORT" for e in ents)
    ents2 = detect_fp("เอกสารแนบ AB1234567 ตามระเบียบ")
    assert any(e.data_type == "PASSPORT" for e in ents2)  # TH format needs no cue


def test_fp_nothing_unmasked_by_relabel():
    """Every string that was detected before must still be detected (label may differ)."""
    text = "12/05/2569 และ 1234567890 และ P1234567"
    covered = sorted(e.original_text for e in detect_fp(text))
    assert covered == ["12/05/2569", "1234567890", "P1234567"]
```

- [ ] **Step 2: Run to verify RED**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_step2_detection.py -q -k "bare_date or birth_cue or id_number or student_cue or general_passport or passport_cue or unmasked"`
Expected: FAIL on bare_date (gets DATE_OF_BIRTH), id_number (gets STUDENT_ID), general_passport (gets PASSPORT); others may already pass.

- [ ] **Step 3: Implement** in `fp_detector.py`:

Add after `_PHONE_CUE_RE` (line ~214):

```python
# Honest-label cues (Horizon-2 #10). "เกิด" as substring covers วันเกิด /
# เกิดวันที่ / เกิดเมื่อ. Student/passport cues gate the wide catch-alls so a
# business PO/invoice number stops masquerading as a passport or student id --
# it is still masked, as the generic ID_NUMBER.
_BIRTH_CUE_RE = re.compile(r"เกิด")
_STUDENT_CUE_RE = re.compile(r"รหัสนักศึกษา|รหัสนิสิต|นักศึกษา|นิสิต|student", re.IGNORECASE)
_PASSPORT_CUE_RE = re.compile(r"พาสปอร์ต|หนังสือเดินทาง|passport", re.IGNORECASE)


def _cue_before(cue_re: re.Pattern, text: str, start: int) -> bool:
    return bool(cue_re.search(text[max(0, start - _CUE_WINDOW):start]))
```

Replace block 7 (DATE_OF_BIRTH, lines ~279-290): keep the loop identical but choose the label:

```python
    # 7. DATE (generic) / DATE_OF_BIRTH (only with a birth cue nearby)
    for m in _RE_DATE.finditer(text):
        raw = m.group(1)
        parts = re.split(r"[/\-]", raw)
        if len(parts) == 3:
            try:
                day = int(parts[0])
                month = int(parts[1])
                if _date_sanity(day, month):
                    dtype = (
                        "DATE_OF_BIRTH"
                        if _cue_before(_BIRTH_CUE_RE, text, m.start(1))
                        else "DATE"
                    )
                    candidates.append(_make_entity(dtype, m, text, score=1.0))
            except ValueError:
                pass
```

Replace block 9 (PASSPORT):

```python
    # 9. PASSPORT — Thai format always; the general catch-all only with a cue,
    # otherwise it is a generic reference number (still masked as ID_NUMBER).
    for m in _RE_PASSPORT_TH.finditer(text):
        candidates.append(_make_entity("PASSPORT", m, text, score=1.0))
    for m in _RE_PASSPORT.finditer(text):
        if _cue_before(_PASSPORT_CUE_RE, text, m.start(1)):
            candidates.append(_make_entity("PASSPORT", m, text, score=1.0))
        else:
            candidates.append(_make_entity("ID_NUMBER", m, text, score=0.8))
```

Replace block 10 (STUDENT_ID):

```python
    # 10. STUDENT_ID only with a student cue; bare 8-12 digit runs are masked
    # as the honest generic ID_NUMBER (low priority; dedup handles overlap).
    for m in _RE_STUDENT_ID.finditer(text):
        dtype = (
            "STUDENT_ID"
            if _cue_before(_STUDENT_CUE_RE, text, m.start(1))
            else "ID_NUMBER"
        )
        candidates.append(_make_entity(dtype, m, text, score=0.8))
```

`fn_scanner.py`: change the loose-date fallback pattern's data_type from `"DATE_OF_BIRTH"` to `"DATE"` (same score/redact_type). Update any test in `tests/test_step2_detection.py` that asserts the old `DATE_OF_BIRTH` label for cue-less dates (search `DATE_OF_BIRTH` in that file; adjust ONLY where the fixture has no เกิด cue, note it in the commit message).

- [ ] **Step 4: Run to verify GREEN**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_step2_detection.py tests/test_recall_leaks.py tests/test_step3_pseudonymize.py -q`
Expected: all PASS (`test_recall_leaks.py` proves the matching set didn't shrink; if a recall-leak test asserts PASSPORT for a cue-less general match, that fixture text contains a passport cue — verify before touching, and if it genuinely has no cue, the fixture represents the old lie: update label with justification).

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/detectors/fp_detector.py pii_redactor/detectors/fn_scanner.py tests/test_step2_detection.py
git commit -m "feat(detector): honest FP labels — DATE vs DOB, ID_NUMBER vs STUDENT_ID/PASSPORT by cue"
```

---

### Task 3: tb_detector honest labels (LABEL_MAP + cue upgrades)

**Files:**
- Modify: `pii_redactor/detectors/tb_detector.py:17-31` (LABEL_MAP) and `_ner_candidates` (label resolution, line ~182)
- Test: `tests/test_step2_detection.py`

**Interfaces:**
- Consumes: `_cue_before`-style pattern (private copy here to avoid importing fp_detector — same "copied to avoid circular import" precedent as `_deduplicate`).
- Produces: `LABEL_MAP` = PERSON→NAME, ORGANIZATION/ORG→ORGANIZATION, LOCATION/GPE/LOC→LOCATION, DATE→DATE (TIME/MONEY/PERCENT/FACILITY/PRODUCT stay None); `_apply_cue_upgrades(text, start, end, data_type) -> str` with `_ADDR_CUE_RE = re.compile(r"ที่อยู่|บ้านเลขที่|อาศัยอยู่|พักอยู่|เลขที่|ซอย|ถนน|ตำบล|แขวง|อำเภอ|เขต|จังหวัด")`, `_TB_BIRTH_CUE_RE = re.compile(r"เกิด")`, `_TB_CUE_WINDOW = 30`. CRITICAL: the LOCATION→ADDRESS check scans `text[max(0, start-30):end]` — INCLUDING the span itself, because address cues (เขต/ตำบล/ซอย) usually live INSIDE the address span (e.g. "55 เขตบางรัก"); the DATE→DATE_OF_BIRTH check scans only the 30 chars BEFORE start.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_step2_detection.py` (deterministic via a fake engine; real CRF output is not stable enough to pin):

```python
def _fake_ner_detect(text, bio_tokens, monkeypatch):
    """Run detect_tb with a fake engine that returns fixed BIO tokens."""
    import pii_redactor.detectors.tb_detector as tbd

    class FakeNER:
        def tag(self, chunk):
            return [(w, t) for (w, t) in bio_tokens if w in chunk]

    monkeypatch.setitem(tbd._ner_cache, "thainer", FakeNER())
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    return tbd.detect_tb(text)


def test_tb_location_without_cue_stays_location(monkeypatch):
    text = "ปีหน้าจะไปเที่ยวเชียงใหม่กับครอบครัว"
    ents = _fake_ner_detect(text, [("เชียงใหม่", "B-LOCATION")], monkeypatch)
    assert any(e.data_type == "LOCATION" and e.original_text == "เชียงใหม่" for e in ents)
    assert not any(e.data_type == "ADDRESS" for e in ents)


def test_tb_location_with_addr_cue_upgrades_to_address(monkeypatch):
    text = "บ้านเลขที่ 55 เขตบางรัก กรุงเทพ"
    ents = _fake_ner_detect(text, [("เขตบางรัก", "B-LOCATION")], monkeypatch)
    assert any(e.data_type == "ADDRESS" for e in ents)


def test_tb_date_with_birth_cue_upgrades_to_dob(monkeypatch):
    text = "เกิดวันที่ 12 พฤษภาคม 2530 ที่กรุงเทพ"
    ents = _fake_ner_detect(
        text, [("12 พฤษภาคม 2530", "B-DATE")], monkeypatch
    )
    assert any(e.data_type == "DATE_OF_BIRTH" for e in ents)


def test_tb_organization_is_kept_and_labeled(monkeypatch):
    text = "ผมทำงานที่ธนาคารกสิกรไทยมาห้าปี"
    ents = _fake_ner_detect(text, [("ธนาคารกสิกรไทย", "B-ORGANIZATION")], monkeypatch)
    assert any(e.data_type == "ORGANIZATION" for e in ents)
```

- [ ] **Step 2: Run to verify RED**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_step2_detection.py -q -k "tb_location or tb_date_with or tb_organization"`
Expected: FAIL — LOCATION comes back ADDRESS (old map), ORGANIZATION comes back absent (mapped None).

- [ ] **Step 3: Implement** in `tb_detector.py`:

New `LABEL_MAP` (replace lines 17-31):

```python
LABEL_MAP: dict[str, str | None] = {
    "PERSON": "NAME",
    "ORGANIZATION": "ORGANIZATION",  # quasi-identifier (employer/hospital)
    "LOCATION": "LOCATION",          # upgraded to ADDRESS by cue (below)
    "DATE": "DATE",                  # upgraded to DATE_OF_BIRTH by cue (below)
    "TIME": None,
    "MONEY": None,
    "PERCENT": None,
    "FACILITY": None,
    "PRODUCT": None,
    # Aliases from brief (kept for safety)
    "ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
}
```

Add after `LABEL_MAP`:

```python
# Cue-based upgrades (same cue-window mechanism as fp_detector's
# _disambiguate_bank_phone; regexes copied rather than imported to avoid a
# circular import, same precedent as _deduplicate below).
# The ADDRESS check includes the span ITSELF because address cues (เขต/ตำบล/
# ซอย/ถนน) usually sit inside the address text; the DOB check looks only at
# the preceding context.
import re

_ADDR_CUE_RE = re.compile(
    r"ที่อยู่|บ้านเลขที่|อาศัยอยู่|พักอยู่|เลขที่|ซอย|ถนน|ตำบล|แขวง|อำเภอ|เขต|จังหวัด"
)
_TB_BIRTH_CUE_RE = re.compile(r"เกิด")
_TB_CUE_WINDOW = 30


def _apply_cue_upgrades(text: str, start: int, end: int, data_type: str) -> str:
    if data_type == "LOCATION":
        ctx = text[max(0, start - _TB_CUE_WINDOW):end]
        if _ADDR_CUE_RE.search(ctx):
            return "ADDRESS"
    elif data_type == "DATE":
        ctx = text[max(0, start - _TB_CUE_WINDOW):start]
        if _TB_BIRTH_CUE_RE.search(ctx):
            return "DATE_OF_BIRTH"
    return data_type
```

(put the `import re` at the top of the file with the other imports, not mid-file)

In `_ner_candidates`, after computing `orig_start`/`orig_end` and before appending the Entity, resolve the final label:

```python
            data_type = LABEL_MAP.get(label)
            if data_type is None:
                continue
            orig_start = sent_offset + (ctx_start - context_sent_start)
            orig_end = sent_offset + (ctx_end - context_sent_start)
            if (orig_end - orig_start) < 2:
                continue
            data_type = _apply_cue_upgrades(text, orig_start, orig_end, data_type)
```

- [ ] **Step 4: Run to verify GREEN**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_step2_detection.py tests/test_name_context.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/detectors/tb_detector.py tests/test_step2_detection.py
git commit -m "feat(detector): honest TB labels — LOCATION/DATE/ORGANIZATION with cue upgrades"
```

---

### Task 4: Stride-chunk windowing (kill the ~7x re-tag)

**Files:**
- Modify: `pii_redactor/detectors/tb_detector.py` `_ner_candidates` (lines ~156-197) + `detect_tb` docstring/default
- Test: new `tests/test_tb_windowing.py`

**Interfaces:**
- Consumes: `sentence_offsets: list[tuple[str, int]]` built in `detect_tb` (sentence text + global start offset), `_bio_to_spans`, `_apply_cue_upgrades` (Task 3).
- Produces: `_ner_candidates(text, ner, sentence_offsets, margin_sentences)` — chunks of consecutive sentences whose CORE totals ≤ `_CHUNK_CORE_CHARS = 500` (always ≥1 sentence), with `margin_sentences` (default 1) sentences of context before/after; the tagged string is `text[ctx_begin:ctx_end]` **sliced from the original text** (never a join of sentences — joins drop inter-sentence gaps and corrupt offsets); global offset = `ctx_begin + ctx_start`; keep only spans whose global START falls inside the core `[core_begin, core_end)`. `detect_tb(text, *, window_size: int = 1)` — the kwarg KEEPS its name for caller compatibility but now means margin sentences; docstring updated.

- [ ] **Step 1: Write the failing tests** — create `tests/test_tb_windowing.py`:

```python
"""Stride-chunk NER windowing: ~1.2x chars tagged instead of ~7x, offsets exact."""
import pii_redactor.detectors.tb_detector as tbd


class SpyNER:
    """Counts every character handed to .tag(); finds no entities."""

    def __init__(self):
        self.chars_tagged = 0
        self.calls = 0

    def tag(self, chunk):
        self.chars_tagged += len(chunk)
        self.calls += 1
        return [(chunk, "O")]


class NameNER:
    """Tags every occurrence of 'สมชาย' in the chunk as PERSON."""

    def tag(self, chunk):
        out = []
        pos = 0
        while True:
            i = chunk.find("สมชาย", pos)
            if i < 0:
                out.append((chunk[pos:], "O"))
                break
            if i > pos:
                out.append((chunk[pos:i], "O"))
            out.append(("สมชาย", "B-PERSON"))
            pos = i + len("สมชาย")
        return [(w, t) for (w, t) in out if w]


def _with_engine(monkeypatch, engine):
    monkeypatch.setitem(tbd._ner_cache, "thainer", engine)
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")


def test_chars_tagged_is_near_linear(monkeypatch):
    spy = SpyNER()
    _with_engine(monkeypatch, spy)
    # ~30 sentences of ~40 chars -> old sliding window tagged ~7x
    text = " ".join(f"ประโยคทดสอบหมายเลข {i} มีความยาวประมาณนี้ครับ" for i in range(30))
    tbd.detect_tb(text)
    assert spy.chars_tagged <= 1.5 * len(text), (
        f"tagged {spy.chars_tagged} chars for a {len(text)}-char text "
        f"(> 1.5x — stride chunking is not in effect)"
    )


def test_entity_near_chunk_boundary_found_once(monkeypatch):
    _with_engine(monkeypatch, NameNER())
    # long filler so the name lands deep into a later chunk
    filler = " ".join(f"ประโยคเติมความยาวหมายเลข {i} เพื่อดันข้อความให้ยาวขึ้น" for i in range(20))
    text = filler + " ลงชื่อ สมชาย ผู้จัดการ"
    ents = [e for e in tbd.detect_tb(text) if "สมชาย" in e.original_text]
    assert len(ents) == 1
    e = ents[0]
    start = text.index("สมชาย")
    assert e.span[0] <= start < e.span[1]
    assert text[e.span[0]:e.span[1]] == e.original_text


def test_short_text_single_chunk(monkeypatch):
    spy = SpyNER()
    _with_engine(monkeypatch, spy)
    tbd.detect_tb("ประโยคเดียวสั้นๆ")
    assert spy.calls == 1
```

Note for the boundary test: `NameNER` tags the name in the margin too; the core-start filter must ensure exactly ONE surviving entity with exact offsets. (`detect_name_context` also fires on the `ลงชื่อ` cue and dedup keeps the higher-scoring/longer span — the assertion counts entities whose text CONTAINS สมชาย, which stays 1 after dedup either way.)

- [ ] **Step 2: Run to verify RED**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_tb_windowing.py -q`
Expected: `test_chars_tagged_is_near_linear` FAILS (~7x), `test_short_text_single_chunk` FAILS (one call per sentence).

- [ ] **Step 3: Implement** — replace `_ner_candidates` in `tb_detector.py`:

```python
_CHUNK_CORE_CHARS = 500


def _ner_candidates(
    text: str, ner: NER, sentence_offsets: list[tuple[str, int]], margin_sentences: int
) -> list[Entity]:
    """Run one NER engine over stride chunks and return TB Entity candidates
    mapped to original-text offsets (pre-dedup).

    Chunks are runs of consecutive sentences whose combined length is capped
    at ~_CHUNK_CORE_CHARS (always at least one sentence), padded with
    `margin_sentences` sentences of context on each side. The tagged string is
    ALWAYS a slice of the original text (a join of sentence strings would drop
    the gaps between sentences and corrupt every offset after the first gap).
    Only spans that START inside the chunk core are kept, so margins never
    duplicate entities across neighbouring chunks. Each sentence is tagged
    ~1+2*margin/chunk_len times instead of the old sliding window's ~7x.
    """
    n = len(sentence_offsets)
    candidates: list[Entity] = []

    def _sent_start(i: int) -> int:
        return sentence_offsets[i][1]

    def _sent_end(i: int) -> int:
        s, off = sentence_offsets[i]
        return off + len(s)

    chunk_first = 0
    while chunk_first < n:
        # grow the core until the char cap (always >= 1 sentence)
        chunk_last = chunk_first
        while (
            chunk_last + 1 < n
            and _sent_end(chunk_last + 1) - _sent_start(chunk_first) <= _CHUNK_CORE_CHARS
        ):
            chunk_last += 1

        core_begin = _sent_start(chunk_first)
        core_end = _sent_end(chunk_last)
        ctx_begin = _sent_start(max(0, chunk_first - margin_sentences))
        ctx_end = _sent_end(min(n - 1, chunk_last + margin_sentences))
        context_text = text[ctx_begin:ctx_end]

        try:
            tagged: list[tuple[str, str]] = ner.tag(context_text)
        except Exception:
            chunk_first = chunk_last + 1
            continue

        if tagged:
            for ent_text, ctx_start, ctx_end_pos, label in _bio_to_spans(tagged, context_text):
                orig_start = ctx_begin + ctx_start
                orig_end = ctx_begin + ctx_end_pos
                if not (core_begin <= orig_start < core_end):
                    continue
                data_type = LABEL_MAP.get(label)
                if data_type is None:
                    continue
                if (orig_end - orig_start) < 2:
                    continue
                data_type = _apply_cue_upgrades(text, orig_start, orig_end, data_type)
                candidates.append(Entity(
                    entity_id=str(uuid.uuid4()),
                    redact_type="TB",
                    data_type=data_type,
                    span=(orig_start, orig_end),
                    score=0.85,
                    original_text=text[orig_start:orig_end],
                ))

        chunk_first = chunk_last + 1

    return candidates
```

In `detect_tb`: change the signature default to `window_size: int = 1`, pass it through as `margin_sentences` (`_ner_candidates(text, ner, sentence_offsets, window_size)` — call site unchanged), and update the docstring line to: `window_size: sentences of margin context on each side of a chunk (default 1; raise to 2 if benchmark recall regresses)`.

- [ ] **Step 4: Run to verify GREEN + no semantic regressions**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_tb_windowing.py tests/test_step2_detection.py tests/test_name_context.py tests/test_ner_engine.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/detectors/tb_detector.py tests/test_tb_windowing.py
git commit -m "perf(detector): stride-chunk NER windowing — ~1.2x chars tagged instead of ~7x"
```

---

### Task 5: Benchmark alignment (corpus + gold relabel, floors intact)

**Files:**
- Modify: `benchmark/gold.py`, `benchmark/corpus.py` (labels only where the new semantics changed them), possibly `tests/test_benchmark.py` / `tests/test_benchmark_gold.py` label references
- Test: benchmark test files + a real benchmark run

**Interfaces:**
- Consumes: new label behavior from Tasks 2-3.
- Produces: gold/corpus expectations aligned with honest labels; ALL floor THRESHOLDS unchanged.

- [ ] **Step 1: Survey what the semantics change touched**

Run: `git grep -n "DATE_OF_BIRTH\|STUDENT_ID\|PASSPORT\|ADDRESS" -- benchmark/ | head -50`
For every gold doc / corpus template hit, decide by the new rules: date WITH เกิด cue stays `DATE_OF_BIRTH`, without → `DATE`; 8-12 digit value with student cue stays `STUDENT_ID`, without → `ID_NUMBER`; general passport with cue stays `PASSPORT`, without → `ID_NUMBER`; address strings containing เลขที่/ซอย/ถนน/ตำบล/เขต/อำเภอ (they nearly all do) stay `ADDRESS`. Where a template lacks the cue but the type should survive (e.g. a DOB sample), PREFER adding the natural cue to the template text (เกิดวันที่ ...) over relabeling — the sample then tests the upgrade path.

- [ ] **Step 2: Apply the relabels/cue-edits and run the benchmark tests**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_benchmark.py tests/test_benchmark_gold.py tests/test_benchmark_strategies.py -q`
Expected: all PASS with UNCHANGED thresholds. If a floor fails, the cue-upgrade rules or the relabel is wrong — fix those, never the threshold.

- [ ] **Step 3: Run the real CRF benchmark on both sources and record**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m benchmark --source gold --json benchmark/reports/gold-crf-post10.json` then `--source synthetic --seed 42 --size 200 --json benchmark/reports/syn-crf-post10.json`
Expected: exit 0; eyeball NAME/ADDRESS recall vs the ADR numbers (gold CRF NAME ~0.607, ADDRESS ~0.882 pre-change) — a drop >0.05 on either means the chunk margin is too thin: set `window_size` default to 2 in `detect_tb`, re-run, and note the outcome in the commit message.

- [ ] **Step 4: Commit**

```bash
git add benchmark/ tests/test_benchmark.py tests/test_benchmark_gold.py
git commit -m "test(benchmark): align gold/corpus labels with honest type semantics (floors unchanged)"
```

(include the per-item relabel rationale in the commit body)

---

### Task 6: Union gold gate, e2e round-trip, docs, PR

**Files:**
- Modify: `pii_redactor/models.py` (Entity docstring data_type list), `docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md` (status line)
- Test: `tests/test_e2e_examples.py` (append), full suite, sweep

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Union gold validation (transformers installed locally)**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest tests/test_union_gold_validation.py tests/test_ner_engine.py -q`
Expected: PASS with the ORIGINAL floors (ADDRESS ≥0.99, NAME ≥0.60, overall ≥0.83). Failure → widen margin to 2 (if not already) per Task 5 Step 3; still failing → STOP and report BLOCKED with the numbers.

- [ ] **Step 2: Write the business round-trip e2e test** — append to `tests/test_e2e_examples.py` (follow the file's client style):

```python
def test_business_doc_surrogates_stay_plausible(client):
    """Invoice numbers and meeting dates must mask as same-shape values
    (ID_NUMBER keeps digit length, DATE stays a date) — not as fake
    passports/birthdays — and restore exactly."""
    # 8-digit invoice number on purpose — 10 digits would be claimed by the
    # BANK_ACCOUNT pattern instead of ID_NUMBER.
    text = "ใบแจ้งหนี้เลขที่ 12345678 นัดประชุมวันที่ 12/05/2569 กับ สมชาย ใจดี"
    s = client.post("/api/sanitize", json={"text": text, "mode": "surrogate"}).json()
    assert "12345678" not in s["sanitized_text"]
    assert "12/05/2569" not in s["sanitized_text"]
    types = {e["data_type"] for e in s["entities"]}
    assert "ID_NUMBER" in types and "DATE" in types
    assert "PASSPORT" not in types and "DATE_OF_BIRTH" not in types
    r = client.post("/api/reidentify",
                    json={"session_id": s["session_id"], "text": s["sanitized_text"]}).json()
    assert "12345678" in r["restored_text"] and "12/05/2569" in r["restored_text"]
```

Run it: expect PASS already (capability landed in Tasks 1-2); if FAIL, the pipeline wiring has a bug — investigate, don't weaken.

- [ ] **Step 3: Docs**

- `pii_redactor/models.py`: extend the Entity docstring's data_type enumeration with `LOCATION`, `DATE`, `ORGANIZATION`, `ID_NUMBER`.
- Roadmap "อัปเดตสถานะ (2026-07-16)" section, append:

```markdown
- **Horizon-2 #10 TB restructure — เสร็จ (2026-07-16)**: stride-chunk windowing (~1.2x เทียบ ~7x, gate ด้วย spy test + gold floors เดิม) + honest labels (DATE/LOCATION/ORGANIZATION/ID_NUMBER พร้อม cue upgrade เป็น DOB/ADDRESS/STUDENT_ID/PASSPORT) — mask เท่าเดิม label ตรงความจริง
```

- [ ] **Step 4: Full verification + commit + PR**

Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pytest -q` → all pass (~450+); `PYTHONUTF8=1 ./.venv/Scripts/python.exe benchmark/sweep_web_guard.py` → `TOTAL: 0`.

```bash
git add pii_redactor/models.py docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md tests/test_e2e_examples.py
git commit -m "test(e2e): business-doc surrogate plausibility + docs for honest type semantics"
git push -u origin feat/tb-restructure
gh pr create --base main --title "feat(detector): stride-chunk NER windowing + honest type semantics (Horizon-2 #10)" --body "$(cat <<'EOF'
The PR body MUST contain, in this order: (1) the mask-เท่าเดิม-label-ซื่อสัตย์ policy sentence; (2) the new label rules table (DATE/DOB, LOCATION/ADDRESS, ORGANIZATION, ID_NUMBER/STUDENT_ID/PASSPORT cues); (3) windowing change + the spy-test chars-tagged ratio measured; (4) gold + synthetic recall numbers BEFORE vs AFTER from the Task 5 runs, stating floors unchanged; (5) margin setting used (1 or 2) and why.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

(compose the real prose for items 1-5 — the list above names the required content, it is not literal body text)
```

---

## Final verification (controller)

- [ ] Contract files untouched: `git diff main -- tests/test_step11_api.py tests/test_api_hardening.py` → empty
- [ ] Union gold floors pass; benchmark reports recorded under `benchmark/reports/` are gitignored — quote the numbers in the PR body instead
- [ ] CI green; merge after review
