"""Format-preserving (FP) PII detector using regex + checksum validation."""

from __future__ import annotations

import re
import uuid

from pii_redactor.detectors.thai_id import is_valid_thai_id
from pii_redactor.models import Entity

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
    """Remove overlapping spans; prefer higher score, then first occurrence.

    Score is the PRIMARY key (DET-2). The old code sorted by (start, -score),
    i.e. earliest-start-wins, which contradicted this docstring and let a
    low-score VEHICLE_PLATE ("ปชช 1", 0.9) that started before a checksum-valid
    THAI_ID/PHONE/BANK/CREDIT_CARD (1.0) evict the real number via the greedy
    keep — leaking it entirely. A separator after the plate's first digit group
    (the normal way Thai IDs/phones are written) made this the common case, not
    an edge one. Sorting score-first keeps the checksum-backed number; ties fall
    back to earliest start so same-score ordering is unchanged."""
    sorted_ents = sorted(entities, key=lambda e: (-e.score, e.span[0]))
    kept: list[Entity] = []
    for ent in sorted_ents:
        if (ent.span[1] - ent.span[0]) < 2:
            continue
        overlaps = any(not (ent.span[1] <= k.span[0] or ent.span[0] >= k.span[1]) for k in kept)
        if not overlaps:
            kept.append(ent)
    return sorted(kept, key=lambda e: e.span[0])


# ---------------------------------------------------------------------------
# BANK vs PHONE context disambiguation
# ---------------------------------------------------------------------------


def _rightmost_cue(pattern: re.Pattern, ctx: str) -> int:
    """End offset of the cue nearest the number (rightmost match in ctx), or -1."""
    end = -1
    for m in pattern.finditer(ctx):
        end = m.end()
    return end


