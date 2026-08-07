"""Contract tests for the shared protected-provider attempt policy."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from pii_redactor import ai_client
from pii_redactor.ai_client import (
    AIProvider,
    ProviderCallError,
    ProviderProtocolError,
    complete_provider_with_retry_policy,
)
from pii_redactor.leak_guard import OutboundPolicyError

MASKED_TEXT = "synthetic masked text"
SYSTEM_PROMPT = "synthetic system prompt"


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://provider.invalid/v1/complete")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        "synthetic provider status",
        request=request,
        response=response,
    )


def _timeout_error() -> httpx.ReadTimeout:
    return httpx.ReadTimeout(
        "synthetic timeout",
        request=httpx.Request("POST", "https://provider.invalid/v1/complete"),
    )


def _network_error() -> httpx.ConnectError:
    return httpx.ConnectError(
        "synthetic network failure",
        request=httpx.Request("POST", "https://provider.invalid/v1/complete"),
    )


class _SequenceProvider(AIProvider):
    def __init__(self, outcomes: list[Callable[[], object]]):
        self._outcomes = outcomes
        self.calls: list[tuple[str, str, float]] = []

    def complete(self, system: str, user: str, *, timeout: float = 30.0) -> str:
        self.calls.append((system, user, timeout))
        outcome = self._outcomes[len(self.calls) - 1]()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


@pytest.mark.parametrize(
    "failure_factory",
    [
        _timeout_error,
        _network_error,
        lambda: _http_status_error(429),
        lambda: _http_status_error(500),
        lambda: _http_status_error(599),
    ],
    ids=["timeout", "network", "http-429", "http-500", "http-599"],
)
def test_shared_policy_retries_only_locked_transient_failures(monkeypatch, failure_factory):
    provider = _SequenceProvider([failure_factory, failure_factory, lambda: MASKED_TEXT])
    checks: list[int] = []
    delays: list[float] = []
    monkeypatch.setattr(ai_client, "_sleep", delays.append)

    response, _latency, attempts = complete_provider_with_retry_policy(
        provider,
        SYSTEM_PROMPT,
        MASKED_TEXT,
        before_attempt=checks.append,
    )

    assert response == MASKED_TEXT
    assert attempts == 3
    assert checks == [0, 1, 2]
    assert delays == [1, 2]
    assert provider.calls == [
        (SYSTEM_PROMPT, MASKED_TEXT, 60.0),
        (SYSTEM_PROMPT, MASKED_TEXT, 60.0),
        (SYSTEM_PROMPT, MASKED_TEXT, 60.0),
    ]


@pytest.mark.parametrize(
    ("outcome", "category", "status_code"),
    [
        (lambda: _http_status_error(400), "http_status", 400),
        (lambda: _http_status_error(408), "http_status", 408),
        (
            lambda: ProviderProtocolError("synthetic malformed response"),
            "malformed",
            None,
        ),
        (lambda: b"not text", "non_text", None),
        (
            lambda: RuntimeError("synthetic provider failure"),
            "failed",
            None,
        ),
    ],
    ids=["http-400", "http-408", "malformed", "non-text", "other"],
)
def test_shared_policy_does_not_retry_nontransient_failures(
    monkeypatch,
    outcome,
    category,
    status_code,
):
    provider = _SequenceProvider([outcome])
    checks: list[int] = []
    delays: list[float] = []
    monkeypatch.setattr(ai_client, "_sleep", delays.append)

    with pytest.raises(ProviderCallError) as excinfo:
        complete_provider_with_retry_policy(
            provider,
            SYSTEM_PROMPT,
            MASKED_TEXT,
            before_attempt=checks.append,
        )

    assert excinfo.value.category == category
    assert excinfo.value.status_code == status_code
    assert excinfo.value.attempts == 1
    assert checks == [0]
    assert delays == []
    assert len(provider.calls) == 1


def test_shared_policy_rechecks_outbound_policy_before_actual_retry(monkeypatch):
    provider = _SequenceProvider(
        [
            lambda: _http_status_error(503),
            lambda: pytest.fail("blocked retry must not invoke provider"),
        ]
    )
    checks: list[int] = []
    delays: list[float] = []

    def changing_policy(attempt: int) -> None:
        checks.append(attempt)
        if attempt == 1:
            raise OutboundPolicyError(
                ["THAI_ID"],
                policy_categories=["structured"],
            )

    monkeypatch.setattr(ai_client, "_sleep", delays.append)

    with pytest.raises(OutboundPolicyError):
        complete_provider_with_retry_policy(
            provider,
            SYSTEM_PROMPT,
            MASKED_TEXT,
            before_attempt=changing_policy,
        )

    assert checks == [0, 1]
    assert delays == [1]
    assert provider.calls == [(SYSTEM_PROMPT, MASKED_TEXT, 60.0)]


def test_shared_policy_ignores_legacy_provider_retry_capability(monkeypatch):
    class LegacyCapabilityProvider(_SequenceProvider):
        @property
        def handles_retries(self):
            raise AssertionError("shared orchestration must not inspect retry capability")

    provider = LegacyCapabilityProvider(
        [
            _timeout_error,
            _network_error,
            lambda: MASKED_TEXT,
        ]
    )
    delays: list[float] = []
    monkeypatch.setattr(ai_client, "_sleep", delays.append)

    response, _latency, attempts = complete_provider_with_retry_policy(
        provider,
        SYSTEM_PROMPT,
        MASKED_TEXT,
        before_attempt=lambda _attempt: None,
    )

    assert response == MASKED_TEXT
    assert attempts == 3
    assert delays == [1, 2]
    assert len(provider.calls) == 3


def test_shared_policy_never_exceeds_three_attempts(monkeypatch):
    provider = _SequenceProvider([_timeout_error for _ in range(9)])
    delays: list[float] = []
    monkeypatch.setattr(ai_client, "_sleep", delays.append)

    with pytest.raises(ProviderCallError) as excinfo:
        complete_provider_with_retry_policy(
            provider,
            SYSTEM_PROMPT,
            MASKED_TEXT,
            before_attempt=lambda _attempt: None,
            max_attempts=9,
        )

    assert excinfo.value.category == "timeout"
    assert excinfo.value.attempts == 3
    assert delays == [1, 2]
    assert len(provider.calls) == 3


def test_shared_policy_does_not_call_provider_after_initial_validation_failure(monkeypatch):
    provider = _SequenceProvider([lambda: pytest.fail("provider must not run")])
    delays: list[float] = []
    monkeypatch.setattr(ai_client, "_sleep", delays.append)

    def reject(_attempt: int) -> None:
        raise OutboundPolicyError(
            ["THAI_ID"],
            policy_categories=["structured"],
        )

    with pytest.raises(OutboundPolicyError):
        complete_provider_with_retry_policy(
            provider,
            SYSTEM_PROMPT,
            MASKED_TEXT,
            before_attempt=reject,
        )

    assert provider.calls == []
    assert delays == []


def test_shared_policy_sleep_failure_is_not_retried(monkeypatch):
    provider = _SequenceProvider(
        [
            _timeout_error,
            lambda: pytest.fail("sleep failure must stop orchestration"),
        ]
    )

    def fail_sleep(_seconds: float) -> None:
        raise RuntimeError("synthetic sleep failure")

    monkeypatch.setattr(ai_client, "_sleep", fail_sleep)

    with pytest.raises(ProviderCallError) as excinfo:
        complete_provider_with_retry_policy(
            provider,
            SYSTEM_PROMPT,
            MASKED_TEXT,
            before_attempt=lambda _attempt: None,
        )

    assert excinfo.value.category == "failed"
    assert excinfo.value.attempts == 1
    assert len(provider.calls) == 1
