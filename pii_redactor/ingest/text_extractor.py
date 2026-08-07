"""Text extraction from documents."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pii_redactor.ingest.file_detector import (
    PAGE_TEXT_LAYER_MIN_CHARS,
    page_needs_ocr,
    validate_encoding,
)
from pii_redactor.models import WordBbox
from pii_redactor.safe_errors import discard_exception_graph

_PDF_PAGE_SEPARATOR = "\n\n"
_PDF_PROVENANCE_ERROR = "PDF source provenance could not be established safely"
_OCR_UNAVAILABLE_ERROR = (
    "This PDF has pages without a text layer and cannot be read without OCR. "
    "Run: pip install -r requirements-ocr.txt"
)


class _PdfSourceProvenanceError(RuntimeError):
    """Raised when extracted text cannot be tied to trustworthy geometry."""


def _join_pdf_pages(
    page_payloads: list[tuple[str, list[WordBbox]]],
) -> tuple[str, list[WordBbox], list[int]]:
    """Join page text and shift page-local source spans into document offsets."""
    page_offsets: list[int] = []
    shifted_boxes: list[WordBbox] = []
    offset = 0

    for page_index, (page_text, page_boxes) in enumerate(page_payloads):
        page_offsets.append(offset)
        for box in page_boxes:
            span = box.source_span
            if not isinstance(span, tuple) or len(span) != 2:
                raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR)
            start, end = span
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end <= start
                or end > len(page_text)
                or page_text[start:end] != box.text
            ):
                raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR)
            shifted_boxes.append(replace(box, source_span=(offset + start, offset + end)))
        offset += len(page_text)
        if page_index + 1 < len(page_payloads):
            offset += len(_PDF_PAGE_SEPARATOR)

    return (
        _PDF_PAGE_SEPARATOR.join(page_text for page_text, _boxes in page_payloads),
        shifted_boxes,
        page_offsets,
    )


def _extract_pdfplumber_page(page, page_num: int) -> tuple[str, list[WordBbox]]:
    """Build text and boxes from pdfplumber's authoritative character map."""
    text_map = page.get_textmap()
    page_text = text_map.as_string
    tuples = list(text_map.tuples)
    if any(not isinstance(char, str) or len(char) != 1 for char, _obj in tuples):
        raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR)
    if "".join(char for char, _obj in tuples) != page_text:
        raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR)

    word_bboxes: list[WordBbox] = []
    cur_chars: list[str] = []
    cur_start: int | None = None
    cur_box: list[float] | None = None

    def flush(end: int) -> None:
        if cur_chars and cur_start is not None and cur_box is not None:
            word_bboxes.append(
                WordBbox(
                    text="".join(cur_chars),
                    page=page_num,
                    x=cur_box[0],
                    y=cur_box[1],
                    width=cur_box[2] - cur_box[0],
                    height=cur_box[3] - cur_box[1],
                    source_span=(cur_start, end),
                )
            )

    for index, (char, source_char) in enumerate(tuples):
        if char.isspace():
            flush(index)
            cur_chars = []
            cur_start = None
            cur_box = None
            continue
        if source_char is None:
            raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR)
        try:
            x0 = float(source_char["x0"])
            top = float(source_char["top"])
            x1 = float(source_char["x1"])
            bottom = float(source_char["bottom"])
        except Exception as error:
            discard_exception_graph(error)
            raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR) from None

        cur_chars.append(char)
        if cur_start is None:
            cur_start = index
        if cur_box is None:
            cur_box = [x0, top, x1, bottom]
        else:
            cur_box[0] = min(cur_box[0], x0)
            cur_box[1] = min(cur_box[1], top)
            cur_box[2] = max(cur_box[2], x1)
            cur_box[3] = max(cur_box[3], bottom)

    flush(len(page_text))
    return page_text, word_bboxes


