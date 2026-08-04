"""Label-aware `_name_hygiene` segmentation (gov-form OCR gap, F2).

On label-first OCR field order the thainer CRF can glue a form label to the
real name(s) that follow it into ONE PERSON span, e.g. (reproduced from the
ภ.ง.ด.91 OCR corpus, M6-P0 mechanism 2, OCR edit distance 0):

    เดือนปีเกิด\n\nกิตติ พรดี\nพิมพ์ใจ แสนดี

The old unconditional head-keep trimmed this span at the first newline and
kept the HEAD -- "เดือนปีเกิด" ("month/year of birth", a form label) became a
false-positive NAME, and both real names past the break were discarded
entirely. These tests pin the fix: the span is split at newlines into
segments, label/compound segments are dropped, and each surviving
name-shaped segment becomes its own NAME entity at its own offsets.
"""

from __future__ import annotations

import pytest

import pii_redactor.detectors.tb_detector as tbd
from pii_redactor.detectors.name_context import is_glued_name_run

OCR_LABEL_FIRST_SPAN = "เดือนปีเกิด\n\nกิตติ พรดี\nพิมพ์ใจ แสนดี"


def test_name_hygiene_drops_form_label_and_recovers_both_names():
    prefix = "หัวข้อฟอร์ม\n"
    suffix = "\nท้ายเอกสาร"
    text = prefix + OCR_LABEL_FIRST_SPAN + suffix
    start = len(prefix)
    end = start + len(OCR_LABEL_FIRST_SPAN)

    spans = tbd._name_hygiene(text, start, end)

    texts = [text[s:e] for s, e in spans]
    assert texts == ["กิตติ พรดี", "พิมพ์ใจ แสนดี"], texts
    assert "เดือนปีเกิด" not in texts


def test_name_hygiene_segment_offsets_are_exact():
    text = "หัว\n" + OCR_LABEL_FIRST_SPAN + "\nท้าย"
    start = len("หัว\n")
    end = start + len(OCR_LABEL_FIRST_SPAN)

    spans = tbd._name_hygiene(text, start, end)

    assert len(spans) == 2
    name1_start = text.index("กิตติ พรดี")
    name2_start = text.index("พิมพ์ใจ แสนดี")
    assert spans[0] == (name1_start, name1_start + len("กิตติ พรดี"))
    assert spans[1] == (name2_start, name2_start + len("พิมพ์ใจ แสนดี"))


def test_name_hygiene_drops_segment_with_digits():
    entity_text = "กิตติ พรดี\n12345"
    text = "หัว\n" + entity_text + "\nท้าย"
    start = len("หัว\n")
    end = start + len(entity_text)

    spans = tbd._name_hygiene(text, start, end)

    texts = [text[s:e] for s, e in spans]
    assert texts == ["กิตติ พรดี"], texts


def test_name_hygiene_no_newline_unchanged_single_span():
    # Single-line span: no segmentation needed, behaves exactly as before.
    text = "หัว\nกิตติ พรดี\nท้าย"
    start = text.index("กิตติ พรดี")
    end = start + len("กิตติ พรดี")

    spans = tbd._name_hygiene(text, start, end)

    assert spans == [(start, end)]


def test_name_hygiene_cue_veto_preserved():
    # The next line opens with a name cue ("นาย ...") -> the cue pass owns
    # the person; the whole span (including any earlier junk head) is
    # dropped rather than emitting a bogus NAME from glued ordinary words.
    entity_text = "ข้อมูลทั่วไป\nนาย สมชาย ใจดี"
    text = "หัว\n" + entity_text + "\nท้าย"
    start = len("หัว\n")
    end = start + len(entity_text)

    assert tbd._name_hygiene(text, start, end) == []


def test_name_hygiene_single_line_document_compound_still_rejected():
    # Regression: the original (no-newline) compound rejection is untouched.
    text = "ตารางสอบปลายภาค วันจันทร์ ถึง วันศุกร์"
    start = 0
    end = len("ตารางสอบปลายภาค")

    assert tbd._name_hygiene(text, start, end) == []


def test_finalize_tb_candidate_emits_two_name_entities_for_label_first_span():
    """Integration through the CRF call site: one PERSON BIO span covering
    the label-first OCR text yields two NAME entities, not one label FP."""
    prefix = "หัวข้อฟอร์ม\n"
    text = prefix + OCR_LABEL_FIRST_SPAN + "\nท้ายเอกสาร"
    start = len(prefix)
    end = start + len(OCR_LABEL_FIRST_SPAN)

    entities = tbd._finalize_tb_candidate(text, start, end, "PERSON")

    assert [e.data_type for e in entities] == ["NAME", "NAME"]
    names = {e.original_text for e in entities}
    assert names == {"กิตติ พรดี", "พิมพ์ใจ แสนดี"}
    for e in entities:
        assert text[e.span[0] : e.span[1]] == e.original_text