def _disambiguate_bank_phone(text: str, candidates: list[Entity]) -> list[Entity]:
    """Resolve spans that are ambiguously PHONE and BANK_ACCOUNT.

    A 10-digit number starting 06-09 matches both the mobile PHONE and the
    BANK_ACCOUNT patterns and, on a score tie, PHONE wins deduplication. When
    both candidates share a span, the cue nearest the number in the preceding
    ~30 chars decides: a bank cue keeps BANK, a phone cue keeps PHONE, a tie
    favours BANK, and no cue at all leaves the default (PHONE) untouched.
    """
    types_by_span: dict[tuple[int, int], set[str]] = {}
    for e in candidates:
        types_by_span.setdefault(e.span, set()).add(e.data_type)

    drop_phone: set[tuple[int, int]] = set()
    drop_bank: set[tuple[int, int]] = set()
    for span, types in types_by_span.items():
        if "PHONE" not in types or "BANK_ACCOUNT" not in types:
            continue
        ctx = text[max(0, span[0] - _CUE_WINDOW) : span[0]]
        bank = _rightmost_cue(_BANK_CUE_RE, ctx)
        phone = _rightmost_cue(_PHONE_CUE_RE, ctx)
        if bank < 0 and phone < 0:
            continue
        if bank >= phone:
            drop_phone.add(span)
        else:
            drop_bank.add(span)

    if not drop_phone and not drop_bank:
        return candidates
    out: list[Entity] = []
    for e in candidates:
        if e.data_type == "PHONE" and e.span in drop_phone:
            continue
        if e.data_type == "BANK_ACCOUNT" and e.span in drop_bank:
            continue
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Numeric PII uses digit-boundary lookarounds (?<!\d)...(?!\d) instead of \b.
# In Unicode-aware regex a Thai letter is a "word" character, so \b does NOT
# fire between Thai script and a digit -- a value glued to Thai text (e.g.
# "เลขบัตรประชาชน1101700230708") slipped past every \b-anchored pattern. The
# digit-boundary lookarounds still reject a value embedded in a longer number
# while allowing letter/Thai adjacency (recall > precision).
_RE_THAI_ID = re.compile(r"(?<!\d)(\d{1}[-\s]?\d{4}[-\s]?\d{5}[-\s]?\d{2}[-\s]?\d{1})(?!\d)")
_RE_CREDIT_CARD = re.compile(r"(?<!\d)(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4})(?!\d)")
# Total length is bounded 15-34 to match real IBANs (shortest is Norway at 15,
# longest is 34) -- the old {4,30} lower bound made the total minimum 8, which
# let a 9-char passport-length string ([A-Z]{2}\d{7}) both match the shape AND
# occasionally pass mod-97 by chance, stealing the span from PASSPORT even with
# an explicit passport cue right in front of it. Do not loosen this again.
_RE_IBAN = re.compile(r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b")
_RE_EMAIL = re.compile(r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")
_RE_PHONE_MOBILE = re.compile(r"(?<!\d)(0[- ]?[6-9]\d[-\s]?\d{3}[-\s]?\d{4})(?!\d)")
# Thai landlines are 9 digits (not 10). Two written shapes, both 9 digits:
#   Bangkok    02-XXX-XXXX  (2-digit area, then 3+4)
#   provincial 0XX-XXX-XXX  (3-digit area, then 3+3)
# The old pattern demanded a third area digit before the first separator, so it
# needed 10 digits and missed every standard landline (DET-1). Mobile numbers
# (0[6-9], 10 digits) stay with _RE_PHONE_MOBILE; the [2-7] second digit here
# never collides with them.
# The separator after the leading 0 is optional in both patterns because Thai
# organisations also split after the trunk prefix (0-2123-4567, 0-81-234-5678)
# rather than after the area code. Requiring adjacency there missed that whole
# shape -- and detect_fp is what the pre-send leak guard runs, so those numbers
# went out unmasked.
# That trunk-prefix separator is [- ], NOT [-\s]: `\s` matches a newline, which
# would let a lone '0' ending a table row fuse with the digits on the next row.
# The interior separators keep [-\s] (a wrapped number is still one number), but
# a leading zero has no such excuse -- and the blast radius is asymmetric, since
# redactor._build_redact_set turns each whitespace-separated word of an entity
# into a document-wide redaction fragment on a path that flattens to image.
_RE_PHONE_LANDLINE = re.compile(
    r"(?<!\d)(0[- ]?(?:2[-\s]?\d{3}[-\s]?\d{4}|[3-7]\d[-\s]?\d{3}[-\s]?\d{3}))(?!\d)"
)
# +66 form drops the national leading 0, so a Thai number carries 8 (landline)
# or 9 (mobile) digits after +66 -- e.g. +66 81 234 5678 is 9. The old pattern
# only matched 8, missing every mobile and leaking it to the STUDENT_ID
# catch-all. Allow an optional single separator between any two digits.
_RE_PHONE_INTL = re.compile(r"(?<![a-zA-Z0-9_])(\+66[-\s]?\d(?:[-\s]?\d){7,8})(?!\d)")
_RE_BANK_ACCOUNT_1 = re.compile(r"(?<!\d)(\d{3}[-\s]?\d{1}[-\s]?\d{5}[-\s]?\d{1})(?!\d)")
_RE_BANK_ACCOUNT_2 = re.compile(r"(?<!\d)(\d{7}[-\s]?\d{3})(?!\d)")
_RE_DATE = re.compile(
    # day-first (dd/mm/yyyy or dd/mm/yy) OR ISO year-first (yyyy-mm-dd).
    # The year-first alternative must come after so the day-first form still
    # wins for short years; the digit-boundary lookarounds keep both anchored.
    r"(?<!\d)(\d{1,2}[/\-]\d{1,2}[/\-](?:\d{4}|\d{2})|\d{4}[/\-]\d{1,2}[/\-]\d{1,2})(?!\d)"
)
# The trailing (?!\d) is load-bearing (DET-2): without it, this pattern bit the
# first 1-4 digits of a LONGER number after a Thai-consonant abbreviation
# (e.g. "ปชช 1101...", "กทม 0812..."), and _deduplicate's earlier-start-wins
# rule then dropped the overlapping checksum-valid THAI_ID/PHONE, leaking the
# rest. A real plate never sits inside a longer digit run, so requiring a
# non-digit right boundary costs no recall. No leading (?<!\d): new-format
# plates carry a leading digit ("1กก 1234") we must still match.
_RE_VEHICLE_PLATE = re.compile(r"([ก-ฮ]{1,3}\s*\d{1,4})(?!\d)")
# Passport is alphanumeric, so it needs the same Thai-adjacency handling as the
# numeric PII above: \b does NOT fire between a Thai letter and "A" (both are
# word characters in Unicode regex), so a passport glued to Thai text (e.g.
# "หนังสือเดินทางเลขที่AB1234567") slipped past. Alnum-boundary lookarounds still
# reject a value embedded in a longer alphanumeric run while allowing Thai/space
# adjacency.
_RE_PASSPORT_TH = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{2}\d{7})(?![A-Za-z0-9_])")
_RE_PASSPORT = re.compile(r"(?<![A-Za-z0-9_])([A-Z]{1,2}\d{6,9})(?![A-Za-z0-9_])")
_RE_STUDENT_ID = re.compile(r"(?<!\d)(\d{8,12})(?!\d)")

# Thai address components. The NER side only ever recognises place NAMES it has
# seen (province, district), which is the LEAST identifying part of an address
# line -- "กรุงเทพมหานคร" was masked while "99 ซอยลาดพร้าว 71" went out intact.
# These patterns key on the structure instead: a label word followed by its
# value. The label itself is not captured (group 1 is the value), so the output
# still reads as an address with the identifying part removed.
_RE_HOUSE_NO = re.compile(r"(?:บ้านเลขที่|เลขที่|ที่อยู่)\s*(\d{1,4}(?:\s*[/-]\s*\d{1,4})?)(?!\d)")
# Captures the soi/road NAME plus its number ("ลาดพร้าว 71"): the name alone
# identifies a neighbourhood and the number narrows it to one lane, so masking
# only the digits would leave the person locatable.
_RE_SOI_ROAD = re.compile(r"(?:ซอย|ซ\.|ถนน|ถ\.)\s*([ก-๛A-Za-z0-9]+(?:\s*\d{1,4})?)(?!\d)")
_RE_MOO = re.compile(r"(?:หมู่ที่|หมู่|ม\.)\s*(\d{1,3})(?!\d)")
# Sub-district / district / province NAMES. The CRF recognises the well-known
# ones (it masked "กรุงเทพมหานคร") but misses the rest, and a sub-district plus
# a postal code narrows a person to a few streets. Structure again, not a
# gazetteer: whatever follows the administrative label is the value.
_RE_ADMIN_AREA = re.compile(r"(?:แขวง|ตำบล|ต\.|อำเภอ|อ\.|เขต|จังหวัด|จ\.)\s*([ก-๛]{2,})")
# A bare 5-digit run is far too common to mask on sight (quantities, years in
# tables, reference numbers), so the postal code is only claimed when an address
# cue sits close in front of it.
_RE_POSTAL_CODE = re.compile(r"(?<!\d)(\d{5})(?!\d)")
# HN (เวชระเบียน) is the primary identifier inside a Thai health record and is
# typically 5-9 digits -- below the 8-digit floor the generic numeric catch-all
# starts at, so it was invisible to every detector. Requires its own cue, which
# also makes the MEDICAL_ID label honest rather than a guess.
_RE_MEDICAL_ID = re.compile(
    r"(?<![A-Za-z])(?:HN|เวชระเบียน|ผู้ป่วยเลขที่)\s*[:：]?\s*(\d{4,9})(?!\d)", re.IGNORECASE
)

_SEP_RE = re.compile(r"[-\s]")
_THAI_CHAR_RE = re.compile(r"[฀-๿]")

# BANK-vs-PHONE disambiguation cues. A 10-digit number starting 06-09 matches
# both the mobile PHONE and the BANK_ACCOUNT patterns, so the surrounding text
# is the only signal. `บัญชี` already covers เลขบัญชี / เลขที่บัญชี as a
# substring, so the alternation stays minimal.
_BANK_CUE_RE = re.compile(r"บัญชี|ธนาคาร")
_PHONE_CUE_RE = re.compile(r"โทรศัพท์|โทร|เบอร์|มือถือ|ติดต่อ")

# Honest-label cues (Horizon-2 #10). "เกิด" as substring covers วันเกิด /
# เกิดวันที่ / เกิดเมื่อ. Student/passport cues gate the wide catch-alls so a
# business PO/invoice number stops masquerading as a passport or student id --
# it is still masked, as the generic ID_NUMBER.
_BIRTH_CUE_RE = re.compile(r"เกิด")
# Address cue for the postal code. The window is wider than _CUE_WINDOW because
# a postal code sits at the END of the address line, so the nearest cue is a
# whole district/province name away ("แขวงวังทองหลาง กรุงเทพมหานคร 10310").
_POSTAL_CUE_RE = re.compile(r"รหัสไปรษณีย์|จังหวัด|แขวง|ตำบล|อำเภอ|เขต|กรุงเทพ|ที่อยู่")
_POSTAL_CUE_WINDOW = 45
_STUDENT_CUE_RE = re.compile(r"รหัสนักศึกษา|รหัสนิสิต|นักศึกษา|นิสิต|student", re.IGNORECASE)
_PASSPORT_CUE_RE = re.compile(r"พาสปอร์ต|หนังสือเดินทาง|passport", re.IGNORECASE)


def _cue_before(cue_re: re.Pattern, text: str, start: int) -> bool:
    return bool(cue_re.search(text[max(0, start - _CUE_WINDOW) : start]))


# A vehicle plate glued to Thai text (e.g. "ทะเบียนรถขก 4471") is normally
# suppressed by the mid-word guard below, which rejects any plate preceded by a
# Thai char. A plate cue in the ~15 chars before the match marks a real plate
# and relaxes that guard.
_PLATE_CUE_RE = re.compile(r"ทะเบียน")
_PLATE_CUE_WINDOW = 15
# The loose plate pattern ([ก-ฮ]{1,3}\s*\d{1,4}) also matches common Thai
# locality words that are all-consonant and precede a number -- most notably
# "ซอย N" (Soi/lane N) in addresses. Reject a match whose leading consonant run
# is such a word; real plate prefixes (กข, ถขก, ...) are not words.
_PLATE_STOPWORDS = frozenset({"ซอย", "ถนน"})
_PLATE_LEAD_RE = re.compile(r"[ก-ฮ]{1,3}")
# Look back this many characters. Thai runs words together with no spaces, and
# the disambiguating cue can sit a whole clause before the number (e.g.
# "บัญชีธนาคารกสิกรไทย เลขที่ 0731122334"), so the window is generous.
_CUE_WINDOW = 30


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

    # 7. DATE (generic) / DATE_OF_BIRTH (only with a birth cue nearby)
    for m in _RE_DATE.finditer(text):
        raw = m.group(1)
        parts = re.split(r"[/\-]", raw)
        if len(parts) == 3:
            try:
                # ISO year-first (yyyy-mm-dd) vs day-first (dd-mm-yyyy): a
                # 4-digit leading field means the day/month are the last two.
                if len(parts[0]) == 4:
                    day, month = int(parts[2]), int(parts[1])
                else:
                    day, month = int(parts[0]), int(parts[1])
                if _date_sanity(day, month):
                    dtype = (
                        "DATE_OF_BIRTH" if _cue_before(_BIRTH_CUE_RE, text, m.start(1)) else "DATE"
                    )
                    candidates.append(_make_entity(dtype, m, text, score=1.0))
            except ValueError:
                pass

    # 8. VEHICLE_PLATE
    # Reject matches where the Thai consonants are mid-word (preceded by a Thai
    # char) -- unless a plate cue (ทะเบียน...) just before it marks a real plate
    # glued to the label text.
    for m in _RE_VEHICLE_PLATE.finditer(text):
        start = m.start(1)
        lead = _PLATE_LEAD_RE.match(m.group(1))
        if lead and lead.group() in _PLATE_STOPWORDS:
            continue
        if start > 0 and _THAI_CHAR_RE.match(text[start - 1]):
            if not _PLATE_CUE_RE.search(text[max(0, start - _PLATE_CUE_WINDOW) : start]):
                continue
        candidates.append(_make_entity("VEHICLE_PLATE", m, text, score=0.9))

    # 9. PASSPORT — Thai format always; the general catch-all only with a cue,
    # otherwise it is a generic reference number (still masked as ID_NUMBER).
    for m in _RE_PASSPORT_TH.finditer(text):
        candidates.append(_make_entity("PASSPORT", m, text, score=1.0))
    for m in _RE_PASSPORT.finditer(text):
        if _cue_before(_PASSPORT_CUE_RE, text, m.start(1)):
            candidates.append(_make_entity("PASSPORT", m, text, score=1.0))
        else:
            candidates.append(_make_entity("ID_NUMBER", m, text, score=0.8))

    # 10. STUDENT_ID only with a student cue; bare 8-12 digit runs are masked
    # as the honest generic ID_NUMBER (low priority; dedup handles overlap).
    for m in _RE_STUDENT_ID.finditer(text):
        dtype = "STUDENT_ID" if _cue_before(_STUDENT_CUE_RE, text, m.start(1)) else "ID_NUMBER"
        candidates.append(_make_entity(dtype, m, text, score=0.8))

    # 11. ADDRESS components (house number, soi/road, moo). Scored above the
    # generic numeric catch-alls (0.8) so an address value keeps its honest
    # ADDRESS label instead of being swallowed as ID_NUMBER, but below the
    # checksum-backed types (1.0) which must always win an overlap.
    for pattern in (_RE_HOUSE_NO, _RE_SOI_ROAD, _RE_MOO, _RE_ADMIN_AREA):
        for m in pattern.finditer(text):
            candidates.append(_make_entity("ADDRESS", m, text, score=0.85))

    # 12. POSTAL_CODE — only with an address cue in front (see _RE_POSTAL_CODE).
    for m in _RE_POSTAL_CODE.finditer(text):
        ctx = text[max(0, m.start(1) - _POSTAL_CUE_WINDOW) : m.start(1)]
        if _POSTAL_CUE_RE.search(ctx):
            candidates.append(_make_entity("POSTAL_CODE", m, text, score=0.85))

    # 13. MEDICAL_ID (HN) — cue-gated, so the label is earned rather than assumed.
    for m in _RE_MEDICAL_ID.finditer(text):
        candidates.append(_make_entity("MEDICAL_ID", m, text, score=0.9))

    candidates = _disambiguate_bank_phone(text, candidates)
    return _deduplicate(candidates)
