"""NAME campaign 2: role cues, rosters, Latin names, and CRF span hygiene.

Gold v4 measured NAME R=0.774 / P=0.963 while the blind holdout showed
R=0.958 / P=0.748 — gold exposes a recall gap (role-introduced names the CRF
misses), blind a precision gap (header/form registers the CRF hallucinates
on). The positive cases below are gold miss classes; the negative controls
are the adversarial review's counterexamples (Codex 2026-07-29), including
the real-name traps that killed the naive versions of these rules: เลขา,
ใบเฟิร์น, ประกาศิต are given names, so hygiene filters match document
COMPOUNDS (ตารางสอบ, เลขครุภัณฑ์), never noun prefixes.
"""

from __future__ import annotations

from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.detectors.tb_detector import detect_tb


def ctx_names(text: str) -> set[str]:
    return {e.original_text for e in detect_name_context(text)}


def tb_names(text: str) -> set[str]:
    return {e.original_text for e in detect_tb(text) if e.data_type == "NAME"}


# ── role cues (gold miss class 1) ──────────────────────────────────────────


def test_role_cues_introduce_two_group_names():
    for text, name in (
        ("ผู้ป่วย สมบูรณ์ ทรงศิริ เลขประจำตัวผู้ป่วย 445102", "สมบูรณ์ ทรงศิริ"),
        ("ผู้ปกครอง นฤมล อ่อนละมุน โทร 093-115-2214", "นฤมล อ่อนละมุน"),
        ("ผู้กู้ ยุทธนา สินสมบัติ เลขบัตรประชาชนตามแนบ", "ยุทธนา สินสมบัติ"),
        ("ผู้ค้ำประกันเงินกู้คือ สราวุธ มั่นคง ตามสัญญาแนบท้าย", "สราวุธ มั่นคง"),
        ("ผู้รับมอบอำนาจ เกษม สายทอง ดำเนินการแทนได้ทุกกรณี", "เกษม สายทอง"),
        ("ผู้ยื่นอุทธรณ์ ปรีชา หาญกล้า ขอให้ทบทวนคำสั่ง", "ปรีชา หาญกล้า"),
        ("ผู้ถือบัตร อธิป จรัสแสงทอง หมายเลขบัตรตามระบบ", "อธิป จรัสแสงทอง"),
        ("คู่กรณีที่ 2 ผู้ขับขี่ อุมาพร สินธุประเสริฐ รถจักรยานยนต์", "อุมาพร สินธุประเสริฐ"),
        ("ขอมอบอำนาจให้ อัมพร ตั้งจิตต์ เป็นผู้ดำเนินการแทน", "อัมพร ตั้งจิตต์"),
        ("ชื่อบัญชี ศักดิ์ชัย รุ่งอรุณ เลขบัญชีตามสลิป", "ศักดิ์ชัย รุ่งอรุณ"),
    ):
        assert name in ctx_names(text), text


def test_glued_role_cue_with_field_after():
    # messy register: cue glued to the name, a field label right after.
    names = ctx_names("ผู้ติดต่อมานพ ดีเลิศเบอร์0891234455")
    assert any(n.startswith("มานพ") for n in names), names


def test_role_suffix_vetoes():
    # Role words continuing into ordinary prose must not produce names.
    for text in (
        "ผู้ป่วยใน ห้องพิเศษ ชั้น 5",
        "ผู้กู้ร่วม ต้องชำระ ภายในกำหนด",
        "ผู้ติดต่อสอบถาม ข้อมูลเพิ่มเติม ได้ทุกวัน",
        "ผู้ติดต่อหลัก ฝ่ายบัญชี อาคาร 2",
        "ผู้ถือบัตรต้อง แสดงบัตร ทุกครั้ง",
        "ผู้ขับขี่ควร ปฏิบัติตาม กฎจราจร",
        "มอบอำนาจให้ดำเนินการ แทนข้าพเจ้า ได้",
        "ชื่อบัญชี ออมทรัพย์ ดอกเบี้ยสูง",
        "ผู้แจ้งความ ประสงค์ดำเนินคดี ถึงที่สุด",
    ):
        assert ctx_names(text) == set(), (text, ctx_names(text))


def test_collector_rejects_leading_verbs():
    for text in (
        "ผู้ค้ำประกัน ต้องชำระ หนี้แทน",
        "ผู้ปกครอง กรุณาลงนาม รับทราบ",
        "ผู้ป่วย ได้รับ การรักษาต่อเนื่อง",
    ):
        assert ctx_names(text) == set(), (text, ctx_names(text))


# ── bare "ชื่อ" label at line start (gold miss class 2) ────────────────────


def test_line_start_name_label():
    assert "กมล ทวีสิน" in ctx_names("ข้อมูลผู้สมัครงาน\nชื่อ กมล ทวีสิน\nโทร 0955512345")
    assert "ศศิธร อุดมทรัพย์" in ctx_names("ชื่อ ศศิธร อุดมทรัพย์ วันเดือนปีเกิดตามบัตร")


def test_mid_sentence_bare_name_label_does_not_fire():
    # "ชื่อ" mid-sentence stays gated on the pronoun rule.
    assert ctx_names("กรุณากรอกชื่อ สถานประกอบการ ให้ครบถ้วน") == set()


