# Thai PII recall benchmark — design (v1 synthetic)

- วันที่ 2026-07-13
- บริบท design doc เลือก tech stack (working doc ไม่ได้เผยแพร่) สรุปว่าสิ่งที่ต้องสร้างก่อนสิ่งเดียวเพื่อ de-risk ทุกการตัดสินใจคือ benchmark วัด recall PII ภาษาไทย เพราะตอนนี้ไม่มีตัวเลข recall PII ไทยจริงมา gate เอกสารนี้คือ spec ของ benchmark รอบแรก (v1 synthetic-only)
- เอกสารที่เกี่ยวข้อง production tech-stack selection design และ rust rewrite architecture design (จอง crate ชื่อ `benchmark` ไว้แล้ว) ทั้งสองเป็น working doc ที่เก็บไว้ในเครื่อง ไม่ได้เผยแพร่ตามเกณฑ์ใน [README](README.md), [post-competition roadmap](2026-07-10-post-competition-longterm-roadmap.md)
- สถานะ อนุมัติดีไซน์แล้ว รอ review spec ก่อนเขียน plan
- ขอบเขต v1 synthetic-only วัด detector ที่ product ใช้จริง gold set เอกสารจริงเป็น follow-up คนละ spec

## เป้าหมาย

วัด recall (และ precision F1 F2) ของ detection layer ปัจจุบันบน corpus PII ภาษาไทยสังเคราะห์ที่รู้ ground-truth span แน่นอน เพื่อ

1. ได้ตัวเลข recall PII ไทยจริงของระบบเรา แทนการอ้าง proxy จาก ThaiNER
2. เทียบ thainer-CRF vs WangchanBERTa (thainer-v2) บนข้อมูลของเราเอง เพื่อยืนยันหรือหักล้างข้อสรุปของ design doc ก่อน commit ทิศทาง
3. เป็น regression gate กัน recall leak กลับมา (ต่อยอด `tests/test_recall_leaks.py`)
4. เป็น oracle ให้การ rewrite ในอนาคต ต้องพิสูจน์ recall parity ก่อน/หลัง

## หลักการที่ยึด

- recall มากกว่า precision รายงาน F2 (beta=2) เป็นตัวพาดหัว
- ไม่มี dependency ใหม่ scorer และ corpus generator เขียนเองใน repo (ตอบคำถาม brainstorm)
- วัด detector ที่ product ใช้จริง ไม่ใช่ path ที่ไม่มีใครเรียก ดังนั้น benchmark เรียก assembly เดียวกับ `/api/sanitize`
- deterministic corpus seed ได้ ผลซ้ำได้ CI ไม่ flaky
- single source of truth ของ format ค่า PII สังเคราะห์มาจาก generator ที่มีอยู่ ไม่ปั้น format ซ้ำ

## โครงสร้างโมดูล

top-level package `benchmark/` (ชื่อเดียวกับ Rust crate ที่ spec rust-rewrite จองไว้ ชื่อ carry over ตอน cutover)

| ไฟล์ | หน้าที่ |
|---|---|
| `benchmark/__init__.py` | package marker |
| `benchmark/types.py` | dataclass `GoldSpan(start, end, entity_type)` และ `Sample(text, spans, template_id, slice)` |
| `benchmark/corpus.py` | สร้าง corpus สังเคราะห์ `build_corpus(seed, size) -> list[Sample]` เติม slot ในเทมเพลตไทย track offset ได้ ground-truth span แม่นยำ |
| `benchmark/scorer.py` | จับคู่ span + คำนวณ metric `score(gold_samples, predictions) -> Report` |
| `benchmark/runner.py` | ต่อทุกอย่าง `run_benchmark(engine, seed, size) -> Report` build corpus แล้วรัน detection แล้ว score แล้ว render |
| `benchmark/__main__.py` | CLI `python -m benchmark --engine crf --seed 42 --size 200 [--json out.json]` |
| `tests/test_benchmark.py` | เทสต์ corpus span-alignment เทสต์ scorer ด้วยเคสคำนวณมือ และ CI gate assert recall floor (ใช้ CRF) |

## ชนิด entity และการ map

