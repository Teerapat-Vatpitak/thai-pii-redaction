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

## หลักการเขียน (สำคัญ — อย่าแก้ให้เกินจริง)
เคลมเฉพาะที่ระบบทำได้จริง: regex+checksum, thainer-CRF NER + กฎบริบท, token/surrogate, vault ในเครื่อง,
true PDF redaction (bbox), ธง ม.26, re-id risk, extension + .exe
**ของที่เป็น roadmap (ห้ามเคลมว่าทำแล้ว):** WangchanBERTa, OCR เอกสารสแกน, Presidio bridge, การวัด F1 ทางการ
