"""REL-3: mutable draft bytes never inherit current-run provenance by name.

The gate requires the exact closed filename set, compares every Desktop byte to
the current workflow run's manifest, and compares canonical updater metadata
before hashing or attestation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SCRIPT = ROOT / "scripts" / "check_release_assets.py"

_spec = importlib.util.spec_from_file_location("check_release_assets", SCRIPT)
check_release_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_release_assets)


def _run(
    assets_dir: Path,
    version: str,
    *,
    build_manifest: Path | None = None,
    expected_latest: Path | None = None,
) -> subprocess.CompletedProcess:
    command = [PY, str(SCRIPT), "--dir", str(assets_dir), "--expect-version", version]
    if build_manifest is not None:
        command.extend(("--build-manifest", str(build_manifest)))
    if expected_latest is not None:
        command.extend(("--expected-latest", str(expected_latest)))
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
    )


def _touch(d: Path, *names: str) -> None:
    for n in names:
        (d / n).write_bytes(b"x")


def _complete_assets(version: str) -> tuple[str, ...]:
    return tuple(sorted(check_release_assets.required_assets(version)))


def _write_build_manifest(assets_dir: Path, version: str = "3.0.0") -> Path:
    artifacts = []
    for name in sorted(check_release_assets.required_build_assets(version)):
        value = (assets_dir / name).read_bytes()
        artifacts.append(
            {
                "name": name,
                "size": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
                "source_sha": "a" * 40,
            }
        )
    path = assets_dir.parent / "release-build-manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema": "aiguard-release-build/v1",
                "version": version,
                "source_sha": "a" * 40,
                "source_tree": "b" * 40,
                "run_id": "123",
                "run_attempt": 1,
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_sums(assets_dir: Path, version: str) -> None:
    lines = []
    for name in sorted(check_release_assets.required_assets(version)):
        lines.append(f"{hashlib.sha256((assets_dir / name).read_bytes()).hexdigest()}  {name}")
    (assets_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")


def test_accepts_assets_all_on_the_expected_version(tmp_path):
    _touch(tmp_path, *_complete_assets("2.3.0"))
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 0, result.stdout + result.stderr


def test_rejects_a_stale_asset_from_another_version(tmp_path):
    """The documented failure: a re-run over a draft still holding the previous
    run's (different-version) assets would attest them as this release."""
    _touch(
        tmp_path,
        *_complete_assets("2.3.0"),
        "AI.Guard_2.2.0_x64-setup.exe",
    )
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1
    assert "2.2.0" in (result.stdout + result.stderr)


def test_rejects_empty_asset_dir(tmp_path):
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1


def test_rejects_when_no_asset_carries_the_expected_version(tmp_path):
    """If nothing on the release is named for this version, the download step
    resolved the wrong release — do not hash/attest it."""
    _touch(tmp_path, "SHA256SUMS", "latest.json")
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1


def test_ignores_unversioned_sidecar_files(tmp_path):
    """A complete SHA256SUMS is the only optional unversioned sidecar."""
    _touch(tmp_path, *_complete_assets("2.3.0"), "AI.Guard_2.3.0_x64-setup.exe.sig")
    _write_sums(tmp_path, "2.3.0")
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 0, result.stdout + result.stderr


def test_download_dir_does_not_collide_with_a_tracked_path():
    """REL-3 regression: the checksums job checks out the repo (to read VERSION
    and this script), so its asset download dir must not be a path the repo
    already tracks. `assets/` IS tracked (logos), and `mkdir assets` under the
    Actions default `bash -e` shell would abort the job — no SHA256SUMS, no
    attestation, on every release."""
    # Deliberately no PyYAML: this guard must also run in the core-only install
    # job (requirements.txt has no yaml), so it scans the raw workflow text.
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    git = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if git.returncode != 0:
        pytest.skip("git not available to list tracked files")
    tracked_top_level = {p.split("/")[0] for p in git.stdout.splitlines() if "/" in p}
    mkdirs = re.findall(r"^\s*mkdir(?:\s+-\S+)*\s+(\S+)", text, re.MULTILINE)
    assert mkdirs, "expected the job to create a download directory"
    for d in mkdirs:
        assert d.strip('"') not in tracked_top_level, (
            f"download dir {d!r} collides with tracked directory {d!r}; "
            "checkout would make mkdir fail and kill the job"
        )


def test_unversioned_asset_is_rejected_unless_allowlisted(tmp_path):
    """REL-3: an asset with no version in its name (a foreign upload to the
    draft) must not silently ride along into SHA256SUMS + attestation."""
    _touch(tmp_path, *_complete_assets("2.3.0"), "payload.zip")
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1
    assert "payload.zip" in (result.stdout + result.stderr)


