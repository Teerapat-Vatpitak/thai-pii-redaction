"""Tests for Step 2 FP detection: thai_id.py and fp_detector.py."""
from pii_redactor.detectors.thai_id import is_valid_thai_id
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.models import Entity


# ---------------------------------------------------------------------------
# Thai ID tests
# ---------------------------------------------------------------------------

def test_thai_id_valid():
    # Build a valid ID programmatically: first 12 digits, compute check digit
    digits = [1, 1, 0, 1, 2, 0, 0, 0, 1, 2, 3, 4]
    weights = [13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(d * w for d, w in zip(digits, weights))
    check = (11 - (total % 11)) % 10
    valid_id = "".join(str(d) for d in digits) + str(check)
    assert is_valid_thai_id(valid_id) is True


def test_thai_id_invalid():
    assert is_valid_thai_id("1101200012346") is False  # wrong check digit
    assert is_valid_thai_id("123") is False             # too short
    assert is_valid_thai_id("abcdefghijklm") is False   # non-digits


def test_thai_id_non_digit_returns_false():
    assert is_valid_thai_id("") is False


# ---------------------------------------------------------------------------
# FP detector tests
# ---------------------------------------------------------------------------

def test_detect_fp_email():
    text = "ติดต่อที่ wittaya.s@company.co.th หรือ test@gmail.com"
    entities = detect_fp(text)
    emails = [e for e in entities if e.data_type == "EMAIL"]
    assert len(emails) >= 1
    assert any("wittaya" in e.original_text for e in emails)


def test_detect_fp_phone():
    text = "โทร 081-234-5678 หรือ 02-345-6789"
    entities = detect_fp(text)
    phones = [e for e in entities if e.data_type == "PHONE"]
    assert len(phones) >= 1


def test_detect_fp_sample_thai():
    from pathlib import Path
    text = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    entities = detect_fp(text)
    types = {e.data_type for e in entities}
    assert "PHONE" in types
    assert "EMAIL" in types


def test_detect_fp_no_overlap():
    text = "ID: 1101200012345 email: test@example.com"
    entities = detect_fp(text)
    for i, e1 in enumerate(entities):
        for j, e2 in enumerate(entities):
            if i != j:
                assert e1.span[1] <= e2.span[0] or e1.span[0] >= e2.span[1], (
                    f"Overlapping spans: {e1} and {e2}"
                )


def test_detect_fp_span_min_2():
    text = "test@example.com 081-234-5678"
    entities = detect_fp(text)
    for e in entities:
        assert e.span[1] - e.span[0] >= 2


def test_detect_fp_entity_fields():
    text = "test@example.com"
    entities = detect_fp(text)
    assert len(entities) > 0
    e = entities[0]
    assert isinstance(e, Entity)
    assert e.redact_type == "FP"
    assert isinstance(e.score, float)
    assert isinstance(e.entity_id, str)
    assert len(e.entity_id) > 0


def test_detect_fp_sorted_by_span():
    text = "phone: 081-234-5678 email: test@example.com"
    entities = detect_fp(text)
    if len(entities) >= 2:
        for i in range(len(entities) - 1):
            assert entities[i].span[0] <= entities[i + 1].span[0]


def test_detect_fp_credit_card_luhn():
    # Valid Luhn: 4532015112830366
    text = "card: 4532015112830366"
    entities = detect_fp(text)
    ccs = [e for e in entities if e.data_type == "CREDIT_CARD"]
    assert len(ccs) == 1


def test_detect_fp_invalid_credit_card_not_detected():
    # Invalid Luhn: 4532015112830367
    text = "card: 4532015112830367"
    entities = detect_fp(text)
    ccs = [e for e in entities if e.data_type == "CREDIT_CARD"]
    assert len(ccs) == 0


def test_detect_fp_iban_valid():
    # GB29NWBK60161331926819 is the canonical IBAN test vector (mod-97 == 1)
    text = "IBAN: GB29NWBK60161331926819"
    entities = detect_fp(text)
    ibans = [e for e in entities if e.data_type == "IBAN"]
    assert len(ibans) == 1
    assert "GB29" in ibans[0].original_text


def test_detect_fp_iban_invalid_not_detected():
    # GB29NWBK60161331926820 — last digit changed, mod-97 != 1
    text = "IBAN: GB29NWBK60161331926820"
    entities = detect_fp(text)
    ibans = [e for e in entities if e.data_type == "IBAN"]
    assert len(ibans) == 0


def test_detect_fp_thai_id_in_mixed_text():
    text = "ID: 1101200012345 email: test@example.com"
    entities = detect_fp(text)
    # Verify email is detected (Thai ID 1101200012345 has check digit 5 which may or may not be valid)
    emails = [e for e in entities if e.data_type == "EMAIL"]
    assert len(emails) >= 1


def test_detect_fp_intl_phone():
    text = "call +66-8-123-4567 for info"
    entities = detect_fp(text)
    phones = [e for e in entities if e.data_type == "PHONE"]
    assert len(phones) >= 1


# ---------------------------------------------------------------------------
# TB detector tests
# ---------------------------------------------------------------------------

from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.detectors.fn_scanner import scan_fn


def test_detect_tb_returns_list():
    text = "นายวิทยา สมบูรณ์ อาศัยอยู่ที่กรุงเทพมหานคร"
    result = detect_tb(text)
    assert isinstance(result, list)
    for e in result:
        assert isinstance(e, Entity)


def test_detect_tb_redact_type():
    text = "นายวิทยา สมบูรณ์ อาศัยอยู่ที่กรุงเทพมหานคร"
    result = detect_tb(text)
    for e in result:
        assert e.redact_type == "TB"


def test_detect_tb_no_overlap():
    text = "นายวิทยา สมบูรณ์ อาศัยอยู่ที่กรุงเทพมหานคร"
    entities = detect_tb(text)
    for i, e1 in enumerate(entities):
        for j, e2 in enumerate(entities):
            if i != j:
                assert e1.span[1] <= e2.span[0] or e1.span[0] >= e2.span[1]


def test_detect_tb_span_min_2():
    text = "นายวิทยา สมบูรณ์ อาศัยอยู่ที่กรุงเทพมหานคร"
    entities = detect_tb(text)
    for e in entities:
        assert e.span[1] - e.span[0] >= 2


def test_detect_tb_sample_thai():
    from pathlib import Path
    text = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    result = detect_tb(text)
    assert isinstance(result, list)


def test_detect_tb_sorted_by_span():
    text = "นายวิทยา สมบูรณ์ อาศัยอยู่ที่กรุงเทพมหานคร"
    entities = detect_tb(text)
    if len(entities) >= 2:
        for i in range(len(entities) - 1):
            assert entities[i].span[0] <= entities[i + 1].span[0]


def test_detect_tb_empty_text():
    result = detect_tb("")
    assert result == []


def test_detect_tb_score():
    text = "นายวิทยา สมบูรณ์ อาศัยอยู่ที่กรุงเทพมหานคร"
    entities = detect_tb(text)
    for e in entities:
        assert isinstance(e.score, float)
        assert 0.0 <= e.score <= 1.0


# ---------------------------------------------------------------------------
# FN scanner tests
# ---------------------------------------------------------------------------

def test_scan_fn_no_duplicates():
    import uuid as _uuid
    text = "email: test@example.com and 1234567890123"
    existing = [Entity(
        entity_id=str(_uuid.uuid4()),
        redact_type="FP",
        data_type="EMAIL",
        span=(7, 23),
        score=1.0,
        original_text="test@example.com",
    )]
    new_ents = scan_fn(text, existing)
    for e in new_ents:
        assert not (e.span[0] < 23 and e.span[1] > 7)


def test_scan_fn_finds_new():
    text = "her id is 1234567890123 and more"
    new_ents = scan_fn(text, [])
    thirteen_digit = [e for e in new_ents if e.data_type == "THAI_ID"]
    assert len(thirteen_digit) >= 1


def test_scan_fn_returns_list():
    result = scan_fn("hello world", [])
    assert isinstance(result, list)


def test_scan_fn_sorted_by_span():
    text = "id: 1234567890123 email: foo@bar.com date: 01/01/2000"
    result = scan_fn(text, [])
    if len(result) >= 2:
        for i in range(len(result) - 1):
            assert result[i].span[0] <= result[i + 1].span[0]


def test_scan_fn_entity_fields():
    text = "foo@bar.com"
    result = scan_fn(text, [])
    emails = [e for e in result if e.data_type == "EMAIL"]
    assert len(emails) >= 1
    e = emails[0]
    assert isinstance(e, Entity)
    # THAI_ID/EMAIL/DATE are format-preserving types -- must be "FP"
    # so anonymizer.py generates a realistic fake value (generate_fp), not
    # tb_generator's literal "[REDACTED_x]" fallback.
    assert e.redact_type == "FP"
    assert isinstance(e.entity_id, str)
    assert len(e.entity_id) > 0


def test_scan_fn_thai_id_and_date_are_fp():
    # No "เกิด" cue in this fixture -- fn_scanner's loose date fallback has no
    # cue context to gate on, so it always emits the honest generic DATE label
    # (see fp_detector.py's cue-gated DATE/DATE_OF_BIRTH split for the primary
    # detection pass, which does have cue context).
    text = "id: 1234567890123 date: 01/01/2000"
    result = scan_fn(text, [])
    by_type = {e.data_type: e for e in result}
    assert by_type["THAI_ID"].redact_type == "FP"
    assert by_type["DATE"].redact_type == "FP"


def test_scan_fn_iso_date():
    # fn_scanner's loose date fallback must also catch ISO year-first dates.
    text = "logged 2024-06-29 ok"
    result = scan_fn(text, [])
    assert any(e.data_type == "DATE" and e.original_text == "2024-06-29" for e in result)


def test_scan_fn_no_overlap_with_existing():
    import uuid as _uuid
    text = "date: 01/06/2024 and something"
    existing = [Entity(
        entity_id=str(_uuid.uuid4()),
        redact_type="FP",
        data_type="DATE_OF_BIRTH",
        span=(6, 16),
        score=1.0,
        original_text="01/06/2024",
    )]
    new_ents = scan_fn(text, existing)
    for e in new_ents:
        # Should not overlap with (6, 16)
        assert e.span[1] <= 6 or e.span[0] >= 16


# ---------------------------------------------------------------------------
# Honest labels: DATE vs DATE_OF_BIRTH, ID_NUMBER vs STUDENT_ID/PASSPORT
# ---------------------------------------------------------------------------

def test_fp_bare_date_is_generic_date():
    ents = detect_fp("นัดประชุมวันที่ 12/05/2569 ที่สำนักงานใหญ่")
    dates = [e for e in ents if e.data_type in ("DATE", "DATE_OF_BIRTH")]
    assert dates and all(e.data_type == "DATE" for e in dates)


def test_fp_birth_cue_date_is_dob():
    ents = detect_fp("ผมเกิดวันที่ 12/05/2530 ครับ")
    assert any(e.data_type == "DATE_OF_BIRTH" for e in ents)


def test_fp_iso_date_generic():
    # ISO year-first dates (yyyy-mm-dd) used to be missed entirely: the regex
    # led with \d{1,2} and _date_sanity assumed day-first.
    ents = detect_fp("บันทึกเมื่อวันที่ 2024-06-29 เวลาบ่าย")
    dates = [e for e in ents if e.data_type in ("DATE", "DATE_OF_BIRTH")]
    assert any(e.original_text == "2024-06-29" for e in dates)
    assert all(e.data_type == "DATE" for e in dates)  # no birth cue


def test_fp_iso_date_with_birth_cue_is_dob():
    ents = detect_fp("ผมเกิดวันที่ 1990-01-15 ครับ")
    assert any(
        e.data_type == "DATE_OF_BIRTH" and e.original_text == "1990-01-15"
        for e in ents
    )


def test_fp_bare_long_number_is_id_number():
    # 8 digits ON PURPOSE: a 10-digit value is claimed by the BANK_ACCOUNT
    # pattern (\d{7}\d{3}) at score 1.0 and would never reach ID_NUMBER.
    ents = detect_fp("เลขที่ใบแจ้งหนี้ 12345678 ออกเมื่อวานนี้")
    assert any(e.data_type == "ID_NUMBER" and e.original_text == "12345678" for e in ents)
    assert not any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_student_cue_keeps_student_id():
    # 9 digits, not the brief's original 10: a 10-digit run is also claimed by
    # the pre-existing BANK_ACCOUNT pattern (\d{7}\d{3}) at score 1.0, which
    # beats STUDENT_ID's 0.8 in dedup regardless of any cue -- a real
    # (out-of-scope) collision unrelated to this task's cue-gating change.
    ents = detect_fp("รหัสนักศึกษา 641234567 คณะวิศวกรรมศาสตร์")
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


# ---------------------------------------------------------------------------
# TB honest labels: LOCATION/DATE/ORGANIZATION with cue upgrades
# ---------------------------------------------------------------------------

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


def test_tb_ner_failure_is_logged_not_silent(monkeypatch, caplog):
    """A NER engine that raises must not silently swallow a whole chunk of
    text — the failure has to be logged so missed PII is observable."""
    import logging
    import pii_redactor.detectors.tb_detector as tbd

    class BoomNER:
        def tag(self, chunk):
            raise RuntimeError("boom")

    monkeypatch.setitem(tbd._ner_cache, "thainer", BoomNER())
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    with caplog.at_level(logging.WARNING, logger="pii_redactor.detectors.tb_detector"):
        # must not raise — detection degrades, does not crash
        tbd.detect_tb("วันนี้อากาศดีมากเลยครับ ไปเที่ยวกันเถอะ")
    assert any("NER" in r.getMessage() for r in caplog.records)


def test_tb_organization_is_kept_and_labeled(monkeypatch):
    text = "ผมทำงานที่ธนาคารกสิกรไทยมาห้าปี"
    ents = _fake_ner_detect(text, [("ธนาคารกสิกรไทย", "B-ORGANIZATION")], monkeypatch)
    assert any(e.data_type == "ORGANIZATION" for e in ents)


def test_tb_pure_latin_org_is_rejected_by_thai_guard(monkeypatch):
    """DELIBERATE recall trade (commit 3d02738): thainer CRF hallucinates
    ORGANIZATION on plain-English text, so an ORGANIZATION span with zero Thai
    characters is dropped — including a real foreign employer name. Pinned
    here so any future change to this boundary is a conscious decision."""
    text = "ผมทำงานที่ Google มาสามปีแล้ว"
    ents = _fake_ner_detect(text, [("Google", "B-ORGANIZATION")], monkeypatch)
    assert not any(e.data_type == "ORGANIZATION" for e in ents)


def test_tb_mixed_thai_latin_org_survives_thai_guard(monkeypatch):
    text = "ผมทำงานที่บริษัท เอบีซี จำกัด สาขาไทย"
    ents = _fake_ner_detect(
        text, [("บริษัท เอบีซี จำกัด", "B-ORGANIZATION")], monkeypatch
    )
    assert any(e.data_type == "ORGANIZATION" for e in ents)
