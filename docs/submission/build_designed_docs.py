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

# QR code for the poster/A4 footer, pointing at the latest GitHub release.
# Generated once with segno (build-time only tool, not a runtime dependency):
#   PYTHONUTF8=1 ./.venv/Scripts/python.exe -m pip install segno
#   PYTHONUTF8=1 ./.venv/Scripts/python.exe -c "
#   import segno
#   segno.make('https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest',
#               error='h').save('docs/submission/qr-release.png', scale=20, border=2)
#   "
# Regenerate the same way if the release URL ever changes.
QR_URL = "https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest"


def b64(name: str) -> str:
    data = (ASSETS / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def b64_file(path: Path) -> str:
    data = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


LOGO = b64("logo.png")
DEMO = b64("demo-before-after.png")
ARCH = b64("architecture.png")
QR = b64_file(OUT / "qr-release.png")

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
.page {{ width:210mm; height:297mm; padding:12mm 13mm; display:flex; flex-direction:column; }}
.head {{ display:flex; align-items:center; gap:13px; }}
.head img {{ width:62px; }}
.title {{ font-size:20px; font-weight:700; line-height:1.18; }}
.sub {{ font-size:11.5px; color:#5B6B85; margin-top:3px; line-height:1.4; }}
.tag {{ font-size:10px; color:#2563EB; font-weight:600; margin-top:3px; letter-spacing:.2px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:5px; margin-top:9px; }}
.chip {{ font-size:9.5px; font-weight:600; color:#1E3A8A; background:#EAF1FE;
        border:1px solid #D5E2FB; border-radius:20px; padding:2px 9px; }}
.body {{ margin-top:11px; }}
section {{ margin-top:8px; }}
h2 {{ font-size:12px; color:#15233B; font-weight:700; margin-bottom:3px;
      display:flex; align-items:center; gap:7px; }}
.n {{ flex:none; width:17px; height:17px; border-radius:5px; background:#2563EB; color:#fff;
     font-size:10px; font-weight:700; display:flex; align-items:center; justify-content:center; }}
.en {{ color:#8595AD; font-weight:600; font-size:10px; }}
p {{ font-size:11px; line-height:1.46; color:#26344C; }}
b.k {{ color:#15233B; font-weight:700; }}
.demo {{ margin:7px auto 1px; border:1px solid #E3E9F2; border-radius:9px; overflow:hidden; max-width:155mm; }}
.cap {{ font-size:9px; color:#8595AD; text-align:center; margin-top:3px; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:7px 18px; }}
.foot {{ margin-top:auto; padding-top:8px; border-top:1px solid #E3E9F2;
         font-size:10px; color:#5B6B85; display:flex; justify-content:space-between; gap:12px; }}
</style></head><body>
<div class="page">
  <div class="head">
    <img src="{LOGO}">
    <div>
      <div class="title">AI Guard — ระบบปกปิดข้อมูลส่วนบุคคลภาษาไทยก่อนใช้งานปัญญาประดิษฐ์ภายนอก</div>
      <div class="sub">ปกปิด (mask) ข้อมูลส่วนบุคคลก่อนส่งให้ ChatGPT หรือ Claude แล้วคืนค่าจริงในเครื่องของผู้ใช้ — ข้อมูลจริงไม่ออกนอกเครื่อง สอดคล้องกับ PDPA</div>
      <div class="tag">ระดับผลงาน: ต้นแบบ (Prototype) &nbsp;|&nbsp; PSU Future Tech Challenge 2026 — AI Innovation for Future Society</div>
    </div>
  </div>
  <div class="bar" style="margin-top:9px"></div>
  <div class="chips">
    <span class="chip">ประมวลผลในเครื่อง 100%</span>
    <span class="chip">PII มีรูปแบบ 10+ ประเภท</span>
    <span class="chip">ข้อมูลอ่อนไหว ม.26 ครบ 8 หมวด</span>
    <span class="chip">ปกปิด 2 โหมด: รหัส / ข้อมูลปลอมสมจริง</span>
    <span class="chip">ใช้บน ChatGPT &amp; Claude</span>
    <span class="chip">ทดสอบอัตโนมัติ 269 กรณี</span>
  </div>

  <div class="body">
  <section>
    <h2><span class="n">6</span> แนวคิดและที่มา <span class="en">Concept &amp; Background</span></h2>
    <p>คนทำงานยุคนี้ใช้ Generative AI ช่วยร่างและสรุปเอกสารเป็นประจำ ซึ่งมักมีข้อมูลส่วนบุคคลปนอยู่ แนวคิดของ AI Guard คือ <b class="k">ปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI แล้วคืนค่าจริงกลับในเครื่องหลังได้คำตอบ</b> ต่างจากเครื่องมือต่างประเทศ (Microsoft Presidio, LLM-Guard) ตรงที่ออกแบบเพื่อภาษาไทยเป็นหลัก ยึดตาม PDPA รวมข้อมูลอ่อนไหวมาตรา 26 ประมวลผลทั้งหมดในเครื่องของผู้ใช้ และเข้าทำงานบนหน้าจอ AI จริงผ่านส่วนขยายเบราว์เซอร์</p>
  </section>

  <section>
    <h2><span class="n">7</span> ปัญหาที่ต้องการแก้ไข <span class="en">Problem Statement</span></h2>
    <p>เมื่อพิมพ์ชื่อ เลขบัตรประชาชน เบอร์โทรศัพท์ เลขบัญชี หรือประวัติสุขภาพ ลงในบริการ AI สาธารณะ ข้อมูลออกนอกองค์กรไปยังเซิร์ฟเวอร์ต่างประเทศทันทีและเรียกคืนไม่ได้ เสี่ยงละเมิด PDPA โดยตรง โดยเฉพาะข้อมูลอ่อนไหวตามมาตรา 26 ผู้ได้รับผลกระทบหลักคือบุคลากรหน่วยงานราชการ มหาวิทยาลัย และโรงพยาบาล ที่ผ่านมายังไม่มีเครื่องมือฝั่งภาษาไทยที่ดักจุดนี้โดยเฉพาะ</p>
  </section>

  <section>
    <h2><span class="n">8</span> วิธีการนำ AI มาใช้ <span class="en">AI Approach &amp; Tools</span></h2>
    <p>ใช้การประมวลผลภาษาธรรมชาติและการรู้จำเอนทิตี (NLP/NER) ร่วมกับกฎ สองแนวทางเสริมกัน: <b class="k">(1) กฎ + checksum</b> สำหรับข้อมูลมีรูปแบบ เช่น เลขบัตรประชาชน (mod-11), เบอร์, อีเมล, บัญชีธนาคาร, บัตรเครดิต (Luhn), พาสปอร์ต, ทะเบียนรถ <b class="k">(2) NER ภาษาไทย</b> (PyThaiNLP thainer) จับชื่อและที่อยู่ เสริมกฎบริบทคำนำหน้า (นาย/นาง/ผมชื่อ) พร้อมตรวจข้อมูลอ่อนไหวมาตรา 26 ทั้ง 8 หมวด ปกปิดได้ 2 โหมด คือรหัส [ชื่อ_1] หรือข้อมูลปลอมที่สมจริงผ่าน checksum (ทำให้ AI ตอบได้เต็มคุณภาพ) เครื่องมือ: PyThaiNLP, pypdfium2, reportlab, pdfplumber, FastAPI และส่วนขยาย MV3 — ขั้นตรวจจับไม่ส่งข้อมูลจริงให้ LLM ใดเลย ยึดหลัก recall &gt; precision และสแกนซ้ำก่อนส่งทุกครั้ง</p>
    <div class="demo"><img src="{DEMO}"></div>
    <div class="cap">ตัวอย่างจริง: ก่อน–หลังปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI แล้วคืนค่าจริงในเครื่อง</div>
  </section>

  <div class="grid2">
    <section>
      <h2><span class="n">9</span> ผลลัพธ์ <span class="en">Results</span></h2>
      <p>ความเสี่ยงข้อมูลรั่วไปยัง AI ภายนอกลดลงเกือบทั้งหมดสำหรับ PII ที่ตรวจจับได้ เพราะตารางสลับค่าอยู่ในหน่วยความจำ ครอบคลุม PII มีรูปแบบ 10+ ประเภท + ชื่อ/ที่อยู่ + อ่อนไหว 8 หมวด ทดสอบครบวงจรบน Claude สำเร็จ ผ่านชุดทดสอบอัตโนมัติ 269 กรณี (การวัด F1 ทางการเป็นงานขั้นต่อไป)</p>
    </section>
    <section>
      <h2><span class="n">10</span> ประโยชน์ที่ได้รับ <span class="en">Impact</span></h2>
      <p>ใช้ AI ช่วยงานต่อได้โดยไม่เสี่ยงผิด PDPA ปกปิดและคืนค่าอัตโนมัติในไม่กี่คลิก ลดเวลาและความผิดพลาดเทียบกับการลบเอง โหมดข้อมูลปลอมรักษาคุณภาพคำตอบ และทำงานในเครื่อง/ออฟไลน์ได้ เหมาะกับองค์กรที่ห้ามข้อมูลออกนอก</p>
    </section>
    <section>
      <h2><span class="n">11</span> แนวทางการขยายผล <span class="en">Scalability</span></h2>
      <p>ติดตั้ง on-premise ผ่านไฟล์ติดตั้งหรือ Docker ส่วนขยายติดตั้งง่าย ขยายตามจำนวนผู้ใช้โดยไม่มีคอขวดที่เซิร์ฟเวอร์กลาง เปิดเป็นโอเพนซอร์สพร้อม 269 เทสต์และเอกสารสถาปัตยกรรม โรดแมป: WangchanBERTa, OCR เอกสารสแกน, แพลตฟอร์มเพิ่ม, โหมดปกปิด PDF สมบูรณ์</p>
    </section>
    <section>
      <h2><span class="n">12</span> จริยธรรมและการกำกับข้อมูล <span class="en">Responsible AI</span></h2>
      <p>ตารางสลับค่าอยู่ในหน่วยความจำเท่านั้น ไม่เขียนดิสก์/ไม่ส่งเครือข่าย สแกนซ้ำก่อนส่งทุกครั้ง รับเฉพาะข้อความในต้นฉบับจริงจึงไม่เปิดช่องให้ AI แต่งข้อมูล มาตรา 26 แจ้งเตือนไม่ประมวลผลอัตโนมัติ log เก็บเพียงรหัสอ้างอิงและเวลา และระบุข้อจำกัดอคติของ NER ตรงไปตรงมา</p>
    </section>
  </div>
  </div>

  <!-- TODO(user-text): fill in the real team name / affiliation / contact email once provided. -->
  <div class="foot">
    <div>ทีม: {{TEAM_NAME}} / {{TEAM_AFFILIATION}}</div>
    <div>โค้ดและวิดีโอเดโม: {QR_URL}</div>
  </div>
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
.foot {{ margin-top:26px; font-size:21px; color:#5B6B85; display:flex; justify-content:space-between; align-items:flex-end; }}
.footqr {{ display:flex; flex-direction:column; align-items:center; gap:4px; }}
.footteam {{ align-self:flex-start; }}
.qrbox {{ display:flex; flex-direction:column; align-items:center; gap:4px; background:#fff;
          border:1px solid #E3E9F2; border-radius:10px; padding:10px 14px; }}
.qr {{ width:35mm; height:35mm; display:block; }}
.qrurl {{ font-size:13px; color:#5B6B85; word-break:break-all; max-width:60mm; text-align:center; }}
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
    <div>ผล: ลดความเสี่ยงรั่ว ~100% สำหรับ PII ที่ตรวจจับได้ &nbsp;|&nbsp; ทดสอบจริงบน Claude &nbsp;|&nbsp; ทดสอบอัตโนมัติ 269 กรณี</div>
    <!-- TODO(user-text): fill in the real team name and contact email once provided. -->
    <div class="footqr">
      <div class="footteam">ทีม: {{TEAM_NAME}} &nbsp;|&nbsp; {{TEAM_EMAIL}}</div>
      <div class="qrbox">
        <img src="{QR}" class="qr">
        <div class="qrurl">{QR_URL}</div>
      </div>
    </div>
  </div>
</div>
</body></html>"""

(OUT / "a4.html").write_text(A4, encoding="utf-8")
(OUT / "poster.html").write_text(POSTER, encoding="utf-8")
print("wrote a4.html and poster.html")
