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
