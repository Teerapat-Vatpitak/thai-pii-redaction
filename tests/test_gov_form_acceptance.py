"""Automated contract tests for the government-form synthetic acceptance runner."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark.data.probe.gov_forms import run_acceptance
from benchmark.data.probe.gov_forms.generate_inputs import CorpusRow
from benchmark.probe_document import ExpectedValue

EXPECTED_INDICES = (0, 1)


def _rows() -> list[CorpusRow]:
    return [
        CorpusRow(
            form_code=form_code,
            modality=modality,
            document=f"{slug}/{slug}-{modality}.pdf",
            expectations=f"{slug}/{slug}-{modality}.expected.json",
        )
        for form_code, slug in (
            ("คร.1", "khor-ror-1"),
            ("ภ.ง.ด.91", "pnd91-2568"),
            ("สปส.1-03", "sps-1-03"),
        )
        for modality in ("digital", "print_like", "degraded")
    ]


def _expected_values() -> list[ExpectedValue]:
    return [
        ExpectedValue(
            index=index,
            field=f"synthetic_{index}",
            value=f"SYNTHETIC-{index}",
            type="STUDENT_ID",
        )
        for index in EXPECTED_INDICES
    ]


def _result(modality: str) -> dict:
    return {
        "source_type": "pdf_hybrid",
        "ocr": {
            "status": "measured",
            "values": [
                {"index": index, "field": f"synthetic_{index}", "status": "measured"}
                for index in EXPECTED_INDICES
            ],
        },
        "extraction": {
            "total": 2,
            "found": 2,
            "missing": 0,
            "values": [
                {"index": index, "field": f"synthetic_{index}", "found": True}
                for index in EXPECTED_INDICES
            ],
        },
        "detection": {
            "total": 2,
            "detected": 2,
            "scored": 2,
            "type_matches": 2,
            "out_of_scheme": 0,
            "values": [],
        },
        "privacy_alignment": {
            "total": 2,
            "aligned": 2,
            "unaligned": 0,
            "values": [
                {
                    "index": index,
                    "field": f"synthetic_{index}",
                    "aligned": True,
                    "alignment": "exact",
                }
                for index in EXPECTED_INDICES
            ],
        },
        "coverage": {
            "status": "measured",
            "values_measured": 2,
            "fully_covered": 2,
            "values": [
                {
                    "index": index,
                    "field": f"synthetic_{index}",
                    "status": "measured",
                    "black_fraction": 1.0,
                    "fully_covered": True,
                }
                for index in EXPECTED_INDICES
            ],
        },
        "residual": {
            "status": "measured",
            "text_arm": {
                "redacted_source_type": "pdf_hybrid",
                "text_layer_chars": 0,
                "vacuous": True,
            },
            "render_ocr": {
                "status": "measured",
                "surviving": 0,
                "values": [
                    {
                        "index": index,
                        "field": f"synthetic_{index}",
                        "survives": False,
                    }
                    for index in EXPECTED_INDICES
                ],
            },
            "removed": 2,
            "exposed": 0,
            "unmeasurable": 0,
            "values": [
                {
                    "index": index,
                    "field": f"synthetic_{index}",
                    "verdict": "removed",
                    "render_ocr_survives": False,
                }
                for index in EXPECTED_INDICES
            ],
        },
        "decoy_control": {"false_hits": []},
    }


def _install_fakes(monkeypatch, mutate=None) -> None:
    rows = _rows()
    monkeypatch.setattr(run_acceptance, "generate_corpus", lambda _corpus, _output: rows)
    monkeypatch.setattr(
        run_acceptance,
        "load_expectations",
        lambda path: {
            "meta": {"modality": Path(path).stem.split("-")[-1]},
            "values": _expected_values(),
        },
    )

    def fake_probe(document, _expectations):
        name = Path(document).name
        modality = next(item for item in ("digital", "print_like", "degraded") if item in name)
        result = _result(modality)
        if mutate is not None:
            mutate(result, modality)
        return result

    monkeypatch.setattr(run_acceptance, "probe", fake_probe)
    monkeypatch.setattr(
        run_acceptance,
        "runtime_versions",
        lambda: {
            "python": "3.test",
            "paddlepaddle": "paddle-test",
            "paddleocr": "ocr-test",
            "pillow": "pillow-test",
            "reportlab": "reportlab-test",
            "pypdfium2": "pdfium-test",
            "opencv": {
                "runtime": "cv-test",
                "distributions": {"opencv-contrib-python": "dist-test"},
            },
        },
    )
    monkeypatch.setattr(
        run_acceptance,
        "repository_state",
        lambda: {"commit": "test-commit", "dirty": False},
    )


def test_runner_writes_nine_results_and_a_passing_summary(tmp_path, monkeypatch):
    _install_fakes(monkeypatch)

    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")

    assert summary["evidence_scope"] == run_acceptance.EVIDENCE_SCOPE
    assert summary["schema_version"] == 3
    assert summary["generated_inputs"] == 9
    assert summary["acceptance_passed"] is True
    assert summary["evidence_status"] == "synthetic_local_pass_clean"
    assert summary["failure_counts"] == {}
    assert summary["runtime_versions"]["paddleocr"] == "ocr-test"
    assert summary["runtime_versions"]["pillow"] == "pillow-test"
    assert summary["runtime_versions"]["reportlab"] == "reportlab-test"
    assert summary["runtime_versions"]["pypdfium2"] == "pdfium-test"
    assert summary["repository"] == {"commit": "test-commit", "dirty": False}
    assert summary["aggregate_metrics"] == {
        "inputs": 9,
        "source_routes_correct": 9,
        "ocr_routes_expected": 9,
        "ocr_routes_measured": 9,
        "expected_values": 18,
        "extraction_found": 18,
        "privacy_aligned": 18,
        "detection_total": 18,
        "detection_detected": 18,
        "detection_scored": 18,
        "type_matches": 18,
        "coverage_fully_covered": 18,
        "residual_removed": 18,
        "residual_exposed": 0,
        "residual_unmeasurable": 0,
        "residual_ocr_routes_measured": 9,
        "residual_ocr_surviving": 0,
        "decoy_inputs_without_false_hits": 9,
    }

    summary_path = tmp_path / "reports" / "summary.json"
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary
    result_paths = [tmp_path / "reports" / item["result_json"] for item in summary["inputs"]]
    assert len(result_paths) == 9
    assert len(set(result_paths)) == 9
    assert all(path.is_file() for path in result_paths)
    saved_result = json.loads(result_paths[0].read_text(encoding="utf-8"))
    assert saved_result["schema_version"] == 3
    assert saved_result["probe"]["source_type"]


def test_persisted_results_remove_value_bearing_text(tmp_path, monkeypatch):
    canary = "SYNTHETIC-RAW-CANARY-4417"
    near_match = "SYNTHETIC-RAW-CANARY-441X"

    def add_value_text(result, _modality):
        result["extract_meta"] = {
            "ocr_confidence": 0.9,
            "human_review": False,
            "pages_ocred": [1],
            "pages_text_layer": [1],
            "ocr_text_ranges": [(0, len(near_match))],
            "ocr_observations": [near_match],
            "warnings": [],
        }
        result["extraction"]["values"][0]["value"] = canary
        result["ocr"]["values"] = [
            {
                "index": 0,
                "field": "synthetic_0",
                "status": "measured",
                "expected": canary,
                "best_match": canary,
                "start": 0,
                "end": len(canary),
                "edit_distance": 0,
                "char_accuracy": 1.0,
            }
        ]
        result["residual"]["render_ocr"]["values"][0].update(
            expected=canary,
            best_match=canary,
        )
        result["residual"]["text_arm"] = {
            "values_surviving_in_text": [canary],
        }
        result["decoy_control"]["false_hits"] = [canary]

    _install_fakes(monkeypatch, add_value_text)

    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")
    result_path = tmp_path / "reports" / summary["inputs"][0]["result_json"]
    raw = result_path.read_text(encoding="utf-8")
    summary_raw = (tmp_path / "reports" / "summary.json").read_text(encoding="utf-8")
    saved = json.loads(raw)["probe"]

    assert canary not in raw
    assert near_match not in raw
    assert canary not in summary_raw
    assert "document" not in saved
    assert "ocr_observations" not in saved["extract_meta"]
    assert "value" not in saved["extraction"]["values"][0]
    assert saved["extraction"]["values"][0]["value_chars"] == len(canary)
    assert "expected" not in saved["ocr"]["values"][0]
    assert "best_match" not in saved["ocr"]["values"][0]
    assert saved["ocr"]["values"][0]["expected_chars"] == len(canary)
    assert saved["ocr"]["values"][0]["best_match_chars"] == len(canary)
    render_row = saved["residual"]["render_ocr"]["values"][0]
    assert "expected" not in render_row
    assert "best_match" not in render_row
    assert render_row["expected_chars"] == len(canary)
    assert render_row["best_match_chars"] == len(canary)
    assert "values_surviving_in_text" not in saved["residual"]["text_arm"]
    assert saved["residual"]["text_arm"]["values_surviving_in_text_count"] == 1
    assert "false_hits" not in saved["decoy_control"]
    assert saved["decoy_control"]["false_hit_count"] == 1


def test_unknown_value_field_is_not_saved(tmp_path, monkeypatch):
    def add_unknown_field(result, _modality):
        result["future_debug_field"] = "SYNTHETIC-0"

    _install_fakes(monkeypatch, add_unknown_field)
    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")
    result_path = tmp_path / "reports" / summary["inputs"][0]["result_json"]
    raw = result_path.read_text(encoding="utf-8")
    saved = json.loads(raw)

    assert summary["acceptance_passed"] is True
    assert "SYNTHETIC-0" not in raw
    assert "future_debug_field" not in saved["probe"]


def test_declared_value_in_safe_field_nulls_the_probe(tmp_path, monkeypatch):
    def add_declared_value(result, _modality):
        result["coverage"]["note"] = "unsafe SYNTHETIC-0"

    _install_fakes(monkeypatch, add_declared_value)
    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")
    result_path = tmp_path / "reports" / summary["inputs"][0]["result_json"]
    saved = json.loads(result_path.read_text(encoding="utf-8"))

    assert summary["acceptance_passed"] is False
    assert summary["failure_counts"]["unsafe_evidence"] == 9
    assert saved["probe"] is None


def test_runner_keeps_a_safe_summary_when_probe_raises(tmp_path, monkeypatch):
    _install_fakes(monkeypatch)
    monkeypatch.setattr(
        run_acceptance,
        "probe",
        lambda _document, _expectations: (_ for _ in ()).throw(RuntimeError("private text")),
    )

    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")

    assert summary["acceptance_passed"] is False
    assert summary["failure_counts"] == {"probe_error": 9}
    assert summary["aggregate_metrics"]["inputs"] == 9
    assert summary["aggregate_metrics"]["ocr_routes_expected"] == 9
    assert summary["aggregate_metrics"]["expected_values"] == 0
    assert all(item["metrics"] is None for item in summary["inputs"])
    raw = (tmp_path / "reports" / "summary.json").read_text(encoding="utf-8")
    assert "private text" not in raw


@pytest.mark.parametrize(
    ("failure_code", "mutate"),
    [
        (
            "source_type_mismatch",
            lambda result, _modality: result.update(source_type="text"),
        ),
        (
            "ocr_not_measured",
            lambda result, _modality: result["ocr"].update(status="skipped"),
        ),
        (
            "coverage_not_measured",
            lambda result, _modality: result["coverage"].update(status="skipped"),
        ),
        (
            "coverage_row_invalid",
            lambda result, _modality: result["coverage"]["values"][0].update(
                black_fraction=float("nan")
            ),
        ),
        (
            "privacy_alignment_incomplete",
            lambda result, _modality: (
                result["privacy_alignment"].update(aligned=1, unaligned=1),
                result["privacy_alignment"]["values"][1].update(aligned=False, alignment=None),
            ),
        ),
        (
            "residual_not_measured",
            lambda result, _modality: result["residual"].update(status="skipped"),
        ),
        (
            "residual_text_layer_present",
            lambda result, _modality: result["residual"]["text_arm"].update(
                text_layer_chars=10,
                vacuous=False,
            ),
        ),
        (
            "residual_ocr_not_measured",
            lambda result, _modality: result["residual"]["render_ocr"].update(status="skipped"),
        ),
        (
            "residual_ocr_exposed",
            lambda result, _modality: result["residual"]["render_ocr"].update(surviving=1),
        ),
        (
            "residual_ocr_row_invalid",
            lambda result, _modality: result["residual"]["render_ocr"]["values"][0].pop("survives"),
        ),
        (
            "residual_ocr_row_mismatch",
            lambda result, _modality: result["residual"]["values"][0].update(
                render_ocr_survives=True
            ),
        ),
        (
            "decoy_false_hit",
            lambda result, _modality: result["decoy_control"].update(
                false_hits=["synthetic-decoy"]
            ),
        ),
        (
            "residual_exposed",
            lambda result, _modality: result["residual"].update(exposed=1),
        ),
        (
            "residual_unmeasurable",
            lambda result, _modality: result["residual"].update(unmeasurable=1),
        ),
    ],
)
def test_runner_fails_each_binding_gate(tmp_path, monkeypatch, failure_code, mutate):
    _install_fakes(monkeypatch, mutate)

    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")

    assert summary["acceptance_passed"] is False
    assert summary["failure_counts"][failure_code] > 0
    assert any(
        failure["code"] == failure_code
        for input_result in summary["inputs"]
        for failure in input_result["failures"]
    )


def test_record_only_keeps_failures_but_returns_success(tmp_path, monkeypatch):
    def expose(result, _modality):
        result["residual"]["exposed"] = 1

    _install_fakes(monkeypatch, expose)
    reports = tmp_path / "reports"

    exit_code = run_acceptance.main(
        [
            "--corpus-dir",
            str(tmp_path / "corpus"),
            "--output-dir",
            str(reports),
            "--record-only",
        ]
    )

    assert exit_code == 0
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    assert summary["record_only"] is True
    assert summary["acceptance_passed"] is False
    assert summary["failure_counts"]["residual_exposed"] == 9


def test_default_cli_exit_is_nonzero_when_a_binding_gate_fails(tmp_path, monkeypatch):
    def skip_coverage(result, _modality):
        result["coverage"]["status"] = "skipped"

    _install_fakes(monkeypatch, skip_coverage)

    exit_code = run_acceptance.main(
        [
            "--corpus-dir",
            str(tmp_path / "corpus"),
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 1


def test_result_gate_does_not_mutate_the_probe_payload():
    payload = _result("degraded")
    original = deepcopy(payload)

    failures = run_acceptance.evaluate_result("degraded", EXPECTED_INDICES, payload)

    assert failures == []
    assert payload == original


def test_exact_extraction_is_telemetry_when_privacy_alignment_is_reliable():
    payload = _result("degraded")
    payload["extraction"].update(found=1, missing=1)
    payload["extraction"]["values"][1].update(found=False)

    failures = run_acceptance.evaluate_result("degraded", EXPECTED_INDICES, payload)

    assert failures == []


def test_result_gate_rejects_empty_expectations():
    payload = _result("digital")
    for section_name in ("extraction", "coverage", "residual"):
        payload[section_name]["values"] = []
    payload["extraction"].update(total=0, found=0, missing=0)
    payload["coverage"].update(values_measured=0, fully_covered=0)
    payload["residual"].update(removed=0, exposed=0, unmeasurable=0)

    failures = run_acceptance.evaluate_result("digital", (), payload)

    assert any(failure["code"] == "expectations_empty" for failure in failures)


def test_runner_rejects_an_input_with_empty_expectations(tmp_path, monkeypatch):
    _install_fakes(monkeypatch)
    monkeypatch.setattr(
        run_acceptance,
        "load_expectations",
        lambda _path: {"meta": {}, "values": []},
    )

    summary = run_acceptance.run_batch(tmp_path / "corpus", tmp_path / "reports")

    assert summary["acceptance_passed"] is False
    assert summary["failure_counts"]["expectations_empty"] == 9


@pytest.mark.parametrize(
    ("failure_code", "mutate"),
    [
        (
            "extraction_index_mismatch",
            lambda result: result["extraction"]["values"].__setitem__(
                1, {"index": 0, "field": "duplicate", "found": True}
            ),
        ),
        (
            "coverage_index_mismatch",
            lambda result: result["coverage"]["values"].pop(),
        ),
        (
            "residual_index_mismatch",
            lambda result: result["residual"]["values"].__setitem__(
                1, {"index": 7, "field": "unexpected", "verdict": "removed"}
            ),
        ),
        (
            "extraction_summary_inconsistent",
            lambda result: result["extraction"].update(total=1),
        ),
        (
            "extraction_summary_inconsistent",
            lambda result: result["extraction"]["values"][1].update(found=False),
        ),
        (
            "coverage_summary_inconsistent",
            lambda result: result["coverage"].update(values_measured=1),
        ),
        (
            "coverage_incomplete",
            lambda result: result["coverage"].update(fully_covered=1),
        ),
        (
            "residual_summary_inconsistent",
            lambda result: result["residual"].update(removed=1),
        ),
        (
            "residual_row_not_removed",
            lambda result: result["residual"]["values"][1].update(verdict="exposed"),
        ),
    ],
)
def test_result_gate_rejects_incomplete_or_inconsistent_measurements(failure_code, mutate):
    payload = _result("degraded")
    mutate(payload)

    failures = run_acceptance.evaluate_result("degraded", EXPECTED_INDICES, payload)

    assert any(failure["code"] == failure_code for failure in failures)


@pytest.mark.parametrize(
    ("repository", "expected"),
    [
        ({"commit": "abc", "dirty": False}, "synthetic_local_pass_clean"),
        ({"commit": "abc", "dirty": True}, "functional_pass_repository_dirty"),
        ({"commit": None, "dirty": None}, "functional_pass_repository_unknown"),
    ],
)
def test_evidence_status_qualifies_a_functional_pass_by_repository_state(repository, expected):
    assert run_acceptance.evidence_status(True, repository) == expected


def test_evidence_status_keeps_a_functional_failure_binding():
    assert (
        run_acceptance.evidence_status(False, {"commit": "abc", "dirty": False})
        == "functional_failure"
    )


def test_dirty_repository_cli_never_prints_an_unqualified_pass(tmp_path, monkeypatch, capsys):
    _install_fakes(monkeypatch)
    monkeypatch.setattr(
        run_acceptance,
        "repository_state",
        lambda: {"commit": "test-commit", "dirty": True},
    )

    exit_code = run_acceptance.main(
        [
            "--corpus-dir",
            str(tmp_path / "corpus"),
            "--output-dir",
            str(tmp_path / "reports"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "FUNCTIONAL PASS ONLY" in output
    assert "not release-grade evidence" in output
    assert "\nPASS:" not in output


def test_runtime_versions_include_rendering_dependencies(monkeypatch):
    versions = {
        "paddlepaddle": "3.2.0",
        "paddleocr": "3.3.2",
        "Pillow": "11.3.0",
        "reportlab": "4.4.3",
        "pypdfium2": "4.30.0",
        "opencv-contrib-python": "4.11.0",
        "opencv-python": None,
        "opencv-python-headless": None,
        "opencv-contrib-python-headless": None,
    }
    monkeypatch.setattr(
        run_acceptance,
        "_distribution_version",
        lambda name: versions[name],
    )
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(__version__="4.11.0"))

    result = run_acceptance.runtime_versions()

    assert result["pillow"] == "11.3.0"
    assert result["reportlab"] == "4.4.3"
    assert result["pypdfium2"] == "4.30.0"
