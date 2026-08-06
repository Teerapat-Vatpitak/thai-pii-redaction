"""Reverse mapping for de-anonymization.

Restores original PII from pseudonymized AI response using the vault's reverse index.
"""

import re
from collections.abc import Iterable

from pii_redactor.anonymizer.token_generator import token_namespace_from_candidate
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.models import AIResponse, EntityRegistry, ReverseResult
from pii_redactor.session_vault import SessionVault


def _char_class(c: str) -> str | None:
    """Classify a char for the reverse-map boundary guard (VAULT-1).

    A surrogate-mode pseudonym is a bare value (a fake phone / name), so a raw
    substring match can land INSIDE a longer number or Thai word and splice the
    real value mid-token. We only claim a match when neither edge is glued to a
    character of the same class. Token-mode pseudonyms start/end with brackets
    (class None), so they are never boundary-rejected.
    """
    if c.isdigit():  # covers Thai (๐-๙) and ASCII digits
        return "digit"
    if "ก" <= c <= "๎":  # Thai letters / vowels / tone marks (digits handled above)
        return "thai"
    if c.isascii() and c.isalpha():
        return "latin"
    return None


def _boundary_ok(text: str, start: int, end: int, pseudonym: str) -> bool:
    """Reject a match that is embedded in a longer token (VAULT-1).

    Classes with word delimiters (digits, Latin) reject on EITHER side: a value
    glued to a same-class char is inside a longer token (a longer number, or a
    longer Latin run — e.g. a surrogate email spliced into "prefix<email>").
    Thai is the exception: it has no word spaces, so a surrogate name legitimately
    abuts a neighbouring word on ONE side (e.g. "ผมชื่อ<name>"); only Thai gluing
    on BOTH sides means the name is truly embedded inside a longer word.
    """
    lc = _char_class(pseudonym[0])
    rc = _char_class(pseudonym[-1])
    left_glue = start > 0 and lc is not None and _char_class(text[start - 1]) == lc
    right_glue = end < len(text) and rc is not None and _char_class(text[end]) == rc
    if (left_glue and lc in ("digit", "latin")) or (right_glue and rc in ("digit", "latin")):
        return False
    if left_glue and right_glue:
        return False
    return True


# Foreign-token detector (spec 2026-07-27): bracket-shaped tokens in the raw
# model reply that we never sent. A translated or stale token remains a weak
# unused-pseudonym signal while nothing else classifies the bracket value left
# in the text. Alert-only: guessing its meaning could restore the wrong person.
_BRACKET_CANDIDATE = re.compile(r"\[([^\[\]\r\n]{1,128})\]")
# ASCII-only ordinal: str.isdigit() accepts Thai digits the generator never emits.
_TOKEN_ORDINAL = re.compile(r"[1-9][0-9]*")


def _is_token_shaped(inner: str) -> bool:
    label, sep, ordinal = inner.rpartition("_")
    if not sep or not label:
        return False
    return _TOKEN_ORDINAL.fullmatch(ordinal) is not None


def count_foreign_tokens(
    raw_text: str,
    sent_pseudonyms: Iterable[str],
    *,
    mode: str | None = None,
) -> int:
    """Occurrences of bracket tokens in `raw_text` that are not in the sent set.

    Exact current namespaced tokens remain active in every mode so stale token
    text cannot fail open through a replacement surrogate session. Legacy or
    translated bracket shapes remain active only in explicit/inferred token
    mode to avoid surrogate-mode false positives. Returns a count, never the
    candidates: arbitrary model output must not reach audit logs (VAULT-4).
    """
    sent = {p for p in sent_pseudonyms if p}

    def _is_token(p: str) -> bool:
        m = _BRACKET_CANDIDATE.fullmatch(p)
        return bool(m) and _is_token_shaped(m.group(1))

    token_mode = mode == "token" or (mode is None and any(_is_token(p) for p in sent))
    count = 0
    for match in _BRACKET_CANDIDATE.finditer(raw_text):
        candidate = match.group(0)
        if candidate in sent:
            continue
        if token_namespace_from_candidate(candidate) is not None or (
            token_mode and _is_token_shaped(match.group(1))
        ):
            count += 1
    return count


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


