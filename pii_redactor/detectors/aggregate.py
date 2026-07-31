"""Shared PII detection assembly used by both the web API and the benchmark.

detect_all() is the exact ensemble /api/sanitize runs: format-preserving +
text-based + false-negative scan, then overlap dedup. Keeping it in one place
means the benchmark measures precisely what the product ships.
"""

from __future__ import annotations

import re

from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.name_context import detect_parallel_record_names
from pii_redactor.detectors.tb_detector import NERChunkDiagnostics, detect_tb
from pii_redactor.models import Entity


def dedupe_spans(entities: list[Entity]) -> list[Entity]:
    """Drop overlapping spans, keeping a non-overlapping set.

    FP entities (regex + checksum validated: id/email/phone/card/...) are placed
    first, so a fuzzy NER (TB) span can never displace a precise structured hit
    it overlaps -- a checksum-valid email must not be relabeled ADDRESS just
    because the NER span happened to start earlier. Within each tier, prefer the
    earlier start, then the longer span.
    """

    def _key(e: Entity):
        return (e.span[0], -(e.span[1] - e.span[0]))

    kept: list[Entity] = []

    def _overlaps(e: Entity) -> bool:
        return any(not (e.span[1] <= k.span[0] or e.span[0] >= k.span[1]) for k in kept)

    fp = sorted((e for e in entities if e.redact_type == "FP"), key=_key)
    tb = sorted((e for e in entities if e.redact_type != "FP"), key=_key)
    for e in (*fp, *tb):
        if not _overlaps(e):
            kept.append(e)
    return sorted(kept, key=lambda e: e.span[0])


def _prefer_record_names(
    entities: list[Entity],
    record_names: list[Entity],
) -> list[Entity]:
    """Keep strong record context above a conflicting TB label."""
    kept = list(entities)
    for name in record_names:
        overlaps = [
            entity
            for entity in kept
            if name.span[0] < entity.span[1] and entity.span[0] < name.span[1]
        ]
        if any(entity.redact_type == "FP" for entity in overlaps):
            continue
        # Relabeling a span the record row explains is the point of this pass,
        # so a coextensive LOCATION/ADDRESS still becomes the NAME. What it may
        # never do is UNCOVER: an overlap reaching outside the record name (a
        # CRF ADDRESS whose span runs on into the next line) would lose that
        # tail to a shorter NAME, and dropping already-masked characters
        # violates recall > precision. Tested against every data_type —
        # limiting the guard to NAME is what let other labels be swapped for a
        # shorter span.
        if any(
            entity.span[0] < name.span[0] or entity.span[1] > name.span[1] for entity in overlaps
        ):
            continue
        kept = [entity for entity in kept if entity not in overlaps]
        kept.append(name)
    return sorted(kept, key=lambda entity: entity.span[0])


# ── ADDRESS coalescing ─────────────────────────────────────────────────────
#
# The FP address patterns capture components (house number, moo, soi/road,
# admin areas) as separate spans, so one real address becomes several
# entities: several pseudonyms downstream, several boxes on the PDF path, and
# on gold v4 an ADDRESS entity precision of 0.220 where 175 of 183 "false
# positives" were fragments inside real addresses. Coalescing is done here,
# after dedupe, over the FULL sorted entity list — merging only consecutive
# entities so a chain can never swallow an intervening NAME and recreate the
# overlap dedupe just removed.
#
# Gap rules (adversarially reviewed): a strict gap is a few spaces/commas; a
# bridge gap may carry an uncaptured Thai token run (a building name) but ONLY
# when it contains an address-structure word, no digit, no tab/newline, and no
# ownership/introducer word — "ผู้ขาย เลขที่" between two addresses is two
# parties, not one address, and on the PDF path every word of a merged span
# becomes a document-wide redaction fragment, so over-merging is costly.

_MERGE_TYPES = {"ADDRESS", "POSTAL_CODE"}
_STRICT_GAP_RE = re.compile(r"[ , ]{0,3}")
# The FP patterns capture VALUES only ("บางพระ" from "ตำบลบางพระ"), so the
# labels themselves live in the gaps between fragments. A bridgeable gap is
# short, single-line, and must contain an address label or structure word;
# digit runs are capped at 3 so a moo/floor number may sit in the gap but a
# phone or id cannot.
_BRIDGE_CHARSET_RE = re.compile(r"[ .,ก-๎0-9]{1,18}")
_ADDRESS_GLUE_RE = re.compile(
    r"ตำบล|อำเภอ|จังหวัด|แขวง|เขต|หมู่ที่|หมู่|ซอย|ถนน|ต\.|อ\.|จ\.|ม\."
    r"|อาคาร|หมู่บ้าน|ตึก|ชั้น|ห้อง|คอนโด|ตรอก|แยก|นิคม"
)
_BRIDGE_VETO_RE = re.compile(
    r"บ้านเลขที่|ที่อยู่|เลขที่|ผู้ซื้อ|ผู้ขาย|ผู้กู้|ผู้ค้ำ|ผู้เช่า|ผู้ให้เช่า|ส่งที่|ติดต่อ|นาย|นาง|นางสาว"
)


