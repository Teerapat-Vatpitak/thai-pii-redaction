"""Report generation."""
import re
from dataclasses import dataclass

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.reid_risk import assess_reid_risk, ReidRiskResult


@dataclass
class PDPAReport:
    direct_pii_count: int          # fp + tb entities
    fp_count: int
    tb_count: int
    section26_flags: list[str]     # sensitive categories found (not redacted, just flagged)
    reid_risk: ReidRiskResult
    overall_score: float           # combined 0-100
    overall_grade: str             # A-F
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
            hits.append({
                "category": category,
                "text": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
    return hits


def generate_report(text: str) -> PDPAReport:
    """
    Generate a PDPA risk assessment report for the given text.
    Does NOT redact. Returns structured analysis.
    """
    fp_entities = detect_fp(text)
    tb_entities = detect_tb(text)

    direct_pii_count = len(fp_entities) + len(tb_entities)

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
        recommendations.append("Remove quasi-identifier combinations to reduce re-identification risk.")
    if overall >= 60:
        recommendations.append("Consider data minimization — only collect data necessary for the purpose.")

    return PDPAReport(
        direct_pii_count=direct_pii_count,
        fp_count=len(fp_entities),
        tb_count=len(tb_entities),
        section26_flags=section26_flags,
        reid_risk=reid,
        overall_score=overall,
        overall_grade=grade,
        recommendations=recommendations,
    )
