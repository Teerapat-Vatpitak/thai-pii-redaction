"""Stateless core used by hosted and worker adapters.

The signed proposal states the platform "จะไม่ถือข้อมูลส่วนบุคคลของผู้ใช้รายใดเลย".
This module enforces only the core-owned part of that boundary: it builds a
SessionVault, uses it for one call, optionally returns a mapping to an
in-process adapter or the legacy worker-v1 opt-in path, and clears its
function-local vault. Hosted roundtrip consumes the mapping inside one request;
the accepted HTTP v2 wire contract does not export it. This primitive retains
no process-global session or vault; its adapter owns wire, logging, and storage
policy.

SessionService (local storefronts) keeps a vault on purpose. Both paths run the
same body — `sanitize_into_vault` — which is deliberately handed the vault it
works on rather than owning one; that is the single knob separating the
stateless platform deployment from the stateful local one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pii_redactor.anonymizer.anonymizer import PIILeakError, anonymize
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.leak_guard import (
    OutboundGuardContext,
    OutboundPolicyError,
    enforce_outbound_policy,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.models import AIResponse, Entity, EntityRegistry
from pii_redactor.report import scan_section26
from pii_redactor.reverse_mapper import reverse_map
from pii_redactor.safe_errors import discard_exception_graph
from pii_redactor.session_vault import SessionVault, VaultTimeoutError

_VALID_MODES = ("token", "surrogate")
_SANITIZE_FAILURE_CODE = "stateless_sanitize_failed"
_RESTORE_FAILURE_CODE = "stateless_restore_failed"
_PROCESSING_ERROR_MESSAGES = {
    _SANITIZE_FAILURE_CODE: "stateless sanitize failed",
    _RESTORE_FAILURE_CODE: "stateless restore failed",
}
_VAULT_TIMEOUT_MESSAGE = "Session vault idle timeout"
_INVALID_MODE_MESSAGE = "unknown stateless mode"
_INVALID_MAPPING_MESSAGE = "restore mapping must be a dict"
_EMPTY_RESTORE_MESSAGE = "restore text must not be empty"


@dataclass
class StatelessRestoreResult:
    restored_text: str
    replaced_count: int
    leftover_pseudonyms: list[str]
    warnings: list[str]


@dataclass
class StatelessSanitizeResult:
    sanitized_text: str
    mapping: dict[str, str]
    entities: list[dict]
    entity_type_counts: dict[str, int]
    section26: list[dict]
    warnings: list[str]

    @property
    def guard_context(self) -> OutboundGuardContext:
        """Trusted pseudonyms for an immediate pre-provider rescan.

        The context is captured from vault provenance and attached outside the
        dataclass fields, so repr, asdict, and the existing wire shapes cannot
        include it. Manually shaped results receive an empty context.
        """
        context = getattr(self, "_guard_context", None)
        if isinstance(context, OutboundGuardContext):
            return context
        return OutboundGuardContext()


@dataclass
class SanitizeCore:
    """Shared result of the mask+guard body, before either caller shapes it."""

    sanitized_text: str
    detected: list[Entity]  # raw Entity objects, for the session's registry
    entities: list[dict]  # the wire shape (start/end/data_type/redact_type/token)
    entity_type_counts: dict[str, int]
    warnings: list[str]


class StatelessLeakError(Exception):
    """Value-free failure to produce policy-safe masked text."""

    def __init__(
        self,
        leak_types: list[str],
        *,
        policy_categories: list[str] | set[str] | tuple[str, ...] = (),
    ):
        normalized = OutboundPolicyError(
            leak_types,
            policy_categories=policy_categories,
        )
        self.leak_types = normalized.leak_types
        self.policy_categories = normalized.policy_categories
        self.category_count = normalized.category_count
        self.policy_category_count = self.category_count
        super().__init__(f"outbound residual: {self.leak_types}")


class StatelessProcessingError(RuntimeError):
    """Fixed, value-free failure for an unexpected stateless-core defect."""

    def __init__(self, code: str):
        safe_code = code if code in _PROCESSING_ERROR_MESSAGES else _SANITIZE_FAILURE_CODE
        self.code = safe_code
        super().__init__(_PROCESSING_ERROR_MESSAGES[safe_code])


class _RestoreValidationError(Exception):
    """Internal marker translated only after public arguments are cleared."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__("stateless restore input rejected")