# ---------------------------------------------------------------------------
# The HEAD keeps the original lenient rule (>= 2 chars after rstrip, not a
# document compound). Applying the strict segment shape to it too dropped the
# real name outright whenever a comma, a parenthesised role, an age or Latin
# script sat in the head -- the sample-PDF regression class, measured A/B on
# the branch review. These four are that measurement, turned into tests.
# ---------------------------------------------------------------------------


def _hygiene_texts(entity_text: str) -> list[str]:
    text = "หัว\n" + entity_text + "\nท้าย"
    start = len("หัว\n")
    spans = tbd._name_hygiene(text, start, start + len(entity_text))
    for s, e in spans:
        assert 0 <= s < e <= len(text)
    return [text[s:e] for s, e in spans]


@pytest.mark.parametrize(
    ("entity_text", "expected_head"),
    [
        ("สมชาย ใจดี,\nที่อยู่ 99 ถนนสุขุมวิท", "สมชาย ใจดี,"),
        ("สมชาย ใจดี (ผู้ยื่น)\nวันที่ 1 สิงหาคม", "สมชาย ใจดี (ผู้ยื่น)"),
        # 2026-08-04 (fn10 digit-run truncation): the head is now cut at its
        # first digit run — the NAME survives, the age suffix does not. A
        # digits-glued head kept whole is exactly what let dedupe_spans drop
        # a whole name for overlapping the FP span on its tail.
        ("สมชาย ใจดี 45 ปี\nอาชีพ", "สมชาย ใจดี"),
        ("John Smith\nAddress 12", "John Smith"),
    ],
)
def test_name_hygiene_head_survives_mixed_content(entity_text, expected_head):
    assert _hygiene_texts(entity_text) == [expected_head]


# ---------------------------------------------------------------------------
# Trailing segments: a Thai form label or letter closing is not a person.
# Each string below is a reproduced false positive from the branch review's
# gold attribution (12 instances across 9 distinct strings) or its HR-letter
# repro; each was emitted as its own NAME entity before this gate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "เลขประจำตัวประชาชน",
        "ที่อยู่",
        "ที่อยู่จัดส่งเอกสาร",
        "บัญชีรับเงินกู้",
        "บัญชีรับเงินคืน",
        "วันเดือนปีเกิด",
        "ท่านมียอดค้างชำระ",
        "ขอแสดงความนับถือ",
        "ตำแหน่ง",
    ],
)
def test_name_hygiene_drops_trailing_form_label_segment(label):
    texts = _hygiene_texts("บุญช่วย ศิริพัฒน์\n" + label)
    assert texts == ["บุญช่วย ศิริพัฒน์"], texts


def test_name_hygiene_keeps_real_trailing_name_whose_tokens_split_on_a_stop_word():
    # The rejection is the LEADING token only. newmm splits the real surname
    # "ทองอยู่" into ทอง|อยู่ and "อยู่" is a stop word in two lexicons -- an
    # every-token rule would unmask this person.
    assert _hygiene_texts("กิตติ พรดี\nชลธิชา ทองอยู่") == ["กิตติ พรดี", "ชลธิชา ทองอยู่"]


def test_name_hygiene_trims_trailing_punctuation_on_tail_segment():
    # Trim the comma, do not drop the segment (the strict shape gate would
    # otherwise discard a real name because of an OCR line-break comma).
    assert _hygiene_texts("กิตติ พรดี\nพิมพ์ใจ แสนดี,") == ["กิตติ พรดี", "พิมพ์ใจ แสนดี"]


def test_full_birth_date_label_rejected_by_both_rules():
    # The compound regex is used with .match(), so the full form spelling
    # needed its own alternative. Pin that the two rules the branch unified
    # now agree on this exact string.
    assert tbd._NAME_DOC_COMPOUND_RE.match("วันเดือนปีเกิด") is not None
    assert is_glued_name_run("วันเดือนปีเกิด") is False


def test_detect_tb_finetuned_emits_two_name_entities_for_label_first_span(monkeypatch):
    """Same contract on the fine-tuned engine call site (`_detect_tb_finetuned`,
    'every neural engine' per its docstring)."""
    monkeypatch.setenv("AIGUARD_NER_ENGINE", "finetuned")
    prefix = "หัวข้อฟอร์ม\n"
    text = prefix + OCR_LABEL_FIRST_SPAN + "\nท้ายเอกสาร"
    start = len(prefix)
    end = start + len(OCR_LABEL_FIRST_SPAN)

    class _FakeEngine:
        def spans(self, _text):
            return [(start, end, "PERSON", 0.97)]

    monkeypatch.setitem(tbd._finetuned_cache, "engine", _FakeEngine())
    try:
        entities = tbd.detect_tb(text)
    finally:
        tbd._finetuned_cache.pop("engine", None)

    names = {e.original_text for e in entities if e.data_type == "NAME"}
    assert names == {"กิตติ พรดี", "พิมพ์ใจ แสนดี"}
    assert not any(e.original_text == "เดือนปีเกิด" for e in entities)