def _gap_ok(gap: str, prev_type: str) -> bool:
    if _STRICT_GAP_RE.fullmatch(gap):
        return True
    # Bridges continue an ADDRESS, never extend forward from a postal code.
    if prev_type != "ADDRESS":
        return False
    if any(ch in gap for ch in "\n\t\r\v\f"):
        return False
    if not _BRIDGE_CHARSET_RE.fullmatch(gap):
        return False
    if any(len(run) > 3 for run in re.findall(r"\d+", gap)):
        return False
    if _BRIDGE_VETO_RE.search(gap):
        return False
    return bool(_ADDRESS_GLUE_RE.search(gap))


def merge_address_spans(text: str, entities: list[Entity]) -> list[Entity]:
    """Coalesce adjacent ADDRESS/POSTAL_CODE entities into single ADDRESS spans.

    Input must be sorted and non-overlapping (dedupe_spans output). Output
    keeps that invariant. A chain merges only if it contains at least one
    ADDRESS; the merged entity is TB so the anonymizer routes it to the Thai
    address surrogate generator instead of the generic ASCII fallback.
    """
    out: list[Entity] = []
    i = 0
    while i < len(entities):
        e = entities[i]
        if e.data_type not in _MERGE_TYPES:
            out.append(e)
            i += 1
            continue
        chain = [e]
        j = i + 1
        while j < len(entities) and entities[j].data_type in _MERGE_TYPES:
            gap = text[chain[-1].span[1] : entities[j].span[0]]
            if not _gap_ok(gap, chain[-1].data_type):
                break
            chain.append(entities[j])
            j += 1
        if len(chain) == 1 or not any(c.data_type == "ADDRESS" for c in chain):
            out.append(e)
            i += 1
            continue
        start, end = chain[0].span[0], chain[-1].span[1]
        out.append(
            Entity(
                entity_id=chain[0].entity_id,
                redact_type="TB",
                data_type="ADDRESS",
                span=(start, end),
                score=max(c.score for c in chain),
                original_text=text[start:end],
            )
        )
        i = j
    return out


def _relabel_student_ids(tb: list[Entity], kept: list[Entity]) -> list[Entity]:
    """Give a TB STUDENT_ID span its honest label past the FP-first dedupe.

    A cue-free student id is matched by the generic 8-12 digit FP pattern as
    ID_NUMBER, and FP-first dedupe then discards the TB STUDENT_ID candidate
    covering the same digits — so an engine that can actually recognize
    student ids (the fine-tuned one) could never surface the label. The
    masked span is identical either way; only the label (and therefore the
    surrogate) changes. A no-op for engines that emit no TB STUDENT_ID.
    """
    student_spans = {e.span for e in tb if e.data_type == "STUDENT_ID"}
    if not student_spans:
        return kept
    out = []
    for e in kept:
        if e.data_type == "ID_NUMBER" and e.span in student_spans:
            e = Entity(
                entity_id=e.entity_id,
                redact_type=e.redact_type,
                data_type="STUDENT_ID",
                span=e.span,
                score=e.score,
                original_text=e.original_text,
            )
        out.append(e)
    return out


def detect_all(
    text: str,
    *,
    ner_diagnostics: NERChunkDiagnostics | None = None,
) -> list[Entity]:
    """Run the full detection ensemble and return deduped entities."""
    fp = detect_fp(text)
    if ner_diagnostics is None:
        tb = detect_tb(text)
    else:
        tb = detect_tb(text, diagnostics=ner_diagnostics)
    fn = scan_fn(text, fp + tb)
    record_names = detect_parallel_record_names(text, fp + tb + fn)
    deduped = dedupe_spans(fp + tb + fn + record_names)
    kept = merge_address_spans(text, _prefer_record_names(deduped, record_names))
    return _relabel_student_ids(tb, kept)
