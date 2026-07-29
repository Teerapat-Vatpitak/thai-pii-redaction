"""Generate examples/sample_document.pdf — a Thai document with (fake) PII for
trying the True PDF redaction flow.

Run:  python examples/make_sample_pdf.py
Uses the Sarabun font if found; otherwise Thai glyphs may not render (the
committed sample_document.pdf is already generated with Sarabun).

This file draws Thai with a raw `drawString`, and it is going to keep doing
that. `tests/test_thai_shaping.py` forbids exactly this in every module that
authors a PDF for a USER — report_pdf.py, exporter.py, receipt_pdf.py — and
exempts this one on purpose. The exemption was re-examined on 2026-07-29 and
kept, because routing this through `thai_pdf_text.draw_text()` breaks the
fixture at its actual job:

`draw_text` writes an affected line twice, an invisible real-character layer
under the visible shaped one. pypdfium2 returns those sequentially, but
pdfplumber orders by coordinate, so it interleaves them — "081-234-5678" comes
back as "008811--223344--55667788", which no phone regex will ever match. And
`ingest/text_extractor.py` reads PDFs with pdfplumber first; pypdfium2 is only
the fallback. Measured: detection on the regenerated fixture drops from 13
entities to 9, losing PHONE, EMAIL, POSTAL_CODE and DATE, and every word bbox
for the targeted words disappears.

So the trade is real but one-sided. What is wrong here is the appearance of
tone marks in a document the tool INGESTS — a scanned-looking input with
slightly wrong glyphs is a perfectly good test input, and arguably a more
realistic one. What would be wrong after "fixing" it is the fixture no longer
exercising the path it exists to exercise. If the rendering ever needs to be
correct too, the fix belongs upstream in reportlab's ToUnicode CMap for
substituted glyphs, not here.
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# All PII below is fabricated for demo purposes only.
LINES = [
    "หนังสือยินยอมให้ประมวลผลข้อมูลส่วนบุคคล",
    "",
    "ชื่อ-นามสกุล: สมชาย ใจดี",
    "เลขบัตรประชาชน: 3-1009-02845-17-2",
    "เบอร์โทรศัพท์: 081-234-5678",
    "อีเมล: somchai.j@example.co.th",
    "เลขที่บัญชี: 123-4-56789-0",
    "ที่อยู่: 99 ถนนพหลโยธิน แขวงจตุจักร กรุงเทพฯ 10900",
    "",
    "ข้าพเจ้ายินยอมให้เก็บรวบรวมและใช้ข้อมูลข้างต้นตามวัตถุประสงค์ที่แจ้งไว้",
]

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\sarabun-v17-latin_latin-ext_thai_vietnamese-regular.ttf",
    "/usr/share/fonts/truetype/thai/Sarabun-Regular.ttf",
]


def main() -> None:
    out = Path(__file__).parent / "sample_document.pdf"
    font_path = next((f for f in _FONT_CANDIDATES if Path(f).exists()), None)

    font_name = "Helvetica"  # latin-only fallback
    if font_path:
        font_name = "Sarabun"
        pdfmetrics.registerFont(TTFont(font_name, font_path))

    c = canvas.Canvas(str(out), pagesize=letter)
    page_width, page_height = letter
    c.setFont(font_name, 14)

    y = page_height - 72
    for line in LINES:
        if line:
            c.drawString(72, y, line)
        y -= 28

    c.save()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
