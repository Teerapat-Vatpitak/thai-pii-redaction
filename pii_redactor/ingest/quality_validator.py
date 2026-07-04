"""Input quality validation."""
from dataclasses import dataclass

OCR_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class QualityResult:
    quality_score: float            # 0.0 to 100.0
    grade: str                      # "A" (80+), "B" (60-79), "C" (40-59), "D" (20-39), "F" (<20)
    warnings: list[str]             # human-readable warning messages
    pattern_ok: bool                # Pattern validation passed
    structure_ok: bool              # Structure validation passed
    ocr_confidence_ok: bool         # OCR confidence ok (True if not pdf_hybrid)


def _pattern_validation(text: str, min_thai_ratio: float) -> tuple[bool, list[str]]:
    """Returns (ok, warnings)"""
    warnings = []

    if not text or not text.strip():
        return False, ["Text is empty"]

    # Count Thai characters (Unicode range U+0E00-U+0E7F)
    thai_chars = sum(1 for c in text if '฀' <= c <= '๿')
    total_non_space = sum(1 for c in text if not c.isspace())

    if total_non_space == 0:
        return False, ["Text contains only whitespace"]

    thai_ratio = thai_chars / total_non_space
    if thai_ratio < min_thai_ratio:
        warnings.append(
            f"Low Thai character ratio: {thai_ratio:.1%} (expected >= {min_thai_ratio:.1%})"
        )

    # Check for garbled text (high proportion of replacement characters)
    replacement_count = text.count('?') + text.count('�')
    if replacement_count / max(total_non_space, 1) > 0.05:
        warnings.append(f"High replacement character ratio: {replacement_count} found")

    ok = len(warnings) == 0 or thai_ratio >= min_thai_ratio
    return ok, warnings


def _structure_validation(text: str) -> tuple[bool, list[str]]:
    """Returns (ok, warnings)"""
    warnings = []

    lines = [l for l in text.split('\n') if l.strip()]

    if len(lines) == 0:
        return False, ["No non-empty lines found"]

    avg_line_len = sum(len(l) for l in lines) / len(lines)
    if avg_line_len < 3:
        warnings.append(f"Very short average line length: {avg_line_len:.1f} chars")

    single_char_lines = sum(1 for l in lines if len(l.strip()) == 1)
    if len(lines) > 5 and single_char_lines / len(lines) > 0.3:
        warnings.append(
            f"High single-character line ratio: {single_char_lines}/{len(lines)}"
        )

    ok = len(warnings) == 0
    return ok, warnings


def _ocr_confidence_validation(
    source_type: str,
    ocr_confidence: float | None
) -> tuple[bool, list[str]]:
    """Returns (ok, warnings)"""
    if source_type != "pdf_hybrid":
        return True, []

    if ocr_confidence is None:
        return True, ["OCR confidence not provided for pdf_hybrid source"]

    warnings = []
    if ocr_confidence < OCR_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Low OCR confidence: {ocr_confidence:.1%} "
            f"(threshold: {OCR_CONFIDENCE_THRESHOLD:.0%})"
        )

    ok = ocr_confidence >= OCR_CONFIDENCE_THRESHOLD
    return ok, warnings


def _compute_score(pattern_ok: bool, structure_ok: bool, ocr_ok: bool,
                   all_warnings: list[str]) -> tuple[float, str]:
    """Returns (score, grade)"""
    score = 100.0

    if not pattern_ok:
        score -= 40.0
    elif any("replacement" in w for w in all_warnings):
        score -= 15.0

    if not structure_ok:
        score -= 30.0
    elif any("short average" in w for w in all_warnings):
        score -= 10.0
    elif any("single-character" in w for w in all_warnings):
        score -= 15.0

    if not ocr_ok:
        score -= 30.0
    elif any("OCR confidence" in w for w in all_warnings):
        score -= 20.0

    score = max(0.0, min(100.0, score))

    if score >= 80:
        grade = "A"
    elif score >= 60:
        grade = "B"
    elif score >= 40:
        grade = "C"
    elif score >= 20:
        grade = "D"
    else:
        grade = "F"

    return score, grade


def validate(
    text: str,
    source_type: str,
    *,
    ocr_confidence: float | None = None,
    min_thai_ratio: float = 0.1,
) -> QualityResult:
    """
    Validate cleaned text quality before PII detection.

    source_type: "text" | "pdf_text" | "pdf_hybrid"
    """
    pattern_ok, pattern_warnings = _pattern_validation(text, min_thai_ratio)
    structure_ok, structure_warnings = _structure_validation(text)
    ocr_ok, ocr_warnings = _ocr_confidence_validation(source_type, ocr_confidence)

    all_warnings = pattern_warnings + structure_warnings + ocr_warnings
    score, grade = _compute_score(pattern_ok, structure_ok, ocr_ok, all_warnings)

    return QualityResult(
        quality_score=score,
        grade=grade,
        warnings=all_warnings,
        pattern_ok=pattern_ok,
        structure_ok=structure_ok,
        ocr_confidence_ok=ocr_ok,
    )
