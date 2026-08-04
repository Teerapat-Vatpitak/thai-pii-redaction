"""Recall regressions the 2026-08-04 adversarial review found against base.

Every catch below is a verbatim reviewer sentence that base (20a9a1d) masked
and this branch's precision work left in the clear -- the direction the
repository's prime invariant (recall > precision) forbids. Grouped by
mechanism: the new-format plate's leading-digit re-attach lost dedupe to the
junk candidate that had eaten the same digit; a glued gender qualifier vetoed
the whole ผู้ป่วย role cue instead of being skipped; the ผู้ nominalizer
carve-out ate a given name newmm had glued into the role group; a facility
LOCATION was dropped on ABSENCE of neighbours rather than on positive
facilities-register evidence; the head-trim lexicon used _LEAD_STOP (a list of
words that never START a name in prose) to UNMASK an attested given name; the
head segment was truncated at its first digit run and only the PREFIX kept, so
a numbered roster line lost the person; and the passport-adjacency gate judged
a compound surname by its leading newmm token alone.

All values fabricated. Each control below pins the precision boundary the
original finding was written against, so a fix cannot be a plain revert.
"""

from __future__ import annotations

import pytest

import pii_redactor.detectors.tb_detector as tbd
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.name_context import detect_name_context


def _covered(text: str, value: str) -> bool:
    """True when detect_all's spans cover every character of ``value``."""
    lo = text.index(value)
    hi = lo + len(value)
    cur = lo
    for s, e in sorted(e.span for e in detect_all(text) if e.span[0] < hi and e.span[1] > lo):
        if s > cur:
            return False
        cur = max(cur, e)
    return cur >= hi


def _ctx_names(text: str) -> set[str]:
    return {e.original_text for e in detect_name_context(text)}


# ── 1. the re-attached new-format plate must win dedupe ────────────────────


@pytest.mark.parametrize(
    ("text", "plate"),
    [
        ("รถ 2กท 8899 ของนายสมชาย ใจดี", "2กท 8899"),
        ("จยย 2กท 8899 หายจากหน้าบ้าน", "2กท 8899"),
        ("รถ 1กก 1234 ทะเบียนกรุงเทพ", "1กก 1234"),
        ("รถ 2กท8899 ของผม", "2กท8899"),
        ("รถ 2กท 8899 และ รถ 3ขข 4567", "2กท 8899"),
        ("รถ 2กท 8899 และ รถ 3ขข 4567", "3ขข 4567"),
    ],
)
def test_leading_digit_plate_is_not_evicted_by_the_junk_candidate(text, plate):
    # The junk candidate ("รถ 2") ends ON the digit the real plate re-attaches,
    # so the two overlap; at equal score _deduplicate's earlier-start tiebreak
    # kept the junk one and the registration shipped unmasked.
    assert _covered(text, plate), (text, [(e.data_type, e.original_text) for e in detect_all(text)])


def test_plate_uncued_word_lead_and_amount_guards_still_hold():
    # Documented precision trades that must survive the re-attach fix.
    for text in ("ยอด 2,500 บาท", "ออก 17.40 น.", "รวม 1,200 บาท"):
        assert not any(e.data_type == "VEHICLE_PLATE" for e in detect_all(text)), text


# ── 2. a glued gender qualifier is skipped, not a veto on the whole cue ────


def test_patient_gender_qualifier_still_yields_the_patient_name():
    text = "ผู้ป่วยชาย ธงชัย รักถิ่น เข้ารับการรักษา"
    # The CRF carries no PERSON span here, so vetoing the cue on หญิง/ชาย left
    # the whole name in the clear.
    assert _covered(text, "ธงชัย รักถิ่น"), [(e.data_type, e.original_text) for e in detect_all(text)]


def test_gender_qualifier_never_becomes_the_first_name():
    # The B6 boundary the veto was written for: หญิง/ชาย stay OUT of the span.
    for text in (
        "ผู้ป่วยหญิง รัตนา แสงวิเชียร อายุ 52 ปี มาพบแพทย์ตามนัด",
        "ผู้ป่วยชาย สมบูรณ์ ทรงศิริ เข้ารับการตรวจตามนัด",
    ):
        names = _ctx_names(text)
        assert not any(n.startswith(("หญิง", "ชาย")) for n in names), (text, names)


def test_patient_prose_continuations_still_yield_nothing():
    for text in ("ผู้ป่วยนอก ห้องตรวจ 3", "ผู้ป่วยเรื้อรัง ทุกราย ต้องลงทะเบียน"):
        assert _ctx_names(text) == set(), (text, _ctx_names(text))