gold label ใช้ชื่อชนิดตรงกับที่ detector emit เพื่อเทียบด้วย type equality ตรงๆ

- FP structured THAI_ID PHONE EMAIL BANK_ACCOUNT CREDIT_CARD PASSPORT VEHICLE_PLATE STUDENT_ID DATE_OF_BIRTH
- TB free-text NAME ADDRESS DATE_OF_BIRTH

หมายเหตุการ map ที่ต้องระวัง detector map วันที่ทั้งจาก TB (DATE ไป DATE_OF_BIRTH) และ FP regex ไป DATE_OF_BIRTH ดังนั้น gold วันที่ทั้งหมด label เป็น DATE_OF_BIRTH ที่อยู่ detector emit เป็น ADDRESS (map จาก LOCATION) ชื่อ+สกุล detector emit เป็น NAME เดียวเสมอ (ไม่มี SURNAME แยก) ดังนั้น gold ก็ label ทั้งก้อน นาย + ชื่อ + สกุล เป็น NAME span เดียว scorer มี type-equivalence map เผื่อ IBAN/BANK และ DATE variants

## corpus design

- เทมเพลตประโยค/เอกสารไทยจริงหลายแนว อีเมลลาป่วย เอกสารราชการ ฟอร์มสมัคร ใบคำร้อง แชทร้องเรียน แต่ละเทมเพลตมี placeholder เช่น `{name}` `{thai_id}` `{phone}` วางในบริบทที่มี cue จริง (นาย ที่อยู่ เลขบัตร)
- ตอน render generator เดินทีละ placeholder แทนค่าแล้วบันทึก (start, end, entity_type) ของ substring ที่วาง จึงได้ ground-truth span แม่นยำ 100% ไม่ต้อง label มือ และไม่ต้องเดา offset ทีหลัง
- ค่าที่เติม reuse ตรงจาก generator ที่มีอยู่ import `pii_redactor.anonymizer.fp_generator` (helper `_gen_thai_id` `_gen_credit_card` `_gen_phone` `_gen_passport` `_gen_vehicle_plate` ที่รับ rng และคืนค่า format ถูก checksum ผ่าน) และ pool จาก `tb_generator` (MALE_NAMES FEMALE_NAMES SURNAMES DISTRICTS) benchmark เป็น internal module การ import helper ภายในยอมรับได้ เพื่อคง single source ของ format สำหรับชนิดที่ helper ต้องการ original (bank/date/generic/student_id) ส่ง template original ให้
- สอง slice ใน corpus
  - `core` เคสทั่วไป กระจายทุกชนิด entity หลายเทมเพลต
  - `hard_case` เคสที่เคยเป็น recall leak PII ติดอักษรไทย (เลขบัตรประชาชน1101700230708) +66 mobile ทั้งมีและไม่มีเว้นวรรค/วงเล็บ อีเมลติดตัวอักษรไทย ตรงกับที่ `tests/test_recall_leaks.py` คุ้ม เพื่อให้ benchmark เป็น regression guard ด้วย
- deterministic RNG seed จาก `--seed` (default 42) จำนวน sample จาก `--size` (default 200) corpus เดิม seed เดิม ได้ผลเดิมทุกครั้ง

## scorer design

จับคู่ span สองมุมพร้อมกัน เพราะ redaction ต้องการมากกว่า จับได้หรือไม่

1. entity recall แบบ type-aware overlap ต่อชนิด entity รวบ gold spans G และ predicted spans P ชนิดเดียวกัน greedy match แต่ละ gold กับ predicted ที่ overlap (intersection มากกว่า 0) TP = gold ที่จับคู่ได้ FN = gold ที่เหลือ FP = predicted ที่เหลือ ได้ precision recall F1 F2 ต่อชนิดและรวม micro/macro
2. coverage recall แบบ type-agnostic เศษของ char ใน gold ที่ถูกครอบด้วย union ของ predicted span ใดๆ (ไม่สนชนิด) เพราะสำหรับ blackout การจับได้ครึ่งเบอร์โทรยังเหลือ PII โผล่ = ยัง leak มุมนี้จับ partial coverage ที่ overlap มองข้าม เป็นตัวเลขที่ตรงกับความเสี่ยง product ที่สุด
3. exact-boundary recall รายงานเสริม สัดส่วน gold ที่มี predicted span ตรง boundary เป๊ะ ใช้ดู boundary quality (CRF ชอบ clip)

