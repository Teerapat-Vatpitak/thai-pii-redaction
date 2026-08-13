"""Raw Tauri artifacts are staged under their final GitHub Release names."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scripts.create_release_candidate_manifest import required_artifacts

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "stage_release_candidate_assets.py"

_spec = importlib.util.spec_from_file_location("scripts.stage_release_candidate_assets", SCRIPT)
stage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stage)


def _raw_name(published_name: str, metadata: dict[str, object]) -> str:
    if metadata["os"] == "macos" and metadata["kind"] == "updater-archive":
        return "AI Guard.app.tar.gz"
    if metadata["os"] == "macos" and metadata["kind"] == "updater-signature":
        return "AI Guard.app.tar.gz.sig"
    return published_name.replace("AI.Guard_", "AI Guard_", 1)


def _platform_files(root: Path, platform: str) -> dict[str, bytes]:
    values = {}
    for index, (published_name, metadata) in enumerate(
        required_artifacts("3.0.0").items(), start=1
    ):
        if metadata["os"] != platform:
            continue
        value = f"raw-tauri-artifact-{index}".encode()
        path = root / f"bundle-{index}" / _raw_name(published_name, metadata)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        values[published_name] = value
    return values


@pytest.mark.parametrize("platform", ("windows", "macos", "linux"))
def test_stage_renames_without_changing_bytes(tmp_path, platform):
    source = tmp_path / "source"
    expected = _platform_files(source, platform)
    output = tmp_path / "staged"

    staged = stage.stage_assets(
        source,
        output=output,
        version="3.0.0",
        platform=platform,
    )

    assert [path.name for path in staged] == sorted(expected)
    assert {path.name: path.read_bytes() for path in staged} == expected


def test_stage_rejects_missing_duplicate_empty_and_existing_output(tmp_path):
    source = tmp_path / "source"
    expected = _platform_files(source, "windows")
    published_name = next(iter(expected))
    metadata = required_artifacts("3.0.0")[published_name]
    raw_name = _raw_name(published_name, metadata)
    raw = next(source.rglob(raw_name))

    raw.unlink()
    with pytest.raises(ValueError, match="missing raw Tauri artifact"):
        stage.stage_assets(
            source,
            output=tmp_path / "missing",
            version="3.0.0",
            platform="windows",
        )

    raw.write_bytes(b"candidate")
    duplicate = source / "duplicate" / raw_name
    duplicate.parent.mkdir()
    duplicate.write_bytes(b"candidate")
    with pytest.raises(ValueError, match="duplicate raw Tauri artifact"):
        stage.stage_assets(
            source,
            output=tmp_path / "duplicate-output",
            version="3.0.0",
            platform="windows",
        )

    duplicate.unlink()
    raw.write_bytes(b"")
    with pytest.raises(ValueError, match="raw Tauri artifact is empty"):
        stage.stage_assets(
            source,
            output=tmp_path / "empty",
            version="3.0.0",
            platform="windows",
        )

    raw.write_bytes(b"candidate")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="output directory already exists"):
        stage.stage_assets(
            source,
            output=existing,
            version="3.0.0",
            platform="windows",
        )
