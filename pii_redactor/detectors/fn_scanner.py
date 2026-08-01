"""False-negative (FN) second pass scanner using lightweight regex patterns."""

from __future__ import annotations

import re
import uuid

from pii_redactor.detectors.fp_detector import _NON_STUDENT_NUM_CUE_RE, _STUDENT_INTRO_RE
from pii_redactor.models import Entity

# ---------------------------------------------------------------------------
# Patterns for common false-negative scenarios
# ---------------------------------------------------------------------------

_FN_PATTERNS: list[tuple[re.Pattern[str], str, str, float]] = [
    # 13-digit sequences not caught (checksum failed but highly suspicious).
    # THAI_ID/EMAIL/DATE_OF_BIRTH are all format-preserving types -- redact_type
    # must be "FP" (matching fp_detector's own classification of these same
    # data_types) so anonymizer.py routes them through generate_fp() for a
    # realistic fake value instead of tb_generator's literal "[REDACTED_x]"
    # fallback.
    # Digit-boundary lookarounds, not \b: a Thai letter is a word char, so \b
    # never fires between Thai script and a digit, letting a 13-digit run glued
    # to Thai text ("รหัส1234567890123") slip past this fallback too.
    (re.compile(r"(?<!\d)(\d{13})(?!\d)"), "THAI_ID", "FP", 0.6),
    # Email-like patterns with @ (simpler than full RFC pattern)
    (re.compile(r"([^\s@]+@[^\s@]+\.[^\s@]{2,})"), "EMAIL", "FP", 0.7),
    # Date-like patterns in various formats. Labeled DATE (not DATE_OF_BIRTH):
    # this loose fallback has no cue context to gate on, so the honest generic
    # label is the only defensible one here (see fp_detector.py's cue-gated
    # DATE/DATE_OF_BIRTH split for the primary pass).
    # day-first (dd-mm-yyyy) OR ISO year-first (yyyy-mm-dd).
    (
        re.compile(r"(?<!\d)(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})(?!\d)"),
        "DATE",
        "FP",
        0.6,
    ),
]


# ---------------------------------------------------------------------------
# Corrupted-duplicate structured id scan (F4).
#
# The OCR retry merge (ingest/ocr_processor.py) can leave a second, corrupted
# copy of a structured value beside the valid read -- e.g. "13122+1506581"
# next to the valid "1312271505581". The corrupt copy matches neither
# fp_detector's regex nor its checksum, so without this rule 12 of 13 digits
# of a national id leave unmasked on the text path (/api/sanitize, roundtrip).
#
# Rule: a run of length 12-15 that is digits except for 1-2 INNER (not
# leading/trailing) non-digit "junk" characters is tagged ID_NUMBER -- honest
# label, since the checksum cannot be verified on a corrupt read. The junk
# character set is deliberately narrow and evidence-based (+ $ #): comma and
# period are excluded on purpose, since a thousands/decimal-separated amount
# like "1,234,567.89" is the likeliest real-world false-positive source; Thai
# characters and letters are excluded because they were never observed in the
# OCR corruption evidence.
#
# Cue gate: the rule above describes the SHAPE of an OCR-corrupted id, and an
# ordinary summed amount has the same shape ("รวมเป็นเงิน 600000+120000 = 720000
# บาท" -> a 13-char digit run with one inner "+"). So the same nearest-cue-wins
# idiom fp_detector uses for STUDENT_ID/bank/phone decides: an amount or order
# introducer NEARER to the run than an id introducer suppresses the tag. The
# amount side is imported from fp_detector rather than restated -- a second copy
# is how the two rules would drift. Default is KEEP (recall > precision): a run
# with no cue on either side, which is the register the corrupted-id evidence
# came from, is still tagged. Windows are clipped at the line, since the cue and
# the value share a line in form and invoice text alike.
#
# The ID side needs its own pattern and cannot just BE fp_detector's
# `_STUDENT_INTRO_RE`: that one introduces a STUDENT id
# (รหัสประจำตัว|เลขประจำตัว|รหัส|id) and knows nothing about national-id-card
# phrasing, so "ค่าธรรมเนียม 500 บาท เลขบัตร 13122+1506581" found no id cue at
# all and the fee's บาท suppressed a REAL corrupted national id. The card
# phrasings below are evidenced -- gold's own gov-form document gf08 labels a
# THAI_ID with "เลขที่บัตรประชาชน". Longest alternative first so the widest
# label is the one that matches.
_AMOUNT_CUE_RE = re.compile(
    _NON_STUDENT_NUM_CUE_RE.pattern + r"|รวม|บาท|total",
    re.IGNORECASE,
)
_CORRUPTED_ID_CUE_RE = re.compile(
    _STUDENT_INTRO_RE.pattern
    + r"|เลขที่บัตรประชาชน|เลขบัตรประชาชน|เลขประจำตัวประชาชน|บัตรประชาชน"
    + r"|เลขที่บัตร|เลขบัตร|เลขประชาชน|national id",
    re.IGNORECASE,
)
_CORRUPTED_ID_CUE_WINDOW = 40
_CORRUPTED_ID_JUNK_CHARS = "+$#"
_CORRUPTED_ID_CANDIDATE_RE = re.compile(r"(?<![0-9+$#])[0-9+$#]+(?![0-9+$#])")


