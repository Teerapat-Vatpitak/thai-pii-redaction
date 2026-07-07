"""True PDF redaction via flatten-to-image (Step 8).

Renders each page to a raster image, paints opaque black rectangles over the
word bboxes that match entity spans, then rebuilds the PDF from the images.
The output has no text layer, so redacted text is unrecoverable (this also
means the non-redacted text is no longer selectable/searchable — the standard
trade-off of guaranteed redaction).

Permissively licensed: pypdfium2 (Apache/BSD) for rendering, Pillow for drawing.
Replaces the previous PyMuPDF (AGPL) implementation.
"""

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from pii_redactor.models import EntityRegistry, WordBbox

# Render scale (points -> pixels). Higher = crisper output but larger files.
RENDER_SCALE = 2.0

# Padding added around each redaction rectangle, in PDF points, before scaling
# to pixels. Thai vowel/tone marks (sara i/ii, mai ek/tho, etc.) and tall
# consonants (e.g. in "ถนนพหลโยธิน") render above the word bbox's nominal top
# -- measured at ~3pt overshoot on examples/sample_document.pdf (Sarabun,
# 14pt) -- so REDACT_PAD_TOP_PT carries extra margin. Left/right/bottom only
# need to absorb anti-aliasing fringe at a tight box edge. Padding biases
# toward over-coverage per the project's recall > precision invariant.
REDACT_PAD_PT = 2.0
REDACT_PAD_TOP_PT = 5.0

# Two redaction rectangles on the same page are merged into one covering
# rectangle if they are within this many PDF points of each other vertically
# (same line) and horizontally (adjacent words of one entity/line, e.g.
# "ถนนพหลโยธิน" + "แขวงจตุจักร" on an address line). This removes the exposed
# gaps that appeared between separately-drawn per-word boxes.
REDACT_MERGE_GAP_PT = 6.0


def _build_redact_set(entity_registry: EntityRegistry) -> set[str]:
    """
    Build set of text fragments to redact.

    Extracts original_text from each entity and creates a set of fragments
    to match against word bboxes. Also breaks multi-word entities into
    individual words for more granular matching.

    Args:
        entity_registry: Registry containing all detected entities

    Returns:
        Set of text strings to redact
    """
    fragments: set[str] = set()
    for entity in entity_registry.entities:
        orig = entity.original_text.strip()
        if orig:
            fragments.add(orig)
            # Also add individual words from multi-word entities (names, addresses)
            for word in orig.split():
                if len(word) >= 2:
                    fragments.add(word)
    return fragments


def _merge_boxes(boxes: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """
    Merge nearby/overlapping (x0, y0, x1, y1) rectangles (PDF points) into
    covering rectangles, so redacted words that sit next to each other on the
    same line (e.g. multiple words of one NAME/ADDRESS entity) are painted as
    a single solid rectangle instead of leaving a gap of exposed text between
    them. Two boxes merge if their vertical ranges overlap (same line) and
    their horizontal gap is within REDACT_MERGE_GAP_PT.

    Runs to a fixed point so chained merges (A touches B, B touches C) collapse
    into one rectangle even if the boxes weren't given in left-to-right order.
    """
    remaining = list(boxes)
    merged: list[tuple[float, float, float, float]] = []
    while remaining:
        x0, y0, x1, y1 = remaining.pop()
        changed = True
        while changed:
            changed = False
            still_separate = []
            for ox0, oy0, ox1, oy1 in remaining:
                vertical_overlap = y0 < oy1 and oy0 < y1
                horizontal_gap = max(x0, ox0) - min(x1, ox1)
                if vertical_overlap and horizontal_gap <= REDACT_MERGE_GAP_PT:
                    x0, y0, x1, y1 = min(x0, ox0), min(y0, oy0), max(x1, ox1), max(y1, oy1)
                    changed = True
                else:
                    still_separate.append((ox0, oy0, ox1, oy1))
            remaining = still_separate
        merged.append((x0, y0, x1, y1))
    return merged


def redact_pdf(
    input_pdf_path: str,
    entity_registry: EntityRegistry,
    word_bboxes: list[WordBbox],
    output_path: str,
) -> Path:
    """
    Paint black rectangles over all WordBbox items that match entity spans,
    then flatten the PDF to images so the redacted text cannot be recovered.

    Matching is heuristic: a WordBbox is redacted if its text is a substring
    of any entity's original_text, or if the entity's original_text contains
    the word text. This is suitable for prototypes; production would use
    precise char-offset to bbox alignment.

    Args:
        input_pdf_path: Path to input PDF file
        entity_registry: Registry containing entities to redact
        word_bboxes: List of word bounding boxes from PDF extraction
                     (top-origin: x = left, y = top, in PDF points)
        output_path: Path to write redacted PDF

    Returns:
        Path to the redacted PDF file
    """
    out_path = Path(output_path)
    redact_fragments = _build_redact_set(entity_registry)

    # Group word_bboxes by page (text_extractor numbers pages 1-based).
    by_page: dict[int, list[WordBbox]] = {}
    for wb in word_bboxes:
        by_page.setdefault(wb.page, []).append(wb)

    doc = pdfium.PdfDocument(input_pdf_path)
    try:
        page_images: list[Image.Image] = []
        for idx in range(len(doc)):
            page_num = idx + 1  # match the 1-based bboxes
            pil = doc[idx].render(scale=RENDER_SCALE).to_pil().convert("RGB")
            draw = ImageDraw.Draw(pil)

            # Collect PDF-point rectangles first (padded), then merge adjacent
            # ones on the same line, so we draw solid coverage with no gaps
            # instead of one tight rectangle per word.
            pt_boxes: list[tuple[float, float, float, float]] = []
            for wb in by_page.get(page_num, []):
                word_text = wb.text.strip()
                should_redact = len(word_text) >= 2 and any(
                    word_text in frag or frag in word_text for frag in redact_fragments
                )
                if should_redact:
                    pt_boxes.append((
                        wb.x - REDACT_PAD_PT,
                        wb.y - REDACT_PAD_TOP_PT,
                        wb.x + wb.width + REDACT_PAD_PT,
                        wb.y + wb.height + REDACT_PAD_PT,
                    ))

            for x0, y0, x1, y1 in _merge_boxes(pt_boxes):
                draw.rectangle(
                    [x0 * RENDER_SCALE, y0 * RENDER_SCALE, x1 * RENDER_SCALE, y1 * RENDER_SCALE],
                    fill=(0, 0, 0),
                )

            page_images.append(pil)
    finally:
        doc.close()

    if not page_images:
        # No pages — write an empty 1-page white image so output is a valid PDF.
        page_images = [Image.new("RGB", (612, 792), (255, 255, 255))]

    # Pillow's PDF writer JPEG-compresses ("DCTDecode") RGB images by default,
    # which introduces ringing artifacts (a faint gray fringe a few pixels
    # past a hard black/white edge) right at the border of every redaction
    # box -- part of the reported leak. Converting to an adaptive-palette
    # image ("P" mode) makes Pillow write it via lossless ASCIIHexDecode
    # instead, so redaction box edges stay perfectly solid.
    page_images = [im.convert("P", palette=Image.ADAPTIVE) for im in page_images]

    page_images[0].save(
        str(out_path),
        "PDF",
        save_all=True,
        append_images=page_images[1:],
        resolution=72.0 * RENDER_SCALE,
    )
    return out_path
