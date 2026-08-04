"""Address chain head/tail mechanisms and boundary fixes (2026-08-03 wave).

Every catch below reproduces a measured gold-v4 failure: address chains that
start late (single-digit house/moo numbers dying at the 2-char floor, house
numbers behind non-adjacent labels, estate names no pattern captured), chains
that end early (bare province tails living only in dedupe-dropped CRF spans),
admin-area labels matched inside compound prose words, a Thai-month birth date
with the year unmasked, plate left-edge defects, an email clipped at a glued
Thai label, and bare facility designators (ห้องประชุม 1204) masked in a
facilities notice with no person in sight.

The controls pin the recall boundary each fix must not move: every sentence
here that detected something before the fix must still detect it after.
"""

from __future__ import annotations

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.fp_detector import detect_fp


def _addresses(ents):
    return [e for e in ents if e.data_type == "ADDRESS"]


def _one_address_covering(text: str, first: str, last: str):
    """Assert a single ADDRESS entity spans from `first` through `last`."""
    lo = text.index(first)
    hi = text.index(last) + len(last)
    ents = detect_all(text)
    for a, b in zip(ents, ents[1:]):  # dedupe invariant must survive the new passes
        assert a.span[1] <= b.span[0], (a.span, b.span)
    hits = [e for e in _addresses(ents) if e.span[0] <= lo and hi <= e.span[1]]
    assert hits, [(e.data_type, e.span, e.original_text) for e in ents]
    return hits[0]


def _fp_types_at(text: str, value: str) -> set[str]:
    lo = text.index(value)
    hi = lo + len(value)
    return {e.data_type for e in detect_fp(text) if e.span[0] < hi and lo < e.span[1]}


# ── admin-area label inside a compound word (FP-gf02, FP-lf10) ─────────────


def test_khet_phuenthi_kansuksa_is_not_an_address():
    # สำนักงานเขตพื้นที่การศึกษา is a government agency name; เขต inside it
    # must not seed an ADDRESS fragment.
    ents = detect_fp("คำสั่งสำนักงานเขตพื้นที่การศึกษา ที่ 118/2569")
    assert not _addresses(ents), [(e.span, e.original_text) for e in ents]


def test_real_khet_district_still_detected():
    assert "ADDRESS" in _fp_types_at("บ้านอยู่เขตบางกะปิ กรุงเทพมหานคร", "บางกะปิ")


def test_glued_province_label_does_not_capture_across_newline():
    # 'ต่างจังหวัด' ends a line; the next line's first word is a meeting
    # agenda header, not a province.
    ents = detect_fp("ติดภารกิจราชการต่างจังหวัด\nวาระที่ 1 เรื่องแจ้งเพื่อทราบ")
    assert not _addresses(ents), [(e.span, e.original_text) for e in ents]


def test_glued_province_label_same_line_still_captures():
    assert "ADDRESS" in _fp_types_at("ย้ายไปทำงานต่างจังหวัด ขอนแก่น", "ขอนแก่น")


def test_form_label_on_its_own_line_still_captures():
    # Forms put the label and value on separate lines; only a label glued to
    # prose loses the right to cross a newline.
    assert "ADDRESS" in _fp_types_at("จังหวัด\nเชียงใหม่ รหัสไปรษณีย์ 50200", "เชียงใหม่")


# ── single-digit house/moo numbers (COV-ad04, B8-ii) ───────────────────────


def test_single_digit_house_and_moo_join_the_chain():
    text = "ภูมิลำเนาเดิม บ้านเลขที่ 7 หมู่ที่ 9 ต.แม่เหียะ อ.เมือง จ.เชียงใหม่"
    _one_address_covering(text, "7 หมู่ที่ 9", "เชียงใหม่")


def test_single_digit_exemption_needs_the_exact_labels():
    # เลขที่/ที่อยู่ alone and the ม. abbreviation stay under the 2-char floor.
    for text in ("ใบเสร็จเลขที่ 7", "นักเรียนชั้น ม.5", "ผู้เช่าที่อยู่ 5 ปีแล้ว"):
        assert not _addresses(detect_fp(text)), text


def test_single_digit_moo_without_sibling_stays_dropped():
    # A military หมู่ with no address component nearby is not an address.
    assert not _addresses(detect_fp("ทหารหมู่ 5 กองร้อยที่ 2"))


# ── house numbers behind wider labels and slash-form before a building ─────


def test_current_address_label_reaches_the_house_number():
    text = "ที่อยู่ปัจจุบัน 88 หมู่บ้านสวนหลวง ซอย 4 ตำบลหนองปรือ อำเภอบางละมุง ชลบุรี 20150"
    _one_address_covering(text, "88", "20150")


