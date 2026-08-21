"""latest.json is derived from the current run and one exact draft release."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "create_latest_json.py"

_spec = importlib.util.spec_from_file_location("create_latest_json", SCRIPT)
latest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(latest)


def _inputs(tmp_path: Path):
    version = "3.0.0"
    build_names = sorted(latest.required_build_artifacts(version))
    artifacts = []
    metadata = []
    signatures = tmp_path / "signatures"
    signatures.mkdir()
    for index, name in enumerate(build_names, start=1):
        artifacts.append({"name": name, "size": index, "sha256": f"{index:064x}"})
        metadata.append({"id": 1000 + index, "name": name, "size": index})
        if name.endswith(".sig"):
            encoded = base64.b64encode(f"signature-{index}".encode()).decode()
            (signatures / name).write_text(f"{encoded}\n", encoding="utf-8")
    metadata.extend(
        (
            {"id": 2001, "name": "latest.json", "size": 1},
            {"id": 2002, "name": "SHA256SUMS", "size": 1},
        )
    )
    build_manifest = tmp_path / "build.json"
    build_manifest.write_text(
        json.dumps(
            {
                "schema": "aiguard-release-build/v1",
                "version": version,
                "source_sha": "a" * 40,
                "source_tree": "b" * 40,
                "run_id": "1",
                "run_attempt": 1,
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    asset_metadata = tmp_path / "assets.json"
    asset_metadata.write_text(json.dumps(metadata), encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text("Release-specific notes.\n", encoding="utf-8")
    return build_manifest, asset_metadata, signatures, notes


def test_latest_is_canonical_and_uses_exact_release_asset_ids(tmp_path):
    build, assets, signatures, notes = _inputs(tmp_path)
    output = tmp_path / "latest.json"

    latest.create_latest(
        build_manifest=build,
        asset_metadata=assets,
        signatures_dir=signatures,
        notes_path=notes,
        pub_date="2026-08-14T12:00:00+07:00",
        repository="owner/repository",
        output=output,
    )

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["version"] == "3.0.0"
    assert document["notes"] == "Release-specific notes.\n"
    # No `linux-*` keys: the Desktop stopped shipping AppImage and DEB, and an
    # updater entry pointing at an asset this release never built would send a
    # 3.0.0 Linux install after a download that does not exist.
    assert set(document["platforms"]) == {
        "darwin-aarch64",
        "darwin-aarch64-app",
        "windows-x86_64",
        "windows-x86_64-nsis",
    }
    for update in document["platforms"].values():
        assert update["url"].startswith(
            "https://api.github.com/repos/owner/repository/releases/assets/"
        )
        assert base64.b64decode(update["signature"], validate=True).startswith(b"signature-")
    assert output.read_bytes().endswith(b"\n")


@pytest.mark.parametrize(
    "mutation,error",
    (
        (
            lambda data: data.append({"id": 9999, "name": "payload-3.0.0.zip", "size": 1}),
            "unexpected release assets",
        ),
        (lambda data: data.__setitem__(0, {**data[0], "size": 999}), "size differs"),
        (lambda data: data.pop(0), "missing release assets"),
    ),
)
def test_latest_rejects_ambiguous_stale_or_incomplete_draft_assets(tmp_path, mutation, error):
    build, assets, signatures, notes = _inputs(tmp_path)
    metadata = json.loads(assets.read_text(encoding="utf-8"))
    mutation(metadata)
    assets.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        latest.create_latest(
            build_manifest=build,
            asset_metadata=assets,
            signatures_dir=signatures,
            notes_path=notes,
            pub_date="2026-08-14T12:00:00Z",
            repository="owner/repository",
            output=tmp_path / "latest.json",
        )
