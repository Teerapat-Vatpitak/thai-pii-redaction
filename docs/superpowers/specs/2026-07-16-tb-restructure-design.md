# Restructure TB detection + honest type semantics (Horizon-2 #10) — Design

- วันที่: 2026-07-16
- สถานะ: อนุมัติ design แล้ว (brainstorm ร่วมกับผู้ใช้ สองคำถามหลักเคาะแล้ว) รอ implementation plan
- ที่มา: roadmap `2026-07-10-post-competition-longterm-roadmap.md` item #10

## ปัญหา

1. **Performance**: `tb_detector._ner_candidates` ใช้ sliding window ±3 ประโยคต่อประโยค แต่ละประโยคถูก NER tag ซ้ำ ~7 รอบต่อ engine ทำให้ WangchanBERTa (~1.3s/ประโยค CPU) และ union ช้าเกินใช้จริง
2. **Semantic โกหก**: ทุก DATE → DATE_OF_BIRTH, ทุก LOCATION → ADDRESS, ORGANIZATION ถูกทิ้ง, STUDENT_ID = เลข 8-12 หลักอะไรก็ได้, PASSPORT general catch-all กิน PO/invoice number — ทำ surrogate เพี้ยนในเอกสารธุรกิจ (เลข invoice กลายเป็นเลขสุ่ม เดทธุรกิจกลายเป็นวันเกิดปลอม)

## การตัดสินใจที่ล็อคแล้ว (จาก brainstorm)

| ประเด็น | ตัดสินใจ |
|---|---|
| นโยบายรวม | **"Mask เท่าเดิม label ซื่อสัตย์"** — ไม่มีอะไรที่เคย mask แล้วเลิก mask (recall ไม่ลด) เปลี่ยนเฉพาะ label ให้ตรงความจริง + surrogate ที่สมเหตุผลกับ label |
| DATE/LOCATION | NER LOCATION → type `LOCATION`, DATE → type `DATE` โดย **cue-based upgrade**: LOCATION→`ADDRESS` เมื่อมี address cue ใกล้ (ที่อยู่/บ้านเลขที่/อาศัยอยู่/พักอยู่/เลขที่ + ซอย/ถนน/ตำบล/แขวง/อำเภอ/เขต/จังหวัด); DATE→`DATE_OF_BIRTH` เมื่อมี birth cue (เกิด/วันเกิด/ว.ด.ป. เกิด) กลไก cue-window แบบเดียวกับ `_disambiguate_bank_phone` (มองย้อน/รอบ ~30 chars) |
| FP date | `fp_detector` regex วันที่ → `DATE` (default) ยกเว้น birth cue ใกล้ → `DATE_OF_BIRTH` |
| ORGANIZATION | เก็บและ **mask เป็น type ใหม่** (token `[องค์กร_n]`, surrogate จาก pool ชื่อองค์กรปลอม) เหตุผล ชื่อนายจ้าง/โรงพยาบาลเป็น quasi-identifier |
| STUDENT_ID | เลข 8-12 หลักเปล่า → type กลางใหม่ `ID_NUMBER` (ยัง mask, surrogate = เลขสุ่มยาวเท่าเดิม); เป็น `STUDENT_ID` เฉพาะมี cue รหัสนักศึกษา/รหัสนิสิต/student id |
| PASSPORT | Thai format `[A-Z]{2}\d{7}` (มี lookaround เดิม) ยังเป็น `PASSPORT`; general catch-all `[A-Z]{1,2}\d{6,9}` ต้องมี cue พาสปอร์ต/หนังสือเดินทาง/passport ไม่งั้น → `ID_NUMBER` |
| Windowing | `_ner_candidates` เปลี่ยนเป็น **stride chunk**: รวมประโยคติดกันเป็นก้อน core ≤ ~500 chars + margin 1 ประโยคหน้า/หลังเป็นบริบท; เก็บเฉพาะ span ที่ **start ใน core**; map offset กลับ global เหมือนเดิม; แต่ละประโยคถูก tag ~1.2x |
| Perf gate | unit test ด้วย spy engine: total chars tagged ≤ 1.5x ของความยาวข้อความ (เทียบของเดิม ~7x) |
| Recall gate | benchmark synthetic floors เดิม (CI) + `test_union_gold_validation` floors เดิม (ADDRESS ≥0.99, NAME ≥0.60, overall ≥0.83) ต้องผ่าน; ถ้า margin 1 ประโยคทำ recall ตก ให้ขยาย margin เป็น 2 ก่อนแตะอย่างอื่น |
| Gold set | relabel รายการที่ semantic เปลี่ยน (เช่น วันที่ไม่มี cue เกิด → DATE) ใน commit แยก พร้อมเหตุผลต่อรายการใน commit message; ห้ามลด floor ใดเพื่อให้ผ่าน — ถ้า floor ไม่ผ่านคือ bug ของ upgrade cue |
| Contract | `data_type` ใหม่ (LOCATION/DATE/ORGANIZATION/ID_NUMBER) เป็น additive บน `/api/sanitize` entities[] — extension แสดงค่าตรงๆ อยู่แล้ว ไม่ต้องแก้ |

