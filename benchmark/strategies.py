"""Pure NER-engine strategy merges for the benchmark comparison.

Given one sample's CRF and WangchanBERTa entity lists, compose the `union` and
`route` strategy predictions. Model-free so the merge logic is unit-testable
without loading any NER model.
"""
from __future__ import annotations

from pii_redactor.detectors.aggregate import dedupe_spans
from pii_redactor.models import Entity


def union_entities(crf: list[Entity], wcb: list[Entity]) -> list[Entity]:
    """CRF ∪ WCB: keep every span from both engines, then drop overlaps via
    dedupe_spans (FP-first, earlier-start-then-longer). Recall-first."""
    return dedupe_spans(list(crf) + list(wcb))


def route_entities(crf: list[Entity], wcb: list[Entity]) -> list[Entity]:
    """ADDRESS from WangchanBERTa, everything else from CRF, then dedupe.
    Encodes the gold finding: WCB wins ADDRESS, CRF wins NAME-without-cue."""
    picked = [e for e in crf if e.data_type != "ADDRESS"]
    picked += [e for e in wcb if e.data_type == "ADDRESS"]
    return dedupe_spans(picked)
