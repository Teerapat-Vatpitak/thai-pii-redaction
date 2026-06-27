"""Semantic Section-26 detector (MiniLM). Skipped without sentence-transformers."""
import pytest

pytest.importorskip("sentence_transformers")

from pii_redactor.sensitive_detector import detect_sensitive


def test_semantic_flags_health_without_keyword():
    """'ป่วยเป็นเบาหวาน' has no Section-26 keyword but is a health disclosure."""
    hits = detect_sensitive("วันนี้ฉันป่วยเป็นเบาหวานมาหลายปีแล้ว")
    assert "HEALTH" in {h["category"] for h in hits}


def test_semantic_ignores_benign_sentence():
    hits = detect_sensitive("วันนี้อากาศดีมากเหมาะกับการออกไปเดินเล่น")
    assert hits == []
