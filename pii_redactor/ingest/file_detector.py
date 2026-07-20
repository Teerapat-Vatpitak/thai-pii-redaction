"""File type detection."""

from __future__ import annotations

from pathlib import Path

# A page with at least this many text-layer characters is treated as having a
# real text layer. Mirrors text_extractor.PDF_HYBRID_PAGE_TEXT_LAYER_MIN_CHARS
# (the per-page threshold the hybrid extractor uses to decide text vs OCR); the
# two must agree so a page classified image-only here is actually OCR'd there.
PAGE_TEXT_LAYER_MIN_CHARS = 20


def _page_is_image_only(page) -> bool:
    """True if the page carries a raster image but (almost) no text layer.

    This is the signal for a scanned page that needs OCR, distinct from a
    genuinely blank page (no text AND no image) which has nothing to extract.
    If the page objects can't be inspected, err toward True: a low-text page we
    cannot vet is treated as needing OCR rather than silently yielding no text.
    """
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
    - Open with pypdfium2 and classify PER PAGE (not by a whole-document char
      total, which let a mostly-scanned PDF with one text page pass as
      pdf_text and silently drop its scanned pages). A page with a real text
      layer (>= PAGE_TEXT_LAYER_MIN_CHARS chars) is fine; a page with little or
      no text but a raster image is image-only and forces "pdf_hybrid" so the
      extractor OCRs it. A blank page (no text, no image) forces nothing.
      Return "pdf_hybrid" if any page is image-only, else "pdf_text".
    - If the PDF cannot be opened: raise ValueError(f"Cannot open PDF: {path}")
    """
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return "text"

    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        has_image_only_page = False
        try:
            for page in doc:
                textpage = page.get_textpage()
                try:
                    n_chars = textpage.count_chars()
                finally:
                    textpage.close()
                if n_chars >= PAGE_TEXT_LAYER_MIN_CHARS:
                    continue
                if _page_is_image_only(page):
                    has_image_only_page = True
                    break
        finally:
            doc.close()
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {path}") from exc

    return "pdf_hybrid" if has_image_only_page else "pdf_text"


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
