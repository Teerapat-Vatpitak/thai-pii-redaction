"""Thai shaping in the reportlab paths.

reportlab draws glyphs in code-point order unless HarfBuzz shaping is on, which
drops a tone mark that stacks on an upper vowel (ที่ = ท + ี + ่). The bug is
invisible to every text-level assertion, so most tests here look at the
shaping data reportlab produces rather than at pixels: a golden image would be
brittle across font versions and platforms, and would still need a human to
interpret it.

Shaping trades one defect for another: HarfBuzz sometimes re-glyphs a stacked
mark to a form with no Unicode codepoint of its own, and reportlab stands it
in with a synthetic Private-Use-Area codepoint. Draw the shaped string alone
and the PDF renders correctly but its text layer is poisoned -- Ctrl+F for
"ที่" fails, extraction returns mangled text. `draw_text()`'s tests build a
real PDF and extract its text with pypdfium2 (the same library the rest of
this project uses to read PDFs) specifically to catch that: a shaping-data
assertion alone would not have caught the PUA defect, only reading back what
the finished document actually contains does.

All sample text is synthetic.
"""

import io

import pypdfium2 as pdfium
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import ShapedStr
from reportlab.pdfgen import canvas

from pii_redactor.thai_pdf_text import (
    contains_thai,
    draw_text,
    register_thai_font,
    shaped,
    shaping_available,
)

STACKED = "ที่"  # ท + ี + ่ -- the tone mark sits on the upper vowel
FLAT = "สมชาย"  # single marks only, nothing for HarfBuzz to move

no_thai_font = pytest.mark.skipif(
    register_thai_font() == "Helvetica",
    reason="no Thai TTF on this machine; shaping cannot be exercised",
)


