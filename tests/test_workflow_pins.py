"""REL-12: build inputs must be pinned, not floating.

The repo's verifiable-build claim is that every build input is pinned. Actions
are pinned by commit SHA, Python deps by hash-pinned lockfiles — but the
toolchains themselves were resolved at run time (`lts/*`, `stable`, "latest
pip"), so two runs of the same tag could build against different compilers.

This also had a live cost: the one job configured with `node-version: "lts/*"`
(js-syntax) failed a CI run with `manifest.filter is not a function` while
setup-node resolved the LTS alias against GitHub's API during an outage. The
sibling job pinned to an explicit major never hit that path.

Deliberate exception: apt packages stay unversioned. Ubuntu's archive drops old
package versions, so a version-pinned apt install breaks the moment the archive
rotates — worse than the drift it would prevent. Named in the workflow header
instead of silently claimed as pinned.

Pure stdlib (no PyYAML) so this runs in the core-only install job too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _strip_comments(text: str) -> str:
    """Drop comments so prose describing the pins (e.g. the header explaining
    that lts/* is no longer used) cannot trip the checks below — only real
    settings should count."""
    return "\n".join(re.sub(r"#.*$", "", line) for line in text.splitlines())


def _texts():
    return [(p.name, _strip_comments(p.read_text(encoding="utf-8"))) for p in WORKFLOWS]


def test_workflows_exist():
    assert WORKFLOWS, "no workflow files found"


@pytest.mark.parametrize("name,text", _texts(), ids=[p.name for p in WORKFLOWS])
def test_node_version_is_pinned(name, text):
    """`lts/*` makes setup-node resolve an alias against GitHub's API at run
    time — non-deterministic, and the source of a real CI failure."""
    for m in re.finditer(r"node-version:\s*[\"']?([^\"'\s]+)", text):
        assert re.fullmatch(r"\d+(\.\d+)*", m.group(1)), (
            f"{name}: node-version {m.group(1)!r} is not an explicit version"
        )


@pytest.mark.parametrize("name,text", _texts(), ids=[p.name for p in WORKFLOWS])
def test_rust_toolchain_is_pinned(name, text):
    """`toolchain: stable` resolves to whatever rustc is newest that day, so the
    action SHA pin does not actually pin the compiler."""
    for m in re.finditer(r"toolchain:\s*[\"']?([^\"'\s]+)", text):
        assert re.fullmatch(r"\d+\.\d+(\.\d+)?", m.group(1)), (
            f"{name}: rust toolchain {m.group(1)!r} floats; pin an explicit version"
        )


@pytest.mark.parametrize("name,text", _texts(), ids=[p.name for p in WORKFLOWS])
def test_pip_is_pinned(name, text):
    """`pip install --upgrade pip` pulls whatever pip released most recently —
    the tool that then enforces --require-hashes should itself be pinned."""
    assert not re.search(r"pip install\s+--upgrade\s+pip(?![=\w])", text), (
        f"{name}: pip is upgraded to an unpinned latest; use pip==<version>"
    )
