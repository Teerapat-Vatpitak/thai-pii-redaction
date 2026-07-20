"""Outbound PII leak scan shared by the CLI pre-send guard and the web path.

A "leak" is a detector hit in already-pseudonymized text that pseudonym
occurrences cannot account for. Fuzzy NER spans around embedded pseudonyms
are excused via position-based overlap + per-segment remainder scans + a
cue-preserving name_context re-check (see PR #33/#34 history).
"""

from __future__ import annotations

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.models import Entity
from pii_redactor.session_vault import SessionVault


def _pseudonym_ranges(text: str, pseudonyms: list[str]) -> list[tuple[int, int]]:
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


def scan_outbound_leaks(text: str, vault: SessionVault) -> list[Entity]:
    """Return real leaks in pseudonymized text (empty list = safe to send)."""
    # PII leak check: fp + tb detectors on pseudonymized text
    # (tb catches name/address leaks that regex/checksum miss).
    # Exact-match exclusion against known pseudonyms is not enough for TB:
    # NER span boundaries are fuzzy, so a span can swallow ordinary words
    # around an embedded pseudonym ("หน่อยครับ\nผมชื่อ <pseudonym>") or
    # re-detect a fragment inside one (the district part of a fake address).
    # Excuse a span only when pseudonym occurrences fully account for its
    # PII content; anything else still halts the send.
    known_pseudonyms = set(vault._reverse.keys())
    ordered = sorted((p for p in known_pseudonyms if p), key=len, reverse=True)
    ranges = _pseudonym_ranges(text, ordered)
    real_leaks = []
    for entity in detect_fp(text) + detect_tb(text):
        if entity.original_text in known_pseudonyms:
            continue
        start, end = entity.span
        overlapping = [(cs, ce) for cs, ce in ranges if cs < end and ce > start]
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
                if segments_clean and not _cue_leak_in_window(text, start, end, ranges):
                    continue
        real_leaks.append(entity)
    return real_leaks
