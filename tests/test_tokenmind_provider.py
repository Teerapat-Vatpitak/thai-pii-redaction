"""TokenmindProvider protocol/retry tests -- MockTransport only, no network."""

import httpx
import pytest

from pii_redactor.ai_client import ProviderProtocolError, TokenmindProvider

BASE = "https://tokenmind.example/v1"


def _provider(monkeypatch, handler, *, clock=None, sleep=None):
    monkeypatch.setenv("TOKENMIND_BASE_URL", BASE)
    monkeypatch.setenv("TOKENMIND_API_KEY", "sk-test123")
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    if sleep is not None:
        kwargs["sleep"] = sleep
    p = TokenmindProvider(**kwargs)
    transport = httpx.MockTransport(handler)
    p._client = lambda: httpx.Client(transport=transport)
    return p


def _ok(content="สวัสดี", finish="stop"):
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]}
    )


class TestConstruction:
    def test_missing_base_url_raises(self, monkeypatch):
        monkeypatch.delenv("TOKENMIND_BASE_URL", raising=False)
        monkeypatch.setenv("TOKENMIND_API_KEY", "sk-x")
        with pytest.raises(ValueError, match="TOKENMIND_BASE_URL"):
            TokenmindProvider()

    def test_base_url_without_v1_suffix_raises(self, monkeypatch):
        monkeypatch.setenv("TOKENMIND_BASE_URL", "https://tokenmind.example")
        monkeypatch.setenv("TOKENMIND_API_KEY", "sk-x")
        with pytest.raises(ValueError, match="/v1"):
            TokenmindProvider()

    def test_http_url_rejected_without_dev_flag(self, monkeypatch):
        monkeypatch.setenv("TOKENMIND_BASE_URL", "http://tokenmind.example/v1")
        monkeypatch.setenv("TOKENMIND_API_KEY", "sk-x")
        monkeypatch.delenv("TOKENMIND_ALLOW_HTTP", raising=False)
        with pytest.raises(ValueError, match="https"):
            TokenmindProvider()

    def test_http_url_allowed_with_dev_flag(self, monkeypatch):
        monkeypatch.setenv("TOKENMIND_BASE_URL", "http://tokenmind.example/v1")
        monkeypatch.setenv("TOKENMIND_API_KEY", "sk-x")
        monkeypatch.setenv("TOKENMIND_ALLOW_HTTP", "1")
        TokenmindProvider()  # no raise

    @pytest.mark.parametrize(
        "bad", ["sk-ไทย", "sk-x\n", " sk-x", "sk-x\r"], ids=["thai", "lf", "ws", "cr"]
    )
    def test_header_unsafe_key_raises_before_network(self, monkeypatch, bad):
        monkeypatch.setenv("TOKENMIND_BASE_URL", BASE)
        monkeypatch.setenv("TOKENMIND_API_KEY", bad)
        with pytest.raises(ValueError, match="TOKENMIND_API_KEY"):
            TokenmindProvider()

    def test_handles_retries_flag(self, monkeypatch):
        monkeypatch.setenv("TOKENMIND_BASE_URL", BASE)
        monkeypatch.setenv("TOKENMIND_API_KEY", "sk-x")
        assert TokenmindProvider.handles_retries is True
        assert TokenmindProvider().handles_retries is True


class TestPayload:
    def test_payload_pins_spec_decisions(self, monkeypatch):
        seen = {}

        def handler(request):
            import json

            seen.update(json.loads(request.content))
            seen["_auth"] = request.headers.get("Authorization")
            return _ok()

        p = _provider(monkeypatch, handler)
        assert p.complete("sys", "user") == "สวัสดี"
        assert seen["model"] == "thaillm-8b"
        assert seen["stream"] is False
        assert seen["temperature"] == 0.0
        assert seen["max_tokens"] == 1024
        assert seen["chat_template_kwargs"] == {"enable_thinking": False}
        assert seen["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ]
        assert seen["_auth"] == "Bearer sk-test123"


class TestProtocolValidation:
    def test_sse_response_is_protocol_error(self, monkeypatch):
        def handler(req):
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=b"data: {}"
            )

        with pytest.raises(ProviderProtocolError):
            _provider(monkeypatch, handler).complete("s", "u")

    def test_non_json_body_is_protocol_error(self, monkeypatch):
        def handler(req):
            return httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"not json"
            )

        with pytest.raises(ProviderProtocolError):
            _provider(monkeypatch, handler).complete("s", "u")

    @pytest.mark.parametrize("content", [None, "", "   "], ids=["null", "empty", "blank"])
    def test_null_or_empty_content_is_protocol_error_not_empty_string(self, monkeypatch, content):
        with pytest.raises(ProviderProtocolError):
            _provider(monkeypatch, lambda req: _ok(content=content)).complete("s", "u")

    def test_finish_reason_length_is_protocol_error(self, monkeypatch):
        with pytest.raises(ProviderProtocolError):
            _provider(monkeypatch, lambda req: _ok(finish="length")).complete("s", "u")

    @pytest.mark.parametrize(
        "leak",
        ["<think>x</think>ตอบ", "<think>ไม่ปิด", "คำตอบ</think>", "&lt;think&gt;x&lt;/think&gt;ตอบ"],
        ids=["closed", "unclosed-open", "stray-close", "html-escaped"],
    )
    def test_think_trace_is_protocol_error(self, monkeypatch, leak):
        with pytest.raises(ProviderProtocolError):
            _provider(monkeypatch, lambda req: _ok(content=leak)).complete("s", "u")

    def test_protocol_error_message_never_contains_body(self, monkeypatch):
        secret = "SECRET-BODY-CONTENT"
        with pytest.raises(ProviderProtocolError) as exc_info:
            _provider(monkeypatch, lambda req: _ok(content=f"<think>{secret}")).complete("s", "u")
        assert secret not in str(exc_info.value)


