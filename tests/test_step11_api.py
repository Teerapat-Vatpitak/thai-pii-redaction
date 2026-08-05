"""Tests for the FastAPI web server (Step 11: Web API).

Covers the v2 token-mode contract:
- /api/sanitize  -> session_id, original_text, sanitized_text, entities[], section26
- /api/reidentify -> restore tokens via stored session map
- /api/analyze   -> full PDPA report (score, grade, reid, breakdown, recs)
"""

import json
import uuid
from dataclasses import asdict

import pytest

# Skip entire module if fastapi not installed
try:
    from fastapi.testclient import TestClient

    from app.server import app

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not FASTAPI_AVAILABLE,
    reason="fastapi not installed",
)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.server import app

    return TestClient(app, base_url="http://localhost")


def _service_state(service):
    """Serialize ordered, identity-bearing session state without touching it."""
    return [
        (
            sid,
            {
                "session_object_id": id(session),
                "vault_object_id": id(session.vault),
                "mode": session.mode,
                "salt": session.salt,
                "created": session.created,
                "last_access": session.last_access,
                "entities": [asdict(entity) for entity in session.entities],
                "vault": {
                    "table": {
                        entity_id: asdict(record)
                        for entity_id, record in session.vault._table.items()
                    },
                    "reverse": dict(session.vault._reverse),
                    "last_access": session.vault._last_access,
                    "idle_timeout_s": session.vault._idle_timeout_s,
                    "session_id": session.vault.session_id,
                    "clear_epoch": session.vault._clear_epoch,
                    "audit_entries": [entry._asdict() for entry in session.vault._audit_entries],
                },
            },
        )
        for sid, session in service._sessions.items()
    ]


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root_redirects_to_docs(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/docs"


def test_cors_preflight_allows_extension(client):
    origin = "chrome-extension://" + "a" * 32
    resp = client.options(
        "/api/sanitize",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


def test_health_version(client):
    # REL-13: read the single source of truth rather than hardcoding another
    # copy of the version that every release would have to hand-bump.
    from pathlib import Path

    expected = (
        (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    )
    resp = client.get("/api/health")
    assert resp.json()["version"] == expected


def test_sanitize_returns_session_and_entities(client):
    resp = client.post("/api/sanitize", json={"text": "โทร 081-234-5678 นะ"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "sanitized_text" in data
    assert isinstance(data["entities"], list)
    assert isinstance(data["entity_type_counts"], dict)


def test_sanitize_empty_text_rejected(client):
    resp = client.post("/api/sanitize", json={"text": "   "})
    assert resp.status_code == 400


def test_sanitize_with_email_is_tokenized(client):
    resp = client.post("/api/sanitize", json={"text": "Contact me at user@example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entities"]) >= 1
    assert "user@example.com" not in data["sanitized_text"]


def test_sanitize_section26_flagged(client):
    resp = client.post("/api/sanitize", json={"text": "ผู้ป่วยนับถือศาสนาพุทธ มีโรคประจำตัว"})
    assert resp.status_code == 200
    cats = {s["category"] for s in resp.json()["section26"]}
    assert "RELIGION" in cats


def test_reidentify_round_trip(client):
    """Sanitize then restore the same tokens via the session map."""
    s = client.post("/api/sanitize", json={"text": "โทร 081-234-5678 ได้เลย"}).json()
    r = client.post(
        "/api/reidentify",
        json={
            "session_id": s["session_id"],
            "text": s["sanitized_text"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "081-234-5678" in data["restored_text"]
    assert data["replaced_count"] >= 1
    assert data["leftover_tokens"] == []


def test_reidentify_unknown_session(client):
    resp = client.post("/api/reidentify", json={"session_id": "nope", "text": "hi"})
    assert resp.status_code == 404


def test_analyze_returns_report_shape(client):
    resp = client.post("/api/analyze", json={"text": "โทร 081-234-5678 นะ"})
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "overall_score",
        "overall_grade",
        "risk_label",
        "direct_pii_count",
        "fp_count",
        "tb_count",
        "section26",
        "reid",
        "breakdown",
        "recommendations",
    ):
        assert key in data
    assert data["direct_pii_count"] >= 1


def test_analyze_no_pii_is_grade_a(client):
    resp = client.post("/api/analyze", json={"text": "The weather is nice today."})
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_grade"] == "A"
    assert data["risk_label"] == "Very Low Risk"


def test_analyze_breakdown_is_list(client):
    resp = client.post("/api/analyze", json={"text": "email me at a@b.com"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["breakdown"], list)


def test_analyze_reid_shape(client):
    resp = client.post("/api/analyze", json={"text": "นายสมชาย อายุ 32 ปี แขวงคลองเตย"})
    assert resp.status_code == 200
    reid = resp.json()["reid"]
    for key in ("score", "grade", "qi_found", "high_risk_combo"):
        assert key in reid


def test_analyze_high_risk(client):
    text = (
        "ชื่อ: นายสมชาย ใจดี อีเมล: somchai@example.com "
        "โทร: 081-234-5678 เลขบัตร: 1-1019-03451-08-3 "
        "อีกเบอร์: 090-000-1234 อีเมลสอง: b@c.com"
    )
    resp = client.post("/api/analyze", json={"text": text})
    assert resp.status_code == 200
    data = resp.json()
    assert data["direct_pii_count"] > 5
    assert data["overall_score"] >= 60


def test_sanitize_surrogate_mode_round_trip(client):
    """Surrogate mode replaces PII with realistic fakes; restore is exact."""
    text = "ผมชื่อสมชาย ใจดี โทร 081-234-5678 อีเมล somchai@example.com"
    s = client.post("/api/sanitize", json={"text": text, "mode": "surrogate"}).json()
    san = s["sanitized_text"]
    assert len(s["entities"]) >= 2
    assert san != text
    # original PII must be gone from the surrogate text
    assert "081-234-5678" not in san
    assert "somchai@example.com" not in san
    # round-trip restore returns the originals exactly
    r = client.post("/api/reidentify", json={"session_id": s["session_id"], "text": san}).json()
    assert "081-234-5678" in r["restored_text"]
    assert "somchai@example.com" in r["restored_text"]
    assert r["leftover_tokens"] == []


def test_sanitize_token_mode_unchanged(client):
    """Token mode still emits bracket tokens (default behavior)."""
    s = client.post("/api/sanitize", json={"text": "โทร 081-234-5678", "mode": "token"}).json()
    assert "[" in s["sanitized_text"]
    assert "081-234-5678" not in s["sanitized_text"]


def test_shutdown_endpoint_returns_ack(monkeypatch):
    import app.server as server

    called = {}

    def fake_schedule_exit():
        called["scheduled"] = True

    monkeypatch.setattr(server, "_schedule_exit", fake_schedule_exit)

    from fastapi.testclient import TestClient

    client = TestClient(server.app, base_url="http://localhost")
    resp = client.post("/api/shutdown", headers={"X-AIGuard-Local": "1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "shutting_down"}
    assert called.get("scheduled") is True


@pytest.mark.parametrize("with_existing_session", [False, True])
@pytest.mark.parametrize(
    "stage",
    [
        "guard_scan",
        "guard_projection",
        "audit_path",
        "audit_write",
        "response_encoding",
    ],
)
def test_sanitize_api_stage_failure_preserves_complete_session_state(
    monkeypatch,
    tmp_path,
    with_existing_session,
    stage,
):
    import app.server as server
    from pii_redactor.session_service import SessionService

    service = SessionService(now_fn=lambda: 1000.0)
    monkeypatch.setattr(server, "SERVICE", service)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    existing = service.sanitize("โทร 081-234-5678") if with_existing_session else None
    before = _service_state(service)
    audit_calls = []

    def fail_stage(*_args, **_kwargs):
        raise RuntimeError("forced API transaction stage failure")

    if stage == "guard_scan":
        monkeypatch.setattr(server, "scan_injection", fail_stage)
    elif stage == "guard_projection":
        monkeypatch.setattr(server, "to_wire", fail_stage)
    elif stage == "audit_path":
        monkeypatch.setattr(server, "_get_audit_log_dir", fail_stage)
    elif stage == "audit_write":
        monkeypatch.setattr(server, "write_process_log", fail_stage)
    else:
        monkeypatch.setattr(server, "JSONResponse", fail_stage)
        monkeypatch.setattr(
            server,
            "write_process_log",
            lambda **row: audit_calls.append(row),
        )

    request = server.SanitizeRequest(
        text="อีเมล first@example.com",
        session_id=existing.session_id if existing else None,
    )
    with pytest.raises(RuntimeError, match="forced API transaction stage failure"):
        server.sanitize(request)

    assert _service_state(service) == before
    assert list(tmp_path.glob("audit_*_process.jsonl")) == []
    if stage == "response_encoding":
        assert audit_calls == []


@pytest.mark.parametrize("stdout_mode", [False, True])
def test_sanitize_audit_uses_operation_id_without_mapping_material(
    tmp_path,
    monkeypatch,
    capsys,
    stdout_mode,
):
    from fastapi.testclient import TestClient

    import app.server as server
    from pii_redactor.session_service import SessionService

    service = SessionService(now_fn=lambda: 1000.0)
    monkeypatch.setattr(server, "SERVICE", service)
    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    if stdout_mode:
        monkeypatch.setenv("AIGUARD_AUDIT_STDOUT", "1")
    else:
        monkeypatch.delenv("AIGUARD_AUDIT_STDOUT", raising=False)

    response = TestClient(server.app, base_url="http://localhost").post(
        "/api/sanitize",
        json={"text": "โทร 081-234-5678", "mode": "token"},
    )
    assert response.status_code == 200
    body = response.json()

    if stdout_mode:
        rows = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.strip().startswith("{")
        ]
        assert not list(tmp_path.glob("audit_*_process.jsonl"))
        audit_text = json.dumps(rows, ensure_ascii=False)
        record = rows[-1]
    else:
        paths = list(tmp_path.glob("audit_*_process.jsonl"))
        assert len(paths) == 1
        assert body["session_id"] not in paths[0].name
        audit_text = paths[0].read_text(encoding="utf-8")
        record = json.loads(audit_text.splitlines()[-1])

    assert record["session_id"] != body["session_id"]
    assert record["validation_result"] == "prepared"
    assert str(uuid.UUID(record["session_id"])) == record["session_id"]
    forbidden = [
        "081-234-5678",
        body["session_id"],
        *(entity["token"] for entity in body["entities"]),
    ]
    assert all(value not in audit_text for value in forbidden)


def test_blocked_sanitize_audit_is_safe_and_non_authorizing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.server as server
    import pii_redactor.session_service as service_module
    from pii_redactor.models import Entity
    from pii_redactor.session_service import SessionService

    service = SessionService(now_fn=lambda: 1000.0)
    monkeypatch.setattr(server, "SERVICE", service)
    monkeypatch.setattr(server, "_API_KEY", None)
    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    monkeypatch.delenv("AIGUARD_AUDIT_STDOUT", raising=False)
    monkeypatch.setattr(
        service_module,
        "scan_outbound_leaks",
        lambda _text, _vault: [
            Entity(
                entity_id="synthetic-leak",
                redact_type="FP",
                data_type="THAI_ID",
                span=(0, 1),
                score=1.0,
                original_text="synthetic-checksum-value",
            )
        ],
    )

    response = TestClient(server.app, base_url="http://localhost").post(
        "/api/sanitize",
        json={"text": "โทร 081-234-5678", "mode": "token"},
    )

    assert response.status_code == 422
    assert service.session_count == 0
    paths = list(tmp_path.glob("audit_*_process.jsonl"))
    assert len(paths) == 1
    assert "081-234-5678" not in paths[0].name
    assert "synthetic-checksum-value" not in paths[0].name
    audit_text = paths[0].read_text(encoding="utf-8")
    record = json.loads(audit_text.splitlines()[-1])
    assert record["validation_result"] == "blocked"
    assert str(uuid.UUID(record["session_id"])) == record["session_id"]
    assert "081-234-5678" not in audit_text
    assert "synthetic-checksum-value" not in audit_text


def test_sanitize_writes_one_audit_record(tmp_path, monkeypatch):
    import app.server as server

    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))

    from fastapi.testclient import TestClient

    client = TestClient(server.app, base_url="http://localhost")
    resp = client.post(
        "/api/sanitize", json={"text": "ผมชื่อสมชาย ใจดี เบอร์ 0812345678", "mode": "token"}
    )
    assert resp.status_code == 200

    logs = list(tmp_path.glob("audit_*_process.jsonl"))
    assert len(logs) == 1
    rec = json.loads(logs[0].read_text(encoding="utf-8").splitlines()[0])
    assert rec["type"] == "process"
    assert rec["step"] == "api_sanitize"
    assert rec["entity_count"] >= 1
    # PII-free: the record must not contain the original phone number
    assert "0812345678" not in logs[0].read_text(encoding="utf-8")


def test_audit_log_endpoint_returns_safe_records(tmp_path, monkeypatch):
    import app.server as server

    monkeypatch.setattr(server, "_get_audit_log_dir", lambda: str(tmp_path))
    from fastapi.testclient import TestClient

    client = TestClient(server.app, base_url="http://localhost")
    client.post("/api/sanitize", json={"text": "ผมชื่อสมชาย เบอร์ 0812345678", "mode": "token"})

    resp = client.get("/api/audit-log?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] >= 1
    rec = data["logs"][0]
    assert rec["type"] == "process"
    assert "step" in rec and "entity_count" in rec and "timestamp" in rec
    assert "0812345678" not in resp.text  # no PII in the audit response