def test_slash_house_number_before_condo_joins_the_chain():
    text = "โปรดจัดส่งเอกสารมายัง 123/456 คอนโดริเวอร์ไซด์ ชั้น 12 ถนนเจริญนคร คลองต้นไทร คลองสาน กรุงเทพฯ"
    _one_address_covering(text, "123/456", "คลองสาน")


def test_bare_count_before_village_word_is_not_a_house_number():
    # "88 หมู่บ้าน" as a quantity: the building lookahead is slash-form only.
    ents = detect_fp("โครงการครอบคลุมจำนวน 88 หมู่บ้านในตำบลแม่แฝก")
    assert not any(e.original_text == "88" for e in _addresses(ents))


# ── estate names and label-only gaps (COV-ad09, COV-ad10, FP-lf13) ─────────


def test_moo_village_label_gap_chain():
    text = "ที่ทำการไปรษณีย์ปลายทาง หมู่ 5 บ้านโนนสูง ตำบลในเมือง อำเภอเมือง จังหวัดนครราชสีมา 30000"
    _one_address_covering(text, "5 บ้านโนนสูง", "30000")


def test_industrial_estate_name_joins_the_chain():
    text = "โรงงานตั้งอยู่ที่ นิคมอุตสาหกรรมอมตะนคร 700/1 หมู่ 6 ตำบลดอนหัวฬ่อ อำเภอเมือง ชลบุรี"
    _one_address_covering(text, "อมตะนคร", "ชลบุรี")


def test_estate_chain_with_labelled_house_number():
    text = "สถานที่อบรม เลขที่ 88 นิคมอุตสาหกรรมตัวอย่าง หมู่ 5 ตำบลมาบตาพุด อำเภอเมืองระยอง ระยอง 21150"
    _one_address_covering(text, "88", "21150")


def test_ieat_agency_name_is_not_an_estate_value():
    # การนิคมอุตสาหกรรมแห่งประเทศไทย is the state agency, not an estate name.
    ents = detect_fp("หนังสือจากการนิคมอุตสาหกรรมแห่งประเทศไทยเรื่องค่าบริการ")
    assert not _addresses(ents), [(e.span, e.original_text) for e in ents]


# ── bare province tails and dropped CRF spans (FP-ad08, COV-ad13, B9) ──────


def test_label_less_khwaeng_gap_is_absorbed():
    text = "ส่งใบแจ้งหนี้ไปที่ 55/1 ถนนสุขุมวิท ซอย 24 คลองตัน คลองเตย กรุงเทพมหานคร"
    _one_address_covering(text, "55/1", "กรุงเทพมหานคร")


def test_bare_province_tail_joins_the_chain():
    text = "ร้านตั้งอยู่ เลขที่ 15 ตลาดสดเทศบาล ถนนศรีจันทร์ อำเภอเมือง ขอนแก่น"
    _one_address_covering(text, "15", "ขอนแก่น")


def test_gazetteer_province_needs_an_adjacent_admin_fragment():
    # A branch name and a lone postcode: no admin-area fragment in front, so
    # the province gazetteer must not fire and the code stays unclaimed.
    ents = detect_fp("สาขาชลบุรี 20150 โทร 021234567")
    assert not _addresses(ents)
    assert not any(e.data_type == "POSTAL_CODE" for e in ents)


def test_gazetteer_province_after_admin_fragment_fires():
    assert "ADDRESS" in _fp_types_at("อยู่ที่ตำบลบางพระ ชลบุรี", "ชลบุรี")


def test_gazetteer_is_the_complete_fixed_national_list():
    from pii_redactor.detectors.fp_detector import _PROVINCES

    assert len(set(_PROVINCES)) == 77


def test_postal_code_merges_backward_across_one_bare_token():
    # กทม is not in the gazetteer; the postal code still merges backward
    # across exactly one bare Thai token.
    text = "ที่อยู่ 45/12 ถนนงามวงศ์วาน แขวงทุ่งสองห้อง เขตหลักสี่ กทม 10210"
    _one_address_covering(text, "45/12", "10210")


def test_union_extension_never_swallows_a_name():
    text = "ที่อยู่ 99/1 ถนนสุขุมวิท แขวงคลองเตย กรุงเทพฯ ผู้ขาย นายสมชาย ใจดี"
    ents = detect_all(text)
    lo = text.index("นายสมชาย ใจดี")
    hi = lo + len("นายสมชาย ใจดี")
    names = [e for e in ents if e.data_type == "NAME" and e.span[0] < hi and lo < e.span[1]]
    assert names, [(e.data_type, e.span, e.original_text) for e in ents]
    for a in _addresses(ents):
        assert a.span[1] <= lo or hi <= a.span[0], (a.span, a.original_text)


# ── Thai-month dates (B10) ─────────────────────────────────────────────────


def test_thai_month_birth_date_includes_the_year():
    ents = detect_fp("เลขบัตรประชาชน 5398925384963 วันเกิด 16 สิงหาคม 2508")
    dob = [e for e in ents if e.data_type == "DATE_OF_BIRTH"]
    assert [e.original_text for e in dob] == ["16 สิงหาคม 2508"], dob


