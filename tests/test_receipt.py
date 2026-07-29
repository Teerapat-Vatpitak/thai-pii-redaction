"""Processing receipt (PDPA มาตรา 39) — issue and verify.

The receipt is a per-run artifact, not a cumulative record, and its verifier
re-runs the same input through the same pipeline and compares digests rather
than checking a signature. Those two properties are what these tests pin: the
digest must depend on the detection RESULT and nothing else (not on UUIDs, not
on dict iteration order), and it must never carry a value from the document.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from pii_redactor.models import Entity
from pii_redactor.receipt import (
    RECEIPT_SCHEMA,
    build_receipt,
    result_digest,
    verify_receipt,
)
from pii_redactor.receipt_pdf import render_receipt
from pii_redactor.thai_pdf_text import register_thai_font

ROOT = Path(__file__).resolve().parents[1]

requires_thai_font = pytest.mark.skipif(
    register_thai_font() == "Helvetica",
    reason="no Thai-capable font on this machine — Thai text cannot render or extract",
)

# Fabricated, as every fixture in this repository is.
PII_TEXT = "นายสมชาย ใจดี โทร 081-234-5678 อีเมล somchai@example.com เลขบัตร 1101700230708\n"


def _entity(entity_id: str, span: tuple[int, int], data_type: str, value: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        redact_type="FP",
        data_type=data_type,
        span=span,
        score=1.0,
        original_text=value,
    )


# ── digest ────────────────────────────────────────────────────────────────


def test_digest_ignores_entity_id_and_the_value_itself():
    """Same spans and types = same digest, whatever the UUIDs and values are.

    entity_id is a fresh UUID4 on every run, so a digest that included it could
    never match twice — the whole recompute-to-verify design would be dead on
    arrival. original_text is excluded for the other reason: it is the PII.
    """
    a = [_entity("id-a", (4, 16), "NAME", "สมชาย ใจดี")]
    b = [_entity("id-b", (4, 16), "NAME", "somebody else entirely")]
    assert result_digest(a) == result_digest(b)


def test_digest_changes_when_a_span_moves():
    a = [_entity("x", (4, 16), "NAME", "v")]
    b = [_entity("x", (5, 16), "NAME", "v")]
    assert result_digest(a) != result_digest(b)


def test_digest_changes_when_a_type_changes():
    a = [_entity("x", (4, 16), "NAME", "v")]
    b = [_entity("x", (4, 16), "ADDRESS", "v")]
    assert result_digest(a) != result_digest(b)


def test_digest_ignores_input_ordering():
    """Detection order is an implementation detail; the SET of findings is not."""
    one = _entity("x", (4, 16), "NAME", "v")
    two = _entity("y", (20, 32), "PHONE", "v")
    assert result_digest([one, two]) == result_digest([two, one])


def test_digest_of_nothing_is_stable_and_not_empty():
    assert result_digest([]) == result_digest([])
    assert result_digest([]).startswith("sha256:")


def test_digest_survives_hash_randomization_across_processes(tmp_path):
    """The claim the design rests on, measured rather than assumed.

    Python salts str/bytes hashing per process unless PYTHONHASHSEED is fixed.
    Anything in the detection path that walked a set or an unordered dict could
    therefore produce a different digest on the verifier's machine than on the
    issuer's — the failure mode would be a receipt that never verifies, blamed
    on the document. Three processes, three different seeds, one digest.
    """
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    script = (
        "import sys;"
        "from pii_redactor.receipt import process_for_receipt, result_digest;"
        "print(result_digest(process_for_receipt(sys.argv[1]).entities))"
    )
    digests = []
    for seed in ("0", "1", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1"}
        proc = subprocess.run(
            [sys.executable, "-c", script, str(doc)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        digests.append(proc.stdout.strip())

    assert len(set(digests)) == 1, f"digest is not process-stable: {digests}"
    # Three identical digests over an empty result would agree for the wrong
    # reason — a detector that silently found nothing in every subprocess.
    assert digests[0] != result_digest([])


# ── issuing ───────────────────────────────────────────────────────────────


def test_receipt_carries_no_value_from_the_document(tmp_path):
    """Structural: nothing in the receipt is derived from an entity's text."""
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    blob = json.dumps(build_receipt(doc), ensure_ascii=False)
    for secret in (
        "สมชาย",
        "ใจดี",
        "081-234-5678",
        "0812345678",
        "somchai@example.com",
        "1101700230708",
    ):
        assert secret not in blob, f"receipt leaked {secret!r}"


