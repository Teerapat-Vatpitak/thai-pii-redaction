import json
import os

import pytest

try:
    from fastapi.testclient import TestClient
    import app.server as server
    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi not installed")

EXT_ORIGIN = "chrome-extension://" + "a" * 32


def _client():
    return TestClient(server.app, base_url="http://localhost")


def test_cors_allows_extension_origin():
    resp = _client().get("/api/health", headers={"Origin": EXT_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == EXT_ORIGIN


def test_cors_allows_tauri_scheme_origin():
    resp = _client().get("/api/health", headers={"Origin": "tauri://localhost"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "tauri://localhost"


def test_cors_allows_tauri_http_origin():
    resp = _client().get("/api/health", headers={"Origin": "http://tauri.localhost"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://tauri.localhost"


@pytest.mark.parametrize("origin", ["https://chatgpt.com", "https://evil.example", "http://localhost:5173"])
def test_cors_blocks_web_origin_read(origin):
    resp = _client().get("/api/health", headers={"Origin": origin})
    assert resp.headers.get("access-control-allow-origin") != origin


@pytest.mark.parametrize("origin", ["https://chatgpt.com", "https://evil.example"])
def test_cors_blocks_web_origin_preflight(origin):
    resp = _client().options(
        "/api/reidentify",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != origin


def test_trusted_host_rejects_foreign_host():
    resp = _client().get("/api/health", headers={"Host": "evil.example"})
    assert resp.status_code == 400


def test_trusted_host_rejects_rebinding_host():
    resp = _client().get("/api/health", headers={"Host": "rebind.attacker.test"})
    assert resp.status_code == 400


def test_trusted_host_allows_localhost():
    resp = _client().get("/api/health", headers={"Host": "localhost"})
    assert resp.status_code == 200


def test_trusted_host_allows_loopback_ip():
    resp = _client().get("/api/health", headers={"Host": "127.0.0.1"})
    assert resp.status_code == 200


def test_shutdown_rejected_without_local_header(monkeypatch):
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown")
    assert resp.status_code == 403
    assert "hit" not in called


def test_shutdown_allowed_with_local_header(monkeypatch):
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Local": "1"})
    assert resp.status_code == 200
    assert called.get("hit") is True


def test_session_expires_after_idle_ttl(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(server, "_now", lambda: clock["t"])
    client = _client()
    s = client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    sid = s["session_id"]
    clock["t"] += server._SESSION_TTL_S + 1
    resp = client.post("/api/reidentify", json={"session_id": sid, "text": s["sanitized_text"]})
    assert resp.status_code == 404


def test_session_survives_within_ttl(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(server, "_now", lambda: clock["t"])
    client = _client()
    s = client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    sid = s["session_id"]
    clock["t"] += server._SESSION_TTL_S - 5
    resp = client.post("/api/reidentify", json={"session_id": sid, "text": s["sanitized_text"]})
    assert resp.status_code == 200
    assert "0812345678" in resp.json()["restored_text"]


def test_session_idle_timer_resets_on_access(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(server, "_now", lambda: clock["t"])
    client = _client()
    s = client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    sid = s["session_id"]
    clock["t"] += server._SESSION_TTL_S - 10
    assert client.post("/api/reidentify", json={"session_id": sid, "text": s["sanitized_text"]}).status_code == 200
    clock["t"] += server._SESSION_TTL_S - 10
    assert client.post("/api/reidentify", json={"session_id": sid, "text": s["sanitized_text"]}).status_code == 200


def test_delete_session_clears_reidentify():
    client = _client()
    s = client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    sid = s["session_id"]
    deleted = client.delete(f"/api/session/{sid}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    resp = client.post("/api/reidentify", json={"session_id": sid, "text": s["sanitized_text"]})
    assert resp.status_code == 404


def test_delete_unknown_session_returns_false():
    resp = _client().delete("/api/session/does-not-exist")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is False


def test_reidentify_unknown_session_404():
    resp = _client().post("/api/reidentify", json={"session_id": "nope", "text": "x"})
    assert resp.status_code == 404


def test_audit_log_omits_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    rec = {"type": "process", "session_id": "secret-sid-123", "timestamp": 1,
           "step": "api_sanitize", "entity_count": 1}
    (tmp_path / "audit_1_process.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    resp = _client().get("/api/audit-log")
    assert resp.status_code == 200
    assert "secret-sid-123" not in resp.text
    for row in resp.json()["logs"]:
        assert "session_id" not in row


def test_audit_log_read_is_bounded_by_max_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "_AUDIT_MAX_FILES", 3)
    for i in range(10):
        p = tmp_path / f"audit_{i}_process.jsonl"
        p.write_text(json.dumps({"type": "process", "timestamp": i, "step": "s", "entity_count": 0}) + "\n",
                     encoding="utf-8")
        os.utime(p, (float(i), float(i)))
    resp = _client().get("/api/audit-log?limit=100")
    assert resp.status_code == 200
    assert resp.json()["total_count"] == 3
    ts = [row["timestamp"] for row in resp.json()["logs"]]
    assert ts == [9, 8, 7]
