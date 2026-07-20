# Roadmap v2 — GitHub-first release — AI Guard (Thai PII Redaction)

- วันที่: 2026-07-17 +07:00
- บริบท: หนึ่งสัปดาห์หลังจบการประกวด (poster day 10 ก.ค.) Horizon 1 ของ roadmap เดิมปิดครบ, Horizon 2 ปิด #8/#10/#11/#13-แกน แล้ว เอกสารนี้คือ roadmap รอบใหม่ที่จัดลำดับงานที่เหลือใหม่ทั้งหมดตาม decision ชุดใหม่ของ owner
- ที่มา: context sweep แบบขนาน 4 มุม + completeness critic (workflow `wf_37169350-0c3`: docs/specs, git state, storefronts, deferred work) ตามด้วย Q&A ล็อก decision กับ owner ในวันเดียวกัน
- North star (คงเดิม): maximum adoption ของเครื่องมือปกป้อง PII ภาษาไทย local-first ไม่มี cloud
- สถานะ: อนุมัติโดย owner 2026-07-17 (โครงแบบ A — release ก่อน ตาข่ายทีหลัง)

## Decisions ที่ owner ล็อกแล้ว (2026-07-17)

1. **แกนหลัก = ปล่อยของถึงมือผู้ใช้จริง ผ่าน GitHub เท่านั้น** — GitHub Releases + README คือประตูหน้าเพียงทางเดียวของรอบนี้ ยังไม่ submit Chrome Web Store, ยังไม่ submit winget/scoop, ยังไม่ publish PyPI, ยังไม่โปรโมท ทั้งหมดย้ายไป backlog รอสัญญาณ
2. **Rust rewrite ถูกฆ่าถาวร** — spec `2026-07-10-rust-rewrite-architecture-design.md` และ plan `2026-07-10-aiguard-core-detection.md` มีสถานะ superseded โดยเอกสารนี้ fork ที่ค้างใน `2026-07-13-production-tech-stack-selection-design.md` (candle vs ONNX vs Python) ปิดลงที่ **Python + ONNX Runtime** — อนาคตของ detection คือ optimize บน Python stack เดิม ไม่มี migration ภาษา
3. **ทำคู่กับ AIFT เต็มสูบ** — ไม่กัน buffer ให้ AIFT (ประกาศผล 20 ก.ค. ถ้าเข้ารอบ: deploy ก่อน 17 ส.ค., present 19 ส.ค.) roadmap นี้เดินเต็มความเร็วตั้งแต่วันนี้ ถ้างานชนกันจริงค่อยปรับหน้างาน
4. **Audit รอบใหม่ก่อน v2.3.0** — audit "tier 1-6" รอบก่อนไม่มีเอกสาร findings เป็น artifact ใน repo (มีแต่ 3 commits + red tests 4 ตัว) ตามกติกา audit ของ owner ถือว่า **ยืนยันความครบไม่ได้** จึงรัน audit ใหม่ทั้ง repo และคราวนี้ต้องมีเอกสาร findings ใน `docs/` เป็น artifact ถาวร
5. **โครงแบบ A — release ก่อน ตาข่ายทีหลัง** — v2.3.0 ออกก่อน แล้วค่อยสร้าง CI recall gate / Playwright ตามหลัง (แลกกับการที่ช่วง audit ยังไม่มี recall gate อัตโนมัติช่วยจับ regression — ยอมรับแล้ว)

Ground rules เดิมจาก spec 2026-07-10 ยังบังคับใช้: OSS solo, stay unsigned (verifiable build แทน cert), kill-list เดิมทุกข้อยังมีผล ยกเว้นที่เอกสารนี้ระบุแก้

## ความสัมพันธ์กับ roadmap เดิม

เอกสารนี้ **supersede การจัดลำดับ** ของ Horizon 2-3 ใน `2026-07-10-post-competition-longterm-roadmap.md` (ตัวเลขอ้างอิง item เดิมยังใช้อ้างถึงกันได้) สถานะ ณ วันเขียน:

