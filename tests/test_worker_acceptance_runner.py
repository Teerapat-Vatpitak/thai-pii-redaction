import json

from scripts.run_worker_acceptance import HONEYTOKEN, SYNTHETIC_TEXT, run_acceptance


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
