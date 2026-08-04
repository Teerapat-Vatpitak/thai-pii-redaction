"""Text extraction from documents."""

from __future__ import annotations

from pathlib import Path

from pii_redactor.ingest.file_detector import (
    PAGE_TEXT_LAYER_MIN_CHARS,
    page_needs_ocr,
    validate_encoding,
)
from pii_redactor.models import WordBbox


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
      - Per-page: keep selectable text and also OCR every raster page. Mixed
        pages merge both sources so a text overlay cannot hide image-only PII.
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


def _remove_layer_text(word: WordBbox, layer_words: list[WordBbox]) -> WordBbox | None:
    """Remove selectable text that OCR read again."""

    def view(value: str) -> tuple[str, list[int]]:
        chars = []
        positions = []
        for index, char in enumerate(value.casefold()):
            if char.isalnum():
                chars.append(char)
                positions.append(index)
        return "".join(chars), positions

    overlaps = []
    for layer_word in layer_words:
        if layer_word.page != word.page:
            continue
        left = max(word.x, layer_word.x)
        top = max(word.y, layer_word.y)
        right = min(word.x + word.width, layer_word.x + layer_word.width)
        bottom = min(word.y + word.height, layer_word.y + layer_word.height)
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        word_area = max(0.0, word.width) * max(0.0, word.height)
        layer_area = max(0.0, layer_word.width) * max(0.0, layer_word.height)
        smaller_area = min(word_area, layer_area)
        if smaller_area and intersection / smaller_area >= 0.5:
            overlaps.append(layer_word)
    if not overlaps:
        return word
    layer_text = "".join(item.text for item in sorted(overlaps, key=lambda item: item.x))
    layer_clean, _layer_positions = view(layer_text)
    word_clean, word_positions = view(word.text)
    start = word_clean.find(layer_clean) if layer_clean else -1
    if start < 0:
        return word

    from pii_redactor.detectors.fn_scanner import scan_fn
    from pii_redactor.detectors.fp_detector import detect_fp
    from pii_redactor.ingest.text_cleaner import clean_length_preserving

    def structured(value: str) -> set[tuple[str, str]]:
        clean_value = clean_length_preserving(value)
        entities = detect_fp(clean_value)
        entities.extend(scan_fn(clean_value, entities))
        return {(entity.data_type, entity.original_text.casefold().strip()) for entity in entities}

    word_keys = structured(word.text)
    layer_keys = structured(layer_text)
    if word_keys:
        if not word_keys <= layer_keys:
            return word
    elif word_clean != layer_clean:
        return word

    source_start = word_positions[start]
    source_end = word_positions[start + len(layer_clean) - 1] + 1
    remaining = f"{word.text[:source_start]} {word.text[source_end:]}".strip()
    if not any(char.isalnum() for char in remaining):
        return None
    return WordBbox(
        text=remaining,
        page=word.page,
        x=word.x,
        y=word.y,
        width=word.width,
        height=word.height,
    )


def _extract_pdf_hybrid(path: Path) -> tuple[str, list[WordBbox], dict]:
    """Extract text layers and OCR every raster page."""
    from pii_redactor.ingest import ocr_processor

    # Routing sends a page here as soon as it carries a raster image, even one
    # sitting beside a full text layer (a letterhead logo). Refusing the whole
    # document when the OCR extra is missing would take PDF redaction away from
    # every core-only install — including the packaged exe, which ships without
    # requirements-ocr.txt — for documents it used to read fine. So the refusal
    # is made per page and only where it is true: a raster page with no usable
    # text layer really cannot be read, while one that has a text layer falls
    # back to it, loudly (warning + human_review), because whatever the image
    # holds stays unread.
    ocr_available = ocr_processor.is_available()

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    page_payloads: list[tuple[str, list[tuple[int, int]]]] = []
    word_bboxes: list[WordBbox] = []
    pages_ocred: list[int] = []
    pages_text_layer: list[int] = []
    warnings: list[str] = []
    confidences: list[float] = []
    ocr_observations: list[str] = []
    human_review_any = False

    try:
        for page_num, page in enumerate(doc, start=1):
            layer_text, layer_bboxes = _extract_page_text_layer(page, page_num)
            layer_chars = len(layer_text.strip())
            has_text_layer = layer_chars >= PAGE_TEXT_LAYER_MIN_CHARS
            needs_ocr = page_needs_ocr(page)
            page_parts: list[str] = []
            page_ranges: list[tuple[int, int]] = []

            if layer_text.strip():
                page_parts.append(layer_text)
                word_bboxes.extend(layer_bboxes)
            if has_text_layer:
                pages_text_layer.append(page_num)

            if needs_ocr and not ocr_available:
                if not has_text_layer:
                    raise ocr_processor.OCRUnavailableError(
                        "This PDF has pages without a text layer and cannot be read "
                        "without OCR. Run: pip install -r requirements-ocr.txt"
                    )
                needs_ocr = False
                human_review_any = True
                warnings.append(
                    f"page {page_num}: an image on this page was not read because OCR is "
                    "not installed; only its text layer was extracted"
                )

            if needs_ocr:
                result = ocr_processor.ocr_page(page, page_num)
                warnings.extend(result.warnings)
                pages_ocred.append(page_num)
                confidences.append(result.confidence)
                ocr_observations.append(result.text)
                ocr_words = [
                    kept
                    for word in result.words
                    if (kept := _remove_layer_text(word, layer_bboxes)) is not None
                ]
                ocr_text = "\n".join(word.text for word in ocr_words)
                if ocr_text.strip():
                    start = sum(len(part) for part in page_parts) + len(page_parts)
                    page_parts.append(ocr_text)
                    page_ranges.append((start, start + len(ocr_text)))
                word_bboxes.extend(result.words)
                if result.human_review:
                    human_review_any = True
                    warnings.append(
                        f"page {page_num}: low OCR confidence after {result.attempts} attempt(s)"
                    )
            page_payloads.append(("\n".join(page_parts), page_ranges))
    finally:
        doc.close()

    page_texts: list[str] = []
    ocr_text_ranges: list[tuple[int, int]] = []
    offset = 0
    for page_text, local_ranges in page_payloads:
        page_texts.append(page_text)
        ocr_text_ranges.extend((offset + start, offset + end) for start, end in local_ranges)
        offset += len(page_text) + 2
    full_text = "\n\n".join(page_texts)
    meta = {
        "ocr_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        "human_review": human_review_any,
        "pages_ocred": pages_ocred,
        "pages_text_layer": pages_text_layer,
        "ocr_text_ranges": ocr_text_ranges,
        "ocr_observations": ocr_observations,
        "warnings": warnings,
    }
    return full_text, word_bboxes, meta
