# หลักฐาน phase 2: ฟอร์มราชการเปล่าและ probe 9 อินพุต

บันทึกนี้แยกสี่สถานะออกจากกัน: ดาวน์โหลดต้นฉบับ, สร้างอินพุตสังเคราะห์,
รัน probe แบบ text layer และรัน OCR. ผลวันที่ 2026-07-31 ยังไม่ใช่ accuracy
benchmark และไม่ได้แตะ blind set.

## แหล่งและความครบถ้วน

| กลุ่ม | ฟอร์มที่ใช้ | แหล่งทางการ | Source SHA-256 | สถานะ |
|---|---|---|---|---|
| ทะเบียนครอบครัว | คร.1 คำร้องขอจดทะเบียนและบันทึกทะเบียนครอบครัว | [หน้าแบบฟอร์ม BORA](https://www.bora.dopa.go.th/menu-stt) และ [PDF ตรง](https://www.bora.dopa.go.th/wp-content/uploads/2025/10/%E0%B8%84%E0%B8%B3%E0%B8%A3%E0%B9%89%E0%B8%AD%E0%B8%87%E0%B8%82%E0%B8%AD%E0%B8%88%E0%B8%94%E0%B8%97%E0%B8%B0%E0%B9%80%E0%B8%9A%E0%B8%B5%E0%B8%A2%E0%B8%99%E0%B9%81%E0%B8%A5%E0%B8%B0%E0%B8%9A%E0%B8%B1%E0%B8%99%E0%B8%97%E0%B8%B6%E0%B8%81%E0%B8%97%E0%B8%B0%E0%B9%80%E0%B8%9A%E0%B8%B5%E0%B8%A2%E0%B8%99%E0%B8%84%E0%B8%A3%E0%B8%AD%E0%B8%9A%E0%B8%84%E0%B8%A3%E0%B8%B1%E0%B8%A7-%E0%B8%84%E0%B8%A3.1.pdf) | `84692fd1f64a254ead8b7ae7ff193890d5a5412ce03ef18b0cfcf6323500df31` | ดาวน์โหลดแล้ว 64,718 bytes; แบบเปล่าทางการมีลายน้ำ “ตัวอย่าง” |
| ภาษี | ภ.ง.ด.91 ปีภาษี 2568 | [หน้าดาวน์โหลดกรมสรรพากร](https://www.rd.go.th/67335.html) และ [PDF ตรง](https://www.rd.go.th/fileadmin/tax_pdf/pit/2568/241268PIT91.pdf) | `8cb80f3b2392be6462c3b73cb31bd7b560578e81a84625b3938bb02d258e206b` | ดาวน์โหลดแล้ว 1,463,353 bytes |
| ประกันสังคม | สปส.1-03 แบบขึ้นทะเบียนผู้ประกันตน | [SSO Data Catalog](https://catalog.sso.go.th/dataset/dataset-22_01) และ [ทรัพยากร PDF](https://catalog.sso.go.th/dataset/c72fd51f-8e63-4565-8b6a-120fe5a95e60/resource/bd8da94a-a375-482b-a233-b9069c390f03/download/.pdf) | `e43c424e64456581faa37319b88e1b9a4daea7a4cbcbaa4b3c664c78a7d94e4d` | ดาวน์โหลดแล้ว 172,715 bytes |

ท.ร.6 ตัวหลักไม่ถูกแทนด้วยภาพสินค้าหรือไฟล์จากแหล่งรอง.
[คู่มือ DOPA](https://www.dopa.go.th/public_service/service_guide24/view435)
ยืนยันชื่อเอกสาร ส่วน
[คู่มือฝ่ายทะเบียนกรุงเทพมหานคร](https://webportal.bangkok.go.th/upload/user/00000083/General/DownloadPDF/Manual63/02_tabain63.pdf)
ระบุขั้นตอนว่าเจ้าหน้าที่ “พิมพ์ใบแจ้งการย้ายที่อยู่ (ท.ร.6 ตอนที่ 1)”.
ไม่พบ public blank download จาก DOPA/BORA จึงใช้ คร.1 ซึ่งเป็นตัวสำรองที่
sampling frame กำหนดไว้. ข้อจำกัดนี้ทำให้ phase 2 รอบนี้ไม่มีหลักฐานของ layout
ท.ร.6.

ต้นฉบับดิบใช้ตรวจ source SHA-256 แล้วไม่ commit เพราะ metadata อาจมีชื่อผู้สร้าง
ไฟล์. Repo เก็บเฉพาะ page-only copy ใต้
`benchmark/data/probe/gov_forms/sanitized/`. `sanitize_download.py` render
เฉพาะหน้าที่มองเห็น จึงไม่พา metadata, form fields, links, scripts, notes หรือ
attachments มาด้วย. `manifest.json` แยก source hash จาก artifact hash และ
tests ตรวจทั้งสองค่า รวมถึง hidden-payload structures.
Render QA ตรวจครบทั้ง 6 หน้าแล้วและไม่พบช่องข้อมูลบุคคลที่กรอกเสร็จ.

## อินพุตที่สร้าง

`generate_inputs.py` สร้าง 3 modality ต่อฟอร์ม รวม 9 อินพุต:

1. `digital`: ภาพฟอร์มเดิมกับ text-layer overlay;
2. `print_like`: flatten เป็นภาพแบบ lossless; และ
3. `degraded`: ลดความละเอียด หมุน 0.65 องศา เบลอ และบีบอัด JPEG ด้วยค่าคงที่.

ไม่มี random noise และ test สร้างสองรอบแล้วเทียบ SHA-256 ของ output.
ค่าชื่อ เลข 13 หลัก วันเกิด ที่อยู่ และ passport เป็นข้อมูลสังเคราะห์ทั้งหมด.
อินพุตและผลละเอียดออกใต้ `benchmark/reports/gov-forms-phase2/` ซึ่ง gitignore
ไว้; ต้นฉบับไม่ถูกแก้.

คำสั่งหลัก:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest tests\test_gov_form_phase2.py -q
.\.venv\Scripts\python.exe -m benchmark.data.probe.gov_forms.generate_inputs `
  --output-dir benchmark/reports/gov-forms-phase2/inputs
.\.venv\Scripts\python.exe -m benchmark.probe_document `
  benchmark/reports/gov-forms-phase2/inputs/khor-ror-1/khor-ror-1-digital.pdf `
  benchmark/reports/gov-forms-phase2/inputs/khor-ror-1/khor-ror-1-digital.expected.json `
  --json benchmark/reports/gov-forms-phase2/khor-ror-1-digital.result.json
```

Builder พิมพ์ path ของเอกสารและ expectation ครบทั้ง 9 คู่; ใช้คำสั่ง probe
บรรทัดสุดท้ายซ้ำกับแต่ละคู่เพื่อสร้าง result JSON.

## ผล local default environment

Focused contract test ผ่าน `7 passed`. Builder สร้าง 9/9 อินพุต. Probe รันครบ
9 คำสั่ง แต่มีผลที่วัดได้เฉพาะ digital 3 อินพุต:

| ฟอร์ม / modality | extraction | detection | type match | redaction coverage | residual |
|---|---:|---:|---:|---:|---:|
| คร.1 digital | 4/4 | 2/4 | 2/4 | 2/4 | removed 2, exposed 2 |
| ภ.ง.ด.91 digital | 6/6 | 4/6 | 3/6 | 3/6 | removed 3, exposed 3 |
| สปส.1-03 digital | 5/5 | 3/5 | 2/4 ที่อยู่ใน legacy-11; ORGANIZATION 1 ฟิลด์อยู่นอก scheme | 3/5 | removed 3, exposed 2 |
| print-like 3 อินพุต | skip: ไม่มี OCR extra | ไม่ได้วัด | ไม่ได้วัด | ไม่ได้วัด | ไม่ได้วัด |
| degraded 3 อินพุต | skip: ไม่มี OCR extra | ไม่ได้วัด | ไม่ได้วัด | ไม่ได้วัด | ไม่ได้วัด |

Digital ทั้งสามผ่าน negative decoy control โดยไม่มี false hit. ช่อง NAME
สังเคราะห์ทั้งห้ารายการไม่ถูกตรวจพบ. วันเกิดใน ภ.ง.ด.91 และ สปส.1-03 ถูกพบ
แต่ได้ label `DATE` แทน `DATE_OF_BIRTH`. ที่อยู่ ภ.ง.ด.91 ได้ label ถูก แต่
span coverage 0.85. THAI_ID ทั้งห้ารายการ และ passport ใน สปส.1-03 ถูกพบและ
ได้ชนิดตรง.

Print-like และ degraded ทั้งหกถูกจำแนกเป็น `pdf_hybrid` ตามที่ออกแบบ แต่
environment นี้ไม่มี `requirements-ocr.txt`; probe จึงรายงาน
`OCR dependencies unavailable` และ skip extraction, OCR accuracy, detection,
redaction coverage และ residual. นี่เป็น **OCR skipped**, ไม่ใช่ผลผ่าน 0/15.

## ข้อจำกัด

- เป็น overlay ที่สร้างด้วยคอมพิวเตอร์ ไม่ใช่ลายมือหรือการสแกนจากเครื่องจริง.
- Digital input ใช้ page-only copy เป็นภาพและให้ text layer เฉพาะค่าทดสอบ จึงวัด
  field values แต่ไม่วัดการอ่านข้อความ label ของฟอร์ม.
- Image-only inputs ยังไม่มี OCR evidence บนเครื่องนี้.
- Probe รุ่นนี้วัด coverage/residual เฉพาะ text-layer PDF.
- ไม่กรอกช่องมาตรา 26 ใน สปส.1-03 และยังไม่เปลี่ยนนโยบาย warn-only.
- ผลนี้เปิดช่องว่างที่ต้องแก้ แต่ไม่ใช่ benchmark accuracy และไม่ใช้ blind set.
