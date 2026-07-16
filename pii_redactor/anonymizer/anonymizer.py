"""Pseudonymization orchestrator.

Two modes: mode="surrogate" (default) draws realistic fake values from
fp_generator/tb_generator with collision-safe re-rolls; mode="token" emits
bracket tokens like [ชื่อ_1] via token_generator (web AI-Guard default).

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
from pii_redactor.anonymizer.token_generator import generate_token
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


def _generate_pseudonym(entity: Entity, text: str, salt: str, attempt: int = 0) -> str:
    """Generate appropriate pseudonym based on entity redact_type."""
    if entity.redact_type == "FP":
        return generate_fp(
            entity.data_type, entity.original_text, salt=salt, attempt=attempt
        )
    else:
        context = _get_context_with_blank(text, entity)
        return generate_tb(
            entity.data_type,
            context,
            salt=salt,
            original=entity.original_text,
            attempt=attempt,
        )


_MAX_COLLISION_REROLLS = 8
_MAX_EXTENDED_REROLLS = 64


def _generate_unique_pseudonym(
    entity: Entity,
    text: str,
    salt: str,
    vault: SessionVault,
    all_originals: set[str],
) -> str:
    """Generate a pseudonym that cannot be confused with anyone else's data.

    The fake-value pools (esp. Thai names) are small, so two different people
    can deterministically draw the same pseudonym — the vault reverse index
    would then restore the wrong person. A candidate is rejected when it:
    - is already vaulted for a DIFFERENT original (same original = consistency,
      allowed), or
    - equals another entity's real value, or appears verbatim in the source
      text (reverse mapping would rewrite unrelated text).

    Re-rolls the seed up to _MAX_COLLISION_REROLLS times. Last resort differs
    by redact_type: FP keeps re-rolling (a '#N' suffix would leave the valid
    FP-looking base embedded in the output and detect_fp would re-flag it) and
    fails loudly when exhausted; TB may take a '#N' suffix (mirrors the
    uniqueness rules the old web-path generator had), but only on a base that
    is safe to embed — never someone's real value or a string from the source
    text.
    """
    original = entity.original_text

    # Cross-turn consistency: if this exact original already has a pseudonym
    # in the vault (regardless of which entity_id produced it), reuse it —
    # otherwise the same person can get a different fake name/address each
    # turn depending on which sentence-context tb_generator happened to see.
    existing = vault.get_by_original(original, data_type=entity.data_type)
    if existing is not None:
        return existing.pseudonym

    def _available(candidate: str) -> bool:
        if candidate == original:
            return False  # a pseudonym identical to its original masks nothing
        owner_id = vault._reverse.get(candidate)
        if owner_id is not None:
            owner = vault._table.get(owner_id)
            if owner is not None and owner.original != original:
                return False
        if candidate in all_originals:
            return False
        if candidate in text:
            return False
        return True

    candidate = _generate_pseudonym(entity, text, salt)
    for attempt in range(1, _MAX_COLLISION_REROLLS + 1):
        if _available(candidate):
            return candidate
        candidate = _generate_pseudonym(entity, text, salt, attempt=attempt)
    if _available(candidate):
        return candidate

    base = candidate
    suffix_ok = (
        entity.redact_type != "FP"
        and base != original
        and base not in all_originals
        and base not in text
    )
    if suffix_ok:
        n = 2
        while not _available(f"{base}#{n}"):
            n += 1
        return f"{base}#{n}"

    # FP (format must stay valid) or an unsafe-to-embed base: keep re-rolling.
    for attempt in range(_MAX_COLLISION_REROLLS + 1, _MAX_EXTENDED_REROLLS + 1):
        candidate = _generate_pseudonym(entity, text, salt, attempt=attempt)
        if _available(candidate):
            return candidate
    # SECURITY: no pseudonym/original values in the message
    raise ValueError(
        f"unable to generate a unique pseudonym for entity "
        f"{entity.entity_id[:8]} ({entity.data_type}) "
        f"after {_MAX_EXTENDED_REROLLS} attempts"
    )


def _next_token(entity: Entity, text: str, vault: SessionVault) -> str:
    """Token-mode pseudonym: reuse the token of the same (data_type, original);
    otherwise take the next ordinal for that data_type (continues across turns
    because the count comes from the vault, not from this call)."""
    existing = vault.get_by_original(entity.original_text, data_type=entity.data_type)
    if existing is not None:
        return existing.pseudonym
    distinct = {
        r.original for r in vault._table.values() if r.data_type == entity.data_type
    }
    ordinal = len(distinct) + 1
    token = generate_token(entity.data_type, ordinal)
    # a bracket token colliding with source text is near-impossible; bump anyway
    while token in text or token in vault._reverse:
        ordinal += 1
        token = generate_token(entity.data_type, ordinal)
    return token


def anonymize(
    text: str,
    entity_registry: EntityRegistry,
    vault: SessionVault,
    *,
    salt: str,
    mode: str = "surrogate",
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
    all_originals = {e.original_text for e in entity_registry.entities}
    for entity in sorted_entities:
        existing = vault.get_by_entity_id(entity.entity_id)
        if existing is not None:
            pseudonym = existing.pseudonym
        else:
            if mode == "token":
                pseudonym = _next_token(entity, text, vault)
            else:
                pseudonym = _generate_unique_pseudonym(
                    entity, text, salt, vault, all_originals
                )
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
    # Build known pseudonyms set first to avoid cascading: skip replacement
    # when the original text is itself a known pseudonym (would corrupt vault mapping)
    known_pseudonyms_scan: set[str] = set()
    for entity in sorted_entities:
        rec = vault.get_by_entity_id(entity.entity_id)
        if rec is not None:
            known_pseudonyms_scan.add(rec.pseudonym)

    for entity in sorted_entities:
        existing = vault.get_by_entity_id(entity.entity_id)
        if existing is None:
            continue
        original = entity.original_text
        pseudo = existing.pseudonym
        if original in pseudonymized and original not in known_pseudonyms_scan:
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
