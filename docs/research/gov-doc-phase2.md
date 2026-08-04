# หลักฐาน phase 2: ฟอร์มราชการเปล่าและ probe 9 อินพุต

บันทึกนี้แยกสี่สถานะออกจากกัน: ดาวน์โหลดต้นฉบับ, สร้างอินพุตสังเคราะห์,
รัน probe แบบ text layer และรัน OCR. ผลวันที่ 2026-07-31 ยังไม่ใช่ accuracy
benchmark. Runner ไม่เรียก `blind-v1`. (reveal log อยู่ที่ 4/6 ตลอดช่วงพัฒนา
งานนี้; reveal 5 เกิดหลังงาน land แล้วตามคำสั่ง owner — ดู project-status.)

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
  --output-dir benchmark/reports/gov-forms-2026-07-31-final
```

Runner สร้างและ probe ทั้ง 9 อินพุตใน process เดียว แล้วเขียน result JSON แยก
ต่ออินพุตพร้อม `summary.json`. ค่า exit เป็น `1` เมื่อ strict gate ใดไม่ผ่าน.
ใช้ `--record-only` ได้เฉพาะเก็บ baseline; failure ยังอยู่ใน JSON ตามเดิม.
`summary.json` เป็นหลักฐานหลักและมี per-input/aggregate metrics ที่ไม่มีค่า
entity. Result รายอินพุตเป็น diagnostic ที่ตัด expected value, OCR text,
surviving value, decoy string และข้อความ exception/free-text reason ออกก่อน
เขียนไฟล์; CLI ก็ไม่พิมพ์ absolute path หรือ traceback.

## ผล local full OCR environment

Builder สร้าง 9/9 อินพุตและ route ถูกทั้ง 9. ทั้ง 9 อินพุตรัน OCR, coverage และ
residual จริงแล้ว (ไม่ใช่แค่ image-only เหมือนรอบก่อน). Strict result เป็น
**FUNCTIONAL FAIL**:

<!-- generated from gov-forms-2026-07-31-final/summary.json -->

| ฟอร์ม / modality | OCR mean | extraction | detection | type match | coverage | residual | render-OCR |
|---|---:|---:|---:|---:|---:|---:|---:|
| คร.1 digital | 0.95 | 4/4 | 4/4 | 4/4 | 4/4 | removed 4, exposed 0 | 0 surviving |
| คร.1 print-like **ตก** | 0.95 | 2/4 | 2/4 | 2/4 | 2/4 | removed 2, exposed 2 | 2 surviving |
| คร.1 degraded | 0.95 | 3/4 | 4/4 | 4/4 | 4/4 | removed 4, exposed 0 | 0 surviving |
| ภ.ง.ด.91 digital | 1.00 | 6/6 | 6/6 | 5/6 | 6/6 | removed 6, exposed 0 | 0 surviving |
| ภ.ง.ด.91 print-like **ตก** | 1.00 | 6/6 | 5/6 | 5/6 | 5/6 | removed 5, exposed 1 | 0 surviving |
| ภ.ง.ด.91 degraded **ตก** | 0.98 | 5/6 | 5/6 | 5/6 | 5/6 | removed 5, exposed 1 | 1 surviving |
| สปส.1-03 digital | 1.00 | 5/5 | 5/5 | 3/4 | 5/5 | removed 5, exposed 0 | 0 surviving |
| สปส.1-03 print-like | 1.00 | 5/5 | 5/5 | 4/4 | 5/5 | removed 5, exposed 0 | 0 surviving |
| สปส.1-03 degraded | 0.96 | 3/5 | 5/5 | 4/4 | 5/5 | removed 5, exposed 0 | 0 surviving |
| **รวม** | 9/9 image inputs measured | **39/45** | **41/45** | **36/42** | **41/45** | **removed 41, exposed 4, unmeasurable 0** | **3 surviving** |

ไม่มี declared decoy string ปรากฏในข้อความ extraction ของทั้ง 9 อินพุต. นี่เป็น
matcher-level check ไม่ใช่ false-positive benchmark ของ detector. ค่า OCR mean
นับเฉพาะค่าที่จับคู่กับช่วงข้อความได้แบบไม่ซ้ำ; ค่าที่จับคู่ไม่ได้ยังทำให้
extraction/coverage/residual fail. Exposed สี่ช่องคือชื่อผู้ร้องคนที่ 1 และคนที่ 2
ใน คร.1 print-like, กับชื่อคู่สมรสใน ภ.ง.ด.91 print-like และ ภ.ง.ด.91 degraded
(คนละอินพุต). ไม่มีช่องใด unmeasurable รอบนี้.

Render-OCR ของหน้าที่แก้ไขแล้วอ่านค่ากลับได้ 3 ช่องจาก 4 ช่องที่ expose. ชื่อผู้ร้อง
คนที่ 1 และ 2 ใน คร.1 print-like ระบบอ่าน OCR ต้นทางได้ที่ char_accuracy ราว 0.90
เท่านั้น (ไม่ตรงเป๊ะ). detector จึงตีความว่าไม่พบค่านั้น ไม่วาดกล่องดำ และ render-OCR
ก็อ่านชื่อกลับมาได้ตรง. ช่องชื่อคู่สมรสใน ภ.ง.ด.91 degraded ก็ถูก render-OCR อ่านกลับ
มาได้เช่นกันแม้ OCR ต้นทางจะอ่านถูก 100% เพราะ detector ไม่ติดป้าย NAME ให้เลย จึง
ไม่มีกล่องมาตั้งแต่ต้น. ส่วนชื่อคู่สมรสใน ภ.ง.ด.91 print-like expose เพราะกล่องดำครอบ
พื้นที่ได้ไม่ครบ (31.5%) ไม่ใช่เพราะ render-OCR อ่านได้.

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
ไม่เรียก `blind-v1` และ reveal log ขณะรันวันนั้นอยู่ที่ 4/6.

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

## ส่วนเพิ่มเติม 2026-08-02 ปิดกลไกตรวจจับสี่จุด

Investigation ในสาขา feat/ocr-detection-gaps พบว่ากลไกจริงไม่ใช่สองช่องว่างที่
ROADMAP เดิมระบุไว้. ระบบทนต่อ OCR ที่อ่านใกล้เคียงอยู่แล้ว (accuracy ขั้นต่ำ
0.8 ค่าที่ผิดหนึ่งหรือสองตัวอักษรยังถูกจับได้ในอินพุตที่ผ่านมาก่อนหน้านี้)
ประโยค “OCR อ่านคลาดหนึ่งตัวอักษรถูกมองว่าไม่พบค่า” จึงไม่ใช่สาเหตุจริง. กลไกที่
พบมีสี่จุด.

1. Degenerate whole-chunk CRF span. เมื่อ OCR มีสัญญาณรบกวนมาก thainer CRF
   อาจคืน span เดียวครอบทั้ง chunk ด้วย label ที่ไม่อยู่ใน LABEL_MAP (เช่น
   LAW) แล้วถูกทิ้งเงียบ ทำให้ทั้งเอกสารไม่มี entity เลย. แก้ด้วย
   degenerate-chunk guard ใน `tb_detector.py` ตรวจ span ที่ครอบ chunk core
   ตั้งแต่ 80% ขึ้นไปแล้ว retag เอกสารทีละบรรทัดแทน.
2. `_name_hygiene` เก็บส่วนหัวเมื่อ OCR วางป้ายฟอร์มไว้ก่อนชื่อ. เมื่อ span
   มาในลำดับ “เดือนปีเกิด\n\nกิตติ พรดี\nพิมพ์ใจ แสนดี” กติกาเดิมตัดที่
   newline แรกแล้วเก็บส่วนหัว ทำให้ป้ายฟอร์มกลายเป็นชื่อปลอมและชื่อจริงสองชื่อ
   หาย. แก้ด้วย label-aware `_name_hygiene` segmentation ที่แยก span เป็น
   ท่อนตาม newline ทิ้งท่อนที่ตรงป้ายฟอร์มหรือ compound ที่รู้จัก แล้วให้ท่อน
   ที่เหลือแต่ละท่อนเป็น NAME span ของตัวเอง.
3. Name shape ที่ต้องมีช่องว่าง. OCR ลบช่องว่างใน “สมชาย ใจดี” เหลือ
   “สมชายใจดี” ทำให้ fallback เดิมทุกทางไม่ผ่านเพราะต้องมีช่องว่างหรือสองกลุ่ม
   คำ. ป้าย “ชื่อ” ที่อยู่บรรทัดของตัวเองก็ไม่ vouch ให้บรรทัดถัดไปเพราะ
   delimiter เดิมไม่รวม newline. แก้ด้วย OCR-tolerant name shapes รวม newline
   label cue และการยอมรับ Thai token run เดี่ยวที่ไม่มีช่องว่างในบาง
   fallback ที่กำหนดขอบเขตไว้แคบ.
4. ค่า structured ซ้ำที่เพี้ยนจากการ merge retry ของ OCR (จุดที่ ROADMAP เดิม
   ไม่เคยตั้งชื่อ). การ merge retry อาจทิ้งสำเนาที่สองของค่า structured ที่
   เพี้ยนไว้ข้างค่าที่ถูกต้อง (เช่น `13122+1506581` ข้าง `1312271505581`)
   `detect_fp` ไม่จับสำเนาที่เพี้ยนเพราะไม่ตรง pattern หรือ checksum ทำให้เลข
   บัตรประชาชนหลุดไม่ถูกปิดบนเส้นทางข้อความ (`/api/sanitize`, roundtrip).
   เส้นทาง PDF ปลอดภัยอยู่แล้วเพราะกล่องดำครอบซ้อนกัน. แก้ด้วย corrupted-id
   FN scan ที่มี nearest-cue gate ในตัวสแกน false negative.

ทั้งสี่ปิดแล้วในคอมมิต 76eb9c4 ถึง 60955b6. `git diff 741c516..HEAD --
benchmark/` ว่างเปล่า ไม่มีการแก้ gate threshold หรือ expected value ใด ๆ
ในรอบนี้เลย.

### ผล acceptance รอบใหม่ (commit 60955b6 dirty false)

<!-- generated from gov-forms-2026-08-01-trackA/summary.json -->

| ฟอร์ม / modality | OCR mean | extraction | detection | type match | coverage | residual | render-OCR |
|---|---:|---:|---:|---:|---:|---:|---:|
| คร.1 digital | 0.95 | 4/4 | 4/4 | 4/4 | 4/4 | removed 4, exposed 0 | 0 surviving |
| คร.1 print-like | 0.95 | 2/4 | 4/4 | 4/4 | 4/4 | removed 4, exposed 0 | 0 surviving |
| คร.1 degraded | 0.95 | 3/4 | 4/4 | 4/4 | 4/4 | removed 4, exposed 0 | 0 surviving |
| ภ.ง.ด.91 digital | 1.00 | 6/6 | 6/6 | 5/6 | 6/6 | removed 6, exposed 0 | 0 surviving |
| ภ.ง.ด.91 print-like | 1.00 | 6/6 | 6/6 | 6/6 | 6/6 | removed 6, exposed 0 | 0 surviving |
| ภ.ง.ด.91 degraded | 0.98 | 5/6 | 6/6 | 6/6 | 6/6 | removed 6, exposed 0 | 0 surviving |
| สปส.1-03 digital | 1.00 | 5/5 | 5/5 | 3/4 | 5/5 | removed 5, exposed 0 | 0 surviving |
| สปส.1-03 print-like | 1.00 | 5/5 | 5/5 | 4/4 | 5/5 | removed 5, exposed 0 | 0 surviving |
| สปส.1-03 degraded | 0.96 | 3/5 | 5/5 | 4/4 | 5/5 | removed 5, exposed 0 | 0 surviving |
| **รวม** | 9/9 image inputs measured | **39/45** | **45/45** | **40/42** | **45/45** | **removed 45, exposed 0, unmeasurable 0** | **0 surviving** |

`acceptance_passed` เป็น `true` ครั้งแรก. Strict gate ผ่านทั้ง 9/9 อินพุต.
`residual_ocr_routes_measured` 9/9 `decoy_inputs_without_false_hits` 9/9.
extraction_found ยังอยู่ที่ 39/45 เท่าเดิมกับรอบ 2026-07-31 เพราะการจับคู่
whitespace ฝั่ง probe ไม่ถูกแก้ในรอบนี้และไม่มี gate คุมค่านั้น.

### Gold v4 ก่อนหลัง

main ที่ 741c516 recall 0.937 precision 0.816 F2 0.910 NAME recall 0.910
precision 0.953 negative false positive 33 เอกสาร.
สาขานี้ที่ commit สุดท้าย recall 0.948 precision 0.814 F2 0.918 NAME
recall 0.945 precision 0.954 negative false positive 33 เอกสาร (ไม่เปลี่ยน).

### ข้อสังเกตตรงไปตรงมา

- Synthetic expectations ยังเป็น developer-authored ไม่ผ่าน independent
  adjudication เหมือนเดิม. ท.ร.6 ยังไม่มีหลักฐาน physical scan และ handwriting
  ยังอยู่นอกขอบเขต.
- รอบ acceptance รอบกลางทางรัน 1 เจอ `RuntimeError` ที่ probe ภ.ง.ด.91
  digital หนึ่งครั้ง ตรวจแล้วเป็น transient เพราะอินพุตเดียวกันรันแยกเดี่ยว
  ผ่านปกติและไม่มี code path ใดโยน bare `RuntimeError` ตรง ๆ รอบถัดไปรันซ้ำ
  ผ่านทั้ง 9/9 และเป็นรอบที่บันทึกไว้ข้างต้น.
- Blind set ไม่ถูกแตะต้องในงานนี้ reveal log คงเดิม.

## ส่วนเพิ่มเติม 2026-08-04: current-tree rerun ยังไม่จบ

บน `main` ที่ commit `595b0aa` และ working tree สะอาด เรียก runner ด้วย
`.venv-full` และ output ใหม่ `benchmark/reports/gov-forms-2026-08-04-current-long`
โดยไม่ใช้ `--record-only`. Builder สร้าง input ครบ 9 รายการ แต่ process
หมดเวลา 30 นาทีหลังเขียนผลรายอินพุต 7 รายการแรก (คร.1 ทั้ง 3, ภ.ง.ด.91 ทั้ง 3
และ สปส.1-03 digital) จึงไม่มี `summary.json` และไม่มี aggregate verdict.

ผลรายอินพุตทั้ง 7 ไฟล์ไม่มี gate failure, ไม่มี residual exposure และไม่มีค่า
ที่ unmeasurable; นี่เป็น partial diagnostic evidence เท่านั้น ไม่ใช่ strict
acceptance pass. การรันก่อนหน้านี้ยังมี access violation ของ PaddlePaddle
Windows ที่จุดอื่นของ process ซึ่งเกิดซ้ำเมื่อ revert OCR กลับ `main`; รอบ
ปัจจุบันแสดงปัญหาอีกแบบคือเวลารันและ memory สูง (ประมาณ 3.4 GiB peak ที่
สังเกตได้) จนไม่จบภายใน timeout. ไม่มีการลด threshold, เปลี่ยน expected value
หรือข้าม modality. รายละเอียดนี้จึงคงสถานะ current-tree strict OCR เป็น
**unverified** และต้องใช้ environment/runtime ที่จบรันทั้ง 9 input ก่อนจึง
จะเลื่อนหลักฐานขึ้นเป็น pass.
