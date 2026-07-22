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


def test_docker_base_image_is_pinned_to_a_multi_platform_digest():
    """The hosted artifact must not rebuild from a moving base-image tag.

    Keep the human-readable tag for provenance, but pin the OCI index digest;
    unlike an architecture manifest, an index still supports native builds on
    both amd64 and arm64.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert from_lines == [
        "FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91"
    ]


def test_docker_smoke_covers_authenticated_declared_contract():
    """CI must boot the real image and call every endpoint we promise."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    docker_job = ci.split("  docker-smoke:", 1)[1].split("  windows-exe-smoke:", 1)[0]

    for path in ("/api/health", "/api/sanitize", "/api/reidentify", "/api/analyze", "/api/guard"):
        assert path in docker_job
    assert "AIGUARD_API_KEY=" in docker_job
    assert "X-AIGuard-Key" in docker_job
    assert "out['session_id']" in docker_job


def test_compose_keeps_api_key_optional_for_local_and_worker_modes():
    """Hosted docs require the key, but Compose also serves local/worker use.

    A required-variable interpolation on the HTTP service is evaluated even
    for ``--profile worker`` and would prevent that independent deployment
    mode from starting. CI's hosted smoke supplies the key explicitly.
    """
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "AIGUARD_API_KEY: ${AIGUARD_API_KEY:-}" in compose
    assert "AIGUARD_API_KEY:?" not in compose