| Item เดิม | สถานะ | ไปอยู่ไหนใน v2 |
|---|---|---|
| H1 #1-#7 | เสร็จ/ปิด moot | — (เหลือ owner action: private vulnerability reporting → Phase 1) |
| H2 #8 unify สองสมอง | เสร็จ | PyPI publish ที่แยกออกมา → Backlog |
| H2 #9 benchmark + recall gate | corpus+ADR เสร็จ | CI recall gate → Phase 2 |
| H2 #10 TB restructure | เสร็จ | — |
| H2 #11 verifiable build | เสร็จ (ยังไม่เคยโดน tag จริง) | พิสูจน์ด้วย v2.3.0 → Phase 1 |
| H2 #12 Presidio bridge | ไม่เริ่ม | Backlog (เงื่อนไข decision doc คงเดิม) |
| H2 #13 JS/Rust harness | แกนเสร็จ | Playwright + selector-drift badge → Phase 2 |
| H2 #14 paper | ตัดแล้ว (OSS solo) | — |
| H3 #15 fine-tune Thai NER | ไม่เริ่ม (prerequisite ครบแล้ว) | Phase 3 |
| H3 #16 native messaging | ไม่เริ่ม | Backlog (ผูกกับการกลับไป store) |
| H3 #17 OCR bake-off | ไม่เริ่ม | Backlog |
| H3 #18 on-prem tier | deprioritized | Backlog |
| H3 #19 benchmark dataset บน HF | ไม่เริ่ม | Phase 3 |
| H3 #20 funding channels | ตัดแล้ว | — |
| H3 #21 CWS + Edge | ไม่เริ่ม | Backlog (ตาม decision GitHub-only) |
| Rust rewrite (spec แยก) | ไม่มีโค้ด | **ฆ่าถาวร** |

## Phase 1 — "ปิด v2.3.0" (ตอนนี้ → ประมาณกลาง ส.ค. 2026)

เป้าหมาย: release แรกหลังประกวดที่สะอาด ผ่าน audit ใหม่ และพิสูจน์ release pipeline ที่ยังไม่เคยโดนใช้จริง

1. **ปิด branch `audit-fixes-tier1-6`** — เขียน 3 fix ที่ red tests (uncommitted) เรียกหา:
   - `POST /api/sanitize` ตอบ 400 เมื่อ `mode` ไม่รู้จัก (ตอนนี้ `app/server.py` เงียบ ๆ coerce เป็น default)
   - `_MAX_PDF_BYTES` cap ขนาด upload บน `/api/redact-pdf` ตอบ 413 เมื่อเกิน
   - sanitize `session_id` ใน `_log_path` ของ `pii_redactor/audit.py` (กัน path traversal)
   แล้ว commit tests+fixes, push branch, เปิด PR เข้า main
2. **Audit รอบใหม่ทั้ง repo** — multi-agent, ครอบ `pii_redactor/`, `app/`, `extension/`, `desktop/`, `scripts/`, CI/release workflows เขียนเอกสาร findings ลง `docs/decisions/` เป็น artifact ถาวร (ทุก finding มีสถานะ + หลักฐาน) แล้วปิด findings ตามความรุนแรง — งานนี้ต้องจบก่อน tag
3. **Housekeeping** —
   - regenerate `ROADMAP.md` จากเอกสารนี้ (คอลัมน์สถานะเดิมเชื่อไม่ได้แล้ว)
   - ลบ text_cleaner stage 4/5/6 ตาม kill-list เดิม + อัปเดต CLAUDE.md ที่ยังบรรยาย 7 stage
   - เคลียร์ Dependabot PRs #42-#45 (major bump — ตรวจความเข้ากันกับ SHA-pinning ใน release.yml ก่อน merge)
   - mark spec Rust ทั้งสองไฟล์เป็น superseded (โน้ตหัวไฟล์ชี้มาที่เอกสารนี้)
   - owner action: เปิด GitHub private vulnerability reporting ใน repo settings
4. **Tag v2.3.0** — ครั้งแรกที่ `release.yml` (lockfile build + `checksums-and-attest`) โดน tag `v*` จริง ต้อง review log ของ job ทั้งสองตามคำเตือนใน CLAUDE.md ก่อนถือว่า pipeline ใช้ได้ จากนั้นรัน `scripts/update_packaging.py` bump winget/scoop manifests ใน repo (ยังไม่ submit ไปที่ไหน) และ hand-bump fallback literal ใน `app/server.py`

เกณฑ์สำเร็จ Phase 1: v2.3.0 ขึ้น GitHub Releases พร้อม `SHA256SUMS` + attestation ที่ตรวจแล้ว, audit findings doc อยู่ใน repo, ไม่มี finding ระดับสูงค้าง, ROADMAP.md ตรงความจริง

## Phase 2 — "ตาข่าย + ประตูหน้า" (ปลาย ส.ค. → ต.ค. 2026)

