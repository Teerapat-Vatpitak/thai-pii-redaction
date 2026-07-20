"""Name-level guard that the lockfiles stay in sync with their .txt sources.

Not a resolver: it only checks that every package declared in the source
requirements appears pinned (`name==`) in the lock, so a
forgot-to-regenerate mistake fails fast. Hash correctness is enforced by
pip --require-hashes in CI, not here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("lock_deps", ROOT / "scripts" / "lock_deps.py")
lock_deps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lock_deps)


def _norm(name: str) -> str:
    # PEP 503 name normalization
    return re.sub(r"[-_.]+", "-", name).lower()


def _source_names(*req_files: str) -> set[str]:
    names = set()
    for fname in req_files:
        for line in (ROOT / fname).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
            if m:
                names.add(_norm(m.group(1)))
    return names


def _locked_names(lock_file: str) -> set[str]:
    path = ROOT / lock_file
    if not path.is_file():
        pytest.fail(f"{lock_file} missing -- run: python scripts/lock_deps.py")
    text = path.read_text(encoding="utf-8")
    return {_norm(m.group(1)) for m in re.finditer(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==", text)}


def test_requirements_lock_covers_core_and_web():
    missing = _source_names("requirements.txt", "requirements-web.txt") - _locked_names(
        "requirements.lock"
    )
    assert not missing, (
        f"missing from requirements.lock: {sorted(missing)} -- "
        "regenerate with: python scripts/lock_deps.py"
    )


def test_build_lock_covers_sources_and_pyinstaller():
    locked = _locked_names("requirements-build.lock")
    missing = (
        _source_names("requirements.txt", "requirements-web.txt", "requirements-build.txt") - locked
    )
    assert not missing, (
        f"missing from requirements-build.lock: {sorted(missing)} -- "
        "regenerate with: python scripts/lock_deps.py"
    )
    assert "pyinstaller" in locked


def test_lock_deps_compile_args():
    outputs = [o for o, _ in lock_deps.LOCKS]
    assert outputs == ["requirements.lock", "requirements-build.lock"]
    args = lock_deps.compile_args(*lock_deps.LOCKS[0])
    for flag in ("--universal", "--generate-hashes", "--python-version"):
        assert flag in args, f"{flag} missing from uv invocation"
