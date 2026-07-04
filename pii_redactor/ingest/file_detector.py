"""File type detection."""
from __future__ import annotations

from pathlib import Path


def detect_source_type(path: str | Path) -> str:
    """
    Returns: "text" | "pdf_text" | "pdf_hybrid"

    Logic:
    - If not a PDF (extension not .pdf): return "text"
    - Open with pypdfium2. For each page, count chars via its text page.
      If total chars across all pages >= 50: return "pdf_text"
      Otherwise: return "pdf_hybrid"
    - If the PDF cannot be opened: raise ValueError(f"Cannot open PDF: {path}")
    """
    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return "text"

    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(path))
        total_chars = 0
        try:
            for page in doc:
                textpage = page.get_textpage()
                try:
                    total_chars += textpage.count_chars()
                finally:
                    textpage.close()
        finally:
            doc.close()
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {path}") from exc

    if total_chars >= 50:
        return "pdf_text"
    return "pdf_hybrid"


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