def test_skipped_qualifier_must_buy_two_real_groups():
    # The qualifier is left unmasked, so a single-group fallback must not turn
    # the next prose word into a person.
    names = _ctx_names("ผู้ป่วยหญิง อายุ 52 ปี มาตามนัด")
    assert names == set(), names


# ── 3. the ผู้ carve-out must not eat a glued given name ───────────────────


def test_glued_role_compound_keeps_the_given_name():
    # newmm splits ผู้ค้ำสมศรี into ผู้|ค้ำ|สม|ศรี, so consuming the whole
    # space group took the given name with the role word.
    text = "ผู้ค้ำสมศรี ใจงาม ลงลายมือชื่อ"
    assert _covered(text, "สมศรี ใจงาม"), [(e.data_type, e.original_text) for e in detect_all(text)]


def test_split_role_compounds_are_still_trimmed_whole():
    # The B1 rows the carve-out exists for: when the group IS the compound,
    # the whole group still goes.
    from pii_redactor.detectors.name_context import trim_same_line_name_edges

    for seg, expected in (
        ("ผู้รับเงิน สมชาย ใจดี", "สมชาย ใจดี"),
        ("ผู้ให้เช่า บุญส่ง วรรณโภคิน", "บุญส่ง วรรณโภคิน"),
    ):
        lo, hi = trim_same_line_name_edges(seg)
        assert seg[lo:hi] == expected, seg


# ── 4. a facility span is dropped on positive register evidence only ──────


def test_delivery_address_facility_stays_masked():
    text = "ส่งเอกสารมาที่ อาคาร 7 ชั้น 3"
    # A short delivery line carries no booking/meeting register, so absence of
    # neighbouring entities is not evidence that the building is furniture.
    assert _covered(text, "อาคาร 7"), [(e.data_type, e.original_text) for e in detect_all(text)]


def test_bookable_meeting_room_notice_stays_closed():
    # ng19 verbatim (gold negative slice): ความจุ / ที่นั่ง / จอง ARE the
    # facilities register, so the three spans are still dropped.
    text = "ห้องประชุม 1204 อาคาร 7 ชั้น 12 ความจุ 80 ที่นั่ง จองผ่านระบบล่วงหน้า 3 วัน"
    assert not any(e.data_type == "LOCATION" for e in detect_all(text)), [
        (e.data_type, e.original_text) for e in detect_all(text)
    ]


# ── 5. _LEAD_STOP must not be used to UNMASK an attested given name ────────


def test_lead_stop_word_that_is_a_real_given_name_stays_masked():
    text = "พยาน 2 คน คือ ประสงค์ ดีงาม สมศรี ใจดี"
    # "never STARTS a name in prose" is not "never IS a name" -- ประสงค์ is an
    # attested Thai given name and the head trim unmasked it.
    assert _covered(text, "ประสงค์ ดีงาม"), [(e.data_type, e.original_text) for e in detect_all(text)]


def test_role_and_label_head_trims_are_unaffected():
    from pii_redactor.detectors.name_context import trim_same_line_name_edges

    for seg, expected in (
        ("ผู้จัดการฝ่ายขาย วิชัย ประสงค์ดี", "วิชัย ประสงค์ดี"),
        ("ผู้ค้ำประกัน ดารณี สินสมบัติ", "ดารณี สินสมบัติ"),
        ("ตำแหน่ง อรุณี วัฒนสิทธิ์", "อรุณี วัฒนสิทธิ์"),
    ):
        lo, hi = trim_same_line_name_edges(seg)
        assert seg[lo:hi] == expected, seg


# ── 6. the head digit split must evaluate BOTH sides ──────────────────────


@pytest.mark.parametrize(
    ("entity_text", "name"),
    [
        ("1. สมชาย ใจดี", "สมชาย ใจดี"),
        ("2 สมชาย ใจดี", "สมชาย ใจดี"),
        ("15 สมชาย ใจดี", "สมชาย ใจดี"),
        ("ม.6/2 ศิริพร นาคสุข", "ศิริพร นาคสุข"),
        ("ลำดับ 3 กิตติ พรดี", "กิตติ พรดี"),
    ],
)
def test_numbered_roster_line_keeps_the_person(entity_text, name):
    # Truncating the head at the first digit run and keeping only the PREFIX
    # dropped every line whose number comes before the name.
    spans = tbd._name_hygiene(entity_text, 0, len(entity_text))
    covered = [entity_text[s:e] for s, e in spans]
    assert any(name in seg for seg in covered), (entity_text, covered)


