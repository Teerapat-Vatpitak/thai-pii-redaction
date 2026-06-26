"""Text extraction from documents."""
from __future__ import annotations

from pathlib import Path

from pii_redactor.ingest.file_detector import validate_encoding
from pii_redactor.models import WordBbox


def extract(path: str | Path, source_type: str) -> tuple[str, list[WordBbox]]:
    """
    Returns (full_text, word_bboxes).

    For source_type == "text":
      - Read file bytes, call validate_encoding
      - Return (decoded_text, [])  # no bboxes for plain text

    For source_type == "pdf_text":
      - Use pdfplumber to extract text page by page
      - For each word: create WordBbox(text, page_num, x0, top, width, height)
        pdfplumber word dict keys: "text", "page_number" (1-based), "x0", "top", "x1", "bottom"
        width = x1 - x0; height = bottom - top
      - Join all pages with "\n\n"
      - If pdfplumber extraction fails or returns empty string:
        fallback to PyMuPDF (fitz):
          for each page: page.get_text("words") returns (x0,y0,x1,y1,word,block,line,word_num)
          Create WordBbox(text=word[4], page=page_num, x=word[0], y=word[1],
                         width=word[2]-word[0], height=word[3]-word[1])
      - Return (full_text, word_bboxes)

    For source_type == "pdf_hybrid":
      - This is handled by ocr_processor.py (Task later).
      - Raise NotImplementedError
    """
    path = Path(path)

    if source_type == "text":
        raw = path.read_bytes()
        text = validate_encoding(raw)
        return text, []

    if source_type == "pdf_text":
        return _extract_pdf_text(path)

    if source_type == "pdf_hybrid":
        raise NotImplementedError(
            "OCR processing not yet implemented; use pdf_text or text"
        )

    raise ValueError(f"Unknown source_type: {source_type!r}")


def _extract_pdf_text(path: Path) -> tuple[str, list[WordBbox]]:
    """Extract text and bboxes from a text-layer PDF using pdfplumber with PyMuPDF fallback."""
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

        # pdfplumber returned empty — fall through to PyMuPDF
    except Exception:
        pass  # fall through to PyMuPDF

    return _extract_pdf_fitz(path)


def _extract_pdf_fitz(path: Path) -> tuple[str, list[WordBbox]]:
    """Fallback: extract text and bboxes using PyMuPDF (fitz)."""
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    page_texts: list[str] = []
    word_bboxes: list[WordBbox] = []

    for page_num, page in enumerate(doc, start=1):
        page_texts.append(page.get_text())
        for word in page.get_text("words"):
            # word tuple: (x0, y0, x1, y1, "text", block_no, line_no, word_no)
            word_bboxes.append(
                WordBbox(
                    text=word[4],
                    page=page_num,
                    x=word[0],
                    y=word[1],
                    width=word[2] - word[0],
                    height=word[3] - word[1],
                )
            )

    doc.close()
    full_text = "\n\n".join(page_texts)
    return full_text, word_bboxes
