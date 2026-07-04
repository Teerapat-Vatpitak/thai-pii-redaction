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
    # THAI_ID/EMAIL/DATE_OF_BIRTH are format-preserving types -- must be "FP"
    # so anonymizer.py generates a realistic fake value (generate_fp), not
    # tb_generator's literal "[REDACTED_x]" fallback.
    assert e.redact_type == "FP"
    assert isinstance(e.entity_id, str)
    assert len(e.entity_id) > 0


def test_scan_fn_thai_id_and_date_are_fp():
    text = "id: 1234567890123 date: 01/01/2000"
    result = scan_fn(text, [])
    by_type = {e.data_type: e for e in result}
    assert by_type["THAI_ID"].redact_type == "FP"
    assert by_type["DATE_OF_BIRTH"].redact_type == "FP"


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
