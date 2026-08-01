"""Tests for pii_redactor/dsar.py -- the DSAR (PDPA มาตรา 30) locate core.

All PII values below are fabricated. Thai national ids are computed to pass
the real mod-11 checksum (see `is_valid_thai_id`); the same values used in
tests/test_breach_assessment.py are reused here so the FP detector actually
fires on them.
"""

import json
import re
from pathlib import Path

import pytest

from pii_redactor.dsar import (
    NoFilesAssessedError,
    NoSubjectIdentifiersError,
    _classify_subject_line,
    locate_subject,
)

# Fabricated, checksum-valid Thai national ids (verified against
# pii_redactor.detectors.thai_id.is_valid_thai_id) -- same values
# tests/test_breach_assessment.py uses.
ID_A = "1101700230708"
ID_B = "1101200012345"

PHONE_1 = "0812345678"
EMAIL_1 = "somchai@example.com"
PASSPORT_1 = "AA1234567"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _subject_file(tmp_path: Path, lines: list[str]) -> Path:
    return _write(tmp_path, "subject.txt", "\n".join(lines))


# --------------------------------------------------------------------------
# Subject-file line classification
# --------------------------------------------------------------------------


def test_classify_subject_line_covers_all_five_shapes():
    assert _classify_subject_line(ID_A) == "THAI_ID"
    assert _classify_subject_line("1-1017-00230-70-8") == "THAI_ID"
    assert _classify_subject_line(PASSPORT_1) == "PASSPORT"
    assert _classify_subject_line(EMAIL_1) == "EMAIL"
    assert _classify_subject_line("Somchai@Example.COM") == "EMAIL"
    assert _classify_subject_line(PHONE_1) == "PHONE"
    assert _classify_subject_line("+66 81 234 5678") == "PHONE"
    assert _classify_subject_line("สมชาย ใจดี") == "NAME"
    assert _classify_subject_line("   ") is None
    assert _classify_subject_line("") is None


def test_locate_subject_reports_one_of_each_identifier_type(tmp_path):
    subject = _subject_file(tmp_path, [ID_A, PASSPORT_1, EMAIL_1, PHONE_1, "สมชาย ใจดี"])
    _write(
        tmp_path,
        "doc.txt",
        f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_A} หนังสือเดินทางเลขที่ {PASSPORT_1} "
        f"อีเมล {EMAIL_1} โทร {PHONE_1}",
    )

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert result.subject_counts == {
        "EMAIL": 1,
        "NAME": 1,
        "PASSPORT": 1,
        "PHONE": 1,
        "THAI_ID": 1,
    }
    assert len(result.matched_files) == 1


def test_empty_subject_file_raises(tmp_path):
    subject = _subject_file(tmp_path, [])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_A}")

    with pytest.raises(NoSubjectIdentifiersError):
        locate_subject([str(tmp_path / "doc.txt")], str(subject))


def test_subject_file_with_only_blank_lines_raises(tmp_path):
    subject = _subject_file(tmp_path, ["", "   ", "\t"])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_A}")

    with pytest.raises(NoSubjectIdentifiersError):
        locate_subject([str(tmp_path / "doc.txt")], str(subject))


# --------------------------------------------------------------------------
# Matching matrix
# --------------------------------------------------------------------------


def test_hyphenated_subject_id_matches_plain_document_id(tmp_path):
    subject = _subject_file(tmp_path, ["1-1017-00230-70-8"])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_A}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"THAI_ID": 1}


def test_intl_phone_subject_matches_domestic_document_phone(tmp_path):
    subject = _subject_file(tmp_path, [PHONE_1])
    _write(tmp_path, "doc.txt", "โทร +66 81 234 5678")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"PHONE": 1}


def test_email_case_insensitive_match(tmp_path):
    subject = _subject_file(tmp_path, ["Somchai@Example.COM"])
    _write(tmp_path, "doc.txt", f"อีเมล {EMAIL_1}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"EMAIL": 1}


def test_name_without_title_matches_document_name_with_title(tmp_path):
    subject = _subject_file(tmp_path, ["สมชาย ใจดี"])
    _write(tmp_path, "doc.txt", "นาย สมชาย ใจดี เดินทางไปทำงาน")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"NAME": 1}


