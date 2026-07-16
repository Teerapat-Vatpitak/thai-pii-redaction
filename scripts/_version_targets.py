"""Shared list of files that carry the product version string, plus getters
and setters for each file format.

Used by both `scripts/check_version.py` (drift detection) and
`scripts/bump_version.py` (writes a new version everywhere) so the two
scripts can never disagree about what "every version-bearing file" means.
Pure stdlib -- no dependencies, so both scripts stay runnable in a bare CI
job with no `pip install`.

`VERSION` at repo root is the single source of truth and is handled
separately by `read_version_file()` / the callers -- it is not itself in
`targets()`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

Getter = Callable[[Path], Optional[str]]
Setter = Callable[[Path, str], None]


def read_version_file(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def _json_get(path: Path) -> Optional[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("version")


def _json_set(path: Path, new_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if "version" not in data:
        return  # optional field (e.g. desktop/package.json) -- nothing to update
    data["version"] = new_version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# `[package]\nname = "..."\nversion = "..."` -- matches the first
# `version = "..."` line in a Cargo.toml, which is the `[package]` table's
# version as long as it appears before any dependency table (true for every
# Cargo.toml this repo generates/hand-writes).
_CARGO_TOML_VERSION_RE = re.compile(r'^(version\s*=\s*")([^"]+)(")', re.MULTILINE)


def _cargo_toml_get(path: Path) -> Optional[str]:
    match = _CARGO_TOML_VERSION_RE.search(path.read_text(encoding="utf-8"))
    return match.group(2) if match else None


def _cargo_toml_set(path: Path, new_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, n = _CARGO_TOML_VERSION_RE.subn(rf"\g<1>{new_version}\g<3>", text, count=1)
    if n:
        path.write_text(new_text, encoding="utf-8")


# Cargo.lock entry for the `desktop` package specifically -- Cargo.lock lists
# dozens of `[[package]]` blocks (one per crate dependency); only the
# `name = "desktop"` block's version tracks the product version.
_CARGO_LOCK_DESKTOP_RE = re.compile(
    r'(\[\[package\]\]\nname = "desktop"\nversion = ")([^"]+)(")'
)


def _cargo_lock_get(path: Path) -> Optional[str]:
    match = _CARGO_LOCK_DESKTOP_RE.search(path.read_text(encoding="utf-8"))
    return match.group(2) if match else None


def _cargo_lock_set(path: Path, new_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, n = _CARGO_LOCK_DESKTOP_RE.subn(rf"\g<1>{new_version}\g<3>", text, count=1)
    if n:
        path.write_text(new_text, encoding="utf-8")


def targets(root: Path) -> list[tuple[Path, Getter, Setter]]:
    """Every file (besides VERSION itself) that carries the version string,
    as (path-relative-to-root, getter, setter)."""
    return [
        (Path("extension/manifest.json"), _json_get, _json_set),
        (Path("desktop/src-tauri/tauri.conf.json"), _json_get, _json_set),
        (Path("desktop/src-tauri/Cargo.toml"), _cargo_toml_get, _cargo_toml_set),
        (Path("desktop/src-tauri/Cargo.lock"), _cargo_lock_get, _cargo_lock_set),
        # desktop/package.json's `version` field is optional per the design
        # spec -- some Tauri scaffolds omit it. _json_get/_json_set already
        # no-op cleanly when the key is absent.
        (Path("desktop/package.json"), _json_get, _json_set),
    ]
