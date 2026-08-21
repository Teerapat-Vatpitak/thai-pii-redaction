"""Pseudonymization orchestrator.

Two modes: mode="surrogate" (default) draws realistic fake values from
fp_generator/tb_generator with collision-safe re-rolls; mode="token" emits
session-namespaced bracket tokens via token_generator (web AI-Guard default).

Algorithm:
1. Sort entities by span[0] DESCENDING (tail-first) to preserve offsets during replacement.
2. For each entity: reuse only a safe vault hit; otherwise generate -> write.
3. Replace span in text (tail-first preserves earlier spans).
4. Consistency scan: replace remaining verbatim occurrences of each original.
5. Post-replace PII leak check via detect_fp -> raise PIILeakError if any found.
6. Return PseudonymizedDocument.
"""

from __future__ import annotations

import time
import unicodedata

from pii_redactor.anonymizer.fp_generator import generate_fp
from pii_redactor.anonymizer.tb_generator import generate_tb
from pii_redactor.anonymizer.token_generator import (
    generate_token,
    is_token_for_data_type,
    new_token_nonce,
    token_data_type_from_candidate,
    token_namespace_from_candidate,
    token_ordinal_from_candidate,
)
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.leak_guard import (
    OutboundGuardContext,
    pseudonym_ranges,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.models import (
    Entity,
    EntityRegistry,
    PseudonymizedDocument,
    ReplacementHighlight,
    VaultRecord,
)
from pii_redactor.scan_common import canonical_value
from pii_redactor.session_vault import SEEDED_DATA_TYPE, SessionVault


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
        return generate_fp(entity.data_type, entity.original_text, salt=salt, attempt=attempt)
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
_MAX_TOKEN_NONCE_ATTEMPTS = 32


def _compact_identity(value: str) -> str:
    """Fold case, width, spacing, and punctuation for conservative comparison."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if unicodedata.category(char)[0] in {"L", "M", "N"})


def _safe_to_reuse(
    candidate: str,
    original: str,
    compact_source: str,
    data_type: str,
) -> bool:
    """Return whether a prior pseudonym can safely represent this turn.

    Takes the source text already folded: it is the same text for every entity
    of one document, and folding it per entity cost length x entities.
    """
    if not candidate:
        return False
    typed_candidate = canonical_value(data_type, candidate)
    typed_original = canonical_value(data_type, original)
    compact_candidate = _compact_identity(candidate)
    compact_original = _compact_identity(original)
    return (
        bool(compact_candidate)
        and (not typed_original or typed_original not in typed_candidate)
        and compact_original not in compact_candidate
        and compact_candidate not in compact_source
    )


def _seeded_candidate_is_admissible(record: VaultRecord, data_type: str, mode: str) -> bool:
    """Require caller-supplied replacements to pass this turn's safety policy."""
    if record.data_type != SEEDED_DATA_TYPE:
        return True

    candidate = record.pseudonym
    empty_context = OutboundGuardContext()
    if scan_outbound_leaks(candidate, empty_context) or scan_residual_signals(
        candidate,
        empty_context,
    ):
        return False

    if mode != "token":
        return True
    # Legacy caller-held mappings remain readable at the explicit stateless
    # boundary. Tokens minted by this process always carry a namespace.
    return is_token_for_data_type(candidate, data_type, allow_legacy=True)


def _generate_unique_pseudonym(
    entity: Entity,
    text: str,
    salt: str,
    vault: SessionVault,
    all_originals: set[str],
    compact_text: str,
) -> str:
    """Generate a pseudonym that cannot be confused with anyone else's data.

    The fake-value pools (esp. Thai names) are small, so two different people
    can deterministically draw the same pseudonym — the vault reverse index
    would then restore the wrong person. A candidate is rejected when it:
    - is empty or contains the original;
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
    if (
        existing is not None
        and _seeded_candidate_is_admissible(existing, entity.data_type, "surrogate")
        and _safe_to_reuse(
            existing.pseudonym,
            original,
            compact_text,
            entity.data_type,
        )
    ):
        return existing.pseudonym

    def _available(candidate: str) -> bool:
        if not _safe_to_reuse(candidate, original, compact_text, entity.data_type):
            return False  # empty, identity, and embedded-original values do not mask
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
        and _safe_to_reuse(base, original, compact_text, entity.data_type)
        and base not in all_originals
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


def _next_token(entity: Entity, text: str, vault: SessionVault, compact_text: str) -> str:
    """Reuse a safe token or take the next ordinal for this data type."""
    existing = vault.get_by_original(entity.original_text, data_type=entity.data_type)
    candidates: list[VaultRecord] = []
    if existing is not None:
        candidates.append(existing)
    candidates.extend(
        record
        for entity_id, record in vault._table.items()
        if record is not existing
        and record.original == entity.original_text
        and record.data_type in {entity.data_type, SEEDED_DATA_TYPE}
        and vault._reverse.get(record.pseudonym) == entity_id
    )
    candidates.sort(key=lambda record: record.data_type == SEEDED_DATA_TYPE)
    for candidate in candidates:
        if (
            vault._reverse.get(candidate.pseudonym) == candidate.entity_id
            and _seeded_candidate_is_admissible(candidate, entity.data_type, "token")
            and _safe_to_reuse(
                candidate.pseudonym,
                entity.original_text,
                compact_text,
                entity.data_type,
            )
        ):
            return candidate.pseudonym
    used_ordinals: set[int] = set()
    for entity_id, record in vault._table.items():
        if vault._reverse.get(record.pseudonym) != entity_id:
            continue
        if record.data_type == entity.data_type:
            ordinal = token_ordinal_from_candidate(record.pseudonym, entity.data_type)
        elif _seeded_token_is_admissible(record, entity.data_type, compact_text):
            ordinal = token_ordinal_from_candidate(
                record.pseudonym,
                entity.data_type,
                allow_legacy=True,
            )
        else:
            ordinal = None
        if ordinal is not None:
            used_ordinals.add(ordinal)
    ordinal = max(used_ordinals, default=0) + 1
    for _ in range(_MAX_TOKEN_NONCE_ATTEMPTS):
        token = generate_token(
            entity.data_type,
            ordinal,
            namespace=vault.token_namespace,
            nonce=new_token_nonce(),
        )
        if token not in text and token not in vault._reverse:
            return token
    raise ValueError("unable to mint a unique token")


def _seeded_token_is_admissible(
    record: VaultRecord,
    data_type: str,
    compact_text: str,
) -> bool:
    """Return whether one caller-held token may affect this turn."""
    return (
        record.data_type == SEEDED_DATA_TYPE
        and _seeded_candidate_is_admissible(record, data_type, "token")
        and _safe_to_reuse(
            record.pseudonym,
            record.original,
            compact_text,
            data_type,
        )
    )


def _adopt_seeded_token_namespace(
    compact_text: str,
    entity_registry: EntityRegistry,
    vault: SessionVault,
) -> None:
    """Continue one admissible caller-held token chain before minting."""
    detected_types_by_original: dict[str, set[str]] = {}
    for entity in entity_registry.entities:
        detected_types_by_original.setdefault(entity.original_text, set()).add(entity.data_type)

    namespaces: set[str] = set()
    for entity_id, record in vault._table.items():
        if vault._reverse.get(record.pseudonym) != entity_id:
            continue
        data_type = token_data_type_from_candidate(record.pseudonym)
        detected_types = detected_types_by_original.get(record.original)
        if detected_types is not None and data_type not in detected_types:
            continue
        if data_type is None or not _seeded_token_is_admissible(record, data_type, compact_text):
            continue
        namespace = token_namespace_from_candidate(record.pseudonym)
        if namespace is not None:
            namespaces.add(namespace)
    if len(namespaces) == 1:
        vault.adopt_token_namespace(next(iter(namespaces)))


def _find_all(haystack: str, needle: str) -> list[int]:
    """Non-overlapping start offsets of needle in haystack, left to right.

    A match consumes its own characters, which is the scan str.replace performs:
    "กก" occurs once in "กกก", not twice. Advancing a single character instead
    would queue overlapping ranges, and the tail-first splice would then write
    one of them over an offset a later splice had already invalidated.
    """
    out: list[int] = []
    pos = 0
    while (i := haystack.find(needle, pos)) >= 0:
        out.append(i)
        pos = i + len(needle)
    return out


def _add_replacement_highlight(
    highlights: list[ReplacementHighlight],
    *,
    start: int,
    end: int,
    replacement_length: int,
    data_type: str,
    redact_type: str,
) -> None:
    """Keep prior sanitized intervals aligned across one text splice."""
    delta = replacement_length - (end - start)
    shifted: list[ReplacementHighlight] = []
    for item in highlights:
        if item.start >= end:
            shifted.append(
                ReplacementHighlight(
                    start=item.start + delta,
                    end=item.end + delta,
                    data_type=item.data_type,
                    redact_type=item.redact_type,
                )
            )
        else:
            shifted.append(item)
    shifted.append(
        ReplacementHighlight(
            start=start,
            end=start + replacement_length,
            data_type=data_type,
            redact_type=redact_type,
        )
    )
    highlights[:] = shifted


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
    replacement_highlights: list[ReplacementHighlight] = []
    # One folded copy of the source for every reuse check in this call.
    compact_text = _compact_identity(text)
    if mode == "token":
        _adopt_seeded_token_namespace(compact_text, entity_registry, vault)

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
                pseudonym = _next_token(entity, text, vault, compact_text)
            else:
                pseudonym = _generate_unique_pseudonym(
                    entity, text, salt, vault, all_originals, compact_text
                )
            vault.write(
                VaultRecord(
                    entity_id=entity.entity_id,
                    original=entity.original_text,
                    pseudonym=pseudonym,
                    type=entity.redact_type,
                    data_type=entity.data_type,
                    span=entity.span,
                    timestamp=time.monotonic(),
                )
            )

        start, end = entity.span
        pseudonymized = pseudonymized[:start] + pseudonym + pseudonymized[end:]
        _add_replacement_highlight(
            replacement_highlights,
            start=start,
            end=end,
            replacement_length=len(pseudonym),
            data_type=entity.data_type,
            redact_type=entity.redact_type,
        )

    # Step 4: consistency scan - replace remaining verbatim occurrences
    # Build known pseudonyms set first to avoid cascading: skip replacement
    # when the original text is itself a known pseudonym (would corrupt vault mapping)
    known_pseudonyms_scan: set[str] = set()
    for entity in sorted_entities:
        rec = vault.get_by_entity_id(entity.entity_id)
        if rec is not None:
            known_pseudonyms_scan.add(rec.pseudonym)

    scan_pseudonyms = [p for p in known_pseudonyms_scan if p]
    # Those ranges depend only on the text and that fixed pseudonym list, so
    # they are derived once and kept until this scan itself rewrites the text.
    # Re-deriving them per entity made masking cost entities x document length,
    # and a long paste took minutes.
    protected: list[tuple[int, int]] | None = None
    for entity in sorted_entities:
        existing = vault.get_by_entity_id(entity.entity_id)
        if existing is None:
            continue
        original = entity.original_text
        pseudo = existing.pseudonym
        if not original or original in known_pseudonyms_scan:
            continue
        # Replace only OUTSIDE the ranges pseudonyms already occupy. A generated
        # pseudonym can contain another entity's original verbatim -- the fake
        # pools are small and the NER splits names, so "ไทย" is its own LOCATION
        # entity while also sitting inside a fake surname. str.replace reached
        # into the pseudonym written moments earlier, and the corrupted value no
        # longer matched the vault, so reverse_map could not restore it and the
        # original was lost. Whole-string equality does not catch that; the
        # hazard is containment. Same positional rule as reverse_mapper.
        if protected is None:
            protected = pseudonym_ranges(pseudonymized, scan_pseudonyms)
        hits = [
            (i, i + len(original))
            for i in _find_all(pseudonymized, original)
            if not any(i < pe and i + len(original) > ps for ps, pe in protected)
        ]
        for start, end in reversed(hits):  # tail-first so earlier offsets stay valid
            pseudonymized = pseudonymized[:start] + pseudo + pseudonymized[end:]
            _add_replacement_highlight(
                replacement_highlights,
                start=start,
                end=end,
                replacement_length=len(pseudo),
                data_type=entity.data_type,
                redact_type=entity.redact_type,
            )
        if hits:
            protected = None

    # Step 5: post-replace PII leak check
    # Collect known pseudonyms so they are not mistaken for real PII leaks.
    # Generated pseudonyms (e.g. fake emails, fake phones) are themselves
    # valid-looking PII patterns and would otherwise be flagged.
    known_pseudonyms: set[str] = set()
    for entity in sorted_entities:
        rec = vault.get_by_entity_id(entity.entity_id)
        if rec is not None:
            known_pseudonyms.add(rec.pseudonym)

    # Whole-string exclusion is not enough once the detectors read address
    # STRUCTURE: a generated fake address carries its own "ซอย"/"แขวง" labels,
    # so the address detectors re-detect a FRAGMENT of a pseudonym we just
    # wrote ("สุขสันต์ 9" out of a longer fake address). That fragment is not
    # in known_pseudonyms and used to raise PIILeakError on our own output.
    # Same fix leak_guard already applies: excuse a span only when pseudonym
    # occurrences positionally account for it.
    ranges = pseudonym_ranges(pseudonymized, [p for p in known_pseudonyms if p])
    leak_entities = detect_fp(pseudonymized)
    real_leaks = [
        e
        for e in leak_entities
        if e.original_text not in known_pseudonyms
        and not any(cs <= e.span[0] and e.span[1] <= ce for cs, ce in ranges)
    ]
    if real_leaks:
        raise PIILeakError(
            f"PII detected in pseudonymized output: {[e.data_type for e in real_leaks]}"
        )

    return PseudonymizedDocument(
        text=pseudonymized,
        entity_registry=entity_registry,
        session_id=vault.session_id,
        replacement_highlights=tuple(
            sorted(replacement_highlights, key=lambda item: (item.start, item.end))
        ),
    )
