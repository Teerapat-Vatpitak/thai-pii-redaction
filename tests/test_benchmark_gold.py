"""Tests for the hand-authored Thai PII gold set (benchmark v2)."""
from __future__ import annotations

import importlib.util

import pytest

from benchmark.gold import parse_gold, load_gold, GOLD_DOCS, GOLD_SLICES
from benchmark.runner import run_benchmark
from pii_redactor.detectors.fp_detector import detect_fp

_TITLE_CUES = ("นาย", "นาง", "นางสาว", "น.ส.", "ด.ช.", "ด.ญ.", "เด็กชาย", "เด็กหญิง")
_INTRO_CUES = ("ลงชื่อ", "ผมชื่อ", "ดิฉันชื่อ", "ชื่อ")


# ── parser ─────────────────────────────────────────────────────────────
def test_parse_gold_strips_markup_and_aligns_spans():
    s = parse_gold("t", "name_no_cue", "เรียน [[NAME|สมชาย ใจดี]] ที่บัญชี [[BANK_ACCOUNT|0612345678]]")
    assert "[[" not in s.text and "]]" not in s.text
    assert s.text == "เรียน สมชาย ใจดี ที่บัญชี 0612345678"
    for sp in s.spans:
        assert sp.end > sp.start
    assert s.text[s.spans[0].start:s.spans[0].end] == "สมชาย ใจดี"
    assert s.spans[0].entity_type == "NAME"
    assert s.text[s.spans[1].start:s.spans[1].end] == "0612345678"
    assert s.spans[1].entity_type == "BANK_ACCOUNT"


def test_every_gold_span_round_trips():
    # Re-parse each doc and confirm every labeled value matches its span exactly.
    for doc_id, slice_, annotated in GOLD_DOCS:
        s = parse_gold(doc_id, slice_, annotated)
        for sp in s.spans:
            assert s.text[sp.start:sp.end], (doc_id, sp)
            assert "[[" not in s.text, doc_id


# ── coverage / slice integrity ─────────────────────────────────────────
def test_all_slices_present_and_nonempty():
    by_slice = {sl: 0 for sl in GOLD_SLICES}
    for s in load_gold():
        assert s.slice in GOLD_SLICES, s.slice
        by_slice[s.slice] += 1
    for sl, n in by_slice.items():
        assert n >= 10, (sl, n)


def test_name_no_cue_names_have_no_title_or_intro_cue():
    for s in load_gold():
        if s.slice != "name_no_cue":
            continue
        for sp in s.spans:
            if sp.entity_type != "NAME":
                continue
            before = s.text[max(0, sp.start - 8):sp.start]
            assert not any(before.endswith(c) for c in _TITLE_CUES), (s.template_id, before)
            assert not any(before.rstrip().endswith(c) for c in _INTRO_CUES), (s.template_id, before)


def test_bank_phone_slice_has_both_types():
    types = {
        sp.entity_type
        for s in load_gold() if s.slice == "bank_phone"
        for sp in s.spans
    }
    assert "BANK_ACCOUNT" in types
    assert "PHONE" in types


# ── runner --source gold ───────────────────────────────────────────────
def test_run_benchmark_source_gold():
    r = run_benchmark(engine="crf", source="gold")
    assert r["source"] == "gold"
    assert r["corpus"]["samples"] == len(load_gold())
    for sl in GOLD_SLICES:
        assert sl in r["by_slice"]


def test_gold_structured_clearformat_still_strong():
    # Clear-format structured PII should still be caught on gold (sanity, not a
    # NAME/ADDRESS floor -- those are the hard cases gold exists to expose).
    r = run_benchmark(engine="crf", source="gold")
    for t in ("THAI_ID", "EMAIL"):
        if t in r["by_type"]:
            assert r["by_type"][t]["recall"] >= 0.9, (t, r["by_type"][t])


# ── BANK vs PHONE disambiguation ───────────────────────────────────────
def _types_over(text, lo_substr):
    lo = text.index(lo_substr)
    return {e.data_type for e in detect_fp(text) if e.span[0] <= lo < e.span[1]}


def test_bank_cue_makes_10digit_a_bank_account():
    text = "เลขที่บัญชี 0612345678 ธนาคารกรุงเทพ"
    assert "BANK_ACCOUNT" in _types_over(text, "0612345678")


def test_phone_cue_keeps_10digit_a_phone():
    text = "โทร 0612345678 เพื่อสอบถาม"
    assert "PHONE" in _types_over(text, "0612345678")


def test_no_cue_10digit_defaults_to_phone():
    text = "หมายเลข 0612345678 นี้"
    assert "PHONE" in _types_over(text, "0612345678")


def test_bank_cue_far_before_number_still_wins():
    # gold bp05-shape: the บัญชี/ธนาคาร cue sits a whole clause (~25 chars)
    # before the number, with a type-neutral "เลขที่" right in front of it.
    text = "บัญชีธนาคารกสิกรไทย เลขที่ 0731122334 พร้อมสลิป"
    assert "BANK_ACCOUNT" in _types_over(text, "0731122334")


# ── WangchanBERTa gold comparison (opt-in) ─────────────────────────────
@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="requires requirements-ml.txt",
)
def test_wangchanberta_gold_runs():
    r = run_benchmark(engine="wangchanberta", source="gold")
    assert r["source"] == "gold"
    assert r["by_type"].get("NAME", {}).get("tp", 0) + r["by_type"].get("NAME", {}).get("fn", 0) > 0