def extract(path: str | Path, source_type: str) -> tuple[str, list[WordBbox], dict]:
    """
    Returns (full_text, word_bboxes, meta).

    For source_type == "text":
      - Read file bytes, call validate_encoding
      - Return (decoded_text, [], {})  # no bboxes for plain text

    For source_type == "pdf_text":
      - Use pdfplumber's character-to-text map to extract text page by page
      - Every WordBbox carries its exact half-open interval in full_text
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
        ocr_confidence / human_review / human_review_pages / pages_ocred /
        pages_text_layer / warnings.
    """
    path = Path(path)

    if source_type == "text":
        raw = path.read_bytes()
        text = validate_encoding(raw)
        return text, [], {}

    if source_type == "pdf_text":
        extraction_failed = False
        try:
            text, word_bboxes = _extract_pdf_text(path)
        except Exception as error:
            discard_exception_graph(error)
            extraction_failed = True
        if extraction_failed:
            del path
            raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR) from None
        return text, word_bboxes, {}

    if source_type == "pdf_hybrid":
        from pii_redactor.ingest.ocr_processor import OCRUnavailableError

        failure_kind: str | None = None
        try:
            hybrid_result = _extract_pdf_hybrid(path)
        except OCRUnavailableError as error:
            discard_exception_graph(error)
            failure_kind = "ocr"
        except Exception as error:
            discard_exception_graph(error)
            failure_kind = "provenance"
        if failure_kind:
            del path
            if failure_kind == "ocr":
                raise OCRUnavailableError(_OCR_UNAVAILABLE_ERROR) from None
            raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR) from None
        return hybrid_result

    raise ValueError(f"Unknown source_type: {source_type!r}")


def _extract_pdf_text(path: Path) -> tuple[str, list[WordBbox]]:
    """Extract text and bboxes from a text-layer PDF using pdfplumber with pypdfium2 fallback."""
    try:
        import pdfplumber

        page_payloads: list[tuple[str, list[WordBbox]]] = []

        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_num = page.page_number  # 1-based
                page_payloads.append(_extract_pdfplumber_page(page, page_num))

        full_text, word_bboxes, _page_offsets = _join_pdf_pages(page_payloads)
        if full_text.strip():
            return full_text, word_bboxes

        # pdfplumber returned empty — fall through to pypdfium2
    except Exception as exc:
        discard_exception_graph(exc)
        # Fall through to pypdfium2.

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
        if len(raw_text) != n_chars:
            raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR)

        word_bboxes: list[WordBbox] = []
        page_chars: list[str] = []
        cur_chars: list[str] = []
        cur_start: int | None = None
        cur_box: list[float] | None = None  # [left, top, right, bottom]

        def _flush(end: int):
            if cur_chars and cur_start is not None and cur_box is not None:
                word_bboxes.append(
                    WordBbox(
                        text="".join(cur_chars),
                        page=page_num,
                        x=cur_box[0],
                        y=cur_box[1],
                        width=cur_box[2] - cur_box[0],
                        height=cur_box[3] - cur_box[1],
                        source_span=(cur_start, end),
                    )
                )

        i = 0
        while i < n_chars:
            ch = raw_text[i]
            if ch == "\r" and i + 1 < n_chars and raw_text[i + 1] == "\n":
                _flush(len(page_chars))
                cur_chars = []
                cur_start = None
                cur_box = None
                page_chars.append("\n")
                i += 2
                continue
            if ch.isspace():
                _flush(len(page_chars))
                cur_chars = []
                cur_start = None
                cur_box = None
                page_chars.append(ch)
                i += 1
                continue

            left, bottom, right, top = textpage.get_charbox(i)
            # Convert to top-origin: y = distance from page top.
            box_top = page_height - top
            box_bottom = page_height - bottom

            if cur_start is None:
                cur_start = len(page_chars)
            cur_chars.append(ch)
            page_chars.append(ch)
            if cur_box is None:
                cur_box = [left, box_top, right, box_bottom]
            else:
                cur_box[0] = min(cur_box[0], left)
                cur_box[1] = min(cur_box[1], box_top)
                cur_box[2] = max(cur_box[2], right)
                cur_box[3] = max(cur_box[3], box_bottom)
            i += 1

        _flush(len(page_chars))
        return "".join(page_chars), word_bboxes
    except _PdfSourceProvenanceError:
        raise
    except Exception as error:
        discard_exception_graph(error)
        raise _PdfSourceProvenanceError(_PDF_PROVENANCE_ERROR) from None
    finally:
        textpage.close()


