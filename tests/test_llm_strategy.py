"""Tests for the LLM-as-detector baseline's parsing and span mapping.

Pure functions only -- no network. What a hosted model actually answers is
measured by scripts/run_llm_benchmark.py, not pinned here.
"""

from __future__ import annotations

import pytest

from benchmark.llm_providers import ProviderUnavailable, build_caller
from benchmark.llm_strategy import locate, parse_items


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
