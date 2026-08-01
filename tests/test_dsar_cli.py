"""Tests for the `ai_guard.py dsar locate` CLI verb.

Follows the direct-namespace-call pattern used in tests/test_breach_cli.py
(construct an Args object, call the cmd_* function, inspect capsys/SystemExit)
rather than going through argparse, except for the usage-error-remap tests,
which deliberately go through real `main()` so the exit codes seen by an
actual invocation are pinned.

Synthetic Thai national ids/phone/email are the same fabricated, checksum-valid
values used in tests/test_dsar.py and tests/test_breach_assessment.py, reused
here so the FP detector actually fires on them.
"""

import json
import sys
import types
from pathlib import Path

import pytest

ID_A = "1101700230708"
ID_B = "1101200012345"
PHONE_1 = "0812345678"
EMAIL_1 = "somchai@example.com"


def _args(paths, subject_file, output=None, pdf=None, recursive=False):
    return type(
        "Args",
        (),
        {
            "paths": paths,
            "subject_file": subject_file,
            "output": output,
            "pdf": pdf,
            "recursive": recursive,
        },
    )()


def _subject_file(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "subject.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Happy path / exit codes
# --------------------------------------------------------------------------


def test_dsar_locate_happy_path_prints_thai_summary_and_json_keys(tmp_path, capsys):
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "result.json"

    ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject), output=str(outfile)))

    payload = json.loads(outfile.read_text(encoding="utf-8"))
    for key in (
        "schema",
        "assessed_at",
        "subject",
        "files",
        "matched_files",
        "method",
        "environment",
    ):
        assert key in payload
    assert payload["files"]["matched"] == 1
    assert payload["files"]["assessed"] == 1

    out = capsys.readouterr().out
    assert "ตรวจแล้ว 1/1 ไฟล์" in out
    assert "พบไฟล์ที่ตรงกับผู้ขอข้อมูล 1 ไฟล์" in out
    assert ID_A not in out


def test_dsar_locate_weak_only_match_marked_in_stdout(tmp_path, capsys):
    """F2: a file that matches ONLY on NAME must be marked in the CLI summary,
    not presented identically to an id-backed match."""
    import ai_guard

    subject = _subject_file(tmp_path, ["สมชาย ใจดี"])
    doc = tmp_path / "doc.txt"
    doc.write_text("นาย สมชาย ใจดี เดินทางไปทำงาน", encoding="utf-8")

    ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject)))

    out = capsys.readouterr().out
    assert "ไฟล์ที่ตรงกันเฉพาะชื่อ" in out
    assert "doc.txt" in out


def test_dsar_locate_id_backed_match_not_marked_weak_in_stdout(tmp_path, capsys):
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")

    ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject)))

    out = capsys.readouterr().out
    assert "ไฟล์ที่ตรงกันเฉพาะชื่อ" not in out


def test_dsar_locate_zero_match_exits_0_and_says_so_plainly(tmp_path, capsys):
    """Zero matched files is a valid DSAR outcome, not a failure -- exit stays
    0 and the summary says so in words, not a bare "0"."""
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_B}", encoding="utf-8")

    ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject)))  # must not raise SystemExit

    out = capsys.readouterr().out
    assert "ไม่พบไฟล์ที่ตรงกับผู้ขอข้อมูล" in out
    assert ID_A not in out
    assert ID_B not in out


def test_dsar_locate_partial_failure_exits_2_lists_failed_basenames(tmp_path, capsys):
    """`missing.txt` never being created means `extract()` raises a REAL
    FileNotFoundError, whose message (via `OSError.__str__`'s `repr()`
    formatting) embeds `tmp_path` in a doubled-backslash form as well as the
    plain one -- both are checked, plus `tmp_path.name` (unaffected by the
    doubling), so this test cannot pass vacuously the way a plain
    `str(tmp_path) not in captured.err` check could."""
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    good = tmp_path / "good.txt"
    good.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    missing = tmp_path / "missing.txt"  # never created

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(_args([str(good), str(missing)], str(subject)))
    assert exc.value.code == 2

    captured = capsys.readouterr()
    assert "ตรวจแล้ว 1/2 ไฟล์" in captured.out
    assert "missing.txt" in captured.err
    assert "good.txt" not in captured.err
    assert ID_A not in captured.out
    assert ID_A not in captured.err
    assert str(tmp_path) not in captured.err
    assert str(tmp_path).replace("\\", "\\\\") not in captured.err
    assert tmp_path.name not in captured.err


def test_dsar_locate_empty_input_exits_1(tmp_path, capsys):
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(_args([str(empty_dir)], str(subject)))
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert captured.err  # a clear message, not a silent exit
    assert ID_A not in captured.err


# --------------------------------------------------------------------------
# Bad subject file -- the strictest privacy surface in this suite
# --------------------------------------------------------------------------


