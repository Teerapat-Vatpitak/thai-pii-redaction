"""Blind-set protocol guards (benchmark/blind.py).

The property under test is not correctness of the metrics (the shared scorer
has its own tests) but the protocol itself: the corpus stays unreadable
without the key, the lock pins it, scoring output is aggregate-only, and the
audit log is an append-only hash chain. The fixture corpus plants SENTINEL
strings and every output channel is asserted sentinel-free.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from benchmark import blind

SENTINEL_NAME = "XQ_SENTINEL_NAME_XQ"
SENTINEL_TEXT = "XQ_SENTINEL_BODY_XQ"

# A checksum-valid fabricated Thai ID and Luhn-valid card for the fixture.
VALID_THAI_ID = "1101700230708"
VALID_CARD = "4111111111111111"

FIXTURE_MINIMUMS = {"NAME": 1, "THAI_ID": 1, "CREDIT_CARD": 1}


def _fixture_records() -> list[dict]:
    return [
        {
            "doc_id": "b-fix01",
            "slice": "gov_form",
            "layer": "natural",
            "annotated": (
                f"เรียนเจ้าหน้าที่ {SENTINEL_TEXT} ผู้ยื่นคำร้องชื่อ "
                f"[[NAME|{SENTINEL_NAME}]] เลขบัตรประชาชน [[THAI_ID|{VALID_THAI_ID}]] "
                "ขอให้ดำเนินการตามระเบียบ"
            ),
        },
        {
            "doc_id": "b-fix02",
            "slice": "finance",
            "layer": "natural",
            "annotated": (
                "แจ้งการชำระผ่านบัตรเครดิตหมายเลข "
                f"[[CREDIT_CARD|{VALID_CARD}]] ยอดรวมตามใบแจ้งหนี้เดือนล่าสุด"
            ),
        },
        {
            "doc_id": "b-fix03",
            "slice": "negative",
            "layer": "negative",
            "annotated": "ใบเสร็จเลขที่ INV-77012 ยอดสุทธิ 1,250 บาท สอบถามโทรสายด่วน 1112",
        },
    ]


@pytest.fixture()
def frozen_blind(tmp_path):
    """A frozen fixture corpus: returns (data_dir, key_file, draft_path)."""
    draft = tmp_path / "outside" / "blind-v1.draft.jsonl"
    draft.parent.mkdir()
    draft.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in _fixture_records()) + "\n",
        encoding="utf-8",
    )
    key_file = tmp_path / "outside" / "blind-v1.key"
    blind.generate_key(key_file)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    blind.freeze(
        draft, key_file, data_dir=data_dir, type_minimums=FIXTURE_MINIMUMS, reveal_budget=1
    )
    return data_dir, key_file, draft


def test_freeze_roundtrip_and_lock(frozen_blind):
    data_dir, key_file, _ = frozen_blind
    samples, lock = blind.load_blind(key_file, data_dir=data_dir)
    assert lock["documents"] == 3
    assert lock["slice_counts"]["negative"] == 1
    assert lock["type_counts"]["NAME"] == 1
    assert len(samples) == 3
    # The blob on disk must not contain the corpus in readable form.
    blob = (data_dir / "blind-v1.enc").read_bytes()
    assert SENTINEL_NAME.encode() not in blob
    assert SENTINEL_TEXT.encode() not in blob
    assert VALID_THAI_ID.encode() not in blob


def test_wrong_key_and_tamper_are_rejected(frozen_blind, tmp_path):
    data_dir, key_file, _ = frozen_blind
    other_key = tmp_path / "other.key"
    blind.generate_key(other_key)
    with pytest.raises(blind.BlindError):
        blind.load_blind(other_key, data_dir=data_dir)

    enc = data_dir / "blind-v1.enc"
    blob = bytearray(enc.read_bytes())
    flip = len(blob) // 2
    blob[flip] ^= 0x01
    enc.write_bytes(bytes(blob))
    with pytest.raises(blind.BlindError):
        blind.load_blind(key_file, data_dir=data_dir)


def test_lock_mismatch_is_rejected(frozen_blind):
    data_dir, key_file, _ = frozen_blind
    lock_path = data_dir / "blind-v1.lock.json"
    lock = json.loads(lock_path.read_text())
    lock["plaintext_sha256"] = "0" * 64
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(blind.BlindError):
        blind.load_blind(key_file, data_dir=data_dir)


def test_refreeze_requires_force(frozen_blind):
    data_dir, key_file, draft = frozen_blind
    with pytest.raises(blind.BlindError):
        blind.freeze(draft, key_file, data_dir=data_dir, type_minimums=FIXTURE_MINIMUMS)
    blind.freeze(draft, key_file, data_dir=data_dir, type_minimums=FIXTURE_MINIMUMS, force=True)


def test_run_blind_is_aggregate_only_and_logs_chain(frozen_blind, capsys):
    data_dir, key_file, _ = frozen_blind
    log_path = data_dir / "blind-scores.jsonl"

    result = blind.run_blind(
        engine="crf",
        key_file=key_file,
        reason="protocol test",
        data_dir=data_dir,
        log_path=log_path,
        bootstrap_iters=50,
    )
    table = blind.render_blind_table(result)
    print(table)
    out = capsys.readouterr().out

    for channel in (out, json.dumps(result, ensure_ascii=False), log_path.read_text()):
        assert SENTINEL_NAME not in channel
        assert SENTINEL_TEXT not in channel
        assert VALID_THAI_ID not in channel
        assert VALID_CARD not in channel

    assert result["reveal_index"] == 1
    assert result["over_budget"] is False
    assert result["negative"]["documents"] == 1
    assert blind.verify_log(log_path) == 1

    # Second run exceeds the fixture budget of 1 and must say so, permanently.
    result2 = blind.run_blind(
        engine="crf",
        key_file=key_file,
        reason="over budget test",
        data_dir=data_dir,
        log_path=log_path,
        bootstrap_iters=50,
    )
    assert result2["reveal_index"] == 2
    assert result2["over_budget"] is True
    assert blind.verify_log(log_path) == 2

    entries = blind.read_log(log_path)
    assert entries[1]["prev_sha256"] == entries[0]["entry_sha256"]
    assert entries[0]["bench_code_sha256"] == blind.code_digest()

    # Tampering with a logged metric breaks the chain verification.
    entries[0]["metrics"]["overall"]["recall"] = 1.0
    log_path.write_text(
        "\n".join(json.dumps(e, sort_keys=True, ensure_ascii=True) for e in entries) + "\n",
        encoding="ascii",
    )
    with pytest.raises(blind.BlindError):
        blind.verify_log(log_path)


def test_run_blind_requires_key_and_reason(frozen_blind):
    data_dir, key_file, _ = frozen_blind
    with pytest.raises(blind.BlindError, match="AIGUARD_BLIND_KEY_FILE"):
        blind.run_blind(engine="crf", key_file=None, reason="x", data_dir=data_dir)
    with pytest.raises(blind.BlindError, match="reason"):
        blind.run_blind(engine="crf", key_file=key_file, reason="  ", data_dir=data_dir)


def test_validate_draft_rejects_defects_without_leaking_values():
    records = _fixture_records()
    records[0]["annotated"] = records[0]["annotated"].replace("NAME", "FULLNAME")
    records.append(dict(records[1], doc_id="b-fix02"))  # duplicate id
    records.append(
        {
            "doc_id": "b-neg-bad",
            "slice": "negative",
            "layer": "negative",
            "annotated": f"หมายเลขอ้างอิง {VALID_THAI_ID} ในระบบ",  # 13-digit run in negative
        }
    )
    errors = blind.validate_draft(records, type_minimums={})
    kinds = {k for _, k in errors}
    assert "unknown-type-FULLNAME" in kinds
    assert "duplicate-doc-id" in kinds
    assert "negative-contains-13-digit-run" in kinds
    joined = json.dumps(errors, ensure_ascii=False)
    assert SENTINEL_NAME not in joined
    assert VALID_THAI_ID not in joined


def test_freeze_rejects_draft_inside_data_dir(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "sub").mkdir(parents=True)
    inside = data_dir / "sub" / "draft.jsonl"
    inside.write_text("", encoding="utf-8")
    key_file = tmp_path / "k.key"
    blind.generate_key(key_file)
    with pytest.raises(blind.BlindError, match="outside"):
        blind.freeze(inside, key_file, data_dir=data_dir, type_minimums={})


def test_llm_benchmark_paths_never_reference_blind():
    """The LLM benchmark sends document text to hosted providers; the blind
    corpus must be structurally out of its reach, not just prohibited in
    prose."""
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "benchmark/llm_strategy.py",
        "benchmark/llm_providers.py",
        "scripts/run_llm_benchmark.py",
        "scripts/run_llm_benchmark_all.ps1",
    ):
        path = root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "blind" not in text.lower(), f"{rel} must not touch the blind set"


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".git").exists(),
    reason="needs a git checkout",
)
def test_blind_scores_log_is_not_gitignored():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["git", "check-ignore", "benchmark/data/blind-scores.jsonl"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "blind-scores.jsonl must be committable (audit log)"
