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


class ProviderUnavailable(RuntimeError):
    """Credential or endpoint missing. Raised at construction, never mid-run."""


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
    ):
        base = (os.environ.get(base_url_env) or "").rstrip("/")
        key = os.environ.get(api_key_env) or ""
        if not base:
            raise ProviderUnavailable(f"{base_url_env} is not set")
        if not key:
            raise ProviderUnavailable(f"{api_key_env} is not set")
        if not key.isascii():
            # httpx encodes headers as latin-1; a key carrying Thai text (a note
            # pasted in beside it, say) fails deep inside the transport with a
            # UnicodeEncodeError that names neither the variable nor the cause.
            raise ProviderUnavailable(
                f"{api_key_env} contains non-ASCII characters and cannot be sent "
                "as an HTTP header -- set it to the bare key"
            )
        self._base = base
        self._key = key
        self.model = model
        self.name = name or model
        self._max_tokens = max_tokens

    def __call__(self, system: str, user: str, *, timeout: float = 120.0) -> str:
        def send():
            r = httpx.post(
                f"{self._base}/chat/completions",
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
                },
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""

        return _retrying_post(send)


def build_caller(spec: str):
    """`pathumma`, `dotblue:<model>`, or `thaillm:<model>`."""
    if spec == "pathumma":
        return PathummaCaller()
    if ":" not in spec:
        raise ValueError(f"unknown provider spec {spec!r}")
    provider, model = spec.split(":", 1)
    if provider == "dotblue":
        return OpenAICompatCaller(
            model,
            base_url_env="PSU_DOTBLUE_BASE_URL",
            api_key_env="DOTBLUE_API_KEY",
            name=f"dotblue:{model}",
        )
    if provider == "thaillm":
        return OpenAICompatCaller(
            model,
            base_url_env="THAILLM_BASE_URL",
            api_key_env="THAILLM_API_KEY",
            name=f"thaillm:{model}",
        )
    raise ValueError(f"unknown provider {provider!r}")