def test_different_person_does_not_match(tmp_path):
    subject = _subject_file(tmp_path, [ID_A])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_B}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert result.matched_files == []
    assert result.files_assessed == 1


def test_match_ignores_detectors_label_bank_account_on_a_phone(tmp_path):
    """F1 repro (reviewer's exact scenario): the subject's phone number,
    detected in a bank-account context (nearest-cue-wins tags it
    BANK_ACCOUNT, not PHONE -- see fp_detector.py), must still match. Matching
    is on canonical VALUE under the SUBJECT identifier's own type rules, never
    gated on the detector's own label for the entity."""
    subject = _subject_file(tmp_path, [PHONE_1])
    _write(tmp_path, "doc.txt", f"เลขที่บัญชี {PHONE_1} ธนาคารกสิกร สำหรับโอนเงินคืน")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"PHONE": 1}


def test_bare_66_prefixed_digit_run_without_plus_does_not_match_phone(tmp_path):
    """Re-review repro: F1's original fix over-matched. `canonical_value`'s
    PHONE international-fold ("66"-prefixed digit run -> domestic "0..." form)
    fires on bare digits alone, with no requirement that the source text ever
    carried a "+" country-code marker. A bare 11-digit value that merely
    STARTS with 66 (e.g. an unrelated bank account) would then fold to the
    exact same domestic string as the subject's phone purely by digit
    coincidence -- a false positive a legal-evidence tool must not produce.
    Must NOT match even though the raw digits, canonicalized under PHONE
    rules blindly, land on the subject's own canonical phone value."""
    subject = _subject_file(tmp_path, [PHONE_1])
    bare_66 = "66" + PHONE_1[1:]  # "66812345678" -- no "+", not the subject's phone
    _write(tmp_path, "doc.txt", f"เลขที่บัญชี {bare_66} ธนาคารกสิกร สำหรับโอนเงินคืน")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert result.matched_files == []


def test_plus_66_marker_still_matches_subject_phone(tmp_path):
    """The legitimate spelling this guard must not break: an explicit "+66"
    marker in the entity's own raw text still folds to the subject's
    domestic phone and matches, regardless of surrounding label/context."""
    subject = _subject_file(tmp_path, [PHONE_1])
    _write(tmp_path, "doc.txt", "โทร +66 81 234 5678 ติดต่อกลับ")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"PHONE": 1}


def test_different_bank_account_does_not_match_subject_phone(tmp_path):
    """Negative control for the fix above: label-independent matching must
    not turn into value-independent matching. A different 10-digit bank
    account, detected in the same BANK_ACCOUNT context, is not the subject's
    phone number and must not match."""
    subject = _subject_file(tmp_path, [PHONE_1])
    other_account = "1234567890"
    assert other_account != PHONE_1
    _write(tmp_path, "doc.txt", f"เลขที่บัญชี {other_account} ธนาคารกสิกร สำหรับโอนเงินคืน")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert result.matched_files == []


def test_match_ignores_detectors_label_organization_on_a_name(tmp_path, monkeypatch):
    """F1 repro (reviewer's second scenario): a name the detector labels
    ORGANIZATION (e.g. folded into a company-name phrase -- CLAUDE.md
    documents this as a real NER behavior) must still match on value. The
    detector call is monkeypatched here to a fixed single-entity result so
    this test pins the matching logic itself rather than depending on the
    CRF's non-deterministic behavior on any particular sentence."""
    import pii_redactor.dsar as dsar_module
    from pii_redactor.models import Entity

    subject = _subject_file(tmp_path, ["สมชาย ใจดี"])
    doc = _write(tmp_path, "doc.txt", "บริษัท สมชาย ใจดี จำกัด")
    fake_entity = Entity(
        entity_id="fixture-1",
        redact_type="TB",
        data_type="ORGANIZATION",
        span=(0, len(doc.read_text(encoding="utf-8"))),
        score=0.9,
        original_text="สมชาย ใจดี",
    )
    monkeypatch.setattr(dsar_module, "detect_all", lambda text: [fake_entity])

    result = locate_subject([str(doc)], str(subject))

    assert len(result.matched_files) == 1
    assert result.matched_files[0].matched_identifier_counts == {"NAME": 1}


