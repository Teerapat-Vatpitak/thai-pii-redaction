# NER engine strategy comparison — วัด 4 กลยุทธ์บน benchmark (design)

- วันที่ 2026-07-15
- บริบท gold v2 ([2026-07-14 design](2026-07-14-thai-pii-recall-benchmark-gold-v2-design.md)) เผยว่าบนชื่อไม่มี title cue WangchanBERTa recall แพ้ CRF สวนทางกับ [stack-selection doc](2026-07-13-production-tech-stack-selection-design.md) ที่แนะนำ WCB เป็น primary เอกสารนี้คือ spec ของงานวัด 4 กลยุทธ์ NER บน benchmark เพื่อ gate การตัดสิน engine ด้วยข้อมูลของเราเอง
- สถานะ อนุมัติดีไซน์แล้ว (brainstorm) รอเขียน plan
- ขอบเขต เพิ่มการวัดเข้า harness แล้วออก ADR ไม่แตะ product `detect_tb`/`detect_all`

## ปัญหา

stack-selection doc (2026-07-13) แนะนำเปลี่ยน NER หลักเป็น WangchanBERTa (thainer-v2) อ้างตัวเลข ThaiNER PERSON recall 0.79 ไป 0.95 LOCATION 0.68 ไป 0.88 แต่ gold v2 (2026-07-14) วัดของเราเองแล้วเจอตรงข้าม บน slice name_no_cue WCB recall 0.357 แพ้ CRF 0.607 เพราะตัวเลขที่ doc อ้างเป็น in-distribution ที่ใส่ title cue ครบ พอถอด cue ออกภาพจริงต่าง

ตอนนี้เรามีแค่ตัวเลข CRF-เดี่ยว กับ WCB-เดี่ยว ยังไม่มีตัวเลขของ union (CRF ∪ WCB) หรือ route-by-type ซึ่งเป็นทางที่ invariant recall มากกว่า precision ชอบ ตัดสิน engine ไม่ได้ถ้าไม่วัดสองทางนี้ก่อน

## เป้าหมาย

1. วัด 4 กลยุทธ์ NER บน benchmark ทั้ง gold และ synthetic ได้ per-type recall/precision มา gate การตัดสิน
2. ออก ADR เป็น record การตัดสิน engine strategy พร้อม trade-off
3. ไม่แตะ product detect_tb การ implement กลยุทธ์ที่เลือกเป็นงานถัดไปหลัง ADR

## 4 กลยุทธ์

1. `crf` thainer CRF เดี่ยว (default ปัจจุบัน เร็ว offline)
2. `wcb` WangchanBERTa/thainer-v2 เดี่ยว
3. `union` CRF ∪ WCB รวม span ทั้งคู่แล้ว dedup แนว recall-first
4. `route` NAME กับชนิดที่เหลือจาก CRF ส่วน ADDRESS จาก WCB (encode gold finding ตรงๆ)

## กลไก merge

harness รันทั้ง 2 engine ในโปรเซสเดียว reset process-global singleton `tb_detector._ner` แบบเดียวกับ `run_benchmark` แล้วเก็บ Entity ต่อ sample 2 ชุด (`ents_crf`, `ents_wcb`) จากนั้นประกอบ

- union `dedupe_spans(ents_crf + ents_wcb)` เก็บทุก span ตัด overlap ด้วย logic จริงของ product
- route `dedupe_spans([e for e in ents_crf if e.data_type != "ADDRESS"] + [e for e in ents_wcb if e.data_type == "ADDRESS"])`

FP entity (ID phone email bank card passport plate student date) เหมือนกันทั้ง 2 engine เพราะมาจาก regex/checksum ไม่พึ่ง NER `dedupe_spans` จัดการ dup ให้เอง ตัวที่ต่างจริงมีแค่ TB (NAME ADDRESS DATE)

