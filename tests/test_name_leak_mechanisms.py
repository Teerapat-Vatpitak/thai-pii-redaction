"""NAME and DATE_OF_BIRTH leak mechanisms from the 2026-08-04 weakness inventory.

Every catch below is a verbatim gold/inventory case (docs ed06/id06/lf01/lf19/
nc09/gf09/gf14/fn10/id25/lf10/lf20/gf16/ed09/ed11/id02/id09/id15/lf03/lf07 —
NAME 0.945/0.954, DATE_OF_BIRTH recall 0.889), grouped by mechanism: the bare
เกิด cue matching inside เกิดเหตุ, a CRF DATE span that absorbed its own
วันเดือนปีเกิด cue, unknown CRF labels (LAW) silently swallowing multi-line
PII, a digits-glued PERSON span whose whole-span drop unmasked a name (fn10 —
the one full product leak), and cue passes vouching for document titles and
field labels. All values fabricated.

The controls pin the recall boundary named by each finding: incident dates
stay DATE while patient birth dates stay DATE_OF_BIRTH, cue-vetoed prose
yields nothing while cued real names keep detecting, and the real-name traps
(สัญญา ธรรมศักดิ์, แบบบุญมี, ทองอยู่, นาย-titled spans) survive every new
rejection.
"""

from __future__ import annotations

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.models import Entity


def _fp_types(text: str, value: str) -> set[str]:
    lo = text.index(value)
    hi = lo + len(value)
    return {e.data_type for e in detect_fp(text) if e.span[0] < hi and lo < e.span[1]}


def _tb_types(text: str, value: str) -> set[str]:
    lo = text.index(value)
    hi = lo + len(value)
    return {e.data_type for e in detect_tb(text) if e.span[0] < hi and lo < e.span[1]}


def _ctx_names(text: str) -> set[str]:
    return {e.original_text for e in detect_name_context(text)}


def _upgrade(text: str, value: str) -> str | None:
    from pii_redactor.detectors.tb_detector import _apply_cue_upgrades

    lo = text.index(value)
    return _apply_cue_upgrades(text, lo, lo + len(value), "DATE")


def _hygiene_texts(text: str, value: str) -> list[str]:
    from pii_redactor.detectors.tb_detector import _name_hygiene

    lo = text.index(value)
    return [text[s:e] for s, e in _name_hygiene(text, lo, lo + len(value))]


# ── A. birth cue: เกิดเหตุ is an incident, English labels are birth labels ─


def test_incident_date_is_not_a_birthday():
    # lf19 shape on the FP side: เกิด inside เกิดเหตุ/เหตุเกิด cued a fake DOB.
    for text in (
        "วันที่เกิดเหตุ 18/07/2569 บริเวณถนนมิตรภาพ",
        "เหตุเกิดวันที่ 18/07/2569 เวลา 07.45 น.",
    ):
        got = _fp_types(text, "18/07/2569")
        assert "DATE" in got and "DATE_OF_BIRTH" not in got, (text, got)


def test_patient_birth_date_keeps_the_upgrade():
    assert _fp_types("ผู้ป่วยเกิดวันที่ 18/07/2500 รับยาต่อเนื่อง", "18/07/2500") == {"DATE_OF_BIRTH"}


def test_english_birth_labels_cue_the_upgrade():
    # id06: Thai visa/passport paperwork labels the birth date in English.
    text = "แบบฟอร์มขอวีซ่าทำงาน ผู้ยื่น Kanyarat Techasiri passport no. WK4455312 date of birth 22/04/2535 nationality Thai"
    assert "DATE_OF_BIRTH" in _fp_types(text, "22/04/2535")
    assert "DATE_OF_BIRTH" in _fp_types("DOB 22/04/2535", "22/04/2535")


def test_certificate_issue_date_is_not_a_birthday():
    # "birth certificate" carries no birth-date label; the issue date stays DATE.
    got = _fp_types("ออกใบแทน birth certificate เมื่อ 12/05/2560", "12/05/2560")
    assert "DATE" in got and "DATE_OF_BIRTH" not in got, got


# ── B. a CRF DATE span that absorbed the วันเดือนปีเกิด cue (lf01/lf06/lf14) ─


def test_glued_cue_in_span_head_upgrades_to_dob():
    for text, span_value in (
        (
            "เลขประจำตัวประชาชน 2052814287318 วันเดือนปีเกิด 24 มีนาคม 2550",
            "ปีเกิด 24 มีนาคม 2550",
        ),
        (
            "เลขประจำตัวประชาชน 7963450026061\nวันเดือนปีเกิด 11 พฤษภาคม 2508 วันที่เกษียณอายุราชการ",
            "ปีเกิด 11 พฤษภาคม 2508",
        ),
    ):
        assert _upgrade(text, span_value) == "DATE_OF_BIRTH", text


