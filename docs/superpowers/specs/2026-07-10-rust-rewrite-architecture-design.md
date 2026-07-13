# Rust rewrite architecture — AI Guard backend

- วันที่: 2026-07-10 22:29 +07:00
- บริบท: หลังจบการประกวด PSU FTC 2026 ผู้ใช้ตัดสินใจ rewrite backend จาก Python เป็น Rust ทั้งหมด เอกสารนี้ล็อกสถาปัตยกรรมปลายทาง ลำดับการ migrate และ spec ของ sub-project แรก
- เอกสารที่เกี่ยวข้อง: [post-competition long-term roadmap](2026-07-10-post-competition-longterm-roadmap.md) (แผนเดิม), การสแกน deep-scan 2026-07-10 (ยืนยัน bug/หนี้ด้วยการรันโค้ดจริง)
- คงเดิม: product ทำอะไรและ data flow ไม่เปลี่ยน เปลี่ยนแค่เครื่องยนต์ใต้ฝากระโปรง

## Decisions ที่ล็อก (2026-07-10)

1. **Rewrite backend เป็น Rust ทั้งหมด** runtime ของ product เป็น Rust ล้วน binary เดียว ไม่มี Python interpreter ไม่มี PyInstaller ไม่มี process/port ที่สอง
2. **เส้น purity** pure-Rust ก่อนเสมอ ใช้ native lib เฉพาะสองกรณี (ก) ที่ product พึ่งอยู่แล้ว = PDFium ผ่าน `pdfium-render` (ของเดิมก็ ship PDFium ผ่าน pypdfium2) (ข) ที่ pure-Rust สู้ได้จริง = `candle` สำหรับ NER ไม่ใช่กติกา "ห้ามแตะ C/C++ ทุกกรณี" ซึ่งจะทำให้ PDF แย่ลงโดยไม่ได้อะไรกลับ
3. **NER = WangchanBERTa** ทิ้ง thainer-CRF เดิม ใช้ WangchanBERTa (RoBERTa-base ไทย) fine-tune บน PII แล้วรันด้วย candle เหลือโมเดลตระกูลเดียว recall สูงกว่า CRF ตรงกับ invariant recall > precision
4. **Migration แบบ library-first bottom-up** ซอยเป็น sub-project ทำทีละอัน เทสต์ครบก่อน merge Python เดิมยังเป็นตัว ship จนกว่า Rust จะพิสูจน์แล้ว cutover แล้วค่อยลบ Python pytest เดิมเป็น behavioral oracle
5. **กติกาการเขียนโค้ด (จากผู้ใช้)** ไม่มี comment สักบรรทัด โค้ดเพียวๆ และเตรียมเทสต์ทุกสถานการณ์ที่เป็นไปได้ รันทุกครั้ง ผ่านเขียวจริงเท่านั้นถึงนับว่าเสร็จ

## สิ่งที่ทำไปแล้ว (stopgap ฝั่ง Python)

ก่อนเริ่ม Rust ได้ปิดช่องโหว่ security ที่ยืนยันว่ายิงได้จริงบน Python server เดิม (ยังเป็นตัว ship ระหว่าง migrate) ยืนยันด้วย pytest 295 passed + ยิง uvicorn จริง 8 เคสผ่าน

- ล็อก CORS เป็น `allow_origin_regex` เฉพาะ extension/tauri origin (ปิด drive-by exfil chain ผ่าน audit-log + reidentify)
- `TrustedHostMiddleware` กัน DNS rebinding
- `/api/shutdown` ต้องมี header `X-AIGuard-Local` (ปิด DoS) + อัปเดต `sidecar.rs` ให้ส่ง header
- `_SESSIONS` idle TTL 1800s + `DELETE /api/session/{id}`
- audit-log อ่าน bound (newest 50 ไฟล์) + ตัด `session_id` ออกจาก response

## สถาปัตยกรรมปลายทาง

Cargo workspace ที่ repo root binary เดียว native lib เฉพาะ PDFium กับ (ทางอ้อม) BLAS ของ candle

| Crate | ชนิด | หน้าที่ | native dep |
|---|---|---|---|
| `aiguard-core` | lib | FP detect (regex+checksum), pseudonymize (token/surrogate กัน collision), vault (TTL, snapshot/restore), reverse mapper, output validator NER ฉีดผ่าน trait `NerEngine` | ไม่มี |
| `aiguard-ner` | lib | WangchanBERTa fine-tuned PII: candle + `tokenizers` + `nlpo3` (Rust Thai word tokenizer) + safetensors impl `NerEngine` | ไม่มี (candle pure Rust; อาจ link BLAS optional) |
| `aiguard-server` | bin | axum HTTP wired core+ner harden ตั้งแต่วันแรก (token auth, CORS ล็อก, TrustedHost, session TTL, DELETE, audit bound) คง v2 contract | ไม่มี |
| `aiguard-pdf` | lib | PDF extract (text+word bbox) + redact (raster + กล่องดำ flatten-to-image) | PDFium (`pdfium-render`) |
| `benchmark` | bin/lib | corpus PII ไทยสังเคราะห์ (generator เดียวปั้น training data ให้ ner ด้วย) + harness recall/precision + CI gate | ไม่มี |

