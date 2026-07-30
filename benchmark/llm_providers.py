"""Chat callers for the LLM-as-detector baseline.

Each caller is a plain `(system, user) -> str` function object. They exist here
rather than reusing `pii_redactor.ai_client` on purpose: that module's providers
are part of the product's send path and carry the pre-send leak guard, vault
rollback and retry policy that belong to a real user request. A benchmark caller
must do none of that -- it sends gold text verbatim and returns raw output.
"""

from __future__ import annotations

import os
import time

import httpx

from pii_redactor.openai_compat import (
    chat_completions_url,
    extract_chat_content,
    validate_header_value,
)


class ProviderUnavailable(RuntimeError):
    """Credential or endpoint missing. Raised at construction, never mid-run."""


def provider_request_config(spec: str) -> dict:
    """Return the safe request settings that affect model output."""
    common = {
        "temperature": 0.0,
        "stream": False,
    }
    if spec == "pathumma":
        return {
            "provider_spec": spec,
            "protocol": "aiforthai-form",
            "model": "pathumma",
            "max_output_tokens": 1024,
            "extra_body": {},
            **common,
        }
    if spec == "tokenmind":
        return {
            "provider_spec": spec,
            "protocol": "openai-compatible",
            "model": "thaillm-8b",
            "max_output_tokens": 4096,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            **common,
        }
    if ":" not in spec:
        raise ValueError(f"unknown provider spec {spec!r}")
    provider, model = spec.split(":", 1)
    if provider not in {"dotblue", "thaillm"} or not model:
        raise ValueError(f"unknown provider {provider!r}")
    return {
        "provider_spec": spec,
        "protocol": "openai-compatible",
        "model": model,
        "max_output_tokens": 4096,
        "extra_body": {},
        **common,
    }


def _retrying_post(send, *, attempts: int = 3):
    """Retry transient failures only (timeout, network, 429, 5xx)."""
    delay = 2.0
    last: Exception | None = None
    for i in range(attempts):
        try:
            return send()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 and exc.response.status_code < 500:
                raise
            last = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
        if i < attempts - 1:
            time.sleep(delay)
            delay *= 2
    raise last  # type: ignore[misc]


class PathummaCaller:
    """Pathumma LLM (NECTEC, AI for Thai).

    Form-encoded body only -- a JSON body draws a 422 that reads like a naming
    bug but is a content-type bug (proven against the live endpoint 2026-07-21).
    """

    name = "pathumma"
    API_URL = "https://api.aiforthai.in.th/textqa/completion"

    def __init__(self, model: str = "pathumma", *, max_tokens: int = 1024):
        self._key = os.environ.get("AIFORTHAI_API_KEY", "")
        if not self._key:
            raise ProviderUnavailable("AIFORTHAI_API_KEY is not set")
        self.model = model
        self._max_tokens = max_tokens

    def __call__(self, system: str, user: str, *, timeout: float = 120.0) -> str:
        def send():
            r = httpx.post(
                self.API_URL,
                data={
                    "instruction": user,
                    "system_prompt": system,
                    "max_new_tokens": self._max_tokens,
                    "temperature": 0.0,
                },
                headers={"Apikey": self._key, "X-lib": "aiguard-benchmark"},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["content"]

        return _retrying_post(send)


class OpenAICompatCaller:
    """Any OpenAI-compatible /chat/completions endpoint.

    Covers the PSU gateway at ai.psu.blue and anything else exposing the same
    shape, including a Thai LLM endpoint supplied through THAILLM_BASE_URL.
    """

    def __init__(
        self,
        model: str,
        *,
        base_url_env: str,
        api_key_env: str,
        name: str | None = None,
        max_tokens: int = 4096,
        extra_body: dict | None = None,
    ):
        base = (os.environ.get(base_url_env) or "").rstrip("/")
        key = os.environ.get(api_key_env) or ""
        if not base:
            raise ProviderUnavailable(f"{base_url_env} is not set")
        try:
            # Intentionally stricter than the old ASCII-only check: also
            # rejects CR/LF, other control characters, and leading/trailing
            # whitespace (a key pasted with a stray newline used to reach
            # httpx and fail deep inside the transport instead of here).
            key = validate_header_value(key, env_name=api_key_env)
        except ValueError as exc:
            raise ProviderUnavailable(str(exc)) from None
        self._url = chat_completions_url(base)
        self._key = key
        self.model = model
        self.name = name or model
        self._max_tokens = max_tokens
        self._extra_body = extra_body or {}

    def __call__(self, system: str, user: str, *, timeout: float = 120.0) -> str:
        def send():
            r = httpx.post(
                self._url,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,
                    "max_tokens": self._max_tokens,
                    # The PSU gateway answers text/event-stream by DEFAULT, so
                    # without this every response arrives as SSE chunks and
                    # r.json() dies on "data: " -- which looks like an auth or
                    # model error and is neither.
                    "stream": False,
                    # Gateway-specific knobs (e.g. vLLM's chat_template_kwargs
                    # that turns a reasoning model's <think> block off).
                    **self._extra_body,
                },
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=timeout,
            )
            r.raise_for_status()
            content, _finish = extract_chat_content(r.json())
            # Benchmark policy: empty/null content is a countable result (zero
            # predictions), not an error -- the product provider decides otherwise.
            return content or ""

        return _retrying_post(send)


def build_caller(spec: str):
    """`pathumma`, `tokenmind`, `dotblue:<model>`, or `thaillm:<model>`."""
    config = provider_request_config(spec)
    if spec == "pathumma":
        return PathummaCaller(
            model=config["model"],
            max_tokens=config["max_output_tokens"],
        )
    if spec == "tokenmind":
        # The hackathon LiteLLM gateway (TOKENMIND_BASE_URL), NOT the
        # thaillm.or.th service behind THAILLM_BASE_URL -- different host,
        # different model list; conflating them once already produced a wrong
        # "the model does not exist" conclusion. Model fixed to thaillm-8b and
        # thinking disabled to match the product's TokenmindProvider config,
        # so the benchmark measures the model as it would actually be used.
        return OpenAICompatCaller(
            config["model"],
            base_url_env="TOKENMIND_BASE_URL",
            api_key_env="TOKENMIND_API_KEY",
            name="tokenmind:thaillm-8b",
            max_tokens=config["max_output_tokens"],
            extra_body=config["extra_body"],
        )
    provider, model = spec.split(":", 1)
    if provider == "dotblue":
        return OpenAICompatCaller(
            model,
            base_url_env="PSU_DOTBLUE_BASE_URL",
            api_key_env="DOTBLUE_API_KEY",
            name=f"dotblue:{model}",
            max_tokens=config["max_output_tokens"],
        )
    if provider == "thaillm":
        return OpenAICompatCaller(
            model,
            base_url_env="THAILLM_BASE_URL",
            api_key_env="THAILLM_API_KEY",
            name=f"thaillm:{model}",
            max_tokens=config["max_output_tokens"],
        )
    raise ValueError(f"unknown provider {provider!r}")
