"""Boot-token enforcement on the localhost control plane (Horizon-1 #2).

Enforced ONLY on the control plane (`POST /api/shutdown`,
`DELETE /api/session/{id}`) and ONLY when `server._BOOT_TOKEN` is set. When it
is unset the grace path keeps the pre-token behavior byte-for-byte — that is
proven by tests/test_api_hardening.py, which this file does not touch.

These tests monkeypatch `server._BOOT_TOKEN` directly (no module reload) and
follow the `_schedule_exit` monkeypatch pattern from test_api_hardening.py.
"""
import pytest

try:
    from fastapi.testclient import TestClient

    import app.server as server
    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi not installed")

TOKEN = "boot-token-under-test-0123456789abcdef"


def _client():
    return TestClient(server.app, base_url="http://localhost")


# ── /api/health capability discovery ───────────────────────────────────
def test_health_reports_token_not_required_when_unset(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    body = _client().get("/api/health").json()
    assert body["capabilities"]["token_required"] is False


def test_health_reports_token_required_when_set(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    body = _client().get("/api/health").json()
    assert body["capabilities"]["token_required"] is True


# ── shutdown: token SET ─────────────────────────────────────────────────
def test_shutdown_allowed_with_correct_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Token": TOKEN})
    assert resp.status_code == 200
    assert called.get("hit") is True


def test_shutdown_rejected_with_wrong_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Token": "wrong"})
    assert resp.status_code == 403
    assert "hit" not in called


def test_shutdown_rejected_with_missing_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown")
    assert resp.status_code == 403
    assert "hit" not in called


def test_shutdown_local_header_alone_rejected_when_token_set(monkeypatch):
    """X-AIGuard-Local by itself must NOT authorize shutdown once a token is set."""
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Local": "1"})
    assert resp.status_code == 403
    assert "hit" not in called


# ── shutdown: token UNSET (grace path) ──────────────────────────────────
def test_shutdown_grace_path_requires_local_header(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown")
    assert resp.status_code == 403
    assert "hit" not in called


def test_shutdown_grace_path_allowed_with_local_header(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Local": "1"})
    assert resp.status_code == 200
    assert called.get("hit") is True


# ── delete-session: token SET ───────────────────────────────────────────
def _make_session(client):
    s = client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    return s["session_id"]


def test_delete_session_allowed_with_correct_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}", headers={"X-AIGuard-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_session_rejected_with_wrong_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}", headers={"X-AIGuard-Token": "wrong"})
    assert resp.status_code == 403
    # Session must survive a rejected delete.
    r = client.post("/api/reidentify", json={"session_id": sid, "text": "x"})
    assert r.status_code == 200


def test_delete_session_rejected_with_missing_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}")
    assert resp.status_code == 403


# ── delete-session: token UNSET (grace path) ────────────────────────────
def test_delete_session_grace_path_open(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ── the 403 body must never echo the token ──────────────────────────────
def test_forbidden_response_does_not_leak_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    monkeypatch.setattr(server, "_schedule_exit", lambda: None)
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Token": "wrong"})
    assert resp.status_code == 403
    assert TOKEN not in resp.text
    del_resp = _client().delete("/api/session/whatever", headers={"X-AIGuard-Token": "wrong"})
    assert del_resp.status_code == 403
    assert TOKEN not in del_resp.text
