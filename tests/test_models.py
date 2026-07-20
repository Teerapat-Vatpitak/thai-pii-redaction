"""Tests for PII redaction data models."""
import time
from dataclasses import fields
from uuid import uuid4

from pii_redactor.models import (
    AIResponse,
    Entity,
    EntityRegistry,
    NormalizedDocumentModel,
    PseudonymizedDocument,
    ReverseResult,
    VaultRecord,
    WordBbox,
)


class TestWordBbox:
    """Tests for WordBbox dataclass."""

    def test_word_bbox_instantiation(self):
        """Test that WordBbox can be instantiated with expected fields."""
        wb = WordBbox(text="สวัสดี", page=0, x=10.0, y=20.0, width=50.0, height=12.0)
        assert wb.text == "สวัสดี"
        assert wb.page == 0
        assert wb.x == 10.0
        assert wb.y == 20.0
        assert wb.width == 50.0
        assert wb.height == 12.0

    def test_word_bbox_fields_exist(self):
        """Test that all expected fields exist in WordBbox."""
        field_names = {f.name for f in fields(WordBbox)}
        expected_fields = {"text", "page", "x", "y", "width", "height"}
        assert field_names == expected_fields

    def test_word_bbox_english_text(self):
        """Test WordBbox with English text."""
        wb = WordBbox(text="hello", page=1, x=5.5, y=15.5, width=30.0, height=10.0)
        assert wb.text == "hello"
        assert wb.page == 1


class TestNormalizedDocumentModel:
    """Tests for NormalizedDocumentModel dataclass."""

    def test_normalized_document_instantiation(self):
        """Test that NormalizedDocumentModel can be instantiated."""
        words = [
            WordBbox(text="test", page=0, x=0.0, y=0.0, width=20.0, height=10.0),
        ]
        ndm = NormalizedDocumentModel(
            text="test document",
            words=words,
            language="th",
            source_type="pdf_text",
            metadata={"quality_score": 0.95},
        )
        assert ndm.text == "test document"
        assert len(ndm.words) == 1
        assert ndm.language == "th"
        assert ndm.source_type == "pdf_text"
        assert ndm.metadata["quality_score"] == 0.95

    def test_normalized_document_metadata_default(self):
        """Test that metadata defaults to empty dict."""
        ndm = NormalizedDocumentModel(
            text="test",
            words=[],
            language="en",
            source_type="text",
        )
        assert ndm.metadata == {}
        assert isinstance(ndm.metadata, dict)

    def test_normalized_document_fields_exist(self):
        """Test that all expected fields exist."""
        field_names = {f.name for f in fields(NormalizedDocumentModel)}
        expected_fields = {"text", "words", "language", "source_type", "metadata"}
        assert field_names == expected_fields

    def test_normalized_document_multiple_languages(self):
        """Test with different language codes."""
        for lang in ["th", "en"]:
            ndm = NormalizedDocumentModel(
                text="test",
                words=[],
                language=lang,
                source_type="text",
            )
            assert ndm.language == lang


class TestEntity:
    """Tests for Entity dataclass."""

    def test_entity_instantiation(self):
        """Test that Entity can be instantiated with expected fields."""
        entity_id = str(uuid4())
        e = Entity(
            entity_id=entity_id,
            redact_type="FP",
            data_type="THAI_ID",
            span=(0, 13),
            score=1.0,
            original_text="1101200012345",
        )
        assert e.entity_id == entity_id
        assert e.redact_type == "FP"
        assert e.data_type == "THAI_ID"
        assert e.span == (0, 13)
        assert e.score == 1.0
        assert e.original_text == "1101200012345"

    def test_entity_span_is_tuple(self):
        """Test that Entity span is a tuple of two ints."""
        e = Entity(
            entity_id=str(uuid4()),
            redact_type="FP",
            data_type="THAI_ID",
            span=(0, 13),
            score=1.0,
            original_text="1101200012345",
        )
        assert isinstance(e.span, tuple)
        assert len(e.span) == 2
        assert isinstance(e.span[0], int)
        assert isinstance(e.span[1], int)

    def test_entity_redact_types(self):
        """Test Entity with different redact types."""
        for redact_type in ["FP", "TB"]:
            e = Entity(
                entity_id=str(uuid4()),
                redact_type=redact_type,
                data_type="PHONE",
                span=(0, 10),
                score=0.95,
                original_text="0812345678",
            )
            assert e.redact_type == redact_type

    def test_entity_data_types(self):
        """Test Entity with various data types."""
        data_types = [
            "THAI_ID",
            "PHONE",
            "EMAIL",
            "NAME",
            "SURNAME",
            "ADDRESS",
            "BANK_ACCOUNT",
            "CREDIT_CARD",
            "DATE_OF_BIRTH",
            "VEHICLE_PLATE",
            "PASSPORT",
        ]
        for data_type in data_types:
            e = Entity(
                entity_id=str(uuid4()),
                redact_type="TB",
                data_type=data_type,
                span=(0, 5),
                score=0.9,
                original_text="test",
            )
            assert e.data_type == data_type

    def test_entity_fields_exist(self):
        """Test that all expected fields exist."""
        field_names = {f.name for f in fields(Entity)}
        expected_fields = {"entity_id", "redact_type", "data_type", "span", "score", "original_text"}
        assert field_names == expected_fields