def sanitize_into_vault(
    text: str,
    vault: SessionVault,
    *,
    mode: str,
    salt: str,
    scan_leaks: Callable[[str, SessionVault], list[Entity]] = scan_outbound_leaks,
    scan_residual: Callable[[str, SessionVault], list[str]] = scan_residual_signals,
) -> SanitizeCore:
    """Run the shared mask body without retaining sensitive exception frames."""
    failure_kind = None
    failure_metadata = None
    try:
        return _sanitize_into_vault_impl(
            text,
            vault,
            mode=mode,
            salt=salt,
            scan_leaks=scan_leaks,
            scan_residual=scan_residual,
        )
    except StatelessLeakError as error:
        failure_kind = "residual"
        failure_metadata = (
            list(error.leak_types),
            list(error.policy_categories),
        )
        discard_exception_graph(error)
    except VaultTimeoutError as error:
        failure_kind = "timeout"
        discard_exception_graph(error)
    except Exception as error:
        failure_kind = "failed"
        discard_exception_graph(error)

    text = ""
    vault = None
    mode = ""
    salt = ""
    scan_leaks = None
    scan_residual = None
    if failure_kind == "residual":
        safe_leak_types, safe_categories = failure_metadata
        raise StatelessLeakError(
            safe_leak_types,
            policy_categories=safe_categories,
        )
    if failure_kind == "timeout":
        raise VaultTimeoutError(_VAULT_TIMEOUT_MESSAGE)
    raise StatelessProcessingError(_SANITIZE_FAILURE_CODE)


def _sanitize_into_vault_impl(
    text: str,
    vault: SessionVault,
    *,
    mode: str,
    salt: str,
    scan_leaks: Callable[[str, SessionVault], list[Entity]] = scan_outbound_leaks,
    scan_residual: Callable[[str, SessionVault], list[str]] = scan_residual_signals,
) -> SanitizeCore:
    """Detect, mask and leak-guard `text` using the vault the caller supplies.

    The vault is a parameter, not a field: a caller that wants statelessness
    passes a throwaway one, a caller that wants multi-turn continuity passes
    the one it keeps. Nothing else differs between the two deployments.

    Both scan callbacks are injectable so a caller's own module-level
    references are used. They are security boundaries, and callers must be
    able to substitute either one without reaching into this module.

    Raises:
        StatelessLeakError: masking failed, a replacement record is missing, or
            any outbound residual survived. The text is never returned.
        VaultTimeoutError: propagated untouched from the supplied vault.
    """
    detected = detect_all(text)
    registry = EntityRegistry(
        entities=detected,
        fp_count=sum(1 for e in detected if e.redact_type == "FP"),
        tb_count=sum(1 for e in detected if e.redact_type == "TB"),
    )
    anonymize_failure = False
    try:
        pseudo = anonymize(text, registry, vault, salt=salt, mode=mode)
    except (PIILeakError, ValueError) as error:
        discard_exception_graph(error)
        anonymize_failure = True
    if anonymize_failure:
        text = ""
        vault = None
        detected = []
        registry = None
        scan_leaks = None
        scan_residual = None
        salt = ""
        mode = ""
        raise StatelessLeakError(
            ["ANONYMIZE_FAILED"],
            policy_categories=["replacement_integrity"],
        )

    policy_failure = None
    try:
        enforce_outbound_policy(
            pseudo.text,
            guard_context=vault,
            scan_leaks=scan_leaks,
            scan_residual=scan_residual,
        )
    except OutboundPolicyError as error:
        policy_failure = (list(error.leak_types), list(error.policy_categories))
        discard_exception_graph(error)
    if policy_failure is not None:
        safe_leak_types, safe_categories = policy_failure
        text = ""
        vault = None
        detected = []
        registry = None
        pseudo = None
        scan_leaks = None
        scan_residual = None
        salt = ""
        mode = ""
        raise StatelessLeakError(
            safe_leak_types,
            policy_categories=safe_categories,
        )

    out_entities = []
    missing_record = False
    for e in detected:
        record = vault.get_by_entity_id(e.entity_id)
        if record is None:
            missing_record = True
            break
        out_entities.append(
            {
                "start": e.span[0],
                "end": e.span[1],
                "data_type": e.data_type,
                "redact_type": e.redact_type,
                "token": record.pseudonym,
            }
        )
    if missing_record:
        text = ""
        vault = None
        detected = []
        registry = None
        pseudo = None
        scan_leaks = None
        scan_residual = None
        salt = ""
        mode = ""
        out_entities = []
        e = None
        record = None
        raise StatelessLeakError(
            ["MISSING_REPLACEMENT_RECORD"],
            policy_categories=["replacement_integrity"],
        )
    type_counts: dict[str, int] = {}
    for e in out_entities:
        type_counts[e["data_type"]] = type_counts.get(e["data_type"], 0) + 1

    return SanitizeCore(
        sanitized_text=pseudo.text,
        detected=detected,
        entities=out_entities,
        entity_type_counts=type_counts,
        warnings=[],
    )


