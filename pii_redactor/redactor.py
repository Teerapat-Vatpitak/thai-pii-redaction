"""True PDF redaction via PyMuPDF (Step 8).

Draw opaque black rectangles over word bboxes that match entity spans.
"""

import fitz
from pathlib import Path

from pii_redactor.models import EntityRegistry, WordBbox


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
    Draw black rectangles over all WordBbox items that match entity spans.

    Matching is heuristic: a WordBbox is redacted if its text is a substring
    of any entity's original_text, or if the entity's original_text contains
    the word text. This is suitable for prototypes; production would use
    precise char-offset to bbox alignment.

    Args:
        input_pdf_path: Path to input PDF file
        entity_registry: Registry containing entities to redact
        word_bboxes: List of word bounding boxes from PDF extraction
        output_path: Path to write redacted PDF

    Returns:
        Path to the redacted PDF file
    """
    out_path = Path(output_path)

    redact_fragments = _build_redact_set(entity_registry)

    # Group word_bboxes by page
    by_page: dict[int, list[WordBbox]] = {}
    for wb in word_bboxes:
        by_page.setdefault(wb.page, []).append(wb)

    doc = fitz.open(input_pdf_path)

    for page_num, page in enumerate(doc):
        words_on_page = by_page.get(page_num, [])
        for wb in words_on_page:
            # Check if this word should be redacted
            word_text = wb.text.strip()
            should_redact = (
                len(word_text) >= 2
                and any(
                    word_text in frag or frag in word_text
                    for frag in redact_fragments
                )
            )
            if should_redact:
                rect = fitz.Rect(wb.x, wb.y, wb.x + wb.width, wb.y + wb.height)
                # Add annotation with black fill (true redaction)
                page.add_redact_annot(rect, fill=(0, 0, 0))

        page.apply_redactions()

    doc.save(str(out_path))
    doc.close()

    return out_path
