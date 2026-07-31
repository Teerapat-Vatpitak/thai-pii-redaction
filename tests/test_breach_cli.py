"""Tests for the `ai_guard.py breach assess` CLI verb.

Follows the direct-namespace-call pattern used in tests/test_step10_cli.py
(construct an Args object, call the cmd_* function, inspect capsys/SystemExit)
rather than going through argparse.

Synthetic Thai national ids are the same checksum-valid values used in
tests/test_breach_assessment.py (verified against
pii_redactor.detectors.thai_id.is_valid_thai_id), reused here so the FP
detector actually fires the same way.
"""

import json
import sys
import types

import pytest

ID_A = "1101700230708"
ID_B = "1101200012345"


def _args(paths, output=None, pdf=None, recursive=False):
    return type(
        "Args",
        (),
        {"paths": paths, "output": output, "pdf": pdf, "recursive": recursive},
    )()


def test_breach_assess_happy_path_prints_thai_summary(tmp_path, capsys):
    import ai_guard

    (tmp_path / "f1.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    (tmp_path / "f2.txt").write_text(f"เลขบัตรประชาชน {ID_B}", encoding="utf-8")

    ai_guard.cmd_breach_assess(_args([str(tmp_path)]))

    out = capsys.readouterr().out
    assert "ประเมินแล้ว 2/2 ไฟล์" in out
    assert "ประเภทข้อมูลที่พบ" in out
    assert "ประมาณการจำนวนเจ้าของข้อมูล" in out
    assert "ระดับความเสี่ยงสูงสุด" in out
    # Default stdout is counts only -- no fixture value leaks into the summary.
    assert ID_A not in out
    assert ID_B not in out


def test_breach_assess_reports_skipped_non_txt_pdf_files(tmp_path, capsys):
    """A directory holding files outside *.txt/*.pdf must surface them by
    basename in both the JSON and stdout, not drop them silently, and
    assessed + skipped + failed must add up to total."""
    import ai_guard

    (tmp_path / "good.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    (tmp_path / "leak.docx").write_text("unsupported extension", encoding="utf-8")
    (tmp_path / "scan.png").write_text("unsupported extension", encoding="utf-8")
    outfile = tmp_path / "report.json"

    ai_guard.cmd_breach_assess(_args([str(tmp_path)], output=str(outfile)))

    payload = json.loads(outfile.read_text(encoding="utf-8"))
    files = payload["files"]
    skipped = files["skipped"]
    assert skipped["count"] == 2
    assert sorted(skipped["basenames"]) == ["leak.docx", "scan.png"]
    assert files["assessed"] + skipped["count"] + len(files["failed"]) == files["total"]

    out = capsys.readouterr().out
    assert "leak.docx" in out
    assert "scan.png" in out


def test_breach_assess_no_strong_identifiers_reports_distinct_wording(tmp_path, capsys):
    """A corpus with detected NAME entities but no THAI_ID/PASSPORT/PHONE/EMAIL
    must not print a literal 0-0 headline -- that reads as "nobody affected"
    in a legal-evidence document when the tool plainly found named people."""
    import ai_guard

    (tmp_path / "f1.txt").write_text("นาย สมชาย ใจดี พบกับ นาย มานะ ดีใจ ที่ร้านอาหาร", encoding="utf-8")

    ai_guard.cmd_breach_assess(_args([str(tmp_path)]))

    out = capsys.readouterr().out
    assert "0-0 คน" not in out
    assert "ไม่พบตัวระบุแบบเข้ม" in out


def test_breach_assess_partial_failure_exits_2_and_lists_failed_basenames(tmp_path, capsys):
    import ai_guard

    good = tmp_path / "good.txt"
    good.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    missing = tmp_path / "missing.txt"  # never created

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_breach_assess(_args([str(good), str(missing)]))
    assert exc.value.code == 2

    captured = capsys.readouterr()
    assert "ประเมินแล้ว 1/2 ไฟล์" in captured.out
    assert "missing.txt" in captured.err
    # The basename of the file that DID succeed must not show up as a failure.
    assert "good.txt" not in captured.err


def test_breach_assess_empty_input_exits_1(tmp_path, capsys):
    import ai_guard

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_breach_assess(_args([str(empty_dir)]))
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert captured.err  # a clear message, not a silent exit


def test_breach_assess_output_file_has_expected_top_level_keys(tmp_path, capsys):
    import ai_guard

    (tmp_path / "f1.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "report.json"

    ai_guard.cmd_breach_assess(_args([str(tmp_path)], output=str(outfile)))

    assert outfile.exists()
    payload = json.loads(outfile.read_text(encoding="utf-8"))
    for key in (
        "schema",
        "assessed_at",
        "files",
        "types",
        "subjects",
        "name_weak_identifier",
        "section26",
        "risk",
        "environment",
        "file_rows",
    ):
        assert key in payload
    assert payload["types"]["THAI_ID"] == {"total": 1, "distinct": 1}

    out = capsys.readouterr().out
    assert f"Assessment written: {outfile}" in out


def test_breach_assess_pdf_flag_writes_pdf_and_json(tmp_path, capsys):
    """Now that pii_redactor/breach_pdf.py (Task 3) exists, --pdf is a happy
    path: both the PDF and the JSON land on disk and the CLI reports both.
    (Until Task 3 landed, this same scenario exercised the "renderer missing"
    error path -- see test_breach_assess_pdf_flag_fails_clearly_when_missing
    below for that failure mode, faked via a monkeypatched absent module.)"""
    import ai_guard

    (tmp_path / "f1.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "report.json"
    pdf_file = tmp_path / "report.pdf"

    ai_guard.cmd_breach_assess(_args([str(tmp_path)], output=str(outfile), pdf=str(pdf_file)))

    assert outfile.exists()
    assert pdf_file.read_bytes()[:5] == b"%PDF-"

    captured = capsys.readouterr()
    assert f"Assessment PDF written: {pdf_file}" in captured.out
    assert f"Assessment written: {outfile}" in captured.out
    # The fixture id must not leak into stdout.
    assert ID_A not in captured.out


def test_breach_assess_pdf_flag_fails_clearly_when_missing(tmp_path, monkeypatch, capsys):
    """If pii_redactor.breach_pdf cannot be imported at all (e.g. a broken
    install), --pdf must fail with a clear message rather than an ImportError
    traceback, and must not leave a JSON file behind from the same run (both
    destinations are checked before anything is written)."""
    import ai_guard

    monkeypatch.setitem(sys.modules, "pii_redactor.breach_pdf", None)

    (tmp_path / "f1.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "report.json"
    pdf_file = tmp_path / "report.pdf"

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_breach_assess(_args([str(tmp_path)], output=str(outfile), pdf=str(pdf_file)))
    assert exc.value.code == 1
    assert not outfile.exists()
    assert not pdf_file.exists()

    captured = capsys.readouterr()
    assert "not yet available" in captured.err


def test_breach_assess_pdf_write_failure_leaves_no_json_behind(tmp_path, monkeypatch, capsys):
    """--pdf is rendered/written before -o's JSON, so a failed PDF write must
    not leave the JSON behind despite the run exiting 1."""
    import ai_guard

    (tmp_path / "f1.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "report.json"
    pdf_file = tmp_path / "report.pdf"

    def _boom(payload, path):
        raise OSError("disk full")

    fake_module = types.ModuleType("pii_redactor.breach_pdf")
    fake_module.render_breach_pdf = _boom
    monkeypatch.setitem(sys.modules, "pii_redactor.breach_pdf", fake_module)

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_breach_assess(_args([str(tmp_path)], output=str(outfile), pdf=str(pdf_file)))
    assert exc.value.code == 1
    assert not outfile.exists()
    assert not pdf_file.exists()

    captured = capsys.readouterr()
    assert "cannot write assessment" in captured.err


def test_breach_assess_json_write_failure_deletes_the_pdf_already_written(tmp_path, capsys):
    """The mirror image of the test above: the PDF is rendered/written FIRST
    and succeeds, then the JSON write fails (here, -o points into a directory
    that does not exist). The run must not leave a complete assessment PDF on
    disk for a run that reports a hard failure and never mentions it -- the
    PDF this run wrote is deleted, and the error message says so."""
    import ai_guard

    (tmp_path / "f1.txt").write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    pdf_file = tmp_path / "report.pdf"
    bad_outfile = tmp_path / "no-such-directory" / "report.json"

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_breach_assess(
            _args([str(tmp_path)], output=str(bad_outfile), pdf=str(pdf_file))
        )
    assert exc.value.code == 1
    assert not bad_outfile.exists()
    assert not pdf_file.exists()

    captured = capsys.readouterr()
    assert "cannot write assessment" in captured.err
    assert "deleted" in captured.err


def test_breach_assess_top_level_failure_scrubs_input_paths(tmp_path, monkeypatch, capsys):
    """A failure raised inside assess_breach itself (e.g. a directory scan
    blowing up with a PermissionError) must not leak the caller's own input
    path into the generic failure line -- the same path-scrub discipline
    breach.py already applies to per-file FailedFile.reason."""
    import ai_guard

    bad_dir = tmp_path / "case-folder"
    bad_dir.mkdir()

    def _boom(paths, *, recursive=False):
        raise PermissionError(f"[Errno 13] Permission denied: '{paths[0]}'")

    monkeypatch.setattr("pii_redactor.breach.assess_breach", _boom)

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_breach_assess(_args([str(bad_dir)]))
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert str(bad_dir) not in captured.err
    assert "case-folder" in captured.err


# --------------------------------------------------------------------------
# Through real argparse / main() -- not the direct-namespace-call shortcut
# used above -- so the usage-error vs partial-failure exit codes are pinned
# against what a user actually invoking `ai_guard.py breach assess ...` sees.
# --------------------------------------------------------------------------


def test_breach_assess_no_paths_exits_1_through_real_main(monkeypatch, capsys):
    """A usage error (no paths given) must exit 1, not argparse's own default
    of 2 -- 2 is reserved for partial failure so a scripted caller can tell
    the two apart."""
    import ai_guard

    monkeypatch.setattr(sys, "argv", ["ai_guard", "breach", "assess"])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 1


def test_breach_assess_partial_failure_exits_2_through_real_main(tmp_path, monkeypatch, capsys):
    import ai_guard

    good = tmp_path / "good.txt"
    good.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    missing = tmp_path / "missing.txt"  # never created

    monkeypatch.setattr(sys, "argv", ["ai_guard", "breach", "assess", str(good), str(missing)])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 2


def test_breach_alone_with_no_verb_exits_1_through_real_main(monkeypatch, capsys):
    """`ai_guard.py breach` with no sub-subcommand is also a usage error on
    this verb -- it must exit 1 too, not argparse's stock 2 for a missing
    required subparser. This is the OUTER level (breach_parser itself, whose
    required-subcommand check fires before assess_parser is ever reached),
    distinct from the `breach assess`-with-no-paths case above (the INNER
    level)."""
    import ai_guard

    monkeypatch.setattr(sys, "argv", ["ai_guard", "breach"])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 1


def test_receipt_alone_with_no_verb_still_exits_2_through_real_main(monkeypatch, capsys):
    """Guard against the breach-only exit-code remap leaking onto other
    verbs: `receipt` (built from the same top-level subparsers action as
    `breach`) must keep argparse's stock exit 2 for this exact usage error."""
    import ai_guard

    monkeypatch.setattr(sys, "argv", ["ai_guard", "receipt"])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 2
