# Post-competition long-term roadmap — AI Guard (Thai PII Redaction)

- วันที่: 2026-07-10 16:35 +07:00
- บริบท: วันนี้คือวัน poster presentation ของ PSU Future Tech Challenge 2026 ซึ่งเป็น event ปิดท้ายการประกวด phase 1-5 เดิม (Tauri shell, tray/hotkey/audit, Apache-2.0 relicense + ถอด PyMuPDF, auto-updater, winget/scoop, cross-platform smoke CI) ปิดครบแล้วตั้งแต่ v2.2.0 เอกสารนี้วางแผน "ชีวิตหลังการประกวด"
- ที่มา: สังเคราะห์จากการ map ระบบทั้ง 8 subsystem แบบขนาน (workflow wf_1cd2e070-846) + critic ตรวจความครบ + roadmap 3 มุมมอง (product/adoption, engineering, impact/ecosystem) finding สำคัญยืนยันด้วยการรันโค้ดจริง
- North star (คงเดิมจาก spec 2026-07-04): maximum adoption ของเครื่องมือปกป้อง PII ภาษาไทย local-first ไม่มี cloud

## Decisions ที่ผู้ใช้ล็อกแล้ว (2026-07-10 16:35 +07:00)

1. **แกนหลัก 3-12 เดือน = Engineering / Quality** — โฟกัสความแข็งแรงของ core: unify สองสมอง, benchmark corpus + recall gate ใน CI, ปิด test gap JS/Rust, ทำ codebase ให้ maintain ได้ยาวและพิสูจน์คุณภาพได้ Horizon 2-3 เอนน้ำหนักมาทางนี้ ไม่ใช่ product features หรือ academic output
2. **OSS solo** — ไม่เดินสาย PSU/DIIS partnership benchmark corpus เป็น synthetic-first + community annotation (ไม่พึ่งนักศึกษา PSU) ตัด/พัก item ที่พึ่งพา partnership: paper กับ PSU co-author, pilot org ผ่าน PSU, funding ผ่าน depa/NIA/PSU
3. **Stay unsigned** — ไม่จ่ายค่า code signing ใช้ note "More info -> Run anyway" เหมือนเดิม เน้น reproducible/verifiable build (SHA256SUMS, pinned deps) แทนการซื้อ cert; macOS deprioritize ต่อ

ผลต่อแผน: item ที่มี "[พัก - OSS solo]" หรือ "[ปรับ - unsigned]" กำกับด้านล่าง ถูกปรับตาม decision เหล่านี้แล้ว ลำดับความสำคัญจริงอยู่ในหัวข้อ "ลำดับที่แนะนำหลังล็อก decision" ท้ายเอกสาร

## อัปเดตสถานะ (2026-07-16)

Horizon 1 คืบไปมากแล้ว สถานะจริง ณ วันนี้ (ยืนยันจากโค้ด/CI ไม่ใช่จากความจำ):

- **#1 แก้ 3 recall leak — เสร็จ** (PR #25, regression ใน `tests/test_recall_leaks.py` ครอบ Thai-glued PII, +66, per-page PDF routing รวมถึง fix ตามหลัง PR #28/#29)
- **#2 Harden localhost API — เสร็จเกือบหมด**: CORS เป็น strict allowlist (`allow_origin_regex` เฉพาะ extension/Tauri ไม่ใช่ `*`), TrustedHost, `/api/shutdown` ต้องมี header `X-AIGuard-Local`, `_SESSIONS` มี TTL 1800s + `DELETE /api/session/{id}` (ทดสอบใน `tests/test_api_hardening.py`) — **ยังไม่ทำ**: random boot token (`X-AIGuard-Token`) บน mutating endpoint ทั่วไป
- **#3 CI test gate — เสร็จ** (PR #24, `.github/workflows/ci.yml`: pytest win+ubuntu, core-only job, cargo test, JS syntax check, windows exe smoke)
- **#4 Collision-safe pseudonym + span merge — ยังไม่ทำ**
- **#5 Single-source version — ยังไม่ทำ** (Cargo.toml drift 2.1.0 แก้เป็น 2.2.0 แล้ว 2026-07-16 แต่ยังไม่มี VERSION ไฟล์เดียว + CI drift check)
- **#6 CWS submission / #7 booth latency — ยังไม่ทำ** (ตาราง latency ใน booth-checklist ยังเป็น placeholder)
- นอกแผน: benchmark v1+v2 (gold) + NER strategy ADR + union engine ใน `detect_tb` เสร็จแล้ว (2026-07-13 ถึง 07-15) ซึ่งกินเนื้องานส่วนใหญ่ของ #9 ล่วงหน้า