def test_digit_split_still_keeps_a_glued_account_number_out():
    # fn10 class: the digits (and anything the FP patterns claim on their own)
    # must stay outside every NAME segment.
    entity_text = "บัญชี ศักดิ์ชัย รุ่งอรุณ เลขบัญชี8807123456"
    spans = tbd._name_hygiene(entity_text, 0, len(entity_text))
    assert [entity_text[s:e] for s, e in spans] == ["ศักดิ์ชัย รุ่งอรุณ"], spans


# ── 7. passport adjacency: a label must BE the group, not lead it ─────────


def test_compound_surname_before_a_passport_survives():
    text = "รายา บัตรทอง AC1112223"
    # บัตรทอง newmm-splits onto the label token บัตร; a prefix hit is not
    # evidence, the same rule trim_same_line_name_edges already documents.
    assert _covered(text, "รายา บัตรทอง"), [(e.data_type, e.original_text) for e in detect_all(text)]


def test_passport_adjacent_field_labels_are_still_rejected():
    for text, junk in (
        (
            "บันทึกการตรวจลงตราเข้าเมือง หมายเลขหนังสือเดินทาง VE5443322 วันเกิดผู้ถือหนังสือเดินทาง 12/06/2529",
            "หมายเลขหนังสือเดินทาง",
        ),
        (
            "แบบคำขอต่ออายุหนังสือเดินทาง เลขที่เล่มเดิม BY7846353 ผู้ถือ สุทธิดา วรกิตติ์",
            "เลขที่เล่มเดิม",
        ),
    ):
        assert not any(junk in n for n in _ctx_names(text)), (text, _ctx_names(text))


# ── 8. a document compound at the head must not drop the name behind it ────


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("รายชื่อ สมชาย ใจดี", "สมชาย ใจดี"),
        ("ขอบคุณ ปิยะพงษ์ วราภรณ์", "ปิยะพงษ์ วราภรณ์"),
        ("รายชื่อ ทศพล เกียรติขจร ได้รับอนุมัติแล้ว", "ทศพล เกียรติขจร"),
    ],
)
def test_compound_label_keeps_the_name_it_introduces(text, name):
    assert _covered(text, name), (text, [e.original_text for e in detect_all(text)])


@pytest.mark.parametrize(
    "header",
    [
        "รายชื่อนักศึกษาฝึกงาน ประจำภาคฤดูร้อน",
        "แบบประเมินการฝึกสอนของนักศึกษาครู",
        "สัญญาเช่ารถยนต์",
        "ขอบคุณมา ณ โอกาสนี้",
        "ตารางสอบปลายภาค วันจันทร์",
    ],
)
def test_glued_compound_headers_stay_dropped(header):
    """A compound GLUED to what follows is one header phrase, not a label plus
    a name -- the measured gold false positives all have this shape."""
    assert tbd._name_hygiene(header, 0, len(header)) == []


# ── 9. a label on its own OCR line still vouches for the name below it ─────


def test_direct_cue_survives_a_line_break_before_the_name():
    text = "ข้าพเจ้า\nวิชัย ประสงค์ดี\nขอรับรองว่าข้อความข้างต้นเป็นความจริง\n"
    assert _covered(text, "วิชัย ประสงค์ดี"), [e.original_text for e in detect_all(text)]


def test_glued_direct_cue_is_still_not_a_name():
    assert detect_all("ข้าพเจ้าขอแสดงความนับถือ") == []


# ── 10. blocking ทะเบียนบ้าน as a plate cue must not orphan the house number ─


def test_house_registration_number_keeps_a_claim():
    text = "ทะเบียนบ้าน 203 หมู่ 4 ตำบลบางพระ อำเภอศรีราชา ชลบุรี"
    assert _covered(text, "203"), [e.original_text for e in detect_all(text)]


# ── 11. a fee word glued to a real organization keeps the organization ─────


@pytest.mark.parametrize(
    "text",
    ["ค่าจ้างบริษัท เอบีซี จำกัด", "ค่าธรรมเนียมธนาคารกสิกรไทย 50 บาท"],
)
def test_fee_prefix_does_not_delete_a_real_organization(text):
    assert any(e.data_type == "ORGANIZATION" for e in detect_all(text)), text


def test_bare_fee_label_is_still_dropped():
    text = "ค่าธรรมเนียมการศึกษาภาคปกติ 18,500 บาทต่อภาคการศึกษา"
    assert all(e.data_type != "ORGANIZATION" for e in detect_all(text))


# ── 12. EMAIL lookaround must not absorb leading punctuation ───────────────


def test_email_span_starts_at_the_local_part():
    from pii_redactor.detectors.fp_detector import detect_fp

    got = {e.original_text for e in detect_fp("..a@b.co และ manop.d@example.com")}
    assert "manop.d@example.com" in got
    assert not any(v.startswith((".", "-")) for v in got), got