def test_multi_file_corpus_reports_matched_subset_only(tmp_path):
    # Subject file lives outside the scanned corpus directory -- the same
    # separation `ai_guard.py dsar locate` enforces by taking `--subject-file`
    # and document `paths` as distinct arguments, so a directory scan never
    # picks up the subject file itself as one of the documents to search.
    subject = _subject_file(tmp_path, [ID_A])
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    _write(docs_dir, "match.txt", f"เลขบัตรประชาชน {ID_A}")
    _write(docs_dir, "other1.txt", f"เลขบัตรประชาชน {ID_B}")
    _write(docs_dir, "other2.txt", "นาย มานะ ดีใจ ไปเที่ยวทะเล")

    result = locate_subject([str(docs_dir)], str(subject))

    assert result.files_assessed == 3
    assert len(result.matched_files) == 1
    assert result.matched_files[0].basename == "match.txt"


# --------------------------------------------------------------------------
# Third-party flag
# --------------------------------------------------------------------------


def test_third_party_possible_set_when_extra_pii_present(tmp_path):
    subject = _subject_file(tmp_path, [ID_A])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_A} โทร {PHONE_1}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    row = result.matched_files[0]
    assert row.matched_identifier_counts == {"THAI_ID": 1}
    assert row.type_counts["PHONE"] == 1
    assert row.third_party_possible is True


def test_third_party_possible_false_when_only_subject_pii_present(tmp_path):
    # "เลขประจำตัวประชาชน" (unlike "เลขบัตรประชาชน") does not itself get
    # mistagged as a NAME entity by the CRF NER, so this document contains
    # exactly one entity -- the subject's own THAI_ID -- and nothing else.
    subject = _subject_file(tmp_path, [ID_A])
    _write(tmp_path, "doc.txt", f"เลขประจำตัวประชาชน {ID_A}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    row = result.matched_files[0]
    assert row.third_party_possible is False


def test_third_party_note_states_the_flag_is_heuristic(tmp_path):
    """M6: the flag also fires on the subject's own data under an unlisted
    type, and on detector false positives -- the fixed note must say so
    rather than let a warn-only flag read as a conclusion."""
    subject = _subject_file(tmp_path, [ID_A])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_A}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))
    payload = result.to_json_dict()

    assert "heuristic" in payload["method"]["third_party"]
    assert "false positive" in payload["method"]["third_party"]


def test_name_weak_match_note_present_in_json(tmp_path):
    """F2: the fixed weak-identifier note is a distinct entry in `method`,
    present regardless of whether any file actually matched on NAME only."""
    subject = _subject_file(tmp_path, [ID_A])
    _write(tmp_path, "doc.txt", f"เลขบัตรประชาชน {ID_A}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))
    payload = result.to_json_dict()

    assert "name_weak_match" in payload["method"]
    assert "weak identifier" in payload["method"]["name_weak_match"]


# --------------------------------------------------------------------------
# weak_only flag (F2): a NAME-only match is weaker evidence than an
# id/passport/phone/email-backed match and must be flagged, not presented the
# same way.
# --------------------------------------------------------------------------


def test_weak_only_true_when_only_name_matches(tmp_path):
    subject = _subject_file(tmp_path, ["สมชาย ใจดี"])
    _write(tmp_path, "doc.txt", "นาย สมชาย ใจดี เดินทางไปทำงาน")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    row = result.matched_files[0]
    assert row.matched_identifier_counts == {"NAME": 1}
    assert row.weak_only is True


def test_weak_only_false_when_id_backed_match_present(tmp_path):
    """Same document also carries the subject's name -- weak_only must stay
    False because a checksum-backed THAI_ID also matched, not just NAME."""
    subject = _subject_file(tmp_path, [ID_A, "สมชาย ใจดี"])
    _write(tmp_path, "doc.txt", f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_A}")

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))

    assert len(result.matched_files) == 1
    row = result.matched_files[0]
    assert row.matched_identifier_counts == {"NAME": 1, "THAI_ID": 1}
    assert row.weak_only is False


# --------------------------------------------------------------------------
# Failed / skipped file discipline (mirrors breach.py's own tests)
# --------------------------------------------------------------------------


