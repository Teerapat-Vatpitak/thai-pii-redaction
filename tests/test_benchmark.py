"""Tests for the synthetic Thai PII recall benchmark."""
from __future__ import annotations

import importlib.util

import pytest

from benchmark.corpus import ENTITY_TYPES, build_corpus
from benchmark.runner import render_table, run_benchmark
from benchmark.scorer import score
from benchmark.types import GoldSpan, Sample
from pii_redactor.detectors.aggregate import detect_all


# ── types ──────────────────────────────────────────────────────────────
def test_goldspan_and_sample_construct():
    s = Sample(text="นายสมชาย", spans=[GoldSpan(0, 8, "NAME")], template_id="t0", slice="core")
    assert s.text[s.spans[0].start:s.spans[0].end] == "นายสมชาย"
    assert s.spans[0].entity_type == "NAME"
    assert s.slice == "core"


# ── detect_all ─────────────────────────────────────────────────────────
def test_detect_all_finds_thai_id_and_dedupes():
    ents = detect_all("เลขบัตรประชาชนของผมคือ 1101700230708 ครับ")
    assert any(e.data_type == "THAI_ID" for e in ents)
    ordered = sorted(e.span for e in ents)
    assert all(ordered[i][1] <= ordered[i + 1][0] for i in range(len(ordered) - 1))


# ── dedupe_spans: FP wins over TB on overlap ───────────────────────────
from pii_redactor.detectors.aggregate import dedupe_spans
from pii_redactor.models import Entity


def _ent(redact_type, data_type, span, score=1.0):
    return Entity(
        entity_id="x", redact_type=redact_type, data_type=data_type,
        span=span, score=score, original_text="v",
    )


def test_dedupe_prefers_fp_over_overlapping_tb():
    # A broad NER (TB) span that starts earlier must NOT displace a precise,
    # checksum/regex-validated FP span it overlaps.
    tb = _ent("TB", "ADDRESS", (5, 25), 0.85)
    fp = _ent("FP", "EMAIL", (10, 20), 1.0)
    kept = {(e.redact_type, e.data_type) for e in dedupe_spans([tb, fp])}
    assert ("FP", "EMAIL") in kept
    assert ("TB", "ADDRESS") not in kept


def test_dedupe_keeps_nonoverlapping_fp_and_tb():
    tb = _ent("TB", "NAME", (0, 8), 0.9)
    fp = _ent("FP", "PHONE", (9, 19), 1.0)
    assert len(dedupe_spans([tb, fp])) == 2


# ── corpus ─────────────────────────────────────────────────────────────
def test_corpus_spans_align_with_text():
    for s in build_corpus(seed=1, size=60):
        for sp in s.spans:
            assert sp.end > sp.start
            assert s.text[sp.start:sp.end]
            assert sp.entity_type in ENTITY_TYPES


def test_corpus_is_deterministic():
    a = build_corpus(seed=7, size=40)
    b = build_corpus(seed=7, size=40)
    assert [(s.text, s.spans) for s in a] == [(s.text, s.spans) for s in b]


def test_corpus_covers_every_entity_type():
    seen = {sp.entity_type for s in build_corpus(seed=3, size=200) for sp in s.spans}
    for t in ENTITY_TYPES:
        assert t in seen, f"{t} never generated"


def test_corpus_has_hard_case_slice():
    hard = [s for s in build_corpus(seed=5, size=200) if s.slice == "hard_case"]
    assert hard
    assert any("1101700230708" not in s.text for s in hard)  # values are random
    assert any("+66" in s.text or "เลขบัตรประชาชน" in s.text for s in hard)


# ── scorer ─────────────────────────────────────────────────────────────
def _s(text, spans):
    return Sample(text=text, spans=[GoldSpan(*x) for x in spans], template_id="t", slice="core")


def test_scorer_perfect():
    r = score([_s("0812345678", [(0, 10, "PHONE")])], [[(0, 10, "PHONE")]])
    assert r["overall"]["recall"] == 1.0
    assert r["overall"]["precision"] == 1.0
    assert r["overall"]["coverage_recall"] == 1.0
    assert r["overall"]["exact_recall"] == 1.0


def test_scorer_miss_is_fn():
    r = score([_s("0812345678", [(0, 10, "PHONE")])], [[]])
    assert r["overall"]["recall"] == 0.0
    assert r["by_type"]["PHONE"]["fn"] == 1