# ── rosters (gold miss class 4) ────────────────────────────────────────────


def test_numbered_roster_names():
    text = "รายชื่อผู้ผ่านการสอบคัดเลือกพนักงานราชการ\nลำดับที่ 1 ศิริลักษณ์ บุญประกอบ\nลำดับที่ 2 ทศพล เกียรติขจร\n"
    names = ctx_names(text)
    assert "ศิริลักษณ์ บุญประกอบ" in names, names
    assert "ทศพล เกียรติขจร" in names, names


def test_numbered_agenda_items_do_not_become_names():
    for text in (
        "ระเบียบวาระการประชุม\n1. รายการสินค้า จำนวนเงิน\n2. การชำระ เงินล่วงหน้า\n",
        "เงื่อนไข\n3. ผู้ขาย ต้องส่งมอบ สินค้าตามกำหนด\n",
    ):
        assert ctx_names(text) == set(), (text, ctx_names(text))


def test_name_before_passport_number():
    text = "ทะเบียนผู้เดินทางกลุ่มทัวร์\nอัครวินท์ สุนทรพจน์ PE1350656\nชนม์นิภา บุญญฤทธิ์ DV8240222\n"
    names = ctx_names(text)
    assert "อัครวินท์ สุนทรพจน์" in names, names
    assert "ชนม์นิภา บุญญฤทธิ์" in names, names


# ── Latin names (gold miss class 3) ────────────────────────────────────────


def test_latin_names_with_person_cues():
    for text, name in (
        ("ข้อมูลผู้สมัคร:Name=Somsak Jaidee,ID=21405233", "Somsak Jaidee"),
        ("contact person Nattaya S. mobile 0644445555", "Nattaya S."),
        ("ผู้ยื่น Kanyarat Techasiri passport ตามแนบ", "Kanyarat Techasiri"),
        ("Wichuda Pornprasit passport MV3641618 ห้อง 512", "Wichuda Pornprasit"),
        ("ที่นั่งสอบ A12 Panuwat Chaiyaporn รหัส 66020817", "Panuwat Chaiyaporn"),
    ):
        assert name in ctx_names(text), text


def test_latin_org_and_place_phrases_do_not_become_names():
    for text in (
        "ชื่อ Bangkok Bank สาขาสีลม",
        "Name: Grand Palace Hotel",
        "โอนผ่าน Kasikorn Bank Public Company Limited",
        "แม่น้ำ Chao Phraya River ช่วงฤดูฝน",
        "contact Customer Service ได้ตลอด 24 ชั่วโมง",
    ):
        assert ctx_names(text) == set(), (text, ctx_names(text))


# ── CRF span hygiene (blind precision classes seen in gold's 6 FPs) ────────


def test_crf_name_spans_with_newlines_are_rejected():
    # Any NAME crossing a line break is CRF junk, whatever the content.
    for e in detect_tb("สถานีตำรวจภูธรเมืองขอนแก่น\nวันที่ 12 กรกฎาคม 2569"):
        if e.data_type == "NAME":
            assert "\n" not in e.original_text


def test_document_compound_spans_are_not_names():
    for text, junk in (
        ("ตารางสอบปลายภาค วันจันทร์ ถึง วันศุกร์", "ตารางสอบ"),
        ("เลขครุภัณฑ์ 7440-001-0001 ประจำห้องปฏิบัติการ", "เลขครุภัณฑ์"),
        ("รายงานการหักภาษี ณ ที่จ่าย ประจำเดือน", "รายงานการ"),
        ("ประวัติการแพ้ยา แพ้ยากลุ่มเพนิซิลลิน", "ประวัติการ"),
    ):
        for e in detect_tb(text):
            if e.data_type == "NAME":
                assert not e.original_text.startswith(junk), (text, e.original_text)


def test_real_names_that_start_like_document_nouns_survive():
    # เลขา / ใบเฟิร์น / ประกาศิต are real given names — the hygiene filter must
    # match document compounds, not noun prefixes.
    for text, name in (
        ("นาง เลขา วงศ์สว่าง มารายงานตัวแล้ว", "เลขา วงศ์สว่าง"),
        ("นางสาว ใบเฟิร์น สุขใจ ยื่นเอกสารครบ", "ใบเฟิร์น สุขใจ"),
        ("นาย ประกาศิต ชัยมงคล ลงนามรับทราบ", "ประกาศิต ชัยมงคล"),
    ):
        assert any(name in n for n in ctx_names(text)), text


# ── overlap resolution ─────────────────────────────────────────────────────


def test_fuller_context_name_beats_clipped_crf_span():
    # Even when a CRF NAME starts earlier (swallowing the role word), the
    # higher-scored fuller context candidate must win NAME-NAME dedupe so the
    # surname does not leak.
    ents = [e for e in detect_tb("ผู้ติดต่อมานพ ดีเลิศเบอร์0891234455") if e.data_type == "NAME"]
    assert ents, "expected a NAME"
    assert any("ดีเลิศ" in e.original_text for e in ents), [e.original_text for e in ents]