class TestEntityRegistry:
    """Tests for EntityRegistry dataclass."""

    def test_entity_registry_instantiation(self):
        """Test that EntityRegistry can be instantiated."""
        entities = [
            Entity(
                entity_id=str(uuid4()),
                redact_type="FP",
                data_type="THAI_ID",
                span=(0, 13),
                score=1.0,
                original_text="1101200012345",
            ),
        ]
        registry = EntityRegistry(entities=entities, fp_count=1, tb_count=0)
        assert len(registry.entities) == 1
        assert registry.fp_count == 1
        assert registry.tb_count == 0

    def test_entity_registry_counts(self):
        """Test that fp_count and tb_count can be set correctly."""
        fp_entity = Entity(
            entity_id=str(uuid4()),
            redact_type="FP",
            data_type="THAI_ID",
            span=(0, 13),
            score=1.0,
            original_text="1101200012345",
        )
        tb_entity = Entity(
            entity_id=str(uuid4()),
            redact_type="TB",
            data_type="NAME",
            span=(15, 20),
            score=0.92,
            original_text="John",
        )
        registry = EntityRegistry(entities=[fp_entity, tb_entity], fp_count=1, tb_count=1)
        assert registry.fp_count + registry.tb_count == len(registry.entities)

    def test_entity_registry_empty(self):
        """Test EntityRegistry with no entities."""
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        assert len(registry.entities) == 0
        assert registry.fp_count == 0
        assert registry.tb_count == 0

    def test_entity_registry_fields_exist(self):
        """Test that all expected fields exist."""
        field_names = {f.name for f in fields(EntityRegistry)}
        expected_fields = {"entities", "fp_count", "tb_count"}
        assert field_names == expected_fields


class TestPseudonymizedDocument:
    """Tests for PseudonymizedDocument dataclass."""

    def test_pseudonymized_document_instantiation(self):
        """Test that PseudonymizedDocument can be instantiated."""
        entity_registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        session_id = str(uuid4())
        pdoc = PseudonymizedDocument(
            text="This is a [REDACT_0] test.",
            entity_registry=entity_registry,
            session_id=session_id,
        )
        assert pdoc.text == "This is a [REDACT_0] test."
        assert pdoc.entity_registry == entity_registry
        assert pdoc.session_id == session_id

    def test_pseudonymized_document_with_entities(self):
        """Test PseudonymizedDocument containing actual entities."""
        entities = [
            Entity(
                entity_id=str(uuid4()),
                redact_type="FP",
                data_type="THAI_ID",
                span=(0, 13),
                score=1.0,
                original_text="1101200012345",
            ),
        ]
        entity_registry = EntityRegistry(entities=entities, fp_count=1, tb_count=0)
        pdoc = PseudonymizedDocument(
            text="[REDACT_0] owns a car.",
            entity_registry=entity_registry,
            session_id=str(uuid4()),
        )
        assert len(pdoc.entity_registry.entities) == 1
        assert pdoc.entity_registry.fp_count == 1

    def test_pseudonymized_document_fields_exist(self):
        """Test that all expected fields exist."""
        field_names = {f.name for f in fields(PseudonymizedDocument)}
        expected_fields = {"text", "entity_registry", "session_id"}
        assert field_names == expected_fields


class TestVaultRecord:
    """Tests for VaultRecord dataclass."""

    def test_vault_record_instantiation(self):
        """Test that VaultRecord can be instantiated with all required fields."""
        entity_id = str(uuid4())
        timestamp = time.monotonic()
        vr = VaultRecord(
            entity_id=entity_id,
            original="1101200012345",
            pseudonym="[REDACT_0]",
            type="FP",
            data_type="THAI_ID",
            span=(0, 13),
            timestamp=timestamp,
        )
        assert vr.entity_id == entity_id
        assert vr.original == "1101200012345"
        assert vr.pseudonym == "[REDACT_0]"
        assert vr.type == "FP"
        assert vr.data_type == "THAI_ID"
        assert vr.span == (0, 13)
        assert vr.timestamp == timestamp

    def test_vault_record_all_fields_required(self):
        """Test that all VaultRecord fields are defined."""
        field_names = {f.name for f in fields(VaultRecord)}
        expected_fields = {"entity_id", "original", "pseudonym", "type", "data_type", "span", "timestamp"}
        assert field_names == expected_fields

    def test_vault_record_span_is_tuple(self):
        """Test that VaultRecord span is a tuple."""
        vr = VaultRecord(
            entity_id=str(uuid4()),
            original="test_value",
            pseudonym="[REDACT_0]",
            type="TB",
            data_type="NAME",
            span=(10, 20),
            timestamp=time.monotonic(),
        )
        assert isinstance(vr.span, tuple)
        assert len(vr.span) == 2

    def test_vault_record_different_types(self):
        """Test VaultRecord with different type values."""
        for rec_type in ["FP", "TB"]:
            vr = VaultRecord(
                entity_id=str(uuid4()),
                original="value",
                pseudonym="[REDACT_0]",
                type=rec_type,
                data_type="EMAIL",
                span=(0, 5),
                timestamp=time.monotonic(),
            )
            assert vr.type == rec_type


