"""SessionService — the single core brain behind /api/sanitize and /api/reidentify."""

from dataclasses import asdict

import pytest

import pii_redactor.session_service as svc_mod
import pii_redactor.stateless as stateless_mod
from pii_redactor.models import Entity
from pii_redactor.session_service import (
    ModeMismatchError,
    OutboundLeakError,
    RestoreTransactionError,
    SanitizeOutcome,
    SanitizeTransactionError,
    SessionExpiredError,
    SessionService,
)
from pii_redactor.session_vault import SessionVault, VaultTimeoutError


def _svc(**kw):
    clock = {"t": 1000.0}
    svc = SessionService(now_fn=lambda: clock["t"], **kw)
    return svc, clock


def _service_state(svc):
    """Serialize every session-owned field without touching access timers."""
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
                "trusted_sanitized_digests": session.trusted_sanitized_digests,
                "vault": {
                    "table": {
                        entity_id: asdict(record)
                        for entity_id, record in session.vault._table.items()
                    },
                    "reverse": dict(session.vault._reverse),
                    "last_access": session.vault._last_access,
                    "idle_timeout_s": session.vault._idle_timeout_s,
                    "session_id": session.vault.session_id,
                    "token_namespace": session.vault._token_namespace,
                    "clear_epoch": session.vault._clear_epoch,
                    "audit_entries": [entry._asdict() for entry in session.vault._audit_entries],
                },
            },
        )
        for sid, session in svc._sessions.items()
    ]


def _forced_stage_failure(*_args, **_kwargs):
    raise RuntimeError("forced transaction stage failure")


def _identity(outcome):
    return outcome


def _forced_fp_leak(_text, _vault):
    return [
        Entity(
            entity_id="synthetic-leak",
            redact_type="FP",
            data_type="THAI_ID",
            span=(0, 1),
            score=1.0,
            original_text="synthetic-checksum-value",
        )
    ]


def _product_traceback_locals(error):
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith(("pii_redactor.", "app.")):
            frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return frames


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
    svc._get_or_create(sid, None)  # access resets the idle timer
    clock["t"] += 90
    svc._get_or_create(sid, None)  # still alive
    clock["t"] += 101
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid, None)


def test_cap_evicts_oldest_and_clears_vault():
    svc, clock = _svc(cap=2)
    sid1, s1 = svc._get_or_create(None, None)
    clock["t"] += 1
    sid2, _ = svc._get_or_create(None, None)
    clock["t"] += 1
    import time as _time

    from pii_redactor.models import VaultRecord

    s1.vault.write(
        VaultRecord(
            entity_id="e1",
            original="ลับมาก",
            pseudonym="[ชื่อ_1]",
            type="TB",
            data_type="NAME",
            span=(0, 5),
            timestamp=_time.monotonic(),
        )
    )
    svc._get_or_create(None, None)  # third session evicts sid1
    assert svc.session_count == 2
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid1, None)
    # The evicted vault dropped its owned lookup references.
    assert len(s1.vault._table) == 0


def test_cap_evicts_least_recently_used_not_oldest_created():
    """VAULT-2: at cap the victim must be the LRU session (last_access), not the
    oldest-created — an old but actively-used session must survive."""
    svc, clock = _svc(cap=2)
    sid_a, _ = svc._get_or_create(None, None)  # created first
    clock["t"] += 1
    sid_b, _ = svc._get_or_create(None, None)
    clock["t"] += 1
    svc._get_or_create(sid_a, None)  # touch A — B is now least recently used
    clock["t"] += 1
    svc._get_or_create(None, None)  # third session: must evict B, not A
    sid_again, _ = svc._get_or_create(sid_a, None)
    assert sid_again == sid_a
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid_b, None)


