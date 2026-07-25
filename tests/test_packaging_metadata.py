"""The setuptools package list is explicit, so a new subpackage is silently
dropped from any wheel until someone adds it by hand. Source-tree tests never
see that: they import from the repo root, where sys.path makes the omission
invisible."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_source_package_is_declared_for_distribution():
    declared = set(
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
            "packages"
        ]
    )
    found = {
        ".".join(init.parent.relative_to(ROOT).parts)
        for top in ("pii_redactor", "app")
        for init in (ROOT / top).rglob("__init__.py")
    }
    assert found <= declared, f"missing from pyproject packages: {sorted(found - declared)}"
