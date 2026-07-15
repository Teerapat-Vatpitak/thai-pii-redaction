"""Tests for NER-engine strategy merges (benchmark comparison)."""
from __future__ import annotations

from pii_redactor.models import Entity
from benchmark.strategies import union_entities, route_entities


def _ent(dtype, span, redact="TB", score=0.85):
    return Entity(entity_id="x", redact_type=redact, data_type=dtype,
                  span=span, score=score, original_text="v")


def test_union_superset_on_disjoint_spans():
    # Disjoint spans: union keeps every span from both engines.
    crf = [_ent("NAME", (0, 8))]
    wcb = [_ent("ADDRESS", (20, 35))]
    spans = {(e.data_type, e.span) for e in union_entities(crf, wcb)}
    assert ("NAME", (0, 8)) in spans
    assert ("ADDRESS", (20, 35)) in spans


def test_route_takes_address_from_wcb_and_name_from_crf():
    crf = [_ent("NAME", (0, 8)), _ent("ADDRESS", (9, 15))]   # CRF's weak address
    wcb = [_ent("ADDRESS", (9, 25))]                          # WCB's better address
    out = route_entities(crf, wcb)
    names = [e for e in out if e.data_type == "NAME"]
    addrs = [e for e in out if e.data_type == "ADDRESS"]
    assert names and names[0].span == (0, 8)     # NAME kept from CRF
    assert addrs and addrs[0].span == (9, 25)    # ADDRESS from WCB, not CRF's (9,15)