def _do_reverse(
    text: str,
    vault: SessionVault,
) -> tuple[str, list[str], tuple[tuple[int, int], ...]]:
    """Replace pseudonyms with originals.

    Algorithm:
    1. Build mapping: pseudonym → original (from vault._reverse).
    2. Locate every pseudonym occurrence on the ORIGINAL (untouched) text,
       longest pseudonym first so a shorter pseudonym cannot claim a slice of a
       longer one; claimed ranges never overlap (same rule as
       leak_guard.pseudonym_ranges).
    3. Build the restored text left-to-right and record each inserted interval.
    4. Return restored text, distinct replaced pseudonyms, and inserted ranges.

    Positional reconstruction (not a progressive str.replace) is what keeps a
    short pseudonym from corrupting an original already spliced in — a
    `.replace` re-scans the growing text and would rewrite a pseudonym-looking
    substring inside a restored value (see
    test_reverse_map_pseudonym_substring_of_original). Longest-first alone does
    not prevent that; only replacing on the untouched text does.

    Args:
        text: The text containing pseudonyms
        vault: The session vault with reverse index

    Returns:
        Restored text, replaced pseudonyms, and restored-output ranges.
    """
    # Build pseudonym → original map
    pseudo_to_original: dict[str, str] = {}
    for pseudonym, entity_id in vault._reverse.items():
        record = vault.get_by_entity_id(entity_id)
        if record is not None:
            pseudo_to_original[pseudonym] = record.original

    claimed: list[tuple[int, int, str]] = []

    def _taken(start: int, end: int) -> bool:
        return any(start < ce and end > cs for cs, ce, _ in claimed)

    replaced: list[str] = []
    for pseudonym in sorted(pseudo_to_original, key=len, reverse=True):
        if not pseudonym:
            continue
        found = False
        pos = 0
        while (i := text.find(pseudonym, pos)) >= 0:
            j = i + len(pseudonym)
            if not _taken(i, j) and _boundary_ok(text, i, j, pseudonym):
                claimed.append((i, j, pseudonym))
                found = True
            pos = i + 1
        if found:
            replaced.append(pseudonym)

    parts: list[str] = []
    restored_ranges: list[tuple[int, int]] = []
    source_cursor = 0
    restored_cursor = 0
    for cs, ce, pseudonym in sorted(claimed, key=lambda item: item[0]):
        prefix = text[source_cursor:cs]
        parts.append(prefix)
        restored_cursor += len(prefix)
        original = pseudo_to_original[pseudonym]
        start = restored_cursor
        parts.append(original)
        restored_cursor += len(original)
        restored_ranges.append((start, restored_cursor))
        source_cursor = ce
    parts.append(text[source_cursor:])
    restored = "".join(parts)

    return restored, replaced, tuple(restored_ranges)


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
    residue_count = sum(1 for pseudonym in vault._reverse if pseudonym in restored_text)
    if residue_count:
        flags.append(f"pseudonym_residue:{residue_count}")

    # 2. Completeness check — count DISTINCT pseudonyms, not raw entities. The
    # same person mentioned N times is N entities but one pseudonym
    # (consistency), so counting entities false-flags every repeated value on a
    # perfect restore. Derive the expected pseudonyms from the registry via the
    # vault (registry entity_ids were written to the vault at anonymize time).
    expected_pseudonyms: set[str] = set()
    for e in entity_registry.entities:
        rec = vault.get_by_entity_id(e.entity_id)
        if rec is not None:
            expected_pseudonyms.add(rec.pseudonym)
    total_entities = len(expected_pseudonyms)
    replaced_count = len(replaced)
    if replaced_count < total_entities:
        flags.append(f"incomplete_reverse:{replaced_count}/{total_entities}")

    # 3. PII scan (informational only — EXPECTED to find PII since we restored it)
    restored_pii = detect_fp(restored_text)

    audit_summary = {
        "total_entities": total_entities,
        "replaced_count": replaced_count,
        "residue_count": residue_count,
        "restored_pii_types": list({e.data_type for e in restored_pii}),
        "request_id": "unknown",  # Caller can set this
    }

    return flags, audit_summary


def reverse_map(
    ai_response: AIResponse,
    entity_registry: EntityRegistry,
    vault: SessionVault,
    *,
    mode: str | None = None,
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

    # Scan the RAW reply, before splice: after restoration the sent tokens are
    # gone and a restored original may itself contain bracket-looking text.
    foreign_count = count_foreign_tokens(
        ai_response.text,
        vault._reverse.keys(),
        mode=mode,
    )

    # Core reverse
    restored_text, replaced, restored_ranges = _do_reverse(ai_response.text, vault)

    # Post-validate
    flags, audit_summary = _post_reverse_validate(restored_text, replaced, entity_registry, vault)
    audit_summary["request_id"] = ai_response.request_id
    if foreign_count:
        flags.append(f"foreign_tokens:{foreign_count}")
    audit_summary["foreign_token_count"] = foreign_count

    return ReverseResult(
        text=restored_text,
        restored_ranges=restored_ranges,
        flags=flags,
        audit_summary=audit_summary,
    )