def test_drop_blocks_while_restore_is_in_flight(monkeypatch):
    """VAULT-3: FastAPI runs sync endpoints in a threadpool, so drop/evict can
    race an in-flight restore. Without locking, drop clears the vault lookups
    mid-restore and the reply comes back with tokens unrestored."""
    import threading
    import time as _time

    import pii_redactor.session_service as svc_mod

    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")

    in_restore = threading.Event()
    release = threading.Event()
    real_reverse = svc_mod.reverse_map

    def slow_reverse(response, registry, vault, **kwargs):
        in_restore.set()
        release.wait(timeout=5)
        return real_reverse(response, registry, vault, **kwargs)

    monkeypatch.setattr(svc_mod, "reverse_map", slow_reverse)

    result = {}
    restorer = threading.Thread(
        target=lambda: result.update(r=svc.restore(out.session_id, out.sanitized_text))
    )
    restorer.start()
    assert in_restore.wait(timeout=5)
    dropper = threading.Thread(target=lambda: svc.drop(out.session_id))
    dropper.start()
    _time.sleep(0.05)  # give drop every chance to run — it must block on the lock
    release.set()
    restorer.join(timeout=5)
    dropper.join(timeout=5)
    assert "081-234-5678" in result["r"].restored_text


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


def test_sanitize_token_mode_v2_shape():
    svc, _ = _svc()
    out = svc.sanitize("ติดต่อ 081-234-5678 หรือ somchai@example.com")
    assert isinstance(out, SanitizeOutcome)
    assert "081-234-5678" not in out.sanitized_text
    assert "somchai@example.com" not in out.sanitized_text
    namespace = svc._sessions[out.session_id].vault.token_namespace
    phone_token = next(e["token"] for e in out.entities if e["data_type"] == "PHONE")
    email_token = next(e["token"] for e in out.entities if e["data_type"] == "EMAIL")
    assert phone_token.startswith(f"[โทรศัพท์_{namespace}_")
    assert email_token.startswith(f"[อีเมล_{namespace}_")
    assert phone_token.endswith("_1]") and email_token.endswith("_1]")
    assert phone_token in out.sanitized_text and email_token in out.sanitized_text
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
    o2 = svc.sanitize("ย้ำ เบอร์ 081-234-5678 กับอีเมล a@b.co", session_id=o1.session_id)
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

        return [
            Entity(
                entity_id="x",
                redact_type="FP",
                data_type="THAI_ID",
                span=(0, 13),
                score=1.0,
                original_text="1101700230708",
            )
        ]

    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", fake_scan)
    with pytest.raises(OutboundLeakError) as exc:
        svc.sanitize("ข้อความอะไรก็ได้ 081-234-5678")
    assert "THAI_ID" in exc.value.leak_types
    assert "1101700230708" not in str(exc.value)  # no PII in the error


def test_failed_new_sanitize_at_capacity_preserves_every_existing_session(monkeypatch):
    svc, clock = _svc(cap=2)
    active = svc.sanitize("โทร 081-234-5678")
    clock["t"] += 1
    lru = svc.sanitize("อีเมล first@example.com")
    lru_vault = svc._sessions[lru.session_id].vault
    clock["t"] += 1
    svc._get_or_create(active.session_id, None)
    before = _service_state(svc)
    clock["t"] += 10

    with monkeypatch.context() as patch:
        patch.setattr(svc_mod, "scan_outbound_leaks", _forced_fp_leak)
        with pytest.raises(OutboundLeakError):
            svc.sanitize("อีเมล second@example.com")

    assert svc.session_count == 2
    assert _service_state(svc) == before

    replacement = svc.sanitize("อีเมล second@example.com")
    assert active.session_id in svc._sessions
    assert lru.session_id not in svc._sessions
    assert replacement.session_id in svc._sessions
    assert lru_vault._table == {}
    assert lru_vault._reverse == {}


def test_post_publish_cleanup_failure_does_not_report_a_failed_request(
    monkeypatch,
    caplog,
):
    svc, _ = _svc(cap=1)
    evicted = svc.sanitize("โทร 081-234-5678")
    evicted_vault = svc._sessions[evicted.session_id].vault

    def fail_cleanup():
        raise RuntimeError("synthetic cleanup failure")

    monkeypatch.setattr(evicted_vault, "clear", fail_cleanup)
    replacement = svc.sanitize("อีเมล second@example.com")

    assert replacement.session_id in svc._sessions
    assert evicted.session_id not in svc._sessions
    assert svc.session_count == 1
    assert "Session vault cleanup did not complete" in caplog.text
    assert "081-234-5678" not in caplog.text
    assert "second@example.com" not in caplog.text


