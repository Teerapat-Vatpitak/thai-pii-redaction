from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.paper_evidence import (
    EvidenceIntegrityError,
    audit_unmatched_address,
    build_external_evidence,
    build_system_evidence,
    prediction_records,
)
from benchmark.types import GoldSpan, Sample


def test_address_audit_separates_contained_fragments():
    samples = [
        Sample(
            text="xxabcdefyy",
            spans=[GoldSpan(2, 8, "ADDRESS")],
            template_id="d1",
            slice="address_varied",
        )
    ]
    predictions = [[(2, 5, "ADDRESS"), (5, 8, "ADDRESS"), (8, 10, "ADDRESS")]]

    report = audit_unmatched_address(samples, predictions)

    assert report == {
        "unmatched_predictions": 2,
        "inside_gold_address": 1,
        "outside_gold_address": 1,
    }


def test_system_evidence_has_unrestricted_shared_and_document_ci():
    samples = [
        Sample(
            text="test@example.com today",
            spans=[GoldSpan(0, 16, "EMAIL")],
            template_id="d1",
            slice="natural",
        )
    ]
    predictions = [[(0, 16, "EMAIL"), (17, 22, "DATE")]]

    report = build_system_evidence(
        samples,
        predictions,
        reference={"gold_version": "gold-v3", "documents": 1, "entities": 1},
        system_commit="a" * 40,
        ner_chunks={"attempted": 1, "succeeded": 1, "skipped": 0},
        bootstrap_iterations=20,
        bootstrap_seed=7,
    )

    assert report["score"]["overall"]["fp"] == 1
    assert report["score"]["shared_11"]["overall"]["fp"] == 0
    assert report["score"]["out_of_scheme_predictions"] == 1
    ci = report["score"]["confidence_intervals"]["overall_f2"]
    assert ci["unit"] == "document"
    assert ci["iterations"] == 20
    assert report["integrity"]["ok"] is True


def test_system_evidence_rejects_a_skipped_chunk():
    with pytest.raises(EvidenceIntegrityError, match="skipped"):
        build_system_evidence(
            [],
            [],
            reference={},
            system_commit="a" * 40,
            ner_chunks={"attempted": 1, "succeeded": 0, "skipped": 1},
        )


def test_external_evidence_keeps_the_same_score_contract():
    report = {
        "provider": "tokenmind",
        "provider_config": {
            "provider_spec": "tokenmind",
            "model": "thaillm-8b",
        },
        "prompt_sha256": "b" * 64,
        "cache_schema": 2,
        "source": "gold",
        "gold_version": "gold-v3",
        "corpus": {"samples": 1, "entities": 1, "by_type": {"EMAIL": 1}},
        "overall": {"tp": 1, "fp": 0, "fn": 0, "f2": 1.0},
        "by_type": {},
        "by_slice": {},
        "confidence_intervals": {
            "overall_f2": {
                "unit": "document",
                "iterations": 10_000,
                "seed": 5252,
                "lower": 1.0,
                "upper": 1.0,
            }
        },
        "shared_11": {"overall": {"f2": 1.0}, "excluded_predictions": 0},
        "out_of_scheme_predictions": 0,
        "type_scheme": {"name": "shared-11"},
        "run": {"cached": 1, "called": 0, "failed": 0},
        "cache_only": True,
    }

    evidence = build_external_evidence(
        report,
        reference={"gold_version": "gold-v3", "documents": 1, "entities": 1},
        cache_fill={"cached": 0, "called": 1, "failed": 0},
    )

    assert evidence["score"]["overall"]["f2"] == 1.0
    assert evidence["score"]["confidence_intervals"]["overall_f2"]["unit"] == "document"
    assert evidence["baseline"]["model"] == "thaillm-8b"
    assert evidence["cache_fill"]["called"] == 1


def test_external_evidence_rejects_a_different_corpus():
    with pytest.raises(EvidenceIntegrityError, match="corpus"):
        build_external_evidence(
            {
                "gold_version": "gold-v4",
                "corpus": {"samples": 1, "entities": 1},
            },
            reference={"gold_version": "gold-v3", "documents": 1, "entities": 1},
            cache_fill={},
        )


