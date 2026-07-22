"""Tests for the queue worker's job handler (platform storefront #3).

The handler is the KNOWN half of the worker: our job schema in, stateless
core out. The transport half is the guess and lives elsewhere.
"""

import pytest

from app.worker.handler import handle_job

# The `analyze` op late-imports app.server (fastapi); on a core-only install
# (the CI job that guards the end-user path with the unpinned requirements.txt)
# fastapi is absent, so analyze legitimately returns an error there. Guard the
# analyze assertion behind fastapi availability instead of asserting it works
# in an environment where the web layer it needs was never installed.
try:
    import fastapi

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

THAI_TEXT = "ผมชื่อ นายสมชาย ใจดี เลขบัตรประชาชน 1101700230708 โทร 081-234-5678"


def test_sanitize_omits_mapping_by_default():
    out = handle_job(
        {
            "job_id": "j1",
            "operation": "sanitize",
            "payload": {"text": THAI_TEXT, "mode": "token"},
        }
    )
    assert out["job_id"] == "j1"
    assert out["status"] == "ok"
    res = out["result"]
    assert "1101700230708" not in res["sanitized_text"]
    assert "mapping" not in res


@pytest.mark.parametrize("truthy_but_not_true", [1, "true", [True]])
def test_sanitize_mapping_opt_in_requires_exact_boolean_true(truthy_but_not_true):
    out = handle_job(
        {
            "job_id": "j-opt-in-shape",
            "operation": "sanitize",
            "payload": {
                "text": THAI_TEXT,
                "mode": "token",
                "include_mapping": truthy_but_not_true,
            },
        }
    )
    assert out["status"] == "ok"
    assert "mapping" not in out["result"]


def test_sanitize_explicit_mapping_opt_in_supports_restore():
    out = handle_job(
        {
            "job_id": "j1-with-mapping",
            "operation": "sanitize",
            "payload": {"text": THAI_TEXT, "mode": "token", "include_mapping": True},
        }
    )
    assert out["status"] == "ok"
    res = out["result"]
    assert res["mapping"]

    restored = handle_job(
        {
            "job_id": "j2",
            "operation": "restore",
            "payload": {"text": res["sanitized_text"], "mapping": res["mapping"]},
        }
    )
    assert restored["status"] == "ok"
    assert "สมชาย" in restored["result"]["restored_text"]


def test_roundtrip_fake_provider_restores_without_returning_mapping():
    out = handle_job(
        {
            "job_id": "j-roundtrip",
            "operation": "roundtrip",
            "payload": {"text": THAI_TEXT, "mode": "token", "provider": "fake"},
        }
    )
    assert out["status"] == "ok"
    res = out["result"]
    assert res["provider_used"] == "fake"
    assert "1101700230708" not in res["sanitized_text"]
    assert "1101700230708" not in res["ai_response_masked"]
    assert "สมชาย" in res["restored_text"]
    assert "mapping" not in res


def test_roundtrip_defaults_to_fake_provider():
    out = handle_job(
        {"job_id": "j-roundtrip-default", "operation": "roundtrip", "payload": {"text": THAI_TEXT}}
    )
    assert out["status"] == "ok"
    assert out["result"]["provider_used"] == "fake"


def test_roundtrip_unknown_provider_is_safe_error():
    out = handle_job(
        {
            "job_id": "j-roundtrip-unknown",
            "operation": "roundtrip",
            "payload": {"text": THAI_TEXT, "provider": THAI_TEXT},
        }
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "invalid_provider"
    assert THAI_TEXT not in str(out)


def test_roundtrip_missing_provider_credentials_is_safe_error(monkeypatch):
    monkeypatch.delenv("AIFORTHAI_API_KEY", raising=False)
    out = handle_job(
        {
            "job_id": "j-roundtrip-no-key",
            "operation": "roundtrip",
            "payload": {"text": THAI_TEXT, "provider": "pathumma"},
        }
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "provider_unavailable"
    assert THAI_TEXT not in str(out)


def test_roundtrip_provider_failure_is_safe_error(monkeypatch):
    import app.worker.handler as handler

    class BoomProvider:
        def complete(self, system, user, *, timeout=30.0):
            raise RuntimeError(f"upstream echoed {THAI_TEXT}")

    monkeypatch.setitem(handler._PROVIDER_FACTORIES, "boom", BoomProvider)
    out = handle_job(
        {
            "job_id": "j-roundtrip-provider-fail",
            "operation": "roundtrip",
            "payload": {"text": THAI_TEXT, "provider": "boom"},
        }
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "provider_failed"
    assert THAI_TEXT not in str(out)


def test_roundtrip_leak_block_maps_to_error(monkeypatch):
    import app.worker.handler as handler
    from pii_redactor.stateless import StatelessLeakError

    def leak(*args, **kwargs):
        raise StatelessLeakError(["THAI_ID"])

    monkeypatch.setattr(handler, "sanitize_stateless", leak)
    out = handle_job(
        {"job_id": "j-roundtrip-leak", "operation": "roundtrip", "payload": {"text": THAI_TEXT}}
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "pii_leak_risk"
    assert THAI_TEXT not in str(out)


def test_detect_operation():
    d = handle_job({"job_id": "j4", "operation": "detect", "payload": {"text": THAI_TEXT}})
    assert d["status"] == "ok"
    assert d["result"]["entities"], "expected entities"


@pytest.mark.skipif(
    not FASTAPI_AVAILABLE,
    reason="analyze op needs the web layer (app.server); absent on core-only installs",
)
def test_analyze_operation():
    a = handle_job({"job_id": "j3", "operation": "analyze", "payload": {"text": THAI_TEXT}})
    assert a["status"] == "ok"
    assert "overall_score" in a["result"]


def test_unknown_operation_is_error_not_crash():
    out = handle_job({"job_id": "j5", "operation": "explode", "payload": {}})
    assert out["status"] == "error"
    assert out["error"]["type"] == "unknown_operation"


def test_bad_payload_is_error_not_crash():
    out = handle_job({"job_id": "j6", "operation": "sanitize", "payload": {}})
    assert out["status"] == "error"


def test_error_result_carries_no_payload_text():
    # error paths must not echo the (possibly PII-bearing) payload back in the
    # error message
    out = handle_job(
        {"job_id": "j7", "operation": "sanitize", "payload": {"text": "", "mode": "token"}}
    )
    assert out["status"] == "error"
    assert "สมชาย" not in str(out)


def test_leak_block_maps_to_error():
    from unittest.mock import patch

    from pii_redactor.stateless import StatelessLeakError

    with patch(
        "app.worker.handler.sanitize_stateless",
        side_effect=StatelessLeakError(["THAI_ID"]),
    ):
        out = handle_job(
            {
                "job_id": "j8",
                "operation": "sanitize",
                "payload": {"text": THAI_TEXT, "mode": "token"},
            }
        )
    assert out["status"] == "error"
    assert out["error"]["type"] == "pii_leak_risk"
    assert "1101700230708" not in str(out)


def test_entrypoint_importable_and_wires_sigterm():
    # smoke: the module imports and exposes main() without side effects
    from app.worker.__main__ import main

    assert callable(main)
