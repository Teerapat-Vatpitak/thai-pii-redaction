"""Pseudonymization orchestrator.

Algorithm:
1. Sort entities by span[0] DESCENDING (tail-first) to preserve offsets during replacement.
2. For each entity: vault cache hit -> reuse pseudonym; miss -> generate -> write to vault.
3. Replace span in text (tail-first preserves earlier spans).
4. Consistency scan: replace remaining verbatim occurrences of each original.
5. Post-replace PII leak check via detect_fp -> raise PIILeakError if any found.
6. Return PseudonymizedDocument.
"""
from __future__ import annotations

import time

from pii_redactor.models import Entity, EntityRegistry, PseudonymizedDocument, VaultRecord
from pii_redactor.session_vault import SessionVault
from pii_redactor.anonymizer.fp_generator import generate_fp
from pii_redactor.anonymizer.tb_generator import generate_tb
from pii_redactor.detectors.fp_detector import detect_fp


class PIILeakError(Exception):
    """Raised when PII is detected in pseudonymized output."""


def _get_context_with_blank(text: str, entity: Entity) -> str:
    """Extract context around entity with PII replaced by ___."""
    start, end = entity.span
    ctx_start = max(0, start - 100)
    ctx_end = min(len(text), end + 100)
    context = text[ctx_start:ctx_end]
    local_start = start - ctx_start
    local_end = end - ctx_start
    return context[:local_start] + "___" + context[local_end:]


def _generate_pseudonym(entity: Entity, text: str, salt: str) -> str:
    """Generate appropriate pseudonym based on entity redact_type."""
    if entity.redact_type == "FP":
        return generate_fp(entity.data_type, entity.original_text, salt=salt)
    else:
        context = _get_context_with_blank(text, entity)
        return generate_tb(
            entity.data_type,
            context,
            salt=salt,
            original=entity.original_text,
        )


def anonymize(
    text: str,
    entity_registry: EntityRegistry,
    vault: SessionVault,
    *,
    salt: str,
) -> PseudonymizedDocument:
    """Replace all detected PII entities with pseudonyms.

    Args:
        text: original document text
        entity_registry: detected entities from Step 2
        vault: in-memory session vault for storing original<->pseudonym mappings
        salt: per-process random salt (never stored)

    Returns:
        PseudonymizedDocument with real PII replaced by pseudonyms

    Raises:
        PIILeakError: if detect_fp finds any structured PII in the pseudonymized output
    """
    pseudonymized = text

    # Step 1: sort entities by span start DESCENDING (tail-first)
    sorted_entities = sorted(
        entity_registry.entities,
        key=lambda e: e.span[0],
        reverse=True,
    )

    # Step 2 & 3: generate or retrieve pseudonym, then replace span
    for entity in sorted_entities:
        existing = vault.get_by_entity_id(entity.entity_id)
        if existing is not None:
            pseudonym = existing.pseudonym
        else:
            pseudonym = _generate_pseudonym(entity, text, salt)
            vault.write(VaultRecord(
                entity_id=entity.entity_id,
                original=entity.original_text,
                pseudonym=pseudonym,
                type=entity.redact_type,
                data_type=entity.data_type,
                span=entity.span,
                timestamp=time.monotonic(),
            ))

        start, end = entity.span
        pseudonymized = pseudonymized[:start] + pseudonym + pseudonymized[end:]

    # Step 4: consistency scan - replace remaining verbatim occurrences
    for entity in sorted_entities:
        existing = vault.get_by_entity_id(entity.entity_id)
        if existing is None:
            continue
        original = entity.original_text
        pseudo = existing.pseudonym
        if original in pseudonymized:
            pseudonymized = pseudonymized.replace(original, pseudo)

    # Step 5: post-replace PII leak check
    # Collect known pseudonyms so they are not mistaken for real PII leaks.
    # Generated pseudonyms (e.g. fake emails, fake phones) are themselves
    # valid-looking PII patterns and would otherwise be flagged.
    known_pseudonyms: set[str] = set()
    for entity in sorted_entities:
        rec = vault.get_by_entity_id(entity.entity_id)
        if rec is not None:
            known_pseudonyms.add(rec.pseudonym)

    leak_entities = detect_fp(pseudonymized)
    real_leaks = [e for e in leak_entities if e.original_text not in known_pseudonyms]
    if real_leaks:
        raise PIILeakError(
            f"PII detected in pseudonymized output: "
            f"{[e.data_type for e in real_leaks]}"
        )

    return PseudonymizedDocument(
        text=pseudonymized,
        entity_registry=entity_registry,
        session_id=vault.session_id,
    )
