import json
import sys
from contextlib import contextmanager

import pytest

from scripts.run_worker_acceptance import HONEYTOKEN, SYNTHETIC_TEXT, run_acceptance

_WEB_ROOTS = ("fastapi", "starlette")


class _BlockWebExtra:
    """Refuse the web extra the way a core-only `pip install` leaves it."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in _WEB_ROOTS:
            raise ModuleNotFoundError(f"No module named {fullname!r}")
        return None


@contextmanager
def _core_only_install():
    # app.server is dropped too: another test may already have imported it, and
    # a cached module would let the late import succeed against a blocked dep.
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name.split(".")[0] in _WEB_ROOTS or name == "app.server"
    }
    for name in saved:
        del sys.modules[name]
    blocker = _BlockWebExtra()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(saved)


def test_acceptance_runner_exercises_every_operation():
    operations = run_acceptance()["checks"]["operations"]

    assert operations["skipped"] == []
    assert set(operations["exercised"]) == {"detect", "sanitize", "analyze", "roundtrip"}


def test_analyze_runs_on_a_core_only_install():
    """The inverse of what this file used to assert.

    `analyze` used to be skipped without the web extra, because the worker
    reached into `app.server` for it and that module needs FastAPI. The
    assembly now lives in `pii_redactor.report`, where it always belonged — it
    never touched the web layer — so the operation runs with fastapi and
    starlette blocked. Kept as the inverse rather than deleted: this is the
    test that pins what the move bought.
    """
    with _core_only_install():
        operations = run_acceptance()["checks"]["operations"]

    assert operations["skipped"] == []
    assert set(operations["exercised"]) == {"detect", "sanitize", "analyze", "roundtrip"}


def test_worker_acceptance_runner_is_repeatable_and_pii_free():
    first = run_acceptance()
    second = run_acceptance()

    for evidence in (first, second):
        assert evidence["evidence_level"] == "local_platform_emulator"
        assert evidence["official_platform_acceptance"] is False
        assert evidence["checks"]["duplicate_delivery"]["provider_calls"] == 1
        assert evidence["checks"]["concurrency"]["jobs"] == 8
        assert evidence["checks"]["failure_matrix"]["provider_timeout"] == "pass"
        assert evidence["checks"]["failure_matrix"]["handler_crash"] == "pass"
        assert "cross_process_crash_idempotency" in evidence["external_blockers"]
        rendered = json.dumps(evidence, ensure_ascii=False)
        assert SYNTHETIC_TEXT not in rendered
        assert HONEYTOKEN not in rendered