@pytest.mark.parametrize(
    "stage",
    [
        "detection",
        "anonymization",
        "residual_scan",
        "independent_residual_scan",
        "wire_projection",
        "section26",
        "finalize",
    ],
)
def test_existing_session_failure_preserves_complete_state(monkeypatch, stage):
    svc, clock = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    before = _service_state(svc)
    clock["t"] += 10
    finalize = _identity

    if stage == "detection":
        monkeypatch.setattr(stateless_mod, "detect_all", _forced_stage_failure)
    elif stage == "anonymization":
        real_anonymize = stateless_mod.anonymize

        def fail_after_vault_writes(*args, **kwargs):
            real_anonymize(*args, **kwargs)
            raise RuntimeError("forced transaction stage failure")

        monkeypatch.setattr(stateless_mod, "anonymize", fail_after_vault_writes)
    elif stage == "residual_scan":
        monkeypatch.setattr(svc_mod, "scan_outbound_leaks", _forced_stage_failure)
    elif stage == "independent_residual_scan":
        monkeypatch.setattr(
            svc_mod,
            "scan_residual_signals",
            _forced_stage_failure,
            raising=False,
        )
    elif stage == "wire_projection":
        monkeypatch.setattr(SessionVault, "get_by_entity_id", _forced_stage_failure)
    elif stage == "section26":
        monkeypatch.setattr(svc_mod, "scan_section26", _forced_stage_failure)
    else:
        finalize = _forced_stage_failure

    with pytest.raises(SanitizeTransactionError, match="sanitize transaction failed"):
        svc.sanitize_transaction(
            "อีเมล first@example.com",
            session_id=existing.session_id,
            finalize=finalize,
        )

    assert _service_state(svc) == before


def test_published_session_entities_are_immutable():
    svc, _ = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    entity = svc._sessions[existing.session_id].entities[0]

    with pytest.raises(AttributeError):
        entity.original_text = "mutated"


@pytest.mark.parametrize(
    "stage",
    [
        "detection",
        "anonymization",
        "residual_scan",
        "independent_residual_scan",
        "wire_projection",
        "section26",
        "finalize",
    ],
)
def test_new_session_failure_never_publishes_provisional_state(monkeypatch, stage):
    svc, _ = _svc()
    finalize = _identity

    if stage == "detection":
        monkeypatch.setattr(stateless_mod, "detect_all", _forced_stage_failure)
    elif stage == "anonymization":
        real_anonymize = stateless_mod.anonymize

        def fail_after_vault_writes(*args, **kwargs):
            real_anonymize(*args, **kwargs)
            raise RuntimeError("forced transaction stage failure")

        monkeypatch.setattr(stateless_mod, "anonymize", fail_after_vault_writes)
    elif stage == "residual_scan":
        monkeypatch.setattr(svc_mod, "scan_outbound_leaks", _forced_stage_failure)
    elif stage == "independent_residual_scan":
        monkeypatch.setattr(
            svc_mod,
            "scan_residual_signals",
            _forced_stage_failure,
            raising=False,
        )
    elif stage == "wire_projection":
        monkeypatch.setattr(SessionVault, "get_by_entity_id", _forced_stage_failure)
    elif stage == "section26":
        monkeypatch.setattr(svc_mod, "scan_section26", _forced_stage_failure)
    else:
        finalize = _forced_stage_failure

    with pytest.raises(SanitizeTransactionError, match="sanitize transaction failed"):
        svc.sanitize_transaction(
            "อีเมล first@example.com",
            finalize=finalize,
        )

    assert _service_state(svc) == []


def test_failed_sanitize_does_not_consume_the_next_token_ordinal(monkeypatch):
    svc, _ = _svc()
    existing = svc.sanitize("โทร 081-234-5678")

    with monkeypatch.context() as patch:
        patch.setattr(svc_mod, "scan_outbound_leaks", _forced_fp_leak)
        with pytest.raises(OutboundLeakError):
            svc.sanitize(
                "อีเมล first@example.com",
                session_id=existing.session_id,
            )

    after = svc.sanitize(
        "อีเมล second@example.com",
        session_id=existing.session_id,
    )
    email_token = next(
        entity["token"] for entity in after.entities if entity["data_type"] == "EMAIL"
    )
    namespace = svc._sessions[existing.session_id].vault.token_namespace
    assert email_token.startswith(f"[อีเมล_{namespace}_")
    assert email_token.endswith("_1]")


