"""The acceptance runner must stay executable and keep evidence PII-free."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from scripts.http_v2_client import ContractError

try:
    from fastapi.testclient import TestClient

    from app.server import app

    DEPS = True
except ImportError:
    DEPS = False

pytestmark = pytest.mark.skipif(not DEPS, reason="web dependencies not installed")

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "run_acceptance", ROOT / "scripts" / "run_acceptance.py"
)
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def test_core_acceptance_passes_and_serialized_results_contain_no_fixture_pii(monkeypatch):
    monkeypatch.setenv("AIGUARD_DEMO", "1")
    results = acceptance.core_checks(TestClient(app, base_url="http://localhost"))

    assert results
    assert {result.status for result in results} == {"pass"}
    evidence = json.dumps([acceptance.asdict(result) for result in results], ensure_ascii=False)
    assert acceptance.SYNTHETIC_NAME not in evidence
    assert acceptance.SYNTHETIC_PHONE not in evidence


def test_checked_records_exception_type_without_exception_message():
    secret = "raw-sensitive-value"

    def boom():
        raise RuntimeError(secret)

    result = acceptance._checked("safe.failure", boom)

    assert result.status == "fail"
    assert result.details == {"error_type": "RuntimeError"}
    assert secret not in json.dumps(acceptance.asdict(result))


def test_evidence_base_url_drops_every_credential_bearing_component():
    raw = "https://user:password@example.test:8443/private/token?api_key=secret#secret"

    safe = acceptance._evidence_base_url(raw)

    assert safe == "https://example.test:8443"
    assert "user" not in safe
    assert "password" not in safe
    assert "token" not in safe
    assert "secret" not in safe


class _Response:
    def __init__(self, status_code, body, headers):
        self.status_code = status_code
        self._body = body
        self.headers = headers

    def json(self):
        return self._body


class _RecordingClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)


def _health_body():
    return {
        "status": "ok",
        "version": "2.5.0",
        "contract_version": 2,
        "capabilities": {
            "control_token_required": True,
            "api_key_required": False,
        },
    }


def test_request_helper_keeps_health_free_of_assertion_and_credentials(monkeypatch):
    monkeypatch.setenv("AIGUARD_API_KEY", "not-recorded")
    client = _RecordingClient(_Response(200, _health_body(), {"X-AIGuard-Contract-Version": "2"}))

    status, body = acceptance._request_json(client, "GET", "/api/health")

    assert status == 200
    assert body == _health_body()
    sent_headers = client.calls[0][2].get("headers", {})
    assert "X-AIGuard-Contract-Version" not in sent_headers
    assert "X-AIGuard-Key" not in sent_headers


def test_request_helper_asserts_v2_and_auth_only_on_non_health(monkeypatch):
    monkeypatch.setenv("AIGUARD_API_KEY", "not-recorded")
    error = {
        "error": {
            "code": "invalid_request",
            "category": "request",
            "count": 0,
            "retryable": False,
            "status": 400,
        }
    }
    client = _RecordingClient(_Response(400, error, {"X-AIGuard-Contract-Version": "2"}))

    status, body = acceptance._request_json(
        client, "POST", "/api/guard", json={"text": "synthetic"}
    )

    assert (status, body) == (400, error)
    sent_headers = client.calls[0][2]["headers"]
    assert sent_headers["X-AIGuard-Contract-Version"] == "2"
    assert sent_headers["X-AIGuard-Key"] == "not-recorded"


def test_request_helper_rejects_missing_or_duplicate_response_assertion(monkeypatch):
    monkeypatch.delenv("AIGUARD_API_KEY", raising=False)
    missing = _RecordingClient(_Response(200, _health_body(), {}))
    with pytest.raises(ContractError):
        acceptance._request_json(missing, "GET", "/api/health")

    class _DuplicateHeaders:
        def get_list(self, _name):
            return ["2", "2"]

    duplicate = _RecordingClient(_Response(200, _health_body(), _DuplicateHeaders()))
    with pytest.raises(ContractError):
        acceptance._request_json(duplicate, "GET", "/api/health")


@pytest.mark.parametrize(
    "response",
    [
        _Response(200, _health_body(), {}),
        _Response(
            200,
            _health_body(),
            {"X-AIGuard-Contract-Version": "02"},
        ),
        _Response(
            200,
            {**_health_body(), "contract_version": 1},
            {"X-AIGuard-Contract-Version": "2"},
        ),
        _Response(
            200,
            {"status": "ok"},
            {"X-AIGuard-Contract-Version": "2"},
        ),
    ],
    ids=["missing-header", "malformed-header", "v1-body", "malformed-body"],
)
def test_failed_health_blocks_every_dependent_acceptance_request(
    monkeypatch,
    response,
):
    monkeypatch.delenv("AIGUARD_API_KEY", raising=False)
    client = _RecordingClient(response)

    results = acceptance.core_checks(client)

    assert results[0].check_id == "api.health"
    assert results[0].status == "fail"
    assert {result.status for result in results[1:]} == {"blocked"}
    assert [(method, path) for method, path, _kwargs in client.calls] == [("GET", "/api/health")]


def test_duplicate_health_header_blocks_every_dependent_acceptance_request(monkeypatch):
    monkeypatch.delenv("AIGUARD_API_KEY", raising=False)

    class _DuplicateHeaders:
        def get_list(self, _name):
            return ["2", "2"]

    client = _RecordingClient(_Response(200, _health_body(), _DuplicateHeaders()))

    results = acceptance.core_checks(client)

    assert results[0].status == "fail"
    assert {result.status for result in results[1:]} == {"blocked"}
    assert len(client.calls) == 1


def test_key_required_health_without_key_blocks_every_dependent_request(monkeypatch):
    monkeypatch.delenv("AIGUARD_API_KEY", raising=False)
    body = _health_body()
    body["capabilities"]["api_key_required"] = True
    client = _RecordingClient(_Response(200, body, {"X-AIGuard-Contract-Version": "2"}))

    results = acceptance.core_checks(client)

    assert results[0].status == "blocked"
    assert {result.status for result in results[1:]} == {"blocked"}
    assert len(client.calls) == 1


def test_docker_smoke_validator_is_in_the_build_context():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "!scripts/http_v2_client.py" in dockerignore
    assert "from scripts.http_v2_client import" in workflow


def test_write_evidence_records_reproducible_git_state_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "_git_state", lambda _root: ("a" * 40, True))
    output = tmp_path / "evidence.json"
    raw_url = "http://owner:credential@localhost:8000/api?token=credential"

    acceptance._write_evidence(output, raw_url, [])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["git_commit"] == "a" * 40
    assert payload["git_dirty"] is True
    assert payload["base_url"] == "http://localhost:8000"
    assert "credential" not in output.read_text(encoding="utf-8")
