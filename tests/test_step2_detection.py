"""Tests for Step 2 FP detection: thai_id.py and fp_detector.py."""

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.thai_id import is_valid_thai_id
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
    assert is_valid_thai_id("123") is False  # too short
    assert is_valid_thai_id("abcdefghijklm") is False  # non-digits


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


def test_detect_landline_9_digit_bangkok():
    """DET-1: Thai landlines are 9 digits (02-XXX-XXXX). The old regex required
    10, so every standard-format Bangkok landline was missed entirely."""
    for text in ("โทร 02-123-4567 ครับ", "02-123-4567", "021234567"):
        phones = [e for e in detect_fp(text) if e.data_type == "PHONE"]
        assert phones, f"landline not detected in {text!r}"


def test_detect_landline_9_digit_provincial():
    """DET-1: provincial landlines are 0XX-XXX-XXX (3-3-3), also 9 digits."""
    for text in ("074-123-456", "038-123-456"):
        phones = [e for e in detect_fp(text) if e.data_type == "PHONE"]
        assert phones, f"provincial landline not detected in {text!r}"


def test_detect_landline_with_separator_after_trunk_prefix():
    """DET-1 (follow-up): Thai organisations routinely write a Bangkok landline
    as 0-2XXX-XXXX, splitting after the trunk prefix rather than after the '02'
    area code. Both regexes required the digit after '0' to be adjacent, so this
    shape was missed -- and the pre-send guard runs the same detect_fp, so the
    number reached the external AI unmasked."""
    for text in ("โทร 0-2123-4567 ครับ", "0-2123-4567", "0 2123 4567"):
        phones = [e for e in detect_fp(text) if e.data_type == "PHONE"]
        assert phones, f"landline not detected in {text!r}"


def test_detect_mobile_with_separator_after_trunk_prefix():
    """DET-1 (follow-up): the same split applies to mobiles (0-81-234-5678)."""
    for text in ("0-81-234-5678", "0 81 234 5678"):
        phones = [e for e in detect_fp(text) if e.data_type == "PHONE"]
        assert phones, f"mobile not detected in {text!r}"


def test_trunk_prefix_separator_does_not_cross_a_line_break():
    """The trunk-prefix separator must not be `\\s`, which matches a newline: a
    lone '0' ending a table row would then fuse with the digits on the next row
    into a bogus PHONE. That is not a harmless over-mask -- redactor's
    _build_redact_set splits an entity on whitespace and registers every word as
    a GLOBAL fragment, so a Buddhist year like 2565 becomes a document-wide
    black-box target, and PDF redaction flattens to image (irreversible)."""
    text = "รายการ  จำนวน\nส่วนลด  0\n2565 1234 บาท\n"
    phones = [e for e in detect_fp(text) if e.data_type == "PHONE"]
    assert not phones, f"line break swallowed into a phone span: {phones}"


def test_plate_regex_does_not_swallow_national_id():
    """DET-2: a Thai-consonant abbreviation before a long number (e.g. 'ปชช
    1101700230708') must not let the plate regex claim the leading digits and
    starve the checksum-valid THAI_ID via dedup."""
    ents = detect_fp("เลขบัตร ปชช 1101700230708 ของผม")
    assert any(e.data_type == "THAI_ID" for e in ents), (
        f"national ID lost to plate regex: {[(e.data_type, e.original_text) for e in ents]}"
    )
    assert not any(e.data_type == "VEHICLE_PLATE" for e in ents)


def test_plate_regex_does_not_swallow_phone():
    """DET-2: 'กทม 0812345678' must yield the full phone, not a truncated plate."""
    ents = detect_fp("ติดต่อคุณ กทม 0812345678")
    phones = [e for e in ents if e.data_type == "PHONE"]
    assert phones and "0812345678" in phones[0].original_text


def test_real_plate_still_detected():
    """DET-2 guard: the boundary fix must not break genuine plate detection."""
    ents = detect_fp("รถทะเบียน ขก 4471 จอดอยู่")
    assert any(e.data_type == "VEHICLE_PLATE" for e in ents)


