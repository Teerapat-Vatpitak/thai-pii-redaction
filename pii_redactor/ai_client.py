"""AI client integration with multiple provider support and validation."""
from __future__ import annotations

import logging
import os
import time
import uuid
from abc import ABC, abstractmethod

import httpx

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.models import AIResponse, EntityRegistry
from pii_redactor.session_vault import SessionVault, VaultTimeoutError

logger = logging.getLogger(__name__)


DEFAULT_SYSTEM_PROMPT = (
    "คุณเป็น AI assistant ที่มีประสิทธิภาพ "
    "ข้อความที่ได้รับอาจมี token เช่น 1909802000000 หรือ นายสมชาย รักชาติ "
    "ให้เก็บ token เหล่านั้นไว้ในคำตอบโดยไม่แก้ไขหรือแปล"
)


class PreSendValidationError(Exception):
    """Raised when pre-send validation fails."""


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """Send prompt to AI and return response text."""


class OllamaProvider(AIProvider):
    """Local Ollama provider. Configurable model (default: llama3.2)."""

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434"):
        self._model = model
        self._base_url = base_url

    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """Send prompt to Ollama and return response text."""
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["message"]["content"]


class ClaudeProvider(AIProvider):
    """Anthropic Claude API provider. Requires ANTHROPIC_API_KEY env var."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self._model = model
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """Send prompt to Claude and return response text."""
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        resp = httpx.post(self.API_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


class FakeLLMProvider(AIProvider):
    """For testing - returns user prompt unchanged (identity function)."""

    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """Return the user prompt unchanged."""
        return user


def _pseudonym_ranges(text: str, pseudonyms: list[str]) -> list[tuple[int, int]]:
    """
    Character ranges of every known-pseudonym occurrence in text.

    Longest pseudonym first so a shorter pseudonym cannot claim a slice of a
    longer one (same ordering rule as reverse_mapper); ranges never overlap.
    """
    claimed: list[tuple[int, int]] = []

    def _taken(start: int, end: int) -> bool:
        return any(start < ce and end > cs for cs, ce in claimed)

    for p in sorted(pseudonyms, key=len, reverse=True):
        pos = 0
        while (i := text.find(p, pos)) >= 0:
            if not _taken(i, i + len(p)):
                claimed.append((i, i + len(p)))
            pos = i + 1
    return claimed


def _validate_pre_send(text: str, vault: SessionVault) -> None:
    """
    4 checks before sending any prompt to AI.
    Raise PreSendValidationError if any fail.

    Args:
        text: The pseudonymized text to validate
        vault: The session vault containing mappings

    Raises:
        PreSendValidationError: If validation fails
        VaultTimeoutError: If vault has been idle past timeout
    """
    # 1. PII leak check: fp + tb detectors on pseudonymized text
    # (tb catches name/address leaks that regex/checksum miss).
    # Exact-match exclusion against known pseudonyms is not enough for TB:
    # NER span boundaries are fuzzy, so a span can swallow ordinary words
    # around an embedded pseudonym ("หน่อยครับ\nผมชื่อ <pseudonym>") or
    # re-detect a fragment inside one (the district part of a fake address).
    # Excuse a span only when pseudonym occurrences fully account for its
    # PII content; anything else still halts the send.
    known_pseudonyms = set(vault._reverse.keys())
    ordered = sorted((p for p in known_pseudonyms if p), key=len, reverse=True)
    ranges = _pseudonym_ranges(text, ordered)
    real_leaks = []
    for entity in detect_fp(text) + detect_tb(text):
        if entity.original_text in known_pseudonyms:
            continue
        start, end = entity.span
        overlapping = [(cs, ce) for cs, ce in ranges if cs < end and ce > start]
        if overlapping:
            if any(cs <= start and end <= ce for cs, ce in overlapping):
                # Span sits entirely inside one pseudonym occurrence.
                continue
            if entity.redact_type == "TB":
                # Fuzzy NER span straddling pseudonym(s): re-scan only the
                # parts of the span NOT covered by pseudonym occurrences.
                # Positional slicing, not string replace — the span may cover
                # a mere fragment of a pseudonym ('เขตสาทร' out of
                # '556 เขตสาทร'), which whole-string stripping leaves behind.
                # Each segment is scanned SEPARATELY: joining them would
                # fabricate adjacency the text never had (a name cue glued to
                # the word after the pseudonym reads as a fresh name).
                # FP spans are exact and never get this leniency.
                segments = []
                pos = start
                for cs, ce in sorted(overlapping):
                    if cs > pos:
                        segments.append(text[pos:min(cs, end)])
                    pos = max(pos, ce)
                if pos < end:
                    segments.append(text[pos:end])
                if all(
                    not seg.strip() or (not detect_fp(seg) and not detect_tb(seg))
                    for seg in segments
                ):
                    continue
        real_leaks.append(entity)
    if real_leaks:
        raise PreSendValidationError(
            f"PII detected in text before sending to AI: "
            f"{[e.data_type for e in real_leaks]}"
        )

    # 2. Prompt size check (rough heuristic: len/4 ≈ tokens)
    estimated_tokens = len(text) // 4
    if estimated_tokens > 100_000:
        raise PreSendValidationError(
            f"Prompt too large: ~{estimated_tokens} tokens (max 100k)"
        )

    # 3. Vault not cleared (passive check - design note, not a hard failure)
    # Empty vault is OK for first call (no entities yet)

    # 4. Session valid (idle check)
    vault.check_idle()


def _validate_response(response: str, entity_registry: EntityRegistry, vault: SessionVault) -> list[str]:
    """
    Validate AI response. Returns list of warning messages.

    Args:
        response: The AI response text to validate
        entity_registry: The entity registry from the original document
        vault: The session vault containing mappings

    Returns:
        List of warning messages (validation warnings don't halt processing)
    """
    warnings = []

    if not response or not response.strip():
        warnings.append("Empty response from AI")
        return warnings

    # Check pseudonym integrity: each pseudonym should still be in response
    for entity in entity_registry.entities:
        record = vault.get_by_entity_id(entity.entity_id)
        if record is None:
            continue
        if record.pseudonym not in response:
            warnings.append(
                f"Pseudonym missing from response: {entity.data_type} ({entity.entity_id[:8]})"
            )

    return warnings


def send_to_ai(
    pseudonymized_text: str,
    entity_registry: EntityRegistry,
    vault: SessionVault,
    provider: AIProvider,
    *,
    system_prompt: str | None = None,
    max_retries: int = 3,
) -> AIResponse:
    """
    Validate, send to AI, validate response, with retry/rollback on failure.

    Args:
        pseudonymized_text: The pseudonymized text to send to AI
        entity_registry: The entity registry from detection
        vault: The session vault with pseudonym mappings
        provider: The AI provider to use
        system_prompt: Optional custom system prompt (default: Thai instruction)
        max_retries: Number of attempts for transient errors — timeouts,
            network errors, HTTP 429/5xx (default: 3). Other HTTP 4xx are
            fatal: vault is rolled back and the error re-raised immediately.

    Returns:
        AIResponse with text, request_id, and latency

    Raises:
        PreSendValidationError: If pre-send validation fails
        VaultTimeoutError: If vault has timed out
        RuntimeError: If all retries are exhausted
    """
    system = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Pre-send validation
    _validate_pre_send(pseudonymized_text, vault)

    # Snapshot for rollback
    snapshot = vault.snapshot()

    # Retry loop
    last_error = None
    for attempt in range(max_retries):
        try:
            start_time = time.monotonic()
            response_text = provider.complete(system, pseudonymized_text, timeout=60.0)
            latency = time.monotonic() - start_time

            # Response validation (warnings only, don't halt)
            warnings = _validate_response(response_text, entity_registry, vault)
            for warning in warnings:
                logger.warning("AI response validation: %s", warning)

            return AIResponse(
                text=response_text,
                request_id=str(uuid.uuid4()),
                latency=latency,
            )

        except httpx.HTTPStatusError as e:
            # Only rate limits and server errors are transient; other 4xx
            # (auth, bad request) will never succeed on retry.
            status = e.response.status_code
            if status != 429 and status < 500:
                vault.restore(snapshot)
                raise
            last_error = e
            if attempt < max_retries - 1:
                backoff = 2 ** attempt  # 1s, 2s, 4s
                time.sleep(backoff)
            continue

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_error = e
            if attempt < max_retries - 1:
                backoff = 2 ** attempt  # 1s, 2s, 4s
                time.sleep(backoff)
            continue

        except Exception:
            # Fatal error - rollback and re-raise
            vault.restore(snapshot)
            raise

    # All retries exhausted - rollback
    vault.restore(snapshot)
    raise RuntimeError(
        f"AI provider failed after {max_retries} attempts: {last_error}"
    )
