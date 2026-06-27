# AI Guard — Thai PII Redaction

ปกปิดข้อมูลส่วนบุคคล (PII) ภาษาไทยก่อนส่งให้ AI ภายนอก แล้วคืนค่าจริงในเครื่อง — ทุกอย่างประมวลผลบนเครื่องคุณ ข้อมูลจริงไม่ออกนอกเครื่อง (ตาม PDPA)

> Mask Thai PII before sending it to an external AI, then restore the real values locally. Everything runs on your machine; raw PII never leaves the device.

PSU Future Tech Challenge 2026 — AI Innovation for Future Society (Prototype)

---

## ทำอะไรได้ / What it does

- **AI Guard** — บน ChatGPT / Claude: แทน PII ด้วยโทเคน `[ชื่อ_1]` หรือข้อมูลปลอมสมจริง ก่อนส่ง แล้วคืนค่าจริงจากตอบกลับ
- **True PDF redaction** — ดำกล่องทับ PII ในไฟล์ PDF จริง (ลบออกจาก text layer)
- **PDPA report** — ให้คะแนนความเสี่ยง + ธงข้อมูลอ่อนไหวมาตรา 26 (โรค ศาสนา ฯลฯ)

การตรวจจับ: regex + checksum (เลขบัตร mod-11, เบอร์, อีเมล ฯลฯ) + Thai NER (PyThaiNLP thainer) — รันในเครื่อง ไม่ใช้ AI คลาวด์

---

## ติดตั้งและใช้งาน / Quick start

### 1. เริ่ม backend (จำเป็น)

สคริปต์จะสร้าง virtualenv + ลง dependency ให้อัตโนมัติในครั้งแรก แล้วเปิดที่ `http://localhost:8000`

```powershell
# Windows (PowerShell)
./run.ps1
```
```bash
# Linux / macOS / git-bash
./run.sh
```

เช็คว่าใช้ได้: เปิด `http://localhost:8000/api/health` ควรได้ `{"status":"ok",...}`

### 2. โหลด Browser Extension (ใช้บน ChatGPT / Claude)

1. เปิด `chrome://extensions`
2. เปิด **Developer mode** (มุมขวาบน)
3. กด **Load unpacked** → เลือกโฟลเดอร์ `extension/`

(รายละเอียดเพิ่มเติม: `extension/README.md`)

### 3. ใช้งานบน ChatGPT / Claude

1. พิมพ์ข้อความที่มี PII ในช่องแชต
2. กด **Mask PII** (แถบลอย AI Guard) — ข้อความจะถูกแทนด้วยโทเคน/ข้อมูลปลอม
3. กดส่งด้วยปุ่มของเว็บตามปกติ
4. พอ AI ตอบ กด **Restore PII** เพื่อเห็นค่าจริง

---

## ลองด้วยตัวอย่าง / Try the examples

ไฟล์ตัวอย่าง (PII ปลอมทั้งหมด) อยู่ใน `examples/`:
- `examples/prompts/*.txt` — prompt สถานการณ์จริง (ลาป่วย / ปรึกษาหมอ / ร้องเรียนธนาคาร)
- `examples/sample_document.pdf` — เอกสารไทยมี PII สำหรับลอง redact

ลองผ่าน Swagger UI ได้เลย: เปิด `http://localhost:8000/docs`

หรือผ่าน API:
```bash
curl -X POST http://localhost:8000/api/sanitize \
  -H "Content-Type: application/json" \
  -d '{"text":"ผมชื่อสมชาย ใจดี โทร 081-234-5678","mode":"surrogate"}'
```

---

## โหมดการ mask / Modes

| โหมด | ผลลัพธ์ | เหมาะกับ |
|---|---|---|
| `token` (ค่าเริ่มต้น) | `[ชื่อ_1]`, `[โทรศัพท์_1]` | เห็นชัดว่าปกปิดแล้ว ตรวจง่าย |
| `surrogate` | ข้อมูลปลอมสมจริง (checksum ถูก) | AI อ่านลื่น ตอบได้เต็มคุณภาพ |

สลับโหมดได้ที่ popup ของ extension (ปุ่มไอคอนบนแถบเครื่องมือ)

---

## ออปชัน: ตัวตรวจข้อมูลอ่อนไหวเชิงความหมาย / Optional semantic detector

ตรวจ PII อ่อนไหว ม.26 แบบ free-form (เช่น "ป่วยเป็นเบาหวาน" ที่ไม่มีคีย์เวิร์ด) ด้วยโมเดล MiniLM:

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements-ml.txt   # ~หลายร้อย MB
```

ไม่ลงก็ใช้งานหลักได้ตามปกติ — ตัว detector จะปิดตัวเองเงียบ ๆ

---

## ความเป็นส่วนตัว / Privacy

- ตาราง vault (โทเคน ↔ ค่าจริง) อยู่ใน**หน่วยความจำเครื่องเท่านั้น** ไม่เขียนดิสก์ ไม่ส่งผ่านเครือข่าย
- Extension เก็บแค่ `session_id` ไม่เคยเก็บค่าจริง
- AI ภายนอก (ChatGPT/Claude) เห็นแค่ข้อความที่ถูก mask แล้ว

---

## ทดสอบ / Run tests

```powershell
$env:PYTHONUTF8='1'; ./.venv/Scripts/python.exe -m pytest
```

## สถาปัตยกรรม / Architecture

ดูรายละเอียดใน [`CLAUDE.md`](CLAUDE.md)

## License

โค้ดส่วนนี้เพื่อการศึกษา/ประกวด — หมายเหตุ: PyMuPDF อยู่ภายใต้สัญญาอนุญาต AGPL