def test_token_nonce_exhaustion_is_value_free_and_does_not_publish(monkeypatch):
    import pii_redactor.anonymizer.anonymizer as anonymizer_mod
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import generate_token

    namespace = "a" * 25
    nonce = "n" * 20
    collision = generate_token("EMAIL", 1, namespace=namespace, nonce=nonce)
    source = f"a@b.co {collision}"
    entity = Entity(
        entity_id="synthetic-entity",
        redact_type="FP",
        data_type="EMAIL",
        span=(0, 6),
        score=1.0,
        original_text="a@b.co",
    )
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: namespace)
    monkeypatch.setattr(anonymizer_mod, "new_token_nonce", lambda: nonce)
    monkeypatch.setattr(stateless_mod, "detect_all", lambda _text: [entity])
    service, _ = _svc()

    with pytest.raises(
        OutboundLeakError,
        match=r"^outbound residual risk: \['ANONYMIZE_FAILED'\]$",
    ) as excinfo:
        service.sanitize(source, mode="token")

    assert service.session_count == 0
    assert excinfo.value.leak_types == ["ANONYMIZE_FAILED"]
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert "a@b.co" not in str(excinfo.value)
    assert collision not in str(excinfo.value)


def test_residual_error_graph_drops_input_and_staged_service_state(monkeypatch):
    svc, _ = _svc()
    residual = "โทร 081-234-5678"
    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", _forced_fp_leak)

    with pytest.raises(OutboundLeakError) as excinfo:
        svc.sanitize(residual)

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(svc is not value for frame in frame_locals for value in frame.values())
    assert residual not in repr(frame_locals)
    assert svc.session_count == 0


def test_retained_finalizer_exception_cannot_keep_transaction_graph():
    svc, _ = _svc()
    request_text = "อีเมล retained@example.invalid"
    retained_error = RuntimeError("synthetic finalizer failure")

    def fail_finalize(_outcome):
        raise retained_error

    with pytest.raises(SanitizeTransactionError) as excinfo:
        svc.sanitize_transaction(
            request_text,
            finalize=fail_finalize,
        )

    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(svc is not value for frame in frame_locals for value in frame.values())
    assert request_text not in repr(frame_locals)
    assert svc.session_count == 0


@pytest.mark.parametrize("boundary", ["section26", "finalizer"])
def test_non_vault_timeout_name_collision_preserves_published_state(
    monkeypatch,
    boundary,
):
    svc, clock = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    before = _service_state(svc)
    clock["t"] += 10

    def fail_with_timeout(*_args, **_kwargs):
        raise VaultTimeoutError(f"synthetic {boundary} failure")

    finalize = _identity
    if boundary == "section26":
        monkeypatch.setattr(svc_mod, "scan_section26", fail_with_timeout)
    else:
        finalize = fail_with_timeout

    with pytest.raises(SanitizeTransactionError, match="sanitize transaction failed"):
        svc.sanitize_transaction(
            "อีเมล first@example.com",
            session_id=existing.session_id,
            finalize=finalize,
        )

    assert _service_state(svc) == before


def test_detector_vault_timeout_name_collision_preserves_published_state(monkeypatch):
    svc, clock = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    before = _service_state(svc)
    clock["t"] += 10

    def fail_detection(*_args, **_kwargs):
        raise VaultTimeoutError("synthetic detector failure")

    monkeypatch.setattr(stateless_mod, "detect_all", fail_detection)
    with pytest.raises(SanitizeTransactionError, match="sanitize transaction failed"):
        svc.sanitize(
            "อีเมล first@example.com",
            session_id=existing.session_id,
        )

    assert _service_state(svc) == before


