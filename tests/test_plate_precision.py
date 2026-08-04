"""VEHICLE_PLATE precision: registration compounds and prose word-leads.

Every catch below is a verbatim false positive from the 2026-08-04 weakness
inventory (gold docs gf05/lf01/fn10/id13/id17/lf20 — precision 0.781, 7 FPs in
two mechanisms): the plate cue ทะเบียน matching inside civil-registration
compounds (ทะเบียนบ้าน/ทะเบียนสมรส), where it relaxed the mid-word guard and
turned house numbers into plates; and the all-consonant prose words ยอด/ออก/รวม
satisfying [ก-ฮ]{1,3} before an amount, a clock time, or a copy count. All
values fabricated.

The controls pin the recall boundary: an explicit (unblocked) plate cue always
wins — over the word-lead stopwords, over the digit-continuation guard, and
past an adjacent blocked compound — and the parking-log document keeps every
real plate while losing its exit times.
"""

from __future__ import annotations

from pii_redactor.detectors.fp_detector import detect_fp


def _plates(text: str) -> set[str]:
    return {e.original_text for e in detect_fp(text) if e.data_type == "VEHICLE_PLATE"}


# ── A. ทะเบียน continued by a civil-registration word is not a plate cue ───


def test_house_registration_number_is_not_a_plate():
    for text in (
        "ที่อยู่ตามทะเบียนบ้าน 203 หมู่ 8 ตำบลท่าช้าง อำเภอบางกล่ำ จังหวัดสงขลา 90110",
        "ที่อยู่ตามทะเบียนบ้าน 61/7 หมู่ 3 ตำบลบางแก้ว อำเภอบางพลี จังหวัดสมุทรปราการ",
    ):
        assert _plates(text) == set(), (text, _plates(text))


def test_other_civil_registration_compounds_do_not_cue():
    assert _plates("จดทะเบียนสมรส 447 เมื่อปีที่แล้ว") == set()
    assert _plates("คัดสำเนาทะเบียนราษฎร 5088 จากสำนักงานเขต") == set()


def test_unblocked_cue_beside_a_blocked_compound_still_wins():
    # A second, unblocked ทะเบียนรถ occurrence in the window cues the plate
    # even with ทะเบียนบ้าน sitting in the same sentence.
    text = "ถ่ายสำเนาทะเบียนบ้านและแจ้งทะเบียนรถ กข 1234 กับตำรวจ"
    assert "กข 1234" in _plates(text)


def test_cued_ministry_code_plate_unchanged():
    # กค is a ministry doc code AND a legal plate prefix; the cue decides.
    assert "กค 0409" in _plates("ทะเบียนรถ กค 0409")


# ── B. amounts, times, and counts behind ยอด/ออก/รวม are not plates ────────


def test_amount_after_yod_is_not_a_plate():
    for text in (
        "ชื่อบัญชี ศักดิ์ชัย รุ่งอรุณ เลขบัญชี8807123456 ยอด 2,500 บาท แนบสลิปมาทางอีเมล",
        "ชำระด้วยบัตรเครดิต 4716-0173-0480-6707 ยอด 7,850 บาท",
        "ยอด 500 บาท ชำระปลายทาง",
    ):
        assert _plates(text) == set(), (text, _plates(text))


def test_credit_card_in_the_amount_sentence_is_unaffected():
    text = "ชำระด้วยบัตรเครดิต 4716-0173-0480-6707 ยอด 7,850 บาท"
    assert any(e.data_type == "CREDIT_CARD" for e in detect_fp(text))


def test_parking_log_keeps_real_plates_and_loses_exit_times():
    text = (
        "บันทึกรถเข้าออกอาคาร\n"
        "ทะเบียน ผน 9250 เข้า 08.12 น. ออก 17.40 น.\n"
        "ทะเบียน ซร 5881 เข้า 09.05 น. ออก 12.30 น.\n"
        "ทะเบียน ผท 5094 เข้า 10.22 น. ยังไม่ออก"
    )
    assert _plates(text) == {"ผน 9250", "ซร 5881", "ผท 5094"}


def test_copy_count_after_ruam_is_not_a_plate():
    # No [.,]<digit> continuation here — this instance is what forces the
    # word-lead stopword entry for รวม.
    text = "หนังสือรับรองความประพฤติ และสำเนาใบเสร็จค่าเทอมภาคล่าสุด รวม 3 ฉบับ"
    assert _plates(text) == set()


# ── C. the cue always beats the uncued-only guards ─────────────────────────


def test_cue_beats_word_lead_stopword():
    # A 3-letter motorcycle series can legally spell ยอด; the explicit cue
    # marks it a real plate and the word-lead stop must not fire.
    assert "ยอด 1234" in _plates("รถกระบะทะเบียน ยอด 1234 ขับชนแล้วหนี")


def test_cue_beats_digit_continuation_guard():
    # Cued digits followed by .5 (a price in หมื่นบาท) still detect.
    assert "กข 123" in _plates("ขายรถทะเบียน กข 123.5 หมื่นบาท")
