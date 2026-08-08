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
from pii_redactor.native_broker_context import native_broker_detector_phase


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
# phone or id cannot. The cap was raised 18 -> 25 (2026-08-04) for building
# names between fragments (" คอนโดริเวอร์ไซด์ ชั้น " is 23); every other gap
# rule — glue word required, no digit run > 3, no newline, no
# ownership/introducer veto — still stands, so the two-party split cases the
# 18 was chosen against remain unmergeable (re-measured on gold + negative).
_BRIDGE_CHARSET_RE = re.compile(r"[ .,ก-๎0-9]{1,25}")
_ADDRESS_GLUE_RE = re.compile(
    r"ตำบล|อำเภอ|จังหวัด|แขวง|เขต|หมู่ที่|หมู่|ซอย|ถนน|ต\.|อ\.|จ\.|ม\."
    r"|อาคาร|หมู่บ้าน|ตึก|ชั้น|ห้อง|คอนโด|ตรอก|แยก|นิคม"
)
_BRIDGE_VETO_RE = re.compile(
    r"บ้านเลขที่|ที่อยู่|เลขที่|ผู้ซื้อ|ผู้ขาย|ผู้กู้|ผู้ค้ำ|ผู้เช่า|ผู้ให้เช่า|ส่งที่|ติดต่อ|นาย|นาง|นางสาว"
)
# A postal code may merge BACKWARD across exactly one bare Thai token — the
# label-less khwaeng/province word that ends most Thai addresses ("เขตหลักสี่
# กทม 10210"): the code already required an address cue within 45 chars to
# exist at all, so the worst case is over-masking one word in front of a real
# postcode, never a new claim. One token only; digits, newlines, and every
# veto word still break it.
_POSTAL_BACKSTEP_RE = re.compile(r" ?[ก-๎]{2,18} ?")


def _gap_ok(gap: str, prev_type: str, next_type: str) -> bool:
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
    if _ADDRESS_GLUE_RE.search(gap):
        return True
    return next_type == "POSTAL_CODE" and bool(_POSTAL_BACKSTEP_RE.fullmatch(gap))


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
            if not _gap_ok(gap, chain[-1].data_type, entities[j].data_type):
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


def _extend_address_chains(text: str, entities: list[Entity], tb: list[Entity]) -> list[Entity]:
    """Union a retained ADDRESS span with raw TB ADDRESS spans dedupe dropped.

    FP-first dedupe keeps the precise label-keyed fragments and discards a
    wider CRF ADDRESS span covering the same ground — but that wider span is
    often the only thing that saw the label-less tail ("อำเภอเมือง ขอนแก่น":
    the bare province lives in no FP capture). The CRF has already asserted
    the whole region is one address, so the retained span may grow to the
    union — clamped at the neighboring retained entities so a NAME beside the
    address can never be swallowed (over-masking within the CRF's own span is
    the worst case, never a new claim). Chains are re-merged afterwards
    because an extension can close the gap to a POSTAL_CODE fragment.
    """
    tb_addr = [t for t in tb if t.data_type == "ADDRESS"]
    if not tb_addr:
        return entities
    ents = sorted(entities, key=lambda e: e.span[0])
    out: list[Entity] = []
    changed = False
    floor = 0  # end of the previous (possibly already extended) entity
    for i, e in enumerate(ents):
        ceiling = ents[i + 1].span[0] if i + 1 < len(ents) else len(text)
        if e.data_type != "ADDRESS":
            out.append(e)
            floor = e.span[1]
            continue
        start, end = e.span
        for t in tb_addr:
            if t.span[0] < end and start < t.span[1]:
                start = min(start, t.span[0])
                end = max(end, t.span[1])
        start = max(start, floor)
        end = min(end, ceiling)
        if (start, end) == e.span:
            out.append(e)
        else:
            changed = True
            out.append(
                Entity(
                    entity_id=e.entity_id,
                    redact_type="TB",
                    data_type="ADDRESS",
                    span=(start, end),
                    score=e.score,
                    original_text=text[start:end],
                )
            )
        floor = end
    if not changed:
        return entities
    return merge_address_spans(text, out)


# Bare facility designators (ng19): a bookable meeting room in a facilities
# notice is furniture, not a place tied to a person. thainer maps FACILITY to
# nothing by design, but the CRF emits these as LOCATION. Runs post-merge,
# where a facility word inside a real address has already been absorbed into
# its ADDRESS chain.
#
# Dropping UNMASKS, so absence of evidence is not evidence: the first cut
# dropped the span whenever NOTHING else was detected nearby, and a bare
# delivery line ("ส่งเอกสารมาที่ อาคาร 7 ชั้น 3") has no neighbours by
# construction — it lost its building outright (2026-08-04 review). Two
# conditions are now required together, both of which must point AT a
# facilities notice:
#
#  - positive register evidence in the window (booking/capacity/meeting
#    vocabulary), read with the facility spans themselves blanked out so
#    "ห้องประชุม 1204" cannot vouch for itself; and
#  - no retained non-facility entity nearby (a name, a phone, an address, an
#    organization keeps the span masked; facility siblings never anchor each
#    other, or the three ng19 spans would keep each other alive).
_FACILITY_SPAN_RE = re.compile(r"(?:ห้องประชุม|ห้องเรียน|ห้อง|อาคาร|ตึก|ชั้น)\s*\d+")
_FACILITY_ANCHOR_WINDOW = 80
# Booking/capacity/event vocabulary. Bare สอบ is deliberately absent — it is a
# substring of ตรวจสอบ/สอบถาม, which are ordinary prose and would license an
# unmasking; the exam-room forms are spelled out instead.
_FACILITY_REGISTER_RE = re.compile(
    r"ความจุ|ที่นั่ง|จอง|ประชุม|อบรม|สัมมนา|บรรยาย|ห้องสอบ|สนามสอบ|ตารางสอบ|ผู้เข้าสอบ"
)


def _drop_unanchored_facility_spans(text: str, entities: list[Entity]) -> list[Entity]:
    facility = {
        i
        for i, e in enumerate(entities)
        if e.data_type == "LOCATION" and _FACILITY_SPAN_RE.fullmatch(text[e.span[0] : e.span[1]])
    }
    if not facility:
        return entities
    # Blank the facility spans so their own designator words are not read as
    # register evidence for themselves.
    masked = list(text)
    for i in facility:
        for pos in range(*entities[i].span):
            masked[pos] = " "
    masked_text = "".join(masked)
    anchors = [e for i, e in enumerate(entities) if i not in facility]
    drop = set()
    for i in facility:
        s, t = entities[i].span
        lo = max(0, s - _FACILITY_ANCHOR_WINDOW)
        hi = min(len(text), t + _FACILITY_ANCHOR_WINDOW)
        if not _FACILITY_REGISTER_RE.search(masked_text[lo:hi]):
            continue
        if not any(a.span[0] < hi and lo < a.span[1] for a in anchors):
            drop.add(i)
    if not drop:
        return entities
    return [e for i, e in enumerate(entities) if i not in drop]


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


@native_broker_detector_phase
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
    kept = _extend_address_chains(text, kept, tb)
    kept = _drop_unanchored_facility_spans(text, kept)
    return _relabel_student_ids(tb, kept)