def _render_and_extract(line: str, font_name: str, font_size: float) -> str:
    """Draw one line with `draw_text` into an in-memory PDF and read it back.

    Uses pypdfium2 (this project's own PDF-reading dependency) rather than a
    pixel comparison, because the defect under test -- a poisoned text layer --
    is invisible to a rendered image and only shows up in extracted text.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont(font_name, font_size)
    draw_text(c, 56, 700, line, font_name, font_size)
    c.showPage()
    c.save()
    doc = pdfium.PdfDocument(buf.getvalue())
    page = doc[0]
    return page.get_textpage().get_text_range()


def _page_ink_bbox(page):
    """Rasterise a pypdfium2 page and return the bbox of its non-white pixels.

    `None` means a blank page -- exactly the failure mode a text-extraction
    assertion cannot see: `setTextRenderMode(3)` on the invisible layer is PDF
    graphics state, not something a `BT`/`ET` text object boundary resets, so
    it silently persisted into the visible layer drawn after it and made the
    whole line invisible, while the extracted text stayed perfectly correct.
    """
    from PIL import ImageOps

    pil = page.render(scale=2).to_pil()
    return ImageOps.invert(pil.convert("L")).getbbox()


def test_contains_thai_is_true_for_any_thai_and_false_otherwise():
    # A cluster-pattern heuristic ("has_stacked_marks") was tried and measured
    # wrong in both directions against real rendering: a false positive on
    # "ผู้ ยู่" (no substitution actually happens) and a false negative on
    # "ป่ ป่วย" (a substitution happens with no vowel involved at all -- driven
    # by the tall ascender on the consonant). Whether a cluster needs
    # re-glyphing is a property of the font, not of adjacent Unicode
    # characters, so this only checks the coarse, honest thing it can get
    # right: is there any Thai script here at all.
    assert contains_thai(STACKED)
    assert contains_thai("ผู้")
    assert contains_thai("ป่วย")
    assert contains_thai(FLAT)
    assert not contains_thai("plain ascii")
    assert not contains_thai("")


@no_thai_font
def test_shaping_is_actually_enabled():
    font = register_thai_font()
    assert shaping_available(font)


@no_thai_font
def test_stacked_word_comes_back_shaped_with_real_offsets():
    font = register_thai_font()
    out = shaped(STACKED, font, 11)
    assert isinstance(out, ShapedStr)
    shaped_text = str(out)
    # HarfBuzz may re-glyph the tone mark to a variant that has no Unicode
    # codepoint of its own; reportlab then stands it in with a private-use-area
    # placeholder (see ttfonts.py's hbAddPrivate). The base consonant and the
    # vowel are never touched -- only a trailing mark can be substituted.
    assert len(shaped_text) == len(STACKED)
    assert shaped_text[:2] == STACKED[:2]
    assert shaped_text[2] == STACKED[2] or 0xE000 <= ord(shaped_text[2]) <= 0xF8FF
    data = out.__shapeData__
    # ท advances; the two marks must not advance and must be nudged into place.
    assert len(data) == 3
    assert data[0].x_advance > 0
    assert all(d.x_advance == 0 for d in data[1:])
    assert any(d.x_offset != 0 or d.y_offset != 0 for d in data[1:])


@no_thai_font
def test_text_with_nothing_to_shape_is_returned_unharmed():
    font = register_thai_font()
    for sample in (FLAT, "plain ascii", ""):
        out = shaped(sample, font, 11)
        assert str(out) == sample


def test_helvetica_fallback_never_raises():
    # No Thai TTF on the machine means reportlab's Latin-only builtin. Shaping
    # is impossible there; the text must come back untouched rather than blow up
    # and take PDF export down with it.
    out = shaped(STACKED, "Helvetica", 11)
    assert str(out) == STACKED
    assert not shaping_available("Helvetica")


def test_shaping_available_is_false_for_an_unregistered_font():
    assert not shaping_available("NoSuchFontRegisteredAnywhere")


@no_thai_font
def test_draw_text_keeps_a_stacked_line_searchable():
    # This is the test that would have caught the PUA defect: shaping alone
    # (drawing `shaped(line, ...)` directly) makes this same line extract as
    # "ทีอยู่ ผู้ปวย" -- mangled, un-Ctrl+F-able text, because HarfBuzz's
    # re-glyphed tone marks land in the Private Use Area. Every other test in
    # this file only inspects shaping data and would stay green even if the
    # text layer were completely poisoned. Only reading back what the
    # finished PDF actually contains exposes that.
    font = register_thai_font()
    line = "ที่อยู่ ผู้ป่วย"
    extracted = _render_and_extract(line, font, 14)
    assert line in extracted


@no_thai_font
def test_draw_text_draws_a_single_layer_when_nothing_needs_shaping():
    font = register_thai_font()
    # ASCII and flat Thai (single marks only, nothing for HarfBuzz to move)
    # both take the same one-layer path: `shaped()` returns a plain `str` for
    # either, so neither should pay for an invisible search layer on top of
    # the visible one -- each line must appear exactly once.
    for line in ("somchai plain text 123", FLAT):
        extracted = _render_and_extract(line, font, 14)
        assert extracted.count(line) == 1


def test_draw_text_never_mutates_the_canvas_font_state():
    """draw_text must never call the canvas's OWN setFont.

    A before/after comparison of `(c._fontname, c._fontsize)` alone cannot
    prove that: those two attributes are in reportlab's own
    `Canvas.STATE_ATTRIBUTES`, so `restoreState()` -- which draw_text calls
    to bracket the invisible layer's `Tr 3` (see the module docstring) --
    silently snapshots and restores them as a side effect. A `c.setFont(...)`
    call injected right after `c.saveState()` inside that bracket is already
    undone by `restoreState()` before this test ever gets control back, so
    a before/after comparison alone stays green even with the mutation
    happening. Spying directly on `canvas.Canvas.setFont` has no such blind
    spot: draw_text only ever calls `PDFTextObject.setFont` (a different
    method, on the text objects `c.beginText(...)` returns), never the
    canvas's own `setFont`, so this spy should see zero calls -- regardless
    of what `restoreState()` later does to canvas attributes.
    """
    font = register_thai_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont(font, 20)
    before = (c._fontname, c._fontsize)

    calls = []
    original_set_font = c.setFont

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original_set_font(*args, **kwargs)

    c.setFont = spy
    # Deliberately mismatched font_size, as before: harmless on its own
    # (HarfBuzz offsets are per-mille-em and rescale), so this isolates the
    # two properties actually under test here.
    draw_text(c, 56, 700, STACKED, font, 9)

    assert calls == [], f"draw_text called canvas.setFont directly: {calls}"
    assert (c._fontname, c._fontsize) == before


@no_thai_font
def test_draw_text_actually_puts_ink_on_the_page():
    """Every other test in this file passes on a completely blank page.

    They all inspect extracted TEXT or shaping DATA, and both of those stayed
    perfectly correct through a real regression: the invisible layer's
    `setTextRenderMode(3)` is PDF graphics state, not scoped to its own `BT`/
    `ET` text object, so it leaked into the visible layer drawn right after
    it and made the whole line invisible -- nine tests, three review rounds,
    and the original spec all missed a blank page, because none of them
    looked at the rendered page. This is the only test in the file that can
    see that failure: it rasterises the page and checks that ink actually
    landed, for a stacked line, a flat Thai line, and an ASCII line.
    """
    font = register_thai_font()
    for line in (STACKED, FLAT, "plain ascii 123"):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        draw_text(c, 100, 700, line, font, 24)
        c.showPage()
        c.save()
        doc = pdfium.PdfDocument(buf.getvalue())
        bbox = _page_ink_bbox(doc[0])
        assert bbox is not None, f"{line!r} produced a blank page"


@no_thai_font
def test_exported_pdf_keeps_every_character_of_a_stacked_word(tmp_path):
    """A dropped glyph is the failure mode that matters; extract and compare.

    Position is checked by the shaping-data tests above. This one catches the
    coarser regression of a character disappearing from the page entirely --
    and, since the `Tr 3` graphics-state leak that made shaped lines invisible
    (see `test_draw_text_actually_puts_ink_on_the_page`) would have shipped
    through this exact path with every text-level assertion here still green,
    also that the rendered page actually has ink on it, not just a correct
    text layer. Exercises the real export() path (pii_redactor/exporter.py),
    which is what actually ships to users, rather than calling draw_text
    directly.
    """
    from pii_redactor.exporter import export
    from pii_redactor.models import ReverseResult
    from pii_redactor.output_validator import ValidationResult

    body = "ผู้ป่วยอยู่ที่บ้านเลขที่ 42 เที่ยงนี้"
    out = tmp_path / "shaped.pdf"
    export(
        ReverseResult(text=body, flags=[], audit_summary={}),
        ValidationResult(
            passed=True,
            layer1_pii_clean=True,
            layer2_completeness_ok=True,
            layer3_integrity_ok=True,
            flags=[],
            halt=False,
        ),
        str(out),
        fmt="pdf_text",
    )

    doc = pdfium.PdfDocument(out.read_bytes())
    page = doc[0]
    extracted = page.get_textpage().get_text_range()
    for ch in set(body) - {" "}:
        assert ch in extracted, f"character {ch!r} vanished from the exported PDF"
    assert _page_ink_bbox(page) is not None, "exported PDF page is blank"


def test_pdf_modules_never_draw_unshaped_text():
    """Every drawString in the PDF-authoring modules must go through shaped().

    This is the test that would have caught the original defect. It reads source
    rather than behaviour on purpose: the failure it guards against is someone
    adding a line, not someone changing a value.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    draw = re.compile(r"\.draw(?:Centred|Right)?String\s*\(")
    offenders = []
    for rel in (
        "pii_redactor/report_pdf.py",
        "pii_redactor/exporter.py",
        "pii_redactor/receipt_pdf.py",
    ):
        src = (root / rel).read_text(encoding="utf-8")
        for n, line in enumerate(src.splitlines(), 1):
            if draw.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, (
        "these modules must draw through thai_pdf_text.draw_text(), which pairs "
        "an invisible real-character layer with the visible shaped glyphs. A raw "
        "drawString drops Thai tone marks, or poisons the text layer with "
        "Private-Use codepoints, depending on what it is handed:\n" + "\n".join(offenders)
    )


