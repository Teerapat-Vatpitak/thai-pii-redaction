"""Run the nine-input synthetic government-form acceptance batch locally.

All nine inputs exercise OCR (every modality, including "digital", embeds a
raster of the page and routes pdf_hybrid), so an OCR-stack transient can
strike any input.

This produces synthetic local regression evidence only. It is not evidence of
general government-form accuracy, physical-scan accuracy, or a blind holdout.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import re
import subprocess
import sys
import traceback
from collections import Counter
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
EVIDENCE_SCHEMA_VERSION = 3
EXPECTED_INPUTS = 9
EXPECTED_SOURCE_TYPES = {
    "digital": "pdf_hybrid",
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

    if expected_source_type == "pdf_hybrid":
        ocr = result.get("ocr", {})
        ocr_status = ocr.get("status")
        if ocr_status != "measured":
            failures.append(
                _failure(
                    "ocr_not_measured",
                    f"hybrid input reported OCR status {ocr_status!r}",
                )
            )
        else:
            failures.extend(_validate_indices("ocr", ocr, expected_indices))

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
    privacy_alignment = result.get("privacy_alignment", {})
    failures.extend(_validate_indices("privacy_alignment", privacy_alignment, expected_indices))
    privacy_rows = privacy_alignment.get("values", [])
    row_aligned = (
        sum(row.get("aligned") is True for row in privacy_rows if isinstance(row, dict))
        if isinstance(privacy_rows, list)
        else -1
    )
    aligned = privacy_alignment.get("aligned")
    unaligned = privacy_alignment.get("unaligned")
    if (
        privacy_alignment.get("total") != expected_total
        or not _valid_count(aligned)
        or not _valid_count(unaligned)
        or aligned + unaligned != expected_total
        or aligned != row_aligned
    ):
        failures.append(
            _failure(
                "privacy_alignment_summary_inconsistent",
                "privacy alignment counts do not match the expected value rows",
            )
        )
    if aligned != expected_total or unaligned != 0:
        failures.append(
            _failure(
                "privacy_alignment_incomplete",
                "every expected value needs a reliable source range or test region",
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
        invalid_coverage_rows = not isinstance(coverage_rows, list) or any(
            not isinstance(row, dict)
            or (
                row.get("black_fraction") is not None
                and (
                    isinstance(row.get("black_fraction"), bool)
                    or not isinstance(row.get("black_fraction"), (int, float))
                    or not math.isfinite(row["black_fraction"])
                    or not 0.0 <= row["black_fraction"] <= 1.0
                )
            )
            for row in coverage_rows
        )
        if invalid_coverage_rows:
            failures.append(
                _failure(
                    "coverage_row_invalid",
                    "coverage rows need a finite black fraction from 0 to 1",
                )
            )
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
        text_arm = residual.get("text_arm")
        if (
            not isinstance(text_arm, dict)
            or type(text_arm.get("text_layer_chars")) is not int
            or text_arm.get("text_layer_chars", -1) < 0
            or type(text_arm.get("vacuous")) is not bool
        ):
            failures.append(
                _failure(
                    "residual_text_arm_invalid",
                    "residual text-arm fields are missing or invalid",
                )
            )
        elif text_arm["text_layer_chars"] != 0 or text_arm["vacuous"] is not True:
            failures.append(
                _failure(
                    "residual_text_layer_present",
                    "the redacted PDF must have no extractable text layer",
                )
            )

    if expected_source_type == "pdf_hybrid":
        render_ocr = residual.get("render_ocr", {})
        render_status = render_ocr.get("status")
        if render_status != "measured":
            failures.append(
                _failure(
                    "residual_ocr_not_measured",
                    f"redacted-render OCR status is {render_status!r}",
                )
            )
        else:
            failures.extend(_validate_indices("residual_ocr", render_ocr, expected_indices))
            render_rows = render_ocr.get("values", [])
            valid_render_rows = (
                isinstance(render_rows, list)
                and len(render_rows) == expected_total
                and all(
                    isinstance(row, dict) and type(row.get("survives")) is bool
                    for row in render_rows
                )
            )
            if not valid_render_rows:
                failures.append(
                    _failure(
                        "residual_ocr_row_invalid",
                        "each redacted-render OCR row needs a boolean survives result",
                    )
                )
            row_surviving = (
                sum(row.get("survives") is True for row in render_rows if isinstance(row, dict))
                if isinstance(render_rows, list)
                else -1
            )
            surviving = render_ocr.get("surviving")
            if not _valid_count(surviving) or surviving != row_surviving:
                failures.append(
                    _failure(
                        "residual_ocr_summary_inconsistent",
                        "redacted-render OCR count does not match its value rows",
                    )
                )
            if isinstance(surviving, int) and surviving:
                failures.append(
                    _failure(
                        "residual_ocr_exposed",
                        f"redacted-render OCR found {surviving} synthetic value(s)",
                    )
                )
            render_by_index = {
                row["index"]: row.get("survives")
                for row in render_rows
                if isinstance(row, dict) and type(row.get("index")) is int
            }
            residual_rows = residual.get("values", [])
            if not isinstance(residual_rows, list) or any(
                not isinstance(row, dict)
                or type(row.get("render_ocr_survives")) is not bool
                or row.get("render_ocr_survives") != render_by_index.get(row.get("index"))
                for row in residual_rows
            ):
                failures.append(
                    _failure(
                        "residual_ocr_row_mismatch",
                        "residual rows must match redacted-render OCR results",
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


def _iter_str_leaves(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _iter_str_leaves(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_str_leaves(item)


def _contains_declared_value(payload: dict[str, Any], values: list[str]) -> bool:
    # Leaf-wise first: a value carrying a quote or backslash survives
    # json.dumps only in escaped form, so scanning the serialized blob alone
    # would miss it. The serialized pass stays as a second net for values
    # split across neighbouring keys.
    leaves = list(_iter_str_leaves(payload))
    if any(value and any(value in leaf for leaf in leaves) for value in values):
        return True
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return any(value and value in serialized for value in values)


# Paddle prefixes enforce-class messages with "(PreconditionNotMet) ...". Do
# not keep arbitrary alphabetic text in parentheses: an English name can look
# like an error code. Only the observed native code is allowlisted; all other
# message text stays out of the fingerprint.
_ERROR_CODE_TOKEN = re.compile(r"^\(([A-Za-z]{3,32})\)")
_SAFE_ERROR_CODES = frozenset({"PreconditionNotMet"})
_TRACEBACK_TAIL_FRAMES = 8


def _frame_location(filename: str) -> str:
    """Relativize a traceback frame path to the repo root or site-packages;
    anything else is reduced to a fixed marker (never an absolute path or a
    user-controlled basename)."""
    path = Path(filename)
    parts = path.parts
    for marker in ("site-packages", "dist-packages"):
        if marker in parts:
            return Path(*parts[parts.index(marker) + 1 :]).as_posix()
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except (OSError, ValueError):
        return "<external>"


def _exception_fingerprint(exc: BaseException) -> dict[str, Any]:
    """Structurally PII-free attribution for a probe failure.

    Exception type names and code locations only -- message text never enters
    evidence (and no hash of it either: a hash of a value counts as a value).
    The one message-derived field, error_code_token, is matched by the
    whitelist regex above.
    """
    chain: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(f"{type(current).__module__}.{type(current).__qualname__}")
        current = current.__cause__ or current.__context__
    tail = [
        f"{_frame_location(frame.filename)}:{frame.lineno}:{frame.name}"
        for frame in traceback.extract_tb(exc.__traceback__)[-_TRACEBACK_TAIL_FRAMES:]
    ]
    fingerprint: dict[str, Any] = {"exception_chain": chain, "traceback_tail": tail}
    token = _ERROR_CODE_TOKEN.match(str(exc))
    if token and token.group(1) in _SAFE_ERROR_CODES:
        fingerprint["error_code_token"] = token.group(1)
    return fingerprint


def _safe_probe_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep only safe fields used by the evidence report."""

    def pick(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {key: value[key] for key in keys if key in value}

    def rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [pick(row, keys) for row in value if isinstance(row, dict)]

    extraction = result.get("extraction", {})
    safe_extraction = pick(extraction, ("total", "found", "missing"))
    safe_extraction["values"] = rows(
        extraction.get("values") if isinstance(extraction, dict) else None,
        ("index", "field", "type", "found", "start", "end", "match"),
    )
    for source, target in zip(
        extraction.get("values", []) if isinstance(extraction, dict) else [],
        safe_extraction["values"],
        strict=False,
    ):
        if isinstance(source, dict) and "value" in source:
            target["value_chars"] = len(str(source["value"]))

    ocr = result.get("ocr", {})
    safe_ocr = pick(ocr, ("status", "reason", "mean_char_accuracy"))
    safe_ocr["values"] = rows(
        ocr.get("values") if isinstance(ocr, dict) else None,
        (
            "index",
            "field",
            "status",
            "reason",
            "start",
            "end",
            "edit_distance",
            "char_accuracy",
            "source_alignment",
        ),
    )
    for source, target in zip(
        ocr.get("values", []) if isinstance(ocr, dict) else [],
        safe_ocr["values"],
        strict=False,
    ):
        if isinstance(source, dict) and "expected" in source:
            target["expected_chars"] = len(str(source["expected"]))
        if isinstance(source, dict) and "best_match" in source:
            target["best_match_chars"] = len(str(source["best_match"]))

    detection = result.get("detection", {})
    safe_detection = pick(
        detection,
        ("total", "detected", "scored", "type_matches", "out_of_scheme"),
    )
    safe_detection["values"] = rows(
        detection.get("values") if isinstance(detection, dict) else None,
        (
            "index",
            "field",
            "expected_type",
            "status",
            "alignment",
            "detected",
            "detected_types",
            "type_match",
            "char_coverage",
        ),
    )

    privacy = result.get("privacy_alignment", {})
    safe_privacy = pick(privacy, ("total", "aligned", "unaligned"))
    safe_privacy["values"] = rows(
        privacy.get("values") if isinstance(privacy, dict) else None,
        ("index", "field", "aligned", "alignment"),
    )

    coverage = result.get("coverage", {})
    safe_coverage = pick(
        coverage,
        (
            "status",
            "reason",
            "note",
            "render_scale",
            "values_measured",
            "fully_covered",
            "mean_black_fraction",
        ),
    )
    safe_coverage["values"] = rows(
        coverage.get("values") if isinstance(coverage, dict) else None,
        (
            "index",
            "field",
            "status",
            "alignment",
            "words",
            "black_pixels",
            "total_pixels",
            "black_fraction",
            "fully_covered",
        ),
    )

    residual = result.get("residual", {})
    safe_residual = pick(
        residual,
        ("status", "reason", "removed", "exposed", "unmeasurable"),
    )
    safe_residual["values"] = rows(
        residual.get("values") if isinstance(residual, dict) else None,
        (
            "index",
            "field",
            "verdict",
            "reason",
            "alignment",
            "text_arm_survives",
            "render_ocr_survives",
            "black_fraction",
            "ink_above_box_pixels",
        ),
    )
    text_arm = residual.get("text_arm") if isinstance(residual, dict) else None
    safe_text_arm = pick(
        text_arm,
        ("redacted_source_type", "text_layer_chars", "vacuous", "note"),
    )
    if isinstance(text_arm, dict) and "values_surviving_in_text" in text_arm:
        survivors = text_arm["values_surviving_in_text"]
        safe_text_arm["values_surviving_in_text_count"] = (
            len(survivors) if isinstance(survivors, list) else None
        )
    safe_residual["text_arm"] = safe_text_arm

    render_ocr = residual.get("render_ocr") if isinstance(residual, dict) else None
    safe_render_ocr = pick(
        render_ocr,
        ("status", "reason", "minimum_accuracy", "text_chars", "surviving"),
    )
    safe_render_ocr["values"] = rows(
        render_ocr.get("values") if isinstance(render_ocr, dict) else None,
        ("index", "field", "survives", "match", "char_accuracy"),
    )
    for source, target in zip(
        render_ocr.get("values", []) if isinstance(render_ocr, dict) else [],
        safe_render_ocr["values"],
        strict=False,
    ):
        if isinstance(source, dict) and "expected" in source:
            target["expected_chars"] = len(str(source["expected"]))
        if isinstance(source, dict) and "best_match" in source:
            target["best_match_chars"] = len(str(source["best_match"]))
    safe_residual["render_ocr"] = safe_render_ocr

    order = result.get("order", {})
    safe_order = pick(
        order,
        (
            "inversions",
            "max_inversions",
            "normalized_inversions",
            "placed_order",
            "extracted_order",
            "meaningful",
            "reason",
            "layout",
            "layout_source",
        ),
    )
    safe_order["columns"] = pick(
        order.get("columns") if isinstance(order, dict) else None,
        ("verdict", "reason", "rows", "wide_gap_rows", "max_gap_pt"),
    )

    meta = result.get("extract_meta", {})
    safe_meta = pick(
        meta,
        ("ocr_confidence", "human_review", "pages_ocred", "pages_text_layer"),
    )
    if isinstance(meta, dict):
        safe_meta["ocr_text_range_count"] = len(meta.get("ocr_text_ranges", []))
        safe_meta["warning_count"] = len(meta.get("warnings", []))

    decoy = result.get("decoy_control", {})
    safe_decoy = pick(decoy, ("checked", "note"))
    if isinstance(decoy, dict) and "false_hits" in decoy:
        false_hits = decoy["false_hits"]
        safe_decoy["false_hit_count"] = len(false_hits) if isinstance(false_hits, list) else None

    return {
        **pick(
            result,
            (
                "source_type",
                "text_chars",
                "word_bboxes",
                "unaligned_word_bboxes",
                "entities_detected",
            ),
        ),
        "extract_meta": safe_meta,
        "extraction": safe_extraction,
        "order": safe_order,
        "ocr": safe_ocr,
        "detection": safe_detection,
        "privacy_alignment": safe_privacy,
        "coverage": safe_coverage,
        "residual": safe_residual,
        "decoy_control": safe_decoy,
    }


def _result_metrics(modality: str, result: dict[str, Any]) -> dict[str, Any]:
    """Return only counts and labels used in the summary."""
    extraction = result.get("extraction", {})
    detection = result.get("detection", {})
    privacy_alignment = result.get("privacy_alignment", {})
    coverage = result.get("coverage", {})
    residual = result.get("residual", {})
    render_ocr = residual.get("render_ocr", {})
    false_hits = result.get("decoy_control", {}).get("false_hits")
    return {
        "source_type": result.get("source_type"),
        "source_route_correct": result.get("source_type") == EXPECTED_SOURCE_TYPES.get(modality),
        "ocr_status": result.get("ocr", {}).get("status"),
        "ocr_mean_char_accuracy": result.get("ocr", {}).get("mean_char_accuracy"),
        "expected_values": extraction.get("total"),
        "extraction_found": extraction.get("found"),
        "privacy_aligned": privacy_alignment.get("aligned"),
        "detection_total": detection.get("total"),
        "detection_detected": detection.get("detected"),
        "detection_scored": detection.get("scored"),
        "type_matches": detection.get("type_matches"),
        "coverage_fully_covered": coverage.get("fully_covered"),
        "residual_removed": residual.get("removed"),
        "residual_exposed": residual.get("exposed"),
        "residual_unmeasurable": residual.get("unmeasurable"),
        "residual_ocr_status": render_ocr.get("status"),
        "residual_ocr_surviving": render_ocr.get("surviving"),
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
        "ocr_routes_expected": sum(
            EXPECTED_SOURCE_TYPES.get(item["modality"]) == "pdf_hybrid" for item in inputs
        ),
        "ocr_routes_measured": sum(
            EXPECTED_SOURCE_TYPES.get(item["modality"]) == "pdf_hybrid"
            and metric(item, "ocr_status") == "measured"
            for item in inputs
        ),
        "expected_values": total("expected_values"),
        "extraction_found": total("extraction_found"),
        "privacy_aligned": total("privacy_aligned"),
        "detection_total": total("detection_total"),
        "detection_detected": total("detection_detected"),
        "detection_scored": total("detection_scored"),
        "type_matches": total("type_matches"),
        "coverage_fully_covered": total("coverage_fully_covered"),
        "residual_removed": total("residual_removed"),
        "residual_exposed": total("residual_exposed"),
        "residual_unmeasurable": total("residual_unmeasurable"),
        "residual_ocr_routes_measured": sum(
            metric(item, "residual_ocr_status") == "measured" for item in inputs
        ),
        "residual_ocr_surviving": total("residual_ocr_surviving"),
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
    overwrite: bool = False,
) -> dict[str, Any]:
    """Build and check all nine inputs in one process."""

    corpus_dir = Path(corpus_dir)
    output_dir = Path(output_dir)
    summary_path = output_dir / "summary.json"
    if summary_path.exists() and not overwrite:
        # A failing run's artifacts must survive its rerun (same idiom as
        # exporter.py): refuse before anything under output_dir is touched.
        raise FileExistsError(
            f"Evidence already exists: {summary_path}. "
            "Use --overwrite (run_batch(overwrite=True)) to replace it."
        )
    if summary_path.exists():
        # Overwriting: drop the old verdict FIRST. summary.json is written
        # last, so a run interrupted mid-loop would otherwise leave a stale
        # pass verdict pointing at result files from two different runs.
        summary_path.unlink()
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

        declared_values: list[str] = []
        try:
            expectations = load_expectations(expectations_path)
            declared_values = [value.value for value in expectations["values"]]
            declared_values.extend(str(value) for value in expectations.get("decoys", []))
            result = probe(document, expectations)
            expected_indices = tuple(value.index for value in expectations["values"])
            failures = evaluate_result(row.modality, expected_indices, result)
            metrics = _result_metrics(row.modality, result)
            safe_probe = _safe_probe_result(result)
            result_payload: dict[str, Any] = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "evidence_scope": EVIDENCE_SCOPE,
                "form_code": row.form_code,
                "modality": row.modality,
                "document": row.document,
                "expectations": row.expectations,
                "failures": failures,
                "probe": safe_probe,
            }
            if _contains_declared_value(result_payload, declared_values):
                failures.append(
                    _failure(
                        "unsafe_evidence",
                        "a declared value reached the saved probe payload",
                    )
                )
                result_payload["probe"] = None
        except Exception as exc:
            metrics = None
            failures = [
                _failure(
                    "probe_error",
                    f"probe raised {type(exc).__name__}; exception text is omitted from evidence",
                )
            ]
            fingerprint: dict[str, Any] | None = _exception_fingerprint(exc)
            if _contains_declared_value(fingerprint, declared_values):
                failures.append(
                    _failure(
                        "unsafe_evidence",
                        "a declared value reached the exception fingerprint",
                    )
                )
                fingerprint = None
            # The message may contain document text or a provider/native error
            # body. Keep operator diagnostics to the same safe fingerprint
            # written to the artifact; never print the raw exception or full
            # traceback.
            safe_fingerprint = (
                json.dumps(fingerprint, ensure_ascii=False, sort_keys=True)
                if fingerprint is not None
                else "suppressed"
            )
            print(
                f"probe failed; exception text omitted; fingerprint={safe_fingerprint}",
                file=sys.stderr,
            )
            result_payload = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "evidence_scope": EVIDENCE_SCOPE,
                "form_code": row.form_code,
                "modality": row.modality,
                "document": row.document,
                "expectations": row.expectations,
                "failures": failures,
                "probe": None,
                "exception_fingerprint": fingerprint,
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
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing summary.json and its result files",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_batch(
            corpus_dir=args.corpus_dir,
            output_dir=args.output_dir,
            record_only=args.record_only,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
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