class TestRetry:
    def _flaky(self, failures, then=_ok):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] <= len(failures):
                return failures[calls["n"] - 1]
            return then()

        return handler, calls

    def test_retries_on_429_then_succeeds(self, monkeypatch):
        handler, calls = self._flaky([httpx.Response(429), httpx.Response(429)])
        slept = []
        p = _provider(monkeypatch, handler, sleep=slept.append)
        assert p.complete("s", "u") == "สวัสดี"
        assert calls["n"] == 3
        assert len(slept) == 2

    def test_retries_on_5xx(self, monkeypatch):
        handler, calls = self._flaky([httpx.Response(503)])
        p = _provider(monkeypatch, handler, sleep=lambda s: None)
        assert p.complete("s", "u") == "สวัสดี"
        assert calls["n"] == 2

    def test_no_retry_on_other_4xx(self, monkeypatch):
        handler, calls = self._flaky([httpx.Response(400)] * 3)
        p = _provider(monkeypatch, handler, sleep=lambda s: None)
        with pytest.raises(httpx.HTTPStatusError):
            p.complete("s", "u")
        assert calls["n"] == 1

    def test_no_retry_on_protocol_error(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return _ok(content="")

        p = _provider(monkeypatch, handler, sleep=lambda s: None)
        with pytest.raises(ProviderProtocolError):
            p.complete("s", "u")
        assert calls["n"] == 1

    def test_exhausted_retries_reraise_last_transient_error(self, monkeypatch):
        handler, calls = self._flaky([httpx.Response(503)] * 5)
        p = _provider(monkeypatch, handler, sleep=lambda s: None)
        with pytest.raises(httpx.HTTPStatusError):
            p.complete("s", "u")
        assert calls["n"] == 3  # initial + 2 retries, no more

    def test_retry_after_integer_is_respected(self, monkeypatch):
        handler, _ = self._flaky([httpx.Response(429, headers={"Retry-After": "7"})])
        slept = []
        p = _provider(monkeypatch, handler, sleep=slept.append)
        assert p.complete("s", "u") == "สวัสดี"
        assert slept == [7.0]

    def test_retry_after_garbage_falls_back_to_exponential(self, monkeypatch):
        handler, _ = self._flaky([httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct"})])
        slept = []
        p = _provider(monkeypatch, handler, sleep=slept.append)
        assert p.complete("s", "u") == "สวัสดี"
        assert slept == [1.0]

    def test_deadline_prevents_sleep_past_budget(self, monkeypatch):
        # fake clock: each call advances; a 429 asks for a delay that would
        # cross the deadline -> raise the transient error without sleeping again
        t = {"now": 0.0}

        def clock():
            return t["now"]

        def sleep(s):
            t["now"] += s

        def handler(request):
            t["now"] += 4.0  # each attempt costs 4s
            return httpx.Response(429, headers={"Retry-After": "100"})

        p = _provider(monkeypatch, handler, clock=clock, sleep=sleep)
        with pytest.raises(httpx.HTTPStatusError):
            p.complete("s", "u", timeout=10.0)
        # attempt 1 at t=4; delay 100 would pass deadline 10 -> stop, no sleep
        assert t["now"] == 4.0

    @pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan")])
    def test_invalid_timeout_rejected(self, monkeypatch, bad):
        p = _provider(monkeypatch, lambda req: _ok())
        with pytest.raises(ValueError, match="timeout"):
            p.complete("s", "u", timeout=bad)
