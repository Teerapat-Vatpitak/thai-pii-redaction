"""Format-preserving (FP) PII detector using regex + checksum validation."""
from __future__ import annotations

import re
import uuid

from pii_redactor.models import Entity
from pii_redactor.detectors.thai_id import is_valid_thai_id


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------

def _luhn_check(digits: str) -> bool:
    """Return True if digits pass the Luhn algorithm."""
    if not digits:
        return False
    try:
        total = 0
        for i, ch in enumerate(reversed(digits)):
            n = int(ch)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        return total % 10 == 0
    except Exception:
        return False


def _iban_check(iban: str) -> bool:
    """Return True if the IBAN passes the mod-97 check."""
    try:
        # Move first 4 chars to end
        rearranged = iban[4:] + iban[:4]
        # Replace letters with digits: A=10, B=11, ... Z=35
        digits = ""
        for ch in rearranged:
            if ch.isalpha():
                digits += str(ord(ch.upper()) - ord("A") + 10)
            else:
                digits += ch
        return int(digits) % 97 == 1
    except Exception:
        return False


def _date_sanity(day: int, month: int) -> bool:
    """Return True if day is 1-31 and month is 1-12."""
    return 1 <= day <= 31 and 1 <= month <= 12


# ---------------------------------------------------------------------------
# Entity factory
# ---------------------------------------------------------------------------

