"""Tests for the hand-authored Thai PII gold set (benchmark v3)."""

from __future__ import annotations

import collections
import importlib.util
import json
import re

import pytest

from benchmark.gold import (
    _DATA_PATH,
    GOLD_DOCS,
    GOLD_LAYERS,
    GOLD_SLICES,
    GOLD_VERSION,
    LONG_FORM_MIN_CHARS,
    SLICE_LAYERS,
    load_gold,
    parse_gold,
)
from benchmark.runner import run_benchmark
from benchmark.scorer import score
from pii_redactor.detectors.fp_detector import detect_fp

_TITLE_CUES = ("นาย", "นาง", "นางสาว", "น.ส.", "ด.ช.", "ด.ญ.", "เด็กชาย", "เด็กหญิง")
_INTRO_CUES = ("ลงชื่อ", "ผมชื่อ", "ดิฉันชื่อ", "ชื่อ")

# Every type must reach this many instances before a per-type number from this
# set is worth printing at all.
_MIN_PER_TYPE = 20

_MARKUP = re.compile(r"\[\[([A-Z_]+)\|(.*?)\]\]")


def _labeled_values() -> list[tuple[str, str, str, str]]:
    """(doc_id, slice, entity_type, raw value) for every label in the set."""
    return [
        (doc_id, slice_, t, v)
        for doc_id, slice_, annotated in GOLD_DOCS
        for t, v in _MARKUP.findall(annotated)
    ]


# ── parser ─────────────────────────────────────────────────────────────
def test_parse_gold_strips_markup_and_aligns_spans():
    s = parse_gold("t", "name_no_cue", "เรียน [[NAME|สมชาย ใจดี]] ที่บัญชี [[BANK_ACCOUNT|0612345678]]")
    assert "[[" not in s.text and "]]" not in s.text
    assert s.text == "เรียน สมชาย ใจดี ที่บัญชี 0612345678"
    for sp in s.spans:
        assert sp.end > sp.start
    assert s.text[s.spans[0].start : s.spans[0].end] == "สมชาย ใจดี"
    assert s.spans[0].entity_type == "NAME"
    assert s.text[s.spans[1].start : s.spans[1].end] == "0612345678"
    assert s.spans[1].entity_type == "BANK_ACCOUNT"


def test_every_gold_span_round_trips():
    # Re-parse each doc and confirm every labeled value matches its span exactly.
    for doc_id, slice_, annotated in GOLD_DOCS:
        s = parse_gold(doc_id, slice_, annotated)
        for sp in s.spans:
            assert s.text[sp.start : sp.end], (doc_id, sp)
            assert "[[" not in s.text, doc_id


# ── coverage / slice integrity ─────────────────────────────────────────
def test_all_slices_present_and_nonempty():
    by_slice = dict.fromkeys(GOLD_SLICES, 0)
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
            before = s.text[max(0, sp.start - 8) : sp.start]
            assert not any(before.endswith(c) for c in _TITLE_CUES), (s.template_id, before)
            assert not any(before.rstrip().endswith(c) for c in _INTRO_CUES), (
                s.template_id,
                before,
            )


def test_bank_phone_slice_has_both_types():
    types = {sp.entity_type for s in load_gold() if s.slice == "bank_phone" for sp in s.spans}
    assert "BANK_ACCOUNT" in types
    assert "PHONE" in types


# ── v3: size, layers, checksums, negatives ─────────────────────────────
def test_every_type_reaches_reportable_n():
    counts = collections.Counter(t for _, _, t, _ in _labeled_values())
    thin = {t: n for t, n in counts.items() if n < _MIN_PER_TYPE}
    assert not thin, f"types below n={_MIN_PER_TYPE}: {thin}"


def test_doc_ids_are_unique():
    ids = [doc_id for doc_id, _, _ in GOLD_DOCS]
    dupes = [i for i, n in collections.Counter(ids).items() if n > 1]
    assert not dupes, dupes


def test_every_doc_has_a_known_layer_matching_its_slice():
    for doc_id, slice_, _ in GOLD_DOCS:
        assert slice_ in SLICE_LAYERS, (doc_id, slice_)
        assert GOLD_LAYERS[doc_id] == SLICE_LAYERS[slice_], (doc_id, slice_)


def test_loader_reads_every_line_of_the_data_file():
    with _DATA_PATH.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(GOLD_DOCS) == len(records)
    assert len(load_gold()) == len(records)


