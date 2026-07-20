from pii_redactor.reid_risk import ReidRiskResult, assess_reid_risk
from pii_redactor.report import PDPAReport, generate_report


def test_reid_risk_no_qi():
    result = assess_reid_risk("The weather is nice today.")
    assert isinstance(result, ReidRiskResult)
    assert result.score == 0.0
    assert result.grade == "A"
    assert result.qi_found == []
    assert not result.high_risk_combo


def test_reid_risk_gender_detected():
    result = assess_reid_risk("นาย สมชาย ทำงานที่บริษัท")
    assert "gender" in result.qi_found
    assert result.score >= 10.0


def test_reid_risk_high_risk_combo():
    text = "นาย สมชาย อายุ 35 ปี อาศัยอยู่ ตำบลบางกอก"
    result = assess_reid_risk(text)
    assert result.high_risk_combo
    assert result.score >= 85.0
    assert result.grade == "F"
    assert len(result.warnings) > 0


def test_reid_risk_date_detected():
    result = assess_reid_risk("เกิดวันที่ 15/06/1990")
    assert "date_of_birth" in result.qi_found


def test_reid_risk_grade_f():
    text = "นาง สมหญิง อายุ 40 ปี ตำบลลาดพร้าว จังหวัดกรุงเทพ"
    result = assess_reid_risk(text)
    assert result.grade in ("D", "F")  # High enough score


def test_generate_report_returns_pdpa_report():
    result = generate_report("No PII here.")
    assert isinstance(result, PDPAReport)
    assert result.direct_pii_count == 0
    assert result.overall_grade == "A"


def test_generate_report_with_pii():
    text = "Call 081-234-5678 or email me at user@example.com"
    result = generate_report(text)
    assert result.direct_pii_count >= 1
    assert result.fp_count >= 1


def test_generate_report_section26_health():
    text = "ผู้ป่วยมีประวัติการรักษาโรคมะเร็ง"
    result = generate_report(text)
    assert "HEALTH" in result.section26_flags


def test_generate_report_section26_religion():
    text = "เขานับถือศาสนาอิสลาม"
    result = generate_report(text)
    assert "RELIGION" in result.section26_flags


def test_generate_report_recommendations_not_empty_with_pii():
    text = "โทรหา 081-234-5678"
    result = generate_report(text)
    assert len(result.recommendations) > 0


def test_generate_report_no_pii_no_s26_grade_a():
    result = generate_report("Hello world.")
    assert result.overall_grade == "A"
    assert result.direct_pii_count == 0
    assert result.section26_flags == []
