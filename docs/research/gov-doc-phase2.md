# หลักฐาน phase 2: ฟอร์มราชการเปล่าและ probe 9 อินพุต

บันทึกนี้แยกสี่สถานะออกจากกัน: ดาวน์โหลดต้นฉบับ, สร้างอินพุตสังเคราะห์,
รัน probe แบบ text layer และรัน OCR. ผลวันที่ 2026-07-31 ยังไม่ใช่ accuracy
benchmark. Runner ไม่เรียก `blind-v1` และ reveal log ยังอยู่ที่ 4/6.

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
.\.venv\Scripts\python.exe -m pytest -q `
  tests\test_gov_form_phase2.py `
  tests\test_gov_form_acceptance.py `
  tests\test_probe_document.py
.\.venv-full\Scripts\python.exe -m benchmark.data.probe.gov_forms.run_acceptance `
  --output-dir benchmark/reports/gov-forms-2026-07-31-clean
```

Runner สร้างและ probe ทั้ง 9 อินพุตใน process เดียว แล้วเขียน result JSON แยก
ต่ออินพุตพร้อม `summary.json`. ค่า exit เป็น `1` เมื่อ strict gate ใดไม่ผ่าน.
ใช้ `--record-only` ได้เฉพาะเก็บ baseline; failure ยังอยู่ใน JSON ตามเดิม.
`summary.json` เป็นหลักฐานหลักและมี per-input/aggregate metrics ที่ไม่มีค่า
entity. Result รายอินพุตเป็น diagnostic ที่ตัด expected value, OCR text,
surviving value และ decoy string ออกก่อนเขียนไฟล์.

## ผล local full OCR environment

Builder สร้าง 9/9 อินพุตและ route ถูกทั้ง 9. Image-only 6 อินพุตรัน OCR,
coverage และ residual จริงแล้ว. Strict result เป็น **FUNCTIONAL FAIL**:

| ฟอร์ม / modality | OCR mean | extraction | detection | type match | coverage / expected | residual |
|---|---:|---:|---:|---:|---:|---:|
| คร.1 digital | n/a | 4/4 | 3/4 | 3/4 | 3/4 | removed 3, exposed 1 |
| คร.1 print-like | 0.95 | 2/4 | 4/4 | 4/4 | 4/4 | removed 4 |
| คร.1 degraded | 0.93 | 2/4 | 4/4 | 3/4 | 4/4 | removed 4 |
| ภ.ง.ด.91 digital | n/a | 6/6 | 6/6 | 5/6 | 6/6 | removed 6 |
| ภ.ง.ด.91 print-like | 0.85 | 4/6 | 4/6 | 3/4 | 4/6 | removed 4, unmeasurable 2 |
| ภ.ง.ด.91 degraded | 0.88 | 5/6 | 5/6 | 5/5 | 5/6 | removed 5, unmeasurable 1 |
| สปส.1-03 digital | n/a | 5/5 | 5/5 | 3/4; ORGANIZATION อยู่นอก legacy-11 | 5/5 | removed 5 |
| สปส.1-03 print-like | 0.97 | 3/5 | 5/5 | 4/4 | 5/5 | removed 5 |
| สปส.1-03 degraded | 0.72 | 2/5 | 2/5 | 1/2 | 2/5 | removed 2, exposed 1, unmeasurable 2 |
| **รวม** | 6/6 image inputs measured | **33/45** | **38/45** | **31/37 scored** | **38/45** | **removed 38, exposed 2, unmeasurable 5** |

ไม่มี declared decoy string ปรากฏในข้อความ extraction ของทั้ง 9 อินพุต. นี่เป็น
matcher-level check ไม่ใช่ false-positive benchmark ของ detector. ค่า OCR mean
นับเฉพาะค่าที่จับคู่กับช่วงข้อความได้แบบไม่ซ้ำ; ค่าที่จับคู่ไม่ได้ยังทำให้
extraction/coverage/residual fail. Exposed สองช่องคือชื่อผู้ร้องคนที่ 2 ใน
คร.1 digital และชื่อผู้ประกันตนใน สปส.1-03 degraded. อีกห้าช่องไม่มีตำแหน่ง
OCR ที่เชื่อถือได้ จึงเป็น `unmeasurable` ไม่ใช่ pass.

Runtime ที่บันทึก: Python 3.13.12, PaddlePaddle 3.2.2, PaddleOCR 3.7.0,
OpenCV 4.10.0, Pillow 12.3.0, ReportLab 5.0.0 และ pypdfium2 5.12.1.
รายละเอียด gate และขอบเขตอยู่ใน
[acceptance record](../acceptance/2026-07-31-government-form-synthetic-run.md).

Strict gate ใช้ route/OCR, extraction, pixel coverage, residual และ declared
decoy extraction check. Detection กับ type match เป็น telemetry ไม่มี threshold.

การขยาย NAME แบบปลอดภัยใช้ isolated-line retry เฉพาะ default CRF, จำกัด 8
บรรทัด, ไม่กิน role prefix และมี semantic negative tests. Gold-v4 ที่มองเห็น
ได้ยังให้ overall recall 0.937 / F2 0.910, NAME recall 0.910 / precision 0.953 /
F2 0.918, exact recall 0.793 และ gov-form slice recall 0.857. กฎกว้างแบบ
“ชื่ออยู่ใกล้ ID/วันที่” ไม่ถูกเก็บไว้หลัง visible-gold regression test. Runner
ไม่เรียก `blind-v1` และ reveal log ยังอยู่ที่ 4/6.

## ข้อจำกัด

- เป็น overlay ที่สร้างด้วยคอมพิวเตอร์ ไม่ใช่ลายมือหรือการสแกนจากเครื่องจริง.
- Digital input ใช้ page-only copy เป็นภาพและให้ text layer เฉพาะค่าทดสอบ จึงวัด
  field values แต่ไม่วัดการอ่านข้อความ label ของฟอร์ม.
- OCR นี้เป็นภาพ transform แบบกำหนดค่าคงที่ ไม่ใช่ภาพจากเครื่องสแกนจริง.
- วันเกิดที่ไม่มี cue ชัดยังอาจได้ `DATE`; ระบบปิดบังได้แต่ type ไม่ตรง
  `DATE_OF_BIRTH`.
- ไม่กรอกช่องมาตรา 26 ใน สปส.1-03 และยังไม่เปลี่ยนนโยบาย warn-only.
- Synthetic expectations เป็น developer-authored และยังไม่มี independent
  adjudication. งาน annotation/adjudication ของเนื้อหาฟอร์มจริงที่กว้างกว่านี้
  ถูกเลื่อนตามคำสั่ง owner.
- ผลนี้เปิดช่องว่างที่ต้องแก้ แต่ไม่ใช่ benchmark accuracy. Runner ไม่เรียก
  blind set.
