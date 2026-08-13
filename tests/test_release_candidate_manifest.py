"""The pre-tag release candidate manifest binds every intended artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "create_release_candidate_manifest.py"

_spec = importlib.util.spec_from_file_location("release_candidate_manifest", SCRIPT)
candidate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(candidate)

SOURCE_SHA = "a" * 40
SOURCE_TREE = "b" * 40
RUN_ID = "12345"
RUN_ATTEMPT = 2


def _complete_candidate(root: Path, version: str = "3.0.0") -> dict[str, bytes]:
    values = {}
    for index, name in enumerate(candidate.required_artifacts(version), start=1):
        value = f"candidate-artifact-{index}".encode()
        path = root / f"platform-{index}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        values[name] = value
    return values


def test_manifest_is_deterministic_complete_and_binds_source(tmp_path):
    values = _complete_candidate(tmp_path)
    first = tmp_path.parent / "first.json"
    second = tmp_path.parent / "second.json"

    candidate.create_manifest(
        tmp_path,
        version="3.0.0",
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        output=first,
    )
    candidate.create_manifest(
        tmp_path,
        version="3.0.0",
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        run_id=RUN_ID,
        run_attempt=RUN_ATTEMPT,
        output=second,
    )

    assert first.read_bytes() == second.read_bytes()
    manifest = json.loads(first.read_text(encoding="utf-8"))
    assert manifest["schema"] == "aiguard-release-candidate/v1"
    assert manifest["version"] == "3.0.0"
    assert manifest["source_sha"] == SOURCE_SHA
    assert manifest["source_tree"] == SOURCE_TREE
    assert manifest["run_id"] == RUN_ID
    assert manifest["run_attempt"] == RUN_ATTEMPT
    assert [item["name"] for item in manifest["artifacts"]] == sorted(values)
    for item in manifest["artifacts"]:
        assert item["source_sha"] == SOURCE_SHA
        assert item["build_job"] in {"build", "extension-candidate"}
        assert item["size"] == len(values[item["name"]])
        assert item["sha256"] == hashlib.sha256(values[item["name"]]).hexdigest()


def test_manifest_rejects_missing_duplicate_and_unexpected_files(tmp_path):
    _complete_candidate(tmp_path)
    expected = next(iter(candidate.required_artifacts("3.0.0")))
    (tmp_path / "platform-1" / expected).unlink()
    with pytest.raises(ValueError, match="missing candidate artifacts"):
        candidate.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            output=tmp_path.parent / "missing.json",
        )

    _complete_candidate(tmp_path)
    duplicate = tmp_path / "duplicate" / expected
    duplicate.parent.mkdir()
    duplicate.write_bytes(b"duplicate")
    with pytest.raises(ValueError, match="duplicate candidate artifact"):
        candidate.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            output=tmp_path.parent / "duplicate.json",
        )

    duplicate.unlink()
    (tmp_path / "unexpected.log").write_text("debug", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected candidate artifacts"):
        candidate.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            output=tmp_path.parent / "unexpected.json",
        )


def test_manifest_rejects_an_empty_candidate_artifact(tmp_path):
    _complete_candidate(tmp_path)
    expected = next(iter(candidate.required_artifacts("3.0.0")))
    (tmp_path / "platform-1" / expected).write_bytes(b"")

    with pytest.raises(ValueError, match="candidate artifact is empty"):
        candidate.create_manifest(
            tmp_path,
            version="3.0.0",
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            output=tmp_path.parent / "empty.json",
        )


@pytest.mark.parametrize("field,value", (("source_sha", "abc"), ("source_tree", "ABC" * 14)))
def test_manifest_rejects_noncanonical_git_identifiers(tmp_path, field, value):
    _complete_candidate(tmp_path)
    arguments = {
        "version": "3.0.0",
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "run_id": RUN_ID,
        "run_attempt": RUN_ATTEMPT,
        "output": tmp_path.parent / "manifest.json",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        candidate.create_manifest(tmp_path, **arguments)
