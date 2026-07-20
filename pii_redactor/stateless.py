"""Stateless core (AI for Thai platform contract).

The signed proposal states the platform "จะไม่ถือข้อมูลส่วนบุคคลของผู้ใช้รายใดเลย".
That is enforced here structurally rather than by configuration: this module
builds a SessionVault, uses it for one call, hands its contents back to the
caller and drops it. There is nowhere for a mapping to persist, which is a
property you can read off the signature.

SessionService (local storefronts) keeps a vault on purpose. Both paths run the
same body — `sanitize_into_vault` — which is deliberately handed the vault it
works on rather than owning one; that is the single knob separating the
stateless platform deployment from the stateful local one.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pii_redactor.anonymizer.anonymizer import PIILeakError, anonymize
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import Entity, EntityRegistry
from pii_redactor.report import scan_section26
from pii_redactor.session_vault import SessionVault

_VALID_MODES = ("token", "surrogate")


@dataclass
class StatelessSanitizeResult:
    sanitized_text: str
    mapping: dict[str, str]
    entities: list[dict]
    entity_type_counts: dict[str, int]
    section26: list[dict]
    warnings: list[str]


@dataclass
class SanitizeCore:
    """Shared result of the mask+guard body, before either caller shapes it."""

    sanitized_text: str
    detected: list[Entity]  # raw Entity objects, for the session's registry
    entities: list[dict]  # the wire shape (start/end/data_type/redact_type/token)
    entity_type_counts: dict[str, int]
    warnings: list[str]


class StatelessLeakError(Exception):
    """Raised when the masked text still carries checksum-grade real PII."""

    def __init__(self, leak_types: list[str]):
        self.leak_types = leak_types
        super().__init__(f"outbound leak: {leak_types}")


def sanitize_into_vault(
    text: str,
    vault: SessionVault,
    *,
    mode: str,
    salt: str,
    scan_leaks: Callable[[str, SessionVault], list[Entity]] = scan_outbound_leaks,
) -> SanitizeCore:
    """Detect, mask and leak-guard `text` using the vault the caller supplies.

    The vault is a parameter, not a field: a caller that wants statelessness
    passes a throwaway one, a caller that wants multi-turn continuity passes
    the one it keeps. Nothing else differs between the two deployments.

    `scan_leaks` is injectable so a caller's own module-level reference is the
    one used — the leak guard is the security boundary, and a caller must be
    able to substitute it without reaching into this module.

    Raises:
        StatelessLeakError: masking failed, or checksum-grade PII survived it.
            The text is never returned in either case.
        VaultTimeoutError: propagated untouched from the supplied vault.
    """
    detected = detect_all(text)
    registry = EntityRegistry(
        entities=detected,
        fp_count=sum(1 for e in detected if e.redact_type == "FP"),
        tb_count=sum(1 for e in detected if e.redact_type == "TB"),
    )
    try:
        pseudo = anonymize(text, registry, vault, salt=salt, mode=mode)
    except (PIILeakError, ValueError) as e:
        # mask failed — never return the text
        raise StatelessLeakError(["ANONYMIZE_FAILED"]) from e

    leaks = scan_leaks(pseudo.text, vault)
    fp_leaks = [e for e in leaks if e.redact_type == "FP"]
    if fp_leaks:
        raise StatelessLeakError(sorted({e.data_type for e in fp_leaks}))
    warnings = [f"possible_tb_leak:{e.data_type}" for e in leaks if e.redact_type != "FP"]

    out_entities = []
    for e in detected:
        record = vault.get_by_entity_id(e.entity_id)
        out_entities.append(
            {
                "start": e.span[0],
                "end": e.span[1],
                "data_type": e.data_type,
                "redact_type": e.redact_type,
                "token": record.pseudonym if record else "",
            }
        )
    type_counts: dict[str, int] = {}
    for e in out_entities:
        type_counts[e["data_type"]] = type_counts.get(e["data_type"], 0) + 1

    return SanitizeCore(
        sanitized_text=pseudo.text,
        detected=detected,
        entities=out_entities,
        entity_type_counts=type_counts,
        warnings=warnings,
    )


def sanitize_stateless(
    text: str,
    *,
    mode: str,
    salt: str,
    prior_mapping: dict[str, str] | None = None,
) -> StatelessSanitizeResult:
    """Mask PII and return the pseudonym->original map to the caller.

    Nothing is retained. `prior_mapping` restores multi-turn token consistency
    without server state: pass back the map from the previous turn.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; supported: {_VALID_MODES}")

    vault = SessionVault()
    try:
        if prior_mapping:
            for pseudonym, original in prior_mapping.items():
                vault.seed(pseudonym, original)

        core = sanitize_into_vault(text, vault, mode=mode, salt=salt)
        mapping = vault.export_mapping()
    finally:
        # The map has already been copied out as plain strings; clearing only
        # scrubs this throwaway vault. Runs on the error paths too, so a failed
        # mask does not leave originals sitting in memory.
        vault.clear()

    return StatelessSanitizeResult(
        sanitized_text=core.sanitized_text,
        mapping=mapping,
        entities=core.entities,
        entity_type_counts=core.entity_type_counts,
        section26=scan_section26(text),
        warnings=core.warnings,
    )
