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

# Surfaces that cannot reach tokens.css and therefore declare every role they
# use themselves: the add-in builds to its own bundle, the playground is served
# standalone. Both have already shipped a var() pointing at a role that was
# never declared, which renders as nothing at all.
SELF_CONTAINED = (
    ROOT / "office-addin" / "src" / "styles.css",
    ROOT / "demo" / "playground.html",
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
    # A stylesheet may also declare its own component-scoped properties — MD3's
    # state layer needs one (`--state-color`) set per variant, which belongs on
    # the component, not in the shared token file. Those count as declared.
    shared = _declared()
    for path in CONSUMERS:
        text = path.read_text(encoding="utf-8")
        used = set(_VAR_USE.findall(text))
        declared = shared | set(_VAR_DECL.findall(text))
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


def test_self_contained_surfaces_declare_every_token_they_use():
    for path in SELF_CONTAINED:
        text = path.read_text(encoding="utf-8")
        used = set(_VAR_USE.findall(text))
        declared = set(_VAR_DECL.findall(text))
        missing = sorted(used - declared)
        assert not missing, f"{path.relative_to(ROOT)} uses undeclared tokens: {missing}"


def _token_value(name: str) -> str:
    match = re.search(rf"{re.escape(name)}\s*:\s*([^;]+);", CANONICAL.read_text(encoding="utf-8"))
    assert match, f"{name} is not declared in tokens.css"
    return match.group(1).strip()


def test_state_layer_opacities_match_the_material_spec():
    # From material-web's _md-sys-state.scss. These four numbers are what makes
    # a hover feel like Material rather than like a colour swap, and they are
    # easy to "tidy" into round numbers that are then subtly wrong everywhere.
    assert _token_value("--md-sys-state-hover-state-layer-opacity") == "0.08"
    assert _token_value("--md-sys-state-focus-state-layer-opacity") == "0.12"
    assert _token_value("--md-sys-state-pressed-state-layer-opacity") == "0.12"
    assert _token_value("--md-sys-state-dragged-state-layer-opacity") == "0.16"


def test_shape_scale_matches_the_material_spec():
    # From material-web's _md-sys-shape.scss.
    assert _token_value("--md-sys-shape-corner-extra-small") == "4px"
    assert _token_value("--md-sys-shape-corner-small") == "8px"
    assert _token_value("--md-sys-shape-corner-medium") == "12px"
    assert _token_value("--md-sys-shape-corner-large") == "16px"
    assert _token_value("--md-sys-shape-corner-extra-large") == "28px"
    assert _token_value("--md-sys-shape-corner-full") == "9999px"


def test_type_scale_matches_the_material_spec():
    # A sample across the five roles, from material-web's _md-sys-typescale.scss.
    assert _token_value("--md-sys-typescale-label-large-size") == "0.875rem"
    assert _token_value("--md-sys-typescale-label-large-weight") == "500"
    assert _token_value("--md-sys-typescale-body-medium-size") == "0.875rem"
    assert _token_value("--md-sys-typescale-body-medium-line-height") == "1.25rem"
    assert _token_value("--md-sys-typescale-title-large-size") == "1.375rem"
    assert _token_value("--md-sys-typescale-headline-small-size") == "1.5rem"
    assert _token_value("--md-sys-typescale-display-small-size") == "2.25rem"


def test_every_colour_role_a_component_needs_is_declared():
    # The component sheets are written against the role names, so a missing role
    # is an invisible failure: var() with no declaration renders as nothing.
    required = [
        "primary",
        "on-primary",
        "primary-container",
        "on-primary-container",
        "secondary-container",
        "on-secondary-container",
        "tertiary-container",
        "on-tertiary-container",
        "error",
        "on-error",
        "error-container",
        "on-error-container",
        "surface",
        "on-surface",
        "on-surface-variant",
        "surface-container-low",
        "surface-container",
        "surface-container-high",
        "outline",
        "outline-variant",
        "inverse-surface",
        "inverse-on-surface",
    ]
    text = CANONICAL.read_text(encoding="utf-8")
    light_block = text.split(':root[data-theme="dark"]')[0]
    missing = [r for r in required if f"--md-sys-color-{r}:" not in light_block.replace(" ", "")]
    assert not missing, f"tokens.css is missing colour roles: {missing}"
