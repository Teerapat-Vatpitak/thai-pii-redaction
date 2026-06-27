"""Generate examples/sample_document.pdf — a Thai document with (fake) PII for
trying the True PDF redaction flow.

Run:  python examples/make_sample_pdf.py
Uses the Sarabun font if found; otherwise Thai glyphs may not render (the
committed sample_document.pdf is already generated with Sarabun).
"""
from pathlib import Path

import fitz  # PyMuPDF

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
    font = next((f for f in _FONT_CANDIDATES if Path(f).exists()), None)

    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in LINES:
        if line:
            if font:
                page.insert_text((72, y), line, fontfile=font, fontname="sarabun", fontsize=14)
            else:
                page.insert_text((72, y), line, fontsize=14)  # latin-only fallback
        y += 28
    doc.save(str(out))
    doc.close()
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