def test_restore_cannot_observe_a_failed_transaction_staging():
    import threading
    import time as _time

    svc, _ = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    finalize_started = threading.Event()
    release_finalize = threading.Event()
    transaction_error = []
    restore_result = []

    def fail_after_pause(_outcome):
        finalize_started.set()
        release_finalize.wait(timeout=5)
        raise RuntimeError("forced transaction stage failure")

    def run_transaction():
        try:
            svc.sanitize_transaction(
                "อีเมล first@example.com",
                session_id=existing.session_id,
                finalize=fail_after_pause,
            )
        except RuntimeError as exc:
            transaction_error.append(exc)

    transaction = threading.Thread(target=run_transaction)
    transaction.start()
    assert finalize_started.wait(timeout=5)

    restorer = threading.Thread(
        target=lambda: restore_result.append(
            svc.restore(
                existing.session_id,
                f"{existing.sanitized_text} [อีเมล_1]",
            )
        )
    )
    restorer.start()
    _time.sleep(0.05)
    assert restore_result == []
    assert restorer.is_alive()

    release_finalize.set()
    transaction.join(timeout=5)
    restorer.join(timeout=5)

    assert not transaction.is_alive()
    assert not restorer.is_alive()
    assert transaction_error
    assert "081-234-5678" in restore_result[0].restored_text
    assert "[อีเมล_1]" in restore_result[0].restored_text


def test_drop_cannot_run_while_transaction_state_is_staged():
    import threading
    import time as _time

    svc, _ = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    finalize_started = threading.Event()
    release_finalize = threading.Event()
    dropped = []
    transaction_error = []

    def fail_after_pause(_outcome):
        finalize_started.set()
        release_finalize.wait(timeout=5)
        raise RuntimeError("forced transaction stage failure")

    def run_transaction():
        try:
            svc.sanitize_transaction(
                "อีเมล first@example.com",
                session_id=existing.session_id,
                finalize=fail_after_pause,
            )
        except RuntimeError as exc:
            transaction_error.append(exc)

    transaction = threading.Thread(target=run_transaction)
    transaction.start()
    assert finalize_started.wait(timeout=5)

    dropper = threading.Thread(target=lambda: dropped.append(svc.drop(existing.session_id)))
    dropper.start()
    _time.sleep(0.05)
    assert dropped == []
    assert dropper.is_alive()

    release_finalize.set()
    transaction.join(timeout=5)
    dropper.join(timeout=5)

    assert not transaction.is_alive()
    assert not dropper.is_alive()
    assert transaction_error
    assert dropped == [True]
    assert svc.session_count == 0


def test_sanitize_tb_leak_blocks_without_publishing_session(monkeypatch):
    import pii_redactor.session_service as svc_mod

    svc, _ = _svc()

    def fake_scan(text, vault):
        from pii_redactor.models import Entity

        return [
            Entity(
                entity_id="x",
                redact_type="TB",
                data_type="NAME",
                span=(0, 5),
                score=0.85,
                original_text="สมชาย",
            )
        ]

    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", fake_scan)
    with pytest.raises(OutboundLeakError) as excinfo:
        svc.sanitize("ข้อความ 081-234-5678")

    assert excinfo.value.leak_types == ["NAME"]
    assert "สมชาย" not in str(excinfo.value)
    assert svc.session_count == 0


def test_detector_independent_residual_preserves_existing_session(monkeypatch):
    svc, clock = _svc()
    existing = svc.sanitize("โทร 081-234-5678")
    before = _service_state(svc)
    clock["t"] += 10
    monkeypatch.setattr(
        svc_mod,
        "scan_residual_signals",
        lambda _text, _vault: ["orphan_digits:7"],
        raising=False,
    )

    with pytest.raises(OutboundLeakError) as excinfo:
        svc.sanitize("เอกสารหมายเลข 6801234", session_id=existing.session_id)

    assert excinfo.value.leak_types == ["ORPHAN_DIGITS"]
    assert "6801234" not in str(excinfo.value)
    assert _service_state(svc) == before


from pii_redactor.session_service import RestoreOutcome


