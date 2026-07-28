"""STUDENT_ID labeling: education-context tier and bank-steal fixes.

Gold v4 measured STUDENT_ID recall at 0.509 with every miss *detected but
mislabeled* (ID_NUMBER / BANK_ACCOUNT / TB DATE), so these tests are about
label honesty, not masking. The design was adversarially reviewed (Codex,
2026-07-28): the compound blockers and the negative controls below came out
of that review — a wider context rule must not flip course codes, employee
codes, payment references, or order numbers into STUDENT_ID.
"""

from __future__ import annotations

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.fp_detector import detect_fp


def _types_for(text: str, value: str, ents) -> set[str]:
    lo = text.index(value)
    hi = lo + len(value)
    return {e.data_type for e in ents if e.span[0] < hi and lo < e.span[1]}


def fp_types(text: str, value: str) -> set[str]:
    return _types_for(text, value, detect_fp(text))


# ── catches: person cue slightly out of the old 30-char window ─────────────


def test_person_cue_up_to_60_chars_before_still_wins():
    # ed07/ed09 shape: the student word sits 30-60 chars before the digits
    # (a name or a heading intervenes).
    for text, value in (
        ("นักศึกษา จิรวัฒน์ ศุภมงคล รหัส 65110288 เกรดเฉลี่ยสะสม 3.21", "65110288"),
        ("นักศึกษาฝึกงาน ประจำภาคฤดูร้อน\nศุภกร ไชยวัฒนา 64010775 อีเมลติดต่อภายหลัง", "64010775"),
    ):
        assert "STUDENT_ID" in fp_types(text, value), text


def test_person_cue_after_the_digits_counts():
    # ed02 shape: "รหัสประจำตัว <digits> เป็นนักศึกษา..."
    text = "ขอรับรองว่า ปาลิตา เรืองรุ่งโรจน์ รหัสประจำตัว 65021178 เป็นนักศึกษาชั้นปีที่ 2"
    assert "STUDENT_ID" in fp_types(text, "65021178")


# ── catches: bare introducer + education context (tier 3) ──────────────────


def test_intro_plus_education_context_labels_student_id():
    for text, value in (
        ("รหัส 65014477 ผ่านการประเมินรายวิชาสหกิจศึกษา", "65014477"),
        ("ID 67013355 ลงทะเบียนเรียนครบตามหลักสูตรแล้ว", "67013355"),
        ("ที่ปรึกษารายงานว่ารหัส 65017001 ขาดเรียนเกินเกณฑ์", "65017001"),
        ("ชื่อ กิตติพัฒน์ อารีรักษ์ รหัส 62010449 สำเร็จการศึกษาภาคปลาย", "62010449"),
    ):
        assert "STUDENT_ID" in fp_types(text, value), text


def test_intro_plus_education_context_beats_uncued_bank_shape():
    # sv-shape: a 10-digit id with a รหัส introducer and education context must
    # not be stolen by the uncued BANK_ACCOUNT pattern.
    text = "รหัส 6402118876 ลงทะเบียนเรียนภาคเรียนที่ 1 เรียบร้อย"
    types = fp_types(text, "6402118876")
    assert "STUDENT_ID" in types, types
    assert "BANK_ACCOUNT" not in types, types


def test_dashed_student_id_with_explicit_label():
    # sv14 shape: dashed value after an explicit student label. The TB layer
    # reads NN-NN-NNNN as DATE; the FP candidate must exist and win dedupe.
    text = "รหัสนักศึกษา 68-01-4429 ตามระบบทะเบียน"
    assert "STUDENT_ID" in fp_types(text, "68-01-4429")
    assert _types_for(text, "68-01-4429", detect_all(text)) == {"STUDENT_ID"}


# ── negative controls (from the adversarial review) ────────────────────────


def test_compound_code_words_block_student_id():
    # "รหัสX" compounds name a different kind of code; education context around
    # them must not make them student ids.
    for text in (
        "รหัสหลักสูตร 25620141 ระดับปริญญาตรี",
        "รหัสวิชา 68123456 ภาคเรียนที่ 2",
        "ฝ่ายบุคคลโรงเรียน รหัสพนักงาน 68123456 ตำแหน่งครูผู้ช่วย",
        "หอพักนักศึกษา รหัสชำระ 68123456 สำหรับค่าเช่าภาคเรียนนี้",
        "ใบรับบริจาคมหาวิทยาลัย รหัสรายการ 68123456 เพื่อทุนการศึกษา",
        "มหาวิทยาลัยออกหนังสือ รหัสเอกสาร 68123456 เรื่องผลการเรียน",
    ):
        assert "STUDENT_ID" not in fp_types(
            text, "68123456" if "68123456" in text else "25620141"
        ), text


def test_order_number_near_a_pupil_still_id_number():
    # The long-pinned boundary: a pupil buying something is an order number.
    text = "นักเรียนสั่งซื้อสินค้ารหัส 88910423"
    types = fp_types(text, "88910423")
    assert "STUDENT_ID" not in types
    assert "ID_NUMBER" in types


def test_hr_applicant_without_education_context_stays_id_number():
    # ผู้สมัครงาน + คัดเลือก reads as hiring, not enrollment; no education
    # token means no STUDENT_ID.
    text = "ผู้สมัครงานรหัส 69011003 ผ่านการคัดเลือกตำแหน่งเจ้าหน้าที่ธุรการ"
    assert "STUDENT_ID" not in fp_types(text, "69011003")


def test_bank_cue_still_owns_the_account_even_with_students_around():
    text = "เลขบัญชีสำหรับรับบริจาค 1234567890 นักศึกษาสามารถโอนได้ทุกสาขา"
    types = fp_types(text, "1234567890")
    assert "BANK_ACCOUNT" in types
    assert "STUDENT_ID" not in types


def test_commerce_cue_on_previous_line_does_not_veto():
    # The veto is about which cue owns THESE digits, not about commerce words
    # elsewhere in the document.
    text = "ใบแจ้งหนี้ 77881122\nรหัส 65014477 ลงทะเบียนเรียนแล้ว"
    assert "STUDENT_ID" in fp_types(text, "65014477")
    assert "STUDENT_ID" not in fp_types(text, "77881122")


# ── honesty: uncued bank shape with a รหัส introducer ──────────────────────


def test_intro_coded_10_digit_without_bank_cue_is_id_number_not_bank():
    # "รหัส <10 digits>" with no bank cue and no education context: we cannot
    # know it is a student id, but calling it a bank account is a fabrication.
    text = "อ้างถึงรหัส 6801442901 ในหนังสือฉบับก่อนหน้า"
    types = fp_types(text, "6801442901")
    assert "BANK_ACCOUNT" not in types
    assert "ID_NUMBER" in types


def test_cued_bank_account_unaffected_by_the_demotion():
    text = "โอนเข้าบัญชีเลขที่ 6801442901 ธนาคารตัวอย่าง"
    assert "BANK_ACCOUNT" in fp_types(text, "6801442901")