def test_receipt_records_source_result_and_environment(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_bytes(PII_TEXT.encode("utf-8"))

    receipt = build_receipt(doc)
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["source"]["sha256"] == _sha256_of(doc)
    assert receipt["source"]["bytes"] == doc.stat().st_size
    assert receipt["source"]["source_type"] == "text"
    assert receipt["result"]["digest"].startswith("sha256:")
    assert receipt["result"]["entity_count"] >= 1
    assert receipt["result"]["entity_count"] == sum(receipt["result"]["type_counts"].values())
    assert receipt["environment"]["ner_engine"] == "thainer"
    assert receipt["environment"]["product_version"]
    assert receipt["issued_at"]


def test_receipt_counts_agree_with_the_detection_it_describes(tmp_path):
    from pii_redactor.receipt import process_for_receipt

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    processed = process_for_receipt(doc)
    receipt = build_receipt(doc)
    assert receipt["result"]["entity_count"] == len(processed.entities)
    assert receipt["result"]["fp_count"] == sum(
        1 for e in processed.entities if e.redact_type == "FP"
    )
    assert receipt["result"]["tb_count"] == sum(
        1 for e in processed.entities if e.redact_type != "FP"
    )


def test_operator_declarations_appear_only_when_supplied(tmp_path):
    """Section 39 wants a purpose and a controller; the tool must not invent them."""
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    bare = build_receipt(doc)
    assert "purpose" not in bare["activity"]
    assert "controller" not in bare["activity"]

    declared = build_receipt(doc, purpose="ตรวจสอบเอกสารก่อนส่งให้ AI", controller="คณะวิศวกรรมศาสตร์")
    assert declared["activity"]["purpose"] == "ตรวจสอบเอกสารก่อนส่งให้ AI"
    assert declared["activity"]["controller"] == "คณะวิศวกรรมศาสตร์"


def test_receipt_can_be_issued_for_a_pdf():
    """Ingest routing is the pipeline's, so a text-layer PDF works unchanged."""
    pdf = ROOT / "examples" / "sample_document.pdf"
    receipt = build_receipt(pdf)
    assert receipt["source"]["source_type"] == "pdf_text"
    assert receipt["source"]["sha256"] == _sha256_of(pdf)


# ── verifying ─────────────────────────────────────────────────────────────


def test_verify_accepts_the_file_the_receipt_was_issued_for(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    result = verify_receipt(build_receipt(doc), doc)
    assert result.ok
    assert result.outcome == "match"
    assert result.differences == []


def test_verify_rejects_a_different_document(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    receipt = build_receipt(doc)

    other = tmp_path / "other.txt"
    other.write_text(PII_TEXT + "และอีกบรรทัด\n", encoding="utf-8")

    result = verify_receipt(receipt, other)
    assert not result.ok
    assert result.outcome == "source_mismatch"
    assert any("sha256" in d for d in result.differences)


def test_verify_reports_a_changed_result_separately_from_a_changed_file(tmp_path):
    """Same bytes, different findings — that is a system change, not a swapped
    document, and telling the two apart is the point of two digests."""
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    receipt = build_receipt(doc)
    receipt["result"]["digest"] = "sha256:" + "0" * 64

    result = verify_receipt(receipt, doc)
    assert not result.ok
    assert result.outcome == "result_mismatch"


def test_verify_explains_a_result_mismatch_with_the_environment_that_changed(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    receipt = build_receipt(doc)
    receipt["result"]["digest"] = "sha256:" + "0" * 64
    receipt["environment"]["ner_engine"] = "wangchanberta"

    result = verify_receipt(receipt, doc)
    assert result.outcome == "result_mismatch"
    assert any("ner_engine" in d for d in result.differences)


def test_verify_notes_an_environment_difference_that_did_not_change_the_result(tmp_path):
    """Reproducing across versions is a stronger result, not a failure."""
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    receipt = build_receipt(doc)
    receipt["environment"]["product_version"] = "0.0.1-ancient"

    result = verify_receipt(receipt, doc)
    assert result.ok
    assert result.outcome == "match"
    assert any("product_version" in d for d in result.differences)


def test_verify_refuses_an_unknown_schema(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    receipt = build_receipt(doc)
    receipt["schema"] = "aiguard.processing-receipt/99"

    result = verify_receipt(receipt, doc)
    assert not result.ok
    assert result.outcome == "unsupported_schema"


def test_verify_refuses_a_receipt_missing_required_fields(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    result = verify_receipt({"schema": RECEIPT_SCHEMA}, doc)
    assert not result.ok
    assert result.outcome == "malformed_receipt"


# ── PDF rendering ─────────────────────────────────────────────────────────


def test_receipt_pdf_has_pdf_magic_bytes(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    assert render_receipt(build_receipt(doc))[:5] == b"%PDF-"


@requires_thai_font
def test_receipt_pdf_shows_the_fields_a_reader_needs(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    receipt = build_receipt(doc, purpose="ตรวจก่อนส่งให้ AI", controller="ฝ่ายทะเบียน")
    text = _text_of(render_receipt(receipt))

    assert "ใบรับรองการประมวลผล" in text
    assert receipt["source"]["sha256"][:16] in text
    assert receipt["result"]["digest"].removeprefix("sha256:")[:16] in text
    assert "ตรวจก่อนส่งให้ AI" in text
    assert "ฝ่ายทะเบียน" in text
    assert receipt["environment"]["product_version"] in text


@requires_thai_font
def test_receipt_pdf_carries_no_value_from_the_document(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    text = _text_of(render_receipt(build_receipt(doc)))
    for secret in ("สมชาย", "081-234-5678", "somchai@example.com", "1101700230708"):
        assert secret not in text, f"receipt PDF leaked {secret!r}"


# ── CLI ───────────────────────────────────────────────────────────────────


def test_cli_issue_then_verify_round_trip(tmp_path, capsys):
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    out = tmp_path / "receipt.json"

    ai_guard.cmd_receipt_issue(
        _args(file=str(doc), output=str(out), pdf=None, purpose=None, controller=None)
    )
    assert out.exists()
    issued = json.loads(out.read_text(encoding="utf-8"))
    assert issued["schema"] == RECEIPT_SCHEMA

    ai_guard.cmd_receipt_verify(_args(receipt=str(out), file=str(doc)))
    # "ยืนยันได้", not "ตรงกัน" — the failure line reads "ยืนยันไม่ได้", and a
    # substring both messages share would pass on a failing verification.
    assert "ยืนยันได้" in capsys.readouterr().out


def test_cli_issue_writes_a_pdf_when_asked(tmp_path, capsys):
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    out = tmp_path / "receipt.json"
    pdf = tmp_path / "receipt.pdf"

    ai_guard.cmd_receipt_issue(
        _args(file=str(doc), output=str(out), pdf=str(pdf), purpose=None, controller=None)
    )
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_cli_issue_prints_the_receipt_when_no_output_given(tmp_path, capsys):
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")

    ai_guard.cmd_receipt_issue(
        _args(file=str(doc), output=None, pdf=None, purpose=None, controller=None)
    )
    assert json.loads(capsys.readouterr().out)["schema"] == RECEIPT_SCHEMA


def test_cli_issue_refuses_to_overwrite_an_existing_receipt(tmp_path):
    """A receipt is evidence someone kept; clobbering one needs to be asked for."""
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    out = tmp_path / "receipt.json"
    out.write_text("earlier receipt", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_receipt_issue(
            _args(file=str(doc), output=str(out), pdf=None, purpose=None, controller=None)
        )
    assert exc.value.code == 1
    assert out.read_text(encoding="utf-8") == "earlier receipt"


def test_cli_issue_overwrites_when_asked(tmp_path, capsys):
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    out = tmp_path / "receipt.json"
    out.write_text("earlier receipt", encoding="utf-8")

    ai_guard.cmd_receipt_issue(
        _args(
            file=str(doc),
            output=str(out),
            pdf=None,
            purpose=None,
            controller=None,
            overwrite=True,
        )
    )
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == RECEIPT_SCHEMA


def test_cli_verify_exits_1_when_the_document_does_not_match(tmp_path, capsys):
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    out = tmp_path / "receipt.json"
    ai_guard.cmd_receipt_issue(
        _args(file=str(doc), output=str(out), pdf=None, purpose=None, controller=None)
    )

    doc.write_text(PII_TEXT + "แก้ไขภายหลัง\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_receipt_verify(_args(receipt=str(out), file=str(doc)))
    assert exc.value.code == 1


def test_cli_verify_exits_1_on_an_unreadable_receipt(tmp_path):
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(PII_TEXT, encoding="utf-8")
    bad = tmp_path / "receipt.json"
    bad.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_receipt_verify(_args(receipt=str(bad), file=str(doc)))
    assert exc.value.code == 1


def test_cli_parser_exposes_receipt_issue_and_verify():
    import ai_guard

    assert hasattr(ai_guard, "cmd_receipt_issue")
    assert hasattr(ai_guard, "cmd_receipt_verify")


# ── helpers ───────────────────────────────────────────────────────────────


def _args(**kwargs):
    # `overwrite` defaults the way argparse's store_true does, so every call
    # site reads as the command a user would actually type.
    return type("Args", (), {"overwrite": False, **kwargs})()


def _sha256_of(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_of(pdf_bytes: bytes) -> str:
    # pypdfium2 rather than pdfplumber: draw_text() lays an invisible original
    # layer under the shaped one, and only pypdfium2 keeps the two sequential
    # so the original survives as a contiguous substring (same reason
    # tests/test_report_pdf.py uses it).
    doc = pdfium.PdfDocument(pdf_bytes)
    return "\n".join(page.get_textpage().get_text_range() for page in doc)
