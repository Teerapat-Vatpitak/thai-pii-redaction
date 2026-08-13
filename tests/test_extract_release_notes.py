"""Release bodies come from the exact dated CHANGELOG section."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "extract_release_notes.py"

_spec = importlib.util.spec_from_file_location("extract_release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)


def test_extracts_only_the_requested_dated_release_section(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [3.0.0] - 2026-08-14\n\n"
        "### Added\n\n- Native package.\n\n## [2.5.0] - 2026-08-01\n\n- Old.\n",
        encoding="utf-8",
    )

    assert release_notes.extract(changelog, "3.0.0") == (
        "## AI Guard 3.0.0 (2026-08-14)\n\n### Added\n\n- Native package."
    )


def test_missing_release_section_fails_closed(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing dated changelog section"):
        release_notes.extract(changelog, "3.0.0")
