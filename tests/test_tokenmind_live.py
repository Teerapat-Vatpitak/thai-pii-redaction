"""Live smoke against the real Tokenmind endpoint. Skipped without env.

A skip is NOT passing evidence (spec test 13) -- the recorded acceptance path
is scripts/run_acceptance.py --live-tokenmind, whose evidence file reports
`blocked` when the credentials are absent instead of green.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("TOKENMIND_BASE_URL") and os.environ.get("TOKENMIND_API_KEY")),
    reason="TOKENMIND_BASE_URL / TOKENMIND_API_KEY not set (live test)",
)


def test_live_completion_round_trips_a_token():
    from pii_redactor.ai_client import TokenmindProvider

    provider = TokenmindProvider()
    reply = provider.complete(
        "ตอบกลับด้วยข้อความของผู้ใช้ตามตัวอักษรทุกตัว ห้ามเพิ่ม ลบ หรือแก้ไข",
        "ยืนยันการทดสอบ [ชื่อ_1]",
        timeout=60.0,
    )
    assert reply.strip()
    assert "<think>" not in reply
