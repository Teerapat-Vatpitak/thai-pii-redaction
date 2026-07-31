"""Run the nine-input synthetic government-form acceptance batch locally.

This produces synthetic local regression evidence only. It is not evidence of
general government-form accuracy, physical-scan accuracy, or a blind holdout.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from benchmark.data.probe.gov_forms.generate_inputs import (
    DEFAULT_CORPUS,
    CorpusRow,
    generate_corpus,
)
from benchmark.probe_document import load_expectations, probe

DEFAULT_OUTPUT = Path("benchmark/reports/gov-forms-phase2")
REPO_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_SCHEMA_VERSION = 2
EXPECTED_INPUTS = 9
EXPECTED_SOURCE_TYPES = {
    "digital": "pdf_text",
    "print_like": "pdf_hybrid",
    "degraded": "pdf_hybrid",
}
EVIDENCE_SCOPE = (
    "Synthetic local regression evidence only; these transformed blank forms do not establish "
    "general government-form accuracy, physical-scan accuracy, or blind-holdout performance."
)


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def runtime_versions() -> dict[str, Any]:
    """Return package versions used by the OCR run."""

    opencv_distributions = {
        name: version
        for name in (
            "opencv-contrib-python",
            "opencv-python",
            "opencv-python-headless",
            "opencv-contrib-python-headless",
        )
        if (version := _distribution_version(name)) is not None
    }
    try:
        import cv2

        cv2_version = str(cv2.__version__)
    except (ImportError, OSError):
        cv2_version = None

    return {
        "python": platform.python_version(),
        "paddlepaddle": _distribution_version("paddlepaddle"),
        "paddleocr": _distribution_version("paddleocr"),
        "pillow": _distribution_version("Pillow"),
        "reportlab": _distribution_version("reportlab"),
        "pypdfium2": _distribution_version("pypdfium2"),
        "opencv": {
            "runtime": cv2_version,
            "distributions": opencv_distributions,
        },
    }


def repository_state() -> dict[str, Any]:
    """Return the commit and whether the repo has changes."""

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"commit": None, "dirty": None}
    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def evidence_status(functional_passed: bool, repository: dict[str, Any]) -> str:
    """Label the result with the repository state."""

    if not functional_passed:
        return "functional_failure"
    if repository.get("commit") is None or repository.get("dirty") is None:
        return "functional_pass_repository_unknown"
    if repository["dirty"]:
        return "functional_pass_repository_dirty"
    return "synthetic_local_pass_clean"


def _failure(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _validate_indices(
    section_name: str,
    section: dict[str, Any],
    expected_indices: tuple[int, ...],
) -> list[dict[str, str]]:
    rows = section.get("values")
    actual_indices = (
        [row.get("index") for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )
    valid = (
        isinstance(rows, list)
        and len(rows) == len(expected_indices)
        and len(actual_indices) == len(rows)
        and all(type(index) is int for index in actual_indices)
        and Counter(actual_indices) == Counter(expected_indices)
    )
    if valid:
        return []
    return [
        _failure(
            f"{section_name}_index_mismatch",
            (
                f"{section_name} rows must contain each of the "
                f"{len(expected_indices)} expected indices exactly once"
            ),
        )
    ]


def _valid_count(value: Any) -> bool:
    return type(value) is int and value >= 0


def evaluate_result(
    modality: str,
    expected_indices: tuple[int, ...],
    result: dict[str, Any],
) -> list[dict[str, str]]:
    """Return safety and run failures for one result."""

    expected_indices = tuple(expected_indices)
    expected_total = len(expected_indices)
    failures: list[dict[str, str]] = []
    if expected_total == 0:
        failures.append(
            _failure(
                "expectations_empty",
                "each input must contain at least one expected synthetic value",
            )
        )
    if len(set(expected_indices)) != expected_total:
        failures.append(
            _failure(
                "expectations_invalid",
                "expected indices must be unique before a probe result can be evaluated",
            )
        )

    expected_source_type = EXPECTED_SOURCE_TYPES.get(modality)
    if expected_source_type is None:
        failures.append(
            _failure("unexpected_modality", f"modality {modality!r} has no acceptance route")
        )
    elif result.get("source_type") != expected_source_type:
        failures.append(
            _failure(
                "source_type_mismatch",
                f"expected {expected_source_type}, got {result.get('source_type')!r}",
            )
        )

    if modality in {"print_like", "degraded"}:
        ocr_status = result.get("ocr", {}).get("status")
        if ocr_status != "measured":
            failures.append(
                _failure(
                    "ocr_not_measured",
                    f"image-only input reported OCR status {ocr_status!r}",
                )
            )

    extraction = result.get("extraction", {})
    failures.extend(_validate_indices("extraction", extraction, expected_indices))
    extraction_counts = (
        extraction.get("total"),
        extraction.get("found"),
        extraction.get("missing"),
    )
    extraction_rows = extraction.get("values", [])
    row_found = (
        sum(1 for row in extraction_rows if isinstance(row, dict) and row.get("found") is True)
        if isinstance(extraction_rows, list)
        else -1
    )
    row_missing = (
        sum(1 for row in extraction_rows if isinstance(row, dict) and row.get("found") is False)
        if isinstance(extraction_rows, list)
        else -1
    )
    if (
        not all(_valid_count(value) for value in extraction_counts)
        or extraction_counts[0] != expected_total
        or extraction_counts[1] + extraction_counts[2] != extraction_counts[0]
        or extraction_counts[1] != row_found
        or extraction_counts[2] != row_missing
    ):
        failures.append(
            _failure(
                "extraction_summary_inconsistent",
                "extraction total/found/missing counts do not match the expected cardinality",
            )
        )
    if (
        extraction.get("found") != expected_total
        or extraction.get("missing") != 0
        or not isinstance(extraction_rows, list)
        or any(not isinstance(row, dict) or row.get("found") is not True for row in extraction_rows)
    ):
        failures.append(
            _failure(
                "extraction_incomplete",
                "every expected synthetic value must survive extraction",
            )
        )

    coverage_status = result.get("coverage", {}).get("status")
    if coverage_status != "measured":
        failures.append(
            _failure(
                "coverage_not_measured",
                f"redaction coverage status is {coverage_status!r}",
            )
        )
    else:
        coverage = result["coverage"]
        failures.extend(_validate_indices("coverage", coverage, expected_indices))
        coverage_rows = coverage.get("values", [])
        measured_rows = (
            sum(
                1
                for row in coverage_rows
                if isinstance(row, dict) and row.get("black_fraction") is not None
            )
            if isinstance(coverage_rows, list)
            else -1
        )
        covered_rows = (
            sum(
                1
                for row in coverage_rows
                if isinstance(row, dict) and row.get("fully_covered") is True
            )
            if isinstance(coverage_rows, list)
            else -1
        )
        values_measured = coverage.get("values_measured")
        fully_covered = coverage.get("fully_covered")
        if (
            not _valid_count(values_measured)
            or not _valid_count(fully_covered)
            or values_measured != measured_rows
            or fully_covered != covered_rows
        ):
            failures.append(
                _failure(
                    "coverage_summary_inconsistent",
                    "coverage summary counts do not match the per-value rows",
                )
            )
        if values_measured != expected_total or fully_covered != expected_total:
            failures.append(
                _failure(
                    "coverage_incomplete",
                    "every expected synthetic value must be measured and fully covered",
                )
            )

    residual = result.get("residual", {})
    residual_status = residual.get("status")
    if residual_status != "measured":
        failures.append(
            _failure(
                "residual_not_measured",
                f"residual status is {residual_status!r}",
            )
        )
    else:
        failures.extend(_validate_indices("residual", residual, expected_indices))
        residual_rows = residual.get("values", [])
        verdicts = (
            [row.get("verdict") for row in residual_rows if isinstance(row, dict)]
            if isinstance(residual_rows, list)
            else []
        )
        exposed = residual.get("exposed")
        unmeasurable = residual.get("unmeasurable")
        removed = residual.get("removed")
        row_removed = verdicts.count("removed")
        row_exposed = sum(verdict in {"exposed", "ink_above_box"} for verdict in verdicts)
        row_unmeasurable = verdicts.count("unmeasurable")
        if (
            not all(_valid_count(value) for value in (removed, exposed, unmeasurable))
            or removed + exposed + unmeasurable != expected_total
            or removed != row_removed
            or exposed != row_exposed
            or unmeasurable != row_unmeasurable
        ):
            failures.append(
                _failure(
                    "residual_summary_inconsistent",
                    "residual summary counts do not match expected cardinality and row verdicts",
                )
            )
        if not isinstance(exposed, int):
            failures.append(
                _failure("residual_summary_missing", "residual exposed count is not an integer")
            )
        elif exposed:
            failures.append(
                _failure("residual_exposed", f"{exposed} synthetic value(s) remain exposed")
            )
        if not isinstance(unmeasurable, int):
            failures.append(
                _failure(
                    "residual_summary_missing",
                    "residual unmeasurable count is not an integer",
                )
            )
        elif unmeasurable:
            failures.append(
                _failure(
                    "residual_unmeasurable",
                    f"{unmeasurable} synthetic value(s) are unmeasurable",
                )
            )
        if len(verdicts) != expected_total or any(verdict != "removed" for verdict in verdicts):
            failures.append(
                _failure(
                    "residual_row_not_removed",
                    "every expected synthetic value must have a removed verdict",
                )
            )

    false_hits = result.get("decoy_control", {}).get("false_hits")
    if not isinstance(false_hits, list):
        failures.append(_failure("decoy_control_missing", "decoy false_hits is not a list"))
    elif false_hits:
        failures.append(
            _failure(
                "decoy_false_hit",
                f"{len(false_hits)} declared decoy(s) appeared in extracted text",
            )
        )
    return failures


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _safe_probe_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove value text before a probe result is saved."""
    safe = deepcopy(result)
    for row in safe.get("extraction", {}).get("values", []):
        value = row.pop("value", None)
        if value is not None:
            row["value_chars"] = len(str(value))

    for row in safe.get("ocr", {}).get("values", []):
        expected = row.pop("expected", None)
        best_match = row.pop("best_match", None)
        if expected is not None:
            row["expected_chars"] = len(str(expected))
        if best_match is not None:
            row["best_match_chars"] = len(str(best_match))

    text_arm = safe.get("residual", {}).get("text_arm")
    if isinstance(text_arm, dict):
        survivors = text_arm.pop("values_surviving_in_text", None)
        if survivors is not None:
            text_arm["values_surviving_in_text_count"] = (
                len(survivors) if isinstance(survivors, list) else None
            )

    decoy_control = safe.get("decoy_control")
    if isinstance(decoy_control, dict):
        false_hits = decoy_control.pop("false_hits", None)
        if false_hits is not None:
            decoy_control["false_hit_count"] = (
                len(false_hits) if isinstance(false_hits, list) else None
            )
    return safe


