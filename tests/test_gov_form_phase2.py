"""Check the phase-2 Thai government-form test corpus.

The source forms are blank. The generator adds synthetic values only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

import pdfplumber
import pytest
from reportlab.pdfgen import canvas

from benchmark.data.probe.gov_forms.generate_inputs import generate_corpus
from benchmark.data.probe.gov_forms.sanitize_download import sanitize_pdf
from benchmark.probe_document import load_expectations
from pii_redactor.ingest.file_detector import detect_source_type

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmark" / "data" / "probe" / "gov_forms"
MANIFEST = CORPUS / "manifest.json"

PINNED_HASHES = {
    "sanitized/khor-ror-1-blank.pdf": (
        "861c97588c0ea09afc65239f42d10bb810afeb3b176abf81721b38603c41b6eb"
    ),
    "sanitized/pnd91-2568-blank.pdf": (
        "b17a877020f5a8f18d704cbc63513c779cea1d22093c71f7243c6c7d72ee9726"
    ),
    "sanitized/sps-1-03-blank.pdf": (
        "2274ade390545fd5e465bd2ff276e338467de69a72c8cdcfde1efbc8e3f48dcb"
    ),
}

SOURCE_HASHES = {
    "คร.1": "84692fd1f64a254ead8b7ae7ff193890d5a5412ce03ef18b0cfcf6323500df31",
    "ภ.ง.ด.91": "8cb80f3b2392be6462c3b73cb31bd7b560578e81a84625b3938bb02d258e206b",
    "สปส.1-03": "e43c424e64456581faa37319b88e1b9a4daea7a4cbcbaa4b3c664c78a7d94e4d",
}

OFFICIAL_HOSTS = {
    "www.bora.dopa.go.th",
    "www.rd.go.th",
    "catalog.sso.go.th",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_official_blank_downloads_are_hash_pinned_and_first_party():
    manifest = _manifest()
    forms = manifest["forms"]

    assert [form["code"] for form in forms] == ["คร.1", "ภ.ง.ด.91", "สปส.1-03"]
    assert len(forms) == 3
    assert {form["official_path"] for form in forms} == set(PINNED_HASHES)

    for form in forms:
        relative = form["official_path"]
        source = CORPUS / relative
        assert source.is_file()
        assert urlparse(form["download_url"]).scheme == "https"
        assert urlparse(form["download_url"]).hostname in OFFICIAL_HOSTS
        assert form["source_sha256"] == SOURCE_HASHES[form["code"]]
        assert form["artifact_sha256"] == PINNED_HASHES[relative]
        assert _sha256(source) == PINNED_HASHES[relative]
        assert form["blank_verified"] is True


def test_committed_blanks_have_no_hidden_payloads():
    for form in _manifest()["forms"]:
        source = CORPUS / form["official_path"]
        with pdfplumber.open(source) as pdf:
            assert pdf.metadata["Author"] == "AI Guard"
            assert pdf.metadata["Creator"] == "AI Guard"
            assert set(pdf.doc.catalog) <= {"Type", "Pages", "PageMode"}
            for page in pdf.pages:
                assert len(page.images) == 1
                assert not page.chars
                assert not page.annots
                assert set(page.page_obj.attrs) <= {
                    "Type",
                    "Parent",
                    "Resources",
                    "MediaBox",
                    "Contents",
                    "Rotate",
                    "Trans",
                }


def test_pdf_sanitizer_removes_metadata_and_links(tmp_path):
    raw = tmp_path / "raw.pdf"
    safe = tmp_path / "safe.pdf"
    c = canvas.Canvas(str(raw))
    c.setAuthor("Example Person")
    c.setTitle("Synthetic private note")
    c.drawString(10, 50, "synthetic page")
    c.linkURL("https://example.invalid", (10, 45, 90, 60))
    c.save()

    sanitize_pdf(raw, safe)

    with pdfplumber.open(safe) as pdf:
        assert pdf.metadata["Author"] == "AI Guard"
        assert pdf.metadata["Creator"] == "AI Guard"
    payload = safe.read_bytes()
    assert b"Example Person" not in payload
    assert b"/Annots" not in payload


def test_no_fabricated_probe_value_occurs_in_an_official_blank():
    manifest = _manifest()
    values = {field["value"] for form in manifest["forms"] for field in form["synthetic_fields"]}

    for form in manifest["forms"]:
        source = CORPUS / form["official_path"]
        payload = source.read_bytes()
        assert all(value.encode("utf-8") not in payload for value in values)


def test_generator_builds_nine_deterministic_modality_inputs(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_rows = generate_corpus(CORPUS, first)
    second_rows = generate_corpus(CORPUS, second)

    assert len(first_rows) == 9
    assert [(row.form_code, row.modality) for row in first_rows] == [
        (form, modality)
        for form in ("คร.1", "ภ.ง.ด.91", "สปส.1-03")
        for modality in ("digital", "print_like", "degraded")
    ]

    for first_row, second_row in zip(first_rows, second_rows, strict=True):
        first_pdf = first / first_row.document
        second_pdf = second / second_row.document
        first_expected = first / first_row.expectations
        second_expected = second / second_row.expectations

        assert _sha256(first_pdf) == _sha256(second_pdf)
        assert first_expected.read_bytes() == second_expected.read_bytes()

        expected = load_expectations(first_expected)
        assert expected["values"]
        assert expected["decoys"]
        assert expected["meta"]["synthetic_only"] is True
        assert expected["meta"]["form_code"] == first_row.form_code
        assert expected["meta"]["modality"] == first_row.modality

        source_type = detect_source_type(first_pdf)
        if first_row.modality == "digital":
            assert source_type == "pdf_text"
        else:
            assert source_type == "pdf_hybrid"


def test_degraded_inputs_are_not_aliases_of_print_like_inputs(tmp_path):
    rows = generate_corpus(CORPUS, tmp_path)
    by_form = {
        form: {
            row.modality: _sha256(tmp_path / row.document) for row in rows if row.form_code == form
        }
        for form in ("คร.1", "ภ.ง.ด.91", "สปส.1-03")
    }

    for hashes in by_form.values():
        assert hashes["digital"] != hashes["print_like"]
        assert hashes["print_like"] != hashes["degraded"]


def test_generator_rejects_a_changed_official_source(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    source = corpus / _manifest()["forms"][0]["official_path"]
    source.write_bytes(source.read_bytes() + b"changed")

    with pytest.raises(ValueError, match="official source hash mismatch"):
        generate_corpus(corpus, tmp_path / "output")
