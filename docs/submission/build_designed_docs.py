"""Build self-contained designed HTML for the A4 one-pager and the A1 poster.

Embeds the logo, before/after demo, and architecture diagram as base64 so each
HTML is a single portable file. Open in a browser and Print -> Save as PDF
(choose the matching paper size) to get the final document.

Run:  python docs/submission/build_designed_docs.py
Out:  docs/submission/a4.html , docs/submission/poster.html
"""
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"
OUT = Path(__file__).resolve().parent


def b64(name: str) -> str:
    data = (ASSETS / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


LOGO = b64("logo.png")
DEMO = b64("demo-before-after.png")
ARCH = b64("architecture.png")

FONT = ("@import url('https://fonts.googleapis.com/css2?"
        "family=Sarabun:wght@400;600;700&display=swap');")

BASE_CSS = f"""
{FONT}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Sarabun',sans-serif; color:#15233B; }}
.accent {{ color:#2563EB; }}
h1,h2,h3 {{ line-height:1.2; }}
.bar {{ height:6px; background:#2563EB; border-radius:3px; }}
img {{ max-width:100%; display:block; }}
.muted {{ color:#5B6B85; }}
"""

A4 = f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<style>
{BASE_CSS}
@page {{ size:A4; margin:0; }}
.page {{ width:210mm; min-height:297mm; padding:16mm 15mm; }}
.head {{ display:flex; align-items:center; gap:14px; }}
.head img {{ width:74px; }}
.title {{ font-size:25px; font-weight:700; }}
.sub {{ font-size:13.5px; color:#5B6B85; margin-top:2px; }}
.tag {{ font-size:11px; color:#2563EB; font-weight:600; margin-top:3px; }}
section {{ margin-top:13px; }}
h2 {{ font-size:15px; color:#2563EB; font-weight:700; margin-bottom:4px; }}
p {{ font-size:12.5px; line-height:1.55; }}
.demo {{ margin:8px 0; border:1px solid #E3E9F2; border-radius:10px; overflow:hidden; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
.foot {{ margin-top:14px; padding-top:8px; border-top:1px solid #E3E9F2; font-size:11px; color:#5B6B85; }}
</style></head><body>
<div class="page">
  <div class="head">
    <img src="{LOGO}">
    <div>
      <div class="title">AI Guard — ระบบปกปิดข้อมูลส่วนบุคคลภาษาไทยก่อนใช้งานปัญญาประดิษฐ์ภายนอก</div>
      <div class="sub">ปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ ChatGPT หรือ Claude แล้วคืนค่าจริงในเครื่อง เพื่อให้ข้อมูลจริงไม่ออกนอกเครื่อง สอดคล้องกับ PDPA</div>
      <div class="tag">ระดับ Prototype &nbsp;|&nbsp; PSU Future Tech Challenge 2026</div>
    </div>
  </div>
  <div class="bar" style="margin-top:10px"></div>

  <section>
    <h2>ปัญหา</h2>
    <p>คนทำงานจำนวนมากวางข้อมูลส่วนบุคคล เช่น ชื่อ เลขบัตรประชาชน เบอร์โทรศัพท์ เลขบัญชี หรือประวัติสุขภาพ ลงในบริการ AI สาธารณะเพื่อให้ช่วยทำงานเอกสาร โดยไม่ทันคิดว่าเมื่อกดส่ง ข้อมูลได้ออกนอกองค์กรไปยังเซิร์ฟเวอร์ในต่างประเทศทันทีและเรียกคืนไม่ได้ ซึ่งเสี่ยงต่อ PDPA โดยตรง โดยเฉพาะข้อมูลอ่อนไหวตามมาตรา 26</p>
  </section>

  <section>
    <h2>วิธีแก้ — ปกปิด ส่ง คืนค่า (เกิดขึ้นในเครื่องผู้ใช้)</h2>
    <p>ตรวจจับและปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI โดยแทนด้วยรหัสหรือข้อมูลปลอมที่สมจริง AI จะเห็นเพียงข้อความที่ปกปิดแล้ว เมื่อ AI ตอบกลับมา ระบบจึงคืนค่าจริงให้ในเครื่อง ใช้งานผ่านส่วนขยายเบราว์เซอร์บนหน้าจอ ChatGPT และ Claude ได้โดยตรง และยังปกปิดข้อมูลในไฟล์ PDF ได้ด้วย</p>
    <div class="demo"><img src="{DEMO}"></div>
  </section>

  <section>
    <h2>การใช้ AI</h2>
    <p>การตรวจจับใช้สองแนวทางเสริมกัน แนวทางแรกใช้กฎและการตรวจ checksum สำหรับข้อมูลที่มีรูปแบบแน่นอน เช่น เลขบัตรประชาชน เบอร์ อีเมล บัญชีธนาคาร และบัตรเครดิต ซึ่งให้ความแม่นยำสูง อีกแนวทางใช้แบบจำลอง NER ภาษาไทยจับชื่อและที่อยู่ เสริมด้วยกฎบริบทคำนำหน้า พร้อมตรวจหาข้อมูลอ่อนไหวตามมาตรา 26 ทั้งแปดหมวด ทั้งหมดประมวลผลในเครื่อง ขั้นตรวจจับไม่ส่งข้อมูลจริงให้ AI ใด</p>
  </section>

  <div class="grid2">
    <section>
      <h2>ผลลัพธ์ (ต้นแบบ)</h2>
      <p>ความเสี่ยงที่ข้อมูลจะรั่วไปยัง AI ภายนอกลดลงเกือบทั้งหมดสำหรับข้อมูลที่ตรวจจับได้ ครอบคลุมข้อมูลแบบมีรูปแบบมากกว่าสิบประเภท เสริมด้วยชื่อ ที่อยู่ และข้อมูลอ่อนไหวแปดหมวด ทดสอบใช้งานจริงครบวงจรบน Claude สำเร็จ และผ่านชุดทดสอบอัตโนมัติ 233 กรณี</p>
    </section>
    <section>
      <h2>การกำกับดูแลข้อมูล</h2>
      <p>ตารางสลับค่าอยู่ในหน่วยความจำเท่านั้น ไม่เขียนดิสก์และไม่ส่งเครือข่าย มีการสแกนซ้ำก่อนส่ง รับเฉพาะข้อความที่อยู่ในต้นฉบับจริงจึงไม่เปิดช่องให้ AI แต่งข้อมูลเพิ่ม บันทึกการทำงานไม่เก็บข้อมูลจริง และระบุข้อจำกัดเรื่องอคติของ NER ไว้ตรงไปตรงมา</p>
    </section>
  </div>

  <section>
    <h2>แนวทางต่อยอด</h2>
    <p>ระบบติดตั้งแบบ on-premise ผ่านไฟล์ติดตั้งหรือ Docker เหมาะกับโรงพยาบาล หน่วยงานราชการ และมหาวิทยาลัย วางแผนต่อยอดด้วย NER ที่แม่นขึ้น การรองรับเอกสารสแกนด้วย OCR และโหมดปกปิด PDF ที่สมบูรณ์ขึ้น โครงการเปิดเป็นโอเพนซอร์สพร้อมชุดทดสอบและเอกสารประกอบ</p>
  </section>

  <div class="foot">ทีม: [ชื่อทีม / สังกัด] &nbsp;|&nbsp; โค้ดและวิดีโอเดโม: [ลิงก์ GitHub / QR]</div>
</div>
</body></html>"""

POSTER = f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<style>
{BASE_CSS}
@page {{ size:594mm 841mm; margin:0; }}
.page {{ width:594mm; height:841mm; padding:30mm 28mm; background:#F4F7FB; }}
.head {{ display:flex; align-items:center; gap:22px; border-bottom:4px solid #2563EB; padding-bottom:16px; }}
.head img {{ width:150px; }}
.htitle {{ font-size:62px; font-weight:700; }}
.hsub {{ font-size:26px; color:#5B6B85; margin-top:6px; }}
.htag {{ font-size:20px; color:#2563EB; font-weight:600; margin-top:6px; }}
.card {{ background:#fff; border:1px solid #E3E9F2; border-radius:18px; padding:26px 30px; margin-top:26px; }}
.card.alert {{ border-left:10px solid #BE342C; }}
.card.blue {{ border-left:10px solid #2563EB; }}
h2 {{ font-size:34px; font-weight:700; margin-bottom:10px; }}
h2.r {{ color:#BE342C; }} h2.b {{ color:#2563EB; }}
p {{ font-size:23px; line-height:1.55; }}
.feat {{ display:grid; grid-template-columns:1fr 1fr; gap:14px 34px; font-size:22px; margin-top:6px; }}
.feat div::before {{ content:'•'; color:#2563EB; font-weight:700; margin-right:10px; }}
.foot {{ margin-top:26px; font-size:21px; color:#5B6B85; display:flex; justify-content:space-between; }}
</style></head><body>
<div class="page">
  <div class="head">
    <img src="{LOGO}">
    <div>
      <div class="htitle">AI Guard</div>
      <div class="hsub">ปกปิดข้อมูลส่วนบุคคลภาษาไทยก่อนใช้งานปัญญาประดิษฐ์ภายนอก ตาม PDPA</div>
      <div class="htag">PSU Future Tech Challenge 2026 &nbsp;|&nbsp; ระดับ Prototype</div>
    </div>
  </div>

  <div class="card alert">
    <h2 class="r">ปัญหา: ข้อมูลของคุณรั่วโดยไม่รู้ตัว</h2>
    <p>ทุกครั้งที่พิมพ์ชื่อ เลขบัตรประชาชน เบอร์ หรือประวัติสุขภาพลงใน AI สาธารณะ ข้อมูลถูกส่งออกนอกองค์กรไปยังเซิร์ฟเวอร์ต่างประเทศทันที เรียกคืนไม่ได้ และเสี่ยงผิด PDPA โดยเฉพาะข้อมูลอ่อนไหวตามมาตรา 26</p>
  </div>

  <div class="card blue">
    <h2 class="b">วิธีแก้: ปกปิด → ส่ง → คืนค่า (ในเครื่องของคุณ)</h2>
    <img src="{DEMO}" style="border:1px solid #E3E9F2;border-radius:12px;margin-top:8px">
  </div>

  <div class="card">
    <h2 class="b">เบื้องหลังทำงานอย่างไร</h2>
    <img src="{ARCH}" style="margin-top:6px">
  </div>

  <div class="card">
    <h2 class="b">จุดเด่นและการกำกับดูแลข้อมูล</h2>
    <div class="feat">
      <div>ปกปิดได้ 2 โหมด: รหัส และ ข้อมูลปลอมสมจริง</div>
      <div>ทำงานบน ChatGPT และ Claude ผ่านส่วนขยาย</div>
      <div>ปกปิดไฟล์ PDF (ดำกล่องทับ PII)</div>
      <div>ตรวจข้อมูลอ่อนไหวมาตรา 26 ทั้ง 8 หมวด</div>
      <div>ตารางสลับค่าอยู่ในหน่วยความจำ ไม่เขียนดิสก์</div>
      <div>ตรวจสอบย้อนกลับได้ ไม่เก็บข้อมูลจริงใน log</div>
    </div>
  </div>

  <div class="foot">
    <div>ผล: ลดความเสี่ยงรั่ว ~100% สำหรับ PII ที่ตรวจจับได้ &nbsp;|&nbsp; ทดสอบจริงบน Claude &nbsp;|&nbsp; ทดสอบอัตโนมัติ 233 กรณี</div>
    <div>[ทีม / อีเมล / QR code -> GitHub]</div>
  </div>
</div>
</body></html>"""

(OUT / "a4.html").write_text(A4, encoding="utf-8")
(OUT / "poster.html").write_text(POSTER, encoding="utf-8")
print("wrote a4.html and poster.html")