## สิ่งที่ต้องเพิ่มตาม type ใหม่

- `anonymizer/token_generator.py` `TOKEN_LABEL`: `LOCATION: "สถานที่"`, `DATE: "วันที่"`, `ORGANIZATION: "องค์กร"`, `ID_NUMBER: "รหัสอ้างอิง"`
- `anonymizer/tb_generator.py`: pool `ORGANIZATIONS` (~15 ชื่อปลอม เช่น บริษัท เจริญวัฒนาการค้า จำกัด), branch `LOCATION` (เลือกจาก DISTRICTS เดิมโดยไม่มีเลขที่บ้าน), branch `DATE` (รูปแบบ dd/mm/yyyy พ.ศ. เหมือน DATE_OF_BIRTH เดิม), branch `ORGANIZATION`
- `anonymizer/fp_generator.py`: branch `ID_NUMBER` (เลขสุ่มยาวเท่า original — เหมือน STUDENT_ID เดิม) และ `DATE` (ใช้ `_gen_date` เดิม)
- `models.py` docstring รายการ data_type
- redact_type ของ `DATE`/`ID_NUMBER` จาก FP regex ยังเป็น "FP"; จาก NER ยังเป็น "TB" (เหมือนโครงเดิม)

## Testing

1. **Semantic unit tests** (`tests/test_step2_detection.py` เพิ่ม): เดทธุรกิจไม่มี cue → DATE ไม่ใช่ DATE_OF_BIRTH; มี cue เกิด → DATE_OF_BIRTH; สถานที่เปล่า (จังหวัดในประโยคข่าว) → LOCATION; ที่อยู่มี cue/บ้านเลขที่ → ADDRESS; ORGANIZATION โผล่และ mask; เลข 10 หลักไม่มี cue → ID_NUMBER; มี cue รหัสนักศึกษา → STUDENT_ID; PO1234567 → ID_NUMBER; มี cue พาสปอร์ต → PASSPORT
2. **Windowing tests** (`tests/test_ner_engine.py` หรือไฟล์ใหม่): spy engine นับ chars; boundary correctness (entity คร่อมรอยต่อ chunk ไม่หาย ไม่ซ้ำ); ผล detect_tb บนข้อความสั้น (ก้อนเดียว) เทียบเท่าของเดิม
3. **Regression**: full suite + benchmark synthetic (CI floors) + union gold validation + salt sweep `benchmark/sweep_web_guard.py` (TOTAL: 0)
4. **Round-trip**: e2e sanitize/reidentify กับข้อความธุรกิจที่มี invoice number + เดทประชุม → surrogate อ่านรู้เรื่อง (เลขยาวเท่าเดิม เดทยังเป็นเดท) restore กลับครบ

## ความเสี่ยงที่รับไว้

- Gold relabel เปลี่ยน per-type recall ตัวเลขบางช่อง (เช่น DATE_OF_BIRTH แถวที่กลายเป็น DATE) — ยอมรับเพราะ label ใหม่ตรงความจริงกว่า และ floor หลักผูกกับ NAME/ADDRESS/overall ที่ต้องคงเดิม
- Margin 1 ประโยคให้บริบทน้อยกว่า ±3 — มี fallback ขยายเป็น 2 ใน spec แล้ว วัดด้วย gold ก่อนตัดสิน
- ผู้ใช้ปลายทางเห็น token label ใหม่ ([วันที่_1], [องค์กร_1]) — เป็นการเปลี่ยนที่ตั้งใจและอ่านเข้าใจง่ายขึ้น

## นอกขอบเขต

- ไม่แตะ CLAUDE.md (sync หลัง merge), ไม่แตะ `tests/test_step11_api.py`/`test_api_hardening.py`
- ไม่ทำ per-type routing ของ engine (ADR union ครอบอยู่แล้ว)
- ไม่ปรับ reid_risk/report (ใช้ type ใหม่ได้ผ่าน generic path เดิม)
