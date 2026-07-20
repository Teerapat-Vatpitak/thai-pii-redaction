"""Re-identification risk assessment."""

import re
from dataclasses import dataclass


@dataclass
class ReidRiskResult:
    score: float  # 0.0 to 100.0
    grade: str  # "A" | "B" | "C" | "D" | "F"
    qi_found: list[str]  # quasi-identifiers detected (e.g. ["gender", "district", "date_of_birth"])
    high_risk_combo: bool  # True if {gender + district + (DOB|age)} combo found
    warnings: list[str]  # human-readable warnings


# Quasi-identifier detection patterns
_QI_PATTERNS = {
    "gender": re.compile(r"(?:นาย|นาง(?:สาว)?|ด\.ช\.|ด\.ญ\.)\s*\w", re.UNICODE),
    "date_of_birth": re.compile(r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}-\d{2}-\d{2})\b"),
    "age": re.compile(r"(?:อายุ\s*\d+\s*ปี|\d+\s*ขวบ)", re.UNICODE),
    "district": re.compile(r"(?:แขวง|ตำบล)\s*\w+", re.UNICODE),
    "province": re.compile(r"(?:จังหวัด|จ\.)\s*\w+", re.UNICODE),
    "occupation": re.compile(r"(?:อาชีพ|ทำงาน(?:เป็น)?|ประกอบอาชีพ)\s*\w+", re.UNICODE),
    "religion": re.compile(r"(?:ศาสนา|พุทธ|คริสต์|อิสลาม|ฮินดู|ซิกข์)", re.UNICODE),
}


def assess_reid_risk(text: str) -> ReidRiskResult:
    """
    Assess re-identification risk from quasi-identifiers in text.

    Quasi-identifiers detected:
    - gender: Thai title prefixes (นาย/นาง/นางสาว/ด.ช./ด.ญ.)
    - date_of_birth: any date pattern (reuse fp_detector DATE_OF_BIRTH logic)
    - age: Thai age pattern (อายุ N ปี, N ขวบ)
    - district: Thai district keywords (แขวง/ตำบล + name)
    - province: Thai province keywords (จังหวัด + name)
    - occupation: Thai occupation keywords (อาชีพ/ทำงาน)
    - religion: mention of religion keywords

    Risk score:
    - Base: 0
    - Each unique QI type: +10 points
    - Mandatory HIGH if combo {gender + district + (date_of_birth OR age)}
    - Cap at 100

    Grades: 0-20=A, 21-40=B, 41-60=C, 61-80=D, 81+=F
    """
    qi_found = []

    for qi_type, pattern in _QI_PATTERNS.items():
        if pattern.search(text):
            qi_found.append(qi_type)

    # Score: 10 per QI type
    score = len(qi_found) * 10.0

    # High-risk combo check
    has_gender = "gender" in qi_found
    has_district = "district" in qi_found
    has_dob_or_age = "date_of_birth" in qi_found or "age" in qi_found
    high_risk_combo = has_gender and has_district and has_dob_or_age

    if high_risk_combo:
        score = max(score, 85.0)  # Mandatory F-range

    score = min(score, 100.0)

    # Grade
    if score <= 20:
        grade = "A"
    elif score <= 40:
        grade = "B"
    elif score <= 60:
        grade = "C"
    elif score <= 80:
        grade = "D"
    else:
        grade = "F"

    # Warnings
    warnings = []
    if high_risk_combo:
        warnings.append(
            "High re-identification risk: gender + district + (age/DOB) combination detected. "
            "This combination may uniquely identify a person even without direct PII."
        )
    if "religion" in qi_found:
        warnings.append("Religion mentioned — PDPA Section 26 sensitive category.")
    if score >= 60:
        warnings.append(
            f"Re-identification risk score {score:.0f}/100 — consider removing quasi-identifiers."
        )

    return ReidRiskResult(
        score=score,
        grade=grade,
        qi_found=qi_found,
        high_risk_combo=high_risk_combo,
        warnings=warnings,
    )