def _covered(text: str, needle: str) -> bool:
    """True if some detected entity span covers the whole needle occurrence."""
    idx = text.index(needle)
    for e in detect_fp(text):
        if e.span[0] <= idx and e.span[1] >= idx + len(needle):
            return True
    return False


def test_plate_regex_does_not_swallow_separated_numbers():
    """DET-2 (separator variants): Thai IDs / phones / bank accounts / credit
    cards are normally written WITH dash or space separators. A separator after
    the plate's first digit group satisfies (?!\\d), so the plate can still claim
    the leading group unless dedup keeps the higher-score checksum-backed number.
    Every one of these must have its full number covered by a detection span."""
    cases = [
        ("เลขที่ ปชช 1-1017-00230-70-8", "1-1017-00230-70-8"),
        ("ปชช 1-1017-00230-70-8", "1-1017-00230-70-8"),
        ("กทม 081-234-5678", "081-234-5678"),
        ("ติดต่อ กทม 081 234 5678", "081 234 5678"),
        ("บช 123-4-56789-0", "123-4-56789-0"),
        ("บช 4111-1111-1111-1111", "4111-1111-1111-1111"),
    ]
    for text, number in cases:
        assert _covered(text, number), (
            f"{number!r} not fully covered in {text!r}: "
            f"{[(e.data_type, e.original_text) for e in detect_fp(text)]}"
        )


def test_detect_fp_sample_thai():
    from pathlib import Path

    text = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    entities = detect_fp(text)
    types = {e.data_type for e in entities}
    assert "PHONE" in types
    assert "EMAIL" in types


def test_detect_fp_house_number_after_address_label_colon_has_exact_span():
    """A form-style colon must not leave the identifying house number exposed."""
    text = "ที่อยู่: 99 ถนนพหลโยธิน แขวงจตุจักร กรุงเทพฯ 10900"
    house_numbers = [
        entity
        for entity in detect_fp(text)
        if entity.data_type == "ADDRESS" and entity.original_text == "99"
    ]

    assert len(house_numbers) == 1
    assert house_numbers[0].span == (text.index("99"), text.index("99") + 2)


def test_detect_fp_house_number_before_street_cue_has_exact_span():
    text = "88 ถนนตัวอย่าง แขวงทดสอบ กรุงเทพฯ 10110"
    houses = [
        entity
        for entity in detect_fp(text)
        if entity.data_type == "ADDRESS" and entity.original_text == "88"
    ]

    assert len(houses) == 1
    assert houses[0].span == (0, 2)


def test_buddhist_year_before_street_word_is_not_a_house_number():
    entities = detect_fp("ปี 2568 ถนนสายหลักเปิดใช้งาน")
    assert not any(
        entity.data_type == "ADDRESS" and entity.original_text == "2568" for entity in entities
    )


def test_house_number_in_buddhist_year_range_is_still_an_address():
    text = "2568 ถนนสุขุมวิท เขตวัฒนา กรุงเทพฯ 10110"
    assert any(
        entity.data_type == "ADDRESS" and entity.original_text == "2568"
        for entity in detect_fp(text)
    )


def test_buddhist_year_with_era_prefix_is_not_a_house_number():
    entities = detect_fp("พ.ศ. 2568 ถนนสุขุมวิทเปิดใช้งาน")
    assert not any(
        entity.data_type == "ADDRESS" and entity.original_text == "2568" for entity in entities
    )


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


def test_detect_all_recovers_a_name_in_repeated_id_records():
    from pii_redactor.detectors.aggregate import detect_all

    text = "สมชาย ใจดี\n1312271505581\nมาลี รักดี\n4951607747108"
    names = {entity.original_text for entity in detect_all(text) if entity.data_type == "NAME"}

    assert {"สมชาย ใจดี", "มาลี รักดี"} <= names


def test_detect_all_recovers_a_repeated_ocr_co_applicant():
    from pii_redactor.detectors.aggregate import detect_all

    text = "สมชาย ใจดี\n1312271505581\nและ...มาลิรักดี\nแถะ...มาลิรักดิ\n4951607747108"
    names = {entity.original_text for entity in detect_all(text) if entity.data_type == "NAME"}

    assert {"มาลิรักดี", "มาลิรักดิ"} <= names