def _extract_pdf_pypdfium2(path: Path) -> tuple[str, list[WordBbox]]:
    """Fallback: extract text and bboxes using pypdfium2."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    page_payloads: list[tuple[str, list[WordBbox]]] = []

    try:
        for page_num, page in enumerate(doc, start=1):
            page_text, page_bboxes = _extract_page_text_layer(page, page_num)
            page_payloads.append((page_text, page_bboxes))
    finally:
        doc.close()

    full_text, word_bboxes, _page_offsets = _join_pdf_pages(page_payloads)
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
    page_payloads: list[tuple[str, list[WordBbox], list[tuple[int, int]]]] = []
    pages_ocred: list[int] = []
    pages_text_layer: list[int] = []
    warnings: list[str] = []
    confidences: list[float] = []
    ocr_observations: list[str] = []
    human_review_pages: list[int] = []
    human_review_any = False

    try:
        for page_num, page in enumerate(doc, start=1):
            layer_text, layer_bboxes = _extract_page_text_layer(page, page_num)
            layer_chars = len(layer_text.strip())
            has_text_layer = layer_chars >= PAGE_TEXT_LAYER_MIN_CHARS
            needs_ocr = page_needs_ocr(page)
            page_parts: list[str] = []
            page_bboxes: list[WordBbox] = []
            page_ranges: list[tuple[int, int]] = []

            if layer_text.strip():
                page_parts.append(layer_text)
                page_bboxes.extend(layer_bboxes)
            if has_text_layer:
                pages_text_layer.append(page_num)

            if needs_ocr and not ocr_available:
                if not has_text_layer:
                    raise ocr_processor.OCRUnavailableError(_OCR_UNAVAILABLE_ERROR)
                needs_ocr = False
                human_review_any = True
                human_review_pages.append(page_num)
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
                    local_offset = start
                    for index, word in enumerate(ocr_words):
                        if index:
                            local_offset += 1
                        word_start = local_offset
                        local_offset += len(word.text)
                        page_bboxes.append(
                            replace(
                                word,
                                source_span=(word_start, local_offset),
                            )
                        )
                if result.human_review:
                    human_review_any = True
                    human_review_pages.append(page_num)
                    warnings.append(
                        f"page {page_num}: low OCR confidence after {result.attempts} attempt(s)"
                    )
            page_payloads.append(("\n".join(page_parts), page_bboxes, page_ranges))
    finally:
        doc.close()

    full_text, word_bboxes, page_offsets = _join_pdf_pages(
        [(text, boxes) for text, boxes, _ranges in page_payloads]
    )
    ocr_text_ranges: list[tuple[int, int]] = []
    for offset, (_page_text, _page_boxes, local_ranges) in zip(page_offsets, page_payloads):
        ocr_text_ranges.extend((offset + start, offset + end) for start, end in local_ranges)
    meta = {
        "ocr_confidence": (sum(confidences) / len(confidences)) if confidences else None,
        "human_review": human_review_any,
        "human_review_pages": human_review_pages,
        "pages_ocred": pages_ocred,
        "pages_text_layer": pages_text_layer,
        "ocr_text_ranges": ocr_text_ranges,
        "ocr_observations": ocr_observations,
        "warnings": warnings,
    }
    return full_text, word_bboxes, meta
