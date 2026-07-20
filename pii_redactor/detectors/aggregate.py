"""Shared PII detection assembly used by both the web API and the benchmark.

detect_all() is the exact ensemble /api/sanitize runs: format-preserving +
text-based + false-negative scan, then overlap dedup. Keeping it in one place
means the benchmark measures precisely what the product ships.
"""

from __future__ import annotations

from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
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


def detect_all(text: str) -> list[Entity]:
    """Run the full detection ensemble and return deduped entities."""
    fp = detect_fp(text)
    tb = detect_tb(text)
    fn = scan_fn(text, fp + tb)
    return dedupe_spans(fp + tb + fn)
