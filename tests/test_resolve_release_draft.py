"""Draft release lookup must not rely on GitHub's published-tag endpoint."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "resolve_release_draft.py"

_spec = importlib.util.spec_from_file_location("resolve_release_draft", SCRIPT)
resolver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolver)


def test_resolves_one_draft_from_paginated_authenticated_release_list(tmp_path):
    pages = [
        [{"id": 11, "tag_name": "v2.5.0", "draft": False}],
        [{"id": 42, "tag_name": "v3.0.0", "draft": True}],
    ]
    source = tmp_path / "releases.json"
    output = tmp_path / "release-id.txt"
    source.write_text(json.dumps(pages), encoding="utf-8")

    resolver.resolve_to_file(source, tag="v3.0.0", output=output)

    assert output.read_text(encoding="ascii") == "42\n"


def test_rejects_published_and_draft_collision_for_same_tag(tmp_path):
    source = tmp_path / "releases.json"
    source.write_text(
        json.dumps(
            [
                [
                    {"id": 41, "tag_name": "v3.0.0", "draft": False},
                    {"id": 42, "tag_name": "v3.0.0", "draft": True},
                ]
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="published release already uses exact tag"):
        resolver.resolve_to_file(source, tag="v3.0.0", output=tmp_path / "id.txt")


@pytest.mark.parametrize(
    ("matching", "error"),
    [
        ([], "expected exactly one draft release"),
        (
            [
                {"id": 42, "tag_name": "v3.0.0", "draft": True},
                {"id": 43, "tag_name": "v3.0.0", "draft": True},
            ],
            "expected exactly one draft release",
        ),
        (
            [{"id": True, "tag_name": "v3.0.0", "draft": True}],
            "draft release id is invalid",
        ),
    ],
)
def test_rejects_missing_ambiguous_or_invalid_draft(tmp_path, matching, error):
    source = tmp_path / "releases.json"
    source.write_text(json.dumps([matching]), encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        resolver.resolve_to_file(source, tag="v3.0.0", output=tmp_path / "id.txt")


def test_rejects_non_paginated_or_malformed_api_shape(tmp_path):
    for document in ({"id": 42}, [{"id": 42}], [["not-an-object"]]):
        source = tmp_path / "releases.json"
        source.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="release list response is invalid"):
            resolver.resolve_to_file(source, tag="v3.0.0", output=tmp_path / "id.txt")
