"""Tests for pii_redactor/breach.py — the breach-assessment aggregation core.

All PII values below are fabricated. Thai national ids are computed to pass
the real mod-11 checksum (see `is_valid_thai_id`) so the FP detector actually
fires on them, the same way the existing gold fixtures do.
"""

import json
import re
from pathlib import Path

import pytest

from pii_redactor.breach import (
    NoFilesAssessedError,
    _canonical_value,
    _max_risk_grade,
    assess_breach,
)

# Fabricated, checksum-valid Thai national ids (verified against
# pii_redactor.detectors.thai_id.is_valid_thai_id).
ID_A = "1101700230708"
ID_B = "1101200012345"
ID_C = "3101999123453"
ID_D = "1502888777669"
ID_E = "2203777665546"

PHONE_1 = "0812345678"
PHONE_2 = "0898765432"

EMAIL_1 = "somchai@example.com"

# Thai-format passport ([A-Z]{2}\d{7}, no cue required -- see fp_detector.py).
PASSPORT_1 = "AA1234567"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Estimation: known overlaps
# --------------------------------------------------------------------------


def test_same_id_in_three_files_gives_min_and_max_one(tmp_path):
    for i in range(3):
        _write(tmp_path, f"f{i}.txt", f"เลขบัตรประชาชน {ID_A}")

    result = assess_breach([str(tmp_path)])

    assert result.files_assessed == 3
    assert result.type_counts["THAI_ID"] == {"total": 3, "distinct": 1}
    assert result.subjects_min == 1
    assert result.subjects_max == 1


def test_id_and_phone_for_one_person_gives_range_one_to_two(tmp_path):
    _write(
        tmp_path,
        "f1.txt",
        f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_B} โทร {PHONE_1}",
    )

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["THAI_ID"] == {"total": 1, "distinct": 1}
    assert result.type_counts["PHONE"] == {"total": 1, "distinct": 1}
    assert result.subjects_min == 1
    assert result.subjects_max == 2
    # NAME is a weak identifier: detected and counted in type_counts, but
    # reported separately (name_distinct) and never folded into the
    # strong-identifier subject bounds above.
    assert result.type_counts["NAME"]["distinct"] == 1
    assert result.name_distinct == 1


def test_distinct_ids_and_phones_sum_correctly(tmp_path):
    for i, national_id in enumerate((ID_C, ID_D, ID_E)):
        _write(tmp_path, f"id{i}.txt", f"เลขบัตรประชาชน {national_id}")
    _write(tmp_path, "phone0.txt", f"โทร {PHONE_1}")
    _write(tmp_path, "phone1.txt", f"โทร {PHONE_2}")

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["THAI_ID"]["distinct"] == 3
    assert result.type_counts["PHONE"]["distinct"] == 2
    # min = max(3, 2); max = 3 + 2 -- summing two DIFFERENT strong types.
    assert result.subjects_min == 3
    assert result.subjects_max == 5


def test_passport_feeds_distinct_counts_and_subject_bounds(tmp_path):
    """PASSPORT is one of the four _STRONG_TYPES that feed subjects_min/max,
    but had zero coverage across the breach test suite before this test."""
    _write(tmp_path, "f1.txt", f"หนังสือเดินทางเลขที่ {PASSPORT_1}")

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["PASSPORT"] == {"total": 1, "distinct": 1}
    assert result.subjects_min == 1
    assert result.subjects_max == 1


# --------------------------------------------------------------------------
# Normalization dedup
# --------------------------------------------------------------------------


def test_spaced_and_hyphenated_id_forms_collapse(tmp_path):
    _write(tmp_path, "plain.txt", f"เลขบัตรประชาชน {ID_A}")
    _write(tmp_path, "hyphenated.txt", "เลขบัตรประชาชน 1-1017-00230-70-8")

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["THAI_ID"] == {"total": 2, "distinct": 1}


