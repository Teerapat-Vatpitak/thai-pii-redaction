"""Outbound PII leak scan shared by the CLI pre-send guard and the web path.

A "leak" is a detector hit in already-pseudonymized text that pseudonym
occurrences cannot account for. Fuzzy NER spans around embedded pseudonyms
are excused via position-based overlap + per-segment remainder scans + a
cue-preserving name_context re-check (see PR #33/#34 history).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.models import Entity


class _GuardContext(Protocol):
    """Minimum trusted state needed by the outbound policy."""

    def trusted_pseudonyms(self) -> set[str]: ...


@dataclass(frozen=True, slots=True)
class OutboundGuardContext:
    """Original-free, repr-hidden context for rechecking a masked result."""

    _trusted: frozenset[str] = field(default_factory=frozenset, repr=False)

    def trusted_pseudonyms(self) -> set[str]:
        return set(self._trusted)


SAFE_OUTBOUND_LEAK_TYPES = frozenset(
    {
        "ADDRESS",
        "ANONYMIZE_FAILED",
        "BANK_ACCOUNT",
        "CREDIT_CARD",
        "CRIMINAL",
        "DATE",
        "DATE_OF_BIRTH",
        "DISABILITY",
        "EMAIL",
        "ETHNICITY",
        "HEALTH",
        "IBAN",
        "ID_NUMBER",
        "LOCATION",
        "MEDICAL_ID",
        "MISSING_REPLACEMENT_RECORD",
        "NAME",
        "ORGANIZATION",
        "ORPHAN_DIGITS",
        "PASSPORT",
        "PHONE",
        "POLITICAL_OPINION",
        "POSTAL_CODE",
        "RELIGION",
        "STUDENT_ID",
        "SURNAME",
        "THAI_ID",
        "UNCLASSIFIED_RESIDUAL",
        "UNION",
        "VEHICLE_PLATE",
    }
)
_POLICY_CATEGORIES = frozenset(
    {"structured", "text", "detector_independent", "replacement_integrity"}
)


def normalize_outbound_leak_types(labels: object) -> list[str]:
    """Deduplicate fixed type labels without retaining injected values."""
    if not isinstance(labels, (list, tuple, set, frozenset)):
        return ["UNCLASSIFIED_RESIDUAL"]
    safe: set[str] = set()
    invalid = False
    for label in labels:
        if isinstance(label, str) and label in SAFE_OUTBOUND_LEAK_TYPES:
            safe.add(label)
        else:
            invalid = True
    if invalid or not safe:
        safe.add("UNCLASSIFIED_RESIDUAL")
    return sorted(safe)


def _safe_policy_categories(categories: set[str] | list[str] | tuple[str, ...]) -> list[str]:
    return sorted(
        {
            category
            for category in categories
            if isinstance(category, str) and category in _POLICY_CATEGORIES
        }
    )


class OutboundPolicyError(Exception):
    """Value-free residual classification raised before outbound use."""

    def __init__(
        self,
        leak_types: list[str] | set[str] | tuple[str, ...],
        *,
        policy_categories: set[str] | list[str] | tuple[str, ...],
    ):
        self.leak_types = normalize_outbound_leak_types(leak_types)
        self.policy_categories = _safe_policy_categories(policy_categories)
        self.category_count = len(self.policy_categories)
        self.policy_category_count = self.category_count
        super().__init__(f"outbound residual detected: {self.leak_types}")


def pseudonym_ranges(text: str, pseudonyms: list[str]) -> list[tuple[int, int]]:
    """
    Character ranges of every known-pseudonym occurrence in text.

    Longest pseudonym first so a shorter pseudonym cannot claim a slice of a
    longer one (same ordering rule as reverse_mapper); ranges never overlap.
    """
    claimed: list[tuple[int, int]] = []

    def _taken(start: int, end: int) -> bool:
        return any(start < ce and end > cs for cs, ce in claimed)

    for p in sorted(pseudonyms, key=len, reverse=True):
        pos = 0
        while (i := text.find(p, pos)) >= 0:
            if not _taken(i, i + len(p)):
                claimed.append((i, i + len(p)))
            pos = i + 1
    return claimed


def _cue_leak_in_window(text: str, start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """
    Cue-preserving re-check for a TB span straddling pseudonym occurrences.

    Scanning the uncovered segments in isolation severs a title/intro cue from
    a name on the far side of the pseudonym ('นาย <pseudonym> <leaked name>'),
    which the bare-segment scan can miss when the CRF does not recognise the
    bare name. Re-run the high-precision cue detector over the span plus a
    little left context; a detected name covering any non-whitespace character
    outside the pseudonym occurrences is a real leak.
    """
    ctx_start = max(0, start - 16)
    window = text[ctx_start:end]
    for nc in detect_name_context(window):
        g0 = ctx_start + nc.span[0]
        g1 = ctx_start + nc.span[1]
        for i in range(max(g0, start), min(g1, end)):
            if text[i].strip() and not any(cs <= i < ce for cs, ce in ranges):
                return True
    return False


# A digit run this long is an identifier, not a quantity, in the documents this
# system handles. Six is deliberately below the numeric detectors' eight-digit
# floor: that floor is precisely the gap a hospital number or a short reference
# number falls through.
_ORPHAN_DIGITS_RE = re.compile(r"(?<!\d)(\d{6,})(?!\d)")


def scan_residual_signals(text: str, guard_context: _GuardContext) -> list[str]:
    """A second opinion that does not consult the detectors again.

    `scan_outbound_leaks` runs the same `detect_fp`/`detect_tb` that produced
    this text, so whatever detection missed on the way in is missed again on
    the way out: three layers on the architecture diagram, one layer in
    practice (correlated failure). This check depends on none of them -- it
    asks a structural question instead, "is there a long bare number here that
    nothing replaced?", and so can catch what the detectors are blind to.

    The strings are structural findings, not caller-facing warnings. The
    shared outbound policy turns any finding into a fail-closed decision.
    """
    trusted = guard_context.trusted_pseudonyms()
    ranges = pseudonym_ranges(text, sorted(trusted, key=len, reverse=True))
    signals: list[str] = []
    for m in _ORPHAN_DIGITS_RE.finditer(text):
        start, end = m.start(1), m.end(1)
        if any(cs <= start and end <= ce for cs, ce in ranges):
            continue  # part of a pseudonym we wrote
        signals.append(f"orphan_digits:{end - start}")
    return signals


def scan_outbound_leaks(text: str, guard_context: _GuardContext) -> list[Entity]:
    """Return real leaks in pseudonymized text (empty list = safe to send)."""
    # PII leak check: fp + tb detectors on pseudonymized text
    # (tb catches name/address leaks that regex/checksum miss).
    # Exact-match exclusion against known pseudonyms is not enough for TB:
    # NER span boundaries are fuzzy, so a span can swallow ordinary words
    # around an embedded pseudonym ("หน่อยครับ\nผมชื่อ <pseudonym>") or
    # re-detect a fragment inside one (the district part of a fake address).
    # Excuse a span only when pseudonym occurrences fully account for its
    # PII content; anything else still halts the send.
    # Caller-seeded mappings are declarations, not proof. Only replacements
    # minted or actually reused by this processing turn may excuse any FP or TB
    # hit. That rule is shared with the detector-independent digit scan.
    trusted = guard_context.trusted_pseudonyms()
    trusted_ranges = pseudonym_ranges(text, sorted(trusted, key=len, reverse=True))
    real_leaks = []
    for entity in detect_fp(text) + detect_tb(text):
        if entity.original_text in trusted:
            continue
        start, end = entity.span
        overlapping = [(cs, ce) for cs, ce in trusted_ranges if cs < end and ce > start]
        if overlapping:
            if any(cs <= start and end <= ce for cs, ce in overlapping):
                # Span sits entirely inside one pseudonym occurrence.
                continue
            if entity.redact_type == "TB":
                # Fuzzy NER span straddling pseudonym(s): re-scan only the
                # parts of the span NOT covered by pseudonym occurrences.
                # Positional slicing, not string replace — the span may cover
                # a mere fragment of a pseudonym ('เขตสาทร' out of
                # '556 เขตสาทร'), which whole-string stripping leaves behind.
                # Each segment is scanned SEPARATELY: joining them would
                # fabricate adjacency the text never had (a name cue glued to
                # the word after the pseudonym reads as a fresh name).
                # FP spans are exact and never get this leniency.
                segments = []
                pos = start
                for cs, ce in sorted(overlapping):
                    if cs > pos:
                        segments.append(text[pos : min(cs, end)])
                    pos = max(pos, ce)
                if pos < end:
                    segments.append(text[pos:end])
                segments_clean = all(
                    not seg.strip() or (not detect_fp(seg) and not detect_tb(seg))
                    for seg in segments
                )
                if segments_clean and not _cue_leak_in_window(text, start, end, trusted_ranges):
                    continue
        real_leaks.append(entity)
    return real_leaks


def enforce_outbound_policy(
    text: str,
    *,
    guard_context: _GuardContext,
    scan_leaks: Callable[[str, _GuardContext], list[Entity]] = scan_outbound_leaks,
    scan_residual: Callable[[str, _GuardContext], list[str]] = scan_residual_signals,
) -> None:
    """Fail closed on structured, text, or detector-independent residuals.

    The exception retains only bounded type labels and fixed policy categories.
    It never retains Entity objects, scanner signals, or source text.
    """
    leak_types: set[str] = set()
    categories: set[str] = set()
    leaks = list(scan_leaks(text, guard_context))
    for leak in leaks:
        data_type = getattr(leak, "data_type", None)
        if isinstance(data_type, str):
            leak_types.add(data_type)
        categories.add("structured" if getattr(leak, "redact_type", None) == "FP" else "text")

    if list(scan_residual(text, guard_context)):
        leak_types.add("ORPHAN_DIGITS")
        categories.add("detector_independent")

    if leak_types or categories:
        safe_leak_types = normalize_outbound_leak_types(leak_types)
        safe_categories = _safe_policy_categories(categories)
        text = ""
        guard_context = None
        scan_leaks = None
        scan_residual = None
        leaks.clear()
        leaks = []
        leak = None
        data_type = None
        raise OutboundPolicyError(
            safe_leak_types,
            policy_categories=safe_categories,
        )
