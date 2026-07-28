"""Wire-level primitives for OpenAI-compatible endpoints — mechanics, no policy."""

import pytest

from pii_redactor.openai_compat import (
    chat_completions_url,
    extract_chat_content,
    is_sse_response,
    validate_header_value,
)


class TestValidateHeaderValue:
    def test_valid_key_passes_through(self):
        assert validate_header_value("sk-abc123", env_name="X") == "sk-abc123"

    @pytest.mark.parametrize(
        "bad",
        ["", "sk-กุญแจ", "sk-abc\r", "sk-abc\n", "sk-a\x00bc", " sk-abc", "sk-abc "],
        ids=["empty", "non-ascii", "cr", "lf", "control", "lead-ws", "trail-ws"],
    )
    def test_rejects_header_unsafe_values_naming_the_env_var(self, bad):
        with pytest.raises(ValueError, match="TOKENMIND_API_KEY"):
            validate_header_value(bad, env_name="TOKENMIND_API_KEY")


class TestChatCompletionsUrl:
    def test_joins_without_double_slash(self):
        assert (
            chat_completions_url("https://x.example/v1") == "https://x.example/v1/chat/completions"
        )
        assert (
            chat_completions_url("https://x.example/v1/") == "https://x.example/v1/chat/completions"
        )


class TestIsSseResponse:
    def test_detects_event_stream_with_params_and_case(self):
        assert is_sse_response("text/event-stream")
        assert is_sse_response("Text/Event-Stream; charset=utf-8")

    def test_json_and_missing_are_not_sse(self):
        assert not is_sse_response("application/json")
        assert not is_sse_response(None)
        assert not is_sse_response("")


class TestExtractChatContent:
    def test_extracts_content_and_finish_reason(self):
        payload = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        assert extract_chat_content(payload) == ("ok", "stop")

    def test_null_content_is_returned_as_none_not_error(self):
        payload = {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
        assert extract_chat_content(payload) == (None, "stop")

    @pytest.mark.parametrize(
        "payload",
        [
            "not a dict",
            {},
            {"choices": []},
            {"choices": ["x"]},
            {"choices": [{}]},
            {"choices": [{"message": "not a dict"}]},
            {"choices": [{"message": {"content": 42}}]},
        ],
    )
    def test_malformed_envelope_raises_value_error(self, payload):
        with pytest.raises(ValueError):
            extract_chat_content(payload)


class TestOpenAICompatCallerCharacterization:
    """Pin caller behavior across the shared-primitives refactor."""

    def _make(self, monkeypatch, *, key="sk-ok", base="https://gw.example/v1"):
        monkeypatch.setenv("X_BASE", base)
        monkeypatch.setenv("X_KEY", key)
        from benchmark.llm_providers import OpenAICompatCaller

        return OpenAICompatCaller("m", base_url_env="X_BASE", api_key_env="X_KEY")

    def test_missing_base_or_key_raises_provider_unavailable(self, monkeypatch):
        from benchmark.llm_providers import OpenAICompatCaller, ProviderUnavailable

        monkeypatch.delenv("X_BASE", raising=False)
        monkeypatch.setenv("X_KEY", "sk-ok")
        with pytest.raises(ProviderUnavailable, match="X_BASE"):
            OpenAICompatCaller("m", base_url_env="X_BASE", api_key_env="X_KEY")

    def test_non_ascii_key_still_raises_provider_unavailable(self, monkeypatch):
        from benchmark.llm_providers import ProviderUnavailable

        with pytest.raises(ProviderUnavailable, match="X_KEY"):
            self._make(monkeypatch, key="sk-ไทย")

    def test_key_with_crlf_now_rejected_by_name(self, monkeypatch):
        # Intentionally stricter than before the refactor (was: ASCII-only check).
        from benchmark.llm_providers import ProviderUnavailable

        with pytest.raises(ProviderUnavailable, match="X_KEY"):
            self._make(monkeypatch, key="sk-ok\n")

    def test_null_content_becomes_empty_string(self, monkeypatch):
        import httpx

        caller = self._make(monkeypatch)
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
            )
        )
        monkeypatch.setattr(
            "benchmark.llm_providers.httpx.post",
            lambda url, **kw: httpx.Client(transport=transport).post(url, **kw),
        )
        assert caller("s", "u") == ""