def test_ocr_co_applicant_recovers_a_name_written_with_a_space():
    """The fixture above runs the given name into the surname, which is what a
    bad OCR read looks like. A form that kept the space is the ordinary shape
    and matched nothing at all, because the run before the name may hold only
    non-Thai characters — so the whole common case of this rule's own target
    class was missed, which is the recall-negative direction.
    """
    from pii_redactor.detectors.aggregate import detect_all

    text = "สมชาย ใจดี\n1312271505581\nและ ( ) สมหญิง รักดี\nแถะ ( ) สมหญิง รักดิ\n4951607747108"
    names = {entity.original_text for entity in detect_all(text) if entity.data_type == "NAME"}

    assert {"สมหญิง รักดี", "สมหญิง รักดิ"} <= names


def test_record_name_rule_rejects_form_prose():
    from pii_redactor.detectors.aggregate import detect_all

    text = (
        "สมชาย ใจดี\n1312271505581\n"
        "โรงงาน ทดสอบ\n4951607747108\n"
        "มูลนิธิ ตัวอย่าง\n3951607747108\n"
        "โครงการ ทดลอง\n2951607747108"
    )

    names = {entity.original_text for entity in detect_all(text) if entity.data_type == "NAME"}

    assert names == {"สมชาย ใจดี"}


def test_ocr_co_applicant_rule_rejects_repeated_form_prose():
    from pii_redactor.detectors.aggregate import detect_all

    text = "สมชาย ใจดี\n1312271505581\nและ...เอกสารแนบ\nแถะ...เอกสารแนบ\n4951607747108"
    names = {entity.original_text for entity in detect_all(text) if entity.data_type == "NAME"}

    assert names == {"สมชาย ใจดี"}


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

from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.detectors.tb_detector import detect_tb


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
    existing = [
        Entity(
            entity_id=str(_uuid.uuid4()),
            redact_type="FP",
            data_type="EMAIL",
            span=(7, 23),
            score=1.0,
            original_text="test@example.com",
        )
    ]
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
    existing = [
        Entity(
            entity_id=str(_uuid.uuid4()),
            redact_type="FP",
            data_type="DATE_OF_BIRTH",
            span=(6, 16),
            score=1.0,
            original_text="01/06/2024",
        )
    ]
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
    assert any(e.data_type == "DATE_OF_BIRTH" and e.original_text == "1990-01-15" for e in ents)


def test_fp_bare_long_number_is_id_number():
    # 8 digits ON PURPOSE: a 10-digit value is claimed by the BANK_ACCOUNT
    # pattern (\d{7}\d{3}) at score 1.0 and would never reach ID_NUMBER.
    ents = detect_fp("เลขที่ใบแจ้งหนี้ 12345678 ออกเมื่อวานนี้")
    assert any(e.data_type == "ID_NUMBER" and e.original_text == "12345678" for e in ents)
    assert not any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_student_cue_keeps_student_id():
    ents = detect_fp("รหัสนักศึกษา 641234567 คณะวิศวกรรมศาสตร์")
    assert any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_student_cue_wins_ten_digit_run_over_bank_account():
    # A 10-digit student id also matches _RE_BANK_ACCOUNT_2, which scores 1.0
    # and needs no cue at all, while STUDENT_ID scores 0.8 and must earn its
    # label -- so a cue-backed student id lost to a cue-free bank account every
    # time. Measured on the gold set: 0 of 8 ten-digit ids kept their type.
    ents = detect_fp("รหัสประจำตัวนักศึกษา 6601552089 สาขาวิชาเคมี")
    assert any(e.data_type == "STUDENT_ID" and e.original_text == "6601552089" for e in ents)
    assert not any(e.data_type == "BANK_ACCOUNT" for e in ents)