def test_external_evidence_rejects_failed_cache_only_rescore():
    report = {
        "provider": "tokenmind",
        "provider_config": {
            "provider_spec": "tokenmind",
            "model": "thaillm-8b",
        },
        "prompt_sha256": "b" * 64,
        "cache_schema": 2,
        "source": "gold",
        "gold_version": "gold-v3",
        "corpus": {"samples": 1, "entities": 1},
        "confidence_intervals": {"overall_f2": {"unit": "document"}},
        "cache_only": True,
        "run": {"cached": 0, "called": 0, "failed": 1},
    }

    with pytest.raises(EvidenceIntegrityError, match="cache-only"):
        build_external_evidence(
            report,
            reference={"gold_version": "gold-v3", "documents": 1, "entities": 1},
            cache_fill={"cached": 0, "called": 1, "failed": 0},
        )


def test_prediction_records_do_not_store_text_or_values():
    samples = [
        Sample(
            text="test@example.com",
            spans=[GoldSpan(0, 16, "EMAIL")],
            template_id="d1",
            slice="natural",
        )
    ]

    records = prediction_records(samples, [[(0, 16, "EMAIL")]])

    assert records == [{"doc_id": "d1", "spans": [[0, 16, "EMAIL"]]}]
    assert "test@example.com" not in str(records)


# ── the frozen artifact itself ─────────────────────────────────────────

_RESEARCH = Path(__file__).resolve().parents[1] / "research" / "stt52"


def _frozen(name: str) -> dict:
    return json.loads((_RESEARCH / "evidence" / name).read_text(encoding="utf-8"))


def test_frozen_evidence_agrees_with_its_readme():
    """Nothing else in CI opens the committed artifact — the builder's own
    expected-dict runs only during a manual rebuild — so the frozen JSON, the
    README's prose numbers, and this test must all say the same thing, or the
    paper's evidence drifted."""
    readme = (_RESEARCH / "README.md").read_text(encoding="utf-8")

    crf = _frozen("gold-v3-crf.json")
    overall = crf["score"]["overall"]
    assert (overall["tp"], overall["fp"], overall["fn"]) == (561, 378, 80)
    assert round(overall["f2"], 3) == 0.801
    ci = crf["score"]["confidence_intervals"]["overall_f2"]
    assert (round(ci["lower"], 3), round(ci["upper"], 3)) == (0.770, 0.829)
    assert round(crf["score"]["shared_11"]["overall"]["f2"], 3) == 0.840
    assert crf["score"]["by_type"]["OUT_OF_SCHEME"]["fp"] == 163
    assert crf["ner_chunks"] == {"attempted": 272, "succeeded": 272, "skipped": 0}

    tok = _frozen("gold-v3-tokenmind-thaillm-8b.json")
    t_overall = tok["score"]["overall"]
    assert (t_overall["tp"], t_overall["fp"], t_overall["fn"]) == (609, 72, 32)
    assert round(t_overall["f2"], 3) == 0.938
    t_ci = tok["score"]["confidence_intervals"]["overall_f2"]
    assert (round(t_ci["lower"], 3), round(t_ci["upper"], 3)) == (0.914, 0.959)
    assert round(tok["score"]["shared_11"]["overall"]["f2"], 3) == 0.941

    for figure in (
        "TP 561, FP 378, FN 80",
        "F2 0.801",
        "0.770-0.829",
        "F2 0.840",
        "163",
        "272",
        "TP 609, FP 72, FN 32",
        "F2 0.938",
        "0.914-0.959",
        "0.941",
    ):
        assert figure in readme, f"README lost the frozen figure {figure!r}"


def test_frozen_predictions_hold_no_document_text_or_values():
    """The README promises offsets and types only. Structural check: every
    JSONL record is exactly {doc_id, spans} with integer offsets and an
    identifier-shaped label. The label set is NOT closed — the hosted model
    invents type names (ISBN, VARIABLE) — but an identifier shape still
    proves no document text or entity value sits in the label field."""
    import re

    label_shape = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")
    for name in (
        "gold-v3-crf-predictions.jsonl",
        "gold-v3-tokenmind-thaillm-8b-predictions.jsonl",
    ):
        lines = (_RESEARCH / "evidence" / name).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 252
        for line in lines:
            record = json.loads(line)
            assert set(record) == {"doc_id", "spans"}
            for span in record["spans"]:
                start, end, etype = span
                assert isinstance(start, int) and isinstance(end, int)
                assert label_shape.match(etype), f"{name}: label not a bare identifier: {etype!r}"
