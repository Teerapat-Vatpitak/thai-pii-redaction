"""AI client integration with multiple provider support and validation."""

from __future__ import annotations

import logging
import math
import os
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from types import MappingProxyType

import httpx

from pii_redactor.leak_guard import (
    OutboundPolicyError,
    enforce_outbound_policy,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.models import AIResponse, EntityRegistry
from pii_redactor.openai_compat import (
    chat_completions_url,
    extract_chat_content,
    is_sse_response,
    validate_header_value,
)
from pii_redactor.safe_errors import discard_exception_graph
from pii_redactor.session_vault import SessionVault, VaultTimeoutError

logger = logging.getLogger(__name__)

# Module-level sleep function for testability (can be monkeypatched)
_sleep = time.sleep

DEFAULT_SYSTEM_PROMPT = (
    "คุณเป็น AI assistant ที่มีประสิทธิภาพ "
    "ข้อความที่ได้รับอาจมี token เช่น 1909802000000 หรือ นายสมชาย รักชาติ "
    "ให้เก็บ token เหล่านั้นไว้ในคำตอบโดยไม่แก้ไขหรือแปล"
)


class PreSendValidationError(Exception):
    """Raised when pre-send validation fails."""

    def __init__(self, message: str, *, code: str = "validation_failed"):
        self.code = code
        super().__init__(message)


class ProviderCallError(RuntimeError):
    """A provider failure reduced to fixed, non-sensitive metadata."""

    def __init__(
        self,
        *,
        category: str,
        error_type: str,
        status_code: int | None = None,
        attempts: int = 1,
    ):
        self.category = category
        self.error_type = error_type
        self.status_code = status_code
        self.attempts = attempts
        super().__init__("AI provider call failed")


class _PreSendAttemptError(RuntimeError):
    """Fixed internal signal for a failed per-attempt safety check."""

    def __init__(self, code: str, attempt: int):
        self.code = code
        self.attempt = attempt
        super().__init__("pre-send validation failed")


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


class PathummaProvider(AIProvider):
    """Pathumma LLM (NECTEC, AI for Thai). Requires AIFORTHAI_API_KEY env var.

    Wire shape proven against the live endpoint on 2026-07-21: the API accepts
    form-encoded bodies ONLY — a JSON body draws a 422 "Field required" that
    looks like a naming bug but is a content-type bug. Same Apikey header
    convention as detectors/tner_client.py, same env var, one credential for
    the whole AI for Thai surface.
    """

    API_URL = "https://api.aiforthai.in.th/textqa/completion"

    def __init__(self):
        self._api_key = os.environ.get("AIFORTHAI_API_KEY", "")
        if not self._api_key:
            raise ValueError("AIFORTHAI_API_KEY environment variable not set")

    def complete(self, system: str, user: str, *, timeout: float = 60.0) -> str:
        """Send prompt to Pathumma LLM and return response text."""
        headers = {"Apikey": self._api_key, "X-lib": "aiguard"}
        data = {
            "instruction": user,
            "system_prompt": system,
            "max_new_tokens": 1024,
            "temperature": 0.4,
        }
        resp = httpx.post(self.API_URL, data=data, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["content"]


class ProviderProtocolError(ValueError):
    """A 200 response that violates the provider protocol.

    Subclasses ValueError so app/server.py's existing malformed-response
    handler turns it into 502 and app/worker/handler.py into provider_failed
    without either surface changing. The message carries a category only --
    never the response body (VAULT-4: a body can contain anything).
    """


class TokenmindProvider(AIProvider):
    """Official AIFT hackathon LiteLLM gateway (OpenAI-compatible).

    Requires TOKENMIND_BASE_URL (must end in /v1; https unless
    TOKENMIND_ALLOW_HTTP=1) and TOKENMIND_API_KEY. Model is hardcoded: the
    gateway has exactly one text model, and an env override would invite
    pointing it at the ptm-tts-1/ptm-asr-1 audio models. Spec:
    docs/superpowers/specs/2026-07-27-tokenmind-provider-design.md.
    """

    MODEL = "thaillm-8b"

    def __init__(self):
        base = (os.environ.get("TOKENMIND_BASE_URL") or "").strip()
        if not base:
            raise ValueError("TOKENMIND_BASE_URL environment variable not set")
        if not base.rstrip("/").endswith("/v1"):
            raise ValueError(
                "TOKENMIND_BASE_URL must include the /v1 suffix, "
                "e.g. https://tokenmind.pathumma.in.th/v1"
            )
        if not base.startswith("https://") and os.environ.get("TOKENMIND_ALLOW_HTTP") != "1":
            raise ValueError(
                "TOKENMIND_BASE_URL must be https "
                "(set TOKENMIND_ALLOW_HTTP=1 only for local development)"
            )
        self._url = chat_completions_url(base)
        self._api_key = validate_header_value(
            os.environ.get("TOKENMIND_API_KEY") or "", env_name="TOKENMIND_API_KEY"
        )

    def _client(self) -> httpx.Client:
        return httpx.Client()

    def _validated_content(self, resp: httpx.Response) -> str:
        if is_sse_response(resp.headers.get("content-type")):
            raise ProviderProtocolError(
                "provider answered with an event stream despite stream=false"
            )
        try:
            data = resp.json()
        except ValueError:
            raise ProviderProtocolError("provider response is not JSON") from None
        try:
            content, finish = extract_chat_content(data)
        except ValueError:
            raise ProviderProtocolError(
                "provider response missing chat completion content"
            ) from None
        if not content or not content.strip():
            raise ProviderProtocolError("provider returned empty content")
        if finish != "stop":
            raise ProviderProtocolError("provider stopped for a non-stop finish_reason")
        lowered = content.lower()
        if any(
            marker in lowered
            for marker in ("<think>", "</think>", "&lt;think&gt;", "&lt;/think&gt;")
        ):
            # enable_thinking was ignored upstream. Restoring tokens inside a
            # thought block would write real PII into it -- refuse instead.
            raise ProviderProtocolError("provider response contains reasoning-block markers")
        return content

    def complete(self, system: str, user: str, *, timeout: float = 60.0) -> str:
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        with self._client() as client:
            resp = client.post(self._url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return self._validated_content(resp)


class FakeLLMProvider(AIProvider):
    """For testing - returns user prompt unchanged (identity function)."""

    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        """Return the user prompt unchanged."""
        return user


def _provider_failure_metadata(
    error: Exception,
) -> tuple[str, str, int | None]:
    """Reduce an arbitrary provider exception without retaining it."""
    try:
        if isinstance(error, httpx.HTTPStatusError):
            status = getattr(getattr(error, "response", None), "status_code", None)
            if type(status) is int and 100 <= status <= 599:
                return "http_status", "HTTPStatusError", status
            return "http", "HTTPError", None
        if isinstance(error, httpx.TimeoutException):
            return "timeout", "TimeoutException", None
        if isinstance(error, httpx.NetworkError):
            return "network", "NetworkError", None
        if isinstance(error, httpx.HTTPError):
            return "http", "HTTPError", None
        if isinstance(error, IndexError):
            return "malformed", "IndexError", None
        if isinstance(error, KeyError):
            return "malformed", "KeyError", None
        if isinstance(error, TypeError):
            return "malformed", "TypeError", None
        if isinstance(error, ValueError):
            return "malformed", "ValueError", None
    except Exception:
        # Provider exception objects are untrusted too. Metadata reduction must
        # never create a second exception that reconnects the raw error graph.
        return "failed", "ProviderError", None
    return "failed", "ProviderError", None


def _invoke_provider_once(
    provider: AIProvider,
    system: str,
    user: str,
    timeout: float | None,
) -> tuple[str | None, tuple[str, str, int | None] | None]:
    """Call one provider while containing its raw exception and traceback."""
    try:
        if timeout is None:
            response = provider.complete(system, user)
        else:
            response = provider.complete(system, user, timeout=timeout)
    except Exception as error:
        failure = _provider_failure_metadata(error)
        discard_exception_graph(error)
        error = None
        provider = None
        system = ""
        user = ""
        timeout = None
        return None, failure
    if not isinstance(response, str):
        return None, ("non_text", "TypeError", None)
    return response, None


def complete_provider_call(
    provider: AIProvider,
    system: str,
    user: str,
    *,
    timeout: float | None = None,
) -> str:
    """Call a provider and expose only a fixed safe failure."""
    response, failure = _invoke_provider_once(provider, system, user, timeout)
    if failure is not None:
        category, error_type, status_code = failure
        # Do not retain provider inputs in this exception's raising frame.
        provider = None
        system = ""
        user = ""
        raise ProviderCallError(
            category=category,
            error_type=error_type,
            status_code=status_code,
        )
    assert response is not None
    return response


def _provider_failure_is_retryable(category: str, status_code: int | None) -> bool:
    if category in {"timeout", "network"}:
        return True
    return category == "http_status" and (
        status_code == 429 or (status_code is not None and status_code >= 500)
    )


def complete_provider_with_retry_policy(
    provider: AIProvider,
    system: str,
    user: str,
    *,
    before_attempt: Callable[[int], None],
    max_attempts: int = 3,
) -> tuple[str, float, int]:
    """Run the shared three-attempt policy with a fresh safety gate each time."""
    effective_attempts = 3
    if type(max_attempts) is int:
        effective_attempts = min(3, max(1, max_attempts))
    for attempt in range(effective_attempts):
        before_attempt(attempt)
        started = time.monotonic()
        try:
            response = complete_provider_call(
                provider,
                system,
                user,
                timeout=60.0,
            )
        except ProviderCallError as error:
            category = error.category if type(error.category) is str else "failed"
            error_type = error.error_type if type(error.error_type) is str else "ProviderError"
            status_code = error.status_code if type(error.status_code) is int else None
            retryable = _provider_failure_is_retryable(category, status_code)
            discard_exception_graph(error)
            if retryable and attempt + 1 < effective_attempts:
                try:
                    _sleep(2**attempt)
                except Exception as sleep_error:
                    discard_exception_graph(sleep_error)
                    provider = None
                    system = ""
                    user = ""
                    before_attempt = None
                    raise ProviderCallError(
                        category="failed",
                        error_type="ProviderError",
                        attempts=attempt + 1,
                    ) from None
                continue
            attempts = attempt + 1
            provider = None
            system = ""
            user = ""
            before_attempt = None
            raise ProviderCallError(
                category=category,
                error_type=error_type,
                status_code=status_code,
                attempts=attempts,
            ) from None
        return response, time.monotonic() - started, attempt + 1

    provider = None
    system = ""
    user = ""
    before_attempt = None
    raise ProviderCallError(
        category="failed",
        error_type="ProviderError",
        attempts=0,
    )


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
    # 1. Fail closed on every outbound residual class. Pass this module's
    # references explicitly so callers can substitute the security scans here.
    residual_failure = False
    try:
        enforce_outbound_policy(
            text,
            guard_context=vault,
            scan_leaks=scan_outbound_leaks,
            scan_residual=scan_residual_signals,
        )
    except OutboundPolicyError as error:
        discard_exception_graph(error)
        residual_failure = True
    if residual_failure:
        text = ""
        vault = None
        raise PreSendValidationError(
            "outbound residual detected",
            code="outbound_residual",
        )

    # 2. Prompt size check (rough heuristic: len/4 ≈ tokens)
    estimated_tokens = len(text) // 4
    if estimated_tokens > 100_000:
        text = ""
        vault = None
        raise PreSendValidationError(
            f"Prompt too large: ~{estimated_tokens} tokens (max 100k)",
            code="prompt_too_large",
        )

    # 3. Vault not cleared (passive check - design note, not a hard failure)
    # Empty vault is OK for first call (no entities yet)

    # 4. Session valid (idle check)
    timeout_failure = False
    try:
        vault.check_idle()
    except VaultTimeoutError as error:
        discard_exception_graph(error)
        timeout_failure = True
    if timeout_failure:
        text = ""
        vault = None
        raise VaultTimeoutError("Session vault idle timeout")


def _raise_pre_send_failure(code: str) -> None:
    """Raise one fixed error after the caller has dropped sensitive locals."""
    if code == "vault_timeout":
        raise VaultTimeoutError("Session vault idle timeout")
    if code == "prompt_too_large":
        raise PreSendValidationError("Prompt too large", code=code)
    if code == "outbound_residual":
        raise PreSendValidationError("outbound residual detected", code=code)
    raise PreSendValidationError("pre-send validation failed")


def _validate_response(
    response: str, entity_registry: EntityRegistry, vault: SessionVault
) -> list[str]:
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


def _restore_snapshot_after_failure(vault: SessionVault, snapshot: dict) -> None:
    """Attempt rollback without allowing its exception graph to escape."""
    try:
        vault.restore(snapshot)
    except Exception as error:
        discard_exception_graph(error)


def _send_to_ai(
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
            fatal: vault is rolled back and a safe provider error is raised.

    Returns:
        AIResponse with text, request_id, and latency

    Raises:
        PreSendValidationError: If pre-send validation fails
        VaultTimeoutError: If vault has timed out
        ProviderCallError: If a provider call fails or retries are exhausted
    """
    system = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Snapshot for rollback
    snapshot = vault.snapshot()

    def validate_attempt(attempt: int) -> None:
        validation_failure = None
        try:
            _validate_pre_send(pseudonymized_text, vault)
        except PreSendValidationError as error:
            validation_failure = (
                error.code
                if error.code in {"outbound_residual", "prompt_too_large"}
                else "validation_failed"
            )
            discard_exception_graph(error)
        except VaultTimeoutError as error:
            discard_exception_graph(error)
            validation_failure = "vault_timeout"
        except Exception as error:
            discard_exception_graph(error)
            validation_failure = "validation_failed"
        if validation_failure is not None:
            raise _PreSendAttemptError(validation_failure, attempt) from None

    try:
        response_text, latency, attempts_used = complete_provider_with_retry_policy(
            provider,
            system,
            pseudonymized_text,
            before_attempt=validate_attempt,
            max_attempts=max_retries,
        )
    except _PreSendAttemptError as error:
        validation_failure = error.code
        failed_attempt = error.attempt
        discard_exception_graph(error)
        if failed_attempt > 0:
            _restore_snapshot_after_failure(vault, snapshot)
        provider = None
        vault = None
        snapshot = None
        entity_registry = None
        pseudonymized_text = ""
        system_prompt = None
        system = ""
        response_text = None
        validate_attempt = None
        _raise_pre_send_failure(validation_failure)
    except ProviderCallError as error:
        category = error.category
        error_type = error.error_type
        status_code = error.status_code
        attempts_used = error.attempts
        discard_exception_graph(error)
        if type(attempts_used) is int and attempts_used > 0:
            _restore_snapshot_after_failure(vault, snapshot)
        provider = None
        vault = None
        snapshot = None
        entity_registry = None
        pseudonymized_text = ""
        system_prompt = None
        system = ""
        response_text = None
        validate_attempt = None
        raise ProviderCallError(
            category=category,
            error_type=error_type,
            status_code=status_code,
            attempts=attempts_used,
        ) from None

    response_failure = False
    warnings = None
    warning = None
    result = None
    try:
        # Response validation warnings do not halt normal processing.
        warnings = _validate_response(response_text, entity_registry, vault)
        for warning in warnings:
            logger.warning("AI response validation: %s", warning)

        result = AIResponse(
            text=response_text,
            request_id=str(uuid.uuid4()),
            latency=latency,
        )
    except Exception as error:
        discard_exception_graph(error)
        response_failure = True
    if response_failure:
        # Tail failures are fatal, not transient provider failures. Preserve
        # the pre-call rollback contract without entering the retry path.
        _restore_snapshot_after_failure(vault, snapshot)

        provider = None
        vault = None
        snapshot = None
        entity_registry = None
        pseudonymized_text = ""
        system_prompt = None
        system = ""
        response_text = None
        warnings = None
        warning = None
        latency = None
        result = None
        validate_attempt = None
        raise ProviderCallError(
            category="failed",
            error_type="ProviderError",
            attempts=attempts_used,
        )
    assert result is not None
    return result


def _public_send_failure_metadata(
    error: Exception,
) -> tuple[str, str, str, int | None, int]:
    """Reduce an internal send failure to fixed public metadata."""
    try:
        if type(error) is PreSendValidationError:
            code = (
                error.code
                if type(error.code) is str
                and error.code
                in {
                    "outbound_residual",
                    "prompt_too_large",
                    "validation_failed",
                }
                else "validation_failed"
            )
            return "pre_send", code, "", None, 0
        if type(error) is VaultTimeoutError:
            return "vault_timeout", "", "", None, 0
        if type(error) is ProviderCallError:
            categories = {
                "failed",
                "http",
                "http_status",
                "malformed",
                "network",
                "non_text",
                "timeout",
            }
            error_types = {
                "HTTPError",
                "HTTPStatusError",
                "IndexError",
                "KeyError",
                "NetworkError",
                "ProviderError",
                "TimeoutException",
                "TypeError",
                "ValueError",
            }
            category = error.category
            error_type = error.error_type
            if (
                type(category) is not str
                or category not in categories
                or type(error_type) is not str
                or error_type not in error_types
            ):
                return "provider", "failed", "ProviderError", None, 0
            status_code = error.status_code if type(error.status_code) is int else None
            if category != "http_status" or status_code is None or not 100 <= status_code <= 599:
                status_code = None
            attempts = error.attempts if type(error.attempts) is int else 0
            if not 1 <= attempts <= 3:
                attempts = 0
            return "provider", category, error_type, status_code, attempts
    except Exception as metadata_error:
        discard_exception_graph(metadata_error)
    return "provider", "failed", "ProviderError", None, 0


def send_to_ai(
    pseudonymized_text: str,
    entity_registry: EntityRegistry,
    vault: SessionVault,
    provider: AIProvider,
    *,
    system_prompt: str | None = None,
    max_retries: int = 3,
) -> AIResponse:
    """Run a protected completion without exposing internal exception graphs."""
    failure = ("provider", "failed", "ProviderError", None, 0)
    try:
        return _send_to_ai(
            pseudonymized_text,
            entity_registry,
            vault,
            provider,
            system_prompt=system_prompt,
            max_retries=max_retries,
        )
    except Exception as error:
        failure = _public_send_failure_metadata(error)
        discard_exception_graph(error)

    provider = None
    vault = None
    entity_registry = None
    pseudonymized_text = ""
    system_prompt = None
    max_retries = 0

    kind, first, second, status_code, attempts = failure
    if kind == "pre_send":
        _raise_pre_send_failure(first)
    if kind == "vault_timeout":
        _raise_pre_send_failure("vault_timeout")
    raise ProviderCallError(
        category=first,
        error_type=second,
        status_code=status_code,
        attempts=attempts,
    )


# Single registry -- app/server.py and app/worker/handler.py used to carry
# byte-identical copies of this dict; the fourth copy was a comment and the
# third a dropdown. Surfaces take a snapshot via get_provider_factories() so
# a future hosted surface can pass an allowlist (public deployments must not
# grow ollama/claude/fake by accident).
PROVIDER_FACTORIES: MappingProxyType[str, Callable[[], AIProvider]] = MappingProxyType(
    {
        "fake": FakeLLMProvider,
        "pathumma": PathummaProvider,
        "tokenmind": TokenmindProvider,
        "ollama": OllamaProvider,
        "claude": ClaudeProvider,
    }
)


def get_provider_factories(
    *, allowed: Iterable[str] | None = None
) -> dict[str, Callable[[], AIProvider]]:
    """Snapshot of the registry, optionally filtered by an allowlist.

    An unknown name in `allowed` raises instead of being dropped: a typo in a
    deployment allowlist must fail the boot, not silently remove a provider.
    """
    if allowed is None:
        return dict(PROVIDER_FACTORIES)
    names = list(allowed)
    unknown = sorted(set(names) - set(PROVIDER_FACTORIES))
    if unknown:
        raise ValueError(f"unknown provider names in allowlist: {unknown}")
    return {name: PROVIDER_FACTORIES[name] for name in names}
