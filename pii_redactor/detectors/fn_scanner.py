"""False-negative (FN) second pass scanner using lightweight regex patterns."""
from __future__ import annotations

import re
import uuid

from pii_redactor.models import Entity

# ---------------------------------------------------------------------------
# Patterns for common false-negative scenarios
# ---------------------------------------------------------------------------

_FN_PATTERNS: list[tuple[re.Pattern[str], str, str, float]] = [
    # 13-digit sequences not caught (checksum failed but highly suspicious).
    # THAI_ID/EMAIL/DATE_OF_BIRTH are all format-preserving types -- redact_type
    # must be "FP" (matching fp_detector's own classification of these same
    # data_types) so anonymizer.py routes them through generate_fp() for a
    # realistic fake value instead of tb_generator's literal "[REDACTED_x]"
    # fallback.
    (re.compile(r"\b(\d{13})\b"), "THAI_ID", "FP", 0.6),
    # Email-like patterns with @ (simpler than full RFC pattern)
    (re.compile(r"([^\s@]+@[^\s@]+\.[^\s@]{2,})"), "EMAIL", "FP", 0.7),
    # Date-like patterns in various formats
    (re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"), "DATE_OF_BIRTH", "FP", 0.6),
]


def scan_fn(text: str, existing_entities: list[Entity]) -> list[Entity]:
    """
    False-negative second pass: lightweight regex scan for PII patterns
    not already caught by fp_detector or tb_detector.

    Returns NEW entities only (no duplicates of existing_entities spans).
    """
    existing_spans = {(e.span[0], e.span[1]) for e in existing_entities}

    new_entities: list[Entity] = []
    for pattern, data_type, redact_type, score in _FN_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.start(1), m.end(1)
            if end - start < 2:
                continue
            # Skip if this span overlaps with any existing entity
            overlaps = any(
                not (end <= es[0] or start >= es[1])
                for es in existing_spans
            )
            if not overlaps:
                new_entities.append(Entity(
                    entity_id=str(uuid.uuid4()),
                    redact_type=redact_type,
                    data_type=data_type,
                    span=(start, end),
                    score=score,
                    original_text=text[start:end],
                ))
                existing_spans.add((start, end))

    return sorted(new_entities, key=lambda e: e.span[0])
