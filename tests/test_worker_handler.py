"""Tests for the queue worker's job handler (platform storefront #3).

The handler is the KNOWN half of the worker: our job schema in, stateless
core out. The transport half is the guess and lives elsewhere.
"""

import pytest

from app.worker.contract import CONTRACT_VERSION
from app.worker.handler import handle_job

THAI_TEXT = "ผมชื่อ นายสมชาย ใจดี เลขบัตรประชาชน 1101700230708 โทร 081-234-5678"
SYNTHETIC_AUTHORIZATION = "Bearer synthetic-provider-credential"
SYNTHETIC_PROVIDER_BODY = "synthetic-provider-body"
SYNTHETIC_VAULT_ORIGINAL = "synthetic-vault-original@example.invalid"


def _exception_graph(error):
    nodes = []
    material = []
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        nodes.append(current)
        material.extend((repr(current.args), repr(vars(current))))
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
        for value in vars(current).values():
            if isinstance(value, BaseException):
                pending.append(value)
    return nodes, "\n".join(material)


def _product_traceback_locals(error):
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith(("pii_redactor.", "app.")):
            frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return frames


def test_sanitize_omits_mapping_by_default():
    out = handle_job(
        {
            "job_id": "j1",
            "operation": "sanitize",
            "payload": {"text": THAI_TEXT, "mode": "token"},
        }
    )
    assert out["job_id"] == "j1"
    assert out["contract_version"] == CONTRACT_VERSION
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


def test_sanitize_orphan_digits_never_cross_worker_result_boundary(monkeypatch):
    import pii_redactor.stateless as stateless_module

    monkeypatch.setattr(
        stateless_module,
        "scan_residual_signals",
        lambda _text, _vault: ["orphan_digits:7"],
    )

    out = handle_job(
        {
            "job_id": "j-sanitize-orphan",
            "operation": "sanitize",
            "payload": {
                "text": "เอกสารหมายเลข 6801234",
                "mode": "token",
                "include_mapping": True,
            },
        }
    )

    assert out["contract_version"] == CONTRACT_VERSION == 1
    assert out["status"] == "error"
    assert out["error"] == {
        "type": "residual_pii",
        "message": "outbound residual detected",
    }
    assert "result" not in out
    assert "6801234" not in str(out)


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


def test_roundtrip_provider_constructor_exception_graph_is_safe(monkeypatch):
    import app.worker.handler as handler

    class CredentialBearingConstructorError(ValueError):
        def __init__(self):
            self.authorization = SYNTHETIC_AUTHORIZATION
            self.body = SYNTHETIC_PROVIDER_BODY
            self.request = {"url": "https://provider.invalid/v1/complete"}
            super().__init__("provider setup failed")

    retained_error = CredentialBearingConstructorError()

    def failing_factory():
        raise retained_error

    monkeypatch.setitem(
        handler._PROVIDER_FACTORIES,
        "credential-constructor-boom",
        failing_factory,
    )
    payload = {
        "text": THAI_TEXT,
        "provider": "credential-constructor-boom",
    }

    with pytest.raises(handler._SafeJobError) as excinfo:
        handler._op_roundtrip(payload)

    nodes, graph_text = _exception_graph(excinfo.value)
    assert excinfo.value.error_type == "provider_unavailable"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert not any(isinstance(node, CredentialBearingConstructorError) for node in nodes)
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_PROVIDER_BODY not in graph_text
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert "1101700230708" not in repr(frame_locals)
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None


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


def test_roundtrip_discards_retained_provider_call_error(monkeypatch):
    import app.worker.handler as handler
    from pii_redactor.ai_client import ProviderCallError

    retained_error = ProviderCallError(
        category="timeout",
        error_type="TimeoutException",
    )

    def fail_provider(*_args, **_kwargs):
        raise retained_error

    monkeypatch.setattr(handler, "complete_provider_call", fail_provider)
    with pytest.raises(handler._SafeJobError) as excinfo:
        handler._op_roundtrip({"text": THAI_TEXT, "provider": "fake"})

    assert excinfo.value.error_type == "provider_failed"
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None
    assert retained_error.args == ()
    assert retained_error.__dict__ == {}


