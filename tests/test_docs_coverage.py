"""Guard the three-document split.

`CODEMAP.md` is the code map, `ROADMAP.md` is the order of work, and
`docs/project-status.md` is the evidence ledger. Each answers exactly one
question, and each states so at the top.

They drifted before. `office-addin/` grew into the largest storefront in the
tree — 42 tracked files, ~13.9k lines, more than twice the size of the
`pii_redactor/` core it wraps — and the code map did not mention it once. A
reader who opened only the file that is loaded automatically would have believed
the project had three storefronts when it had five.

These tests make that specific failure loud. They check that documents point at
each other and that no lane can be added without appearing in the map and the
ledger. They deliberately do NOT check prose quality or freshness; a test cannot
tell whether a sentence is still true, only whether a subject is missing
entirely.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CODE_MAP = ROOT / "CODEMAP.md"
ROADMAP = ROOT / "ROADMAP.md"
STATUS = ROOT / "docs" / "project-status.md"
ACCEPTANCE = ROOT / "docs" / "acceptance" / "README.md"
PLATFORM = ROOT / "docs" / "platform" / "ai-for-thai.md"

# Tracked top-level directories that carry no code a contributor navigates to,
# so requiring them in the code map would add noise instead of removing it.
# Anything holding source, tests, or a build path belongs in the map instead.
NOT_IN_CODE_MAP = {
    ".agents": "agent skill definitions, not project code",
    ".codex": "Codex agent configs, not project code",
    "assets": "binary images for branding and docs",
    "licenses": "third-party license texts required by NOTICE",
}


def _tracked_top_level_dirs() -> set[str]:
    """Top-level directories that git actually tracks.

    Uses git rather than a directory walk so untracked scratch folders, build
    output, and ignored caches never fail this test.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.split("/", 1)[0] for line in result.stdout.splitlines() if "/" in line}


def _storefront_names() -> list[str]:
    """First column of the storefront table in the code map.

    A trailing parenthetical is a qualifier, not part of the name, so
    "Desktop app (Windows)" is looked up as "Desktop app".
    """
    text = CODE_MAP.read_text(encoding="utf-8")
    heading = re.search(r"^## Architecture.*$", text, re.MULTILINE)
    assert heading, "CODEMAP.md lost its Architecture section heading"

    names: list[str] = []
    started = False
    for line in text[heading.end() :].splitlines():
        if not line.startswith("|"):
            # Stop at the end of the FIRST table. The Architecture section also
            # contains a Key Modules table further down, and swallowing it would
            # turn every module path into a phantom storefront.
            if started:
                break
            continue
        started = True
        cell = line.split("|")[1].strip()
        if not cell or cell.startswith("-") or cell == "Storefront":
            continue
        names.append(re.sub(r"\s*\(.*\)\s*$", "", cell).strip())
    return names


@pytest.mark.skipif(
    not (ROOT / ".git").exists(), reason="needs a git checkout to list tracked files"
)
def test_every_tracked_top_level_dir_is_in_the_code_map():
    """A new lane cannot land without the code map learning about it."""
    text = CODE_MAP.read_text(encoding="utf-8")
    missing = sorted(
        d for d in _tracked_top_level_dirs() if d not in NOT_IN_CODE_MAP and d not in text
    )
    assert not missing, (
        f"CODEMAP.md never mentions {missing}. Either describe the directory there, "
        f"or add it to NOT_IN_CODE_MAP in this file with the reason it needs no entry."
    )


@pytest.mark.skipif(
    not (ROOT / ".git").exists(), reason="needs a git checkout to list tracked files"
)
def test_code_map_exemptions_still_exist():
    """Stop the allowlist from silently outliving the directories it excuses."""
    tracked = _tracked_top_level_dirs()
    stale = sorted(d for d in NOT_IN_CODE_MAP if d not in tracked)
    assert not stale, f"NOT_IN_CODE_MAP lists directories git no longer tracks: {stale}"


def test_every_storefront_has_a_status_row():
    """Whatever the code map calls a storefront, the ledger must account for it."""
    status = STATUS.read_text(encoding="utf-8").lower()
    names = _storefront_names()
    assert len(names) >= 5, f"storefront table looks truncated, parsed only {names}"

    missing = sorted(n for n in names if n.lower() not in status)
    assert not missing, (
        f"docs/project-status.md has no entry for {missing}. Every storefront in the "
        f"code map needs a status row, or the two documents disagree about what ships."
    )


def test_the_three_documents_point_at_each_other():
    """Each document must name the other two, so any entry point leads to all three."""
    expected = {
        CODE_MAP: ("ROADMAP.md", "project-status.md"),
        ROADMAP: ("CODEMAP.md", "project-status.md"),
        STATUS: ("CODEMAP.md", "ROADMAP.md"),
    }
    for path, references in expected.items():
        text = path.read_text(encoding="utf-8")
        for reference in references:
            assert reference in text, (
                f"{path.name} does not point at {reference}; a reader landing there "
                f"cannot find the document that answers the other question."
            )


def _flat(text: str) -> str:
    """Collapse whitespace so a phrase assertion survives a markdown reflow.

    These documents are hard-wrapped, so a phrase that reads as one sentence
    often carries a newline in the middle of it. Matching raw text builds a
    guard that fails when someone rewraps a paragraph without changing a single
    word — which is exactly what happened to the worker-provisional assertion
    below.
    """
    return " ".join(text.split())


def test_office_acceptance_separates_local_and_packaged_evidence():
    """Local XML evidence must not silently close the release transport gate."""
    text = _flat(ACCEPTANCE.read_text(encoding="utf-8"))
    assert "### Local host-functional acceptance" in text
    assert "### Packaged unified-manifest acceptance" in text
    assert "- [ ] Install the exact promoted package" in text
    assert "Local XML runs, schema validation, and acquisition metadata do not close" in text


def test_platform_truth_selects_http_shape_and_keeps_worker_provisional():
    """The guide fixes the HTTP shape without mandating one framework."""
    text = _flat(PLATFORM.read_text(encoding="utf-8"))
    assert "HTTP frontend/API containers" in text
    assert "guide permits any Docker-capable framework" in text
    assert 'root_path="/api"' in text
    assert "## Official HTTP adapter boundary" in text
    assert "not the official delivery path" in text