@no_thai_font
def test_the_tone_mark_is_actually_lifted_above_the_vowel():
    """The one assertion that measures what this whole feature exists to do.

    Every other test here passes on catastrophically misplaced marks: the
    shaping-data tests accept any non-zero offset (a mark shoved 400 units left,
    or below the baseline, satisfies them), the ink tests accept any mark
    anywhere on the page, and the extraction tests never look at the page at
    all. The Chrome comparison that actually validated placement was a one-off
    manual step whose images live outside the repo.

    So measure the property directly and cheaply. A tone mark stacked on an
    upper vowel has to sit ABOVE that vowel, which means the topmost ink of
    "ที่" must be higher on the page than the topmost ink of "ที". Unshaped,
    reportlab draws the mark at its default height where it collides with the
    vowel and adds no ink above it, so the two are identical -- measured 769
    and 769. Shaped, HarfBuzz substitutes the raised glyph -- measured 739 vs
    769, a 30px lift at 60pt/scale 2.

    No golden image, so this survives font and platform differences: it only
    asserts an ordering between two renders made the same way on the same box.
    """
    font = register_thai_font()
    base = _top_ink("ที", font)
    stacked = _top_ink("ที่", font)
    assert base is not None and stacked is not None, "expected ink from both renders"
    assert stacked < base, (
        f"the tone mark in 'ที่' is not sitting above the vowel: topmost ink "
        f"{stacked} vs {base} for the same word without the mark. Equal values "
        f"mean shaping is off again and the mark is colliding with the vowel."
    )


def _top_ink(word: str, font: str, size: int = 60) -> int | None:
    """Y of the topmost inked pixel when `word` is drawn through draw_text."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    draw_text(c, 60, 400, word, font, size)
    c.showPage()
    c.save()
    img = pdfium.PdfDocument(buf.getvalue())[0].render(scale=2).to_pil()
    bbox = img.convert("L").point(lambda p: 255 - p).getbbox()
    return bbox[1] if bbox else None