def _thai_id_checksum_ok(digits: str) -> bool:
    # Independent re-implementation on purpose: sharing the detector's helper
    # would let one bug validate itself.
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = sum(int(digits[i]) * (13 - i) for i in range(12))
    return (11 - total % 11) % 10 == int(digits[12])


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def test_checksum_bearing_values_are_valid():
    # A fake THAI_ID/CREDIT_CARD that fails its own checksum would be silently
    # unreachable for the detector, turning a labeled entity into a permanent
    # false negative that says nothing about detection quality.
    for doc_id, _, etype, value in _labeled_values():
        digits = re.sub(r"\D", "", value)
        if etype == "THAI_ID":
            assert _thai_id_checksum_ok(digits), (doc_id, value)
        elif etype == "CREDIT_CARD":
            assert _luhn_ok(digits), (doc_id, value)


def test_negative_slice_documents_carry_no_labels():
    negatives = [s for s in load_gold() if s.slice == "negative"]
    assert negatives
    for s in negatives:
        assert s.spans == [], (s.template_id, s.spans)


def test_pii_values_are_not_reused_across_documents():
    # A value repeated in two different documents lets a detector look good by
    # memorising one string. Repeats WITHIN one document are the opposite -- the
    # same person named twice in one form is normal, and the product is supposed
    # to give both mentions the same pseudonym.
    #
    # bank_phone is exempt entirely: it reuses one number in a bank context and
    # a phone context on purpose, to probe that ambiguity.
    numeric = {"THAI_ID", "CREDIT_CARD", "PHONE", "BANK_ACCOUNT", "STUDENT_ID"}
    seen: dict[tuple[str, str], str] = {}
    for doc_id, slice_, etype, value in _labeled_values():
        if slice_ == "bank_phone":
            continue
        # Digit-normalise the numeric types so a dashed and an undashed copy of
        # the same number still collide. Keyed per type: a student id echoed
        # inside that student's university email is real, not a duplicate.
        key = (etype, re.sub(r"\D", "", value) if etype in numeric else value)
        owner = seen.setdefault(key, doc_id)
        assert owner == doc_id, (key, owner, doc_id)


def test_long_form_documents_cross_the_chunk_boundary():
    # The point of this slice: the detector windows text in 500-char chunks, and
    # every other document here is far too short to reach a boundary.
    long_docs = [s for s in load_gold() if s.slice == "long_form"]
    assert len(long_docs) >= 20
    for s in long_docs:
        assert len(s.text) > LONG_FORM_MIN_CHARS, (s.template_id, len(s.text))
        assert len(s.spans) >= 6, (s.template_id, len(s.spans))
    past_boundary = [
        s.template_id for s in long_docs for sp in s.spans if sp.start >= LONG_FORM_MIN_CHARS
    ]
    assert len(set(past_boundary)) >= 5, past_boundary


def test_student_id_probe_slice_varies_one_axis_at_a_time():
    probes = [s for s in load_gold() if s.slice == "student_id_varied"]
    assert len(probes) >= 20
    assert all(any(sp.entity_type == "STUDENT_ID" for sp in s.spans) for s in probes)
    # The axes the slice exists to separate: digit count, and glued vs spaced.
    lengths = {
        len(re.sub(r"\D", "", s.text[sp.start : sp.end]))
        for s in probes
        for sp in s.spans
        if sp.entity_type == "STUDENT_ID"
    }
    assert {8, 10} <= lengths, lengths


def test_negative_slice_is_large_enough_to_state_a_rate():
    # 12 documents put the clean-document rate's confidence interval so wide it
    # could not be reported; this floor is what makes the number publishable.
    assert sum(1 for s in load_gold() if s.slice == "negative") >= 45


def test_negative_slice_is_scored_as_false_positives_not_recall():
    samples = [s for s in load_gold() if s.slice == "negative"]
    # One document scored as if the detector flagged a stretch of it.
    preds = [[(0, 5, "NAME")]] + [[] for _ in samples[1:]]
    sl = score(samples, preds)["by_slice"]["negative"]
    assert sl["gold_entities"] == 0
    assert "recall" not in sl
    assert sl["false_positives"] == 1
    assert sl["clean_docs"] == len(samples) - 1


# ── runner --source gold ───────────────────────────────────────────────
def test_run_benchmark_source_gold():
    r = run_benchmark(engine="crf", source="gold")
    assert r["source"] == "gold"
    assert r["gold_version"] == GOLD_VERSION
    assert r["corpus"]["samples"] == len(load_gold())
    assert r["confidence_intervals"]["overall_f2"]["unit"] == "document"
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