def test_scorer_overlap_counts_but_partial_coverage():
    r = score([_s("0812345678", [(0, 10, "PHONE")])], [[(0, 6, "PHONE")]])
    assert r["by_type"]["PHONE"]["tp"] == 1
    assert abs(r["overall"]["coverage_recall"] - 0.6) < 1e-9
    assert r["overall"]["exact_recall"] == 0.0


def test_scorer_wrong_type_is_fp_and_fn():
    r = score([_s("0812345678", [(0, 10, "PHONE")])], [[(0, 10, "EMAIL")]])
    assert r["by_type"]["PHONE"]["fn"] == 1
    assert r["by_type"]["EMAIL"]["fp"] == 1
    assert r["overall"]["coverage_recall"] == 1.0


def test_f2_weights_recall():
    r = score([_s("0812345678 x", [(0, 10, "PHONE")])], [[(0, 10, "PHONE"), (11, 12, "PHONE")]])
    assert abs(r["overall"]["f2"] - (2.5 / 3)) < 1e-9


# ── runner ─────────────────────────────────────────────────────────────
def test_run_benchmark_crf_high_fp_recall():
    r = run_benchmark(engine="crf", seed=42, size=60)
    for t in ["THAI_ID", "CREDIT_CARD", "EMAIL", "PHONE"]:
        assert r["by_type"][t]["recall"] >= 0.95, (t, r["by_type"][t])
    assert "PHONE" in render_table(r)


# ── CI gate: CRF recall floors (calibrated from the seed=42 size=200 run) ──
def test_ci_gate_crf_recall_floors():
    r = run_benchmark(engine="crf", seed=42, size=200)
    bt = r["by_type"]
    # Structured PII with an unambiguous format: regex+checksum -> near-perfect.
    for t in ["THAI_ID", "CREDIT_CARD", "PASSPORT", "EMAIL", "PHONE",
              "STUDENT_ID", "VEHICLE_PLATE", "DATE_OF_BIRTH"]:
        assert bt[t]["recall"] >= 0.99, (t, bt[t])
    # VEHICLE_PLATE precision: half the synthetic addresses use a "ซอย N" soi
    # form, which the loose plate regex would flag as a plate. The locality
    # stopword (fp_detector._PLATE_STOPWORDS) suppresses it, so precision stays
    # perfect. observed 1.000 -- a regression here means the ซอย guard broke.
    assert bt["VEHICLE_PLATE"]["precision"] >= 0.99, bt["VEHICLE_PLATE"]
    # BANK_ACCOUNT: a 10-digit account starting 06-09 also matches the mobile
    # pattern; the context disambiguation (fp_detector._disambiguate_bank_phone)
    # sees the "บัญชีธนาคาร" cue in the bank_complaint template and keeps BANK,
    # so type-aware recall is now perfect. observed 1.000 (was 0.921 pre-fix).
    assert bt["BANK_ACCOUNT"]["recall"] >= 0.99, bt["BANK_ACCOUNT"]
    # NAME: the name-context booster keeps this high. observed 0.994.
    assert bt["NAME"]["recall"] >= 0.95, bt["NAME"]
    # ADDRESS: CRF location recall is weak -- THIS is the headline gap the
    # WangchanBERTa comparison should close. observed 0.594 (the soi form carries
    # อำเภอ/เขต cues the CRF catches more often); floor deliberately low.
    assert bt["ADDRESS"]["recall"] >= 0.30, bt["ADDRESS"]
    # Every known recall-leak shape (Thai-glued id/email, +66 mobile) still caught.
    assert r["by_slice"]["hard_case"]["recall"] >= 0.99, r["by_slice"]["hard_case"]
    # The black box actually covers PII characters end to end.
    assert r["overall"]["coverage_recall"] >= 0.90, r["overall"]


# ── WangchanBERTa comparison (opt-in; requires requirements-ml.txt) ─────
@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="requires requirements-ml.txt",
)
def test_wangchanberta_engine_runs_and_switches():
    # Assert the engine actually LOADS and RUNS (the singleton-reset in
    # run_benchmark must let wangchanberta take effect even after a prior crf
    # run in the same process). We do NOT assert wcb > crf here -- whether the
    # transformer beats the CRF is the hypothesis under test, reported as a
    # number by the comparison run, not gated by a test.
    wcb = run_benchmark(engine="wangchanberta", seed=42, size=40)
    assert wcb["engine"] == "wangchanberta"
    assert wcb["by_type"]["NAME"]["tp"] + wcb["by_type"]["NAME"]["fn"] > 0
    assert 0.0 <= wcb["by_type"]["ADDRESS"]["recall"] <= 1.0