def test_incident_and_retirement_dates_stay_plain_dates():
    # The CRF puts the incident cue OUTSIDE the span, so the head search must
    # not fire there; a retirement date has no cue in window or head at all.
    assert _upgrade("เกิดเหตุวันที่ 20 กรกฎาคม 2569 เวลา 07.45 น.", "20 กรกฎาคม 2569") == "DATE"
    assert _upgrade("เหตุเกิดวันที่ 18 กรกฎาคม 2569", "18 กรกฎาคม 2569") == "DATE"
    assert _upgrade("วันที่เกษียณอายุราชการ 30 กันยายน 2568", "30 กันยายน 2568") == "DATE"
    assert _upgrade("ผู้ป่วยเกิดวันที่ 18 กรกฎาคม 2500", "18 กรกฎาคม 2500") == "DATE_OF_BIRTH"


def test_accident_report_end_to_end_keeps_labels_honest():
    # lf19 verbatim: the accident date must not surrogate into a fake birthday
    # while the driver's real birth date keeps its DOB label.
    text = (
        "รายงานอุบัติเหตุจราจร เลขที่รายงาน ACC-2569-0442\n"
        "เกิดเหตุวันที่ 20 กรกฎาคม 2569 เวลา 07.45 น. บริเวณถนนมิตรภาพ กิโลเมตรที่ 42\n"
        "คู่กรณีที่ 2 ผู้ขับขี่ อุมาพร สินธุประเสริฐ รถจักรยานยนต์ทะเบียน สช 3489\n"
        "เกิดวันที่ 02/02/2544 โทรศัพท์ 0632211009 อีเมล umaporn.s@example.com"
    )
    accident = _tb_types(text, "20 กรกฎาคม 2569") | _fp_types(text, "20 กรกฎาคม 2569")
    assert "DATE_OF_BIRTH" not in accident, accident
    birth = _tb_types(text, "02/02/2544") | _fp_types(text, "02/02/2544")
    assert "DATE_OF_BIRTH" in birth, birth


# ── C. unknown CRF labels (LAW) must not swallow multi-line PII (ed06/lf20) ─

ED06_TEXT = (
    "แบบคำขอกู้ยืมเงินกองทุนเพื่อการศึกษา\n"
    "ผู้กู้ นภัสสร อัมพรพิสิฏฐ์ รหัสนักศึกษา 67030922\n"
    "เลขบัตรประชาชน 1488642705188 วันเกิด 30 ตุลาคม 2549\n"
    "ที่อยู่ 54/3 หมู่ 7 ตำบลคลองหนึ่ง อำเภอคลองหลวง จังหวัดปทุมธานี 12120"
)

LF20_ADVISOR_TAIL = (
    "แบบคำร้องขอย้ายสถานศึกษาและโอนผลการเรียน\n"
    "ส่วนที่ 1 ข้อมูลนักศึกษา\n"
    "ชื่อ นางสาว ญาดา ทิพยเนตร รหัสนักศึกษาเดิม 6702113405 รหัสนักศึกษาใหม่ 69040771\n"
    "เลขประจำตัวประชาชน 6520148720271 วันเกิด 28 เมษายน 2548\n"
    "อีเมลเดิม yada.t@old-university.example.ac.th อีเมลใหม่ yada.t@student.example.ac.th\n"
    "โทรศัพท์ 0923344556\n"
    "ที่อยู่ปัจจุบัน 14/9 ซอยสุขุมวิท 71 แขวงพระโขนงเหนือ เขตวัฒนา กรุงเทพมหานคร 10110\n"
    "ส่วนที่ 2 ผู้ปกครอง\n"
    "ธีระชัย ทิพยเนตร โทรศัพท์ 0866778899 บัญชีชำระค่าเทอม 7733991100\n"
    "อาจารย์ที่ปรึกษาคนใหม่ นงลักษณ์ วีรกุลชัย อีเมล nonglak.w@example.ac.th\n"
    "เอกสารแนบ ใบแสดงผลการเรียนฉบับสมบูรณ์ หนังสือรับรองความประพฤติ และสำเนาใบเสร็จค่าเทอมภาคล่าสุด รวม 3 ฉบับ"
)


