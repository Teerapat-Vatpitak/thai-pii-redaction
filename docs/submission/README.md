# ชุดเอกสารส่งประกวด — PSU Future Tech Challenge 2026

ชุดเนื้อหาสำหรับส่งประกวด ผลงาน **AI Guard: ระบบปกปิดข้อมูลส่วนบุคคลภาษาไทยก่อนใช้งาน AI ภายนอก**
ระดับ **Prototype** · งาน PSU Cybersecurity, AI & Data Privacy Day 2026

## ไฟล์ในชุดนี้

| ไฟล์ | ใช้ทำอะไร | ใครทำต่อ |
|---|---|---|
| `form-answers.md` | คำตอบฟอร์มสมัคร ข้อ 1-12 (พร้อม copy ลง MS Form) | ผู้ส่ง (กรอกฟอร์ม) |
| `a4-onepager.md` | เนื้อหาเอกสาร A4 1 หน้า (deliverable ข้อ 13) | ออกแบบเป็น A4 (Canva/Word/InDesign) |
| `video-script.md` | สคริปต์ + สตอรีบอร์ดวิดีโอ <=5 นาที (ข้อ 14) | ถ่าย/ตัดต่อวิดีโอ |
| `poster-a1.md` | เนื้อหา + เลย์เอาต์โปสเตอร์ A1 | ออกแบบโปสเตอร์ |

## ทรัพยากรที่ใช้ประกอบ (มีแล้วในรีโป)
- โลโก้: `assets/logo.svg` (vector คมสำหรับโปสเตอร์), `assets/logo.png` (โปร่งใส), `assets/logo-square-512.png`
- ภาพหน้าจอเดโมจริงบน Claude: ขอจากแชต/ถ่ายซ้ำได้จาก extension (mask -> ส่ง -> restore)
- โค้ด/สถาปัตยกรรม: `CLAUDE.md`, `README.md`

## กำหนดส่ง
- ปิดรับผลงาน: 29 มิ.ย. 2569 (ขยายจาก 22 มิ.ย.)
- ประกาศรอบแรก: 2 ก.ค. 2569 · นำเสนอโปสเตอร์ A1 + ประกาศผล: 10 ก.ค. 2569
- อัปโหลดไฟล์ผ่าน Google Drive/OneDrive/PSU Storage แชร์ไป **governance@psu.ac.th**

## ไฟล์ออกแบบที่ generate ให้แล้ว (เปิดใช้/แก้ต่อได้เลย)

| ไฟล์ | คืออะไร | วิธีใช้ |
|---|---|---|
| `a4.html` | A4 1 หน้า จัดหน้าแล้ว (โลโก้ + before/after ฝังในไฟล์) | เปิดในเบราว์เซอร์ -> Print -> Save as PDF (เลือกขนาด A4) ได้ deliverable ข้อ 13 |
| `poster.html` | โปสเตอร์ A1 จัดหน้าแล้ว (โลโก้ + before/after + แผนภาพ) | เปิดในเบราว์เซอร์ -> Print -> Save as PDF (เลือกขนาด A1 / กระดาษ custom 594x841mm) |
| `build_designed_docs.py` | สคริปต์สร้าง a4.html/poster.html ใหม่ (ฝังรูป base64) | `python docs/submission/build_designed_docs.py` หากแก้รูป/เนื้อหาแล้วอยากสร้างใหม่ |

ภาพประกอบ (อยู่ใน `assets/`): `demo-before-after.png` (ก่อน/หลังปกปิด จาก output จริง), `architecture.png` (แผนภาพสถาปัตยกรรม), `logo.svg`/`logo.png`
> หมายเหตุ: ฟอนต์ในไฟล์ HTML โหลด Sarabun จาก Google Fonts ตอนเปิด (ต้องต่อเน็ตตอน export PDF) เพื่อนปรับสี/เลย์เอาต์/ใส่ QR ต่อใน Canva/Illustrator ได้ตามต้องการ

## หลักการเขียน (สำคัญ — อย่าแก้ให้เกินจริง)
เคลมเฉพาะที่ระบบทำได้จริง: regex+checksum, thainer-CRF NER + กฎบริบท, token/surrogate, vault ในเครื่อง,
true PDF redaction (bbox), OCR ภาพสแกนด้วย PaddleOCR ต่อหน้า (พร้อม retry + human-review flag; ต้องรันจาก source พร้อม `requirements-ocr.txt` — ไม่ได้บันเดิลใน .exe), ธง ม.26, re-id risk, extension + .exe
**ของที่เป็น roadmap (ห้ามเคลมว่าทำแล้ว):** WangchanBERTa, Presidio bridge, การวัด F1 ทางการ (ไม่มีตัวเลข accuracy ของ OCR ที่ผ่านการวัดจริง — อย่าเคลมตัวเลข)