def _result_metrics(modality: str, result: dict[str, Any]) -> dict[str, Any]:
    """Return only counts and labels used in the summary."""
    extraction = result.get("extraction", {})
    detection = result.get("detection", {})
    coverage = result.get("coverage", {})
    residual = result.get("residual", {})
    false_hits = result.get("decoy_control", {}).get("false_hits")
    return {
        "source_type": result.get("source_type"),
        "source_route_correct": result.get("source_type") == EXPECTED_SOURCE_TYPES.get(modality),
        "ocr_status": result.get("ocr", {}).get("status"),
        "ocr_mean_char_accuracy": result.get("ocr", {}).get("mean_char_accuracy"),
        "expected_values": extraction.get("total"),
        "extraction_found": extraction.get("found"),
        "detection_total": detection.get("total"),
        "detection_detected": detection.get("detected"),
        "detection_scored": detection.get("scored"),
        "type_matches": detection.get("type_matches"),
        "coverage_fully_covered": coverage.get("fully_covered"),
        "residual_removed": residual.get("removed"),
        "residual_exposed": residual.get("exposed"),
        "residual_unmeasurable": residual.get("unmeasurable"),
        "decoy_false_hit_count": len(false_hits) if isinstance(false_hits, list) else None,
    }


def _aggregate_metrics(inputs: list[dict[str, Any]]) -> dict[str, int]:
    """Add the safe counters from every input."""

    def metric(item: dict[str, Any], key: str) -> Any:
        metrics = item.get("metrics")
        return metrics.get(key) if isinstance(metrics, dict) else None

    def total(key: str) -> int:
        result = 0
        for item in inputs:
            value = metric(item, key)
            if type(value) is int:
                result += value
        return result

    return {
        "inputs": len(inputs),
        "source_routes_correct": sum(
            metric(item, "source_route_correct") is True for item in inputs
        ),
        "ocr_routes_expected": sum(item["modality"] != "digital" for item in inputs),
        "ocr_routes_measured": sum(
            item["modality"] != "digital" and metric(item, "ocr_status") == "measured"
            for item in inputs
        ),
        "expected_values": total("expected_values"),
        "extraction_found": total("extraction_found"),
        "detection_total": total("detection_total"),
        "detection_detected": total("detection_detected"),
        "detection_scored": total("detection_scored"),
        "type_matches": total("type_matches"),
        "coverage_fully_covered": total("coverage_fully_covered"),
        "residual_removed": total("residual_removed"),
        "residual_exposed": total("residual_exposed"),
        "residual_unmeasurable": total("residual_unmeasurable"),
        "decoy_inputs_without_false_hits": sum(
            metric(item, "decoy_false_hit_count") == 0 for item in inputs
        ),
    }


