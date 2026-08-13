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
def test_external_actions_are_pinned_to_commit_shas(name, text):
    for match in re.finditer(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", text, re.MULTILINE):
        action = match.group(1).strip("\"'")
        if action.startswith("./"):
            continue
        assert "@" in action, f"{name}: action has no revision: {action}"
        revision = action.rsplit("@", 1)[1]
        assert re.fullmatch(r"[0-9a-fA-F]{40}", revision), (
            f"{name}: action is not pinned to a 40-character commit SHA: {action}"
        )


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
    assert "CONTRACT_HEADER: CONTRACT_VERSION" in docker_job
    assert "validate_health" in docker_job
    assert "validate_sanitize" in docker_job
    assert "validate_reidentify" in docker_job
    assert "validate_analyze" in docker_job
    assert "validate_guard" in docker_job
    assert "out['session_id']" in docker_job


def test_windows_packaged_smoke_runs_office_v2_composition():
    """CI builds Office and runs the packaged-backend v2 preflight."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    packaged_job = ci.split("  windows-exe-smoke:", 1)[1]

    assert 'node-version: "22"' in packaged_job
    assert "working-directory: office-addin" in packaged_job
    assert "npm ci --ignore-scripts --no-audit --no-fund" in packaged_job
    assert "npm run build" in packaged_job
    assert "python scripts/office_v2_composition.py" in packaged_job
    assert "--skip-sidecar-build" in packaged_job
    assert "--skip-office-build" in packaged_job


def test_native_runtime_matrix_stages_build_only_tauri_resources():
    """Every platform compile must satisfy Tauri resource discovery."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    rust_job = ci.split("  rust:", 1)[1].split("  native-broker-runtime:", 1)[0]
    runtime_job = ci.split("  native-broker-runtime:", 1)[1].split("  js-syntax:", 1)[0]

    for job in (rust_job, runtime_job):
        assert "cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml" in job
        for manifest in (
            "native-components-v1.nsis.json",
            "native-components-v1.macos.json",
            "native-components-v1.deb.json",
            "native-components-v1.appimage.json",
        ):
            assert manifest in job
        assert "invalid manifest" in job


def test_windows_packaged_smoke_uses_exact_installed_nsis_candidate():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    packaged_job = ci.split("  windows-exe-smoke:", 1)[1]

    placeholder_command = "python scripts/prepare_desktop_native_package.py --build-placeholders"
    assert packaged_job.count(placeholder_command) == 1
    placeholder_index = packaged_job.index(placeholder_command)
    assert packaged_job.index("python scripts/build_native_broker.py") < placeholder_index
    assert placeholder_index < packaged_job.index("npm run tauri -- build --bundles nsis")
    assert "npm run tauri -- build --bundles nsis" in packaged_job
    assert '"createUpdaterArtifacts":false' in packaged_job
    assert 'Get-ChildItem -LiteralPath $bundleRoot -Filter "*-setup.exe"' in packaged_job
    assert '$installRoot = Join-Path $env:LOCALAPPDATA "AI Guard"' in packaged_job
    assert '$installLocationKey = "HKCU:\\Software\\Teerapat Vatpitak\\AI Guard"' in packaged_job
    assert "remembered Desktop install root would redirect the default-path install" in packaged_job
    assert "InstallLocation.Trim('\"')" in packaged_job
    assert (
        "if ($registeredRoot -ne $installRoot -or $rememberedRoot -ne $installRoot)" in packaged_job
    )
    assert "function Invoke-ExactInstaller" in packaged_job
    assert packaged_job.count("Invoke-ExactInstaller") == 5
    assert (
        'Start-Process -FilePath $installer -ArgumentList @("/S") -Wait -PassThru' in packaged_job
    )
    assert "function Invoke-ExactUninstaller" in packaged_job
    assert packaged_job.count("Invoke-ExactUninstaller") == 3
    assert "NSIS uninstall left the product registration" in packaged_job
    assert "NSIS installer left the cross-session package lock" in packaged_job
    assert "NSIS uninstaller left the cross-session package lock" in packaged_job
    assert "function Assert-PackageLockEnforced" in packaged_job
    assert "[System.IO.FileShare]::None" in packaged_job
    assert "concurrent NSIS package transaction was not rejected" in packaged_job
    assert "distinct-root NSIS package transaction was not rejected" in packaged_job
    assert "blocked distinct-root NSIS transaction created package state" in packaged_job
    assert "package-lock-contention.json" in packaged_job
    assert "[System.IO.Directory]::Delete($customLockProbeRoot, $false)" in packaged_job
    assert "blocked package transactions changed default product registration" in packaged_job
    assert "interrupted-package-retry" in packaged_job
    assert "interrupted-uninstall-retry" in packaged_job
    assert "repair cleared an installer-owned barrier" in packaged_job
    assert "if ($process.ExitCode -ne 0)" in packaged_job
    assert "function Invoke-Smoke" in packaged_job
    assert 'scripts/smoke_desktop_native_package.py "$installRoot" --repetitions 2' in packaged_job
    assert "artifacts/desktop-native-nsis/AI-Guard-windows-x64-setup.exe" in packaged_job
    for lifecycle in ("install", "repair", "upgrade", "reinstall"):
        assert f'Invoke-Smoke "{lifecycle}"' in packaged_job
    assert '"$artifactRoot/$name-smoke-evidence.json"' in packaged_job
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in packaged_job
    assert "--no-bundle" not in packaged_job


def test_compose_keeps_api_key_optional_for_local_and_worker_modes():
    """The adapter enforces values at boot; interpolation must not block worker.

    A required-variable interpolation on the HTTP service is evaluated even
    for ``--profile worker`` and would prevent that independent deployment
    mode from starting. CI's hosted smoke supplies both values explicitly.
    """
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "AIGUARD_API_KEY: ${AIGUARD_API_KEY:-}" in compose
    assert "AIGUARD_PROVIDERS: ${AIGUARD_PROVIDERS:-}" in compose
    assert "AIGUARD_API_KEY:?" not in compose
    assert "AIGUARD_PROVIDERS:?" not in compose
