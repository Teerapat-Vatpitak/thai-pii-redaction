"""End-to-end pipeline orchestrator (Steps 1-8)."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from pii_redactor.models import EntityRegistry, PseudonymizedDocument, AIResponse, ReverseResult
from pii_redactor.output_validator import ValidationResult
from pii_redactor.exporter import ExportResult
from pii_redactor.session_vault import SessionVault
from pii_redactor.ai_client import AIProvider, FakeLLMProvider


@dataclass
class PipelineResult:
    """Full end-to-end result, all intermediate outputs preserved."""

    input_path: str | None
    raw_text: str
    clean_text: str
    entity_registry: EntityRegistry
    pseudonymized_text: str
    ai_response: AIResponse
    reverse_result: ReverseResult
    validation_result: ValidationResult
    export_result: ExportResult | None  # None if export_path not provided
    vault: SessionVault
    session_id: str


def run_pipeline(
    input_path: str | None = None,
    *,
    text: str | None = None,
    output_path: str | None = None,
    fmt: str = "txt",
    provider: AIProvider | None = None,
    salt: str | None = None,
    system_prompt: str | None = None,
    overwrite: bool = False,
) -> PipelineResult:
    """
    Run the 8-step PII redaction pipeline.

    Args:
        input_path: Path to input file (.txt or .pdf). Mutually exclusive with text.
        text: Direct text input. Mutually exclusive with input_path.
        output_path: Where to write final output. If None, skip export.
        fmt: Output format ("txt" | "pdf_text"). Default "txt".
        provider: AI provider. Default: FakeLLMProvider() if not given.
        salt: HMAC salt for FP pseudonym generation. Auto-generated if not given.
        system_prompt: Override default AI system prompt.
        overwrite: Whether to overwrite existing output_path.

    Returns:
        PipelineResult with all intermediate outputs.

    Raises:
        ValueError: if neither input_path nor text provided, or both provided
        FileNotFoundError: if input_path does not exist
        PIILeakError: if PII detected in pseudonymized or final output
        ExportError: if export fails
        VaultTimeoutError: if vault times out during processing
    """
    # Validate inputs
    if input_path is None and text is None:
        raise ValueError("Provide either input_path or text")
    if input_path is not None and text is not None:
        raise ValueError("Provide either input_path or text, not both")
    if input_path is not None and not Path(input_path).exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Defaults
    if provider is None:
        provider = FakeLLMProvider()
    if salt is None:
        salt = secrets.token_hex(16)

    vault = SessionVault()

    # --- Step 1: Ingest ---
    if input_path is not None:
        from pii_redactor.ingest.file_detector import detect_source_type
        from pii_redactor.ingest.text_extractor import extract
        source_type = detect_source_type(input_path)
        raw_text, _bboxes = extract(input_path, source_type)
    else:
        raw_text = text
        source_type = "text"

    from pii_redactor.ingest.text_cleaner import clean
    clean_result = clean(raw_text)
    clean_text = clean_result.text

    # Quality check is informational; do not halt on low score
    from pii_redactor.ingest.quality_validator import validate as validate_quality
    validate_quality(clean_text, source_type)

    # --- Step 2: Detection ---
    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.detectors.tb_detector import detect_tb
    from pii_redactor.detectors.fn_scanner import scan_fn

    fp_entities = detect_fp(clean_text)
    tb_entities = detect_tb(clean_text)

    all_so_far = fp_entities + tb_entities
    fn_entities = scan_fn(clean_text, all_so_far)

    all_entities = fp_entities + tb_entities + fn_entities
    entity_registry = EntityRegistry(
        entities=all_entities,
        fp_count=len(fp_entities),
        tb_count=len(tb_entities) + len(fn_entities),
    )

    # --- Step 3+4: Pseudonymization ---
    from pii_redactor.anonymizer.anonymizer import anonymize
    pseudo_doc = anonymize(clean_text, entity_registry, vault, salt=salt)
    pseudonymized_text = pseudo_doc.text

    # --- Step 5: Send to AI ---
    from pii_redactor.ai_client import send_to_ai
    ai_response = send_to_ai(
        pseudonymized_text,
        entity_registry,
        vault,
        provider,
        system_prompt=system_prompt,
    )

    # --- Step 6: Reverse mapping ---
    from pii_redactor.reverse_mapper import reverse_map
    reverse_result = reverse_map(ai_response, entity_registry, vault)

    # --- Step 7: Output validation ---
    from pii_redactor.output_validator import validate_output
    validation_result = validate_output(reverse_result, entity_registry, vault)

    # --- Step 8: Export (optional) ---
    export_result = None
    if output_path is not None:
        from pii_redactor.exporter import export
        export_result = export(
            reverse_result,
            validation_result,
            output_path,
            fmt=fmt,
            overwrite=overwrite,
        )

    return PipelineResult(
        input_path=input_path,
        raw_text=raw_text,
        clean_text=clean_text,
        entity_registry=entity_registry,
        pseudonymized_text=pseudonymized_text,
        ai_response=ai_response,
        reverse_result=reverse_result,
        validation_result=validation_result,
        export_result=export_result,
        vault=vault,
        session_id=vault.session_id,
    )
