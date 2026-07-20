"""Context-based name detection (recall booster) + integration with detect_tb."""

from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.detectors.tb_detector import detect_tb


def _names(text, fn=detect_name_context):
    return [e.original_text for e in fn(text) if e.data_type == "NAME"]


def test_self_intro_catches_full_name():
    # CRF missed this name entirely in live testing
    names = _names("ผมชื่อ สมหญิง รักดี เบอร์ 081-234-5678")
    assert any("สมหญิง" in n and "รักดี" in n for n in names)


def test_title_includes_surname():
    # CRF clipped the surname ("ใจดี" leaked) when a title preceded the name
    names = _names("นายสมชาย ใจดี อายุ 30")
    assert any("ใจดี" in n for n in names)


def test_label_cue():
    assert any("วิชัย" in n and "มั่งมี" in n for n in _names("ลงชื่อ วิชัย มั่งมี"))


def test_nangsao_title():
    assert any("มาลี" in n for n in _names("ส่งเอกสารถึงนางสาวมาลี สวยงาม ด้วยครับ"))


def test_no_false_positive_on_nayok():
    # "นายก" (PM) is one token, must NOT trigger the "นาย" title cue
    assert _names("นายกรัฐมนตรีแถลงข่าววันนี้") == []


def test_no_false_positive_on_filename_label():
    # bare "ชื่อ" (not after a pronoun) is not a name cue
    assert _names("ชื่อไฟล์ report.pdf") == []


def test_no_false_positive_on_khunaphap():
    assert _names("คุณภาพของงานดีมาก") == []


def test_integration_detect_tb_includes_context_name():
    names = _names("ผมชื่อ สมหญิง รักดี เบอร์ 081-234-5678", fn=detect_tb)
    assert any("รักดี" in n for n in names)


def test_label_nouns_not_collected_as_surname():
    # 'รหัสพนักงาน' / 'เลขบัตรประชาชน' are document-label nouns, never part of
    # a person name — the group collector must stop before them.
    names = _names("ผมชื่อ สมชาย รหัสพนักงาน EMP-10234")
    assert names, "the actual name must still be caught"
    assert all("รหัส" not in n and "พนักงาน" not in n for n in names)

    names = _names("ผมชื่อ สมชาย เลขบัตรประชาชน 1101700230708")
    assert names
    assert all("เลขบัตร" not in n and "ประชาชน" not in n for n in names)
