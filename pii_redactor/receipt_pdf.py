"""The processing receipt rendered as a PDF slip.

Same whitelist discipline as `report_pdf.py`: this module is handed a receipt
dict, and a receipt dict has no PII in it to begin with (see `receipt.py`), so
the PII-free property is structural rather than a filter applied here. What it
draws is counts, type labels, hashes and the operator's own declarations.

The slip carries its own verification command. A compliance artifact that can
be checked but does not say how gets filed and never checked.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# One label vocabulary for both PDF surfaces. Duplicating the map would let the
# receipt and the risk report call the same data type two different things in
# two documents about the same run.
from pii_redactor.report_pdf import _TYPE_LABELS
from pii_redactor.thai_pdf_text import draw_text, register_thai_font

_OPERATION_LABELS = {
    "detect": "ตรวจหาข้อมูลส่วนบุคคล",
    "mask": "ตรวจหาและแทนที่ด้วยนามแฝง",
    "redact": "ตรวจหาและปิดทับถาวร",
}

_NOTES = [
    "ข้อจำกัดและวิธีอ่านใบนี้",
    "ใบนี้บันทึกการประมวลผลหนึ่งครั้ง ไม่ใช่ทะเบียนสะสม และไม่มีค่าข้อมูลส่วนบุคคลใดอยู่ในเอกสาร",
    "ความถูกต้องยืนยันด้วยการรันซ้ำ ไม่ใช่ลายเซ็นดิจิทัล ถ้าเวอร์ชันระบบหรือ engine เปลี่ยน ผลอาจต่างจากเดิม",
    "การตรวจจับไม่ครบถ้วนร้อยเปอร์เซ็นต์ จำนวนที่พบคือสิ่งที่ระบบเห็น ไม่ใช่สิ่งที่มีอยู่ทั้งหมด",
    "หัวข้อผู้ควบคุมข้อมูลและวัตถุประสงค์มาจากผู้ใช้ ระบบไม่เติมให้เอง",
]


def render_receipt(receipt: dict) -> bytes:
    """Draw one receipt onto an A4 page and return its bytes."""
    font = register_thai_font()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _width, height = A4
    y = height - 56

    def line(txt: str, size: int = 11, dy: int = 16) -> None:
        nonlocal y
        if y < 60:
            c.showPage()
            y = height - 56
        draw_text(c, 56, y, txt, font, size)
        y -= dy

    activity = receipt["activity"]
    source = receipt["source"]
    result = receipt["result"]
    environment = receipt["environment"]

    line("AI Guard — ใบรับรองการประมวลผลข้อมูลส่วนบุคคล", 17, 24)
    line("บันทึกรายการกิจกรรมการประมวลผล ตาม พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล มาตรา 39", 10, 24)

    line("รายการที่ทำ", 13, 18)
    operation = activity["operation"]
    line(f"- ประเภทการประมวลผล  {_OPERATION_LABELS.get(operation, operation)}")
    line(f"- เวลาที่ออกใบ  {receipt['issued_at']}")
    line(f"- วัตถุประสงค์  {activity.get('purpose', 'ผู้ใช้ไม่ได้ระบุ')}")
    line(f"- ผู้ควบคุมข้อมูล  {activity.get('controller', 'ผู้ใช้ไม่ได้ระบุ')}", dy=22)

    line("เอกสารต้นทาง", 13, 18)
    line(f"- ชนิดที่ระบบตรวจได้  {source['source_type']}   ขนาด {source['bytes']} ไบต์")
    line("- ค่าแฮชของไฟล์ (SHA-256)", dy=13)
    line(f"  {source['sha256']}", 8, 22)

    line("สิ่งที่ตรวจพบ", 13, 18)
    line(
        f"- จำนวนรวม {result['entity_count']} รายการ "
        f"(ชั้นตรวจแบบรูปแบบ {result['fp_count']}  ชั้นตรวจแบบข้อความ {result['tb_count']})"
    )
    if result["type_counts"]:
        for data_type, count in result["type_counts"].items():
            line(f"  - {_TYPE_LABELS.get(data_type, data_type)}  {count} รายการ", 10, 14)
    else:
        line("  - ไม่พบข้อมูลส่วนบุคคล", 10, 14)
    line("- ค่าแฮชของผลการตรวจ", dy=13)
    line(f"  {result['digest']}", 8, 22)

    line("สภาพแวดล้อมที่ใช้ประมวลผล", 13, 18)
    line(f"- เวอร์ชันระบบ  {environment['product_version']}")
    line(f"- เครื่องมือรู้จำชื่อเฉพาะ  {environment['ner_engine']}", dy=22)

    line("วิธีตรวจสอบใบนี้", 13, 18)
    line("รันคำสั่งนี้กับไฟล์ต้นฉบับที่เก็บไว้ ระบบจะประมวลผลซ้ำแล้วเทียบค่าแฮชทั้งสองค่า", 10, 14)
    line("  python ai_guard.py receipt verify <ไฟล์ใบรับรอง .json> <ไฟล์ต้นฉบับ>", 9, 22)

    y = min(y, 150)
    for i, note in enumerate(_NOTES):
        line(note, 12 if i == 0 else 8, 18 if i == 0 else 12)

    c.showPage()
    c.save()
    return buf.getvalue()
