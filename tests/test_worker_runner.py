"""Tests for the worker's transport seam and run loop."""

import logging
import threading

import httpx
import pytest

from app.worker.runner import run
from app.worker.transport import HttpPollTransport, InMemoryTransport

THAI_TEXT = "ผมชื่อ นายสมชาย ใจดี เลขบัตรประชาชน 1101700230708"


def _error_retaining(value):
    retained = value
    try:
        raise RuntimeError("synthetic worker failure")
    except RuntimeError as error:
        assert retained is value
        return error


def _traceback_holds(error, value):
    current = error.__traceback__
    while current is not None:
        if any(candidate is value for candidate in current.tb_frame.f_locals.values()):
            return True
        current = current.tb_next
    return False


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


def test_residual_sanitize_submits_only_safe_error(monkeypatch):
    import pii_redactor.stateless as stateless_module

    residual = "เอกสารหมายเลข 6801234"
    monkeypatch.setattr(
        stateless_module,
        "scan_residual_signals",
        lambda _text, _vault: ["orphan_digits:7"],
    )
    transport = InMemoryTransport(
        [
            {
                "job_id": "residual",
                "operation": "sanitize",
                "payload": {"text": residual, "include_mapping": True},
            }
        ]
    )

    assert run(transport, max_jobs=1) == 1
    assert transport.results == [
        {
            "contract_version": 1,
            "job_id": "residual",
            "operation": "sanitize",
            "status": "error",
            "error": {
                "type": "residual_pii",
                "message": "outbound residual detected",
            },
        }
    ]
    assert residual not in str(transport.results)


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


def test_poll_raising_does_not_kill_loop():
    class BoomTransport:
        def __init__(self):
            self.results = []

        def poll(self):
            raise RuntimeError("transport bug")

        def submit(self, result):
            self.results.append(result)

    t = BoomTransport()
    assert run(t, max_jobs=1) == 0  # survived the raise, processed nothing


def test_poll_failure_discards_retained_exception_graph():
    payload = {"text": THAI_TEXT}
    retained_error = _error_retaining(payload)
    assert _traceback_holds(retained_error, payload)

    class BoomTransport:
        def poll(self):
            raise retained_error

        def submit(self, result):
            raise AssertionError("submit must not run")

    assert run(BoomTransport(), max_jobs=1) == 0
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None


def test_crashing_custom_handler_submits_error_result():
    t = InMemoryTransport([{"job_id": "x", "operation": "detect", "payload": {"text": THAI_TEXT}}])

    def bad_handler(job):
        raise RuntimeError("boom")

    assert run(t, handler=bad_handler, max_jobs=1) == 1
    assert t.results[0]["status"] == "error"
    assert t.results[0]["error"]["type"] == "handler_crashed"


def test_handler_failure_discards_retained_exception_graph():
    job = {"job_id": "x", "operation": "detect", "payload": {"text": THAI_TEXT}}
    retained_error = _error_retaining(job)
    assert _traceback_holds(retained_error, job)
    transport = InMemoryTransport([job])

    def bad_handler(_job):
        raise retained_error

    assert run(transport, handler=bad_handler, max_jobs=1) == 1
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert transport.results[0]["error"]["type"] == "handler_crashed"