report เป็น dataclass `Report` แปลงเป็น JSON ได้

```
Report {
  engine, seed, size,
  corpus: { samples, entities, by_type: {type: count} },
  overall: { precision, recall, f1, f2, coverage_recall, exact_recall },
  by_type: { type: { tp, fp, fn, precision, recall, f1, f2 } },
  by_slice: { core: {...overall...}, hard_case: {...overall...} },
}
```

render สอง format ตารางอ่านคนออก stdout และ JSON เต็มเมื่อ `--json path` (report ไม่ commit ลง repo อยู่ใน .gitignore)

## runner + detection assembly

- runner รัน detection แบบเดียวกับ product `/api/sanitize` เป๊ะ เพื่อวัดสิ่งที่ ship จริง
- targeted improvement แยก assembly (detect_fp + detect_tb + scan_fn + dedupe) ออกเป็นฟังก์ชันร่วม `detect_all(text) -> list[Entity]` แล้วให้ `app/server.py` `_tokenize` และ benchmark เรียกตัวเดียวกัน กันไม่ให้ benchmark drift จากสิ่งที่ ship (ตอน implement อ่าน `_tokenize` จริงก่อน ถ้า assembly ซับซ้อนกว่าคาดให้ reproduce ให้ตรง)
- engine เป็น process-global ( `tb_detector` อ่าน `AIGUARD_NER_ENGINE` ครั้งเดียวต่อ process ผ่าน lazy singleton) ดังนั้น runner หนึ่ง process = หนึ่ง engine การเทียบ CRF vs WangchanBERTa = รัน runner สอง process (CLI สองครั้งด้วย `--engine` ต่างกัน) comparison script วน/พิมพ์ตารางเทียบ ไม่พยายาม reset singleton ใน process เดียว

## การเทียบ CRF vs WangchanBERTa

- ติดตั้ง `requirements-ml.txt` (transformers/torch) ใน venv แล้วรัน `python -m benchmark --engine crf` และ `--engine wangchanberta` บน corpus seed เดียวกัน
- ออกตารางเทียบ recall/F2 per-type ทั้งสอง engine เป็น deliverable ของรอบนี้ เพื่อพิสูจน์ข้อสรุป design doc ด้วยข้อมูลไทยของเรา ไม่ใช่ ThaiNER proxy
- WangchanBERTa ไม่เข้า CI gate (หนัก + ช้า + ต้อง torch) เป็น script/marker opt-in `@pytest.mark.ml` ที่ skip เมื่อไม่มี transformers เหมือน `tests/test_ner_engine.py` เดิม

## testing (TDD)

- corpus เทสต์ทุก sample `text[start:end] == ` ค่าที่วาง (span alignment) และทุกชนิด entity ปรากฏใน corpus อย่างน้อย N ครั้ง และ hard_case slice มีเคส leak ครบ
- scorer เทสต์ด้วยเคสเล็กที่คำนวณ TP/FP/FN มือได้ overlap match ตรงมุม coverage คำนวณถูก F2 สูตรถูก เคส no-prediction เคส over-prediction เคส boundary-clip
- CI gate `tests/test_benchmark.py` build corpus seed คงที่ รัน CRF detection assert floor
  - structured FP ทุกชนิด recall เกือบ 1.0 (checksum/regex บน synthetic valid format ควรได้เต็ม) ตั้ง floor 0.99
  - overall coverage_recall floor และ NAME/ADDRESS recall floor calibrate จากผลรันจริงรอบแรก ตั้งต่ำกว่าที่วัดได้เล็กน้อยเพื่อไม่ flaky (plan จะรันแล้วเซ็ตตัวเลข)
  - hard_case slice recall floor สูง เพราะเป็น leak ที่แก้ไปแล้ว

## ผลรัน v1 (2026-07-13 seed 42 size 200 หลังแก้ dedup)

รันจริง CRF vs WangchanBERTa (thainer-v2) บน corpus สังเคราะห์เดียวกัน ตัวเลขนี้คือหลังแก้ dedup (FP ชนะ NER เมื่อ overlap ดูข้อ 3)