## โครงสร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `benchmark/runner.py` (แก้) | เพิ่ม `run_strategy_comparison(source, seed, size) -> {strategy: report}` |
| `benchmark/__main__.py` (แก้) | เพิ่ม flag `--compare-strategies` พิมพ์ตารางเทียบ 4 กลยุทธ์ |
| `tests/test_benchmark_strategies.py` | เทสต์ merge semantics + comparison run |
| `docs/superpowers/specs/2026-07-15-ner-engine-strategy-decision.md` | ADR (สร้างหลังรัน ได้ตัวเลขจริง) |

## Interface

`run_strategy_comparison(source="synthetic", seed=42, size=200) -> dict[str, dict]` คืน dict 4 key `crf` `wcb` `union` `route` แต่ละ value เป็น report แบบเดียวกับ `score()` (มี `by_type` `by_slice` `overall` `corpus`) เรียก `detect_all` ต่อ sample รอบละ engine (CRF และ WCB รวม 2 รอบต่อ sample) แล้ว reuse `benchmark.scorer.score` เดิม ไม่เขียน scorer ใหม่

CLI `python -m benchmark --compare-strategies --source gold|synthetic [--seed --size --json out.json]` พิมพ์ตารางเทียบ per-type recall/precision 4 คอลัมน์ และเขียน JSON เป็น dict 4 key ถ้าให้ `--json`

## Testing (TDD)

- union recall ต่อชนิด `>=` max(crf, wcb) บน sample ประกอบมือ (union เป็น superset ของ recall)
- route ADDRESS span มาจาก WCB จริง (ต่างจาก CRF) และ NAME มาจาก CRF
- `run_strategy_comparison` คืน 4 key ครบ `by_type` มีชนิดหลัก corpus samples ตรงกับ source
- WCB path opt-in `@pytest.mark.skipif(transformers missing)` เหมือน WCB test เดิม (CRF-only ส่วน merge logic เทสต์ด้วย Entity ประกอบมือ ไม่ต้องโหลดโมเดล)

## กติกาการวัด

reuse `score()` เดิม รายงาน per-type recall/precision/F2 ต่อกลยุทธ์ ตัวชี้ขาดคือ NAME กับ ADDRESS recall (structured เสมอทุกกลยุทธ์เพราะเป็น FP) latency ไม่วัดในโค้ด แต่ ADR ต้องระบุชัดว่า union และ route ต้องรัน 2 engine จึงจ่าย WCB cost (~1.3s/ประโยค บน CPU torch) เท่ากับ wcb เดี่ยว

## Deliverable ADR

หลังรัน gold + synthetic เก็บ JSON แล้วเขียน ADR ไฟล์ใหม่ `2026-07-15-ner-engine-strategy-decision.md`

- ตารางเทียบ 4 กลยุทธ์ x 2 corpus (per-type recall/precision + overall + coverage)
- คำแนะนำ engine strategy ตาม invariant recall มากกว่า precision
- trade-off recall/precision/latency (crf เร็วสุด recall ต่ำ, wcb ยก ADDRESS แต่ทิ้ง NAME-ไม่มี-cue, union recall สูงสุดแต่จ่าย 2x + precision ตก, route สมดุลแต่ยังจ่าย 2x)
- reconcile กับ stack-selection doc ว่าคำแนะนำ WCB-primary เดิมยังยืนไหมเมื่อเจอ gold
- นัยต่อ Rust rewrite (ต้องแบก 2 engine ไหม กระทบ ort/ONNX plan)

## ไม่อยู่ในงานนี้ (YAGNI)

- ไม่แตะ `detect_tb`/`detect_all` จริง การ implement กลยุทธ์ที่ ADR เลือกเป็นงานถัดไปแยกต่างหาก
- ไม่ทำ weighted vote / confidence-gated ensemble / CRF-first-then-WCB-fallback เสนอทีหลังถ้า ADR ชี้ว่าคุ้ม
- ไม่ route DATE (ADDRESS→WCB only ตามที่ตัดสิน DATE คงจาก CRF-base)
- ไม่วัด GLiNER/LLM recall net (นอก 2 engine ที่มีในโค้ด)
