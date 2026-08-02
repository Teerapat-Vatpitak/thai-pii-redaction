"""Regression coverage for Issue #82 Thai NER span boundaries.

The checked-in medical fixture is synthetic and remains the source of truth for
the reported case. These tests keep the fix general: a CRF span that crosses a
line into a name cue is rejected, the cue pass supplies the complete name, and
location text after a name remains independently detectable.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

import pii_redactor.detectors.tb_detector as tbd
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.session_service import SessionService

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "prompts" / "02_medical_consult.txt"


def _fixture_text_and_name() -> tuple[str, str]:
    text = FIXTURE.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if "ชื่อ" in line and "อายุ" in line)
    name = line.split("ชื่อ", 1)[1].split("อายุ", 1)[0].strip()
    return text, name


def _use_default_crf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIGUARD_NER_ENGINE", raising=False)
    monkeypatch.setattr(tbd, "_ner_cache", {})


def test_issue_82_fixture_has_one_full_name_and_no_nested_location(monkeypatch):
    """The raw model may be wrong, but the product boundary must be right."""
    _use_default_crf(monkeypatch)
    text, expected_name = _fixture_text_and_name()
    expected_start = text.index(expected_name)
    expected_span = (expected_start, expected_start + len(expected_name))

    tb_entities = detect_tb(text)
    all_entities = detect_all(text)

    for entities in (tb_entities, all_entities):
        names = [entity for entity in entities if entity.data_type == "NAME"]
        assert any(entity.span == expected_span for entity in names)
        assert not any(
            entity.data_type == "LOCATION"
            and expected_span[0] <= entity.span[0]
            and entity.span[1] <= expected_span[1]
            for entity in entities
        )
        for entity in entities:
            assert text[entity.span[0] : entity.span[1]] == entity.original_text


def test_issue_82_fixture_round_trips_through_api_and_session(monkeypatch):
    """Detection, masking, and restore preserve the corrected source span."""
    _use_default_crf(monkeypatch)
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import server

    text, expected_name = _fixture_text_and_name()
    expected_clean = clean(text).text
    expected_start = expected_clean.index(expected_name)
    expected_end = expected_start + len(expected_name)
    client = TestClient(server.app, base_url="http://localhost")

    detected = client.post("/api/detect", json={"text": text})
    assert detected.status_code == 200
    detected_entities = detected.json()["entities"]
    assert {
        (entity["start"], entity["end"], entity["data_type"]) for entity in detected_entities
    } >= {(expected_start, expected_end, "NAME")}
    assert not any(
        entity["data_type"] == "LOCATION"
        and expected_start <= entity["start"]
        and entity["end"] <= expected_end
        for entity in detected_entities
    )

    sanitized = client.post("/api/sanitize", json={"text": text, "mode": "token"})
    assert sanitized.status_code == 200
    body = sanitized.json()
    assert {
        (entity["start"], entity["end"], entity["data_type"]) for entity in body["entities"]
    } >= {(expected_start, expected_end, "NAME")}
    assert expected_name not in body["sanitized_text"]

    try:
        restored = client.post(
            "/api/reidentify",
            json={"session_id": body["session_id"], "text": body["sanitized_text"]},
        )
        assert restored.status_code == 200
        restore_body = restored.json()
        assert restore_body["restored_text"] == expected_clean
        assert restore_body["leftover_tokens"] == []
    finally:
        server.SERVICE.drop(body["session_id"])

    service = SessionService()
    outcome = service.sanitize(expected_clean, mode="token")
    assert any(
        entity["start"] == expected_start
        and entity["end"] == expected_end
        and entity["data_type"] == "NAME"
        for entity in outcome.entities
    )
    restored = service.restore(outcome.session_id, outcome.sanitized_text)
    assert restored.restored_text == expected_clean
    assert restored.leftover_tokens == []


def test_multiline_name_cue_rejects_cross_line_candidate_and_keeps_full_name(monkeypatch):
    """The shared finalizer drops junk before a cue and keeps the cue value."""
    _use_default_crf(monkeypatch)
    text = "คำเกริ่นหน่อย\nคุณแม่ชื่อ กานดา แสงทอง อายุ 62 ปี"
    candidate_start = text.index("หน่อย")
    candidate_end = text.index("อายุ")

    assert tbd._name_hygiene(text, candidate_start, candidate_end) == []
    assert tbd._finalize_tb_candidate(text, candidate_start, candidate_end, "PERSON") == []

    entities = detect_tb(text)
    expected_start = text.index("กานดา แสงทอง")
    expected_end = expected_start + len("กานดา แสงทอง")
    assert any(
        entity.data_type == "NAME" and entity.span == (expected_start, expected_end)
        for entity in entities
    )


@pytest.mark.parametrize(
    ("text", "expected_name", "expected_location"),
    [
        (
            "ผู้ป่วยชื่อ กิตติ เมืองไทย อาศัยอยู่จังหวัดเชียงใหม่",
            "กิตติ เมืองไทย",
            "เชียงใหม่",
        ),
        (
            "ผู้ป่วยชื่อ สมชาย ทดสอบ อาศัยอยู่จังหวัดเชียงใหม่",
            "สมชาย ทดสอบ",
            "เชียงใหม่",
        ),
    ],
)
def test_name_like_location_text_does_not_split_name_and_real_location_survives(
    monkeypatch, text, expected_name, expected_location
):
    """A location-looking surname is not a reason to carve out a subspan."""
    _use_default_crf(monkeypatch)
    entities = detect_all(text)
    name_start = text.index(expected_name)
    name_end = name_start + len(expected_name)

    assert any(
        entity.data_type == "NAME" and entity.span == (name_start, name_end) for entity in entities
    )
    assert not any(
        entity.data_type == "LOCATION"
        and name_start <= entity.span[0]
        and entity.span[1] <= name_end
        for entity in entities
    )
    assert any(
        entity.data_type == "ADDRESS" and entity.original_text == expected_location
        for entity in entities
    )


def test_name_offsets_preserve_thai_combining_marks(monkeypatch):
    _use_default_crf(monkeypatch)
    text = "ผู้ป่วยชื่อ กิตติ เกื้อกูล อายุ 41 ปี"
    expected_name = "กิตติ เกื้อกูล"
    assert any(unicodedata.combining(char) for char in expected_name)

    entities = detect_all(text)
    start = text.index(expected_name)
    end = start + len(expected_name)
    names = [entity for entity in entities if entity.data_type == "NAME"]

    assert any(entity.span == (start, end) for entity in names)
    for entity in names:
        assert text[entity.span[0] : entity.span[1]] == entity.original_text
