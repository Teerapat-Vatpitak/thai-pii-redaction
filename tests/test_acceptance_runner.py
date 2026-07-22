"""The acceptance runner must stay executable and keep evidence PII-free."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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