def test_fp_bank_cue_nearer_the_number_still_wins_over_a_student_cue():
    # Same rule as BANK vs PHONE: the cue nearest the number decides, so a
    # student's actual bank account stays a bank account.
    ents = detect_fp("นักศึกษาแจ้งบัญชีธนาคารเลขที่ 6601552089 เพื่อรับทุน")
    assert any(e.data_type == "BANK_ACCOUNT" and e.original_text == "6601552089" for e in ents)
    assert not any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_ten_digit_run_without_a_student_cue_stays_bank_account():
    ents = detect_fp("โอนเข้าเลขที่ 6601552089 ภายในวันนี้")
    assert any(e.data_type == "BANK_ACCOUNT" and e.original_text == "6601552089" for e in ents)
    assert not any(e.data_type == "STUDENT_ID" for e in ents)


def test_fp_pupil_and_learner_cues_keep_student_id():
    # นักเรียน / ผู้เรียน mean the same enrolment number as นักศึกษา; without
    # them these fell through to the generic ID_NUMBER.
    for text, value in (
        ("เลขประจำตัวนักเรียน 69200315 ชั้นมัธยมศึกษาปีที่ 4", "69200315"),
        ("หมายเลขประจำตัวผู้เรียน 66033027 หลักสูตรระยะสั้น", "66033027"),
    ):
        ents = detect_fp(text)
        assert any(e.data_type == "STUDENT_ID" and e.original_text == value for e in ents), text


def test_fp_non_person_code_cues_do_not_become_student_id():
    # The cue list must stay about people. "รหัส" alone labels product codes,
    # course codes and curriculum codes too -- those stay the honest ID_NUMBER,
    # which still masks them.
    for text in (
        "รหัสสินค้า 88910423 ราคาต่อหน่วย 1,290 บาท",
        "รหัสหลักสูตร 25620141 ระดับปริญญาตรี",
    ):
        ents = detect_fp(text)
        assert not any(e.data_type == "STUDENT_ID" for e in ents), text


def test_fp_nearer_order_or_price_cue_wins_id_number_over_a_bare_student_word():
    # Reviewer finding (PR #79): a bare person-word ("นักเรียน"/"นิสิต") is weak
    # evidence for STUDENT_ID -- these three are plainly an order number and a
    # price/refund amount in a sentence that happens to mention a pupil. Same
    # nearest-cue-wins rule as _disambiguate_bank_phone and
    # _disambiguate_bank_student above: whichever cue sits closer to the digits
    # decides what they are.
    for text in (
        "นักเรียนสั่งซื้อสินค้ารหัส 88910423",
        "นิสิตชั้นปีที่ 3 ซื้อของราคา 88910423 บาท",
        "นักเรียนได้รับเงินคืน ยอด 88910423 บาท",
    ):
        ents = detect_fp(text)
        assert any(e.data_type == "ID_NUMBER" and e.original_text == "88910423" for e in ents), text
        assert not any(e.data_type == "STUDENT_ID" for e in ents), text


def test_fp_student_cue_with_no_nearer_competing_cue_stays_student_id():
    # Genuine student ids must not regress: no order/price cue sits between
    # the student cue and the digits, so the student cue still wins.
    for text, value in (
        ("รหัสนักศึกษา 64010812 เข้าเรียน", "64010812"),
        ("นักศึกษา 65021178 ลงทะเบียนแล้ว", "65021178"),
        ("ผู้เรียนรหัส 66010334 ส่งงาน", "66010334"),
    ):
        ents = detect_fp(text)
        assert any(e.data_type == "STUDENT_ID" and e.original_text == value for e in ents), text


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


def test_tb_account_number_label_is_not_an_address_cue(monkeypatch):
    """`เลขที่บัญชี` (account number) must not upgrade a span to ADDRESS.

    The address cue `เลขที่` also sits inside compounds that mean "the number
    of <a thing>", so it fired on the account-number label and the label got
    replaced with a fake street address. That surrogate then landed beside
    other surrogates, the NER drew one wide ADDRESS span across them, and the
    pre-send guard halted a perfectly clean prompt (an intermittent
    PreSendValidationError in the pipeline roundtrip, salt-dependent).
    """
    text = "เลขที่บัญชี 123-4-56789-0 เบอร์โทร 086-111-2233"
    ents = _fake_ner_detect(text, [("เลขที่บัญชี", "B-LOCATION")], monkeypatch)
    assert not any(e.data_type == "ADDRESS" for e in ents)