Process model: Tauri spawn `aiguard-server` (Rust sidecar หรือ embed ในตัว Tauri เลย) ไม่มี Python child ให้ reap อีก (ปัญหา PyInstaller onefile หายไป) browser คุยแค่ Rust surface โมเดล WangchanBERTa เก็บเป็นไฟล์ safetensors asset (quantize) โหลดตอน boot

## NER track (zoom)

- **โมเดล** WangchanBERTa base (`airesearch/wangchanberta-base-att-spm-uncased`, RoBERTa-base, ~105M params, SentencePiece) fine-tune หัว token-classification บน PII label (NAME, ADDRESS, DATE และแยก DATE_OF_BIRTH, เก็บ ORGANIZATION)
- **ข้อมูลเทรน** สังเคราะห์จาก `fp_generator`/`tb_generator` (roadmap #9) เป็น synthetic-first เลี่ยง PII liability และ scale ด้วย generator ไม่ใช่แรงคน
- **เทรนที่ไหน** fine-tune เป็น build-time step ครั้งเดียว ทำ offline ได้ (Python + GPU บน Colab) แล้ว export safetensors การเทรนไม่กระทบความ pure ของตัวที่ ship เพราะ runtime = candle Rust ล้วน
- **runtime** candle โหลด safetensors + `tokenizers` crate โหลด tokenizer.json เดียวกัน + `nlpo3` ตัดคำไทย (Rust port ของ newmm โดยทีม PyThaiNLP)
- **สิ่งที่ต้องแก้ก่อนให้เป็น default** (kill-list จาก scan) windowing ±3 ประโยคที่ re-tag ซ้ำ ~7x ต้องเปลี่ยนเป็น non-overlapping/stride + batch inference, quantize ลดขนาด/latency, และ**วัด recall เทียบ CRF บน benchmark ก่อน** ไม่เท product ลงไปกับโมเดลก่อนพิสูจน์
- **trade-off ที่รับ** ทิ้ง CRF ที่เล็ก instant offline ฝังใน exe ได้ แลก recall สูงขึ้น + สแตกโมเดลเดียว size ~30-50MB หลัง quantize inference Rust เร็วกว่า Python

## ลำดับ sub-project

แต่ละอัน = spec + plan + PR + เทสต์ครบก่อน merge

1. **`aiguard-core`** (เริ่มที่นี่ ความเสี่ยง ML = 0) FP + pseudonymize + vault + reverse + validator + `NerEngine` trait + stub exit: พฤติกรรมตรง/ดีกว่า Python (pytest เป็น oracle) recall leak + collision + บั๊ก strict-brain แก้ตั้งแต่ต้น เทสต์ครบ
2. **`benchmark`** corpus สังเคราะห์ + harness recall/precision + CI gate exit: วัด per-type recall ได้จริงใน CI ปั้น training data ให้ #3
3. **`aiguard-ner`** WangchanBERTa fine-tune PII → candle impl `NerEngine` → พิสูจน์ recall กับ benchmark exit: recall >= baseline CRF ที่ latency ยอมรับได้
4. **`aiguard-server`** axum harden wired core+ner คง v2 contract exit: parity กับ Python contract + hardened + token auth
5. **cutover** extension/desktop → Rust port + `aiguard-pdf` + packaging → ลบ Python exit: ผู้ใช้จริงรัน Rust binary, Python ออกจาก repo

dependency: #1 กับ #2 มาก่อนเสมอ #3 ต้องมี #2 #4 ต้องมี #1+#3 #5 ต้องมี #4 เหมือน roadmap เดิม แค่ NER อยู่ใน Rust

## Sub-project #1 — `aiguard-core` (spec ตัวแรก)

**Modules (แต่ละตัวเล็ก แยก responsibility ชัด เทสต์เดี่ยวได้)**

- `detect/fp` regex + checksum ต่อ data_type: Thai ID (mod-11), phone (มือถือ + landline 9 หลัก + +66 รวมวงเล็บ), email, bank, credit card (Luhn), IBAN, passport, vehicle plate, student ID, DOB ใช้ digit-boundary lookaround ไม่ใช่ `\b`
- `pseudonymize` token mode (`[ชื่อ_1]`) + surrogate mode (valid-format ปลอม) collision-safe by construction (uniqueness check + re-roll, ยกพฤติกรรมดีจาก web `_make_surrogate` + `_dedupe_spans`)
- `vault` in-memory pseudonym ↔ original, idle TTL, snapshot/restore rollback, scrub ตอน clear
- `reverse` restore longest-pseudonym-first
- `validate` layered: FP leak scan (raise), completeness/residue (flag), integrity (halt) แก้ให้ไม่ false-halt กับ prose ไทย
- `ner` trait `NerEngine` + `StubNer` (คืนว่าง) ให้ core เทสต์ได้โดยไม่มีโมเดล

**บั๊ก/leak ที่แก้ by construction (ยืนยันจาก scan ว่ามีจริงใน Python)**

- landline regex 10 หลัก → แก้เป็น 9 หลัก (`02-123-4567` เดิมหลุด)
- `(+66) 81 234 5678` วงเล็บเดิมหลุด → รับ
- email ติดอักษรไทยเดิมหลุด (`\b`) → digit/script-boundary + รันบนทุก path (redact-pdf/analyze เดิมไม่รัน fn scan)
- เลขบัตรตัด line break เดิมหลุด → รับ separator ยืดหยุ่นในกลุ่ม
- pseudonym pool เล็กชนกันจน restore ผิดคน → uniqueness check + re-roll
- `run_pipeline` โยน PreSendValidationError กับชื่อไทย (pseudonym ติดคำข้างเคียง) → แก้ exclusion ให้ token-aware
- Layer-3 truncation heuristic halt กับ prose ไทยทุกอัน → แก้เกณฑ์ไม่พึ่ง terminal punctuation

**Test strategy** table-driven unit ต่อ data_type + `proptest` (property) สำหรับ checksum/round-trip + corpus adversarial จาก scan (Thai-glued, +66 variants, line-break, collision) + parity harness เทียบผล Python บน example เดิม ไม่มี comment ในโค้ดและเทสต์

## สิ่งที่ไม่เปลี่ยน

- product ทำอะไร (mask ก่อนส่ง AI → restore ในเครื่อง, ทับดำ PDF) และ data flow
- v2 HTTP contract (`/api/sanitize`, `/api/reidentify`, `/api/analyze`, `/api/redact-pdf`, `/api/health`) เพื่อให้ extension/desktop ทำงานต่อได้ตลอด cutover (เติม token ทีหลัง)
- vault ไม่ออกจากเครื่อง, recall > precision, PDPA Section 26 flag เท่านั้นไม่ auto-redact

## Risks

- **WangchanBERTa latency/size** หนักกว่า CRF ต้อง fix windowing + quantize + วัดก่อน default ไม่งั้น flow interactive ช้าจนใช้ไม่ได้
- **หา/เทรนโมเดล** ต้องมี checkpoint WangchanBERTa NER ที่รันใน candle ได้ หรือ fine-tune เอง (ต้อง GPU offline) ยังไม่ยืนยันว่ามี checkpoint สำเร็จรูปที่ candle โหลดตรงได้ ต้อง spike
- **candle รัน WangchanBERTa** RoBERTa arch candle รองรับ BERT/RoBERTa แต่ต้องยืนยัน parity ของ tokenization (SentencePiece) กับผล Python
- **PDF via PDFium** เป็น native dep (เหมือน product เดิม) ไม่ regress purity แต่ผูก binary PDFium
- **benchmark legality** synthetic-first ตั้งแต่วันแรก ห้าม PII จริง
- **bus factor 1 ข้าม Rust + candle + ML** Claude ย่นเวลา build แต่ recall regression มองไม่เห็นถ้าไม่มี benchmark ใน CI

## Kill-list (ยกมาจาก roadmap + ย้ำ)

- ห้ามมี cloud/SaaS-hosted version local-first คือทั้งหมดของความเชื่อใจ
- freeze feature บน Python `_tokenize`/`_SESSIONS` ของใหม่ลง Rust core เท่านั้น Python ต้องถูกลบ ไม่ maintain
- ห้ามทำ WangchanBERTa เป็น default ก่อนแก้ windowing + วัด benchmark
- ไม่มี comment ในโค้ด Rust/เทสต์ที่เขียนใหม่
- ห้าม claim accuracy/recall/F1 public ก่อน benchmark v1 ออก

## Open questions (รอบถัดไป ไม่ block งาน #1)

- NER bootstrap: ใช้ checkpoint WangchanBERTa NER สำเร็จรูป (thainer-v2) รันใน candle ให้ทำงานก่อน แล้วค่อย fine-tune PII เอง หรือ fine-tune จาก base ตั้งแต่แรก
- PDF: ยืนยัน `pdfium-render` ให้ word bbox ที่ redaction ต้องการ (per-char box → group เป็น word เหมือน `_extract_pdf_pypdfium2` ปัจจุบัน)
- OCR: ตัดออกจาก v1 (เป็น optional tier อยู่แล้ว ไม่อยู่ใน exe) ค่อยกลับมาทำ (tesseract binding หรือ ocrs) เมื่อมี demand
- benchmark scope v1: เริ่ม NAME, THAI_ID, PHONE, ADDRESS ก่อน แล้วเพิ่ม