def test_email_case_collapses(tmp_path):
    _write(tmp_path, "lower.txt", f"อีเมล {EMAIL_1}")
    _write(tmp_path, "mixed.txt", "อีเมล Somchai@Example.COM")

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["EMAIL"] == {"total": 2, "distinct": 1}


def test_mobile_plus66_form_collapses_with_domestic(tmp_path):
    _write(tmp_path, "domestic.txt", f"โทร {PHONE_1}")
    _write(tmp_path, "intl.txt", "โทร +66 81 234 5678")

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["PHONE"] == {"total": 2, "distinct": 1}


def test_landline_plus66_form_collapses_with_domestic(tmp_path):
    _write(tmp_path, "domestic.txt", "โทร 02-123-4567")
    _write(tmp_path, "intl.txt", "โทร +66 2 123 4567")

    result = assess_breach([str(tmp_path)])

    assert result.type_counts["PHONE"] == {"total": 2, "distinct": 1}


# --------------------------------------------------------------------------
# Failure rows
# --------------------------------------------------------------------------


def test_unreadable_file_is_recorded_and_assessment_continues(tmp_path):
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing = tmp_path / "missing.txt"  # never created

    result = assess_breach([str(good), str(missing)])

    assert result.files_assessed == 1
    assert result.files_total == 2
    assert len(result.files_failed) == 1
    failed = result.files_failed[0]
    assert failed.basename == "missing.txt"
    assert "FileNotFoundError" in failed.reason
    # Never file content -- there is none to leak here, but the reason string
    # must not mention the id from the file that DID succeed either.
    assert ID_A not in failed.reason


def test_failed_file_reason_never_leaks_the_input_path(tmp_path):
    """FileNotFoundError's own message embeds the FULL path it was given
    ("No such file or directory: '<full path>'"). The spec limits a
    failed-file row to basename + a short reason, so the parent directory
    (itself potentially a sensitive name -- a ward, a case folder, ...) must
    not survive into the reason, in the dataclass or in the JSON bytes."""
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing = tmp_path / "missing.txt"  # never created

    result = assess_breach([str(good), str(missing)])

    failed = result.files_failed[0]
    assert failed.basename == "missing.txt"
    assert "missing.txt" in failed.reason
    assert str(tmp_path) not in failed.reason

    payload = json.dumps(result.to_json_dict(), ensure_ascii=False)
    assert "missing.txt" in payload
    assert str(tmp_path) not in payload


def test_directory_scan_is_non_recursive_by_default(tmp_path):
    _write(tmp_path, "top.txt", f"เลขบัตรประชาชน {ID_A}")
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    _write(nested_dir, "deep.txt", f"เลขบัตรประชาชน {ID_B}")

    non_recursive = assess_breach([str(tmp_path)])
    assert non_recursive.files_assessed == 1

    recursive = assess_breach([str(tmp_path)], recursive=True)
    assert recursive.files_assessed == 2


def test_skipped_non_txt_pdf_files_are_recorded_and_total_includes_them(tmp_path):
    """A directory scan silently dropping unsupported-extension files used to
    make files_total describe only what survived the *.txt/*.pdf filter. Both
    the skip list and files_total (which now counts everything the scan
    found, not just what it chose to look at) must reflect the two skipped
    files here."""
    _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    _write(tmp_path, "leak.docx", "not really a docx, just an unsupported extension")
    _write(tmp_path, "scan.png", "not really a png either")

    result = assess_breach([str(tmp_path)])

    assert result.files_assessed == 1
    assert sorted(result.files_skipped) == ["leak.docx", "scan.png"]
    assert result.files_total == result.files_assessed + len(result.files_skipped)
    assert result.files_total == 3

    payload = result.to_json_dict()
    assert payload["files"]["skipped"] == {
        "count": 2,
        "basenames": ["leak.docx", "scan.png"],
    }


# --------------------------------------------------------------------------
# Zero-success error
# --------------------------------------------------------------------------


def test_all_files_missing_raises_clear_error(tmp_path):
    missing = tmp_path / "nope.txt"

    with pytest.raises(NoFilesAssessedError):
        assess_breach([str(missing)])