class TestAIResponse:
    """Tests for AIResponse dataclass."""

    def test_ai_response_instantiation(self):
        """Test that AIResponse can be instantiated."""
        request_id = str(uuid4())
        ai_resp = AIResponse(
            text="This is the AI response with [REDACT_0].",
            request_id=request_id,
            latency=1.234,
        )
        assert ai_resp.text == "This is the AI response with [REDACT_0]."
        assert ai_resp.request_id == request_id
        assert ai_resp.latency == 1.234

    def test_ai_response_fields_exist(self):
        """Test that all expected fields exist."""
        field_names = {f.name for f in fields(AIResponse)}
        expected_fields = {"text", "request_id", "latency"}
        assert field_names == expected_fields

    def test_ai_response_latency_types(self):
        """Test AIResponse with different latency values."""
        for latency in [0.1, 1.0, 5.5, 100.999]:
            ai_resp = AIResponse(
                text="response",
                request_id=str(uuid4()),
                latency=latency,
            )
            assert ai_resp.latency == latency
            assert isinstance(ai_resp.latency, float)


class TestReverseResult:
    """Tests for ReverseResult dataclass."""

    def test_reverse_result_instantiation(self):
        """Test that ReverseResult can be instantiated."""
        rr = ReverseResult(
            text="This is the final response with real data restored.",
            flags=["pseudonym_residue"],
            audit_summary={"count": 1, "duration": 0.5},
        )
        assert rr.text == "This is the final response with real data restored."
        assert rr.flags == ["pseudonym_residue"]
        assert rr.audit_summary["count"] == 1

    def test_reverse_result_flags_default(self):
        """Test that flags defaults to empty list."""
        rr = ReverseResult(text="response")
        assert rr.flags == []
        assert isinstance(rr.flags, list)

    def test_reverse_result_audit_summary_default(self):
        """Test that audit_summary defaults to empty dict."""
        rr = ReverseResult(text="response")
        assert rr.audit_summary == {}
        assert isinstance(rr.audit_summary, dict)

    def test_reverse_result_multiple_flags(self):
        """Test ReverseResult with multiple warning flags."""
        flags = ["pseudonym_residue", "incomplete_reverse", "mismatch_detected"]
        rr = ReverseResult(
            text="response",
            flags=flags,
            audit_summary={"warnings": len(flags)},
        )
        assert len(rr.flags) == 3
        assert "incomplete_reverse" in rr.flags

    def test_reverse_result_fields_exist(self):
        """Test that all expected fields exist."""
        field_names = {f.name for f in fields(ReverseResult)}
        expected_fields = {"text", "flags", "audit_summary"}
        assert field_names == expected_fields


class TestDataclassIntegration:
    """Integration tests across multiple dataclasses."""

    def test_full_pipeline_model_flow(self):
        """Test a complete flow through the data models."""
        # Step 1: NormalizedDocumentModel
        words = [
            WordBbox(text="สวัสดี", page=0, x=0.0, y=0.0, width=40.0, height=12.0),
            WordBbox(text="1101200012345", page=0, x=50.0, y=0.0, width=80.0, height=12.0),
        ]
        ndm = NormalizedDocumentModel(
            text="สวัสดี 1101200012345",
            words=words,
            language="th",
            source_type="pdf_text",
            metadata={"quality_score": 0.95},
        )
        assert len(ndm.words) == 2

        # Step 2: Entity detection
        entities = [
            Entity(
                entity_id=str(uuid4()),
                redact_type="FP",
                data_type="THAI_ID",
                span=(8, 21),
                score=1.0,
                original_text="1101200012345",
            ),
        ]
        entity_registry = EntityRegistry(entities=entities, fp_count=1, tb_count=0)

        # Step 3: Pseudonymization
        pseudonymized = PseudonymizedDocument(
            text="สวัสดี [REDACT_0]",
            entity_registry=entity_registry,
            session_id=str(uuid4()),
        )
        assert "[REDACT_0]" in pseudonymized.text

        # Vault records
        vault_record = VaultRecord(
            entity_id=entities[0].entity_id,
            original="1101200012345",
            pseudonym="[REDACT_0]",
            type="FP",
            data_type="THAI_ID",
            span=(8, 21),
            timestamp=time.monotonic(),
        )
        assert vault_record.original == "1101200012345"

        # Step 5: AI response
        ai_response = AIResponse(
            text="สวัสดี [REDACT_0] is a valid ID.",
            request_id=str(uuid4()),
            latency=0.5,
        )

        # Step 6: Reverse mapping
        reverse_result = ReverseResult(
            text="สวัสดี 1101200012345 is a valid ID.",
            flags=[],
            audit_summary={"restored_count": 1},
        )
        assert "1101200012345" in reverse_result.text
