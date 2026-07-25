import json
import sys
from contextlib import contextmanager

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


def test_acceptance_runner_exercises_analyze_when_the_web_extra_is_present():
    operations = run_acceptance()["checks"]["operations"]

    assert operations["skipped"] == []
    assert set(operations["exercised"]) == {"detect", "sanitize", "analyze", "roundtrip"}


def test_acceptance_runner_skips_analyze_without_the_web_extra():
    with _core_only_install():
        operations = run_acceptance()["checks"]["operations"]

    assert operations["skipped"] == ["analyze"]
    assert set(operations["exercised"]) == {"detect", "sanitize", "roundtrip"}


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
