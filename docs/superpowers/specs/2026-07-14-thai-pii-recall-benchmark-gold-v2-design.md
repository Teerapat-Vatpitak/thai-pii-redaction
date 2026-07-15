# Thai PII recall benchmark v2 — hand-authored gold set (design)

- วันที่ 2026-07-14
- บริบท benchmark v1 (synthetic) พิสูจน์ได้ว่า WangchanBERTa ยก ADDRESS recall แต่ structured type ง่ายเกินจริงและ NAME เสมอเพราะ corpus ใส่ title cue ทุกชื่อ v2 คือ gold set เขียนมือที่จงใจเจาะจุดบอดของ v1 เพื่อ external validity จริง
- เอกสารที่เกี่ยวข้อง [benchmark v1 design](2026-07-13-thai-pii-recall-benchmark-design.md), [production tech-stack selection](2026-07-13-production-tech-stack-selection-design.md)
- สถานะ อนุมัติดีไซน์แล้ว ผู้ใช้ให้ลุยต่อ
- ขอบเขต hand-authored gold (PII ปลอมแต่สมจริง privacy-safe commit ได้) reuse scorer v1 ทั้งดุ้น บวกแก้ ambiguity BANK vs PHONE ที่ v1 ขุดเจอ

## เป้าหมาย

1. วัด recall บนเคสยากที่ v1 พิสูจน์ไม่ได้ ชื่อไม่มี title cue ที่อยู่หลากรูป ข้อความ messy จริง
2. เห็นช่องว่าง CRF vs WangchanBERTa บนเคสจริง ไม่ใช่ synthetic ที่ทั้งคู่เกือบเต็ม
3. แก้ ambiguity BANK vs PHONE (เลข 10 หลักขึ้นต้น 06-09) ด้วย context rule พร้อม gold ยืนยัน

## หลักการ

- gold เป็น diagnostic เผยจุดอ่อน ไม่ใช่ hard gate ไม่ตั้ง recall floor แข็งแบบ v1 (จะ fail ตามธรรมชาติ) รายงานตัวเลขตรงๆ
- PII ปลอมทั้งหมด ไม่มี PII คนจริง เพราะ product นี้เป็นเครื่องมือ privacy การเก็บ PII จริงใน repo ขัดกันเอง
- reuse [benchmark/scorer.py](../../../benchmark/scorer.py) เดิม ไม่แตะ ไม่มี dependency ใหม่
- span ถูก 100% โดยไม่นับ offset มือ ใช้ inline markup + parser

## โครงสร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `benchmark/gold.py` | `GOLD_DOCS` เอกสาร annotate ~60-80 ชิ้น + `parse_gold()` ถอด markup เป็น Sample + `load_gold()` + `GOLD_SLICES` |
| `benchmark/runner.py` (แก้) | เพิ่ม param `source="synthetic"|"gold"` เมื่อ gold ใช้ `load_gold()` แทน `build_corpus()` |
| `benchmark/__main__.py` (แก้) | เพิ่ม `--source synthetic|gold` |
| `pii_redactor/detectors/fp_detector.py` (แก้) | disambiguate BANK vs PHONE เมื่อ span ชนกันด้วย context cue |
| `tests/test_benchmark_gold.py` | parse round-trip, category coverage, bank/phone fix, gold diagnostic |

## รูปแบบ markup

เขียนเอกสารพร้อมป้ายในบรรทัด `[[TYPE|value]]` เช่น

```
เรียน [[NAME|สมชาย ใจดี]] ตามที่ท่านแจ้งเลขบัญชี [[BANK_ACCOUNT|0612345678]] ...
```

`parse_gold` ใช้ regex `\[\[([A-Z_]+)\|(.*?)\]\]` เดินทีละ match ต่อ plain text แล้วบันทึก `GoldSpan(start, end, TYPE)` ตาม offset ใน plain text จึงได้ span ตรงเป๊ะ round-trip `text[start:end] == value` ต้องจริงทุก span

TYPE ใช้ชุดเดียวกับ detector NAME ADDRESS DATE_OF_BIRTH THAI_ID PHONE EMAIL BANK_ACCOUNT CREDIT_CARD PASSPORT VEHICLE_PLATE STUDENT_ID

## 4 slice