| ชนิด | n | CRF recall | WangchanBERTa recall | ผล |
|---|---|---|---|---|
| ADDRESS | 32 | 0.406 | 1.000 | +0.594 หัวข้อสำคัญ |
| NAME | 160 | 0.994 | 0.994 | เสมอ |
| EMAIL | 50 | 1.000 | 1.000 | เสมอ |
| BANK_ACCOUNT | 38 | 0.921 | 0.921 | เสมอ |
| CREDIT_CARD PASSPORT PHONE STUDENT_ID THAI_ID VEHICLE_PLATE DATE_OF_BIRTH | รวม 358 | 1.000 | 1.000 | เสมอ |
| OVERALL | 598 | 0.962 | 0.993 | +0.031 |
| coverage_recall | | 0.946 | 0.980 | +0.034 |
| precision overall | | 0.924 | 0.891 | ถอยเล็กน้อย ยอมได้ตาม recall-first |
| hard_case recall | | 1.000 | 1.000 | เสมอ |

หลังแก้ dedup WangchanBERTa ชนะหรือเสมอ CRF ทุกชนิด ไม่มีจุดถอยเหลือ

ข้อสรุปจากตัวเลขจริงของเรา ไม่ใช่ ThaiNER proxy

1. WangchanBERTa ยก ADDRESS recall จาก 0.406 เป็น 1.000 นี่คือ gap free-text ที่ design doc ทำนายไว้ ยืนยันด้วยข้อมูลเราเอง คุ้มค่าต่อ invariant recall > precision
2. NAME เสมอที่ 0.994 เพราะ corpus สังเคราะห์ใส่ cue นาย/นาง/นางสาว ทุกชื่อ ซึ่ง name_context booster จับได้อยู่แล้ว การพิสูจน์ NAME จริงต้องมีชื่อที่ไม่มี title cue (gold set)
3. finding ที่ benchmark ขุดเจอและแก้แล้ว รอบแรก WangchanBERTa ทำ EMAIL ถอย 1.000 เป็น 0.940 และ hard_case ถอย เป็น 0.925 ทั้งที่ EMAIL เป็น FP regex สาเหตุคือ span ของ WangchanBERTa ที่กว้างกว่าไป overlap แล้วชนะ FP span ใน `dedupe_spans` (เดิมเลือก start ก่อน แล้วยาวกว่า ไม่สน redact_type) แก้โดยให้ FP วางก่อน TB ใน dedup FP ที่ผ่าน checksum จึงไม่ถูก NER span กลบ ผลหลังแก้ EMAIL กลับเป็น 1.000 hard_case กลับเป็น 1.000 NAME precision กลับเป็น 1.000 และ ADDRESS ยังคง 1.000 ไม่ regress (`pii_redactor/detectors/aggregate.py`, เทสต์ `test_dedupe_prefers_fp_over_overlapping_tb`)
4. BANK_ACCOUNT 0.921 ทั้งสอง engine เพราะเลขบัญชี 10 หลักที่ขึ้นต้น 06-09 ชนกับ mobile ถูก label PHONE (coverage ปลอดภัย) เป็น ambiguity เชิง format ไม่ใช่ recall leak
5. structured FP ทุกชนิด 1.000 ทั้งสอง engine เพราะ synthetic format ตรงกับ detector การพิสูจน์จริงต้องใช้ gold set เอกสารจริง (v2)

caveat หลัก นี่เป็น synthetic ที่ structured type ง่ายเกินจริง ตัว discriminator จริง (ADDRESS และ NAME ไม่มี cue) ต้องรอ gold set แต่ผล ADDRESS หนักแน่นพอจะสนับสนุนทิศทาง WangchanBERTa แล้ว

## สิ่งที่ไม่อยู่ใน v1 (YAGNI)

- gold set เอกสารจริง label มือ เป็น spec แยก ต้องมีข้อมูลจริงและเวลา label
- presidio-evaluator ไม่ใช้ dep หนัก เขียน scorer เอง
- OCR/PDF path benchmark วัดเฉพาะ text detection ก่อน
- reset NER singleton ใน process เดียว ใช้ two-process comparison แทน
