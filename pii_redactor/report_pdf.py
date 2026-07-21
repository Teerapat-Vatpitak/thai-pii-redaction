"""PDPA risk report rendered as a PDF (feature D — "สิ่งที่องค์กรซื้อคือหลักฐาน").

Renders the /api/analyze result dict. PII-free BY WHITELIST: only the fields
drawn here — scores, grades, counts, data-type labels, category names and the
canned recommendation strings — ever reach the canvas. No raw source text, no
entity values, no keyword excerpts (section26 entries carry a "keyword" field;
this module reads only "category"). Long lines are clipped at the right
margin rather than wrapped — accepted for v1, the content is short labels.
"""

from __future__ import annotations

import datetime as _dt
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pii_redactor.exporter import _register_thai_font

_TYPE_LABELS = {
    "NAME": "ชื่อบุคคล",
    "THAI_ID": "เลขบัตรประชาชน",
    "PHONE": "เบอร์โทรศัพท์",
    "EMAIL": "อีเมล",
    "ADDRESS": "ที่อยู่",
    "LOCATION": "สถานที่",
    "DATE": "วันที่",
    "DATE_OF_BIRTH": "วันเกิด",
    "ORGANIZATION": "องค์กร",
    "BANK_ACCOUNT": "เลขบัญชีธนาคาร",
    "CREDIT_CARD": "บัตรเครดิต",
    "PASSPORT": "หนังสือเดินทาง",
    "ID_NUMBER": "เลขอ้างอิง",
    "STUDENT_ID": "รหัสนักศึกษา",
    "VEHICLE_PLATE": "ทะเบียนรถ",
    "IBAN": "IBAN",
    "MEDICAL_ID": "เลขเวชระเบียน",
    "POSTAL_CODE": "รหัสไปรษณีย์",
}

# ถอดจากใบสมัครส่วนที่ 6 — เอกสารต้องซื่อสัตย์แบบเดียวกับตัวระบบ
_LIMITATIONS = [
    "ข้อจำกัดของระบบ",
    "การตรวจจับไม่มีทางครบถ้วนร้อยเปอร์เซ็นต์ แม้ระบบออกแบบให้เอนไปทางจับเกินแล้วก็ตาม",
    "งานที่ความเสี่ยงสูงควรมีมนุษย์ตรวจทานขั้นสุดท้ายเสมอ ข้อมูลอ่อนไหวตามมาตรา 26",
    "ระบบแจ้งเป็นธงให้ผู้ใช้ตัดสินใจ ไม่ปกปิดอัตโนมัติ ภาษาที่รองรับคือไทยเป็นหลัก อังกฤษเป็นรอง",
]


def render_pdpa_report(
    analysis: dict,
    *,
    version: str,
    source_sha256_12: str,
    generated_at: str | None = None,
) -> bytes:
    """Draw the analysis dict onto an A4 PDF and return its bytes."""
    font = _register_thai_font()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _width, height = A4
    y = height - 56

    def line(txt: str, size: int = 11, dy: int = 16) -> None:
        nonlocal y
        if y < 60:
            c.showPage()
            y = height - 56
        c.setFont(font, size)
        c.drawString(56, y, txt)
        y -= dy

    when = generated_at or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    line("AI Guard — รายงานความเสี่ยงข้อมูลส่วนบุคคล (PDPA)", 17, 26)
    line(f"เวอร์ชันระบบ {version}   ออกรายงาน {when}   รหัสอ้างอิงเอกสาร {source_sha256_12}", 9, 22)

    line(
        f"คะแนนความเสี่ยงรวม {analysis['overall_score']:.0f}/100   เกรด {analysis['overall_grade']}",
        15,
        22,
    )
    line(f"ระดับความเสี่ยง {analysis['risk_label']}", 11, 22)

    line("ข้อมูลส่วนบุคคลที่พบ แยกตามชนิด", 13, 20)
    if analysis["breakdown"]:
        for row in analysis["breakdown"]:
            label = _TYPE_LABELS.get(row["data_type"], row["data_type"])
            line(f"- {label}  {row['count']} รายการ  (ชั้นตรวจ {row['redact_type']})")
    else:
        line("ไม่พบ")

    line("ข้อมูลอ่อนไหวตามมาตรา 26 (แจ้งธง ไม่ปกปิดอัตโนมัติ)", 13, 20)
    if analysis["section26"]:
        counts: dict[str, int] = {}
        for s in analysis["section26"]:
            counts[s["category"]] = counts.get(s["category"], 0) + 1
        for cat, n in counts.items():
            line(f"- {cat}  {n} จุด")
    else:
        line("ไม่พบ")

    reid = analysis["reid"]
    line("ความเสี่ยงการระบุตัวตนซ้ำจากข้อมูลแวดล้อม", 13, 20)
    line(f"คะแนน {reid['score']:.0f}/100  เกรด {reid['grade']}")
    if reid["qi_found"]:
        line(f"ตัวบ่งชี้แวดล้อมที่พบ: {', '.join(reid['qi_found'])}")
    if reid["high_risk_combo"]:
        line("พบชุดข้อมูล เพศ + เขตพื้นที่ + วันเกิด/อายุ ซึ่งเสี่ยงระบุตัวบุคคลได้แม้ไม่มี PII ตรง")

    line("ข้อเสนอแนะ", 13, 20)
    for rec in analysis["recommendations"]:
        line(f"[{rec['level']}] {rec['title']}", 11, 15)
        line(f"    {rec['desc']}", 9, 15)

    y = min(y, 140)
    for i, seg in enumerate(_LIMITATIONS):
        line(seg, 12 if i == 0 else 8, 18 if i == 0 else 12)

    c.showPage()
    c.save()
    return buf.getvalue()
