# Union NER strategy in detect_tb (design)

- วันที่ 2026-07-15
- บริบท [ADR NER engine strategy decision](2026-07-15-ner-engine-strategy-decision.md) เลือกกลยุทธ์ union (CRF ∪ WangchanBERTa) จากการวัด 4 กลยุทธ์บน benchmark ([design](2026-07-15-ner-engine-strategy-comparison-design.md)) เอกสารนี้คือ spec ของการเอา union ไปใช้จริงใน product ที่ `detect_tb`
- สถานะ อนุมัติดีไซน์แล้ว รอเขียน plan
- ขอบเขต เพิ่ม union เป็น mode เปิดเอง (opt-in) ผ่าน env ไม่เปลี่ยน default ไม่แตะ requirements.txt core

## เป้าหมาย

ให้ `detect_tb` รองรับกลยุทธ์ union ตาม ADR โดย `AIGUARD_NER_ENGINE=union` รัน NER ทั้ง thainer (CRF) และ wangchanberta (thainer-v2) แล้วรวม span เป็น union default ยังเป็น thainer เหมือนเดิม เพราะ union ต้องพึ่ง torch/transformers และจ่าย ~1.3 วินาที/ประโยค

## หลักการ

- opt-in เท่านั้น default = thainer core-only install (ไม่มี torch) ยังทำงานได้เหมือนเดิม union ต้องการ requirements-ml.txt เหมือน wangchanberta mode
- fail loudly ถ้า env=union แต่ไม่มี transformers ให้ raise `NEREngineUnavailableError` ตรงกับพฤติกรรม wangchanberta mode เดิม ไม่ silent degrade ไป CRF ตามหลัก recall-first ที่ยอมพลาดไม่ได้แบบเงียบ
- detect_tb เป็น chokepoint เดียว (web app/server.py, CLI ai_guard.py, pre-send guard ai_client.py, detect_all aggregate.py, pipeline.py เรียกหมด) แก้ที่นี่ที่เดียวได้ทุก path

## การเปลี่ยนโครงสร้าง engine

ปัจจุบัน `tb_detector._ner` เป็น singleton ตัวเดียว โหลดจาก env ครั้งแรก union ต้องถือ 2 engine พร้อมกัน จึงเปลี่ยนเป็น cache keyed ด้วยชื่อ engine

- `_ner_cache: dict[str, NER] = {}` module-level
- `_load_ner(name: str) -> NER` validate `name` กับ `_ENGINE_CONFIG` เช็ค requires (transformers) ถ้าขาด raise `NEREngineUnavailableError` ถ้าใหม่สร้าง `NER(engine=config["ner_engine"])` เก็บใน cache แล้วคืน (lazy โหลดครั้งเดียวต่อ engine)
- `_get_ner() -> NER` คงไว้เป็น thin wrapper สำหรับ single mode อ่าน env แล้ว `return _load_ner(name)` (พฤติกรรม public เดิมไม่เปลี่ยนสำหรับ thainer/wangchanberta)

## union ใน detect_tb

แยก loop sliding-window NER ที่มีอยู่ออกเป็น helper `_ner_candidates(text, ner, sentence_offsets) -> list[Entity]` (โค้ดเดิมยกมา ไม่เปลี่ยน logic) แล้ว detect_tb

- อ่าน `name = os.environ.get("AIGUARD_NER_ENGINE", "thainer")`
- ถ้า `name == "union"` engines = [`_load_ner("thainer")`, `_load_ner("wangchanberta")`] มิฉะนั้น engines = [`_load_ner(name)`] (validate ทาง `_load_ner` จะ raise ValueError/NEREngineUnavailableError ตามเดิม)
- วน `_ner_candidates` ต่อ engine เก็บ candidate รวมกัน
- name_context booster (`detect_name_context`) รันครั้งเดียว engine-independent เพิ่มเข้า candidate
- `_deduplicate` เดิมจัด overlap ผลคือ TB_crf ∪ TB_wcb เหมือน strategy union ที่ ADR วัด

## ripple ที่ต้องแก้ตาม

- `tests/test_ner_engine.py` `_reset` เปลี่ยนจาก set `_ner = None` เป็นล้าง `_ner_cache` (`monkeypatch.setattr(tb_detector, "_ner_cache", {})`) เทสต์เดิมทั้งหมดต้องยังเขียว (default thainer, bogus→ValueError, wcb-ไม่มี-transformers→NEREngineUnavailableError, wcb→thainer-v2, wcb real PERSON)
- `benchmark/runner.py` จุดที่ reset `tb_detector._ner` (ใน run_benchmark และ run_strategy_comparison) เปลี่ยนเป็นล้าง `_ner_cache` การสลับ engine ยังต้องได้ผลถูก

## validation

หลัง implement รัน `python -m benchmark --source gold --engine ...` ไม่พอ ต้องยืนยันว่า product union path ให้ผลตรงกับ strategy union ที่ ADR วัด เพิ่มเทสต์ว่า `detect_all` เมื่อ `AIGUARD_NER_ENGINE=union` ให้ prediction ต่อ sample ตรงกับ `union_entities(detect_all_crf, detect_all_wcb)` (oracle เดิมใน benchmark) บน gold ถ้าต่างต้องเข้าใจสาเหตุ เป้าหมายคือ product == oracle ที่ ADR ใช้แนะนำ

## การทดสอบ (targeted)

- union รวม candidate จาก 2 engine จริง (skipif ไม่มี transformers) เทสต์บนข้อความที่ CRF กับ WCB จับชื่อ/ที่อยู่ต่างกัน ต้องเห็น span จากทั้งคู่
- env=union ไม่มี transformers → `NEREngineUnavailableError` (mock import เหมือน test เดิม)
- single mode (thainer default, wangchanberta) ไม่ regression
- `_ner_cache` ไม่โหลดโมเดลซ้ำเมื่อเรียกซ้ำ (cache hit)
- product union == oracle union บน gold (ข้อ validation)

## ไม่อยู่ในงานนี้ (YAGNI)

- ไม่ทำ route หรือกลยุทธ์อื่นใน product (ADR เลือก union)
- ไม่เปลี่ยน default engine ไม่แตะ requirements.txt core
- ไม่ทำ per-request engine override (env-global ต่อ process เหมือนเดิม)
- ไม่ทำ weighted vote / confidence gate (นอก union)
- ไม่แตะ Rust rewrite (นัยเรื่องแบก 2 engine บันทึกไว้ใน ADR แล้ว)
