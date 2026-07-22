"""Release metadata must agree before an immutable tag builds artifacts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_release_readiness.py"

_spec = importlib.util.spec_from_file_location("check_release_readiness", SCRIPT)
release_readiness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_readiness)


def test_current_repo_is_release_metadata_consistent():
    assert release_readiness.check(ROOT) == []


def test_changelog_requires_unreleased_and_current_dated_section(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.2.3] - 2026-07-22\n",
        encoding="utf-8",
    )
    problems = release_readiness.check_changelog(tmp_path, "1.2.3")
    assert any("Unreleased" in problem for problem in problems)


def test_changelog_rejects_a_version_missing_from_release_history(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.2.2] - 2026-07-21\n",
        encoding="utf-8",
    )
    problems = release_readiness.check_changelog(tmp_path, "1.2.3")
    assert any("1.2.3" in problem for problem in problems)


def test_changelog_accepts_valid_release_metadata(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-07-22\n",
        encoding="utf-8",
    )
    assert release_readiness.check_changelog(tmp_path, "1.2.3") == []


def test_tag_gate_requires_unreleased_to_be_empty(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- not released yet\n\n"
        "## [1.2.3] - 2026-07-22\n",
        encoding="utf-8",
    )
    problems = release_readiness.check_changelog(
        tmp_path,
        "1.2.3",
        require_empty_unreleased=True,
    )
    assert any("Unreleased is not empty" in problem for problem in problems)


def test_tag_gate_accepts_a_fresh_empty_unreleased_section(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-07-22\n",
        encoding="utf-8",
    )
    assert (
        release_readiness.check_changelog(
            tmp_path,
            "1.2.3",
            require_empty_unreleased=True,
        )
        == []
    )


def test_changelog_rejects_invalid_calendar_date(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.2.3] - 2026-02-30\n",
        encoding="utf-8",
    )
    problems = release_readiness.check_changelog(tmp_path, "1.2.3")
    assert any("calendar date" in problem for problem in problems)
