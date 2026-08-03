"""Organizational document codes must not become numeric PII.

Every catch below is a verbatim false positive from the gold negative slice
(2026-08-03 dump): digits glued to an ASCII code prefix (PO-/SKU-/...), digits
introduced by an organizational-number cue (ISSN / เลขที่โครงการ / คำขอรับ
สิทธิบัตร), and a service-area postal-code enumeration. All values fabricated.

The controls pin the recall boundary: checksum-backed types still fire behind
a glued prefix, a bank cue still wins by nearest-cue, and a single postcode at
the tail of a real address stays claimed.
"""

from __future__ import annotations

from pii_redactor.detectors.fp_detector import detect_fp


def _types_for(text: str, value: str) -> set[str]:
    lo = text.index(value)
    hi = lo + len(value)
    return {e.data_type for e in detect_fp(text) if e.span[0] < hi and lo < e.span[1]}


# ── A. digits glued to an ASCII code prefix are a document code ────────────


def test_glued_ascii_prefix_suppresses_numeric_fallbacks():
    for text, value in (
        ("ใบสั่งซื้อเลขที่ PO-2569-004512 รายการครุภัณฑ์คอมพิวเตอร์", "2569-004512"),
        ("เลขที่ใบเสร็จ RC-2569-119284 ยอดชำระ 4,500 บาท", "2569-119284"),
        ("เลขที่ใบกำกับภาษี TX-2569-338920 ยอดก่อนภาษี 24,000 บาท", "2569-338920"),
        ("รหัสสินค้า SKU-8891042376 ราคาต่อหน่วย 1,290 บาท", "8891042376"),
        ("รหัสสินค้า ITM-4471002983 ราคาขายปลีก 2,450 บาท", "4471002983"),
    ):
        assert _types_for(text, value) == set(), text


def test_glued_bank_or_generic_prefix_keeps_base_behavior():
    # Adversarial review 2026-08-03: the first cut suppressed ANY letters-
    # prefix, silencing real accounts in payment chat (SCB-/KBANK-/A/C-) and
    # org-issued personal ids (EMP-). The suppression is a closed document-
    # prefix list now; everything else keeps the base recall-first behavior.
    for text, value, expected in (
        ("โอนเงินไปที่ SCB-4071002983 ภายในวันนี้ด้วยนะ", "4071002983", "BANK_ACCOUNT"),
        ("ชำระแล้วโปรดโอนเข้า KBANK-0431234567 ด้วยครับ", "0431234567", "BANK_ACCOUNT"),
        ("กรุณาชำระเงินเข้า A/C-4071002983 ภายในวันที่ 15", "4071002983", "BANK_ACCOUNT"),
        ("โอนไปที่ AC-407-1-00298-3 ก่อนสิ้นเดือน", "407-1-00298-3", "BANK_ACCOUNT"),
        ("รหัสพนักงาน EMP-10078845 ใช้สแกนเข้าออกอาคาร", "10078845", "ID_NUMBER"),
    ):
        assert expected in _types_for(text, value), text


def test_glued_prefix_never_silences_checksum_backed_types():
    # A valid mod-11 id pasted into a code field is still a real id — the
    # recall-first boundary for checksum-backed types stays where it was.
    text = "อ้างอิง REF-1101700230708 ตามแบบฟอร์มเดิม"
    assert "THAI_ID" in _types_for(text, "1101700230708")


def test_thai_label_without_glued_prefix_keeps_the_demotion_path():
    # No ASCII prefix glued to the digits: the nonstandard-separator demotion
    # to ID_NUMBER (recall-first, still masked) must keep working.
    text = "เลขที่ 2569-004512 ตามทะเบียนรับหนังสือ"
    assert "ID_NUMBER" in _types_for(text, "2569-004512")


# ── B. organizational-number cues win by nearest-cue ───────────────────────


