"""Report generation."""

import re
from dataclasses import dataclass

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.models import Entity
from pii_redactor.reid_risk import ReidRiskResult, assess_reid_risk


@dataclass
class PDPAReport:
    direct_pii_count: int  # fp + tb entities
    fp_count: int
    tb_count: int
    section26_flags: list[str]  # sensitive categories found (not redacted, just flagged)
    reid_risk: ReidRiskResult
    overall_score: float  # combined 0-100
    overall_grade: str  # A-F
    recommendations: list[str]


# Section 26 Sensitive Categories
# Keyword flags only — these are reported but NOT auto-redacted.
_SECTION26_KEYWORDS = {
    "RACE_ETHNICITY": re.compile(r"(?:เชื้อชาติ|เผ่าพันธุ์|สัญชาติ)", re.UNICODE),
    "POLITICAL_OPINION": re.compile(r"(?:ความคิดเห็นทางการเมือง|พรรคการเมือง|อุดมการณ์)", re.UNICODE),
    "RELIGION": re.compile(r"(?:ศาสนา|ความเชื่อ|พุทธ|คริสต์|อิสลาม|ฮินดู)", re.UNICODE),
    "HEALTH": re.compile(r"(?:โรค|การรักษา|ผล(?:การ)?ตรวจ|สุขภาพ|ประวัติ(?:การ)?รักษา)", re.UNICODE),
    "SEXUAL_BEHAVIOR": re.compile(r"(?:เพศ(?:สัมพันธ์|วิถี)|รสนิยมทางเพศ)", re.UNICODE),
    "CRIMINAL_RECORD": re.compile(r"(?:คดี|ต้องโทษ|จำคุก|ประวัติอาชญากรรม|ถูกฟ้อง)", re.UNICODE),
    "DISABILITY": re.compile(r"(?:ทุพพลภาพ|ความพิการ|คนพิการ)", re.UNICODE),
    "LABOR_UNION": re.compile(r"(?:สหภาพแรงงาน|สมาคมลูกจ้าง)", re.UNICODE),
}


def scan_section26(text: str) -> list[dict]:
    """Find Section 26 sensitive-category matches with their spans.

    Returns one entry per category found (first match), each a dict with
    keys: category, text, start, end. Flag-only — never used for redaction.
    """
    hits: list[dict] = []
    for category, pattern in _SECTION26_KEYWORDS.items():
        m = pattern.search(text)
        if m:
            hits.append(
                {
                    "category": category,
                    "text": m.group(0),
                    "start": m.start(),
                    "end": m.end(),
                }
            )
    return hits


def _generate_report(text: str, entities: list[Entity]) -> PDPAReport:
    """Build the report from the canonical detector output."""
    fp_count = sum(entity.redact_type == "FP" for entity in entities)
    direct_pii_count = len(entities)

    # Section 26 scan
    section26_flags = []
    for category, pattern in _SECTION26_KEYWORDS.items():
        if pattern.search(text):
            section26_flags.append(category)

    # Re-identification risk
    reid = assess_reid_risk(text)

    # Overall score: max of (PII score, reid score, section26 weight)
    pii_score = min(direct_pii_count * 15.0, 100.0)
    s26_score = len(section26_flags) * 20.0  # Each s26 category = 20 points
    overall = max(pii_score, reid.score, min(s26_score, 100.0))

    if overall <= 20:
        grade = "A"
    elif overall <= 40:
        grade = "B"
    elif overall <= 60:
        grade = "C"
    elif overall <= 80:
        grade = "D"
    else:
        grade = "F"

    # Recommendations
    recommendations = []
    if direct_pii_count > 0:
        recommendations.append(f"Remove or pseudonymize {direct_pii_count} direct PII entities.")
    if section26_flags:
        recommendations.append(
            f"Section 26 sensitive data found ({', '.join(section26_flags)}). "
            "Explicit consent required under PDPA."
        )
    if reid.high_risk_combo:
        recommendations.append(
            "Remove quasi-identifier combinations to reduce re-identification risk."
        )
    if overall >= 60:
        recommendations.append(
            "Consider data minimization — only collect data necessary for the purpose."
        )

    return PDPAReport(
        direct_pii_count=direct_pii_count,
        fp_count=fp_count,
        tb_count=direct_pii_count - fp_count,
        section26_flags=section26_flags,
        reid_risk=reid,
        overall_score=overall,
        overall_grade=grade,
        recommendations=recommendations,
    )


def generate_report(text: str) -> PDPAReport:
    """Generate a PDPA risk report without changing the text."""
    return _generate_report(text, detect_all(text))


def _risk_label(score: float) -> str:
    return (
        "Very Low Risk"
        if score <= 20
        else "Low Risk"
        if score <= 40
        else "Medium Risk"
        if score <= 60
        else "High Risk"
        if score <= 80
        else "Very High Risk"
    )


def analyze_text(text: str) -> dict:
    """Build the shared PDPA response for clean text.

    The API, PDF report, and worker use this same result.
    """
    entities = detect_all(text)
    report = _generate_report(text, entities)
    reid = report.reid_risk

    # entity breakdown per data_type
    breakdown_map: dict[tuple[str, str], dict] = {}
    for e in entities:
        key = (e.data_type, e.redact_type)
        if key not in breakdown_map:
            breakdown_map[key] = {
                "data_type": e.data_type,
                "redact_type": e.redact_type,
                "count": 0,
            }
        breakdown_map[key]["count"] += 1
    breakdown = sorted(breakdown_map.values(), key=lambda x: -x["count"])

    section26 = scan_section26(text)
    # Semantic pass: flag free-form sensitive content the keywords miss.
    # No-op (empty) when sentence-transformers is not installed.
    try:
        from pii_redactor.sensitive_detector import detect_sensitive

        have = {s["category"] for s in section26}
        for hit in detect_sensitive(text):
            if hit["category"] not in have:
                section26 = section26 + [{**hit, "source": "semantic"}]
                have.add(hit["category"])
    except Exception:  # pragma: no cover - defensive; model issues never block analyze
        pass

    # structured recommendations with severity levels
    recs = []
    if report.direct_pii_count > 0:
        recs.append(
            {
                "level": "high",
                "title": f"Remove or pseudonymize {report.direct_pii_count} direct PII entities",
                "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
            }
        )
    if section26:
        cats = ", ".join(s["category"] for s in section26)
        recs.append(
            {
                "level": "high",
                "title": f"Section 26 sensitive data found ({cats})",
                "desc": "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
            }
        )
    if reid.high_risk_combo:
        recs.append(
            {
                "level": "medium",
                "title": "Remove quasi-identifier combinations to reduce re-identification risk",
                "desc": "การรวม gender + district + age สามารถระบุตัวบุคคลได้แม้ไม่มี PII โดยตรง",
            }
        )
    if report.overall_score >= 60:
        recs.append(
            {
                "level": "info",
                "title": "Consider data minimization",
                "desc": "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
            }
        )
    if not recs:
        recs.append(
            {
                "level": "info",
                "title": "No significant PDPA risk detected",
                "desc": "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
            }
        )

    return {
        "overall_score": report.overall_score,
        "overall_grade": report.overall_grade,
        "risk_label": _risk_label(report.overall_score),
        "direct_pii_count": report.direct_pii_count,
        "fp_count": report.fp_count,
        "tb_count": report.tb_count,
        "section26": section26,
        "reid": {
            "score": reid.score,
            "grade": reid.grade,
            "qi_found": reid.qi_found,
            "high_risk_combo": reid.high_risk_combo,
        },
        "breakdown": breakdown,
        "recommendations": recs,
    }
