"""The two copies of the design tokens, and the variables that depend on them.

`desktop/src/tokens.css` is the canonical file and `extension/tokens.css` is a
byte-identical copy — the packages ship separately and cannot `@import` across
each other, so nothing but a test keeps them together.

The second check is the one that catches real breakage: a stylesheet asking for
a custom property nobody declares renders as *nothing*, silently. Renaming a
token and missing one call site produces a transparent border or black-on-black
text with no error anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "desktop" / "src" / "tokens.css"
COPY = ROOT / "extension" / "tokens.css"

# Stylesheets that consume the shared tokens.
CONSUMERS = (
    ROOT / "desktop" / "src" / "styles.css",
    ROOT / "extension" / "sidepanel.css",
)

_VAR_USE = re.compile(r"var\(\s*(--[a-z0-9-]+)", re.IGNORECASE)
# Declarations are packed several to a line in these files, so this cannot be
# anchored to the start of one. `var(--x)` has no colon after the name, so a
# use is never mistaken for a declaration.
_VAR_DECL = re.compile(r"(?<![\w-])(--[a-z0-9-]+)\s*:", re.IGNORECASE)


def _declared() -> set[str]:
    return set(_VAR_DECL.findall(CANONICAL.read_text(encoding="utf-8")))


def test_the_extension_copy_is_byte_identical():
    assert COPY.read_bytes() == CANONICAL.read_bytes(), (
        "extension/tokens.css drifted from desktop/src/tokens.css; copy the canonical file over"
    )


def test_every_token_a_stylesheet_asks_for_is_declared():
    declared = _declared()
    for path in CONSUMERS:
        used = set(_VAR_USE.findall(path.read_text(encoding="utf-8")))
        missing = sorted(used - declared)
        assert not missing, f"{path.relative_to(ROOT)} uses undeclared tokens: {missing}"


def test_injected_page_styles_declare_their_own_namespace():
    # content.css and the shadow-root CSS inside content.js cannot see
    # tokens.css: they are injected into someone else's page. Every --ag-* they
    # use has to be declared in the same file, which is what keeps the host page
    # untouched.
    for path in (ROOT / "extension" / "content.css", ROOT / "extension" / "content.js"):
        text = path.read_text(encoding="utf-8")
        used = {name for name in _VAR_USE.findall(text) if name.startswith("--ag-")}
        declared = set(_VAR_DECL.findall(text))
        missing = sorted(used - declared)
        assert not missing, f"{path.relative_to(ROOT)} uses undeclared --ag- tokens: {missing}"


def test_the_palette_stays_white_first():
    # The agreed direction is clean/white/minimal. --bg being anything but white
    # is the single change that would undo it everywhere at once, so it is
    # pinned rather than left to review.
    text = CANONICAL.read_text(encoding="utf-8")
    light_block = text.split(':root[data-theme="dark"]')[0]
    assert re.search(r"--bg:\s*#FFFFFF", light_block, re.IGNORECASE)
