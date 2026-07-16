"""Data models for the PII redaction pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WordBbox:
    """A single word's text and bounding box from PDF extraction."""

    text: str
    page: int
    x: float
    y: float
    width: float
    height: float


@dataclass
class NormalizedDocumentModel:
    """Output of Step 1 (Ingest). Passed into Step 2 (Detection)."""

    text: str  # cleaned full text (all pages joined)
    words: list[WordBbox]  # per-word bboxes (for PDF redaction in Step 8)
    language: str  # "th" | "en"
    source_type: str  # "text" | "pdf_text" | "pdf_hybrid"
    metadata: dict = field(default_factory=dict)  # ocr_confidence, quality_score, warnings, human_review flag, etc.


@dataclass
class Entity:
    """A single detected PII entity. Output of Step 2 (Detection)."""

    entity_id: str  # UUID4 string
    redact_type: str  # "FP" (format-preserving) | "TB" (text-based)
    data_type: str  # "THAI_ID" | "PHONE" | "EMAIL" | "NAME" | "SURNAME" |
    # "ADDRESS" | "BANK_ACCOUNT" | "CREDIT_CARD" |
    # "DATE_OF_BIRTH" | "VEHICLE_PLATE" | "PASSPORT" |
    # "STUDENT_ID" | "IBAN" | "ETHNICITY" |
    # "POLITICAL_OPINION" | "RELIGION" | "CRIMINAL" |
    # "HEALTH" | "DISABILITY" | "UNION" |
    # "LOCATION" | "DATE" | "ORGANIZATION" | "ID_NUMBER"
    # (honest fallbacks: LOCATION/DATE/ID_NUMBER upgrade to
    # ADDRESS/DATE_OF_BIRTH/STUDENT_ID/PASSPORT only when a nearby cue
    # confirms it; ORGANIZATION has no such upgrade)
    span: tuple[int, int]  # (start, end) char offsets in NormalizedDocumentModel.text
    score: float  # 1.0 for FP (regex+checksum), NER confidence for TB
    original_text: str  # the actual PII text at this span


@dataclass
class EntityRegistry:
    """All detected entities from Step 2. Passed into Step 3 (Pseudonymization)."""

    entities: list[Entity]
    fp_count: int  # count of FP entities
    tb_count: int  # count of TB entities


@dataclass
class PseudonymizedDocument:
    """Output of Step 3. Passed into Step 5 (Send to AI)."""

    text: str  # text with real PII replaced by pseudonyms
    entity_registry: EntityRegistry  # original registry (spans still reference original text)
    session_id: str  # links to the SessionVault


@dataclass
class VaultRecord:
    """One entry in the SessionVault's in-memory mapping table."""

    entity_id: str
    original: str  # the real PII value (NEVER leaves device)
    pseudonym: str  # the fake value sent to AI
    type: str  # "FP" | "TB"
    data_type: str  # same as Entity.data_type
    span: tuple[int, int]  # same as Entity.span
    timestamp: float  # time.monotonic() when created


@dataclass
class AIResponse:
    """Output of Step 5. Contains pseudonymized AI response."""

    text: str  # AI's response (still contains pseudonyms)
    request_id: str  # UUID for audit trail
    latency: float  # seconds


@dataclass
class ReverseResult:
    """Output of Step 6 (Reverse Mapping). Real data restored."""

    text: str  # response with real data restored
    flags: list[str] = field(default_factory=list)  # warnings: "pseudonym_residue", "incomplete_reverse", etc.
    audit_summary: dict = field(default_factory=dict)  # counts, timestamps for audit log