def test_law_swallowed_birth_date_is_recovered():
    # ed06: one LAW span ate name + ids + DOB; the model tags the line fine
    # in isolation, so the unknown-label span is re-tagged per physical line.
    assert "DATE_OF_BIRTH" in _tb_types(ED06_TEXT, "30 ตุลาคม 2549")


def test_retagged_lines_do_not_mint_field_label_names():
    # The retag context is where the CRF hallucinates PERSON on field labels;
    # is_non_person_segment gates what the retag may keep.
    for e in detect_tb(ED06_TEXT):
        assert e.original_text != "เลขบัตรประชาชน", e


def test_law_swallowed_advisor_name_is_recovered():
    assert "NAME" in _tb_types(LF20_ADVISOR_TAIL, "นงลักษณ์ วีรกุลชัย")


# ── D. digits glued into a PERSON span must not unmask the name (fn10) ─────

FN10_TEXT = (
    "แจ้งโอนเงินค่ามัดจำ โอนแล้วนะครับ ชื่อบัญชี ศักดิ์ชัย รุ่งอรุณ เลขบัญชี8807123456 "
    "ยอด 2,500 บาท แนบสลิปมาทางอีเมล sakchai.r@mail.example.org แล้ว"
)


def test_payment_chat_name_survives_the_glued_account_number():
    # The whole chain: CRF glues the digits into the PERSON span, the FP
    # BANK_ACCOUNT overlaps its tail, and dedupe_spans dropped the WHOLE name.
    from pii_redactor.detectors.aggregate import detect_all

    ents = detect_all(FN10_TEXT)
    lo = FN10_TEXT.index("ศักดิ์ชัย รุ่งอรุณ")
    hi = lo + len("ศักดิ์ชัย รุ่งอรุณ")
    assert any(e.data_type == "NAME" and e.span[0] < hi and lo < e.span[1] for e in ents), [
        (e.data_type, e.original_text) for e in ents
    ]
    assert any(e.data_type == "BANK_ACCOUNT" for e in ents)


def test_name_hygiene_splits_at_digit_runs():
    # A person's name never contains a digit run — same invariant class as
    # "never spans a line break". The name segment stays clear of the digits.
    # 2026-08-04 (boundary B1/B2): the same-line edge trim now also strips
    # the label tokens the digit cut left behind (บัญชี head, เลขบัญชี tail
    # — both whole-token _NOT_NAME entries), so the segment is the name.
    segs = _hygiene_texts(FN10_TEXT, "บัญชี ศักดิ์ชัย รุ่งอรุณ เลขบัญชี8807123456")
    assert segs == ["ศักดิ์ชัย รุ่งอรุณ"], segs


# ── E. และ/กับ after an accepted NAME introduces the next person (gf14) ────


def _conjunction(text: str, seed_value: str) -> set[str]:
    from pii_redactor.detectors.name_context import detect_conjunction_names

    lo = text.index(seed_value)
    seed = Entity(
        entity_id="seed",
        redact_type="TB",
        data_type="NAME",
        span=(lo, lo + len(seed_value)),
        score=0.85,
        original_text=seed_value,
    )
    return {e.original_text for e in detect_conjunction_names(text, [seed])}


def test_conjunction_after_name_collects_the_next_person():
    text = "พบ สมชาย ใจดี และ ธงชัย รักถิ่นเกิด เมื่อวานนี้"
    assert _conjunction(text, "สมชาย ใจดี") == {"ธงชัย รักถิ่นเกิด"}


def test_conjunction_requires_two_real_groups():
    # _collect_two_groups returns a single-group span when group 2's head
    # token is rejected — a kinship word or org unit must not become a person.
    for text in (
        "พบ สมชาย ใจดี และ มารดา ของเด็ก",
        "พบ สมชาย ใจดี และ คณะทำงาน จะประชุมพรุ่งนี้",
        "พบ สมชาย ใจดี และ ฝ่ายบัญชี ดำเนินการต่อ",
    ):
        assert _conjunction(text, "สมชาย ใจดี") == set(), text


def test_meeting_attendee_after_conjunction_is_detected():
    # gf14 verbatim: the third attendee shipped fully unmasked.
    text = (
        "รายงานการประชุมคณะกรรมการหมู่บ้าน ครั้งที่ 4/2569\n"
        "ผู้เข้าร่วมประชุมประกอบด้วย ไพโรจน์ สุขสมบูรณ์ เพ็ญศรี ทองอินทร์ และ "
        "ธงชัย รักถิ่นเกิด เริ่มประชุมเวลา 09.30 น."
    )
    assert "NAME" in _tb_types(text, "ธงชัย รักถิ่นเกิด")


# ── F. role cues: ผู้เสียหาย with a glued linker, ออกให้ on issuance rows ──