def _clear_throwaway_vault(vault: SessionVault) -> bool:
    """Drop vault-owned references without retaining a cleanup exception."""
    try:
        vault.clear()
    except Exception as error:
        discard_exception_graph(error)
        return False
    return True


def restore_stateless(text: str, *, mapping: dict[str, str]) -> StatelessRestoreResult:
    """Restore from a caller mapping without retaining sensitive failures."""
    failure_kind = None
    validation_kind = None
    try:
        return _restore_stateless_impl(text, mapping=mapping)
    except _RestoreValidationError as error:
        validation_kind = error.kind
        failure_kind = "validation"
        discard_exception_graph(error)
    except VaultTimeoutError as error:
        failure_kind = "timeout"
        discard_exception_graph(error)
    except Exception as error:
        failure_kind = "failed"
        discard_exception_graph(error)

    text = ""
    mapping = None
    if failure_kind == "validation":
        if validation_kind == "empty_text":
            raise ValueError(_EMPTY_RESTORE_MESSAGE)
        raise ValueError(_INVALID_MAPPING_MESSAGE)
    if failure_kind == "timeout":
        raise VaultTimeoutError(_VAULT_TIMEOUT_MESSAGE)
    raise StatelessProcessingError(_RESTORE_FAILURE_CODE)


def _restore_stateless_impl(
    text: str,
    *,
    mapping: dict[str, str],
) -> StatelessRestoreResult:
    """Restore through a throwaway vault and clear it before any return."""
    if not isinstance(mapping, dict):
        raise _RestoreValidationError("mapping")

    vault = SessionVault()
    output = None
    cleanup_ok = False
    try:
        invalid_mapping = False
        for pseudonym, original in mapping.items():
            try:
                vault.seed(pseudonym, original)
            except ValueError as error:
                discard_exception_graph(error)
                invalid_mapping = True
                break
        if invalid_mapping:
            raise _RestoreValidationError("mapping")
        if not text or not text.strip():
            raise _RestoreValidationError("empty_text")

        result = reverse_map(
            AIResponse(text=text, request_id=str(uuid.uuid4()), latency=0.0),
            EntityRegistry(entities=[], fp_count=0, tb_count=0),
            vault,
        )
        restored = result.text
        flags = list(result.flags)

        # Counted here rather than taken from the audit summary: the caller's
        # question is how much of its mapping was applied, not how many vault
        # records happened to exist.
        present = [p for p in mapping if p and p in text]
        leftover = sorted(p for p in present if p in restored)
        replaced = len(present) - len(leftover)
        unused = [p for p in mapping if p and p not in text]
        if unused:
            flags.append(f"unused_pseudonyms:{len(unused)}")
        if leftover:
            flags.append(f"pseudonym_not_substituted:{len(leftover)}")

        output = StatelessRestoreResult(
            restored_text=restored,
            replaced_count=replaced,
            leftover_pseudonyms=leftover,
            warnings=flags,
        )
    finally:
        cleanup_ok = _clear_throwaway_vault(vault)

    if not cleanup_ok:
        text = ""
        mapping = None
        vault = None
        output = None
        result = None
        restored = ""
        flags = []
        present = []
        leftover = []
        unused = []
        pseudonym = None
        original = None
        raise StatelessProcessingError(_RESTORE_FAILURE_CODE)
    assert output is not None
    return output