เป้าหมาย: ทุกการเปลี่ยนแปลงหลังจากนี้มีเครื่องวัดรองรับ และคนที่หลงมาเจอ repo ติดตั้งใช้ได้จริงโดยไม่ต้องถาม

5. **CI recall gate** (ปิด H2 #9) — ใช้ benchmark corpus v1+v2 ที่มีอยู่ ตั้ง floor ต่อ entity type ใน CI ให้ PR ที่ทำ recall ตกไม่ผ่าน gate
6. **Playwright live-DOM + selector-drift badge** (ปิด H2 #13) — fixture page ต่อ chat site + badge แสดงสถานะ selector แต่ละ site เพื่อปลดล็อกเงื่อนไข kill-list เรื่อง adapter site ที่ 7 ด้วย
7. **ประตูหน้า GitHub** — README ติดตั้งจาก Releases จบใน 3 ขั้น มี screenshots จริง, เขียน `desktop/README.md` แทน Tauri template stub, ตรวจว่าเอกสารทุกจุดสอดคล้องกับของจริงหลัง audit

เกณฑ์สำเร็จ Phase 2: recall gate แดงได้จริงเมื่อ recall ตก, badge selector ทำงาน, คนใหม่ติดตั้งได้จาก README โดยไม่ต้องมีความรู้ dev

## Phase 3 — "Detection quality บน Python" (ต.ค. 2026 → ม.ค. 2027)

เป้าหมาย: ยกคุณภาพ detection บน Python stack ตาม decision ที่ปิด fork ภาษาแล้ว

8. **ONNX Runtime path** — export WangchanBERTa เป็น ONNX + เดินด้วย `onnxruntime` เป็น opt-in engine ใหม่ (เบา/เร็วกว่า torch stack เต็ม) วัดกับ recall gate จาก Phase 2 ก่อนสลับ default ใด ๆ
9. **Fine-tune Thai PII NER** (H3 #15) — prerequisite (benchmark + windowing) ครบแล้ว fine-tune บน corpus ที่มี แล้ว publish model ขึ้น HuggingFace
10. **Publish benchmark dataset ขึ้น HuggingFace** (H3 #19) — ถ้า #9 ไปได้ดี ปล่อย dataset เป็น community standard

เกณฑ์สำเร็จ Phase 3: มี engine ONNX ที่ผ่าน recall gate, model + dataset อยู่บน HuggingFace โดยตัวเลขทุกตัวมาจาก benchmark ไม่ใช่เขียนมือ

## Backlog — ไม่มีกำหนด รอสัญญาณจากผู้ใช้จริงค่อยหยิบ

- Chrome Web Store submission (repo-side พร้อมแล้วทั้งหมด เหลือ dev account + screenshots + upload)
- winget/scoop submission (manifests bump แล้วใน Phase 1 แต่ไม่ส่ง)
- PyPI publish `pii_redactor`
- โปรโมท/blog post เทคนิค (methodology ของ benchmark + ผล CRF vs transformer)
- Native messaging + token-gate data plane (H3 #16 — หยิบเมื่อตัดสินใจกลับไป store)
- Edge port (H3 #21)
- Presidio bridge (H2 #12 — เงื่อนไข one-page decision doc คงเดิม)
- OCR bake-off (H3 #17), on-prem tier (H3 #18)
- Dark theme desktop/popup (token values มีแล้วใน `tokens.css` ทั้งสองฝั่ง แต่ยังไม่ set `data-theme`)
- แก้จุดที่ CLI `run_pipeline()` ไม่เรียก `audit.py` และ drop PDF word bboxes (พฤติกรรมที่ documented ไว้ ถ้า audit ใหม่จัดว่าเป็น finding ค่อยขยับเข้า Phase)

## สิ่งที่ฆ่า/ตัดในรอบนี้ (เพิ่มจาก kill-list เดิม)

- **Rust rewrite ทั้งเส้น** — ไม่มี migration ภาษาอีกต่อไป เหตุผล: ยังไม่มีโค้ดจริงสักบรรทัดหลังผ่านมาหนึ่งสัปดาห์, fork ทาง NER engine (candle) มีความเสี่ยงที่ doc 13 ก.ค. ชี้ไว้ชัด, และแกนใหม่คือปล่อยของ ไม่ใช่เปลี่ยนฐาน
- ความเชื่อถือได้ของ audit "tier 1-6" เดิม — ไม่นับว่า audit แล้ว ต้องทำใหม่ให้มี artifact