def test_same_version_unexpected_asset_is_rejected(tmp_path):
    """A same-version upload must not acquire first-party provenance merely
    because its filename happens to carry the expected version."""
    _touch(tmp_path, *_complete_assets("3.0.0"), "payload-3.0.0.zip")

    result = _run(tmp_path, "3.0.0")

    assert result.returncode == 1
    assert "payload-3.0.0.zip" in (result.stdout + result.stderr)


def test_release_asset_hardlink_is_rejected(tmp_path):
    _touch(tmp_path, *_complete_assets("3.0.0"))
    target = tmp_path / "AI.Guard_3.0.0_x64-setup.exe"
    outside = tmp_path.parent / "outside-hardlink"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.link(outside, target)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")

    result = _run(tmp_path, "3.0.0")

    assert result.returncode == 1
    assert "regular top-level file" in (result.stdout + result.stderr)


def test_required_asset_bytes_must_match_the_current_run_manifest(tmp_path):
    _touch(tmp_path, *_complete_assets("3.0.0"))
    expected_latest = tmp_path.parent / "expected-latest.json"
    expected_latest.write_bytes((tmp_path / "latest.json").read_bytes())
    manifest = _write_build_manifest(tmp_path)
    substituted = tmp_path / "AI.Guard_3.0.0_x64-setup.exe"
    substituted.write_bytes(b"same-name bytes from another run")

    result = _run(
        tmp_path,
        "3.0.0",
        build_manifest=manifest,
        expected_latest=expected_latest,
    )

    assert result.returncode == 1
    assert "x64-setup.exe" in (result.stdout + result.stderr)
    assert "current workflow run" in (result.stdout + result.stderr)


def test_latest_json_must_match_the_locally_generated_current_run_file(tmp_path):
    _touch(tmp_path, *_complete_assets("3.0.0"))
    manifest = _write_build_manifest(tmp_path)
    expected_latest = tmp_path.parent / "expected-latest.json"
    expected_latest.write_bytes(b"expected-current-run-latest")

    result = _run(
        tmp_path,
        "3.0.0",
        build_manifest=manifest,
        expected_latest=expected_latest,
    )

    assert result.returncode == 1
    assert "latest.json" in (result.stdout + result.stderr)


def test_version_tokens_helper_extracts_semver_only():
    f = check_release_assets.version_tokens
    assert f("AI.Guard_2.3.0_x64-setup.exe") == {"2.3.0"}
    assert f("ai-guard_10.20.30_amd64.AppImage") == {"10.20.30"}
    # x64 / aarch64 / en-US must not read as versions
    assert f("AI.Guard_2.3.0_x64_en-US.msi") == {"2.3.0"}
    assert f("SHA256SUMS") == set()


def test_rejects_a_partial_cross_platform_release(tmp_path):
    assets = set(_complete_assets("2.3.0"))
    assets.remove("AI.Guard_2.3.0_amd64.AppImage")
    _touch(tmp_path, *assets)
    result = _run(tmp_path, "2.3.0")
    assert result.returncode == 1
    assert "AppImage" in (result.stdout + result.stderr)


@pytest.mark.parametrize(
    "signature",
    (
        "AI.Guard_2.3.0_x64-setup.exe.sig",
        "AI.Guard_2.3.0_aarch64.app.tar.gz.sig",
        "AI.Guard_2.3.0_amd64.deb.sig",
        "AI.Guard_2.3.0_amd64.AppImage.sig",
    ),
)
def test_rejects_a_release_missing_any_required_updater_signature(tmp_path, signature):
    assets = set(_complete_assets("2.3.0"))
    assets.remove(signature)
    _touch(tmp_path, *assets)

    result = _run(tmp_path, "2.3.0")

    assert result.returncode == 1
    assert signature in (result.stdout + result.stderr)


def test_tag_workflow_attests_only_redownloaded_current_run_closed_set():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    tag_job = workflow.split("  checksums-and-attest:", 1)[1]

    assert "aiguard-release-build-*-${{ github.sha }}-${{ github.run_id }}" in tag_job
    assert "scripts/create_release_build_manifest.py" in tag_job
    assert "gh api --paginate --slurp" in tag_job
    assert '"repos/$GITHUB_REPOSITORY/releases?per_page=100"' in tag_job
    assert "scripts/resolve_release_draft.py" in tag_job
    assert "releases/tags/$TAG" not in tag_job
    assert "scripts/create_latest_json.py" in tag_job
    assert tag_job.count("--build-manifest release-build-manifest.json") >= 3
    assert tag_job.count("--expected-latest generated-release-metadata/latest.json") == 2
    assert "gh release download" not in tag_job
    assert "head -1" not in tag_job
    assert "subject-path: final-release-assets/*" in tag_job
    assert tag_job.index("Redownload and reverify the final downloadable set") < tag_job.index(
        "Attest build provenance for every asset"
    )
