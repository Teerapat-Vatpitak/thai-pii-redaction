"""File type detection."""

from __future__ import annotations

from pathlib import Path

PAGE_TEXT_LAYER_MIN_CHARS = 20


def page_needs_ocr(page) -> bool:
    """Return true when a raster page needs OCR."""
    from pypdfium2 import raw as pdfium_raw

    try:
        return any(obj.type == pdfium_raw.FPDF_PAGEOBJ_IMAGE for obj in page.get_objects())
    except Exception:
        return True


def detect_source_type(path: str | Path) -> str:
    """
    Returns: "text" | "pdf_text" | "pdf_hybrid"

    Logic:
    - If not a PDF (extension not .pdf): return "text"
    - Open with pypdfium2 and inspect every page. Any raster image needs OCR,
      even when selectable text is also present.
    - If the PDF cannot be opened: raise ValueError(f"Cannot open PDF: {path}")
    """
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return "text"

    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        has_ocr_page = False
        try:
            for page in doc:
                if page_needs_ocr(page):
                    has_ocr_page = True
                    break
        finally:
            doc.close()
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {path}") from exc

    return "pdf_hybrid" if has_ocr_page else "pdf_text"


def validate_encoding(content: bytes) -> str:
    """
    Try to decode as UTF-8. If fails, try common Thai encodings (tis-620, cp874).
    Return the decoded string (always as Unicode).
    Raise ValueError if no encoding works.
    """
    for encoding in ("utf-8", "tis-620", "cp874"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("Content could not be decoded as UTF-8, tis-620, or cp874")
