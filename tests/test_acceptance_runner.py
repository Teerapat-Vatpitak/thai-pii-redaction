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