def test_restore_round_trip_token_mode():
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678 อีเมล a@b.co")
    ai_reply = f"สรุปให้: ติดต่อที่ {out.sanitized_text} นะครับ"
    r = svc.restore(out.session_id, ai_reply)
    assert isinstance(r, RestoreOutcome)
    assert "081-234-5678" in r.restored_text
    assert "a@b.co" in r.restored_text
    assert r.replaced_count >= 2
    assert not hasattr(r, "replaced")
    assert r.leftover_tokens == []


def test_restore_partial_reply_restores_what_it_can():
    """AI reply that mangles one token: the intact token still restores and
    the incomplete-reverse condition surfaces as a warning, never an error."""
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678 อีเมล a@b.co")
    phone_token = next(e["token"] for e in out.entities if e["data_type"] == "PHONE")
    email_token = next(e["token"] for e in out.entities if e["data_type"] == "EMAIL")
    reply = f"{phone_token} และ {email_token[:-1]}}}"  # email token mangled
    r = svc.restore(out.session_id, reply)
    assert phone_token not in r.restored_text
    assert "081-234-5678" in r.restored_text
    assert "a@b.co" not in r.restored_text
    assert not any(w.startswith(("incomplete_reverse", "possible_truncation")) for w in r.warnings)


def test_restore_unknown_session_raises():
    svc, _ = _svc()
    with pytest.raises(SessionExpiredError):
        svc.restore("nope", "text")


def test_restore_warns_on_ai_generated_pii():
    """AI reply contains a checksum-valid Thai ID that is NOT in the vault —
    inbound data, so warn (never block)."""
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    reply = f"{out.sanitized_text} และเลขบัตร 1101700230708"
    r = svc.restore(out.session_id, reply)
    assert "081-234-5678" in r.restored_text
    assert any(w.startswith("ai_generated_pii") for w in r.warnings)


def test_restore_warns_when_ai_duplicates_a_known_original():
    svc, _ = _svc()
    original = "081-234-5678"
    out = svc.sanitize(f"เบอร์ {original}")
    reply = f"{out.sanitized_text} สำรอง {original}"

    restored = svc.restore(out.session_id, reply)

    assert restored.restored_text.count(original) == 2
    assert restored.generated_pii_count >= 1
    assert "ai_generated_pii" in restored.warnings


def test_restore_warns_on_ai_generated_text_based_pii():
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    reply = f"{out.sanitized_text} และ นายสมหญิง ทดสอบดี"

    restored = svc.restore(out.session_id, reply)

    assert restored.leftover_tokens == []
    assert restored.generated_pii_count == 1
    assert "ai_generated_pii" in restored.warnings


def test_restore_warning_discards_retained_validator_exception(monkeypatch):
    from pii_redactor.output_validator import PIILeakError as OutputPIILeakError

    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    retained_error = OutputPIILeakError("synthetic validator failure")

    def fail_validation(*_args, **_kwargs):
        raise retained_error

    monkeypatch.setattr(svc_mod, "validate_output", fail_validation)
    restored = svc.restore(out.session_id, out.sanitized_text + " safe")

    assert "ai_generated_pii" in restored.warnings
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None


def test_restore_exact_successful_sanitize_skips_generated_output_scan(monkeypatch):
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("known sanitized output must not need a generated-output scan")

    monkeypatch.setattr(svc_mod, "validate_output", forbidden)

    restored = svc.restore(out.session_id, out.sanitized_text)

    assert restored.restored_text == "เบอร์ 081-234-5678"
    assert restored.generated_pii_count == 0