- `name_no_cue` ชื่อไม่มี นาย/นาง/นางสาว ชื่อลอยกลางประโยค เซ็นชื่อท้าย (ลงชื่อ ... โดยไม่มี title) ชื่อในตาราง ชื่อหลัง โดย/ผู้รับผิดชอบ จุดนี้ name_context booster ช่วยไม่ได้ (มันพึ่ง title cue) เป็นตัววัด recall จริงของ CRF vs WangchanBERTa
- `address_varied` ที่อยู่หลายรูป เต็ม (บ้านเลขที่ ซอย ถนน ตำบล/แขวง อำเภอ/เขต จังหวัด รหัสไปรษณีย์) ย่อ หลายบรรทัด เพื่อวัด ADDRESS recall และคุณภาพ boundary
- `messy` PII ติดข้อความ เว้นวรรคเกิน/ขาด ไทยปนอังกฤษ (label แบบ Tel: Email:) หลายบรรทัด และ OCR-substitution เล็กน้อย จุดนี้เผย robustness นอก distribution สะอาด
- `bank_phone` เลข 10 หลักขึ้นต้น 06-09 คู่กัน แบบมี cue บัญชี/ธนาคาร (ควร BANK) และ cue โทร/เบอร์ (ควร PHONE) เพื่อ track การแก้ ambiguity

แต่ละ doc มี field slice เดียว จำนวนเป้าหมาย ~15-20 ต่อ slice รวม ~60-80

## การแก้ BANK vs PHONE

ราก เลข 10 หลักขึ้นต้น 0[6-9] match ทั้ง mobile PHONE และ BANK_ACCOUNT ใน `detect_fp` PHONE ถูก append ก่อน BANK ที่ score เท่ากัน `_deduplicate` จึงเก็บ PHONE เสมอ

แก้ เพิ่ม disambiguation ใน `detect_fp` ก่อน `_deduplicate` ถ้ามี PHONE กับ BANK candidate ที่ span เดียวกัน ดู context ก่อนหน้า ~15 char ถ้าเจอ cue บัญชี/ธนาคาร/เลขที่บัญชี ให้ทิ้ง PHONE เก็บ BANK ถ้าเจอ cue โทร/เบอร์/มือถือ ให้ทิ้ง BANK เก็บ PHONE ถ้าไม่มี cue คงพฤติกรรมเดิม (PHONE ชนะ) ทำเป็นฟังก์ชันเดียว testable ไม่แตะ score model ที่ที่อื่นใช้

## กติกาการวัด

- reuse `score()` เดิม รายงาน per-type + per-slice + CRF vs WangchanBERTa
- ไม่มี hard recall floor สำหรับ NAME/ADDRESS (gold ตั้งใจให้ยาก)
- targeted test ที่ต้องเขียว parse round-trip ทุก span, ทุก slice ไม่ว่าง, bank/phone rule ถูก, และ structured type ที่รูปแบบชัด (THAI_ID EMAIL) ยังจับได้สูงบน gold
- WangchanBERTa gold comparison เป็น opt-in skip เมื่อไม่มี transformers

## deliverable

รัน `python -m benchmark --source gold --engine crf` และ `--engine wangchanberta` ออกตารางเทียบว่า WangchanBERTa ช่วย NAME-ไม่มี-cue กับ ADDRESS-หลากรูป จริงแค่ไหนบนเคสยาก บันทึกผลลง spec นี้เป็น record

## ผลรัน v2 (gold) 2026-07-14 seed 42

รันจริง CRF (thainer) เทียบ WangchanBERTa (thainer-v2) บน gold set เดียวกัน 64 เอกสาร 81 entity หลังแก้ BANK vs PHONE ตัวเลขจาก `benchmark/reports/gold-crf.json` และ `gold-wcb.json`

### recall ต่อชนิด

| ชนิด | n | CRF recall | WCB recall | ผล |
|---|---|---|---|---|
| ADDRESS | 17 | 0.882 | 1.000 | WCB ชนะ +0.118 |
| NAME | 28 | 0.607 | 0.357 | CRF ชนะ +0.250 |
| PHONE | 16 | 0.875 | 0.875 | เสมอ (FP regex) |
| BANK_ACCOUNT | 9 | 1.000 | 1.000 | เสมอ หลัง fix |
| EMAIL | 4 | 1.000 | 1.000 | เสมอ |
| THAI_ID | 2 | 1.000 | 1.000 | เสมอ |
| CREDIT_CARD | 1 | 1.000 | 1.000 | เสมอ |
| DATE_OF_BIRTH | 1 | 1.000 | 1.000 | เสมอ |
| STUDENT_ID | 1 | 1.000 | 1.000 | เสมอ |
| PASSPORT | 1 | 0.000 | 0.000 | พลาดทั้งคู่ (Thai-glue) |
| VEHICLE_PLATE | 1 | 0.000 | 0.000 | พลาดทั้งคู่ (Thai-glue) |
| OVERALL | 81 | 0.790 | 0.728 | CRF สูงกว่า NAME ฉุด WCB |
| coverage_recall | | 0.654 | 0.628 | |
| precision overall | | 0.621 | 0.615 | |