def test_empty_directory_raises_clear_error(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(NoFilesAssessedError):
        assess_breach([str(empty_dir)])


# --------------------------------------------------------------------------
# Privacy: no value ever appears in the JSON output
# --------------------------------------------------------------------------


def test_json_output_carries_no_pii_value(tmp_path):
    _write(
        tmp_path,
        "sensitive.txt",
        f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_A} โทร {PHONE_1} อีเมล {EMAIL_1} "
        "เป็นโรคเบาหวานและเข้ารับการรักษาต่อเนื่อง",
    )

    result = assess_breach([str(tmp_path)])
    payload = json.dumps(result.to_json_dict(), ensure_ascii=False)

    # Positive: every fixture value was actually detected and counted, so the
    # absence checks below cannot pass simply because detection found nothing.
    assert result.type_counts["THAI_ID"]["total"] == 1
    assert result.type_counts["PHONE"]["total"] == 1
    assert result.type_counts["EMAIL"]["total"] == 1
    assert result.type_counts["NAME"]["total"] == 1
    assert "HEALTH" in result.section26_counts

    # Absence: none of those detected values, or any 13-digit run, survive
    # into the JSON -- only counts, type/category names, and version strings.
    for fixture_value in (ID_A, PHONE_1, EMAIL_1, "สมชาย", "ใจดี"):
        assert fixture_value not in payload
    assert re.search(r"\d{13}", payload) is None


# --------------------------------------------------------------------------
# Shape / sanity of the rest of the assessment
# --------------------------------------------------------------------------


def test_file_row_and_risk_summary_shape(tmp_path):
    _write(tmp_path, "plain.txt", f"เลขบัตรประชาชน {ID_A}")

    result = assess_breach([str(tmp_path)])

    assert len(result.file_rows) == 1
    row = result.file_rows[0]
    assert row.basename == "plain.txt"
    assert row.source_type == "text"
    assert row.human_review is False
    assert row.risk_grade in ("A", "B", "C", "D", "F")
    assert result.risk_max_grade in result.risk_distribution
    assert sum(result.risk_distribution.values()) == result.files_assessed
    assert result.environment["product_version"]
    assert result.assessed_at


# --------------------------------------------------------------------------
# Zero-strong-identifier headline: 0-0 must not read as "nobody affected"
# --------------------------------------------------------------------------


def test_names_only_corpus_flags_no_strong_identifiers(tmp_path):
    """No THAI_ID/PASSPORT/PHONE/EMAIL anywhere in the corpus -- subjects_min
    and subjects_max are both 0 by construction, but that must be
    distinguishable from "nobody was affected": the tool plainly found named
    people, it just has no strong identifier to bound a headcount by."""
    _write(tmp_path, "f1.txt", "นาย สมชาย ใจดี พบกับ นาย มานะ ดีใจ ที่ร้านอาหาร")

    result = assess_breach([str(tmp_path)])

    assert result.subjects_min == 0
    assert result.subjects_max == 0
    assert result.no_strong_identifiers is True
    assert result.name_distinct >= 1

    payload = result.to_json_dict()
    assert payload["subjects"]["no_strong_identifiers"] is True


# --------------------------------------------------------------------------
# Private helpers, exercised directly (both had zero standalone coverage)
# --------------------------------------------------------------------------


def test_max_risk_grade_picks_the_worst_grade_not_the_first():
    """Every existing breach test assesses files that all grade A, so a
    min/max inversion in _max_risk_grade would pass the whole suite green."""
    assert _max_risk_grade({"A": 2, "D": 1, "B": 3}) == "D"
    assert _max_risk_grade({"A": 1, "F": 1}) == "F"


def test_canonical_value_generic_fallback_folds_whitespace_and_case():
    """No test asserted a distinct count for a type outside the five
    specialized branches, so this fold could regress to `return value` with
    the suite green."""
    assert _canonical_value("ID_NUMBER", " 12 345 678 ") == "12 345 678"