ตาราง "ปัญหา/หนี้ที่ยืนยันแล้ว" ด้านล่างคง snapshot ของวันที่ 2026-07-10 ไว้ตามเดิม ให้อ่านคู่กับสถานะข้างบนนี้

---

## ภาพรวมระบบตอนนี้ (ground truth)

สถาปัตยกรรม "Single Brain, Multiple Storefronts" มีจุดที่ต้องรู้ก่อนวางแผน คือ **มันมีสองสมองจริง ไม่ใช่สมองเดียว**:

- **CLI path** (`pii_redactor/pipeline.py` + `SessionVault`) คือ pipeline 8 ขั้นที่เข้มงวด มี pre-send leak guard, vault snapshot/rollback, 3-layer output validation, defense-in-depth สแกน PII ซ้ำ 3 จุด
- **Web path** (`app/server.py` `_tokenize` + `_SESSIONS`) คือทางที่ extension และ desktop ใช้จริง มันยืมแค่ detectors กับ audit.py **ไม่ผ่าน vault, ไม่ผ่าน pre-send guard, ไม่ผ่าน reverse_mapper, ไม่ผ่าน 3-layer validator**

แปลว่า implementation ที่เข้มงวดที่สุดคือทางที่ผู้ใช้จริงไม่เคยแตะ และคุณสมบัติความปลอดภัยที่ poster โฆษณาไว้ ทาง front door ไม่มีครบ นี่คือแกนของแผนเกือบทั้งหมดด้านล่าง

### จุดแข็งที่มีจริง

- Defense-in-depth ของ CLI path (สแกนซ้ำ 3 จุด แต่ละจุด raise ได้จริง) ออกแบบดี
- แยก step ชัด แต่ละ module เล็ก มี dataclass contract + test file เฉพาะ (ชุดทดสอบอัตโนมัติหลายร้อยเคส ตัวเลขจริงดูจาก `pytest --collect-only` / CI ไม่เขียนเลขตายตัวในเอกสารตาม kill-list)
- Pseudonym แบบ SHA256-seeded ให้ consistency ต่อเอกสารและ reproducible ไม่พึ่ง LLM ไม่มี network ตอน generate
- FP detection มี checksum จริง (Thai ID mod-11, Luhn) ทำให้ precision ของ structured PII สูง
- Optional-dependency pattern (OCR / MiniLM) สะอาด degrade เป็น no-op ได้

### ปัญหา/หนี้ที่ยืนยันแล้ว (ไม่ใช่การเดา)

| ประเด็น | สถานะการยืนยัน |
|---|---|
| เลขบัตร ปชช. ติดอักษรไทย `เลขบัตรประชาชน1101700230708` หลุด detect | ยืนยัน รันโค้ดจริง คืน `[]` (สาเหตุ `\b` มองอักษรไทยเป็น word char) |
| `+66 81 234 5678` ไม่ถูกจับ และ `+66812345678` ถูก label ผิดเป็น STUDENT_ID | ยืนยัน รันโค้ดจริง คืน `[]` |
| `POST /api/shutdown` ไม่มี auth + `allow_origins=["*"]` เว็บใดก็ยิงปิด backend ได้ | ยืนยัน อ่าน `app/server.py:58,84` |
| `_SESSIONS` (token map ที่มี PII จริง) ไม่มี idle TTL อยู่จนกว่า process ตาย | ยืนยันจาก map (ต่างจาก SessionVault ที่มี 1800s) |
| CI ไม่รัน pytest เลย (มีแค่ release.yml + smoke-crossplatform.yml) | ยืนยันจาก map + ไฟล์ workflow |
| version string ซ้ำ 8+ ที่ Cargo.toml drift ไปที่ 2.1.0 | ยืนยันจาก spec 07-05 + map |
| extension (~750 บรรทัด) + desktop/src (~620 บรรทัด) ไม่มี test เลย | ยืนยันจาก map |
| detect_source_type ใช้ threshold ทั้งเอกสาร >=50 char ทำให้ PDF ที่มี 1 หน้า text + 99 หน้าสแกน ถูกจัดเป็น pdf_text แล้ว redact ได้ 0 entity แบบเงียบ | รายงานจาก map (ยังไม่รันยืนยัน) |
| text_cleaner Stage 4/5/6 เป็น dead code (no-op / prompt เปล่า / flag ทุกคำที่มี Z หรือ B) | รายงานจาก map (ยังไม่รันยืนยัน) |

