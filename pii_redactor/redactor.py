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

            for wb in by_page.get(page_num, []):
                word_text = wb.text.strip()
                should_redact = len(word_text) >= 2 and any(
                    word_text in frag or frag in word_text for frag in redact_fragments
                )
                if should_redact:
                    x0 = wb.x * RENDER_SCALE
                    y0 = wb.y * RENDER_SCALE
                    x1 = (wb.x + wb.width) * RENDER_SCALE
                    y1 = (wb.y + wb.height) * RENDER_SCALE
                    draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))

            page_images.append(pil)
    finally:
        doc.close()

    if not page_images:
        # No pages — write an empty 1-page white image so output is a valid PDF.
        page_images = [Image.new("RGB", (612, 792), (255, 255, 255))]

    page_images[0].save(
        str(out_path),
        "PDF",
        save_all=True,
        append_images=page_images[1:],
        resolution=72.0 * RENDER_SCALE,
    )
    return out_path
