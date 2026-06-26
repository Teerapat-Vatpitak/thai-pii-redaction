"""Reverse mapping for de-anonymization.

Restores original PII from pseudonymized AI response using the vault's reverse index.
"""

from pii_redactor.models import AIResponse, EntityRegistry, ReverseResult
from pii_redactor.session_vault import SessionVault
from pii_redactor.detectors.fp_detector import detect_fp


def _pre_reverse_validate(ai_response: AIResponse, vault: SessionVault) -> None:
    """Raise if vault is idle or response is empty.

    Args:
        ai_response: The AI response to validate
        vault: The session vault to check for idle timeout

    Raises:
        VaultTimeoutError: If vault has been idle past timeout threshold
        ValueError: If response text is empty or blank
    """
    vault.check_idle()
    if not ai_response.text or not ai_response.text.strip():
        raise ValueError("Empty or blank AI response — cannot reverse map")


def _do_reverse(text: str, vault: SessionVault) -> tuple[str, list[str]]:
    """Replace pseudonyms with originals.

    Algorithm:
    1. Build mapping: pseudonym → original (from vault._reverse)
    2. Sort pseudonyms by LENGTH DESCENDING to avoid partial matches
       (e.g., 'alice.100@example.com' before 'alice')
    3. For each pseudonym: str.replace all occurrences in text
    4. Return (restored_text, list_of_replaced_pseudonyms)

    Args:
        text: The text containing pseudonyms
        vault: The session vault with reverse index

    Returns:
        Tuple of (restored_text, list_of_replaced_pseudonyms)
    """
    # Build pseudonym → original map
    pseudo_to_original: dict[str, str] = {}
    for pseudonym, entity_id in vault._reverse.items():
        record = vault.get_by_entity_id(entity_id)
        if record is not None:
            pseudo_to_original[pseudonym] = record.original

    # Sort by length descending (longest first)
    sorted_pseudonyms = sorted(pseudo_to_original.keys(), key=len, reverse=True)

    restored = text
    replaced = []
    for pseudonym in sorted_pseudonyms:
        if pseudonym in restored:
            restored = restored.replace(pseudonym, pseudo_to_original[pseudonym])
            replaced.append(pseudonym)

    return restored, replaced


def _post_reverse_validate(
    restored_text: str,
    replaced: list[str],
    entity_registry: EntityRegistry,
    vault: SessionVault,
) -> tuple[list[str], dict]:
    """Post-reverse checks. Returns (flags, audit_summary).

    Checks:
    1. Pseudonym residue: any vault pseudonym still in restored text?
    2. Completeness: all registered entities reversed?
    3. PII presence (informational): can fp_detector find PII in restored text?
       (This is EXPECTED — we just restored real PII — so it's for audit only)

    Args:
        restored_text: The text after pseudonym replacement
        replaced: List of pseudonyms that were replaced
        entity_registry: The registry of detected entities
        vault: The session vault

    Returns:
        Tuple of (flags, audit_summary) where:
        - flags: list of warning strings
        - audit_summary: dict with counts and metadata
    """
    flags = []

    # 1. Pseudonym residue check
    residue = []
    for pseudonym in vault._reverse.keys():
        if pseudonym in restored_text:
            residue.append(pseudonym)
            flags.append(f"pseudonym_residue:{pseudonym[:8]}")

    # 2. Completeness check
    total_entities = len(entity_registry.entities)
    replaced_count = len(replaced)
    if replaced_count < total_entities:
        flags.append(f"incomplete_reverse:{replaced_count}/{total_entities}")

    # 3. PII scan (informational only — EXPECTED to find PII since we restored it)
    restored_pii = detect_fp(restored_text)

    audit_summary = {
        "total_entities": total_entities,
        "replaced_count": replaced_count,
        "residue_count": len(residue),
        "restored_pii_types": list({e.data_type for e in restored_pii}),
        "request_id": "unknown",  # Caller can set this
    }

    return flags, audit_summary


def reverse_map(
    ai_response: AIResponse,
    entity_registry: EntityRegistry,
    vault: SessionVault,
) -> ReverseResult:
    """Restore original PII values in AI response text.

    Returns ReverseResult with restored text, warning flags, and audit summary.

    Args:
        ai_response: The pseudonymized AI response
        entity_registry: The registry of detected entities
        vault: The session vault with original↔pseudonym mappings

    Returns:
        ReverseResult with restored text and audit information

    Raises:
        ValueError: If response text is empty or blank
        VaultTimeoutError: If vault has been idle past timeout threshold
    """
    # Pre-validate
    _pre_reverse_validate(ai_response, vault)

    # Core reverse
    restored_text, replaced = _do_reverse(ai_response.text, vault)

    # Post-validate
    flags, audit_summary = _post_reverse_validate(
        restored_text, replaced, entity_registry, vault
    )
    audit_summary["request_id"] = ai_response.request_id

    return ReverseResult(
        text=restored_text,
        flags=flags,
        audit_summary=audit_summary,
    )