def test_missing_file_recorded_as_failed_and_run_continues(tmp_path):
    """`missing.txt` is never created, so `extract()` raises a REAL
    FileNotFoundError from `Path.read_bytes()` -- not a hand-built exception
    string. CPython's `OSError.__str__` formats its filename via `repr()`,
    which backslash-escapes a Windows path, so the raw message embeds
    `tmp_path` in BOTH the plain single-backslash form (which
    `str(tmp_path) not in failed.reason` alone would catch) and a doubled-
    backslash form that a naive scrub misses entirely -- checking
    `tmp_path.name` (one path component, unaffected by the doubling) and the
    explicit doubled-backslash spelling both probe the form a plain
    `str(tmp_path)` check cannot."""
    subject = _subject_file(tmp_path, [ID_A])
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing = tmp_path / "missing.txt"  # never created

    result = locate_subject([str(good), str(missing)], str(subject))

    assert len(result.matched_files) == 1
    assert len(result.files_failed) == 1
    failed = result.files_failed[0]
    assert failed.basename == "missing.txt"
    assert "FileNotFoundError" in failed.reason
    assert str(tmp_path) not in failed.reason
    assert str(tmp_path).replace("\\", "\\\\") not in failed.reason
    assert tmp_path.name not in failed.reason


def test_skipped_non_txt_pdf_files_are_recorded(tmp_path):
    subject = _subject_file(tmp_path, [ID_A])
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    _write(docs_dir, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    _write(docs_dir, "leak.docx", "unsupported extension")

    result = locate_subject([str(docs_dir)], str(subject))

    assert result.files_skipped == ["leak.docx"]
    assert result.files_total == result.files_assessed + len(result.files_skipped)


def test_no_files_found_raises_no_files_assessed_error(tmp_path):
    subject = _subject_file(tmp_path, [ID_A])
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(NoFilesAssessedError):
        locate_subject([str(empty_dir)], str(subject))


# --------------------------------------------------------------------------
# Privacy: subject identifier values never appear in JSON or error messages
# --------------------------------------------------------------------------


def test_json_output_carries_no_subject_identifier_value(tmp_path):
    subject = _subject_file(tmp_path, [ID_A, PHONE_1, EMAIL_1, "สมชาย ใจดี"])
    _write(
        tmp_path,
        "doc.txt",
        f"นาย สมชาย ใจดี เลขบัตรประชาชน {ID_A} โทร {PHONE_1} อีเมล {EMAIL_1}",
    )

    result = locate_subject([str(tmp_path / "doc.txt")], str(subject))
    payload = json.dumps(result.to_json_dict(), ensure_ascii=False)

    # Positive: the run actually matched, so absence below is not vacuous.
    assert len(result.matched_files) == 1

    for value in (ID_A, PHONE_1, EMAIL_1, "สมชาย", "ใจดี"):
        assert value not in payload
    assert re.search(r"\d{13}", payload) is None


def test_error_path_does_not_leak_subject_identifier_in_memory(tmp_path):
    """Probe: subject identifiers are successfully parsed into memory, then
    every document path fails, raising NoFilesAssessedError -- the raised
    message must not carry any subject value that was alive at the time."""
    subject = _subject_file(tmp_path, [ID_A, PHONE_1, EMAIL_1])
    missing = tmp_path / "missing.txt"  # never created

    with pytest.raises(NoFilesAssessedError) as exc_info:
        locate_subject([str(missing)], str(subject))

    message = str(exc_info.value)
    for value in (ID_A, PHONE_1, EMAIL_1):
        assert value not in message


def test_failed_file_reason_does_not_leak_subject_identifier(tmp_path):
    subject = _subject_file(tmp_path, [ID_A, PHONE_1, EMAIL_1])
    good = _write(tmp_path, "good.txt", f"เลขบัตรประชาชน {ID_A}")
    missing = tmp_path / "missing.txt"  # never created

    result = locate_subject([str(good), str(missing)], str(subject))
    payload = json.dumps(result.to_json_dict(), ensure_ascii=False)

    for value in (ID_A, PHONE_1, EMAIL_1):
        assert value not in payload
