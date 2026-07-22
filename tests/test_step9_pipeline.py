"""Integration tests for the end-to-end pipeline (Step 9)."""

import uuid
from pathlib import Path

import pytest

from pii_redactor.ai_client import FakeLLMProvider
from pii_redactor.output_validator import ValidationResult
from pii_redactor.pipeline import PipelineResult, run_pipeline

EXAMPLE_PROMPTS = sorted(
    (Path(__file__).resolve().parents[1] / "examples" / "prompts").glob("*.txt")
)


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


# run_pipeline() mints a random salt when none is passed, and the salt decides
# every surrogate value — so this test used to sample ONE random point of the
# input space per run and went red on CI only when it happened to draw a bad
# one. Fixed salts make it deterministic AND broaden it: each prompt is now
# exercised against several surrogate sets, every one of them reproducible from
# the test id alone.
ROUNDTRIP_SALTS = ["a1b2c3d4", "deadbeef", "0f0f0f0f", "5a5a5a5a", "cafebabe"]


@pytest.mark.parametrize("salt", ROUNDTRIP_SALTS)
@pytest.mark.parametrize("prompt_path", EXAMPLE_PROMPTS, ids=[p.stem for p in EXAMPLE_PROMPTS])
def test_pipeline_example_prompts_roundtrip(prompt_path, salt):
    """The shipped example prompts must survive the full pipeline.

    Regression 1: the pre-send guard used exact-match pseudonym exclusion, but
    NER emits fuzzy spans around embedded pseudonyms (title/context words get
    swallowed into the span), so every Thai prompt with a title-cued name
    halted with PreSendValidationError.

    Regression 2 (salt-dependent, hence the sweep): `เลขที่บัญชี` was upgraded
    to ADDRESS by the `เลขที่` cue, so an account-number LABEL was replaced by
    a fake street address. Next to the other surrogates that made the NER draw
    one wide ADDRESS span across three pseudonyms, and the guard halted a clean
    prompt.
    """
    result = run_pipeline(input_path=str(prompt_path), provider=FakeLLMProvider(), salt=salt)
    assert isinstance(result, PipelineResult)
    assert result.reverse_result.text  # round-trip completed


def test_pipeline_resolves_overlapping_fp_tb_spans(monkeypatch):
    """FP and TB detectors can emit overlapping spans (e.g. a date matched by
    both the regex and NER). Concatenating them unresolved corrupts the text
    during tail-first replacement — the registry must be overlap-free, with
    the checksum-backed FP span winning (same rule as aggregate.dedupe_spans).
    """
    import pii_redactor.detectors.fp_detector as fp_mod
    import pii_redactor.detectors.tb_detector as tb_mod
    from pii_redactor.models import Entity

    text = "ติดต่อ 081-234-5678 ได้เลยครับ"
    phone_start = text.index("081")
    phone_end = phone_start + len("081-234-5678")

    def fake_fp(t):
        return [
            Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="FP",
                data_type="PHONE",
                span=(phone_start, phone_end),
                score=1.0,
                original_text=t[phone_start:phone_end],
            )
        ]

    def fake_tb(t):
        # sloppy NER span starting before and ending inside the phone
        return [
            Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="TB",
                data_type="NAME",
                span=(0, phone_start + 3),
                score=0.85,
                original_text=t[0 : phone_start + 3],
            )
        ]

    monkeypatch.setattr(fp_mod, "detect_fp", fake_fp)
    monkeypatch.setattr(tb_mod, "detect_tb", fake_tb)

    result = run_pipeline(text=text, provider=FakeLLMProvider())

    spans = sorted(e.span for e in result.entity_registry.entities)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2, f"overlapping spans in registry: {spans}"
    # FP wins the overlap; the phone must be gone from the pseudonymized text
    assert "081-234-5678" not in result.pseudonymized_text
    # round-trip restores the original
    assert "081-234-5678" in result.reverse_result.text


def test_pipeline_with_thai_phone():
    text = "โทรหาฉันที่ 081-234-5678"
    result = run_pipeline(text=text, provider=FakeLLMProvider())
    # After round-trip: phone should be restored
    assert "081-234-5678" in result.reverse_result.text
    # In pseudonymized text, original phone should be replaced
    assert "081-234-5678" not in result.pseudonymized_text
