"""Thai text for reportlab-authored PDFs.

reportlab 5 contains HarfBuzz shaping but keeps it off in two independent ways:
`TTFont.shapable` is False whenever `uharfbuzz` cannot be imported (silently),
and `canvas.drawString` only shapes when it is handed a `ShapedStr` rather than
a plain `str`. Without both, a Thai tone mark that stacks on an upper vowel
(ที่, ผู้, เที่ยง) is dropped or misplaced, while single-mark words look fine --
which is why the defect survived every text-level test.

Shaping itself has a cost: HarfBuzz sometimes re-glyphs a stacked mark to a
form that has no Unicode codepoint of its own, and reportlab stands it in with
a synthetic Private-Use-Area codepoint (see `ttfonts.py`'s `hbAddPrivate`).
That poisons the PDF's text layer -- a document built from shaped strings alone
extracts and Ctrl+F-searches as mangled text (measured: "ที่อยู่ ผู้ป่วย" comes
back as "ทีอยู่ ผู้ปวย"). `draw_text()` is the fix the owner accepted: draw the
real characters invisibly (for search/copy) and the shaped glyphs visibly (for
correct rendering) on the same line. The accepted cost is that copying an
affected line out of the finished PDF yields it twice.

Every PRODUCT module that draws Thai into a PDF -- report_pdf.py, exporter.py
and receipt_pdf.py -- routes through here, and tests/test_thai_shaping.py fails
the build if any of them ever calls drawString directly again. `examples/make_sample_pdf.py`
is deliberately outside that net: it is a developer fixture generator, it still
draws Thai with a raw drawString, and the sample PDF committed beside it still
carries the unfixed rendering.

Requires reportlab >= 4.4.0 -- `shapeStr` does not exist before that, and the
import below is what breaks first if the floor in requirements.txt slips.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import ShapedStr, TTFont, shapeStr
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# Thai-capable TrueType candidates, in preference order. Falls back to
# reportlab's Latin-only Helvetica when none exists -- Thai glyphs then do not
# render at all, the same trade-off examples/make_sample_pdf.py accepts.
#
# Order is load-bearing here, not cosmetic: see the note on the second entry.
# Nothing on this list is bundled -- `scripts/build_sidecar.py` ships no font
# at all, so what a packaged user gets depends entirely on what their machine
# already has.
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\sarabun-v17-latin_latin-ext_thai_vietnamese-regular.ttf",
    # Leelawadee UI ships with every Windows edition -- it is the shell's own
    # Thai/Lao/Khmer UI face -- while the Sarabun path above is hand-installed.
    # Without this entry a stock Windows machine finds no candidate at all,
    # falls back to Helvetica, and renders every Thai glyph in the PDPA report
    # and the processing receipt as a black box. That was true from this
    # module's introduction; the developer's machine happened to have Sarabun,
    # so nothing here could see it.
    #
    # Second and not first, deliberately. Sarabun positions Thai marks by
    # substituting glyphs, so HarfBuzz reports no vertical offsets and reportlab
    # emits no `Ts` (text rise) operators at all. Leelawadee UI positions them
    # with non-zero y-offsets instead, which walks into a defect in reportlab's
    # `PDFTextObject.setRise` -- see `_install_rise_fix()` below, which repairs
    # it. Kept second anyway: Sarabun never touches that code path at all, so
    # it stays the safer choice where it exists. This entry is the net under
    # the trapeze, not a recommendation.
    r"C:\Windows\Fonts\leelawui.ttf",
    "/usr/share/fonts/truetype/thai/Sarabun-Regular.ttf",
    # fonts-thai-tlwg (Debian/Ubuntu, incl. CI + Docker): Laksaman is the
    # TH Sarabun New derivative the package actually ships.
    "/usr/share/fonts/truetype/tlwg/Laksaman.ttf",
]

# Filenames Windows itself supplies, as opposed to fonts a developer installed.
# Kept next to the list it describes so the test that guards this cannot drift
# away from it. Tahoma and leelawad.ttf are deliberately absent: both leak rise
# the same way and neither covers a case Leelawadee UI does not.
WINDOWS_STOCK_FONT_FILES = frozenset({"leelawui.ttf", "leelauib.ttf", "leeluisl.ttf"})
THAI_FONT_NAME = "Sarabun"

# Whether a given vowel-plus-tone-mark cluster actually needs its mark
# re-glyphed is a question about the FONT's glyph inventory (a tall-ascender
# consonant like PO PLA needs the mark raised to a substituted glyph; a
# short one like KO KAI or CHO CHAN does not) -- not about which Unicode
# characters are adjacent. A character-class regex chasing that was tried
# and measured wrong in both directions (see `shaped()`'s docstring), so this
# module does not attempt to predict which clusters need shaping. It only
# asks whether Thai script is present at all -- the whole Thai Unicode block.
_THAI_BLOCK = re.compile("[\u0e00-\u0e7f]")

_warned = False


def _rise_state_is_lost() -> bool:
    """True when reportlab's `setRise` forgets the rise it just emitted.

    `PDFTextObject.setRise` has two branches. The else-branch stores the new
    rise and adjusts `_y`. The "optimize out r0 Ts r1 Ts" branch rewrites the
    emitted operator and reverses `_y` using the OLD rise -- then never assigns
    the new one. Probed by behaviour rather than by reading the source, so this
    answers the only question that matters (does this installation disagree
    with itself) and needs no rewriting when the code moves.
    """
    from io import BytesIO

    text = canvas.Canvas(BytesIO()).beginText(0, 0)
    text.setRise(1)  # else-branch: appends "1 Ts"
    text.setRise(2)  # optimize branch: rewrites it
    return text._rise != 2


def _install_rise_fix() -> bool:
    """Repair `setRise` in place, and report whether anything needed repairing.

    Why this is worth patching a third-party library for: Thai fonts split into
    two camps. Sarabun positions tone marks by substituting glyphs, so HarfBuzz
    reports no vertical offsets, no `Ts` is ever emitted, and this defect cannot
    fire. Leelawadee UI -- the only Thai face Windows actually ships, and
    therefore the only fallback available to a user who has installed nothing --
    positions them with y-offsets instead. Under the unrepaired branch the
    Python-side `_rise` drifts from the content stream, the `r != self._rise`
    guard in `_formatText` stops firing, and a run of following characters stays
    stranded at the previous rise. Measured on "รายงานความเสี่ยงข้อมูลส่วนบุคคล"
    at 26pt: the span "ยงข้อมูลส" sits visibly above the baseline, and the line
    resolves to 15 distinct glyph baselines instead of 11.

    Applied conditionally, so a reportlab release that fixes this upstream
    silently stops being patched rather than being patched twice.
    """
    if not _rise_state_is_lost():
        return False

    from reportlab.pdfgen.textobject import PDFTextObject, fp_str

    # Name matches reportlab's own method, which is what it replaces.
    def setRise(self, rise):
        v = f"{fp_str(rise)} Ts"
        if self._code[-1].endswith(" Ts"):
            self._y += self._rise
            self._code[-1] = v
            self._rise = rise
            self._y -= rise
        else:
            self._rise = rise
            self._y -= rise
            self._code.append(v)

    PDFTextObject.setRise = setRise
    return True


RISE_FIX_APPLIED = _install_rise_fix()


def register_thai_font() -> str:
    """Register a Thai-capable TTF with reportlab; fall back to Helvetica."""
    font_path = next((f for f in FONT_CANDIDATES if Path(f).exists()), None)
    if font_path is None:
        return "Helvetica"
    if THAI_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(THAI_FONT_NAME, font_path))
    return THAI_FONT_NAME


def contains_thai(text: str) -> bool:
    """True when `text` has any Thai character (the Thai Unicode block)."""
    return bool(_THAI_BLOCK.search(text))


def shaping_available(font_name: str) -> bool:
    """True when `font_name` is registered and reportlab can shape with it.

    `TTFont.shapable` already folds in the uharfbuzz import check, so this one
    property answers both halves of the question.
    """
    try:
        font = pdfmetrics.getFont(font_name)
    except Exception:
        return False
    return bool(getattr(font, "shapable", False))


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    # Deliberately says nothing about the text being drawn -- it is user content.
    logger.warning(
        "Thai text shaping is unavailable; some stacked tone marks may render "
        "incorrectly. Install uharfbuzz and a Thai TrueType font."
    )


def shaped(text: str, font_name: str, font_size: float) -> str:
    """Return `text` ready for `canvas.drawString`, shaped when possible.

    Returns a `ShapedStr` when HarfBuzz moved something, the original string
    otherwise. Never raises: a font problem must not take PDF export down.

    When shaping is unavailable, the warning fires on any Thai text at all,
    not on some predicted subset of "dangerous" clusters. A first attempt at
    that prediction used a character-class regex over vowel-plus-tone-mark
    adjacency; measuring it against real rendering (Sarabun, 13 clusters)
    found it wrong in both directions -- a false positive ("ผู้ ยู่": no
    substitution happens, the regex fired anyway) and, worse, a false
    negative ("ป่ ป่วย": a substitution happens with no vowel involved at
    all, driven by the tall ascender on the consonant, which the regex never
    modeled). Whether a cluster needs a substituted glyph is a property of
    the font's own glyph inventory, not of which Unicode characters sit next
    to each other -- encoding that into a regex means re-deriving the font's
    shaping rules by hand, and the measurement shows that attempt fails
    silently in exactly the direction that matters: a false negative here is
    a stacked mark rendered wrong with no warning at all, while a false
    positive only costs one avoidable log line (the warning is once-per-
    process). This project's stated invariant is recall over precision, so
    this checks the coarse, honest thing it can actually get right.
    """
    if not text:
        return text
    if not shaping_available(font_name):
        if contains_thai(text):
            _warn_once()
        return text
    try:
        return shapeStr(text, font_name, font_size)
    except Exception:  # pragma: no cover - defensive; shapeStr is total in practice
        _warn_once()
        return text


def draw_text(
    c: canvas.Canvas, x: float, y: float, text: str, font_name: str, font_size: float
) -> None:
    """Draw `text` at `(x, y)`, shaping stacked Thai marks when possible.

    When shaping changes nothing (Latin, digits, Thai with no stacked mark,
    empty text) this draws a single, ordinary visible line -- there is nothing
    a second layer would buy, so it is not paid for.

    When shaping does change something, `shaped()`'s output renders correctly
    but its text layer is partly Private-Use-Area codepoints (see the module
    docstring), so the *original* `text` is drawn first, in the same position,
    with an invisible text render mode -- this is what keeps the line
    searchable and copyable as real characters -- and the shaped glyphs are
    then drawn visibly on top. The accepted cost: extracting an affected line
    from the finished PDF yields it twice (once invisible/original, once
    visible/shaped).

    Self-contained either way: every layer is its own `PDFTextObject` with an
    explicit `setFont(font_name, font_size)`, never `c.drawString`. reportlab
    only consults `ShapedStr.__shapeData__` when the *text object's* font
    matches the one the shape data was computed for (`_formatText` looks up
    `pdfmetrics.getFont(self._fontname)`, the text object's own font, not the
    canvas's) -- `c.drawString` would instead read whatever font happens to be
    active on `c`, which is only correct by coincidence when the caller
    already called `c.setFont(font_name, font_size)` first. A size mismatch
    there would be harmless (HarfBuzz's offsets are per-mille-em and rescale
    with whatever size is drawn at), but a font_name mismatch would render
    the wrong glyphs outright. Building each layer's own text object removes
    that dependency entirely, and never calls `c.setFont(...)`, so nothing
    here reads or mutates the canvas's own font state -- the caller's active
    font is exactly as it was before this call.

    The invisible layer's `Tr 3` (text render mode) is PDF graphics state, not
    something `BT`/`ET` resets -- it persists into whatever gets drawn next in
    the same content stream. Without bracketing it, the visible layer that
    follows inherits render mode 3 and comes out invisible too, so the whole
    line disappears (measured: `saveState`/`restoreState` around only the
    invisible layer is what keeps the visible layer visible; explicitly
    calling `setTextRenderMode(0)` on the visible layer's own text object does
    NOT fix it, because the leaked `Tr 3` lives in the page's graphics state,
    outside any single `PDFTextObject`). `saveState`/`restoreState` (PDF `q`/
    `Q`) is scoped to the canvas, not to a text object, so it is the only one
    of the two that can bracket a graphics-state leak. The bracket is wrapped
    in `try`/`finally` so a `restoreState()` is never skipped -- an unhandled
    exception between `saveState()` and `restoreState()` would otherwise leave
    the canvas's `q`/`Q` stack unbalanced for the rest of the page, corrupting
    everything drawn after this call, not just this one line.

    One consequence worth knowing: `reportlab.pdfgen.canvas.Canvas.
    STATE_ATTRIBUTES` includes `_fontname`/`_fontsize`, so `restoreState()`
    snapshots and restores the canvas's own font as a side effect of
    bracketing `Tr` -- a canvas-level font mutation occurring *inside* this
    bracket would already be undone by the time this function returns. That
    is a reason to verify the "never touches the canvas's font" property by
    spying on whether `c.setFont` is ever called at all (it should not be;
    only `PDFTextObject.setFont` calls on this function's own text objects
    are used), not by comparing `(c._fontname, c._fontsize)` before and after
    the call -- the latter would stay green even if this function called
    `c.setFont(...)` internally, precisely because `restoreState()` erases
    that mutation before control returns to the caller.
    """
    out = shaped(text, font_name, font_size)
    if not isinstance(out, ShapedStr):
        visible = c.beginText(x, y)
        visible.setFont(font_name, font_size)
        visible.textOut(out)
        c.drawText(visible)
        return
    c.saveState()
    try:
        invisible = c.beginText(x, y)
        invisible.setFont(font_name, font_size)
        invisible.setTextRenderMode(3)  # invisible: carries the real characters for search/copy
        invisible.textOut(text)
        c.drawText(invisible)
    finally:
        # Tr 3 is graphics state and would otherwise leak into the visible
        # layer below; `finally` keeps the canvas's q/Q stack balanced even
        # if something above raises, instead of leaving it unbalanced for
        # the rest of the page.
        c.restoreState()
    visible = c.beginText(x, y)
    visible.setFont(font_name, font_size)
    visible.textOut(out)  # visible: the correctly shaped glyphs
    c.drawText(visible)