def sanitize_stateless(
    text: str,
    *,
    mode: str,
    salt: str,
    prior_mapping: dict[str, str] | None = None,
) -> StatelessSanitizeResult:
    """Mask PII without retaining a throwaway-vault failure graph."""
    failure_kind = None
    failure_metadata = None
    if mode not in _VALID_MODES:
        failure_kind = "mode"
    else:
        try:
            return _sanitize_stateless_impl(
                text,
                mode=mode,
                salt=salt,
                prior_mapping=prior_mapping,
            )
        except StatelessLeakError as error:
            failure_kind = "residual"
            failure_metadata = (
                list(error.leak_types),
                list(error.policy_categories),
            )
            discard_exception_graph(error)
        except VaultTimeoutError as error:
            failure_kind = "timeout"
            discard_exception_graph(error)
        except Exception as error:
            failure_kind = "failed"
            discard_exception_graph(error)

    text = ""
    mode = ""
    salt = ""
    prior_mapping = None
    if failure_kind == "mode":
        raise ValueError(_INVALID_MODE_MESSAGE)
    if failure_kind == "residual":
        safe_leak_types, safe_categories = failure_metadata
        raise StatelessLeakError(
            safe_leak_types,
            policy_categories=safe_categories,
        )
    if failure_kind == "timeout":
        raise VaultTimeoutError(_VAULT_TIMEOUT_MESSAGE)
    raise StatelessProcessingError(_SANITIZE_FAILURE_CODE)


def _sanitize_stateless_impl(
    text: str,
    *,
    mode: str,
    salt: str,
    prior_mapping: dict[str, str] | None,
) -> StatelessSanitizeResult:
    """Build the complete result before clearing the function-local vault."""
    vault = SessionVault()
    output = None
    cleanup_ok = False
    try:
        if prior_mapping:
            for pseudonym, original in prior_mapping.items():
                vault.seed(pseudonym, original)

        # Pass this module's own references explicitly. Default arguments are
        # bound at import time and would bypass an adapter's test seam.
        core = sanitize_into_vault(
            text,
            vault,
            mode=mode,
            salt=salt,
            scan_leaks=scan_outbound_leaks,
            scan_residual=scan_residual_signals,
        )
        mapping = vault.export_mapping()
        guard_context = OutboundGuardContext(frozenset(vault.trusted_pseudonyms()))
        output = StatelessSanitizeResult(
            sanitized_text=core.sanitized_text,
            mapping=mapping,
            entities=core.entities,
            entity_type_counts=core.entity_type_counts,
            section26=scan_section26(text),
            warnings=core.warnings,
        )
        object.__setattr__(output, "_guard_context", guard_context)
    finally:
        cleanup_ok = _clear_throwaway_vault(vault)

    if not cleanup_ok:
        text = ""
        mode = ""
        salt = ""
        prior_mapping = None
        vault = None
        output = None
        pseudonym = None
        original = None
        core = None
        mapping = None
        guard_context = None
        raise StatelessProcessingError(_SANITIZE_FAILURE_CODE)
    assert output is not None
    return output
