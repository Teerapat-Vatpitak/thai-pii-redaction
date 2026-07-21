"""Tests for the worker's transport seam and run loop."""

import threading

import httpx
import pytest

from app.worker.runner import run
from app.worker.transport import HttpPollTransport, InMemoryTransport

THAI_TEXT = "ผมชื่อ นายสมชาย ใจดี เลขบัตรประชาชน 1101700230708"


def test_inmemory_end_to_end():
    t = InMemoryTransport([{"job_id": "a", "operation": "detect", "payload": {"text": THAI_TEXT}}])
    processed = run(t, max_jobs=1)
    assert processed == 1
    assert len(t.results) == 1
    assert t.results[0]["status"] == "ok"


def test_poison_job_does_not_kill_loop():
    t = InMemoryTransport(
        [
            {"job_id": "bad", "operation": "sanitize", "payload": {}},
            {"job_id": "good", "operation": "detect", "payload": {"text": THAI_TEXT}},
        ]
    )
    processed = run(t, max_jobs=2)
    assert processed == 2
    assert [r["status"] for r in t.results] == ["error", "ok"]


def test_stop_event_halts_promptly():
    stop = threading.Event()
    stop.set()
    t = InMemoryTransport([])
    assert run(t, stop=stop) == 0


def test_http_transport_wire_shape(monkeypatch):
    calls = {"polls": 0, "submits": []}

    def fake_get(url, **kwargs):
        calls["polls"] += 1
        calls["poll_headers"] = kwargs.get("headers")
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            json={"job_id": "h1", "operation": "detect", "payload": {"text": THAI_TEXT}},
            request=request,
        )

    def fake_post(url, **kwargs):
        calls["submits"].append((url, kwargs.get("json")))
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("AIFORTHAI_API_KEY", "k")
    t = HttpPollTransport(poll_url="https://q.example/next", result_url="https://q.example/result")
    run(t, max_jobs=1)
    assert calls["polls"] == 1
    assert calls["poll_headers"]["Apikey"] == "k"
    url, body = calls["submits"][0]
    assert url == "https://q.example/result"
    assert body["job_id"] == "h1" and body["status"] == "ok"


def test_http_transport_204_means_no_job(monkeypatch):
    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(204, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    t = HttpPollTransport(poll_url="https://q.example/next", result_url="https://q.example/r")
    assert t.poll() is None


def test_http_transport_error_returns_none_not_crash(monkeypatch):
    def fake_get(url, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", fake_get)
    t = HttpPollTransport(poll_url="https://q.example/next", result_url="https://q.example/r")
    assert t.poll() is None
