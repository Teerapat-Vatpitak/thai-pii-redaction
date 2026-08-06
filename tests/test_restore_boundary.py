"""An internal restore defect must not surface as a raw 500 / generic job_failed.

The provider try/except in both surfaces covers provider.complete only;
restore_stateless on the next line was bare (spec: explicit scope, both paths).
"""

import pytest


class TestWorkerRestoreBoundary:
    def _job(self, operation, payload):
        return {
            "contract_version": 1,
            "job_id": "j1",
            "operation": operation,
            "payload": payload,
        }

    def test_roundtrip_restore_defect_is_restore_failed(self, monkeypatch):
        from app.worker import handler

        def boom(text, *, mapping):
            raise RuntimeError("internal defect")

        monkeypatch.setattr(handler, "restore_stateless", boom)
        result = handler.handle_job(self._job("roundtrip", {"text": "สวัสดีครับ", "provider": "fake"}))
        assert result["status"] == "error"
        assert result["error"]["type"] == "restore_failed"
        assert "internal defect" not in result["error"]["message"]

    def test_op_restore_defect_is_restore_failed(self, monkeypatch):
        from app.worker import handler

        def boom(text, *, mapping):
            raise RuntimeError("internal defect")

        monkeypatch.setattr(handler, "restore_stateless", boom)
        result = handler.handle_job(self._job("restore", {"text": "x", "mapping": {"[ชื่อ_1]": "ก"}}))
        assert result["status"] == "error"
        assert result["error"]["type"] == "restore_failed"


class TestServerRestoreBoundary:
    @pytest.fixture()
    def client(self):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from app.server import app

        return TestClient(
            app,
            base_url="http://localhost",
            headers={"X-AIGuard-Contract-Version": "2"},
        )

    def test_restore_defect_is_clean_500(self, client, monkeypatch):
        from app import server

        def boom(text, *, mapping):
            raise RuntimeError("internal defect detail")

        monkeypatch.setattr(server, "restore_stateless", boom)
        resp = client.post(
            "/api/roundtrip",
            json={"text": "สวัสดีครับผมชื่อสมชาย", "mode": "token", "provider": "fake"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "restore_failed"
        assert "internal defect detail" not in resp.text

    def test_non_string_provider_return_is_502(self, client, monkeypatch):
        from app import server
        from pii_redactor.ai_client import AIProvider

        class Broken(AIProvider):
            def complete(self, system, user, *, timeout=30.0):
                return None  # type: ignore[return-value]

        monkeypatch.setitem(server._PROVIDER_FACTORIES, "fake", Broken)
        resp = client.post(
            "/api/roundtrip",
            json={"text": "สวัสดีครับ", "mode": "token", "provider": "fake"},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "provider_response_invalid"

    def test_provider_protocol_error_is_502_not_500(self, client, monkeypatch):
        # spec testing item 4: empty/protocol-violating content must surface as
        # 502 on the HTTP path (the first spec draft had this inverted)
        from app import server
        from pii_redactor.ai_client import AIProvider, ProviderProtocolError

        class Protocol(AIProvider):
            def complete(self, system, user, *, timeout=30.0):
                raise ProviderProtocolError("provider returned empty content")

        monkeypatch.setitem(server._PROVIDER_FACTORIES, "fake", Protocol)
        resp = client.post(
            "/api/roundtrip",
            json={"text": "สวัสดีครับ", "mode": "token", "provider": "fake"},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "provider_response_invalid"