def test_dsar_locate_empty_subject_file_exits_1_no_value_echoed(tmp_path, capsys):
    """M1: the raised `NoSubjectIdentifiersError` names the subject-file PATH
    (never a line's content). `ID_A` alone cannot pin the leak this branch had
    -- the subject file here is empty, so `ID_A` was never in memory as a
    value to echo in the first place, and the assertion below could not fail
    even before the fix. The `str(tmp_path)`/doubled-backslash/`tmp_path.name`
    checks are what actually exercise the scrub (same style as the sibling
    missing-subject-file test at the bottom of this section)."""
    import ai_guard

    subject = _subject_file(tmp_path, [])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject)))
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert captured.err
    assert ID_A not in captured.err
    assert ID_A not in captured.out
    assert str(tmp_path) not in captured.err
    assert str(tmp_path).replace("\\", "\\\\") not in captured.err
    assert tmp_path.name not in captured.err


def test_dsar_locate_blank_only_subject_file_exits_1_no_value_echoed(tmp_path, capsys):
    """Same M1 gap as the empty-file test above: blank-only lines never put
    `ID_A` in memory either, so the path assertions are what actually pin the
    scrub."""
    import ai_guard

    subject = _subject_file(tmp_path, ["", "   ", "\t"])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject)))
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert captured.err
    assert ID_A not in captured.err
    assert ID_A not in captured.out
    assert str(tmp_path) not in captured.err
    assert str(tmp_path).replace("\\", "\\\\") not in captured.err
    assert tmp_path.name not in captured.err


def test_dsar_locate_missing_subject_file_exits_1_and_scrubs_the_real_path(tmp_path, capsys):
    """A missing --subject-file raises a REAL FileNotFoundError from
    `Path.read_text()` inside `_read_subject_identifiers` -- not a hand-built
    exception string. CPython's `OSError.__str__` formats its filename via
    `repr()`, which backslash-escapes a Windows path, so the raw message
    embeds this directory in a doubled-backslash form as well as the plain
    one; checking only `str(tmp_path) not in captured.err` (the previous,
    weaker version of this test) can pass vacuously without exercising the
    doubled form at all -- `tmp_path.name` (one path component, unaffected
    by the doubling) and the explicit doubled-backslash spelling are checked
    too. This is the confirmed top-level-failure-line leak the reviewer
    flagged: the CLI's generic exception handler must scrub this path even
    though it never enters `args.paths`."""
    import ai_guard

    subject = tmp_path / "does-not-exist.txt"
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject)))
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert captured.err
    assert ID_A not in captured.err
    assert str(tmp_path) not in captured.err
    assert str(tmp_path).replace("\\", "\\\\") not in captured.err
    assert tmp_path.name not in captured.err


# --------------------------------------------------------------------------
# --pdf happy path / renderer not yet available / half-state discipline
# --------------------------------------------------------------------------


def test_dsar_locate_pdf_flag_writes_pdf_and_json(tmp_path, capsys):
    """Now that pii_redactor/dsar_pdf.py (Task 3) exists, --pdf is a happy
    path: both the PDF and the JSON land on disk and the CLI reports both.
    (Until Task 3 landed, this same scenario exercised the "renderer missing"
    error path -- see test_dsar_locate_pdf_flag_fails_clearly_when_renderer_missing
    below for that failure mode, faked via a monkeypatched absent module.)"""
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "result.json"
    pdf_file = tmp_path / "result.pdf"

    ai_guard.cmd_dsar_locate(
        _args([str(doc)], str(subject), output=str(outfile), pdf=str(pdf_file))
    )

    assert outfile.exists()
    assert pdf_file.read_bytes()[:5] == b"%PDF-"

    captured = capsys.readouterr()
    assert f"Locate result PDF written: {pdf_file}" in captured.out
    assert f"Locate result written: {outfile}" in captured.out
    # The fixture id must not leak into stdout.
    assert ID_A not in captured.out


def test_dsar_locate_pdf_flag_fails_clearly_when_renderer_missing(tmp_path, monkeypatch, capsys):
    import ai_guard

    monkeypatch.setitem(sys.modules, "pii_redactor.dsar_pdf", None)

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "result.json"
    pdf_file = tmp_path / "result.pdf"

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(
            _args([str(doc)], str(subject), output=str(outfile), pdf=str(pdf_file))
        )
    assert exc.value.code == 1
    assert not outfile.exists()
    assert not pdf_file.exists()

    captured = capsys.readouterr()
    assert "not yet available" in captured.err
    assert ID_A not in captured.err


def test_dsar_locate_pdf_write_failure_leaves_no_json_behind(tmp_path, monkeypatch, capsys):
    import ai_guard

    def _boom(payload, path):
        raise OSError("disk full")

    fake_module = types.ModuleType("pii_redactor.dsar_pdf")
    fake_module.render_dsar_pdf = _boom
    monkeypatch.setitem(sys.modules, "pii_redactor.dsar_pdf", fake_module)

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    outfile = tmp_path / "result.json"
    pdf_file = tmp_path / "result.pdf"

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(
            _args([str(doc)], str(subject), output=str(outfile), pdf=str(pdf_file))
        )
    assert exc.value.code == 1
    assert not outfile.exists()
    assert not pdf_file.exists()

    captured = capsys.readouterr()
    assert "cannot write locate result" in captured.err


