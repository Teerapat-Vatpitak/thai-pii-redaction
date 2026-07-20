"""Render a PDF page to PNG bytes for previews (before/after in /api/redact-pdf).

Permissively licensed: pypdfium2 (Apache/BSD).
"""

from __future__ import annotations

from io import BytesIO

import pypdfium2 as pdfium


def render_page_png(pdf_path: str, page_index: int = 0, scale: float = 2.0) -> bytes:
    """Render a single page of the PDF at `pdf_path` to PNG bytes."""
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[page_index]
        pil_image = page.render(scale=scale).to_pil()
    finally:
        doc.close()

    buf = BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()