---

## แผนระยะยาว (3 horizon)

3 มุมมองที่วิเคราะห์แยกกัน (product, engineering, ecosystem) ลงเอยที่แผนเดียวกันแทบทุกจุด สิ่งที่ทั้งสามเห็นตรงกันคือ **สอง unlock ใหญ่**: (1) unify สองสมองให้เหลือหนึ่ง (2) สร้าง benchmark corpus ที่วัด recall/precision ได้จริง ทุกอย่างอื่น hang อยู่กับสองอันนี้

### Horizon 1 — NOW (0-1 เดือน): อุดรูก่อนโปรโมต

เหตุผลลำดับ: ก่อนจะโปรโมตอะไร ต้องปิดช่องที่ blogger สาย security จะหยิบไปเขียนก่อน เพราะเป็น repo Apache-2.0 เปิด public

1. **[S/สูง] แก้ 3 recall leak ที่ยืนยันแล้ว พร้อม regression test** — เปลี่ยน `\b` เป็น digit-boundary lookaround `(?<!\d)...(?!\d)` ใน fp_detector + fn_scanner; แก้ `_RE_PHONE_INTL` ให้รับ +66 ตามด้วย 9 หลักแบบ separator ยืดหยุ่น; ย้าย per-page text-layer check เข้า extraction ให้หน้าสแกนไม่หายเงียบ ทุกอันมี adversarial test กัน regress
2. **[M/สูง] Harden localhost API** — สร้าง random token ตอน boot, ให้ Tauri shell/launcher ส่งเข้า sidecar env และส่งให้ extension out-of-band, บังคับ header `X-AIGuard-Token` บน mutating endpoint, ตรวจ Host header (กัน DNS rebinding), ใส่ idle TTL + `DELETE /api/session/{id}` ให้ `_SESSIONS`
3. **[S/สูง] ตั้ง CI test gate จริง** — `ci.yml` รัน pytest บน windows-latest + ubuntu-latest, มี core-only-install job, cargo test สำหรับ src-tauri, eslint สำหรับ extension, และ packaged-exe smoke (boot AIGuard.exe -> hit /api/health + /api/sanitize -> taskkill -> เช็ก port ว่าง) เพราะ Windows คือ platform เดียวที่ user รันจริงแต่ CI ไม่เคย boot
4. **[S/สูง] Collision-safe pseudonym + cross-detector span merge** — pool ชื่อ ~40 ทำให้สองคนได้ pseudonym เดียวกันแล้ว vault เขียนทับเงียบ (restore ผิดคน); fp+tb entity list ต่อกันโดยไม่ resolve span ที่ overlap ทำ text เพี้ยนตอน tail-first replace แก้: เช็ก uniqueness ตอน write + re-roll seed, แยก span-merge เป็น module กลาง
5. **[S/กลาง] Single-source version + OSS front door** — VERSION ไฟล์เดียว + bump script + CI drift check; และเพิ่ม ROADMAP.md (เอกสารนี้), CONTRIBUTING, SECURITY.md, CHANGELOG ที่ spec 07-04 สัญญาไว้แต่ไม่เคยเขียน
6. **[M/สูง] เริ่ม Chrome Web Store submission** — เขียน privacy policy (ง่ายเพราะไม่มีอะไรออกจากเครื่อง), listing assets, permission justification, `_locales` th/en เริ่ม review เร็วเพราะ latency ของ CWS อยู่นอกการควบคุม
7. **[S/กลาง] เก็บ momentum วัน poster** — launch post ไทย/อังกฤษ ลง PyThaiNLP community + Thai dev groups; นัด follow-up กับ DIIS/PSU เรื่องนักศึกษาช่วย annotate corpus, co-authorship, และ PSU เป็น pilot org แรก; วัด latency จริงที่บูธเติมลง booth-checklist ที่ยังเป็น placeholder

