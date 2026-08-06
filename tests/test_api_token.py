"""Authenticated localhost control-plane coverage."""

import threading

import pytest

try:
    from fastapi.testclient import TestClient

    import app.server as server

    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="fastapi not installed")

TOKEN = "boot-token-under-test-0123456789abcdef"
AUTH_NOW = 1_800_000_000.0


def _client():
    return TestClient(
        server.app,
        base_url="http://localhost",
        headers={"X-AIGuard-Contract-Version": "2"},
    )


@pytest.fixture(autouse=True)
def _isolated_control_state(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    monkeypatch.setattr(server, "_authorization_now", lambda: AUTH_NOW)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "SERVICE", server.SessionService())


def _disposal_authorization(
    session_id: str,
    *,
    control_token: str = TOKEN,
    issued_at: float = AUTH_NOW,
    lifetime_s: float = 30.0,
    nonce: bytes | None = None,
) -> str:
    return server._make_session_disposal_authorization(
        control_token,
        session_id,
        now=issued_at,
        lifetime_s=lifetime_s,
        nonce=nonce,
    )


# ── /api/health capability discovery ───────────────────────────────────
def test_health_reports_token_not_required_when_unset(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    body = _client().get("/api/health").json()
    assert body["capabilities"]["control_token_required"] is False


def test_health_reports_token_required_when_set(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    body = _client().get("/api/health").json()
    assert body["capabilities"]["control_token_required"] is True


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
def test_shutdown_grace_path_open_without_control_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown")
    assert resp.status_code == 200
    assert called.get("hit") is True


def test_shutdown_grace_path_allowed_with_local_header(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    called = {}
    monkeypatch.setattr(server, "_schedule_exit", lambda: called.setdefault("hit", True))
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Local": "1"})
    assert resp.status_code == 200
    assert called.get("hit") is True


# ── delete-session: control secret SET ─────────────────────────────────
def _make_session(client):
    s = client.post("/api/sanitize", json={"text": "โทร 0812345678"}).json()
    return s["session_id"]


def test_delete_session_allowed_with_valid_authorization(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    authorization = _disposal_authorization(sid)
    resp = client.delete(
        f"/api/session/{sid}",
        headers={"X-AIGuard-Token": authorization},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_session_rejects_raw_boot_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}", headers={"X-AIGuard-Token": TOKEN})
    assert resp.status_code == 403
    # Session must survive a rejected delete.
    r = client.post("/api/reidentify", json={"session_id": sid, "text": "x"})
    assert r.status_code == 200


def test_delete_session_rejects_missing_authorization(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}")
    assert resp.status_code == 403


# ── delete-session: control secret UNSET is fail closed ─────────────────
def test_delete_session_rejected_when_control_token_is_unset(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", None)
    client = _client()
    sid = _make_session(client)
    resp = client.delete(f"/api/session/{sid}")
    assert resp.status_code == 403
    assert (
        client.post(
            "/api/reidentify",
            json={"session_id": sid, "text": "x"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "not-an-authorization",
        "v1.invalid.invalid.invalid",
        "v2.1800000030000.aaaaaaaaaaaaaaaaaaaaaa.invalid",
        "v1.1800000030000.short.invalid",
        "v1.1800000030000.aaaaaaaaaaaaaaaaaaaaaa.short",
        "v1.999999999999999999999.aaaaaaaaaaaaaaaaaaaaaa.invalid",
    ],
)
def test_delete_session_rejects_malformed_authorization(monkeypatch, authorization):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)

    resp = client.delete(
        f"/api/session/{sid}",
        headers={"X-AIGuard-Token": authorization},
    )

    assert resp.status_code == 403
    assert (
        client.post(
            "/api/reidentify",
            json={"session_id": sid, "text": "x"},
        ).status_code
        == 200
    )


def test_delete_session_rejects_non_ascii_authorization(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)

    resp = client.delete(
        f"/api/session/{sid}",
        headers=[(b"X-AIGuard-Token", b"\xff")],
    )

    assert resp.status_code == 403


def test_delete_session_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    authorization = _disposal_authorization(
        sid,
        control_token="different-control-secret",
    )

    resp = client.delete(
        f"/api/session/{sid}",
        headers={"X-AIGuard-Token": authorization},
    )

    assert resp.status_code == 403


def test_delete_session_rejects_expired_authorization(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    authorization = _disposal_authorization(
        sid,
        issued_at=AUTH_NOW - 60,
        lifetime_s=30,
    )

    resp = client.delete(
        f"/api/session/{sid}",
        headers={"X-AIGuard-Token": authorization},
    )

    assert resp.status_code == 403


@pytest.mark.parametrize(
    ("elapsed_s", "expected_status"),
    [
        (29.999, 200),
        (30.0, 403),
        (30.001, 403),
    ],
)
def test_disposal_authorization_expiry_boundary(
    monkeypatch,
    elapsed_s,
    expected_status,
):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    monkeypatch.setattr(
        server,
        "_authorization_now",
        lambda: AUTH_NOW + elapsed_s,
    )
    client = _client()
    sid = _make_session(client)
    authorization = _disposal_authorization(sid)

    resp = client.delete(
        f"/api/session/{sid}",
        headers={"X-AIGuard-Token": authorization},
    )

    assert resp.status_code == expected_status


def test_delete_session_rejects_duplicate_authorization_headers(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    authorization = _disposal_authorization(sid)

    resp = client.delete(
        f"/api/session/{sid}",
        headers=[
            (b"X-AIGuard-Token", authorization.encode("ascii")),
            (b"X-AIGuard-Token", authorization.encode("ascii")),
        ],
    )

    assert resp.status_code == 403


def test_disposal_authorization_is_bound_to_target_session(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    first_id = _make_session(client)
    second_id = _make_session(client)
    first_authorization = _disposal_authorization(first_id)

    resp = client.delete(
        f"/api/session/{second_id}",
        headers={"X-AIGuard-Token": first_authorization},
    )

    assert resp.status_code == 403
    for session_id in (first_id, second_id):
        assert (
            client.post(
                "/api/reidentify",
                json={"session_id": session_id, "text": "x"},
            ).status_code
            == 200
        )


def test_disposal_authorization_replay_fails_closed(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    authorization = _disposal_authorization(sid)
    headers = {"X-AIGuard-Token": authorization}

    assert client.delete(f"/api/session/{sid}", headers=headers).status_code == 200
    replay = client.delete(f"/api/session/{sid}", headers=headers)

    assert replay.status_code == 403


def test_repeated_disposal_with_fresh_authority_is_idempotent(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)

    first = client.delete(
        f"/api/session/{sid}",
        headers={
            "X-AIGuard-Token": _disposal_authorization(
                sid,
                nonce=b"a" * 16,
            )
        },
    )
    repeated = client.delete(
        f"/api/session/{sid}",
        headers={
            "X-AIGuard-Token": _disposal_authorization(
                sid,
                nonce=b"b" * 16,
            )
        },
    )

    assert first.status_code == repeated.status_code == 200
    assert first.json() == {"deleted": True}
    assert repeated.json() == {"deleted": False}


def test_concurrent_repeated_disposal_cleans_once(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    session = server.SERVICE._sessions[sid]
    clear_calls = 0
    clear_lock = threading.Lock()
    real_clear = session.vault.clear

    def counted_clear():
        nonlocal clear_calls
        with clear_lock:
            clear_calls += 1
        real_clear()

    session.vault.clear = counted_clear
    start = threading.Barrier(3)
    responses = []

    def dispose(nonce: bytes):
        start.wait(timeout=5)
        response = _client().delete(
            f"/api/session/{sid}",
            headers={
                "X-AIGuard-Token": _disposal_authorization(
                    sid,
                    nonce=nonce,
                )
            },
        )
        responses.append(response)

    threads = [
        threading.Thread(target=dispose, args=(b"c" * 16,)),
        threading.Thread(target=dispose, args=(b"d" * 16,)),
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sorted(response.json()["deleted"] for response in responses) == [False, True]
    assert clear_calls == 1


def test_disposal_of_already_expired_session_is_safe_noop(monkeypatch):
    clock = {"now": 1000.0}
    service = server.SessionService(ttl_s=10, now_fn=lambda: clock["now"])
    monkeypatch.setattr(server, "SERVICE", service)
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    client = _client()
    sid = _make_session(client)
    clock["now"] += 10
    assert service.expire_due() == 1

    resp = client.delete(
        f"/api/session/{sid}",
        headers={"X-AIGuard-Token": _disposal_authorization(sid)},
    )

    assert resp.status_code == 200
    assert resp.json() == {"deleted": False}


# ── the 403 body must never echo the token ──────────────────────────────
def test_forbidden_response_does_not_leak_token(monkeypatch):
    monkeypatch.setattr(server, "_BOOT_TOKEN", TOKEN)
    monkeypatch.setattr(server, "_schedule_exit", lambda: None)
    resp = _client().post("/api/shutdown", headers={"X-AIGuard-Token": "wrong"})
    assert resp.status_code == 403
    assert TOKEN not in resp.text
    del_resp = _client().delete(
        "/api/session/whatever",
        headers={"X-AIGuard-Token": "wrong"},
    )
    assert del_resp.status_code == 403
    assert TOKEN not in del_resp.text
