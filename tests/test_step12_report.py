from pii_redactor.reid_risk import ReidRiskResult, assess_reid_risk
from pii_redactor.report import PDPAReport, analyze_text, generate_report


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


def test_analyze_text_assembles_the_shared_analysis_without_the_web_layer():
    """The one function three callers share, tested where it now lives.

    It sat in `app/server.py` until 2026-07-29, so it was only ever reached
    through the FastAPI TestClient and was invisible to the core-only CI job.
    Nothing in it needs the web layer — this test is what says so.
    """
    result = analyze_text("ผมชื่อ นายสมชาย ใจดี โทร 081-234-5678 เลขบัตร 1101700230708")

    assert result["direct_pii_count"] >= 1
    assert result["overall_grade"] in {"A", "B", "C", "D", "F"}
    assert result["risk_label"].endswith("Risk")
    assert sum(row["count"] for row in result["breakdown"]) >= 1
    assert result["recommendations"], "an analysis always says something"
    assert set(result["reid"]) == {"score", "grade", "qi_found", "high_risk_combo"}


def test_analyze_text_still_answers_on_a_document_with_nothing_in_it():
    result = analyze_text("Hello world.")

    assert result["direct_pii_count"] == 0
    assert result["overall_grade"] == "A"
    assert result["breakdown"] == []
    assert result["recommendations"], "a clean document still gets a verdict"


def test_analyze_text_matches_the_canonical_fallback_detector():
    result = analyze_text("รหัส 1234567890123 โทร 081-234-5678")

    assert result["direct_pii_count"] == 2
    assert result["fp_count"] == 2
    assert result["tb_count"] == 0
    assert sum(row["count"] for row in result["breakdown"]) == 2
    assert {row["data_type"] for row in result["breakdown"]} == {"PHONE", "THAI_ID"}


def test_analyze_text_runs_detection_once(monkeypatch):
    import pii_redactor.report as report_module
    from pii_redactor.models import Entity

    calls = []

    def fake_detect(text):
        calls.append(text)
        return [
            Entity(
                entity_id="test-id",
                redact_type="FP",
                data_type="THAI_ID",
                span=(0, 13),
                score=0.6,
                original_text=text[:13],
            )
        ]

    monkeypatch.setattr(report_module, "detect_all", fake_detect)
    result = report_module.analyze_text("1234567890123")

    assert calls == ["1234567890123"]
    assert result["direct_pii_count"] == 1