### Horizon 2 — NEXT (1-3 เดือน): unify + วัดผลได้

8. **[L/สูง] Unify web + CLI เหลือ core เดียว (refactor ใหญ่)** — ให้ `/api/sanitize` เรียก detect + anonymize + SessionVault, `/api/reidentify` เรียก reverse_map + Layer-1 re-scan, ลด `_SESSIONS` เหลือ registry ของ SessionVault ที่มี TTL; เพิ่ม bracket-token mode ให้ generator; รับ session_id เดิมได้ (แก้ multi-turn restore ที่พังอยู่ไปในตัว); dual test suite (test_step3/4 vs test_step11) คือ regression net; เสร็จแล้ว publish `pii_redactor` ขึ้น PyPI เป็น embeddable library
9. **[L/สูง] Thai PII benchmark corpus v1 + CI recall gate** — สร้างเอกสาร labeled หลายร้อยชิ้น **synthetic-first ล้วน** ใช้ fp_generator/tb_generator สร้าง (OSS solo ไม่พึ่งนักศึกษา PSU annotate จึงยิ่งต้อง synthetic เพื่อไม่สร้าง PII liability และ scale ด้วย generator ไม่ใช่แรงคน), วัด per-type precision/recall ใน CI, gate เช่น `NAME recall >= 0.90`, publish ตัวเลข CRF vs WangchanBERTa ใน README นี่คือของที่สัญญาใน form-answers ข้อ 9 และเป็น credibility unlock **นี่คือเสาหลักของแกน Engineering/Quality** ไม่มีมันก็เปลี่ยน detection อะไรไม่ได้อย่างมั่นใจ
10. **[M/สูง] Restructure TB detection + แก้ semantic ของ type** — window ±3 ประโยค re-tag ซ้ำ ~7x ทำให้ WangchanBERTa (1.3s/ประโยค) ใช้ไม่ได้จริง เปลี่ยนเป็น non-overlapping/stride window + batch inference; หยุด map ทุก DATE -> DATE_OF_BIRTH และทุก LOCATION -> ADDRESS; เก็บ ORGANIZATION; คุม STUDENT_ID (8-12 หลักอะไรก็ได้) กับ PASSPORT catch-all ที่ทำ surrogate เพี้ยนในเอกสารธุรกิจ
11. **[M/สูง] [ปรับ - unsigned] Reproducible + verifiable Windows build** — pin build (lockfile + pinned PyInstaller + SHA-pinned actions), publish SHA256SUMS, automate winget/scoop hash bump **ตัดการซื้อ Authenticode ออก** (decision: stay unsigned) แทนที่ด้วยการเน้น verifiable build: build reproducible, checksums ตรวจได้, note "More info -> Run anyway" ชัดใน README + release body ให้ความเชื่อใจมาจากความโปร่งใส/ตรวจสอบได้ ไม่ใช่จาก cert
12. **[M/สูง] Publish Presidio bridge เป็น PyPI plugin (ไม่ fork ไม่ rewrite)** — package FP recognizers (Thai ID mod-11, +66 phone, bank, plate, passport) + thainer NER adapter เป็น presidio-analyzer recognizer ในแพ็กเกจ `presidio-thai` Presidio ไม่มี Thai support จึง ride distribution ของ Microsoft ไม่ใช่แข่ง เก็บ vault + AI round-trip + PDF redaction ไว้เป็นของ AI Guard เท่านั้นให้ plugin เป็น funnel (เข้ากับ OSS solo ดี เป็น ecosystem play ที่ไม่ต้องพึ่ง partnership)
13. **[M/สูง] JS/Rust test harness + selector-drift telemetry** — (เลื่อนขึ้นเป็นสูงตามแกน Engineering/Quality) vitest+jsdom สำหรับ logic ล้วน, Playwright ยิง fixture page เลียน DOM ของแต่ละ chat site, Rust integration test สำหรับ sidecar kill order, และ badge เตือนเมื่อ `composer()` fallback เป็น generic หรือ `assistantMessages()` คืนศูนย์บน site ที่รู้จัก (แปลง silent breakage เป็นสัญญาณ) 1,400 บรรทัดที่ไม่มี test เลยคือหนี้ที่ใหญ่ที่สุดสำหรับ solo maintainer
14. **[พัก - OSS solo] ร่าง paper ระบบ+dataset กับ PSU co-author** — ตัดออกตาม decision OSS solo ถ้าอยากได้ credibility เชิงวิชาการภายหลังโดยไม่ผูก PSU ทำเป็น technical writeup / blog post เรื่อง benchmark methodology + ผล CRF vs transformer แทน paper แบบมี co-author (ต้นทุนต่ำกว่ามาก ได้ credibility ส่วนใหญ่)

