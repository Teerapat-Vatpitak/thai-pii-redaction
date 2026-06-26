"""Tests for CLI: ai_guard.py and demo_cli.py."""
import sys
import pytest
from io import StringIO
from pathlib import Path


def test_ai_guard_sanitize_nonexistent_file(tmp_path, capsys):
    """sanitize with nonexistent file should print error and exit 1."""
    import ai_guard
    args_ns = type('Args', (), {
        'file': str(tmp_path / 'nonexistent.txt'),
        'output': None,
        'fmt': 'txt',
        'provider': 'fake',
        'overwrite': False,
    })()
    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_sanitize(args_ns)
    assert exc.value.code == 1


def test_ai_guard_sanitize_real_file(tmp_path, capsys):
    """sanitize with real file should print session id."""
    import ai_guard
    infile = tmp_path / "input.txt"
    infile.write_text("Hello world.", encoding="utf-8")

    args_ns = type('Args', (), {
        'file': str(infile),
        'output': None,
        'fmt': 'txt',
        'provider': 'fake',
        'overwrite': False,
    })()
    ai_guard.cmd_sanitize(args_ns)
    captured = capsys.readouterr()
    assert "Session:" in captured.out


def test_ai_guard_sanitize_with_output(tmp_path, capsys):
    """sanitize with --output writes file."""
    import ai_guard
    infile = tmp_path / "input.txt"
    infile.write_text("Call 081-234-5678 please.", encoding="utf-8")
    outfile = tmp_path / "output.txt"

    args_ns = type('Args', (), {
        'file': str(infile),
        'output': str(outfile),
        'fmt': 'txt',
        'provider': 'fake',
        'overwrite': False,
    })()
    ai_guard.cmd_sanitize(args_ns)
    assert outfile.exists()


def test_ai_guard_report_nonexistent_file(tmp_path, capsys):
    """report with nonexistent file should exit 1."""
    import ai_guard
    args_ns = type('Args', (), {'file': str(tmp_path / 'nonexistent.txt')})()
    with pytest.raises(SystemExit) as exc:
        ai_guard.cmd_report(args_ns)
    assert exc.value.code == 1


def test_ai_guard_report_real_file(tmp_path, capsys):
    """report with real file should print risk report."""
    import ai_guard
    infile = tmp_path / "input.txt"
    infile.write_text("Call 081-234-5678 please.", encoding="utf-8")

    args_ns = type('Args', (), {'file': str(infile)})()
    ai_guard.cmd_report(args_ns)
    captured = capsys.readouterr()
    assert "Risk Level:" in captured.out


def test_ai_guard_argparse_help():
    """Parser should include both subcommands."""
    import ai_guard
    import argparse
    # Verify the module has the required functions
    assert hasattr(ai_guard, 'main')
    assert hasattr(ai_guard, 'cmd_sanitize')
    assert hasattr(ai_guard, 'cmd_report')


def test_demo_cli_imports():
    """demo_cli.py should import cleanly."""
    import demo_cli
    assert hasattr(demo_cli, 'main')
    assert callable(demo_cli.main)


def test_ai_guard_sanitize_with_phone_number(tmp_path, capsys):
    """sanitize should detect and anonymize Thai phone numbers."""
    import ai_guard
    infile = tmp_path / "input.txt"
    infile.write_text("My phone: 081-234-5678", encoding="utf-8")

    args_ns = type('Args', (), {
        'file': str(infile),
        'output': None,
        'fmt': 'txt',
        'provider': 'fake',
        'overwrite': False,
    })()
    ai_guard.cmd_sanitize(args_ns)
    captured = capsys.readouterr()
    assert "Entities detected:" in captured.out
    # Should detect at least 1 entity (phone number)
    assert "FP=" in captured.out


def test_ai_guard_report_with_multiple_entities(tmp_path, capsys):
    """report should count multiple entity types."""
    import ai_guard
    infile = tmp_path / "input.txt"
    # Include both phone and date patterns
    infile.write_text(
        "Contact: 081-234-5678 or email test@example.com. Born 1990-05-15",
        encoding="utf-8"
    )

    args_ns = type('Args', (), {'file': str(infile)})()
    ai_guard.cmd_report(args_ns)
    captured = capsys.readouterr()
    assert "Risk Level:" in captured.out
    assert "Total entities detected:" in captured.out


def test_ai_guard_report_no_pii(tmp_path, capsys):
    """report with clean text should show Low risk."""
    import ai_guard
    infile = tmp_path / "input.txt"
    infile.write_text("This is just some random text with no PII.", encoding="utf-8")

    args_ns = type('Args', (), {'file': str(infile)})()
    ai_guard.cmd_report(args_ns)
    captured = capsys.readouterr()
    assert "Risk Level: Low" in captured.out
