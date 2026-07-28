"""Wire-level primitives for OpenAI-compatible /chat/completions endpoints.

Mechanics only, shared between the product provider (pii_redactor/ai_client.py)
and the benchmark caller (benchmark/llm_providers.py). Policy stays with each
caller: retry ownership, temperature/model/token limits, and whether empty
content is data (benchmark) or an error (product) are deliberately NOT here.
"""

from __future__ import annotations


def validate_header_value(value: str, *, env_name: str) -> str:
    """Return `value` if it can travel as an HTTP header; raise ValueError naming `env_name`.

    httpx encodes headers as latin-1 and rejects CR/LF; a key pasted with a
    stray newline or Thai note fails deep inside the transport with a message
    that names neither the variable nor the cause. Reject here, by name.
    """
    if not value:
        raise ValueError(f"{env_name} is not set")
    if value != value.strip():
        raise ValueError(f"{env_name} has leading/trailing whitespace -- set it to the bare key")
    if not value.isascii():
        raise ValueError(
            f"{env_name} contains non-ASCII characters and cannot be sent as an HTTP header"
        )
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(
            f"{env_name} contains control characters and cannot be sent as an HTTP header"
        )
    return value


def chat_completions_url(base_url: str) -> str:
    """Join a base URL (`.../v1`) with the chat-completions path."""
    return base_url.rstrip("/") + "/chat/completions"


def is_sse_response(content_type: str | None) -> bool:
    """True when a content-type header denotes an SSE stream (despite stream=false)."""
    if not content_type:
        return False
    return content_type.split(";")[0].strip().lower() == "text/event-stream"


def extract_chat_content(payload: object) -> tuple[str | None, str | None]:
    """Structural extraction of (content, finish_reason) from a chat envelope.

    Raises ValueError when the envelope shape is wrong. A present-but-null
    content comes back as None -- whether that is data or an error is the
    caller's policy, not this module's.
    """
    if not isinstance(payload, dict):
        raise ValueError("response body is not a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("response choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("response choice has no message")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ValueError("message content is not text")
    finish = first.get("finish_reason")
    if finish is not None and not isinstance(finish, str):
        raise ValueError("finish_reason is not text")
    return content, finish