### Horizon 3 — LATER (3-12 เดือน): moat + ความยั่งยืน

15. **[L/สูง] Fine-tune Thai PII token classifier เปิดบน HuggingFace** — ไม่มี Thai PII-specific NER model สาธารณะเลย fine-tune WangchanBERTa (หรือ encoder ไทยใหม่กว่า) บน corpus ด้วย label PII จริง (รวม ORGANIZATION, แยก DATE vs DATE_OF_BIRTH), ปล่อย weight permissive, ship เป็น quality tier ชัด (CRF = default offline ใน exe, transformer = opt-in) เปลี่ยน default เฉพาะเมื่อ benchmark พิสูจน์ว่าคุ้ม
16. **[L/สูง] แทน localhost HTTP ด้วย Chrome native messaging** — ตัด fixed port 8000 (hardcode 5+ ที่), wildcard CORS, drive-by probing, และขั้น "start backend ก่อน" ออกหมด extension คุยกับ AIGuard.exe ตรงๆ (winget/scoop delivery มีครึ่งแล้ว) นี่คือของที่ทำให้ CWS install แปลงเป็น active user จริงสำหรับคนไทยที่ไม่ technical
17. **[L/สูง] Offset-accurate redaction + OCR bake-off** — align entity char span กับ per-char box ของ pdfplumber (เลิก over-redact จาก substring matching), ขอ word-level OCR box, แล้ว bake-off PaddleOCR vs Tesseract Thai vs EasyOCR vs Typhoon OCR บน corpus OCR quality คือเพดานของทั้ง scanned-PDF product
18. **[L/กลาง] [ปรับ - OSS solo] On-prem PDPA tier (ไม่มี pilot org ผูก PSU)** — สร้าง headless API mode + auth token + session TTL + audit retention/rotation + capability report ให้เป็น deployment option ที่ maintain ได้ scope single-org (ไม่ multi-tenant); retire/แก้ docker-compose ที่ล้าสมัย **แต่ไม่ผูกกับ pilot ผ่าน PSU** ปล่อยเป็น documented deployment path ให้ org ที่มาเองใช้ได้ ลด priority ลงเพราะไม่มี partnership ดันและไม่ใช่แกน Engineering/Quality โดยตรง
19. **[M/สูง] Publish dataset ให้ benchmark เป็นมาตรฐานชุมชน** — dataset (synthetic) บน HuggingFace แบบ leaderboard (thainer-CRF, WangchanBERTa, fine-tuned model, presidio-thai เป็น baseline) เชิญคนอื่นมาวัดกับมัน เป็น benchmark ที่ทุกคนอ้าง = hedge กันแล็บใหญ่ปล่อยโมเดลแข่ง (ทำได้แบบ OSS solo ไม่ต้องมี co-author)
20. **[พัก - OSS solo] Funding ผ่านช่องไทย** — ตัดออกตาม decision (depa/NIA/PSU ส่วนใหญ่ต้องยึดกับมหาวิทยาลัย) ถ้าต้องการ sustainability แบบไม่ผูกสถาบัน เหลือ GitHub Sponsors เป็น option เดียวที่เข้ากับ OSS solo แต่ผลตอบแทนต่ำ ประเมินภายหลังถ้า adoption โต
21. **[M/กลาง] CWS publication บน stack ที่ unify + hardened แล้ว + cross-browser Edge** — จัดลำดับหลัง unification/hardening/native messaging ให้ listing อธิบายสถาปัตยกรรมสุดท้ายครั้งเดียว แล้วต่อ Edge (Chromium เดียวกัน share ในองค์กรไทยไม่น้อย)

