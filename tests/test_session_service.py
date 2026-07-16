"""SessionService — the single core brain behind /api/sanitize and /api/reidentify."""
import pytest

from pii_redactor.session_service import (
    ModeMismatchError,
    SessionExpiredError,
    SessionService,
)


def _svc(**kw):
    clock = {"t": 1000.0}
    svc = SessionService(now_fn=lambda: clock["t"], **kw)
    return svc, clock


def test_create_session_defaults_to_token_mode():
    svc, _ = _svc()
    sid, session = svc._get_or_create(None, None)
    assert session.mode == "token"
    assert isinstance(sid, str) and len(sid) > 10


def test_reuse_session_inherits_mode():
    svc, _ = _svc()
    sid, _ = svc._get_or_create(None, "surrogate")
    sid2, session = svc._get_or_create(sid, None)
    assert sid2 == sid and session.mode == "surrogate"


def test_mode_conflict_raises():
    svc, _ = _svc()
    sid, _ = svc._get_or_create(None, "token")
    with pytest.raises(ModeMismatchError):
        svc._get_or_create(sid, "surrogate")


def test_unknown_session_raises_expired():
    svc, _ = _svc()
    with pytest.raises(SessionExpiredError):
        svc._get_or_create("does-not-exist", None)


def test_ttl_expiry_and_reset_on_access():
    svc, clock = _svc(ttl_s=100)
    sid, _ = svc._get_or_create(None, None)
    clock["t"] += 90
    svc._get_or_create(sid, None)          # access resets the idle timer
    clock["t"] += 90
    svc._get_or_create(sid, None)          # still alive
    clock["t"] += 101
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid, None)


def test_cap_evicts_oldest_and_clears_vault():
    svc, clock = _svc(cap=2)
    sid1, s1 = svc._get_or_create(None, None)
    clock["t"] += 1
    sid2, _ = svc._get_or_create(None, None)
    clock["t"] += 1
    from pii_redactor.models import VaultRecord
    import time as _time
    s1.vault.write(VaultRecord(entity_id="e1", original="ลับมาก",
                               pseudonym="[ชื่อ_1]", type="TB", data_type="NAME",
                               span=(0, 5), timestamp=_time.monotonic()))
    svc._get_or_create(None, None)         # third session evicts sid1
    assert svc.session_count == 2
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid1, None)
    # evicted vault was null-byte-cleared and emptied
    assert len(s1.vault._table) == 0


def test_drop_clears_and_reports():
    svc, _ = _svc()
    sid, session = svc._get_or_create(None, None)
    assert svc.drop(sid) is True
    assert svc.drop(sid) is False
    assert len(session.vault._table) == 0


def test_unknown_mode_raises():
    svc, _ = _svc()
    with pytest.raises(ModeMismatchError):
        svc._get_or_create(None, "Token")


def test_unknown_mode_at_capacity_does_not_evict():
    svc, clock = _svc(cap=1)
    sid1, _ = svc._get_or_create(None, None)
    clock["t"] += 1
    with pytest.raises(ModeMismatchError):
        svc._get_or_create(None, "Token")
    # the live session must have survived the malformed request
    sid_again, _ = svc._get_or_create(sid1, None)
    assert sid_again == sid1


from pii_redactor.session_service import OutboundLeakError, SanitizeOutcome


def test_sanitize_token_mode_v2_shape():
    svc, _ = _svc()
    out = svc.sanitize("ติดต่อ 081-234-5678 หรือ somchai@example.com")
    assert isinstance(out, SanitizeOutcome)
    assert "081-234-5678" not in out.sanitized_text
    assert "somchai@example.com" not in out.sanitized_text
    assert "[โทรศัพท์_1]" in out.sanitized_text
    assert "[อีเมล_1]" in out.sanitized_text
    for e in out.entities:
        assert set(e) == {"start", "end", "data_type", "redact_type", "token"}
    assert out.entity_type_counts["PHONE"] == 1
    assert out.warnings == []


def test_sanitize_surrogate_mode_no_brackets():
    svc, _ = _svc()
    out = svc.sanitize("ติดต่อ 081-234-5678", mode="surrogate")
    assert "081-234-5678" not in out.sanitized_text
    assert "[" not in out.sanitized_text


def test_sanitize_multi_turn_same_token():
    svc, _ = _svc()
    o1 = svc.sanitize("เบอร์ผม 081-234-5678")
    o2 = svc.sanitize("ย้ำ เบอร์ 081-234-5678 กับอีเมล a@b.co",
                      session_id=o1.session_id)
    assert o2.session_id == o1.session_id
    tok1 = next(e["token"] for e in o1.entities if e["data_type"] == "PHONE")
    tok2 = next(e["token"] for e in o2.entities if e["data_type"] == "PHONE")
    assert tok1 == tok2


def test_sanitize_registry_accumulates_across_turns():
    svc, _ = _svc()
    o1 = svc.sanitize("เบอร์ 081-234-5678")
    svc.sanitize("อีเมล a@b.co", session_id=o1.session_id)
    _, session = svc._get_or_create(o1.session_id, None)
    types = {e.data_type for e in session.entities}
    assert {"PHONE", "EMAIL"} <= types


def test_sanitize_raises_outbound_leak_when_fp_survives(monkeypatch):
    """If a checksum-valid FP value somehow survives anonymization, refuse."""
    import pii_redactor.session_service as svc_mod
    svc, _ = _svc()

    def fake_scan(text, vault):
        from pii_redactor.models import Entity
        return [Entity(entity_id="x", redact_type="FP", data_type="THAI_ID",
                       span=(0, 13), score=1.0, original_text="1101700230708")]

    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", fake_scan)
    with pytest.raises(OutboundLeakError) as exc:
        svc.sanitize("ข้อความอะไรก็ได้ 081-234-5678")
    assert "THAI_ID" in exc.value.leak_types
    assert "1101700230708" not in str(exc.value)  # no PII in the error


def test_sanitize_tb_leak_becomes_warning(monkeypatch):
    import pii_redactor.session_service as svc_mod
    svc, _ = _svc()

    def fake_scan(text, vault):
        from pii_redactor.models import Entity
        return [Entity(entity_id="x", redact_type="TB", data_type="NAME",
                       span=(0, 5), score=0.85, original_text="สมชาย")]

    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", fake_scan)
    out = svc.sanitize("ข้อความ 081-234-5678")
    assert out.warnings == ["possible_tb_leak:NAME"]
    assert "สมชาย" not in " ".join(out.warnings)