def test_poll_non_200_logs_status_but_not_body(monkeypatch, caplog):
    import logging

    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        return httpx.Response(401, json={"detail": "bad key"}, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    t = HttpPollTransport(poll_url="https://q.example/next", result_url="https://q.example/r")
    with caplog.at_level(logging.WARNING):
        assert t.poll() is None
    assert "401" in caplog.text
    assert "bad key" not in caplog.text


def test_submit_raising_does_not_kill_loop():
    class SubmitBoomTransport:
        def __init__(self, jobs):
            self._jobs = list(jobs)

        def poll(self):
            return self._jobs.pop(0) if self._jobs else None

        def submit(self, result):
            raise RuntimeError("result endpoint down")

    t = SubmitBoomTransport(
        [
            {"job_id": "s1", "operation": "detect", "payload": {"text": THAI_TEXT}},
            {"job_id": "s2", "operation": "detect", "payload": {"text": THAI_TEXT}},
        ]
    )
    # both jobs processed despite every submit raising — the loop never dies
    assert run(t, max_jobs=2) == 2


def test_submit_exception_group_discards_every_retained_graph():
    restored_result = {"text": THAI_TEXT}
    member = _error_retaining(restored_result)
    retained_group = ExceptionGroup("synthetic group", [member])
    assert _traceback_holds(member, restored_result)

    class SubmitBoomTransport:
        def __init__(self):
            self._jobs = [{"job_id": "s1", "operation": "detect", "payload": {"text": THAI_TEXT}}]

        def poll(self):
            return self._jobs.pop(0) if self._jobs else None

        def submit(self, _result):
            raise retained_group

    assert run(SubmitBoomTransport(), max_jobs=1) == 1
    assert retained_group.__traceback__ is None
    assert retained_group.__cause__ is None
    assert retained_group.__context__ is None
    assert member.__traceback__ is None
    assert member.__cause__ is None
    assert member.__context__ is None


def test_duplicate_delivery_reuses_result_without_repeating_handler():
    job = {"job_id": "duplicate-1", "operation": "detect", "payload": {"text": THAI_TEXT}}
    t = InMemoryTransport([job, dict(job)])
    calls = 0

    def counting_handler(current):
        nonlocal calls
        calls += 1
        return {
            "contract_version": 1,
            "job_id": current["job_id"],
            "operation": current["operation"],
            "status": "ok",
            "result": {"call": calls},
        }

    assert run(t, handler=counting_handler, max_jobs=2) == 2
    assert calls == 1
    assert t.results[0] == t.results[1]


def test_submit_failure_then_redelivery_does_not_repeat_handler():
    job = {"job_id": "retry-1", "operation": "detect", "payload": {"text": THAI_TEXT}}

    class FailFirstSubmitTransport:
        def __init__(self):
            self.jobs = [job, dict(job)]
            self.results = []
            self.submit_calls = 0

        def poll(self):
            return self.jobs.pop(0) if self.jobs else None

        def submit(self, result):
            self.submit_calls += 1
            if self.submit_calls == 1:
                raise RuntimeError("temporary result failure")
            self.results.append(result)

    calls = 0

    def counting_handler(current):
        nonlocal calls
        calls += 1
        return {
            "contract_version": 1,
            "job_id": current["job_id"],
            "operation": current["operation"],
            "status": "ok",
            "result": {"call": calls},
        }

    t = FailFirstSubmitTransport()
    assert run(t, handler=counting_handler, max_jobs=2) == 2
    assert calls == 1
    assert len(t.results) == 1
    assert t.results[0]["result"]["call"] == 1


def test_same_job_id_with_different_payload_fails_without_second_handler_call():
    first = {"job_id": "conflict-1", "operation": "detect", "payload": {"text": THAI_TEXT}}
    second = {
        "job_id": "conflict-1",
        "operation": "detect",
        "payload": {"text": THAI_TEXT + " changed"},
    }
    t = InMemoryTransport([first, second])
    calls = 0

    def counting_handler(current):
        nonlocal calls
        calls += 1
        return {
            "contract_version": 1,
            "job_id": current["job_id"],
            "operation": current["operation"],
            "status": "ok",
            "result": {},
        }

    assert run(t, handler=counting_handler, max_jobs=2) == 2
    assert calls == 1
    assert t.results[1]["status"] == "error"
    assert t.results[1]["error"]["type"] == "duplicate_conflict"
    assert THAI_TEXT not in str(t.results[1])


def test_zero_capacity_disables_duplicate_cache():
    job = {"job_id": "no-cache", "operation": "detect", "payload": {"text": THAI_TEXT}}
    t = InMemoryTransport([job, dict(job)])
    calls = 0

    def counting_handler(current):
        nonlocal calls
        calls += 1
        return {
            "contract_version": 1,
            "job_id": current["job_id"],
            "operation": current["operation"],
            "status": "ok",
            "result": {},
        }

    assert run(t, handler=counting_handler, max_jobs=2, idempotency_capacity=0) == 2
    assert calls == 2


def test_logs_hash_job_id_and_never_include_payload(monkeypatch, caplog):
    honeytoken = "HONEYTOKEN-PHONE-0812345678"
    job_id = "secret-job-id"
    t = InMemoryTransport(
        [{"job_id": job_id, "operation": "detect", "payload": {"text": honeytoken}}]
    )

    def safe_handler(current):
        return {
            "contract_version": 1,
            "job_id": current["job_id"],
            "operation": current["operation"],
            "status": "error",
            "error": {"type": "synthetic", "message": "safe"},
        }

    with caplog.at_level(logging.INFO, logger="app.worker.runner"):
        assert run(t, handler=safe_handler, max_jobs=1) == 1
    assert honeytoken not in caplog.text
    assert job_id not in caplog.text
    assert "job_ref=" in caplog.text