---

## ลำดับที่แนะนำหลังล็อก decision (Engineering/Quality · OSS solo · unsigned)

เมื่อแกนคือ Engineering/Quality และเป็น solo ลำดับที่ให้ผลคุ้มที่สุดคือทำ "รากฐานที่วัดได้และ regress ไม่ได้" ก่อน แล้วค่อยต่อยอด:

1. **สัปดาห์แรก (NOW ล้วน):** #3 CI test gate -> #1 แก้ 3 recall leak -> #2 harden localhost API -> #4 collision-safe pseudonym ทั้งสี่นี้คือ "หยุดเลือด" ทำก่อนอย่างอื่นทั้งหมด เพราะเป็น repo public และเป็นฐานให้ refactor ต่อได้อย่างปลอดภัย
2. **สัปดาห์ 2-4 (NOW ที่เหลือ):** #5 single-source version + OSS front door docs -> #13 เริ่มวาง JS/Rust test harness (เลื่อนขึ้นมาเพราะเป็นแกน quality) #6 CWS submission กับ #7 launch post ทำคู่ขนานได้แต่เป็น product/impact ไม่ใช่แกนหลัก ทำเท่าที่เวลาเหลือ
3. **เดือน 2-3 (NEXT):** #9 benchmark corpus (เสาหลัก) -> #8 unify สองสมอง (ทำหลัง benchmark เพราะ benchmark คือ regression net ที่ทำให้ refactor นี้ปลอดภัย) -> #10 restructure TB detection (วัดผลด้วย benchmark) -> #11 verifiable build เดินคู่กันได้
4. **เดือน 3-12 (LATER):** #15 fine-tune Thai PII model (ต้องมี benchmark + windowing ก่อน) -> #16 native messaging -> #17 offset-accurate redaction + OCR bake-off -> #19 publish dataset #12 Presidio plugin แทรกได้ทุกเมื่อหลัง #9 (เป็น ecosystem play ที่เข้ากับ OSS solo)

