"""The tag release manifest binds the Desktop bytes produced by this run."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "create_release_build_manifest.py"

_spec = importlib.util.spec_from_file_location("release_build_manifest", SCRIPT)
release_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_build)

SOURCE_SHA = "a" * 40
SOURCE_TREE = "b" * 40


def _complete_build(root: Path, version: str = "3.0.0") -> dict[str, bytes]:
    values = {}
    for index, name in enumerate(release_build.required_build_artifacts(version), start=1):
        value = f"current-run-{index}".encode()
        path = root / f"platform-{index}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        values[name] = value
    return values


def test_manifest_is_closed_deterministic_and_binds_run_identity(tmp_path):
    values = _complete_build(tmp_path)
    output = tmp_path.parent / "manifest.json"

    release_build.create_manifest(
        tmp_path,
        version="3.0.0",
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        run_id="987654",
        run_attempt=2,
        output=output,
    )

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["schema"] == "aiguard-release-build/v1"
    assert document["source_sha"] == SOURCE_SHA
    assert document["source_tree"] == SOURCE_TREE
    assert document["run_id"] == "987654"
    assert document["run_attempt"] == 2
    assert [item["name"] for item in document["artifacts"]] == sorted(values)
    for item in document["artifacts"]:
        value = values[item["name"]]
        assert item["size"] == len(value)
        assert item["sha256"] == hashlib.sha256(value).hexdigest()


@pytest.mark.parametrize("extra", ("payload-3.0.0.zip", "latest.json", "SHA256SUMS"))
def test_manifest_rejects_every_non_build_file(tmp_path, extra):
    _complete_build(tmp_path)
    (tmp_path / extra).write_bytes(b"unexpected")

    with pytest.raises(ValueError, match="unexpected build artifacts"):
        release_build.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id="1",
            run_attempt=1,
            output=tmp_path.parent / "manifest.json",
        )


def test_manifest_rejects_missing_or_duplicate_build_bytes(tmp_path):
    _complete_build(tmp_path)
    name = next(iter(release_build.required_build_artifacts("3.0.0")))
    original = next(tmp_path.rglob(name))
    original.unlink()
    with pytest.raises(ValueError, match="missing build artifacts"):
        release_build.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id="1",
            run_attempt=1,
            output=tmp_path.parent / "manifest.json",
        )

    _complete_build(tmp_path)
    duplicate = tmp_path / "duplicate" / name
    duplicate.parent.mkdir()
    duplicate.write_bytes(b"duplicate")
    with pytest.raises(ValueError, match="duplicate build artifact"):
        release_build.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id="1",
            run_attempt=1,
            output=tmp_path.parent / "manifest.json",
        )


def test_manifest_rejects_a_hardlinked_build_artifact(tmp_path):
    _complete_build(tmp_path)
    name = next(iter(release_build.required_build_artifacts("3.0.0")))
    target = next(tmp_path.rglob(name))
    outside = tmp_path.parent / "outside-hardlink"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        os.link(outside, target)
    except OSError as error:
        pytest.skip(f"hard links unavailable: {error}")

    with pytest.raises(ValueError, match="must not be a symlink"):
        release_build.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id="1",
            run_attempt=1,
            output=tmp_path.parent / "manifest.json",
        )