def test_victim_cue_with_glued_linker_collects_the_name():
    # nc09: คือ glued to ผู้เสียหาย defeated the direct-cue space rule.
    assert "อนุชา ดวงแก้ว" in _ctx_names("ผู้เสียหายคือ อนุชา ดวงแก้ว แจ้งความไว้เป็นหลักฐาน")


def test_victim_cue_prose_continuations_yield_nothing():
    for text in (
        "ผู้เสียหายแจ้งความเมื่อวันอังคารที่ผ่านมา",
        "ผู้เสียหายได้รับการชดเชยครบถ้วนแล้ว",
        "ผู้เสียหายทั้งสามรายมาพบพนักงานสอบสวน",
        "ผู้เสียหายรายนี้ปฏิเสธการไกล่เกลี่ย",
    ):
        assert _ctx_names(text) == set(), (text, _ctx_names(text))


def test_card_issuance_rows_collect_the_holder():
    # id25: the CRF is row-inconsistent on identical formats; ออกให้ owns them.
    assert "ปกรณ์เกียรติ ธนวัฒนา" in _ctx_names("4024-0032-5269-5018 ออกให้ ปกรณ์เกียรติ ธนวัฒนา")
    assert "ลลิตา อนันตศักดิ์" in _ctx_names("5299-0220-0042-1746 ออกให้ ลลิตา อนันตศักดิ์")


def test_issuance_cue_never_vouches_for_orgs_or_registrations():
    for text in (
        "ใบเสร็จรับเงินฉบับนี้ออกให้ บริษัท เอบีซี จำกัด ตามสัญญา",
        "ใบกำกับภาษีออกให้ หจก รุ่งเรืองการโยธา สาขาที่ 1",
        "บัตรจอดรถออกให้ ทะเบียน กข 1234 ประตูสอง",
        # the glued แก่ form is a stated recall cost, not a person collector
        "ออกให้แก่ สมชาย ใจดี",
    ):
        assert _ctx_names(text) == set(), (text, _ctx_names(text))


# ── G. rosters: selection announcements and meeting minutes headers ────────

GF09_TEXT = (
    "ประกาศผลการคัดเลือกพนักงานราชการ\n"
    "ลำดับที่ 1 ศิริลักษณ์ บุญประกอบ\n"
    "ลำดับที่ 2 ทศพล เกียรติขจร\n"
    "ลำดับที่ 3 พัชรินทร์ สมบัติมาก\n"
    "ให้ผู้ผ่านการคัดเลือกรายงานตัวภายในวันที่ 15 กันยายน 2569"
)


def test_selection_announcement_roster_names_are_detected():
    names = _ctx_names(GF09_TEXT)
    for name in ("ศิริลักษณ์ บุญประกอบ", "ทศพล เกียรติขจร", "พัชรินทร์ สมบัติมาก"):
        assert name in names, (name, names)


def test_vendor_selection_roster_yields_no_person():
    # The org-lead check is what keeps the wider header vocabulary honest:
    # juristic persons in a procurement result are not people.
    text = (
        "แจ้งผลการคัดเลือกผู้รับจ้างประจำปี 2569\n"
        "ลำดับที่ 1 บริษัท สยามก่อสร้าง จำกัด เสนอราคา 1,250,000 บาท\n"
        "ลำดับที่ 2 หจก รุ่งเรืองการโยธา เสนอราคา 1,310,000 บาท"
    )
    assert _ctx_names(text) == set(), _ctx_names(text)


def test_meeting_minutes_attendee_roster_is_detected():
    # lf10: ผู้มาประชุม is the STANDARD header of Thai meeting minutes; the
    # CRF misread the surname as LOCATION and half-unmasked the given name.
    text = (
        "รายงานการประชุมคณะกรรมการบริหารความเสี่ยง ครั้งที่ 3/2569\n"
        "วันที่ 10 กรกฎาคม 2569 เวลา 13.30 น. ถึง 16.00 น.\n"
        "ผู้มาประชุม\n"
        "1. วิโรจน์ อัครวรกุล ประธานกรรมการ\n"
        "2. สุภาวดี ธีรพัฒน์ กรรมการ\n"
        "3. ชาญวิทย์ ปรีชาญาณ กรรมการ"
    )
    assert "NAME" in _tb_types(text, "สุภาวดี ธีรพัฒน์")


# ── H. เรียน is the salutation verb, never a given name (gf16) ─────────────