หมายเหตุ dependency ที่สำคัญ: **benchmark corpus (#9) เป็น gatekeeper** ของเกือบทุกอย่างใน NEXT/LATER ที่แตะ detection (unify, TB restructure, fine-tune, OCR bake-off) เพราะไม่มีมันก็เปลี่ยน detection แบบมั่นใจไม่ได้ และ **CI gate (#3) เป็น gatekeeper ของ refactor ใหญ่** ทั้งหมด ทำสองอันนี้ก่อนคือการลงทุนที่ปลดล็อกที่เหลือ

---

## Risks (ข้ามทุกมุมมอง)

- **Corpus legality เป็นเรื่องเป็นตาย** — benchmark ที่มี PII จริงจะละเมิดกฎหมายที่เครื่องมือนี้ปกป้องเอง ต้อง synthetic-first ตั้งแต่วันแรก เอกสารจริงต้องมี consent + IRB/ethics ของ PSU ถ้าให้นักศึกษา annotate
- **ตัวเลข benchmark อาจไม่สวย** — recall ของ NAME/ADDRESS บน text จริงที่ messy อาจต่ำกว่าเรื่องเล่า "recall-first" การ publish baseline อ่อนพร้อมแผนพัฒนายังรอด แต่การถูกจับได้ว่าเลี่ยงการวัดไม่รอด
- **Unification refactor เสี่ยงสุด** — แตะ v2 API contract ที่ extension + desktop ที่ ship แล้วพึ่งอยู่ mitigation คือ dual test suite + API version stamp + grace path หนึ่ง release
- **การ hardening เป็น breaking change ที่ต้อง coordinate** — shared-secret ต้องลงพร้อมกันทั้ง server + extension + desktop + launcher; extension เก่าจะใช้กับ backend ใหม่ไม่ได้ ต้องมี capability field ใน /api/health
- **Bus factor = 1 คน ข้าม 3 ภาษา (Python + JS + Rust)** — Claude ย่นเวลา build แต่ไม่ย่น human-hour ของ community mgmt, CWS review, paper revision, pilot support
- **ไม่มี telemetry โดยตั้งใจ (เป็น privacy tool)** — regression จริงมองไม่เห็น benchmark ใน CI คือ feedback loop เดียว คุณภาพ coverage ของมันจึง load-bearing
- **PSU/DIIS อาจมากับเงื่อนไข IP/publication/branding** ที่ชนกับ north star adoption ตกลง ground rule เรื่อง open license ในการประชุมแรก ไม่ใช่หลัง corpus เกิด
- **แล็บใหญ่ (VISTEC, KBTG, SCB 10X) อาจปล่อยโมเดล Thai PII แข่ง** — benchmark-first คือ hedge แต่เฉพาะถ้า corpus ออกก่อนโมเดลเขา

---

## Kill-list (สิ่งที่ตั้งใจ "ไม่ทำ")

- **ห้ามมี cloud/SaaS-hosted version เด็ดขาด** — local-first คือเรื่องความเชื่อใจทั้งหมดและตัวแยกจาก cloud DLP ทุกเจ้า
- **Freeze feature บน `_tokenize`/`_SESSIONS`** — ของใหม่ลง unified core เท่านั้น path ซ้ำต้องถูกลบ ไม่ใช่ maintain
- **ห้ามทำ WangchanBERTa เป็น default NER ตอนนี้** — 1.3s/ประโยค + windowing ซ้ำ 7x + ไม่มี recall advantage ที่วัดแล้ว ต้องแก้ windowing + วัดก่อน
- **ห้ามสร้าง Presidio bridge แบบเดา** — เขียน decision doc หนึ่งหน้าก่อน และเอาออกจาก public future-work จนกว่าจะตัดสินใจ
- **ลบ dead cleaner stage (4/5/6) แทนที่จะแก้** — deletion ที่ซื่อสัตย์ดีกว่า code เพ้อฝัน reimplement เฉพาะเมื่อ benchmark ชี้ว่า gap สำคัญ
- **ห้าม claim accuracy/F1 ที่ไหน public ก่อน benchmark v1 ออก** — วินัย forbidden-claims จาก submission ยังใช้ต่อ
- **ไม่มี mobile app** — ปฏิเสธไปแล้วใน spec 07-04
- **ไม่มี multi-tenant/Redis session store** ก่อน pilot org จริงร้องขอ single-process in-memory vault เป็น feature ไม่ใช่ข้อจำกัด
- **หยุด claim Docker เป็น deployment ที่ support** ใน docs จนกว่า headless tier จริงจะมี compose ปัจจุบันมาก่อนสถาปัตยกรรม extension/desktop
- **deprioritize macOS polish** (notarization, universal build) — DMG ตอนนี้ arm64-only unsigned Gatekeeper block เต็มๆ ตลาดไทยคือ Windows + Chrome ทำเมื่อมี demand จริง
- **ไม่เพิ่ม chat-site adapter ที่ 7** จนกว่า Playwright harness + selector-drift telemetry จะมี
- **หยุดเขียนตัวเลขผันผวน (test count, version, platform list) ลง prose ด้วยมือ** — drift 269/272/274 เกิดในสัปดาห์เดียว fact อยู่ในไฟล์ machine-readable ไฟล์เดียว

---

## สิ่งที่ตัดสินใจแล้ว (2026-07-10)

1. ทิศทางหลัก 3-12 เดือน = **Engineering / Quality**
2. PSU/DIIS = **OSS solo** ไม่เดินสาย partnership
3. งบ signing = **Stay unsigned**

ดูผลกระทบเต็มที่หัวข้อ "Decisions ที่ผู้ใช้ล็อกแล้ว" ด้านบน และลำดับที่แนะนำ

## คำถามที่เปิดไว้สำหรับรอบถัดไป (ไม่ block งาน NOW)

- เริ่มลงมือ Horizon 1 เลยไหม หรืออยากรีวิวเอกสารนี้ก่อน ถ้าเริ่ม จุดตั้งต้นที่แนะนำคือ #3 (CI test gate) เพราะเป็นฐานให้ทุก refactor
- benchmark corpus (#9) จะ scope type อะไรบ้างในเวอร์ชันแรก (NAME, THAI_ID, PHONE, ADDRESS ก่อน แล้วค่อยเพิ่ม?) เป็น design decision ที่ทำตอนถึง NEXT
