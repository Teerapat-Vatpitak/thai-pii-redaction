"""3-layer output validation to detect PII leaks and data integrity issues.

Security design:
- Layer 1: Detect unexpected PII (not in vault) → halt
- Layer 2: Check pseudonym residue and entity completeness → flag only
- Layer 3: Verify UTF-8 encoding and no abrupt truncation → halt
"""

from dataclasses import dataclass

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.models import EntityRegistry, ReverseResult
from pii_redactor.session_vault import SessionVault


@dataclass
class ValidationResult:
    """Result of 3-layer output validation."""

    passed: bool  # True if all layers pass
    layer1_pii_clean: bool  # Layer 1: no unexpected PII found
    layer2_completeness_ok: bool  # Layer 2: pseudonym residue and entity counts ok
    layer3_integrity_ok: bool  # Layer 3: UTF-8 encodable, no abrupt truncation
    flags: list[str]  # All flags from all layers
    halt: bool  # True if Layer 3 failed (Layer 1 raises PIILeakError instead)


class PIILeakError(Exception):
    """Layer 1: Unexpected PII found in final output. Pipeline must halt immediately."""

    pass


def _layer1_pii_scan(text: str, vault: SessionVault) -> tuple[bool, list[str]]:
    """
    Run fp_detector on restored text.

    After reverse mapping, real PII IS expected in the text. This layer checks
    if the PII found is EXPECTED (was in the original document) by
    cross-referencing with vault records.

    Approach: FP-detected entities whose original_text matches a vault record's
    original are EXPECTED — they came back from reverse mapping.
    Any other FP detection is suspicious (unexpected PII).

    Args:
        text: The re-identified text from reverse mapping
        vault: SessionVault containing expected originals

    Returns:
        (pii_clean, flags) where pii_clean=True if all detected PII is expected
    """
    flags = []

    # Enforce idle timeout before accessing vault data
    vault.check_idle()

    # Build set of known originals from vault
    known_originals: set[str] = set()
    for record in vault._table.values():
        known_originals.add(record.original)

    # Run fp_detector on the text
    detected = detect_fp(text)

    # Flag only unexpected PII (not in known_originals)
    unexpected = [e for e in detected if e.original_text not in known_originals]

    if unexpected:
        data_types = [e.data_type for e in unexpected]
        flags.append(f"unexpected_pii:{data_types}")
        return False, flags

    return True, flags


def _layer2_completeness(
    reverse_result: ReverseResult,
    entity_registry: EntityRegistry,
    vault: SessionVault,
) -> tuple[bool, list[str]]:
    """
    Check: all pseudonyms resolved, all entities accounted for.

    Returns (ok, flags) — never halts, only flags incompleteness.

    Args:
        reverse_result: Output from reverse mapping step
        entity_registry: Original entity registry (contains total entities)
        vault: SessionVault (for completeness context)

    Returns:
        (ok, flags) where ok=True if no completeness issues detected
    """
    flags = []

    # Check for pseudonym residue from reverse_result
    residue_flags = [f for f in reverse_result.flags if "pseudonym_residue" in f]
    if residue_flags:
        flags.extend(residue_flags)

    # Check completeness from audit_summary
    summary = reverse_result.audit_summary
    total = summary.get("total_entities", 0)
    replaced = summary.get("replaced_count", 0)
    if total > 0 and replaced < total:
        flags.append(f"incomplete_reverse:{replaced}/{total}")

    ok = len(flags) == 0
    return ok, flags


def _layer3_integrity(text: str) -> tuple[bool, list[str]]:
    """
    Check: UTF-8 encodable + no abrupt truncation.

    Returns (ok, flags).

    Args:
        text: The text to validate

    Returns:
        (ok, flags) where ok=True if encoding and structure checks pass
    """
    flags = []

    # UTF-8 check
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as e:
        flags.append(f"encoding_error:{e}")
        return False, flags

    # Truncation heuristic, inverted to a small blocklist of endings that only
    # occur mid-cut. Legitimate documents routinely end without sentence-final
    # punctuation: Thai has no such convention at all, and a last line that is
    # a restored phone number, a version string, or an English proper noun is
    # normal output — flagging any of those halted real exports (VAULT-5).
    # So any letter or digit (any script) is a valid ending, as are closers
    # (quotes/brackets), sentence punctuation and whitespace. What remains —
    # a trailing comma, hyphen, opening bracket, colon and the like — is a
    # genuine mid-sentence cut. The cost is that a reply cut off exactly at a
    # digit/letter boundary is undetectable, which is the accepted trade-off:
    # this layer is a heuristic, and false halts destroyed real work.
    # Only flag if text is substantial (>20 chars).
    if text and len(text) > 20:
        last = text[-1]
        is_valid_ending = (
            last.isalnum() or last.isspace() or last in ".!?ฯๆ…%" or last in ")]}»\"'”’"
        )
        if not is_valid_ending:
            flags.append("possible_truncation:no_terminal_punctuation")

    ok = len(flags) == 0
    return ok, flags


def validate_output(
    reverse_result: ReverseResult,
    entity_registry: EntityRegistry,
    vault: SessionVault,
) -> ValidationResult:
    """
    Run 3-layer output validation.

    Layer 1 failure (unexpected PII): raise PIILeakError immediately
    Layer 2 failure (completeness): flag only, do not halt
    Layer 3 failure (encoding/structure): set halt=True, do not raise

    Args:
        reverse_result: Output from reverse mapping step
        entity_registry: Original entity registry
        vault: SessionVault containing expected originals

    Returns:
        ValidationResult with all validation outcomes

    Raises:
        PIILeakError: If Layer 1 detects unexpected PII
    """
    text = reverse_result.text
    all_flags = []

    # Layer 1: PII scan
    l1_ok, l1_flags = _layer1_pii_scan(text, vault)
    all_flags.extend(l1_flags)

    if not l1_ok:
        # Halt — raise PIILeakError
        raise PIILeakError(f"Unexpected PII detected in output: {l1_flags}")

    # Layer 2: Completeness
    l2_ok, l2_flags = _layer2_completeness(reverse_result, entity_registry, vault)
    all_flags.extend(l2_flags)

    # Layer 3: Integrity
    l3_ok, l3_flags = _layer3_integrity(text)
    all_flags.extend(l3_flags)

    halt = not l3_ok  # Layer 3 failure → halt but don't raise
    passed = l1_ok and l2_ok and l3_ok

    return ValidationResult(
        passed=passed,
        layer1_pii_clean=l1_ok,
        layer2_completeness_ok=l2_ok,
        layer3_integrity_ok=l3_ok,
        flags=all_flags,
        halt=halt,
    )