def test_salutation_verb_is_not_a_name():
    text = "หนังสือเชิญประชุมผู้ปกครอง เรียน ผู้ปกครองของนักเรียน ขอเชิญท่านเข้าร่วมประชุม"
    assert _ctx_names(text) == set(), _ctx_names(text)


def test_titled_name_after_salutation_still_detected():
    names = _ctx_names("เรียน นายสมชาย ใจดี ตามที่ท่านแจ้งความประสงค์")
    assert any("สมชาย ใจดี" in n for n in names), names


# ── I. passport adjacency: field labels are not two-group names (id02/id09) ─


def test_passport_adjacent_field_labels_are_rejected():
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


def test_real_names_before_passports_survive():
    # Only the LEAD token is judged, so a surname newmm splits onto a stop
    # word (ทองอยู่ -> ทอง|อยู่) keeps detecting.
    assert "สมชาย ใจดี" in _ctx_names("รายชื่อผู้เข้าพัก สมชาย ใจดี AB1234567")
    assert "ชลธิชา ทองอยู่" in _ctx_names("รายชื่อผู้เข้าพัก ชลธิชา ทองอยู่ DV8240222")


# ── J. token pass: no crossing line breaks, no vouching for compounds ──────


def test_direct_cue_does_not_vouch_across_a_line_break():
    # lf07: ผู้เสียหาย ended the doc title, the collector took the police
    # station as a first name and the next line's วันที่ as a surname.
    text = "บันทึกคำให้การผู้เสียหาย สถานีตำรวจภูธรเมือง\nวันที่ 18 กรกฎาคม 2569 เวลา 10.00 น."
    assert _ctx_names(text) == set(), _ctx_names(text)


def test_direct_cue_same_line_name_still_detected():
    assert "วิชัย ประสงค์ดี" in _ctx_names("ข้าพเจ้า วิชัย ประสงค์ดี ขอรับรองว่าข้อความเป็นจริง")


def test_titled_span_cannot_self_reject_on_the_compound_list():
    # The compound check applies to the name part sans title, so a real
    # "นาย <name>" span survives (ประกาศิต is a real given name).
    names = _ctx_names("นาย ประกาศิต ชัยมงคล ลงนามรับทราบ")
    assert any("ประกาศิต ชัยมงคล" in n for n in names), names


# ── K. document-title compounds leaking through head leniency ──────────────


def test_document_title_heads_are_rejected():
    for text, span_value, kept in (
        (
            "รายชื่อนักศึกษาฝึกงาน ประจำภาคฤดูร้อน\nศุภกร ไชยวัฒนา 64010775",
            "รายชื่อนักศึกษาฝึกงาน ประจำภาคฤดูร้อน\nศุภกร ไชยวัฒนา",
            "ศุภกร ไชยวัฒนา",
        ),
        (
            "แบบประเมินการฝึกสอนของนักศึกษาครู\nนักศึกษา อรวรรณ นพคุณ รหัส 65500193",
            "แบบประเมินการฝึกสอนของนักศึกษาครู\nนักศึกษา อรวรรณ นพคุณ",
            "นักศึกษา อรวรรณ นพคุณ",
        ),
        (
            "สัญญาเช่ารถยนต์\nผู้เช่า ชลดา ภูมิพัฒน์ ใบขับขี่ตามแนบ",
            "สัญญาเช่ารถยนต์\nผู้เช่า ชลดา ภูมิพัฒน์",
            "ผู้เช่า ชลดา ภูมิพัฒน์",
        ),
    ):
        segs = _hygiene_texts(text, span_value)
        assert segs == [kept], (text, segs)


def test_letter_closing_head_is_rejected():
    # lf03: the closing formula survived head leniency while the middle line
    # (ขอแสดงความนับถือ) was already rejected — the signer is all that stays.
    text = "ขอบคุณมา ณ โอกาสนี้\nขอแสดงความนับถือ\nธเนศ ภูวเดชากุล คณบดีคณะวิทยาศาสตร์"
    segs = _hygiene_texts(text, "ขอบคุณมา ณ โอกาสนี้\nขอแสดงความนับถือ\nธเนศ ภูวเดชากุล")
    assert segs == ["ธเนศ ภูวเดชากุล"], segs


def test_real_names_sharing_compound_prefixes_survive():
    # สัญญา and แบบบุญมี are real given names; the additions are compounds
    # (สัญญาเช่า/สัญญาจ้าง/แบบประเมิน), never noun prefixes.
    for value in ("สัญญา ธรรมศักดิ์", "แบบบุญมี สายทอง"):
        text = "ผู้ลงนาม " + value + " ตามเอกสารแนบ"
        assert _hygiene_texts(text, value) == [value], value
