# tokenmind thaillm-8b เป็นตัวตรวจจับ และการแยก repo พอร์ต AIFT

- วันที่ 2026-07-28
- ต่อจาก [2026-07-25 ชุดทอง v3 + LLM baseline](2026-07-25-gold-set-and-llm-baseline.md)
  ซึ่งวางวิธีให้โมเดลแชตทำหน้าที่ตัวตรวจจับบนชุดเดียวกันไว้แล้ว เอกสารนี้บันทึกผล
  ของ provider ใหม่ (gateway `tokenmind` ของงาน AI for Thai รันโมเดล `thaillm-8b`)
  และการตัดสินใจทำ repo พอร์ตแยกสำหรับ deployment
- บริบทงานแพลตฟอร์ม [platform/ai-for-thai.md](../platform/ai-for-thai.md)

## ทำไมวัด และวัดอะไร

`thaillm-8b` ผ่าน gateway `tokenmind` เป็น LLM ปลายทางจริงของเส้น hosted ไม่ใช่แค่
เดโมแข่ง การให้มันทำหน้าที่ตัวตรวจจับบน gold ตอบสองอย่าง หนึ่งคือ baseline ว่าการ
ส่งข้อความออกไปให้โมเดลนี้ ตัวมันเองมองอะไรออกว่าเป็น PII สองคือ sanity ว่า pre-send
leak guard ฝั่งเราไม่ได้ปล่อยผ่านสิ่งที่โมเดลเองยังจับได้ วิธีวัดเหมือน ADR 2026-07-25
(โมเดลได้รายชื่อชนิดตรงกับ gold ถูกขอแค่ค่า span คำนวณฝั่งเราด้วยกฎ claim ยาวก่อน
ไม่ทับกัน คำตอบดิบ cache รายเอกสาร ไม่เก็บ response body ของ provider)

## ผล (gold v4 รันเดียว 28 ก.ค.)

ชุดทอง v4 มี 252 เอกสาร 648 entity ครบ 11 ชนิด ไม่มีชนิดใดต่ำกว่า 24 ตัว บวก negative
slice 45 เอกสารที่ไม่มี PII เอกสารทุกชิ้นประกอบขึ้นตามรูปแบบมาตรฐานไทย ค่าทุกตัวเป็น
ของปลอม ไม่ใช่เอกสารจริงที่เก็บจากการใช้งาน

| มุม | R | P | F2 |
|---|---|---|---|
| entity-level (มีชนิด) | 0.960 | 0.917 | **0.951** |
| type-agnostic (หาเจอไหม) | 0.966 | 0.913 | 0.955 |

tp 622 / fp 56 / fn 26 เรียก provider 249 ครั้ง cache 3 failed 0 อีกสองรายการที่ runner
นับไว้คือค่าที่โมเดลตอบแต่หาตำแหน่งในเอกสารไม่เจอ 2 จุด และเอกสารที่โมเดลไม่คืนค่าอะไรเลย
9 ชิ้น report ที่ `benchmark/reports/llm-tokenmind-thaillm8b-gold-v4.json` (generated ผ่าน
`scripts/run_llm_benchmark.py` โฟลเดอร์ `reports/` gitignore ตามกติกา)

บน negative slice 45 เอกสารที่ไม่มี PII เลย ตัวเลขกลับด้าน โมเดลจับผิด 42 จุด เอกสาร
ที่รอดสะอาด 15 ชิ้น (clean rate 0.333) ในมุม type-agnostic เป็น 50 จุด สะอาด 9 ชิ้น
(0.200) ส่วนต่าง 8 จุดคือ prediction ที่โมเดลตั้งชื่อชนิดขึ้นเอง (ISBN ISSN VARIABLE)
ซึ่งมุมแรกทิ้งเพราะไม่อยู่ในรายการชนิด เทียบเส้นทาง rule+CRF ค่าเริ่มต้นบน gold v4
ชุดเดียวกันที่จับผิด 33 จุด สะอาด 0.400 ตาม
[engine comparison](2026-07-28-engine-comparison-after-campaigns.md) (เลข CRF อ้างจาก
ADR ฉบับนั้น ไม่ได้รันซ้ำในรอบนี้) negative slice คือสิ่งเดียวที่ทำให้รายงาน false
positive ได้ ตัวเลขสองมุมข้างบนจึงต้องอ่านคู่กับบรรทัดนี้เสมอ

