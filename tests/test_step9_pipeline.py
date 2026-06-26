"""Integration tests for the end-to-end pipeline (Step 9)."""
import uuid

import pytest

from pii_redactor.ai_client import FakeLLMProvider
from pii_redactor.output_validator import ValidationResult
from pii_redactor.pipeline import PipelineResult, run_pipeline


def test_pipeline_returns_pipeline_result():
    result = run_pipeline(text="This is a simple test.", provider=FakeLLMProvider())
    assert isinstance(result, PipelineResult)
    assert isinstance(result.session_id, str)


def test_pipeline_no_pii_text():
    result = run_pipeline(text="The weather is nice today.", provider=FakeLLMProvider())
    assert result.entity_registry.fp_count == 0
    # Output should equal input (no PII to pseudonymize)
    assert result.reverse_result.text == "The weather is nice today."


def test_pipeline_with_email_roundtrip():
    text = "Contact me at real.user@example.com for info."
    result = run_pipeline(text=text, provider=FakeLLMProvider())
    # FakeLLM echoes pseudonymized text. After reverse, original email should be back.
    assert "real.user@example.com" in result.reverse_result.text


def test_pipeline_pseudonymized_text_has_no_real_email():
    text = "Contact me at real.user@example.com for info."
    result = run_pipeline(text=text, provider=FakeLLMProvider())
    # Pseudonymized text must NOT contain the original email
    assert "real.user@example.com" not in result.pseudonymized_text


def test_pipeline_session_id_is_uuid():
    result = run_pipeline(text="Hello.", provider=FakeLLMProvider())
    parsed = uuid.UUID(result.session_id)
    assert str(parsed) == result.session_id


def test_pipeline_export_creates_file(tmp_path):
    out = str(tmp_path / "output.txt")
    result = run_pipeline(
        text="Hello world.",
        provider=FakeLLMProvider(),
        output_path=out,
    )
    assert result.export_result is not None
    assert result.export_result.output_path.exists()


def test_pipeline_no_export_when_output_path_none():
    result = run_pipeline(text="Hello.", provider=FakeLLMProvider())
    assert result.export_result is None


def test_pipeline_raises_when_no_input():
    with pytest.raises(ValueError, match="Provide either"):
        run_pipeline()


def test_pipeline_raises_when_both_inputs():
    with pytest.raises(ValueError, match="not both"):
        run_pipeline(text="hello", input_path="some/path.txt")


def test_pipeline_validation_result_is_validation_result():
    result = run_pipeline(text="No PII here.", provider=FakeLLMProvider())
    assert isinstance(result.validation_result, ValidationResult)


def test_pipeline_with_thai_phone():
    text = "โทรหาฉันที่ 081-234-5678"
    result = run_pipeline(text=text, provider=FakeLLMProvider())
    # After round-trip: phone should be restored
    assert "081-234-5678" in result.reverse_result.text
    # In pseudonymized text, original phone should be replaced
    assert "081-234-5678" not in result.pseudonymized_text