def _result_filename(row: CorpusRow) -> str:
    return f"{Path(row.document).stem}.result.json"


def run_batch(
    corpus_dir: str | Path = DEFAULT_CORPUS,
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    record_only: bool = False,
) -> dict[str, Any]:
    """Build and check all nine inputs in one process."""

    corpus_dir = Path(corpus_dir)
    output_dir = Path(output_dir)
    input_dir = output_dir / "inputs"
    result_dir = output_dir / "results"
    rows = generate_corpus(corpus_dir, input_dir)

    batch_failures: list[dict[str, str]] = []
    if len(rows) != EXPECTED_INPUTS:
        batch_failures.append(
            _failure(
                "corpus_shape",
                f"expected {EXPECTED_INPUTS} generated inputs, got {len(rows)}",
            )
        )

    identities = [(row.form_code, row.modality) for row in rows]
    if len(set(identities)) != len(identities):
        batch_failures.append(
            _failure("corpus_shape", "generated form/modality identities are not unique")
        )

    inputs: list[dict[str, Any]] = []
    for row in rows:
        document = input_dir / row.document
        expectations_path = input_dir / row.expectations
        result_path = result_dir / _result_filename(row)

        try:
            expectations = load_expectations(expectations_path)
            result = probe(document, expectations)
            expected_indices = tuple(value.index for value in expectations["values"])
            failures = evaluate_result(row.modality, expected_indices, result)
            metrics = _result_metrics(row.modality, result)
            result_payload: dict[str, Any] = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "evidence_scope": EVIDENCE_SCOPE,
                "form_code": row.form_code,
                "modality": row.modality,
                "document": row.document,
                "expectations": row.expectations,
                "failures": failures,
                "probe": _safe_probe_result(result),
            }
        except Exception as exc:
            metrics = None
            failures = [
                _failure(
                    "probe_error",
                    f"probe raised {type(exc).__name__}; exception text is omitted from evidence",
                )
            ]
            result_payload = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "evidence_scope": EVIDENCE_SCOPE,
                "form_code": row.form_code,
                "modality": row.modality,
                "document": row.document,
                "expectations": row.expectations,
                "failures": failures,
                "probe": None,
            }

        _write_json(result_path, result_payload)
        inputs.append(
            {
                "form_code": row.form_code,
                "modality": row.modality,
                "document": row.document,
                "expectations": row.expectations,
                "result_json": result_path.relative_to(output_dir).as_posix(),
                "passed": not failures,
                "failures": failures,
                "metrics": metrics,
            }
        )

    all_failures = batch_failures + [failure for item in inputs for failure in item["failures"]]
    failure_counts = Counter(failure["code"] for failure in all_failures)
    functional_passed = not all_failures
    repository = repository_state()
    summary = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_scope": EVIDENCE_SCOPE,
        "record_only": record_only,
        "repository": repository,
        "runtime_versions": runtime_versions(),
        "generated_inputs": len(rows),
        "acceptance_passed": functional_passed,
        "evidence_status": evidence_status(functional_passed, repository),
        "failure_counts": dict(sorted(failure_counts.items())),
        "aggregate_metrics": _aggregate_metrics(inputs),
        "batch_failures": batch_failures,
        "inputs": inputs,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--record-only",
        action="store_true",
        help="write baseline evidence but return zero even when binding gates fail",
    )
    args = parser.parse_args(argv)

    summary = run_batch(
        corpus_dir=args.corpus_dir,
        output_dir=args.output_dir,
        record_only=args.record_only,
    )
    if not summary["acceptance_passed"]:
        status = "FUNCTIONAL FAIL"
    elif summary["evidence_status"] == "synthetic_local_pass_clean":
        status = "SYNTHETIC LOCAL PASS"
    elif summary["evidence_status"] == "functional_pass_repository_dirty":
        status = "FUNCTIONAL PASS ONLY (repository dirty; not release-grade evidence)"
    else:
        status = "FUNCTIONAL PASS ONLY (repository state unknown; not release-grade evidence)"
    print(EVIDENCE_SCOPE)
    print(
        f"{status}: {summary['generated_inputs']} input(s), "
        f"{sum(summary['failure_counts'].values())} gate failure(s)"
    )
    print(f"summary: {(args.output_dir / 'summary.json').resolve()}")
    return 0 if args.record_only or summary["acceptance_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
