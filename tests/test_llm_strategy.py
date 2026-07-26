"""Tests for the LLM-as-detector baseline's parsing and span mapping.

Pure functions only -- no network. What a hosted model actually answers is
measured by scripts/run_llm_benchmark.py, not pinned here.
"""

from __future__ import annotations

import pytest

from benchmark.llm_providers import ProviderUnavailable, build_caller
from benchmark.llm_strategy import UNTYPED, locate, parse_items, score_raw


# ── parsing ────────────────────────────────────────────────────────────
def test_parse_plain_json_array():
    items, rejected = parse_items('[{"type": "NAME", "value": "สมชาย ใจดี"}]')
    assert items == [("NAME", "สมชาย ใจดี")]
    assert rejected == []


def test_parse_tolerates_code_fence_and_prose():
    # Scoring output formatting instead of detection would make the comparison
    # meaningless, so a fenced or prefixed answer must still parse.
    raw = 'นี่คือผลลัพธ์\n```json\n[{"type": "EMAIL", "value": "a@b.com"}]\n```'
    items, _ = parse_items(raw)
    assert items == [("EMAIL", "a@b.com")]


def test_parse_lowercase_type_is_normalised():
    items, _ = parse_items('[{"type": "phone", "value": "0812345678"}]')
    assert items == [("PHONE", "0812345678")]


def test_parse_records_invented_types_instead_of_scoring_them():
    items, rejected = parse_items(
        '[{"type": "NICKNAME", "value": "ต้น"}, {"type": "NAME", "value": "สมชาย"}]'
    )
    assert items == [("NAME", "สมชาย")]
    assert rejected == ["NICKNAME"]


def test_parse_bare_object_counts_as_one_row():
    # OpenThaiGPT answers with a bare object when there is exactly one hit.
    # Same answer, different wrapper.
    items, _ = parse_items('{"type": "NAME", "value": "วิชัย ประสงค์ดี"}')
    assert items == [("NAME", "วิชัย ประสงค์ดี")]


def test_parse_objects_without_an_enclosing_array():
    raw = '{"type": "NAME", "value": "สมชาย"}\n{"type": "PHONE", "value": "0812345678"}'
    items, _ = parse_items(raw)
    assert items == [("NAME", "สมชาย"), ("PHONE", "0812345678")]


def test_parse_strips_a_reasoning_block_before_looking_for_the_answer():
    raw = '<think>\nลองพิจารณา [1] กับ [2] ก่อน\n</think>\n\n[{"type": "EMAIL", "value": "a@b.com"}]'
    items, _ = parse_items(raw)
    assert items == [("EMAIL", "a@b.com")]


def test_parse_unclosed_reasoning_block_yields_nothing():
    # The token budget ran out mid-reasoning, so no answer was ever produced.
    items, _ = parse_items('<think>\nกำลังคิด {"type": "NAME", "value": "x"}')
    assert items == []


def test_parse_empty_and_malformed_are_no_detections_not_crashes():
    for raw in ("", "   ", "ไม่พบข้อมูลส่วนบุคคล", "[", '{"type": "NAME"}', "[]"):
        items, _ = parse_items(raw)
        assert items == []


def test_parse_skips_rows_without_a_usable_value():
    items, _ = parse_items('[{"type": "NAME", "value": ""}, {"type": "NAME", "value": 42}]')
    assert items == []


# ── span mapping ───────────────────────────────────────────────────────
def test_locate_finds_every_occurrence_of_a_value():
    text = "ติดต่อ 0812345678 หรือ 0812345678 ได้"
    spans = locate(text, [("PHONE", "0812345678")])
    assert len(spans) == 2
    assert all(text[a:b] == "0812345678" for a, b, _ in spans)


def test_locate_claims_longest_first_and_never_overlaps():
    # The short value sits inside the long one; without longest-first claiming
    # it would steal characters and be counted as a second detection.
    text = "ที่อยู่ 45/12 หมู่ 3 ตำบลบางพระ"
    spans = locate(text, [("ADDRESS", "45/12 หมู่ 3 ตำบลบางพระ"), ("ADDRESS", "45/12")])
    assert len(spans) == 1
    assert text[spans[0][0] : spans[0][1]] == "45/12 หมู่ 3 ตำบลบางพระ"


def test_locate_drops_values_absent_from_the_source():
    # A paraphrased or invented value has no span. It must not be scored as a
    # detection, and the caller counts it as unlocatable.
    spans = locate("ชื่อ สมชาย ใจดี", [("NAME", "นายสมชาย ใจดี")])
    assert spans == []


def test_locate_returns_spans_in_document_order():
    text = "a@b.com คุยกับ สมชาย"
    spans = locate(text, [("NAME", "สมชาย"), ("EMAIL", "a@b.com")])
    assert [t for _, _, t in spans] == ["EMAIL", "NAME"]


# ── type-agnostic view ─────────────────────────────────────────────────
def test_lenient_parse_keeps_rows_the_strict_view_drops():
    # Pathumma answers with the Thai field label as the type. Strict scoring
    # drops those rows, which measures instruction-following; the lenient view
    # keeps the value so "did it find the PII" can be measured on its own.
    raw = '[{"type": "ที่อยู่ปัจจุบัน", "value": "12 ถนนสุขุมวิท"}]'
    strict, rejected = parse_items(raw, strict=True)
    lenient, _ = parse_items(raw, strict=False)
    assert strict == []
    assert rejected == ["ที่อยู่ปัจจุบัน"]
    assert lenient == [(UNTYPED, "12 ถนนสุขุมวิท")]