def _nearest_cue_distance(pattern: re.Pattern[str], text: str, start: int, end: int) -> int | None:
    """Chars between the candidate and the nearest `pattern` match on its line.

    Looks both ways inside `_CORRUPTED_ID_CUE_WINDOW`, clipped at the nearest
    newline on each side. Returns None when the pattern does not occur there.
    """
    before = text[max(0, start - _CORRUPTED_ID_CUE_WINDOW) : start]
    before = before.rsplit("\n", 1)[-1]
    after = text[end : end + _CORRUPTED_ID_CUE_WINDOW]
    after = after.split("\n", 1)[0]

    best: int | None = None
    for m in pattern.finditer(before):
        distance = len(before) - m.end()
        if best is None or distance < best:
            best = distance
    first_after = pattern.search(after)
    if first_after is not None and (best is None or first_after.start() < best):
        best = first_after.start()
    return best


def _competing_amount_cue_wins(text: str, start: int, end: int) -> bool:
    amount = _nearest_cue_distance(_AMOUNT_CUE_RE, text, start, end)
    if amount is None:
        return False
    id_cue = _nearest_cue_distance(_CORRUPTED_ID_CUE_RE, text, start, end)
    # Tie goes to the id cue -- recall > precision.
    return id_cue is None or amount < id_cue


def _is_corrupted_id_candidate(candidate: str) -> bool:
    if not (12 <= len(candidate) <= 15):
        return False
    if not candidate[0].isdigit() or not candidate[-1].isdigit():
        return False
    junk_count = sum(1 for ch in candidate if ch in _CORRUPTED_ID_JUNK_CHARS)
    non_digit_count = sum(1 for ch in candidate if not ch.isdigit())
    if junk_count != non_digit_count:
        # Defensive: candidate class is [0-9+$#], so this cannot happen.
        return False
    return junk_count in (1, 2)


def scan_fn(text: str, existing_entities: list[Entity]) -> list[Entity]:
    """
    False-negative second pass: lightweight regex scan for PII patterns
    not already caught by fp_detector or tb_detector.

    Returns NEW entities only (no duplicates of existing_entities spans).
    """
    existing_spans = {(e.span[0], e.span[1]) for e in existing_entities}

    new_entities: list[Entity] = []
    for pattern, data_type, redact_type, score in _FN_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.start(1), m.end(1)
            if end - start < 2:
                continue
            # Skip if this span overlaps with any existing entity
            overlaps = any(not (end <= es[0] or start >= es[1]) for es in existing_spans)
            if not overlaps:
                new_entities.append(
                    Entity(
                        entity_id=str(uuid.uuid4()),
                        redact_type=redact_type,
                        data_type=data_type,
                        span=(start, end),
                        score=score,
                        original_text=text[start:end],
                    )
                )
                existing_spans.add((start, end))

    for m in _CORRUPTED_ID_CANDIDATE_RE.finditer(text):
        start, end = m.start(), m.end()
        candidate = text[start:end]
        if not _is_corrupted_id_candidate(candidate):
            continue
        if _competing_amount_cue_wins(text, start, end):
            continue
        overlaps = any(not (end <= es[0] or start >= es[1]) for es in existing_spans)
        if overlaps:
            continue
        new_entities.append(
            Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="FP",
                data_type="ID_NUMBER",
                span=(start, end),
                score=0.6,
                original_text=candidate,
            )
        )
        existing_spans.add((start, end))

    return sorted(new_entities, key=lambda e: e.span[0])