def test_dsar_locate_json_write_failure_deletes_pdf_already_written(tmp_path, monkeypatch, capsys):
    """Mirror image: the PDF is rendered/written FIRST and succeeds, then the
    JSON write fails (here, -o points into a directory that does not exist).
    The complete PDF this run wrote must not be left behind for a run that
    reports a hard failure."""
    import ai_guard

    def _ok(payload, path):
        Path(path).write_bytes(b"%PDF-fake")

    fake_module = types.ModuleType("pii_redactor.dsar_pdf")
    fake_module.render_dsar_pdf = _ok
    monkeypatch.setitem(sys.modules, "pii_redactor.dsar_pdf", fake_module)

    subject = _subject_file(tmp_path, [ID_A])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    pdf_file = tmp_path / "result.pdf"
    bad_outfile = tmp_path / "no-such-directory" / "result.json"

    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_dsar_locate(
            _args([str(doc)], str(subject), output=str(bad_outfile), pdf=str(pdf_file))
        )
    assert exc.value.code == 1
    assert not bad_outfile.exists()
    assert not pdf_file.exists()

    captured = capsys.readouterr()
    assert "cannot write locate result" in captured.err
    assert "deleted" in captured.err


# --------------------------------------------------------------------------
# Consolidated privacy probe
# --------------------------------------------------------------------------


def test_dsar_locate_subject_values_never_leak_across_stdout_stderr_json(tmp_path, capsys):
    """One consolidated privacy probe across a run that actually matches on
    every identifier type -- the subject values must never appear in stdout,
    stderr, or the written JSON bytes."""
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A, PHONE_1, EMAIL_1])
    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A} โทร {PHONE_1} อีเมล {EMAIL_1}", encoding="utf-8")
    outfile = tmp_path / "result.json"

    ai_guard.cmd_dsar_locate(_args([str(doc)], str(subject), output=str(outfile)))

    captured = capsys.readouterr()
    blob = outfile.read_text(encoding="utf-8")
    for value in (ID_A, PHONE_1, EMAIL_1):
        assert value not in captured.out
        assert value not in captured.err
        assert value not in blob


# --------------------------------------------------------------------------
# Through real argparse / main() -- usage-error exit-1 remap at both levels,
# and a guard that other verbs' exit codes are unaffected.
# --------------------------------------------------------------------------


def test_dsar_locate_missing_subject_file_arg_exits_1_through_real_main(tmp_path, monkeypatch):
    """`dsar locate <path>` with no `--subject-file` is a usage error at the
    INNER parser level -- must exit 1, not argparse's stock 2."""
    import ai_guard

    doc = tmp_path / "doc.txt"
    doc.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ai_guard", "dsar", "locate", str(doc)])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 1


def test_dsar_locate_no_paths_exits_1_through_real_main(tmp_path, monkeypatch):
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    monkeypatch.setattr(sys, "argv", ["ai_guard", "dsar", "locate", "--subject-file", str(subject)])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 1


def test_dsar_alone_with_no_verb_exits_1_through_real_main(monkeypatch):
    """`ai_guard.py dsar` with no sub-subcommand is a usage error at the
    OUTER parser level (dsar_parser's own required-subcommand check fires
    before locate_parser is ever reached) -- must also exit 1."""
    import ai_guard

    monkeypatch.setattr(sys, "argv", ["ai_guard", "dsar"])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 1


def test_dsar_locate_partial_failure_exits_2_through_real_main(tmp_path, monkeypatch):
    import ai_guard

    subject = _subject_file(tmp_path, [ID_A])
    good = tmp_path / "good.txt"
    good.write_text(f"เลขบัตรประชาชน {ID_A}", encoding="utf-8")
    missing = tmp_path / "missing.txt"  # never created

    monkeypatch.setattr(
        sys,
        "argv",
        ["ai_guard", "dsar", "locate", str(good), str(missing), "--subject-file", str(subject)],
    )

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 2


def test_receipt_alone_with_no_verb_still_exits_2_after_dsar_added(monkeypatch):
    """Guard against the dsar-only exit-code remap leaking onto other verbs
    built from the same shared top-level subparsers action."""
    import ai_guard

    monkeypatch.setattr(sys, "argv", ["ai_guard", "receipt"])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 2


def test_breach_alone_with_no_verb_still_exits_1_after_dsar_added(monkeypatch):
    """Breach's own pre-existing remap must be unaffected by adding dsar's."""
    import ai_guard

    monkeypatch.setattr(sys, "argv", ["ai_guard", "breach"])

    with pytest.raises(SystemExit) as exc:
        ai_guard.main()
    assert exc.value.code == 1
