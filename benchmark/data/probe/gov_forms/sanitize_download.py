"""Make a page-only PDF copy of an official download.

The new file keeps the visible pages. It drops source metadata, links, forms,
scripts, notes, and attachments.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def sanitize_pdf(source: str | Path, output: str | Path, *, scale: float = 1.5) -> None:
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    source = Path(source)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = pdfium.PdfDocument(str(source))
    try:
        pages = [
            (
                page.render(scale=scale).to_pil().convert("RGB"),
                tuple(float(value) for value in page.get_size()),
            )
            for page in doc
        ]
    finally:
        doc.close()

    c = canvas.Canvas(str(output), pagesize=pages[0][1], pageCompression=1, invariant=1)
    c.setAuthor("AI Guard")
    c.setCreator("AI Guard")
    c.setTitle("Sanitized official blank form")
    c.setSubject("Government-form probe source")
    for image, (width, height) in pages:
        c.setPageSize((width, height))
        c.drawImage(ImageReader(image), 0, 0, width=width, height=height)
        c.showPage()
    c.save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scale", type=float, default=1.5)
    args = parser.parse_args(argv)
    sanitize_pdf(args.source, args.output, scale=args.scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