def test_thai_month_date_without_birth_cue_stays_date():
    ents = detect_fp("นัดตรวจ ในวันที่ 30 กันยายน 2569")
    assert [e.data_type for e in ents] == ["DATE"], ents
    assert ents[0].original_text == "30 กันยายน 2569"


def test_thai_month_pattern_needs_day_and_year():
    # No day is a month reference; no year is a period endpoint (ng40 gained a
    # negative-slice FP when the year was optional); no month is a standard
    # designation.
    assert not detect_fp("ประกาศเดือนกันยายน 2568")
    assert not detect_fp("มาตรฐาน มอก. 2540-2555")
    assert not detect_fp("ระหว่างวันที่ 1 เมษายน ถึงปลายปี")


def test_thai_month_pattern_rejects_impossible_days():
    ents = detect_fp("ห้อง 45 สิงหาคม 2569")
    assert not any(e.data_type in ("DATE", "DATE_OF_BIRTH") for e in ents)


# ── plate left edge (B11, B12) ─────────────────────────────────────────────


def test_glued_plate_cue_tail_consonant_is_trimmed():
    ents = detect_fp("ทะเบียนรถขก 4471จอดในลานจอด B2")
    plates = [e.original_text for e in ents if e.data_type == "VEHICLE_PLATE"]
    assert plates == ["ขก 4471"], plates


def test_new_format_plate_keeps_its_leading_digit():
    ents = detect_fp("รถที่ใช้ทะเบียน 2กท 8899")
    plates = [e.original_text for e in ents if e.data_type == "VEHICLE_PLATE"]
    assert plates == ["2กท 8899"], plates


def test_uncued_new_format_plate_detected():
    ents = detect_fp("รถเก๋ง 1กก 1234 เฉี่ยวชนแล้วหลบหนี")
    plates = [e.original_text for e in ents if e.data_type == "VEHICLE_PLATE"]
    assert plates == ["1กก 1234"], plates


def test_glued_date_abbreviation_is_not_a_plate():
    ents = detect_fp("วันที่ 25กค 2569")
    assert not any(e.data_type == "VEHICLE_PLATE" for e in ents)


# ── email boundaries vs Thai script (B13) ──────────────────────────────────


def test_email_glued_to_thai_label_keeps_its_local_part():
    ents = detect_fp("ผู้ติดต่อมานพ ดีเลิศเบอร์0891234567อีเมลmanop.d@example.com")
    emails = [e.original_text for e in ents if e.data_type == "EMAIL"]
    assert emails == ["manop.d@example.com"], emails


def test_email_boundary_controls_keep_matching():
    for text in (
        "อีเมล somchai@example.com ครับ",
        "ส่งมาที่ somchai@example.com. ขอบคุณ",  # sentence-final period
        "อีเมลsomchai@example.comครับ",  # Thai glued both sides
    ):
        emails = [e.original_text for e in detect_fp(text) if e.data_type == "EMAIL"]
        assert emails == ["somchai@example.com"], (text, emails)


def test_email_glued_to_ascii_code_prefix_captures_the_token():
    emails = [e.original_text for e in detect_fp("รหัสid12@example.com") if e.data_type == "EMAIL"]
    assert emails == ["id12@example.com"], emails


# ── bare facility designators (ng19) ───────────────────────────────────────


def _covered(ents, text: str, value: str) -> bool:
    lo = text.index(value)
    hi = lo + len(value)
    return any(e.span[0] <= lo and hi <= e.span[1] for e in ents)


def test_bookable_meeting_room_notice_yields_no_entities():
    text = "ห้องประชุม 1204 อาคาร 7 ชั้น 12 ความจุ 80 ที่นั่ง จองผ่านระบบล่วงหน้า 3 วัน"
    ents = detect_all(text)
    assert not any(e.data_type == "LOCATION" for e in ents), [
        (e.data_type, e.original_text) for e in ents
    ]


def test_building_first_address_keeps_its_facility_span():
    text = "อาคาร 7 ชั้น 12 ถนนพหลโยธิน แขวงจตุจักร กรุงเทพมหานคร 10900"
    assert _covered(detect_all(text), text, "อาคาร 7")


def test_patient_building_beside_a_hospital_stays_masked():
    text = "ผู้ป่วยพักรักษาตัวที่ตึก 84 ปี ชั้น 5 โรงพยาบาลศิริราช"
    assert _covered(detect_all(text), text, "ตึก 84")


def test_facility_span_beside_a_person_stays_masked():
    text = "คุณสมชาย ใจดี อยู่ชั้น 12 อาคาร 7 ติดต่อเบอร์ 081-234-5678"
    assert _covered(detect_all(text), text, "อาคาร 7")