ตีความ บนเอกสารที่มี PII โมเดลทำได้ดีกว่าเส้นทาง rule+CRF ของเราชัดเจน (F2 0.951 เทียบ
0.908) แต่บนเอกสารที่ไม่มี PII มันจับผิดมากกว่า (42 เทียบ 33) ทั้งสองด้านชี้ข้อสรุป
เดียวกัน คือ `thaillm-8b` เข้าใจ PII ไทยดีพอที่ pre-send guard ต้องกันให้ครบก่อนส่ง
ไม่ใช่บันทึกว่าโมเดลนี้ควรมาแทนตัวตรวจจับของเรา คนละงานกัน (generative ปลายทางเทียบกับ
detector) และเส้นทางนี้ต้องส่งข้อความออกนอกเครื่องทีละเอกสาร ซึ่งขัดกับหลัก local-first
ของตัวตรวจจับเองอยู่แล้ว มุม type-agnostic สูงกว่ามุมแรกเล็กน้อยเพราะชนิดที่โมเดลคิดขึ้นเอง
ถูกยุบเป็นชนิดเดียว

## กฎการอ้างตัวเลขนี้

ตามกฎเดียวกับ ADR 2026-07-25 ต้องระบุขนาดชุดและการกระจาย (252 เอกสาร / 648 entity /
11 ชนิด) และบอกว่าเป็นเอกสารประกอบขึ้นทุกครั้ง การยก F2 0.951 ไปใช้ที่ไหนต้องพ่วง
ตัวเลข negative slice ไปด้วยเสมอ เพราะลำพังมุมเดียวอ่านเป็นว่าโมเดลตรวจ PII ได้ดีกว่า
เส้นทางเรารอบด้าน ซึ่งไม่จริง ห้ามยกเป็นผลหลักโดยไม่มี generated
report อ้าง gold ยังเป็น diagnostic ไม่ใช่ CI gate และ **ห้ามเคลมสาธารณะว่าเป็น
benchmark PII ไทยเดียวของประเทศ** (ROADMAP defer public benchmark leadership claims
ใช้ภายในเพื่อจัดลำดับเท่านั้น)

## การตัดสินใจแยก repo พอร์ต AIFT

deployment งาน AI for Thai ทำบน repo พอร์ตแยก `aiguard-aift` (บน gitlab.nectec.or.th
ของงาน) ไม่ใช่ repo หลักนี้ repo หลักคงบทบาท local-first (extension / desktop / CLI /
Office add-in) พอร์ตเป็น "เปลือก service" คือ vendored slice ของ core (manifest มี
SHA-256 ต่อไฟล์ ปักหมุด commit ต้นทางที่รวม PR #101 hosted-readiness) + nginx (เติม
`/api` ที่ proxy ของแพลตฟอร์มตัดออก, allowlist 6 endpoint เป๊ะ, inject service key,
log ตัด query string) + หน้า product + OCR bake ลง image เส้น hosted เป็น stateless
(mask จาก thaillm-8b แล้ว restore จบในคำขอเดียว mapping คืนผู้เรียก ไม่มี vault ฝั่ง
เซิร์ฟเวอร์) ข้อมูลที่ปกปิดด้วย pseudonymization ยังเป็นข้อมูลส่วนบุคคลตาม PDPA เอกสาร
ของพอร์ตไม่เคลมเกินจากนี้

พอร์ตนี้ผ่านเฟส local ครบแล้วบน Docker ในเครื่อง checklist ก ถึง ฌ (health, roundtrip
tokenmind จริงผ่าน nginx, log ไม่มี query, allowlist 404, หน้าเว็บ, vendored --check,
OCR ใน container) บวก failure modes (compose fail-loud เมื่อไม่มี key, /roundtrip ตอบ
503 ชัดเจนเมื่อถอด tokenmind key) บวก soak ระดับ service (fake 8 สาย 10 นาที 5465 ok
ไม่มี 5xx, limit คืน 429 ตอน overload ไม่ crash, tokenmind จริง 2 สาย เสถียร, log ทั้ง
core และ api ไม่มี PII, restart recovery กลับ healthy เอง) หลักฐานสรุปอยู่ในพอร์ต
repo ที่ `docs/evidence/`

## ที่ยังไม่ทำ

- deploy จริงบนแพลตฟอร์ม project ใน group team-08 รอเจ้าของสร้าง (สิทธิ์ Maintainer
  มีแล้ว) การขึ้น GitLab รอคำสั่งเจ้าของ
- soak และ SLA บนโครงสร้างจริง ตัวเลขในเครื่องเป็น readiness ไม่ใช่ platform evidence
- คลื่น 2 ตามแผนแม่บท (residue scan, caller salt, processing receipt)