def test_org_number_cue_suppresses_bare_fallback():
    for text, value in (
        ("การจัดซื้อจัดจ้าง เลขที่โครงการ 66129445871 วงเงินงบประมาณ 2,350,000 บาท", "66129445871"),
        ("วารสารฉบับที่ 4 ปีที่ 27 ISSN 08571724 เผยแพร่เดือนกันยายน 2568", "08571724"),
        ("หมายเลขคำขอรับสิทธิบัตร 2601003847 ยื่นคำขอเมื่อวันที่ 11 กุมภาพันธ์ 2569", "2601003847"),
    ):
        assert _types_for(text, value) == set(), text


def test_patent_topic_word_does_not_silence_a_transfer():
    # Adversarial review 2026-08-03: bare สิทธิบัตร is a topic word (patent
    # royalty notifications), not a number-field label. Only the field forms
    # (คำขอรับสิทธิบัตร / สิทธิบัตรเลขที่) count as org-number cues.
    for text, value in (
        ("เงินรางวัลสิทธิบัตรจะโอนเข้า 4471002983 ภายในเดือนนี้", "4471002983"),
        ("ค่าตอบแทนการใช้สิทธิบัตรจะโอนเข้า 407-1-00298-3 ทุกไตรมาส", "407-1-00298-3"),
    ):
        assert "BANK_ACCOUNT" in _types_for(text, value), text


def test_nearer_bank_cue_beats_org_cue():
    # Nearest-cue-wins, same rule as bank/phone and bank/student: the account
    # inside a project announcement is still an account.
    text = "โครงการช่วยเหลือเกษตรกร โอนเข้าบัญชี 4471002983 ภายในสิ้นเดือน"
    assert "BANK_ACCOUNT" in _types_for(text, "4471002983")


def test_bank_and_student_labels_survive_without_org_cue():
    assert "BANK_ACCOUNT" in _types_for("เลขที่บัญชี 4471002983 ธนาคารกรุงไทย", "4471002983")
    assert "STUDENT_ID" in _types_for("รหัสนักศึกษา 65110288 คณะวิศวกรรมศาสตร์", "65110288")


# ── C. a run of bare 5-digit groups is an enumeration, not an address ──────


def test_postal_code_enumeration_is_not_claimed():
    text = "รหัสไปรษณีย์ปลายทางในเขตบริการ 10110 10230 10250 และ 10400 จัดส่งภายในวันเดียวกัน"
    for value in ("10110", "10230", "10250", "10400"):
        assert _types_for(text, value) == set(), value


def test_single_postcode_at_address_tail_stays_claimed():
    text = "ที่อยู่ 99/1 แขวงวังทองหลาง กรุงเทพมหานคร 10310"
    assert "POSTAL_CODE" in _types_for(text, "10310")


def test_multi_address_line_keeps_every_postcode():
    # Adversarial review 2026-08-03: three real drop-off addresses in one
    # courier line — the middle postcode saw two "siblings" and shipped
    # unmasked. Siblings now require enumeration glue (whitespace/และ/หรือ)
    # between the codes; Thai address words between them break the run.
    text = "ส่งของสามจุด แขวงบางรัก 10500 ตำบลสุเทพ 50200 ตำบลในเมือง 40000 ภายในพรุ่งนี้"
    for value in ("10500", "50200", "40000"):
        assert "POSTAL_CODE" in _types_for(text, value), value


def test_khet_borikan_is_not_an_admin_area():
    # เขตบริการ (service area) must not seed an ADDRESS fragment; a real
    # district behind เขต keeps its claim.
    text = "รหัสไปรษณีย์ปลายทางในเขตบริการ 10110 10230 10250 และ 10400 จัดส่งภายในวันเดียวกัน"
    assert all(e.data_type != "ADDRESS" for e in detect_fp(text))
    assert "ADDRESS" in _types_for("สำนักงานตั้งอยู่เขตบางรัก กรุงเทพมหานคร", "บางรัก")


# ── D/E. TB side: a CRF "location" that is really a document number, and a
# "date" that is really a Thai industrial-standard designation ──────────────