def test_tb_real_address_still_upgrades_after_the_compound_guard(monkeypatch):
    """The guard must not cost a real `เลขที่`-cued address its ADDRESS label."""
    text = "ที่อยู่ เลขที่ 26 ซอยสาทร 5 เขตสาทร กรุงเทพ"
    ents = _fake_ner_detect(text, [("เขตสาทร", "B-LOCATION")], monkeypatch)
    assert any(e.data_type == "ADDRESS" for e in ents)


def test_tb_date_with_birth_cue_upgrades_to_dob(monkeypatch):
    text = "เกิดวันที่ 12 พฤษภาคม 2530 ที่กรุงเทพ"
    ents = _fake_ner_detect(text, [("12 พฤษภาคม 2530", "B-DATE")], monkeypatch)
    assert any(e.data_type == "DATE_OF_BIRTH" for e in ents)


def test_tb_ner_failure_is_logged_not_silent(monkeypatch, caplog):
    """A NER engine that raises must not silently swallow a whole chunk of
    text — the failure has to be logged so missed PII is observable. Called
    bare on purpose: the diagnostics-free default is the path every
    production caller (server, worker, pipeline, receipt, leak_guard) runs."""
    import logging

    import pii_redactor.detectors.tb_detector as tbd

    secret = "SYNTHETIC-PII-DO-NOT-LOG"

    class BoomNER:
        def tag(self, chunk):
            raise RuntimeError(secret)

    monkeypatch.setitem(tbd._ner_cache, "thainer", BoomNER())
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    with caplog.at_level(logging.WARNING, logger="pii_redactor.detectors.tb_detector"):
        # must not raise — detection degrades, does not crash
        tbd.detect_tb("วันนี้อากาศดีมากเลยครับ ไปเที่ยวกันเถอะ")
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "NER" in joined
    assert secret not in joined


def test_tb_ner_failure_counts_into_diagnostics(monkeypatch, caplog):
    """Same failure with a diagnostics object attached: counted as skipped,
    and the exception message still never reaches the log."""
    import logging

    import pii_redactor.detectors.tb_detector as tbd

    secret = "SYNTHETIC-PII-DO-NOT-LOG"

    class BoomNER:
        def tag(self, chunk):
            raise RuntimeError(secret)

    monkeypatch.setitem(tbd._ner_cache, "thainer", BoomNER())
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    with caplog.at_level(logging.WARNING, logger="pii_redactor.detectors.tb_detector"):
        diagnostics = tbd.NERChunkDiagnostics()
        tbd.detect_tb("วันนี้อากาศดีมากเลยครับ ไปเที่ยวกันเถอะ", diagnostics=diagnostics)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in joined
    assert diagnostics.as_dict() == {"attempted": 1, "succeeded": 0, "skipped": 1}


def test_tb_chunk_diagnostics_count_success_without_global_state(monkeypatch):
    import pii_redactor.detectors.tb_detector as tbd

    class EmptyNER:
        def tag(self, chunk):
            return []

    monkeypatch.setitem(tbd._ner_cache, "thainer", EmptyNER())
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "thainer")
    first = tbd.NERChunkDiagnostics()
    second = tbd.NERChunkDiagnostics()

    tbd.detect_tb("วันนี้อากาศดี", diagnostics=first)
    tbd.detect_tb("พรุ่งนี้อากาศดี", diagnostics=second)

    assert first.as_dict() == {"attempted": 1, "succeeded": 1, "skipped": 0}
    assert second.as_dict() == {"attempted": 1, "succeeded": 1, "skipped": 0}


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
    ents = _fake_ner_detect(text, [("บริษัท เอบีซี จำกัด", "B-ORGANIZATION")], monkeypatch)
    assert any(e.data_type == "ORGANIZATION" for e in ents)
