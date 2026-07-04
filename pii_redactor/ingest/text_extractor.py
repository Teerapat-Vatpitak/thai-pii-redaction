"""Text extraction from documents."""
from __future__ import annotations

from pathlib import Path

from pii_redactor.ingest.file_detector import validate_encoding
from pii_redactor.models import WordBbox

# A single page with at least this many text-layer characters is treated as
# having a real text layer (lower than file_detector's whole-document 50-char
# threshold, since one page legitimately holds less content than a whole-doc
# sum).
PDF_HYBRID_PAGE_TEXT_LAYER_MIN_CHARS = 20


def extract(path: str | Path, source_type: str) -> tuple[str, list[WordBbox], dict]:
    """
    Returns (full_text, word_bboxes, meta).

    For source_type == "text":
      - Read file bytes, call validate_encoding
      - Return (decoded_text, [], {})  # no bboxes for plain text

    For source_type == "pdf_text":
      - Use pdfplumber to extract text page by page
      - For each word: create WordBbox(text, page_num, x0, top, width, height)
        pdfplumber word dict keys: "text", "page_number" (1-based), "x0", "top", "x1", "bottom"
        width = x1 - x0; height = bottom - top
      - Join all pages with "\n\n"
      - If pdfplumber extraction fails or returns empty string:
        fallback to pypdfium2:
          for each page: page.get_textpage().get_text_range() for text, and
          per-character boxes stitched into word-level WordBbox entries.
      - Return (full_text, word_bboxes, {})

    For source_type == "pdf_hybrid":
      - Per-page: pages with a real text layer are extracted directly (same
        as pdf_text); pages that are image-only are OCR'd via ocr_processor.py.
      - Raises OCRUnavailableError if the OCR dependencies (requirements-ocr.txt)
        aren't installed.
      - Returns (full_text, word_bboxes, meta) where meta carries
        ocr_confidence / human_review / pages_ocred / pages_text_layer / warnings.
    """
    path = Path(path)

    if source_type == "text":
        raw = path.read_bytes()
        text = validate_encoding(raw)
        return text, [], {}

    if source_type == "pdf_text":
        text, word_bboxes = _extract_pdf_text(path)
        return text, word_bboxes, {}

    if source_type == "pdf_hybrid":
        return _extract_pdf_hybrid(path)

    raise ValueError(f"Unknown source_type: {source_type!r}")


def _extract_pdf_text(path: Path) -> tuple[str, list[WordBbox]]:
    """Extract text and bboxes from a text-layer PDF using pdfplumber with pypdfium2 fallback."""
    try:
        import pdfplumber

        page_texts: list[str] = []
        word_bboxes: list[WordBbox] = []

        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_num = page.page_number  # 1-based
                page_text = page.extract_text() or ""
                page_texts.append(page_text)

                words = page.extract_words()
                for w in words:
                    x0 = w["x0"]
                    top = w["top"]
                    x1 = w["x1"]
                    bottom = w["bottom"]
                    word_bboxes.append(
                        WordBbox(
                            text=w["text"],
                            page=page_num,
                            x=x0,
                            y=top,
                            width=x1 - x0,
                            height=bottom - top,
                        )
                    )

        full_text = "\n\n".join(page_texts)
        if full_text.strip():
            return full_text, word_bboxes

        # pdfplumber returned empty — fall through to pypdfium2
    except Exception:
        pass  # fall through to pypdfium2

    return _extract_pdf_pypdfium2(path)


def _extract_page_text_layer(page, page_num: int) -> tuple[str, list[WordBbox]]:
    """Extract a single pypdfium2 page's text layer as (page_text, word_bboxes).

    pypdfium2 has no built-in word tokenizer, so words are reconstructed by
    grouping consecutive non-whitespace characters using per-character boxes
    (get_charbox), then converting from PDF's bottom-left origin to the
    top-left origin used elsewhere (pdfplumber's "top" convention).
    """
    textpage = page.get_textpage()
    try:
        raw_text = textpage.get_text_range()
        page_height = page.get_size()[1]
        n_chars = textpage.count_chars()

        word_bboxes: list[WordBbox] = []
        cur_chars: list[str] = []
        cur_box: list[float] | None = None  # [left, top, right, bottom]

        def _flush():
            if cur_chars and cur_box is not None:
                word_bboxes.append(
                    WordBbox(
                        text="".join(cur_chars),
                        page=page_num,
                        x=cur_box[0],
                        y=cur_box[1],
                        width=cur_box[2] - cur_box[0],
                        height=cur_box[3] - cur_box[1],
                    )
                )

        for i in range(n_chars):
            ch = raw_text[i]
            if ch.isspace():
                _flush()
                cur_chars = []
                cur_box = None
                continue

            left, bottom, right, top = textpage.get_charbox(i)
            # Convert to top-origin: y = distance from page top.
            box_top = page_height - top
            box_bottom = page_height - bottom

            cur_chars.append(ch)
            if cur_box is None:
                cur_box = [left, box_top, right, box_bottom]
            else:
                cur_box[0] = min(cur_box[0], left)
                cur_box[1] = min(cur_box[1], box_top)
                cur_box[2] = max(cur_box[2], right)
                cur_box[3] = max(cur_box[3], box_bottom)

        _flush()
        return raw_text.replace("\r\n", "\n"), word_bboxes
    finally:
        textpage.close()


def _extract_pdf_pypdfium2(path: Path) -> tuple[str, list[WordBbox]]:
    """Fallback: extract text and bboxes using pypdfium2."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    page_texts: list[str] = []
    word_bboxes: list[WordBbox] = []

    try:
        for page_num, page in enumerate(doc, start=1):
            page_text, page_bboxes = _extract_page_text_layer(page, page_num)
            page_texts.append(page_text)
            word_bboxes.extend(page_bboxes)
    finally:
        doc.close()

    full_text = "\n\n".join(page_texts)
    return full_text, word_bboxes


def _extract_pdf_hybrid(path: Path) -> tuple[str, list[WordBbox], dict]:
    """Extract a mixed/scanned PDF, OCR-ing only the pages that have no text layer."""
    from pii_redactor.ingest import ocr_processor

    if not ocr_processor.is_available():
        raise ocr_processor.OCRUnavailableError(
            "This PDF has pages without a text layer and cannot be read "
            "without OCR. Run: pip install -r requirements-ocr.txt"
        )

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    page_texts: list[str] = []
    word_bboxes: list[WordBbox] = []
    pages_ocred: list[int] = []
    pages_text_layer: list[int] = []
    warnings: list[str] = []
    confidences: list[float] = []
    human_review_any = False

    try:
        for page_num, page in enumerate(doc, start=1):
            text, bboxes = _extract_page_text_layer(page, page_num)
            if len(text.strip()) >= PDF_HYBRID_PAGE_TEXT_LAYER_MIN_CHARS:
                pages_text_layer.append(page_num)
            else:
                result = ocr_processor.ocr_page(page, page_num)
                text, bboxes = result.text, result.words
                pages_ocred.append(page_num)
                confidences.append(result.confidence)
                if result.human_review:
                    human_review_any = True
                    warnings.append(
                        f"page {page_num}: low OCR confidence after {result.attempts} attempt(s)"
                    )
            page_texts.append(text)
            word_bboxes.extend(bboxes)
    finally:
        doc.close()

    full_text = "\n\n".join(page_texts)
    meta = {
        "ocr_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        "human_review": human_review_any,
        "pages_ocred": pages_ocred,
        "pages_text_layer": pages_text_layer,
        "warnings": warnings,
    }
    return full_text, word_bboxes, meta