def _tb_types_for(text: str, value: str) -> set[str]:
    from pii_redactor.detectors.tb_detector import detect_tb

    lo = text.index(value)
    hi = lo + len(value)
    return {e.data_type for e in detect_tb(text) if e.span[0] < hi and lo < e.span[1]}


def test_location_that_is_a_document_code_is_rejected():
    # ng21/ng35/ng38 shapes: an abbreviation+digits contract number and the
    # เลขที่<document> labels the CRF misreads as places.
    for text, value in (
        ("เลขที่สัญญา จ.44/2569 ระยะเวลาดำเนินการ 180 วัน", "จ.44/2569"),
        ("เลขที่คำสั่ง 205/2569 ลงวันที่ 30 มิถุนายน 2569 เรื่อง แต่งตั้งคณะทำงาน", "เลขที่คำสั่ง"),
        ("เลขที่ใบเสนอราคา QT-6907-0231 ยืนราคา 30 วัน นับจากวันเสนอ", "เลขที่ใบเสนอราคา"),
    ):
        got = _tb_types_for(text, value)
        assert "LOCATION" not in got and "ADDRESS" not in got, (text, got)


def test_real_locations_survive_the_code_rejection():
    # A real province stays LOCATION (or upgrades to ADDRESS with a cue), and
    # a location containing digits (a postcode) is still a location.
    got = _tb_types_for("สัมมนาจัดที่จังหวัดขอนแก่น ผู้สนใจลงทะเบียนได้", "ขอนแก่น")
    assert "LOCATION" in got or "ADDRESS" in got


def test_date_after_standard_designation_is_rejected():
    # ng36: "มอก. 2540-2555" is a Thai industrial standard number, not a date.
    text = "ผลิตตามมาตรฐาน มอก. 2540-2555 กำหนดค่าความคลาดเคลื่อนไว้ชัดเจน"
    assert "DATE" not in _tb_types_for(text, "2540-2555")


def test_real_dates_survive_the_standard_rejection():
    text = "ประกาศ ณ วันที่ 8 กรกฎาคม 2569 มีผลบังคับใช้ทันที"
    assert "DATE" in _tb_types_for(text, "8 กรกฎาคม 2569")


def test_mork_the_fog_does_not_suppress_a_date():
    # Adversarial review 2026-08-03: the มอก. lookback had no left boundary,
    # so ทะเลหมอก (sea of fog) swallowed a following date.
    text = "พาลูกค้าไปชมทะเลหมอก 25 ธันวาคม 2569 ที่เขาค้อ"
    assert "DATE" in _tb_types_for(text, "25 ธันวาคม 2569")


def test_bare_house_number_is_not_a_document_code():
    # Adversarial review 2026-08-03: "214/9" (a real Thai house number, no
    # Thai letters) must survive the LOCATION code rejection; the contract
    # number จ.44/2569 is separated from it by its Buddhist-year component.
    # Tested on the chokepoint directly so the pin holds for every engine
    # that routes through it, including the opt-in finetuned one.
    from pii_redactor.detectors.tb_detector import _apply_cue_upgrades

    text = "ส่งของไปที่ 214/9 หมู่ 4 ตำบลบางพลีใหญ่"
    lo = text.index("214/9")
    assert _apply_cue_upgrades(text, lo, lo + len("214/9"), "LOCATION") is not None

    code = "เลขที่สัญญา จ.44/2569 ระยะเวลา 180 วัน"
    lo = code.index("จ.44/2569")
    assert _apply_cue_upgrades(code, lo, lo + len("จ.44/2569"), "LOCATION") is None


def test_date_span_swallowing_a_serial_number_is_rejected():
    # ng17 second layer: with the FP ID_NUMBER gone, dedupe no longer hides
    # the degenerate CRF DATE span that swallowed the ISSN serial. No calendar
    # date component has five digits in a row.
    text = "วารสารฉบับที่ 4 ปีที่ 27 ISSN 08571724 เผยแพร่เดือนกันยายน 2568"
    assert "DATE" not in _tb_types_for(text, "08571724")