@pytest.mark.parametrize("replacement_mode", ["token", "surrogate"])
@pytest.mark.parametrize("lifecycle", ["drop", "restart", "expiry", "eviction"])
def test_replacement_session_cannot_silently_restore_an_old_token_to_new_data(
    monkeypatch,
    lifecycle,
    replacement_mode,
):
    import pii_redactor.session_vault as vault_mod

    namespaces = iter(("a" * 25, "f" * 25))
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: next(namespaces))
    service, clock = _svc(cap=1, ttl_s=10)
    old = service.sanitize("รายการเดิม โทร 081-234-5678", mode="token")
    old_masked_text = old.sanitized_text

    if lifecycle == "drop":
        assert service.drop(old.session_id)
        replacement = service.sanitize(
            "รายการใหม่ โทร 089-765-4321",
            mode=replacement_mode,
        )
    elif lifecycle == "restart":
        service, _ = _svc(cap=1, ttl_s=10)
        replacement = service.sanitize(
            "รายการใหม่ โทร 089-765-4321",
            mode=replacement_mode,
        )
    elif lifecycle == "expiry":
        clock["t"] += 11
        with pytest.raises(SessionExpiredError):
            service.restore(old.session_id, old_masked_text)
        replacement = service.sanitize(
            "รายการใหม่ โทร 089-765-4321",
            mode=replacement_mode,
        )
    else:
        replacement = service.sanitize(
            "รายการใหม่ โทร 089-765-4321",
            mode=replacement_mode,
        )

    restored = service.restore(replacement.session_id, old_masked_text)

    assert old.sanitized_text != replacement.sanitized_text.replace("รายการใหม่", "รายการเดิม")
    assert restored.restored_text == old_masked_text
    assert restored.replaced_count == 0
    assert restored.foreign_replacement_count == 1
    assert "foreign_tokens:1" in restored.warnings


def test_foreign_future_token_cannot_become_trusted_later_in_same_session(
    monkeypatch,
):
    import pii_redactor.anonymizer.anonymizer as anonymizer_mod
    from pii_redactor.anonymizer.token_generator import generate_token

    nonces = iter(("a" * 20, "b" * 20))
    monkeypatch.setattr(anonymizer_mod, "new_token_nonce", lambda: next(nonces))
    service, _ = _svc()
    first = service.sanitize("โทร 081-234-5678", mode="token")
    namespace = service._sessions[first.session_id].vault.token_namespace
    predicted = generate_token(
        "EMAIL",
        1,
        namespace=namespace,
        nonce="z" * 20,
    )
    retained_reply = f"{first.sanitized_text} {predicted}"

    before = service.restore(first.session_id, retained_reply)
    assert before.foreign_replacement_count == 1

    later = service.sanitize(
        "อีเมล a@b.co",
        session_id=first.session_id,
        mode="token",
    )
    email_token = next(item["token"] for item in later.entities if item["data_type"] == "EMAIL")
    after = service.restore(first.session_id, retained_reply)

    assert email_token != predicted
    assert "a@b.co" not in after.restored_text
    assert predicted in after.restored_text
    assert after.foreign_replacement_count == 1
    assert "foreign_tokens:1" in after.warnings


def test_session_bounds_trusted_sanitized_digests():
    svc, _ = _svc()
    out = None
    for index in range(svc_mod._TRUSTED_SANITIZED_DIGEST_LIMIT + 3):
        out = svc.sanitize(
            f"ครั้ง {index} โทร 081-234-{5600 + index}",
            session_id=None if out is None else out.session_id,
        )

    assert out is not None
    session = svc._sessions[out.session_id]
    assert len(session.trusted_sanitized_digests) == svc_mod._TRUSTED_SANITIZED_DIGEST_LIMIT
    assert len(set(session.trusted_sanitized_digests)) == len(session.trusted_sanitized_digests)


def test_restore_multi_turn_uses_accumulated_registry():
    svc, _ = _svc()
    o1 = svc.sanitize("เบอร์ 081-234-5678")
    o2 = svc.sanitize("อีเมล a@b.co", session_id=o1.session_id)
    combined = o1.sanitized_text + " " + o2.sanitized_text
    r = svc.restore(o1.session_id, combined)
    assert "081-234-5678" in r.restored_text and "a@b.co" in r.restored_text


def test_restore_idle_vault_translates_to_session_expired():
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    _, session = svc._get_or_create(out.session_id, None)
    session.vault._idle_timeout_s = 0
    session.vault._last_access -= 1
    with pytest.raises(SessionExpiredError):
        svc.restore(out.session_id, out.sanitized_text)
    assert svc.session_count == 0  # dead session was dropped