def _make_entity(data_type: str, match: re.Match, text: str, score: float = 1.0) -> Entity:
    start, end = match.start(1), match.end(1)
    return Entity(
        entity_id=str(uuid.uuid4()),
        redact_type="FP",
        data_type=data_type,
        span=(start, end),
        score=score,
        original_text=text[start:end],
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(entities: list[Entity]) -> list[Entity]:
    """Remove overlapping spans; prefer higher score, then first occurrence."""
    sorted_ents = sorted(entities, key=lambda e: (e.span[0], -e.score))
    kept: list[Entity] = []
    for ent in sorted_ents:
        if (ent.span[1] - ent.span[0]) < 2:
            continue
        overlaps = any(
            not (ent.span[1] <= k.span[0] or ent.span[0] >= k.span[1])
            for k in kept
        )
        if not overlaps:
            kept.append(ent)
    return sorted(kept, key=lambda e: e.span[0])


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Numeric PII uses digit-boundary lookarounds (?<!\d)...(?!\d) instead of \b.
# In Unicode-aware regex a Thai letter is a "word" character, so \b does NOT
# fire between Thai script and a digit -- a value glued to Thai text (e.g.
# "เลขบัตรประชาชน1101700230708") slipped past every \b-anchored pattern. The
# digit-boundary lookarounds still reject a value embedded in a longer number
# while allowing letter/Thai adjacency (recall > precision).
_RE_THAI_ID = re.compile(
    r"(?<!\d)(\d{1}[-\s]?\d{4}[-\s]?\d{5}[-\s]?\d{2}[-\s]?\d{1})(?!\d)"
)
_RE_CREDIT_CARD = re.compile(
    r"(?<!\d)(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})(?!\d)"
)
_RE_IBAN = re.compile(
    r"\b([A-Z]{2}\d{2}[A-Z0-9]{4,30})\b"
)
_RE_EMAIL = re.compile(
    r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b"
)
_RE_PHONE_MOBILE = re.compile(
    r"(?<!\d)(0[6-9]\d[-\s]?\d{3}[-\s]?\d{4})(?!\d)"
)
_RE_PHONE_LANDLINE = re.compile(
    r"(?<!\d)(0[2-5]\d[-\s]?\d{3}[-\s]?\d{4})(?!\d)"
)
# +66 form drops the national leading 0, so a Thai number carries 8 (landline)
# or 9 (mobile) digits after +66 -- e.g. +66 81 234 5678 is 9. The old pattern
# only matched 8, missing every mobile and leaking it to the STUDENT_ID
# catch-all. Allow an optional single separator between any two digits.
_RE_PHONE_INTL = re.compile(
    r"(?<![a-zA-Z0-9_])(\+66[-\s]?\d(?:[-\s]?\d){7,8})(?!\d)"
)
_RE_BANK_ACCOUNT_1 = re.compile(
    r"(?<!\d)(\d{3}[-\s]?\d{1}[-\s]?\d{5}[-\s]?\d{1})(?!\d)"
)
_RE_BANK_ACCOUNT_2 = re.compile(
    r"(?<!\d)(\d{7}[-\s]?\d{3})(?!\d)"
)
_RE_DATE = re.compile(
    r"(?<!\d)(\d{1,2}[/\-]\d{1,2}[/\-](?:\d{4}|\d{2}))(?!\d)"
)
_RE_VEHICLE_PLATE = re.compile(
    r"([ก-ฮ]{1,3}\s*\d{1,4})"
)
_RE_PASSPORT_TH = re.compile(
    r"\b([A-Z]{2}\d{7})\b"
)
_RE_PASSPORT = re.compile(
    r"\b([A-Z]{1,2}\d{6,9})\b"
)
_RE_STUDENT_ID = re.compile(
    r"(?<!\d)(\d{8,12})(?!\d)"
)

_SEP_RE = re.compile(r"[-\s]")
_THAI_CHAR_RE = re.compile(r"[฀-๿]")


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

def detect_fp(text: str) -> list[Entity]:
    """
    Detect format-preserving PII entities in text using regex + checksum.

    Returns list of Entity objects (redact_type="FP", score=1.0).
    Sorted by span start (ascending).
    Deduplicated: no overlapping spans (keep highest-score; for same score, keep first).
    Span chokepoint: reject any span where (end - start) < 2 chars.
    """
    candidates: list[Entity] = []

    # 1. THAI_ID
    for m in _RE_THAI_ID.finditer(text):
        raw = _SEP_RE.sub("", m.group(1))
        if len(raw) == 13 and is_valid_thai_id(raw):
            candidates.append(_make_entity("THAI_ID", m, text, score=1.0))

    # 2. CREDIT_CARD
    for m in _RE_CREDIT_CARD.finditer(text):
        raw = _SEP_RE.sub("", m.group(1))
        if len(raw) == 16 and _luhn_check(raw):
            candidates.append(_make_entity("CREDIT_CARD", m, text, score=1.0))

    # 3. IBAN
    for m in _RE_IBAN.finditer(text):
        if _iban_check(m.group(1)):
            candidates.append(_make_entity("IBAN", m, text, score=1.0))

    # 4. EMAIL
    for m in _RE_EMAIL.finditer(text):
        candidates.append(_make_entity("EMAIL", m, text, score=1.0))

    # 5. PHONE (mobile, landline, international)
    for pattern in (_RE_PHONE_MOBILE, _RE_PHONE_LANDLINE, _RE_PHONE_INTL):
        for m in pattern.finditer(text):
            candidates.append(_make_entity("PHONE", m, text, score=1.0))

    # 6. BANK_ACCOUNT (two patterns)
    for pattern in (_RE_BANK_ACCOUNT_1, _RE_BANK_ACCOUNT_2):
        for m in pattern.finditer(text):
            candidates.append(_make_entity("BANK_ACCOUNT", m, text, score=1.0))

    # 7. DATE_OF_BIRTH
    for m in _RE_DATE.finditer(text):
        raw = m.group(1)
        parts = re.split(r"[/\-]", raw)
        if len(parts) == 3:
            try:
                day = int(parts[0])
                month = int(parts[1])
                if _date_sanity(day, month):
                    candidates.append(_make_entity("DATE_OF_BIRTH", m, text, score=1.0))
            except ValueError:
                pass

    # 8. VEHICLE_PLATE
    # Reject matches where the Thai consonants are mid-word (preceded by a Thai char)
    for m in _RE_VEHICLE_PLATE.finditer(text):
        start = m.start(1)
        if start > 0 and _THAI_CHAR_RE.match(text[start - 1]):
            continue
        candidates.append(_make_entity("VEHICLE_PLATE", m, text, score=0.9))

    # 9. PASSPORT (Thai format first, then general)
    for pattern in (_RE_PASSPORT_TH, _RE_PASSPORT):
        for m in pattern.finditer(text):
            candidates.append(_make_entity("PASSPORT", m, text, score=1.0))

    # 10. STUDENT_ID (low priority; deduplication handles overlap)
    for m in _RE_STUDENT_ID.finditer(text):
        candidates.append(_make_entity("STUDENT_ID", m, text, score=0.8))

    return _deduplicate(candidates)