def test_lenient_parse_also_relabels_known_types():
    # Both views must be scored against a single relabelled gold set, so a row
    # the strict view accepts still has to come back as UNTYPED here.
    lenient, _ = parse_items('[{"type": "NAME", "value": "สมชาย"}]', strict=False)
    assert lenient == [(UNTYPED, "สมชาย")]


def test_score_raw_produces_both_views_from_one_response():
    text = "ผู้ป่วย สมชาย ใจดี ที่อยู่ 12 ถนนสุขุมวิท"
    raw = '[{"type": "NAME", "value": "สมชาย ใจดี"}, {"type": "ที่อยู่ปัจจุบัน", "value": "12 ถนนสุขุมวิท"}]'
    rec = score_raw(text, raw)
    assert [t for _, _, t in rec["spans"]] == ["NAME"]
    assert [t for _, _, t in rec["untyped_spans"]] == [UNTYPED, UNTYPED]
    assert rec["meta"]["kept_typed"] == 1
    assert rec["meta"]["returned"] == 2
    assert rec["meta"]["unlocatable"] == 0


def test_score_raw_counts_unlocatable_against_the_lenient_view():
    rec = score_raw("ชื่อ สมชาย", '[{"type": "NAME", "value": "นายสมชาย เกิดปี 2530"}]')
    assert rec["spans"] == []
    assert rec["untyped_spans"] == []
    assert rec["meta"]["unlocatable"] == 1


def test_unlocatable_counts_values_not_spans():
    # One returned value, two occurrences in the text. locate() emits a span
    # per occurrence on purpose, so a formula counting values-minus-spans goes
    # negative here (1 value - 2 spans = -1). The field must stay non-negative
    # because it counts values, not spans.
    text = "โทร 081-234-5678 หรือ 081-234-5678"
    raw = '[{"type": "PHONE", "value": "081-234-5678"}]'

    meta = score_raw(text, raw)["meta"]

    assert meta["unlocatable"] == 0


def test_unlocatable_does_not_cancel_out_across_values():
    # A value repeated in the text (contributes 0) alongside a genuinely
    # unlocatable value (contributes 1) in the SAME run. The old
    # values-minus-spans formula computed 2 rows - 2 spans = 0 here, silently
    # hiding the one real miss behind the other value's repeat occurrence.
    # This must not be satisfiable by hardcoding zero.
    text = "โทร 081-234-5678 หรือ 081-234-5678"
    raw = (
        '[{"type": "PHONE", "value": "081-234-5678"}, '
        '{"type": "EMAIL", "value": "ไม่มีอยู่จริง@example.com"}]'
    )

    meta = score_raw(text, raw)["meta"]

    assert meta["unlocatable"] == 1


def test_score_values_reproduces_score_raw_without_the_body():
    from benchmark.llm_strategy import parse_values, score_raw, score_values

    text = "ผมชื่อ นายสมชาย ใจดี โทร 081-234-5678"
    raw = '[{"type":"NAME","value":"นายสมชาย ใจดี"},'
    raw += '{"type":"PHONE","value":"081-234-5678"}]'

    from_raw = score_raw(text, raw)
    from_values = score_values(text, parse_values(raw))

    # Both sides must carry real spans -- otherwise this equality is satisfied
    # by two empty lists no matter what score_values does.
    assert from_raw["spans"] != []
    assert from_values["spans"] == from_raw["spans"]
    assert from_values["untyped_spans"] == from_raw["untyped_spans"]


def test_cache_entry_holds_no_provider_body(tmp_path):
    import json

    from benchmark.llm_strategy import parse_values, score_values

    text = "ผมชื่อ นายสมชาย ใจดี"
    raw = "<think>reasoning: I looked at the sentence and decided</think>\n"
    raw += '[{"type": "NAME", "value": "นายสมชาย ใจดี"}]'

    entry = {"values": parse_values(raw), **score_values(text, parse_values(raw))}
    written = json.dumps(entry, ensure_ascii=False)

    assert "reasoning" not in written
    assert "I looked at the sentence" not in written
    # The stripped prose must not be the only thing missing -- the entry has to
    # carry the actual detection, or "no body" is indistinguishable from "no
    # content at all".
    assert entry["values"] != []


# ── provider construction ──────────────────────────────────────────────
def test_non_ascii_api_key_fails_loudly_at_construction(monkeypatch):
    # A key with Thai text pasted beside it otherwise dies inside httpx with a
    # UnicodeEncodeError naming neither the variable nor the cause.
    monkeypatch.setenv("THAILLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("THAILLM_API_KEY", "sk-abc ใช้คีย์นี้")
    with pytest.raises(ProviderUnavailable, match="non-ASCII"):
        build_caller("thaillm:some-model")


def test_missing_credential_fails_loudly(monkeypatch):
    monkeypatch.setenv("THAILLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.delenv("THAILLM_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable, match="THAILLM_API_KEY"):
        build_caller("thaillm:some-model")


def test_unknown_provider_spec_is_rejected():
    with pytest.raises(ValueError):
        build_caller("nope:model")
