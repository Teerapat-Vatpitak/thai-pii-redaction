"""Confirm the product union mode delivers the recall the strategy ADR measured.

The ADR (docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md)
recommended `union` from gold numbers: ADDRESS recall 1.000, NAME 0.643,
OVERALL recall 0.852. This gates that the shipped detect_all + union path
reproduces that recall-first win (floors sit just under the measured values so
the gate is not flaky). Exact per-sample span equality with the benchmark's
union_entities oracle is NOT asserted -- the false-negative scan and dedup
nesting differ slightly between the two paths; recall is what the ADR promised.
"""
from __future__ import annotations

import importlib.util

import pytest

from benchmark.gold import load_gold
from benchmark.scorer import score
from pii_redactor.detectors.aggregate import detect_all


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="requires requirements-ml.txt",
)
def test_product_union_reproduces_adr_recall_on_gold(monkeypatch):
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "union")
    samples = load_gold()
    preds = [
        [(e.span[0], e.span[1], e.data_type) for e in detect_all(s.text)]
        for s in samples
    ]
    rep = score(samples, preds)
    assert rep["by_type"]["ADDRESS"]["recall"] >= 0.99, rep["by_type"]["ADDRESS"]
    assert rep["by_type"]["NAME"]["recall"] >= 0.60, rep["by_type"]["NAME"]
    assert rep["overall"]["recall"] >= 0.83, rep["overall"]