@pytest.mark.parametrize("entrypoint", ["restore", "_restore_locked"])
def test_restore_error_graph_drops_reply_and_live_session_state(monkeypatch, entrypoint):
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    session = svc._sessions[out.session_id]
    vault = session.vault
    before = _service_state(svc)
    reply = f"คำตอบ {out.sanitized_text}"
    retained_error = RuntimeError("synthetic restore failure")

    def fail_restore(response, _registry, active_vault, **_kwargs):
        hidden_reply = response.text
        hidden_service = svc
        hidden_session = session
        hidden_vault = active_vault
        assert hidden_reply and hidden_service and hidden_session and hidden_vault
        raise retained_error

    monkeypatch.setattr(svc_mod, "reverse_map", fail_restore)

    with pytest.raises(RestoreTransactionError, match="^restore failed$") as excinfo:
        if entrypoint == "restore":
            svc.restore(out.session_id, reply)
        else:
            with svc._lock:
                svc._restore_locked(out.session_id, reply)

    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    sensitive_objects = (svc, session, vault)
    assert all(
        value is not sensitive
        for frame in frame_locals
        for value in frame.values()
        for sensitive in sensitive_objects
    )
    assert reply not in repr(frame_locals)
    assert _service_state(svc) == before


@pytest.mark.parametrize("entrypoint", ["restore", "_restore_locked"])
def test_restore_vault_timeout_translation_has_no_exception_context(monkeypatch, entrypoint):
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    session = svc._sessions[out.session_id]
    vault = session.vault
    reply = f"คำตอบ {out.sanitized_text}"
    retained_timeout = VaultTimeoutError("synthetic vault timeout")

    def fail_restore(response, _registry, active_vault, **_kwargs):
        hidden_reply = response.text
        hidden_service = svc
        hidden_session = session
        hidden_vault = active_vault
        assert hidden_reply and hidden_service and hidden_session and hidden_vault
        raise retained_timeout

    monkeypatch.setattr(svc_mod, "reverse_map", fail_restore)

    with pytest.raises(
        SessionExpiredError,
        match="^Session not found or expired$",
    ) as excinfo:
        if entrypoint == "restore":
            svc.restore(out.session_id, reply)
        else:
            with svc._lock:
                svc._restore_locked(out.session_id, reply)

    assert retained_timeout.__traceback__ is None
    assert retained_timeout.__cause__ is None
    assert retained_timeout.__context__ is None
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    sensitive_objects = (svc, session, vault)
    assert all(
        value is not sensitive
        for frame in frame_locals
        for value in frame.values()
        for sensitive in sensitive_objects
    )
    assert reply not in repr(frame_locals)
    assert svc.session_count == 0
    assert vault._table == {}
    assert vault._reverse == {}


def test_sanitize_idle_vault_translates_to_session_expired():
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    _, session = svc._get_or_create(out.session_id, None)
    session.vault._idle_timeout_s = 0
    session.vault._last_access -= 1
    with pytest.raises(SessionExpiredError):
        svc.sanitize("อีเมล a@b.co", session_id=out.session_id)


def test_restore_happy_path_has_no_warnings():
    svc, _ = _svc()
    o1 = svc.sanitize("ผมชื่อ สมชาย ใจดี เบอร์ 081-234-5678")
    o2 = svc.sanitize("ย้ำ เบอร์ 081-234-5678 ครับ", session_id=o1.session_id)
    reply = f"สรุป: {o1.sanitized_text} / {o2.sanitized_text}"
    r = svc.restore(o1.session_id, reply)
    assert "081-234-5678" in r.restored_text
    assert r.warnings == []


def test_surrogate_same_original_consistent_across_turns():
    svc, _ = _svc()
    o1 = svc.sanitize("นาย สมชาย ใจดี มาติดต่อ", mode="surrogate")
    o2 = svc.sanitize("สมชาย ใจดี โทรมาอีกครั้ง", session_id=o1.session_id)
    _, session = svc._get_or_create(o1.session_id, None)
    name_records = [
        r
        for r in session.vault._table.values()
        if r.data_type == "NAME" and r.original == "สมชาย ใจดี"
    ]
    assert len({r.pseudonym for r in name_records}) <= 1


def test_restore_empty_text_returns_empty_outcome():
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    r = svc.restore(out.session_id, "")
    assert r.restored_text == "" and r.replaced_count == 0 and r.warnings == []
    with pytest.raises(SessionExpiredError):
        svc.restore("unknown", "")