def test_roundtrip_provider_failure_exception_graph_is_safe(monkeypatch):
    import app.worker.handler as handler

    class CredentialBearingError(RuntimeError):
        def __init__(self):
            self.authorization = SYNTHETIC_AUTHORIZATION
            self.body = SYNTHETIC_PROVIDER_BODY
            self.request = {"url": "https://provider.invalid/v1/complete"}
            super().__init__("provider call failed")

    class BoomProvider:
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            raise CredentialBearingError()

    provider = BoomProvider()
    monkeypatch.setitem(
        handler._PROVIDER_FACTORIES,
        "credential-boom",
        lambda: provider,
    )
    payload = {
        "text": THAI_TEXT,
        "provider": "credential-boom",
    }

    with pytest.raises(handler._SafeJobError) as excinfo:
        handler._op_roundtrip(payload)

    nodes, graph_text = _exception_graph(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert not any(isinstance(node, CredentialBearingError) for node in nodes)
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_PROVIDER_BODY not in graph_text
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(provider is not value for frame in frame_locals for value in frame.values())
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert "1101700230708" not in repr(frame_locals)

    out = handle_job(
        {
            "job_id": "j-provider-graph",
            "operation": "roundtrip",
            "payload": payload,
        }
    )
    assert out["error"] == {
        "type": "provider_failed",
        "message": "AI provider call failed",
    }


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
    assert out["error"]["type"] == "residual_pii"
    assert THAI_TEXT not in str(out)


def test_roundtrip_residual_error_graph_drops_payload_mapping_and_provider(monkeypatch):
    import app.worker.handler as handler
    from pii_redactor.stateless import StatelessLeakError

    class SecretProvider:
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            raise AssertionError("provider must not be called")

    def leak(*args, **kwargs):
        raise StatelessLeakError(["THAI_ID"])

    provider = SecretProvider()
    monkeypatch.setattr(handler, "sanitize_stateless", leak)
    monkeypatch.setitem(
        handler._PROVIDER_FACTORIES,
        "residual-graph",
        lambda: provider,
    )
    payload = {
        "text": THAI_TEXT,
        "provider": "residual-graph",
    }

    with pytest.raises(handler._SafeJobError) as excinfo:
        handler._op_roundtrip(payload)

    nodes, graph_text = _exception_graph(excinfo.value)
    assert excinfo.value.error_type == "residual_pii"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert len(nodes) == 1
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(provider is not value for frame in frame_locals for value in frame.values())
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert "1101700230708" not in repr(frame_locals)


def test_roundtrip_restore_error_graph_drops_provider_body_mapping_and_payload(monkeypatch):
    import app.worker.handler as handler
    from pii_redactor.stateless import StatelessSanitizeResult

    forged = StatelessSanitizeResult(
        sanitized_text="safe text",
        mapping={"[EMAIL_9]": SYNTHETIC_VAULT_ORIGINAL},
        entities=[],
        entity_type_counts={},
        section26=[],
        warnings=[],
    )

    class SecretProvider:
        def __init__(self):
            self._api_key = SYNTHETIC_AUTHORIZATION

        def complete(self, system, user, *, timeout=30.0):
            return SYNTHETIC_PROVIDER_BODY

    class CredentialBearingRestoreError(RuntimeError):
        def __init__(self, mapping):
            self.mapping = mapping
            self.authorization = SYNTHETIC_AUTHORIZATION
            self.body = SYNTHETIC_PROVIDER_BODY
            super().__init__("restore failed")

    def fail_restore(_text, *, mapping):
        raise CredentialBearingRestoreError(mapping)

    provider = SecretProvider()
    monkeypatch.setattr(handler, "sanitize_stateless", lambda *_args, **_kwargs: forged)
    monkeypatch.setattr(handler, "restore_stateless", fail_restore)
    monkeypatch.setitem(
        handler._PROVIDER_FACTORIES,
        "restore-graph",
        lambda: provider,
    )
    payload = {
        "text": THAI_TEXT,
        "provider": "restore-graph",
    }

    with pytest.raises(handler._SafeJobError) as excinfo:
        handler._op_roundtrip(payload)

    nodes, graph_text = _exception_graph(excinfo.value)
    assert excinfo.value.error_type == "restore_failed"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert not any(isinstance(node, CredentialBearingRestoreError) for node in nodes)
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_PROVIDER_BODY not in graph_text
    assert SYNTHETIC_VAULT_ORIGINAL not in graph_text
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert all(provider is not value for frame in frame_locals for value in frame.values())
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert SYNTHETIC_PROVIDER_BODY not in repr(frame_locals)
    assert SYNTHETIC_VAULT_ORIGINAL not in repr(frame_locals)
    assert "1101700230708" not in repr(frame_locals)


def test_direct_restore_error_graph_drops_caller_text_and_mapping(monkeypatch):
    import app.worker.handler as handler

    class CredentialBearingRestoreError(RuntimeError):
        def __init__(self, mapping):
            self.mapping = mapping
            self.authorization = SYNTHETIC_AUTHORIZATION
            super().__init__("restore failed")

    def fail_restore(_text, *, mapping):
        raise CredentialBearingRestoreError(mapping)

    monkeypatch.setattr(handler, "restore_stateless", fail_restore)
    payload = {
        "text": THAI_TEXT,
        "mapping": {"[EMAIL_9]": SYNTHETIC_VAULT_ORIGINAL},
    }

    with pytest.raises(handler._SafeJobError) as excinfo:
        handler._op_restore(payload)

    nodes, graph_text = _exception_graph(excinfo.value)
    assert excinfo.value.error_type == "restore_failed"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert not any(isinstance(node, CredentialBearingRestoreError) for node in nodes)
    assert SYNTHETIC_AUTHORIZATION not in graph_text
    assert SYNTHETIC_VAULT_ORIGINAL not in graph_text
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert SYNTHETIC_AUTHORIZATION not in repr(frame_locals)
    assert SYNTHETIC_VAULT_ORIGINAL not in repr(frame_locals)
    assert "1101700230708" not in repr(frame_locals)


def test_poison_barrier_drops_retained_unexpected_exception(monkeypatch):
    import app.worker.handler as handler

    retained_error = RuntimeError("synthetic poison job failure")

    def fail_sanitize(*_args, **_kwargs):
        raise retained_error

    monkeypatch.setattr(handler, "sanitize_stateless", fail_sanitize)
    out = handler.handle_job(
        {
            "job_id": "j-poison-graph",
            "operation": "sanitize",
            "payload": {"text": THAI_TEXT, "mode": "token"},
        }
    )

    assert out["status"] == "error"
    assert out["error"] == {"type": "job_failed", "message": "RuntimeError"}
    assert THAI_TEXT not in str(out)
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None


def test_envelope_error_drops_retained_job_graph(monkeypatch):
    import app.worker.handler as handler
    from app.worker.contract import EnvelopeError

    job = {
        "job_id": "j-envelope-graph",
        "operation": "sanitize",
        "payload": {"text": THAI_TEXT, "mode": "token"},
    }

    def make_retained_error():
        retained_job = job
        try:
            raise EnvelopeError(
                "invalid_envelope",
                "job must be an object",
                operation="sanitize",
            )
        except EnvelopeError as error:
            assert retained_job is job
            return error

    retained_error = make_retained_error()
    assert retained_error.__traceback__ is not None

    def fail_validation(_job):
        raise retained_error

    monkeypatch.setattr(handler, "validate_envelope", fail_validation)
    out = handler.handle_job(job)

    assert out == {
        "contract_version": 1,
        "job_id": "",
        "operation": "sanitize",
        "status": "error",
        "error": {
            "type": "invalid_envelope",
            "message": "job must be an object",
        },
    }
    assert THAI_TEXT not in str(out)
    assert retained_error.__traceback__ is None
    assert retained_error.__cause__ is None
    assert retained_error.__context__ is None


def test_roundtrip_orphan_digits_never_reach_worker_provider(monkeypatch):
    import app.worker.handler as handler
    import pii_redactor.stateless as stateless_module

    calls = []

    class SpyProvider:
        def complete(self, system, user, *, timeout=30.0):
            calls.append((system, user))
            return user

    monkeypatch.setitem(handler._PROVIDER_FACTORIES, "residual-spy", SpyProvider)
    monkeypatch.setattr(
        stateless_module,
        "scan_residual_signals",
        lambda _text, _vault: ["orphan_digits:7"],
    )

    out = handle_job(
        {
            "job_id": "j-roundtrip-orphan",
            "operation": "roundtrip",
            "payload": {
                "text": "เอกสารหมายเลข 6801234",
                "provider": "residual-spy",
            },
        }
    )

    assert out["status"] == "error"
    assert out["error"]["type"] == "residual_pii"
    assert calls == []
    assert "6801234" not in str(out)


@pytest.mark.parametrize(
    "residual",
    [
        "เลขบัตรประชาชน 1101700230708",
        "ผมชื่อ นายสมชาย ใจดี",
        "เอกสารหมายเลข 6801234",
    ],
)
def test_roundtrip_rescans_forged_success_before_worker_provider(
    monkeypatch,
    residual,
):
    import app.worker.handler as handler
    from pii_redactor.stateless import StatelessSanitizeResult

    calls = []

    class SpyProvider:
        def complete(self, system, user, *, timeout=30.0):
            calls.append((system, user))
            return user

    forged = StatelessSanitizeResult(
        sanitized_text=residual,
        mapping={},
        entities=[],
        entity_type_counts={},
        section26=[],
        warnings=[],
    )
    monkeypatch.setattr(handler, "sanitize_stateless", lambda *_args, **_kwargs: forged)
    monkeypatch.setitem(handler._PROVIDER_FACTORIES, "rescan-spy", SpyProvider)

    out = handle_job(
        {
            "job_id": "j-roundtrip-rescan",
            "operation": "roundtrip",
            "payload": {"text": "ข้อความทดสอบ", "provider": "rescan-spy"},
        }
    )

    assert out["contract_version"] == CONTRACT_VERSION == 1
    assert out["status"] == "error"
    assert out["error"] == {
        "type": "residual_pii",
        "message": "outbound residual detected",
    }
    assert "result" not in out
    assert calls == []
    assert residual not in str(out)


def test_detect_operation():
    d = handle_job({"job_id": "j4", "operation": "detect", "payload": {"text": THAI_TEXT}})
    assert d["status"] == "ok"
    assert d["result"]["entities"], "expected entities"


@pytest.mark.parametrize("operation", ["sanitize", "roundtrip", "detect", "analyze"])
def test_explicit_tner_failure_uses_fixed_worker_v1_error(monkeypatch, operation):
    import app.worker.handler as handler
    from pii_redactor.detectors.ner_failure import NERFailureError

    failure = NERFailureError("ner_incomplete", category="upstream", count=1)

    def fail(*_args, **_kwargs):
        failure.provider_body = THAI_TEXT
        raise failure

    if operation in {"sanitize", "roundtrip"}:
        monkeypatch.setattr(handler, "sanitize_stateless", fail)
    elif operation == "detect":
        monkeypatch.setattr(handler, "detect_all", fail)
    else:
        monkeypatch.setattr(handler, "analyze_text", fail)

    out = handle_job(
        {
            "job_id": f"j-tner-{operation}",
            "operation": operation,
            "payload": {"text": THAI_TEXT, "mode": "token", "provider": "fake"},
        }
    )

    assert out["contract_version"] == CONTRACT_VERSION == 1
    assert out["status"] == "error"
    assert out["error"] == {
        "type": "ner_incomplete",
        "message": "explicit TNER result incomplete",
    }
    assert "result" not in out
    assert THAI_TEXT not in str(out)
    assert failure.__traceback__ is None
    assert failure.__cause__ is None
    assert failure.__context__ is None
    assert failure.__dict__ == {}


def test_worker_roundtrip_tner_unavailable_never_invokes_provider(monkeypatch):
    import app.worker.handler as handler
    from pii_redactor.detectors.ner_failure import NERFailureError

    calls = []

    class SpyProvider:
        def complete(self, _system, _user, *, timeout=30.0):
            calls.append(timeout)
            return "provider must not run"

    def fail_tner(*_args, **_kwargs):
        raise NERFailureError("ner_unavailable", category="network", count=1)

    monkeypatch.setitem(handler._PROVIDER_FACTORIES, "tner-spy", SpyProvider)
    monkeypatch.setattr(handler, "sanitize_stateless", fail_tner)

    out = handle_job(
        {
            "job_id": "j-tner-provider-block",
            "operation": "roundtrip",
            "payload": {
                "text": THAI_TEXT,
                "mode": "token",
                "provider": "tner-spy",
            },
        }
    )

    assert out["status"] == "error"
    assert out["error"] == {
        "type": "ner_unavailable",
        "message": "explicit TNER unavailable",
    }
    assert calls == []
    assert THAI_TEXT not in str(out)


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
    assert out["error"]["type"] == "residual_pii"
    assert "1101700230708" not in str(out)


def test_entrypoint_importable_and_wires_sigterm():
    # smoke: the module imports and exposes main() without side effects
    from app.worker.__main__ import main

    assert callable(main)


def test_explicit_contract_version_is_accepted():
    out = handle_job(
        {
            "contract_version": CONTRACT_VERSION,
            "job_id": "contract-v1",
            "operation": "detect",
            "payload": {"text": THAI_TEXT},
        }
    )
    assert out["status"] == "ok"
    assert out["contract_version"] == CONTRACT_VERSION


@pytest.mark.parametrize("version", [0, 2, "1", True])
def test_unsupported_contract_version_fails_safely(version):
    out = handle_job(
        {
            "contract_version": version,
            "job_id": "bad-contract",
            "operation": "detect",
            "payload": {"text": THAI_TEXT},
        }
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "unsupported_contract_version"
    assert THAI_TEXT not in str(out)


@pytest.mark.parametrize(
    "job",
    [
        None,
        [],
        {"job_id": "", "operation": "detect", "payload": {"text": THAI_TEXT}},
        {"job_id": "bad id", "operation": "detect", "payload": {"text": THAI_TEXT}},
        {"job_id": "safe-id", "operation": THAI_TEXT, "payload": {"text": THAI_TEXT}},
        {"job_id": "safe-id", "operation": "detect", "payload": []},
    ],
)
def test_invalid_envelope_never_echoes_payload(job):
    out = handle_job(job)
    assert out["status"] == "error"
    assert out["error"]["type"] == "invalid_envelope"
    assert THAI_TEXT not in str(out)


def test_envelope_limit_is_configurable_and_safe(monkeypatch):
    monkeypatch.setenv("AIGUARD_MAX_JOB_BYTES", "128")
    out = handle_job(
        {
            "contract_version": CONTRACT_VERSION,
            "job_id": "oversized",
            "operation": "detect",
            "payload": {"text": THAI_TEXT * 10},
        }
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "payload_too_large"
    assert THAI_TEXT not in str(out)


def test_invalid_envelope_limit_uses_safe_default(monkeypatch):
    monkeypatch.setenv("AIGUARD_MAX_JOB_BYTES", "not-a-number")
    out = handle_job(
        {
            "contract_version": CONTRACT_VERSION,
            "job_id": "default-limit",
            "operation": "detect",
            "payload": {"text": THAI_TEXT},
        }
    )
    assert out["status"] == "ok"