### recall ต่อ slice

| slice | CRF recall | CRF cov | WCB recall | WCB cov |
|---|---|---|---|---|
| name_no_cue | 0.714 | 0.672 | 0.381 | 0.421 |
| address_varied | 0.875 | 0.543 | 1.000 | 0.586 |
| messy | 0.679 | 0.792 | 0.679 | 0.749 |
| bank_phone | 1.000 | 1.000 | 1.000 | 1.000 |

### อ่านผล

1. address_varied ยืนยันซ้ำผล v1 WangchanBERTa ยก ADDRESS recall 0.882 เป็น 1.000 (slice 0.875 เป็น 1.000) บนที่อยู่จริงหลากรูป ไม่ใช่ synthetic นี่คือ payoff free-text ที่ v2 ตั้งใจวัด
2. name_no_cue พลิกคาดจากที่ handoff เดา บนชื่อไม่มี title cue WangchanBERTa recall ตกเหลือ 0.357 (slice 0.381) ต่ำกว่า CRF 0.607 (slice 0.714) โดย precision WCB เต็ม 1.000 แปลว่า transformer อนุรักษ์นิยม จับเฉพาะที่มั่นใจ ชื่อไทยลอยกลางประโยคจึงหลุดเยอะ ผล v1 ที่ NAME เสมอ 1.000 มาจาก corpus ใส่ title ทุกชื่อ พอถอด cue ออก WangchanBERTa ไม่ได้เหนือ CRF อัตโนมัติ นี่คือ external validity ที่ v1 พิสูจน์ไม่ได้
3. bank_phone ทั้งสอง engine recall 1.000 coverage 1.000 ยืนยัน context rule BANK vs PHONE ทำงานครบทั้ง 16 เคส รวมเคสที่ cue บัญชี/ธนาคาร ห่างเลขเกิน 15 char (bp05 27char bp09 24char) ซึ่งบังคับให้ขยาย window เป็น 30 และเลือก cue ที่ใกล้เลขที่สุด แทน bank-precedence เดิมในแผน (window 15 จะพลาด 2 เคสนี้)
4. OVERALL CRF 0.790 สูงกว่า WCB 0.728 สวนทาง v1 (WCB ชนะทุกชนิด) เพราะ gold ตัด title cue ออก NAME ที่เคยเสมอกลายเป็นจุดที่ CRF นำ ภาพรวมจึงไม่ใช่ WCB ดีกว่าเด็ดขาด แต่เป็น trade รายชนิด ADDRESS เลือก WCB ส่วน NAME-ไม่มี-cue เลือก CRF การเลือก engine จริงจึงควรพิจารณา ensemble หรือ route ตามชนิด
5. finding นอกแผน PASSPORT และ VEHICLE_PLATE บน messy พลาดทั้งสอง engine (recall 0.000 n1) เพราะ PII ติดอักษรไทย ms13 `AB1234567` ติด `ที่` ทำให้ `\b` ไม่ยิง ms11 `ขก 4471` ติด `รถ` โดน mid-word guard ตัดทิ้ง เป็น recall leak คลาสเดียวกับที่ PR #25 แก้ให้ตัวเลข (เปลี่ยนเป็น lookaround) แต่ passport/plate ยังใช้ `\b`/guard เดิม

   แก้แล้ว (คอมมิตถัดจาก v2) passport เปลี่ยน `\b` เป็น alnum-boundary lookaround plate ผ่อน mid-word guard เมื่อมี cue `ทะเบียน` นำหน้าใน ~15 char ผลรัน gold CRF ซ้ำ PASSPORT 0.000 เป็น 1.000 VEHICLE_PLATE 0.000 เป็น 1.000 messy slice 0.750 OVERALL 0.815 BANK/PHONE คงเดิม regression test อยู่ที่ `tests/test_recall_leaks.py` (Leak 4) หมายเหตุ VEHICLE_PLATE precision ยังต่ำ (ที่อยู่รูป `ซอย N` ถูกจับเป็นป้ายเพราะ regex หลวม) เป็น FP เดิมก่อน fix ไม่กระทบ recall product recall-first ยอมได้

## ไม่อยู่ใน v2 (YAGNI)

- real document ของผู้ใช้ (private local hook) เลื่อนไป ถ้าผู้ใช้อยากเสียบทีหลัง harness `--source gold` รองรับได้อยู่แล้วโดยชี้ไฟล์
- OCR/PDF gold แยก
- Thai-digit PII (๐๘๑) เป็นเรื่องของ cleaning layer ก่อน detection ไม่ใช่จุดวัดของ benchmark นี้ ใส่ได้ 1-2 เคสเป็น documented gap ไม่ให้กระทบภาพรวม
