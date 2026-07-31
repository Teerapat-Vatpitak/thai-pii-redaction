# Code cleanup audit — 2026-07-31

ตรวจ imports, entry points, build files, เอกสารปัจจุบัน และ tests ก่อนจัดกลุ่ม
รายการด้านล่าง การไม่พบ reference อย่างเดียวไม่พอสำหรับลบ public contract
หรือไฟล์ที่ใช้สร้าง release

## ลบแล้ว

| รายการ | เหตุผล |
|---|---|
| `scripts/demo_check.ps1` | เครื่องมือ booth demo เก่า ข้อมูลเรื่อง Desktop attach ไม่ตรงกับ runtime ปัจจุบัน |
| `scripts/measure_demo.py` | เครื่องมือจับเวลา booth demo ที่ไม่มี caller และใช้เกณฑ์เก่า; performance gate ปัจจุบันคือ `scripts/measure_perf.py` |
| `benchmark/sweep_web_guard.py` | random sweep ของ PR เก่า ถูกแทนด้วย tests ที่ใช้ salt คงที่และทำซ้ำได้ |
| `benchmark.llm_strategy.GOLD_TYPES` | compatibility alias ที่ไม่มี caller และ benchmark ไม่ใช่ installable package |
| Desktop `button.primary` CSS | ไม่มี HTML หรือ JS ปัจจุบันใช้ selector นี้แล้ว |
| Linux `fonts-thai-tlwg` install | PDF ใช้ฟอนต์ที่ bundle มากับ package เป็นตัวเลือกแรก |
| `aiofiles` | ไม่มี import และไม่ใช่ dependency ของ FastAPI/Starlette |
| Office `@vitest/coverage-v8` | ไม่มี script, config หรือ CI job เรียก coverage |

## ต้องตัดสินใจก่อนลบ

- `text_cleaner.clean(interactive, review_timeout_s)` ไม่มี production caller
  ใน repo แต่เป็น Python call contract ที่อาจมีผู้ใช้ภายนอก
- TNER decoder แบบเก่า `POS=[word, pos]` ยังรองรับ published SDK shape และมี
  contract tests
- worker ที่ไม่มี `contract_version` ยังถูกตีความเป็น v1 การบังคับ field จะ
  เปลี่ยน wire contract
- `build_exe.ps1` และ `desktop/build-sidecar.ps1` เรียก builder ตัวเดียวกัน
  แต่เอกสารยังใช้ทั้งสองชื่อ ต้องเลือก entry point หลักก่อน
- ~~CLI report ยังประกอบผลซ้ำกับ shared report path~~ **รวมแล้ว** `ai_guard.py
  cmd_report` เรียก `detect_all` ตัวเดียวกับทางเว็บ output เปลี่ยนจริงตามที่
  ห่วงไว้ คือจำนวน entity ไม่ถูกนับซ้ำอีกเมื่อ FP กับ TB จับค่าเดียวกัน
  pin ด้วย `tests/test_step10_cli.py::test_ai_guard_report_uses_the_canonical_fallback_detector`
- ~~`analyze_text()` ตรวจ FP/TB ซ้ำกับ `generate_report()`~~ **รวมแล้ว** ทั้งคู่
  รับผล `detect_all` ชุดเดียว `tests/test_step12_report.py::test_analyze_text_runs_detection_once`
  ตรึงไว้ว่าตรวจรอบเดียว และ `breakdown[]` เปลี่ยน key เป็น
  (`data_type`, `redact_type`) จึงมีสองแถวต่อชนิดได้เมื่อเจอทั้งสองแบบ
- source assets ที่ไม่มี build reference อาจยังใช้แก้ logo หรืออัปโหลด store
  จากนอก repo จึงยังไม่ลบ

## ยังใช้อยู่

- `app/worker/` เป็น local failure/retry emulator ตาม architecture ปัจจุบัน
- Office XML manifests ทั้งสามยังใช้ใน real-host acceptance
- `benchmark/probe_document.py` เป็นงาน Track A ปัจจุบัน
- `pii_redactor/audit.py` ถูกเรียกจาก API และมี privacy tests
- `demo_cli.py` ยังอยู่ใน CLI docs และ contract tests
- Desktop legacy attach เป็น dev escape hatch ที่ docs และ Rust tests ยัง pin
- system-font candidates ยังเป็น fallback เมื่อ package data เสียหรือหาย
