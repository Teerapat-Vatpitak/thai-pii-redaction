# Audit v2 — Findings (ก่อน v2.3.0)

- วันที่: 2026-07-19 +07:00
- บริบท: audit รอบใหม่ทั้ง repo ตาม Phase 1 ข้อ 2 ของ roadmap v2 (`2026-07-17-roadmap-v2-design.md`) เหตุผลคือ audit "tier 1-6" รอบก่อนไม่มีเอกสาร findings เป็น artifact จึงยืนยันความครบไม่ได้ เอกสารนี้คือ artifact ถาวรที่กติกา audit ของ owner บังคับ
- วิธีทำ: multi-agent 6 ตัวขนานกัน แบ่งตาม subsystem (detection/anonymization, vault/AI/restore, web API, extension, desktop, scripts/CI/release) ทุก finding ต้องมี file:line + code excerpt จริง ห้ามเดาจากชื่อไฟล์
- การ verify ของ owner-side (Claude ตัวหลัก): finding ระดับ critical และ high ทุกตัวถูก reproduce/อ่านโค้ดยืนยันเองอีกชั้น สถานะระบุต่อ finding
- ขอบเขตที่ครอบ: `pii_redactor/`, `app/`, `extension/`, `desktop/`, `scripts/`, `.github/workflows/`, packaging, Docker
- สิ่งที่ยังไม่ได้ปิดในเอกสารนี้: การแก้โค้ด เอกสารนี้เป็นแค่ findings การแก้จะทำเป็น branch/PR แยกตามลำดับความรุนแรง

## สรุปจำนวน

| ความรุนแรง | จำนวน | id |
|---|---|---|
| Critical | 1 | DET-3 |
| High | 5 | DET-1, DET-2, VAULT-1, EXT-1, DESK-1 |
| Medium | 19 | DET-4/5/6/7, VAULT-2/3/4/5, API-1, EXT-2/3/4, DESK-2/3/4/5, REL-1/2/3 |
| Low | 34 | ที่เหลือ |
| รวม | 59 | |

สถานะการ verify
- CONFIRMED = reproduce ด้วยการรัน หรืออ่านโค้ดยืนยันเองแล้ว
- REPORTED = agent รายงานพร้อม code evidence ยังไม่ได้ reproduce เองรายตัว (ส่วนใหญ่เป็น medium/low)

ทั้งหมดเป็น finding ที่ owner ต้องตัดสินใจแก้ ไม่ใช่การอ้างว่าทำงานเสร็จแล้ว หลักฐานคือ code excerpt + repro ในเอกสารนี้

## สถานะการปิด (อัปเดต 2026-07-20)

Critical + High ปิดครบทั้ง 6 แล้ว commit `298f581` บน branch `audit-v2-findings` แก้แบบ TDD (red ก่อน green ทุกตัว) แล้วผ่าน workflow adversarial verification (6 skeptic agents) ซึ่งเจาะเจอ gap เพิ่ม 4 จุด (DET-2 ฟอร์มมีขีด, VAULT-1 Latin, EXT-1 side panel, DESK-1 empty masked) ปิดเพิ่มครบและ re-verify แล้ว suite เขียวทุกภาษา Python 504 / JS 36 / Rust 13

| id | สถานะ | fix |
|---|---|---|
| DET-3 | FIXED | ลบ deskew ออกจาก OCR path (bbox อยู่ space เดียวกับ redaction) |
| DET-1 | FIXED | landline regex 9 หลัก (BKK 2-3-4 + ต่างจังหวัด 3-3-3) |
| DET-2 | FIXED | `_deduplicate` เป็น score-primary + plate `(?!\d)` ครอบฟอร์มมีขีด/เว้นวรรค |
| VAULT-1 | FIXED | boundary guard: digit/Latin either-side, Thai both-sides |
| EXT-1 | FIXED | reuse session_id บน `/api/sanitize` (content script + side panel) + fallback 404/400 |
| DESK-1 | FIXED | interpret_* เช็ค status, mask fails-closed, empty masked = failure |

DET-1 WEAKNESS เรื่อง dot/paren separator เป็น pre-existing limitation ของทุก phone pattern ไม่ใช่ regression ขยับเป็น low finding แยก

### Medium: REL-1/2/3 ปิดแล้ว (commit `e02e02a`)

กลุ่ม release pipeline ปิดก่อนตัวอื่นเพราะ roadmap กำหนดว่าต้องเสร็จก่อน tag v2.3.0 (pipeline ยังไม่เคยรันบน tag จริงสักครั้ง)

| id | สถานะ | fix |
|---|---|---|
| REL-1 | FIXED | `check_version.py --expect-tag` + step ใน build job assert tag == "v" + VERSION ก่อน build/publish ส่ง tag ผ่าน env กัน injection |
| REL-2 | FIXED | pin SHA256 ของ NER model ใน `build_sidecar.py` + ปฏิเสธ `*.crfsuite` ที่ไม่ได้ pin (pythainlp ไม่ลบ model เก่า) |
| REL-3 | FIXED | `check_release_assets.py` ตรวจ asset set ก่อน hash/attest + ย้าย download dir เป็น `release-assets/` |

บทเรียนสำคัญ adversarial verification จับได้ว่า **ความพยายามแก้ REL-3 ครั้งแรกจะทำ release พังทุกครั้ง** เพราะการเพิ่ม `actions/checkout` ทำให้ `assets/` ที่ repo track อยู่ถูก materialize แล้ว `mkdir assets` fail ใต้ `bash -e` job ตายทั้ง job (ไม่มี SHA256SUMS ไม่มี attestation) ซึ่งพังหนักกว่า finding เดิม แก้เป็น `release-assets/` และมีเทสกัน dir ชนไว้แล้ว หมายเหตุ `mkdir -p` เป็น fix ที่ผิด เพราะจะทำให้ PNG ของ repo เองถูก hash และ attest ไปด้วย

### Low: REL-12 ปิดแล้ว (commit `b41fc18`)

ปิดก่อน tag เพราะเป็น finding เดียวที่ **เคยทำ CI พังจริงแล้ว** ไม่ใช่ความเสี่ยงเชิงทฤษฎี job `js-syntax` ที่ใช้ `node-version: "lts/*"` fail ด้วย `manifest.filter is not a function` ตอน setup-node ไป resolve LTS alias กับ GitHub API ช่วงที่ API ตอบ 503 ส่วน job `js-tests` ที่ pin เลข major ไว้แต่แรกไม่เคยเจอ path นั้นเลย

ยืนยันแล้วว่า setup-node v7 **ไม่ได้แก้** เคสนี้ (โค้ด `resolveLtsAliasFromManifest` เหมือน v4.4.0 ทุกบรรทัด) การ pin เวอร์ชันคือ fix จริง

| input | เดิม | ใหม่ |
|---|---|---|
| Node | `lts/*` | `22` (ตรงกับ job ที่ pin ไว้อยู่แล้ว) |
| Rust | `toolchain: stable` | `1.97.0` |
| pip | `install --upgrade pip` | `pip==26.1.2` |

apt จงใจไม่ pin (archive ของ Ubuntu ลบเวอร์ชันเก่า pin แล้วจะพังตอน archive หมุน) และเขียนระบุข้อยกเว้นไว้ใน release.yml header, CLAUDE.md, README.md แทนการปล่อยให้ประโยค "every build input is pinned" อ้างเกินจริง มี `tests/test_workflow_pins.py` กันถอยหลัง พิสูจน์แล้วว่าจับ regression ได้จริงไม่ใช่ผ่านลอย ๆ

สิ่งที่จงใจไม่ทำ ไม่ assert platform coverage ใน REL-3 เพราะการไล่ชื่อ bundle ต่อ platform ของ tauri-action สำหรับ pipeline ที่ไม่เคยรันจริง เสี่ยงทำให้ release แรก fail ผิด ๆ ซึ่งแย่กว่าช่องที่เหลือ (บันทึกไว้ใน docstring ของ script) ให้ revisit หลัง tag แรกรันจริง

Medium/Low ที่เหลือยังไม่ปิด (งานรอบถัดไป)

---

## Critical

### DET-3 — กล่องดำ redaction เลื่อนจากตัวอักษรบนหน้าสแกนเอียง (OCR path)

- สถานะ: CONFIRMED (อ่านโค้ดยืนยัน OCR stack ไม่ได้ติดตั้งในเครื่องจึง reproduce runtime ไม่ได้)
- ไฟล์: `pii_redactor/ingest/ocr_processor.py:85-107` และ `pii_redactor/redactor.py:133-160`
- อาการ: OCR สร้าง word bbox ในพิกัดของภาพที่ผ่าน `_deskew` หมุนแล้ว แต่ `redact_pdf` วาดกล่องดำลงบน render ของหน้า PDF ต้นฉบับที่ยังไม่หมุน ไม่มีการ apply inverse rotation ที่ไหนเลย หน้าสแกนที่เอียงจึงได้กล่องดำเลื่อนออกจาก PII จริง
- หลักฐาน:
  - `ocr_processor.py:105` `return cv2.warpAffine(image, matrix, ...)` แล้ว `_run_ocr_once` scale box จากภาพที่หมุนแล้วไปเป็น PDF point ตรง ๆ
  - `redactor.py:138` `pil = doc[idx].render(scale=RENDER_SCALE)...` render หน้าต้นฉบับ แล้ว `draw.rectangle(...)` ที่พิกัด bbox เดิม
  - แถมข้อ angle convention: `if angle < -45` (บรรทัด 96) เขียนตามสมัย OpenCV ก่อน 4.5 แต่ `requirements-ocr.txt` pin `opencv-python-headless>=4.9.0` ซึ่ง `minAreaRect` คืน angle ใน (0, 90] สาขา `< -45` จึงเป็น dead code และหน้าที่เกือบตรงอาจถูกหมุนเกือบ 90 องศา พิกัดพังทั้งหน้า
- failure scenario: สแกนเอกสารเอียง 2 องศา OCR อ่าน PII ได้ detection จับได้ แต่กล่องดำไปตกที่พิกัดของ frame ที่หมุนแล้ว PDF "true redaction" ที่ส่งออกมีเลขบัตรประชาชนโผล่ข้างกล่องดำ ซึ่งเป็น worst case ของผลิตภัณฑ์ redaction
- reachability: เฉพาะ path OCR (ต้องติดตั้ง `requirements-ocr.txt` ซึ่งไม่รวมใน exe) และเฉพาะหน้าที่เอียง path text-layer ไม่กระทบ
- แนวทางแก้: ตัด `_deskew` ออกก่อน extract box (ให้ PaddleOCR จัดการ orientation เอง) หรือ apply inverse rotation matrix กับทุก box ก่อนแปลงเป็น PDF point และแก้ logic angle ให้ตรง OpenCV >= 4.5

---

## High

### DET-1 — เบอร์โทรบ้านไทย 9 หลักตรวจไม่เจอ

- สถานะ: CONFIRMED (reproduce)
- ไฟล์: `pii_redactor/detectors/fp_detector.py:168-170`
- อาการ: regex landline ต้องการ 10 หลัก แต่เบอร์บ้านไทยมี 9 หลัก (02-XXX-XXXX) เบอร์บ้าน format มาตรฐานจึงหลุดทั้งหมด ผิด invariant recall > precision
- repro:
  ```
  detect_fp('โทร 02-123-4567 ครับ') -> []
  detect_fp('02-123-4567')          -> []
  detect_fp('021234567')            -> [('ID_NUMBER', (0,9), '021234567')]   # เจอแค่ form ไม่มีขีด และ mislabel เป็น ID_NUMBER
  ```
- failure scenario: sanitize "โทร 02-123-4567" ก่อนส่ง ChatGPT เบอร์หลุดไปหา AI ตรง ๆ ใน PDF ก็ไม่มีกล่องดำ
- แนวทางแก้: เปลี่ยน pattern เป็น 9 หลัก เช่น `0[2-5][-\s]?\d{3}[-\s]?\d{4}` และรองรับ grouping `0-2xxx-xxxx`

### DET-2 — regex ทะเบียนรถขโมยหลักแรกของเลขบัตร/เบอร์ ทำให้ตัวจริงหลุด

- สถานะ: CONFIRMED (reproduce end-to-end ผ่าน `detect_all`)
- ไฟล์: `pii_redactor/detectors/fp_detector.py:190-192` (ต้นเหตุ) และ `:75-88` `_deduplicate` (earlier-start-wins)
- อาการ: `_RE_VEHICLE_PLATE` ไม่มี trailing `(?!\d)` จึงกัด 1-4 หลักแรกของเลขยาวที่ตามหลังพยัญชนะไทย (เช่นตัวย่อ ปชช/กทม) แล้ว `_deduplicate` เลือก span ที่ start ก่อน (ทะเบียน) ทิ้ง THAI_ID/PHONE ที่ checksum ถูกต้องแต่ start ทีหลัง ส่วนที่เหลือของเลขจึงหลุดผ่านทั้ง ensemble
- repro:
  ```
  detect_all('เลขบัตร ปชช 1101700230708 ของผม') -> [('VEHICLE_PLATE',(8,16),'ปชช 1101')]   # เลขบัตร 13 หลัก checksum ถูก หายทั้งก้อน เหลือ 700230708 หลุด
  detect_all('ติดต่อคุณ กทม 0812345678')        -> [('VEHICLE_PLATE',(10,18),'กทม 0812')]  # 345678 หลุด
  ```
- failure scenario: prompt ที่มีตัวย่อ ปชช/กทม นำหน้าเลข → 9 หลักท้ายของเลขบัตร หรือ 6 หลักท้ายของเบอร์ ส่งไปหา AI ดิบ และ path PDF ก็ไม่ redact (fp+tb ไม่มี fn scan)
- แนวทางแก้: เพิ่ม `(?<!\d)`/`(?!\d)` boundary ให้ `_RE_VEHICLE_PLATE` และ/หรือให้ `_deduplicate` เลือกตาม score หรือ FP data-type priority แทน earlier-start

### VAULT-1 — reverse map โหมด surrogate ยัดตัวจริงกลางเลข/คำอื่นแบบไม่มี boundary

- สถานะ: CONFIRMED (reproduce)
- ไฟล์: `pii_redactor/reverse_mapper.py:66-81`
- อาการ: reverse map หา pseudonym แบบ raw substring (`text.find`) ไม่เช็ค boundary โหมด surrogate ที่ pseudonym เป็นค่าจริง ๆ (เบอร์ปลอม/ชื่อปลอม ไม่มีวงเล็บ) เมื่อ pseudonym บังเอิญเป็น substring ของเลข/คำอื่นใน response ของ AI จะถูก splice ทับด้วยค่าจริง corrupt เนื้อหาและยัด PII จริงไปในที่ที่ไม่ควร โดยไม่มี flag เตือน
- repro:
  ```
  vault: 0812345678(ปลอม) -> 0899999999(จริง)
  IN : อ้างอิงเลขที่ 08123456789012 ครับ
  OUT: อ้างอิงเลขที่ 08999999999012 ครับ      # เบอร์จริงยัดกลางเลขอื่น

  vault: วรรณ(ปลอม) -> สมหญิง ใจดี(จริง)
  IN : ผมชอบอ่านวรรณกรรมไทย
  OUT: ผมชอบอ่านสมหญิง ใจดีกรรมไทย            # ชื่อจริงยัดกลางคำว่าวรรณกรรม
  ```
- failure scenario: โหมด surrogate เมื่อ AI ตอบมี substring ตรงกับ pseudonym → เนื้อหาเพี้ยนและ PII จริงโผล่ผิดที่ ไม่มี residue/incomplete flag เพราะ pseudonym "ถูกแทนไปแล้ว" โหมด token ปลอดภัยเพราะวงเล็บกันไว้
- แนวทางแก้: ต้องมี boundary sanity อย่างน้อยสำหรับ surrogate mode (ปฏิเสธ match ที่อักขระข้างเคียงเป็น class เดียวกัน เช่น เลขติดเลข อักษรไทยติดชื่อไทย)

### EXT-1 — extension ไม่ส่ง session_id กลับ ทำ Restore ข้ามเทิร์นคืน PII ผิดคน

- สถานะ: CONFIRMED (อ่านโค้ด)
- ไฟล์: `extension/background.js:108` (และ 110, 118; `extension/sidepanel.js:87, 93`)
- อาการ: `/api/sanitize` ถูกเรียกด้วย `{ text, mode }` ไม่ส่ง session_id ที่เก็บไว้กลับไป ทุกครั้งที่ Mask จึงสร้าง session ใหม่และ `storeSession` เขียนทับ session_id เดิมของแท็บ เลขโทเคนเริ่มนับ 1 ใหม่ทุก session การ Restore คำตอบเก่าจึง map ด้วย vault ของ session ล่าสุด
- หลักฐาน:
  ```js
  const resp = await postJSON("/api/sanitize", { text: msg.text, mode });   // ไม่มี session_id
  if (resp.ok && resp.data && resp.data.session_id) {
    await storeSession(tabId, resp.data.session_id);                        // ทับ sid เดิม
  }
  ...
  const sid = msg.session_id || (await loadSession(tabId));                 // reidentify ใช้ sid ล่าสุด
  ```
- failure scenario: Mask ข้อความ 1 (นาย ก = `[ชื่อ_1]` ใน session A) แล้ว Mask ข้อความ 2 (นาย ข = `[ชื่อ_1]` ใน session B ทับ sid) กด Restore คำตอบเก่าที่มี `[ชื่อ_1]` → backend คืนด้วย map ของ session B → แสดงข้อมูลนาย ข แทนนาย ก โดยไม่เตือน การชนกันแทบแน่นอนในบทสนทนาหลายเทิร์น
- แนวทางแก้: ส่ง session_id ที่เก็บต่อแท็บ (และต่อ panel) กลับไปใน payload ของ `/api/sanitize` ตามที่ backend ออกแบบรองรับ multi-turn ไว้แล้ว

### DESK-1 — global hotkey ล้มเหลวเงียบ clipboard ยังเป็น PII ดิบ

- สถานะ: CONFIRMED (อ่านโค้ด)
- ไฟล์: `desktop/src-tauri/src/hotkey.rs:13-53`
- อาการ: handler mask/restore ไม่เช็ค `resp.status()` และ fall through เงียบทุก failure path (backend ยังไม่ boot, crash, หรือ 422 residual leak) ไม่มี toast ไม่มีเสียง clipboard ยังคงเป็น PII ดิบ ผู้ใช้เชื่อว่า mask แล้วจึง paste เข้า AI
- หลักฐาน:
  ```rust
  if let Ok(r) = resp {
      if let Ok(v) = r.json::<serde_json::Value>().await {
          if let (Some(sid), Some(masked)) = (v["session_id"].as_str(), v["sanitized_text"].as_str()) {
              ... write_text(masked ...)
          }
      }
  }
  // ทุก failure path ตกมาที่นี่โดยไม่แจ้งผู้ใช้ 422 ก็ไม่มี sanitized_text จึง fall through
  ```
- failure scenario: ผู้ใช้ copy บันทึกการแพทย์ กด Ctrl+Shift+M ช่วง backend กำลัง boot (waitForBackend poll ได้ถึง 30s) หรือหลัง crash → ไม่มี error → paste เข้า ChatGPT → PII ดิบออกไป กรณี 422 แย่กว่า เพราะ backend ปฏิเสธเนื่องจากเจอ residual leak แต่ hotkey กลืน
- แนวทางแก้: เช็ค `resp.status().is_success()` ก่อนถือว่าเป็นผล mask และทุก failure ต้องมี feedback ชัด (notification หรือเขียน clipboard เป็น error marker)

---

## Medium

### Detection / anonymization

| id | ไฟล์ | อาการย่อ | สถานะ | แนวทางแก้ |
|---|---|---|---|---|
| DET-4 | `anonymizer/anonymizer.py:231-238` | consistency scan ใช้ bare `str.replace` original สั้น (>=2 ตัว) ไปเขียนทับกลางคำไทยอื่น (reproduce: `กร` ทำให้ `กรุงเทพ` เพี้ยนเป็น `เกษมุงเทพ`) | CONFIRMED | replace เฉพาะที่ token boundary หรือข้าม original ที่สั้นเกิน และเช็ค substring กับทุก known pseudonym |
| DET-5 | `detectors/fp_detector.py:165-177` + `/api/redact-pdf` detect บน raw text | phone regex ใช้ literal ASCII `0`,`[6-9]` เบอร์เลขไทยที่มีขีด (`๐๘๑-๒๓๔-๕๖๗๘`) ไม่เจอบน path PDF ที่ไม่ผ่าน cleaner (form ไม่มีขีดยังเจอเป็น BANK_ACCOUNT) | CONFIRMED (partial) | ทำ phone pattern เป็น digit-class หรือแปลงเลขไทยก่อน match โดยคง offset |
| DET-6 | `detectors/tb_detector.py:134-137,143` | `_bio_to_spans` ข้าม token ที่ `find` ไม่เจอโดยไม่ปิด entity ทำให้ span หด (ท้ายชื่อหลุด) และ orphan `I-` โดนทิ้งทั้ง entity เสี่ยงกับ engine WangchanBERTa/union | REPORTED | track end offset จริงของ token ล่าสุด log เมื่อ find fail และ treat orphan `I-` เป็น `B-` |
| DET-7 | `redactor.py:146-149` | bbox ที่ text ยาว 1 ตัวไม่ถูก redact (`len>=2`) เลขบัตรที่พิมพ์เว้นวรรค (`1 1017 00230 70 8`) หลักแรก/ท้ายไม่มีกล่องดำ | REPORTED | ถ้า word เป็น substring ของ entity ให้ redact แม้ยาว 1 ตัว (โดยเฉพาะ digit) |

### Vault / AI / restore

| id | ไฟล์ | อาการย่อ | สถานะ | แนวทางแก้ |
|---|---|---|---|---|
| VAULT-2 | `session_service.py:123-125` | cap eviction เลือกเหยื่อจาก `created` ไม่ใช่ `last_access` session ที่ยัง active สุดถูกฆ่า และ data plane ไม่มี auth ใครก็ยิง sanitize 200 ครั้งฆ่า vault ที่ใช้อยู่ได้ (reproduce ด้วย cap=2) | FIXED | evict ตาม `last_access` (LRU) — TTL-expired เป็น LRU โดยนิยามจึงถูกฆ่าก่อนเสมอ |
| VAULT-3 | `session_service.py:85-146` + `app/server.py:260,313` | endpoint เป็น sync `def` รันขนานใน threadpool แต่ `SessionService` ไม่มี lock drop/evict null-byte clear vault ที่ thread อื่นกำลังใช้ ทำ `RuntimeError: dict changed size` หรือคืน text ไม่ restore | FIXED | `threading.RLock` serialize ทุก public entry (`_get_or_create`/drop/sanitize/restore) เทส pin drop ต้อง block ระหว่าง restore in-flight; adversarial review ยืนยันไม่มี path หลุด lock — trade-off ที่รับไว้: lock หยาบ serialize งาน NER ข้าม session แต่ class นี้รับแค่ extension ผู้ใช้เดียว (path ขนานจริง roundtrip/worker เป็น stateless ไม่แตะ) |
| VAULT-4 | `app/server.py:326` | `/api/reidentify` เขียน pseudonym เต็มลง audit log ผ่าน flag `leftover:{t}` ผิด invariant ที่ log ห้ามมี pseudonym และ `/api/audit-log` ก็ serve กลับออกมา | FIXED | log แค่ count + data_type ไม่ใช่ตัว token |
| VAULT-5 | `output_validator.py:139-144` | truncation heuristic flag ข้อความ >20 ตัวที่จบด้วยเลข/อักษรละติน → `halt=True` → exporter raise ExportError กับ output ปกติ (reproduce: จบด้วยเบอร์โทรที่ restore แล้ว) path web รอดเพราะ `_NOISY_PREFIXES` filter | CONFIRMED | ให้เลข/อักษรท้ายเป็น ending ที่ valid หรือ downgrade เป็น warning ไม่ halt |

หมายเหตุ VAULT-5 ทับซ้อนกับที่ CLAUDE.md อธิบายว่า Layer 3 เป็น Thai-aware แล้ว แต่ heuristic ยังพลาดกรณีจบด้วยเลข/อังกฤษ ซึ่งพบบ่อยมาก (บรรทัดสุดท้ายเป็นเบอร์โทร)

### Web API

| id | ไฟล์ | อาการย่อ | สถานะ | แนวทางแก้ |
|---|---|---|---|---|
| API-1 | `app/server.py:472-548` | `/api/redact-pdf` เป็น `async def` แต่รันงานหนัก (OCR/NER/render) sync ใน coroutine block event loop ทั้งเซิร์ฟเวอร์ระหว่างประมวลผล ต่างจาก endpoint อื่นที่เป็น `def` (เข้า threadpool) | FIXED | เปลี่ยนเป็น sync `def` อ่านผ่าน `pdf_file.file` เทส pin ว่า endpoint ไม่ใช่ coroutine function |

### Extension

| id | ไฟล์ | อาการย่อ | สถานะ | แนวทางแก้ |
|---|---|---|---|---|
| EXT-2 | `content.js:95-115` + `sites.js:57-90` | doMask จับ composer ก่อน await แล้วเขียนกลับหลัง response `writeComposer` คืน true เสมอ ไม่ตรวจว่าเขียนลง composer จริง รายงานสำเร็จทั้งที่ text ดิบยังอยู่ (fails-open, false positive) | REPORTED | re-query composer หลังเขียนและเทียบ readComposer ได้ sanitized จริงก่อนขึ้น status สำเร็จ |
| EXT-3 | `content.js:107-116` | Mask ล้มเหลวแจ้งแค่ status ตัวเล็กมุมจอ ไม่บล็อก/ดัก submit ปุ่ม Send เว็บ เส้นทางส่ง text ดิบเปิดเสมอ (fails-open เชิงสถาปัตยกรรม) | REPORTED | แสดงเตือนเด่นเมื่อ Mask ล้ม พิจารณาดัก Enter/submit ชั่วคราว |
| EXT-4 | `content.js:67-91,135` | ข้อความ restore (PII จริง) ถูกใส่ลง DOM ของเว็บ AI ผ่าน overlay ธรรมดา script ของเว็บ (session replay/analytics) อ่านได้ ขัด threat model (ยืนยันแล้วว่าไม่รั่วออกเครือข่ายอื่นนอก localhost เป็น DOM exposure) | REPORTED | แสดง restore ใน context ของ extension (side panel/iframe chrome-extension://) หรืออย่างน้อย closed shadow root |

### Desktop

| id | ไฟล์ | อาการย่อ | สถานะ | แนวทางแก้ |
|---|---|---|---|---|
| DESK-2 | `sidecar.rs:48-56` + `api.js:1` | `spawn()` ถือว่าอะไรก็ตามที่ listen 127.0.0.1:8000 คือ backend ของเราโดยไม่ verify identity process ที่ squat port ก่อนได้รับ clipboard PII และ text/PDF ทั้งหมดผ่าน data plane ที่ไม่มี auth | REPORTED | challenge identity หลัง attach หรือให้ shell เลือก ephemeral port แล้วส่งให้ sidecar |
| DESK-3 | `capabilities/default.json:14-17` | webview ได้ `shell:allow-execute` args=true + clipboard read/write + global-shortcut ทั้งที่ frontend ไม่ใช้ (ทำ Rust-side หมด) XSS ใน webview จึง escalate ไป re-exec AIGuard.exe และอ่าน clipboard ได้ | REPORTED | ลบ grant `shell:allow-execute`, clipboard-manager, global-shortcut ออกจาก capability |
| DESK-4 | `screen-report.js:63,99` | `b.count`, `r.direct_pii_count` interpolate ลง innerHTML โดยไม่ `escapeHtml` (ต่างจาก field อื่น) backend ที่ถูก squat (DESK-2) คืน string แทน number ทำ XSS ใน webview ที่มี IPC grant (DESK-3) | REPORTED | ห่อด้วย `escapeHtml(...)` หรือ `Number(...)` |
| DESK-5 | `sidecar.rs:184-188` + `lib.rs:26-36` | reap sidecar เฉพาะ `ExitRequested` shell crash/kill (ไม่มี Windows Job Object) orphan backend และ token ตายไปกับ shell instance ใหม่ attach แต่ shutdown ไม่ได้ (token mismatch) | REPORTED | ผูก sidecar กับ Job Object `KILL_ON_JOB_CLOSE` และ/หรือ fallback kill process ที่ถือ port เมื่อ verify identity แล้ว |

### Scripts / CI / release

| id | ไฟล์ | อาการย่อ | สถานะ | แนวทางแก้ |
|---|---|---|---|---|
| REL-1 | `.github/workflows/release.yml:21-37` | ไม่มีการเช็คว่า tag ที่ push ตรงกับ VERSION ก่อน build/publish tag `v2.3.0` บน commit ที่ VERSION ยัง 2.2.0 ได้ installer ผิดชื่อ และ update_packaging/scoop สมมติ tag==version พัง | REPORTED | เพิ่ม step แรกใน build job รัน check_version.py และ assert `"v"+VERSION == github.ref_name` |
| REL-2 | `release.yml:56-59` + `build_sidecar.py:53-77` | โมเดล thainer CRF โหลดตอน build โดยไม่ pin hash แล้ว bundle เข้า exe ที่ถูก attest ช่องโหว่ของคำว่า "ทุก build input pinned" | REPORTED | บันทึก SHA256 ของ `thai-ner-1-4.crfsuite` + `db.json` ใน repo แล้ว verify ก่อน bundle |
| REL-3 | `release.yml:127-167` | `checksums-and-attest` hash/attest asset ที่อยู่บน draft release ตอนรัน ไม่ใช่ของที่ job นี้ build (re-run/matrix race/ผู้มี contents:write แทรก asset) → asset แปลกได้ provenance first-party | REPORTED | ส่ง build output ระหว่าง job ผ่าน upload/download-artifact หรือ assert ชุด asset ตรง filename ที่คาดจาก VERSION ก่อน hash |

---

## Low (34)

รวมเป็นตารางสั้น หลักฐาน file:line ครบตาม agent report ยังไม่ reproduce เองรายตัว (สถานะ REPORTED ทั้งหมด ยกเว้นที่ระบุ)

### Detection / anonymization
| id | ไฟล์ | อาการย่อ |
|---|---|---|
| DET-8 | `fp_detector.py:159-164` | `_RE_IBAN`/`_RE_EMAIL` ใช้ `\b` ซึ่งไม่ fire ระหว่างไทยกับละติน ค่าที่ติดคำไทยหลุด (เหมือนที่เคยแก้ให้ numeric/passport แล้วแต่ลืม email/iban) |
| DET-9 | `fn_scanner.py:25` | fn EMAIL `[^\s@]+` กลืนคำไทยข้างเคียงเข้า span over-redaction |
| DET-10 | `anonymizer.py:189-194` | token ordinal ไล่ย้อน document order (`[ชื่อ_1]` = ชื่อสุดท้าย) สับสนแต่ไม่ผิด |
| DET-11 | `fp_generator.py:60-70,54-57` | `_gen_date` day-first เสมอ (ISO เพี้ยน) และ bank account ทิ้ง separator format-preserving ไม่รักษา format |
| DET-12 | `report.py:43-46` | `scan_section26` ใช้ `search` เก็บ match แรกต่อ category multi-occurrence under-report (flag-only) |

### Vault / AI / restore
| id | ไฟล์ | อาการย่อ |
|---|---|---|
| VAULT-6 | `session_vault.py:160-161` | `clear()` rebind string ใหม่ (str immutable) ไม่ได้ทับ memory จริง และ `Entity.original_text` ใน `_Session.entities` ไม่ถูก scrub การันตี null-byte อ่อนกว่าที่ docstring อ้าง |
| VAULT-7 | `session_vault.py:133-152` | `snapshot()` shallow copy share VaultRecord `restore()` หลัง `clear()` ปลุก map กลับ (null-byte originals) snapshot ที่ค้างลบล้าง clear |
| VAULT-8 | `reverse_mapper.py:118` | residue flag ฝัง `pseudonym[:8]` (token mode 8 ตัว = ทั้ง token) ผิด contract ที่ flag ห้ามมี PII value |
| VAULT-9 | `app/server.py:124` | `compare_digest` raise `TypeError` บน header non-ASCII (starlette decode latin-1) → 500 แทน 403 |
| VAULT-10 | `exporter.py:73-84` | write probe ชื่อคงที่ `.write_probe` (concurrent race) และ write failure เฉพาะ Windows (`:`,`?`,`CON`) โผล่เป็น OSError ดิบ ไม่ใช่ ExportError |
| VAULT-11 | `session_service.py:165-179` | `sanitize()` เขียน vault ก่อน leak guard บน `OutboundLeakError` ไม่ rollback vault โต asymmetric ทุก turn ที่ถูกบล็อก |
| VAULT-12 | `session_vault.py:199-213` | `_audit_entries` โตไม่จำกัด (3 read/entity/turn) session ยาวสะสม memory ไม่มี cap |
| VAULT-13 | `reverse_mapper.py:71` + `session_service.py:249-251` | token mode restore exact-substring markdown-escaped token (`\[ชื่อ_1\]`) ทั้งไม่ restore และ leftover check มองไม่เห็น silent fail |

### Web API
| id | ไฟล์ | อาการย่อ |
|---|---|---|
| API-2 | `app/server.py:259-366` | text endpoint (sanitize/analyze/reidentify) ไม่มี cap ความยาว (มีแต่ non-empty) `_MAX_PDF_BYTES` กัน PDF อย่างเดียว |
| API-3 | `app/server.py:507-508` | error path PDF สะท้อน `{e}` ดิบใน 422 อาจรั่ว path/library internal |
| API-4 | `app/server.py:271-290 ฯลฯ` | `write_process_log` เรียกไม่สม่ำเสมอบน error path audit log บันทึกเคสล้มเหลว/บล็อกไม่ครบ |

### Extension
| id | ไฟล์ | อาการย่อ |
|---|---|---|
| EXT-5 | `sidepanel.js:56-67,95` | highlightTokens split/join บน HTML ที่มี markup แล้ว token หลัง match ใน markup ได้ HTML เพี้ยน (ไม่ใช่ XSS เพราะ escape แล้ว display bug) |
| EXT-6 | `manifest.json:35-48` + `sites.js:234-245` | content script inject กว้างกว่าหน้าแชท (`*.z.ai`, `*.bigmodel.cn`, `*.chatglm.cn`) ครอบ dev console/หน้า API key และ selectFor ใช้ substring match |
| EXT-7 | `sites.js:170-176 ฯลฯ` | selector assistantMessages บน grok/perplexity/zai กว้าง (`[class*='response']`) "คำตอบล่าสุด" อาจเป็น node ผิด (wrapper ทั้งบทสนทนา) |

### Desktop
| id | ไฟล์ | อาการย่อ |
|---|---|---|
| DESK-6 | `lib.rs:26-35` + `tray.rs:14` | setup spawn sidecar ก่อน tray/hotkey ถ้า tray fail (หรือ `default_window_icon().unwrap()` panic) build Err → `.expect` panic ออกโดยไม่ kill orphan backend |
| DESK-7 | `hotkey.rs:36-53` | Ctrl+Shift+R รู้จักเฉพาะ session ที่ hotkey mask สร้าง หลัง mask ใน UI restore hotkey no-op เงียบ หรือ restore ด้วย session เก่าผิด |
| DESK-8 | `tauri.conf.json:14` | CSP มี `style-src 'unsafe-inline'` และ `connect-src http://localhost:8000` (ชื่อ localhost กว้างกว่า loopback IP ที่ใช้จริง) `script-src 'self'` แน่นดีแล้ว |

### Scripts / CI / release
| id | ไฟล์ | อาการย่อ |
|---|---|---|
| REL-4 | `release.yml:79-81` | Tauri CLI ติดตั้งด้วย `npm install` ไม่ใช่ `npm ci` regenerate lock เงียบถ้า drift |
| REL-5 | `ci.yml`, `smoke-crossplatform.yml` | ไม่มี `permissions:` block GITHUB_TOKEN inherit default อาจ write-all |
| REL-6 | `release.yml:15-17,25,91` | comment บอก dispatch จาก branch "fail harmlessly" แต่จริงสร้าง draft release ชื่อ branch ที่ checksum+attest ได้ |
| REL-7 | `bump_version.py:39-54` | เขียน VERSION ก่อน validate target ครบ parse fail แล้วทิ้ง tree half-bumped |
| REL-8 | `update_packaging.py:33-38` | urlopen ไม่มี timeout และ SHA256SUMS ที่ fetch ไม่ถูก cross-check กับ attestation ก่อนเขียนลง manifest |
| REL-9 | `Dockerfile:1,13-14` | Docker อยู่นอก verifiable-build story: base tag ลอย (`python:3.11-slim`) deps ไม่ pin Python 3.11 (ที่อื่น 3.13) |
| REL-10 | `test_lock_coverage.py:1-71` | lock coverage เช็คแค่ชื่อ package ไม่เทียบ version floor lock เก่าที่ต่ำกว่า floor ใหม่ผ่าน test |
| REL-11 | `test_lock_coverage.py:52-66` | test hardcode source-file list ไม่ derive จาก `lock_deps.LOCKS` input ใหม่หลุด guard |
| REL-12 | `release.yml:40-74` | pip/rustc/node/apt ลอย ("stable","lts/*",unversioned) แม้ action SHA pin แล้ว |
| REL-13 | `test_version_source.py:80-89` | `test_read_version_falls_back...` hardcode `"2.2.0"` เป็นสำเนา version ที่ 3 ต้อง hand-bump อีกจุด |
| REL-14 | `lock_deps.py:50` | เครื่องมือ gen lock (uv) ติดตั้งเองแบบไม่ pin |
| REL-15 | `packaging/scoop/aiguard.json:31-37` | scoop autoupdate update url อย่างเดียว ไม่มี hash extraction จาก SHA256SUMS |

---

## พื้นที่ที่ตรวจแล้วสะอาด (ยืนยันตาม agent)

- CORS regex + TrustedHost (`app/server.py`): agent ทดสอบ origin หลอกหลายแบบ (`https://chrome-extension.evil.com`, `eviltauri.localhost`, trailing-newline) ไม่หลุด `fullmatch` anchor ถูก TrustedHost กัน DNS rebinding host binding เป็น 127.0.0.1
- Temp file `/api/redact-pdf`: `mkdtemp` ชื่อสุ่ม `rmtree` ใน finally ลบทุก path
- Boot token: `secrets.compare_digest` constant-time, legacy grace path ตาม design, CSRF-safe (preflight)
- `/api/audit-log`: field allowlist ไม่มี PII value/path
- session_vault `write()` collision guard: ปฏิเสธ pseudonym reuse ข้าม original, internal audit มีแค่ `{action, entity_id, timestamp, session_id}`
- ai_client pre-send guard: รัน detect_fp + detect_tb จริง halt บน real hit, exception ไม่มี PII, retry classify transient ถูก
- reverse_mapper positional splice (token mode): non-overlapping, tail-first, longest-first, `[ชื่อ_1]` vs `[ชื่อ_10]` ไม่ cross-match (วงเล็บปิด disambiguate)
- leak_guard: fail-closed, FP zero leniency
- thai_id mod-11 checksum: อัลกอริทึมถูก รับเลขไทยได้
- sensitive_detector: non-generative degrade เป็น `[]` ได้ไม่มี ML
- manifest.json extension: permission น้อยสุด (`storage`, `clipboardWrite`, `sidePanel`) ไม่มี `tabs`/`scripting`/`<all_urls>`/`externally_connectable` backend origin hardcode localhost ไม่มีช่อง redirect
- content.js: สร้าง DOM ด้วย createElement/textContent ไม่มี innerHTML กับ backend data restore ไม่ออกเครือข่ายนอก localhost
- Tauri updater: HTTPS + minisign pubkey pinned; taskkill args เป็น Vec ไม่มี shell interpolation; AIGUARD_TOKEN 122-bit uuid ส่งผ่าน env ไม่ใช่ argv ไม่ log
- workflows: ทุก `uses:` pin 40-char SHA, ไม่มี `pull_request_target`, ไม่มี `${{ github.event.* }}` ใน `run:`; CI/exe/release install `--require-hashes`; Dockerfile non-root ไม่มี ADD from URL; docker-compose bind 127.0.0.1
- pipeline.py: order ถูก (dedupe ก่อน anonymize, guard ก่อน send, validate ก่อน export); known gaps (bbox dropped, quality unused, audit.py ไม่ถูกเรียก) ยืนยันตาม documented

## ลำดับการปิด findings ที่เสนอ

1. Critical + High ก่อน (DET-3, DET-1, DET-2, VAULT-1, EXT-1, DESK-1) แต่ละตัวมี failure ที่เป็น PII leak/corrupt จริง ปิดแบบ TDD (red test ก่อน)
2. Medium กลุ่ม leak/leak-adjacent (DET-4, DET-5, VAULT-2/3/4, EXT-2/3) รองลงมา
3. Medium/Low release pipeline (REL-1/2/3) ต้องปิดก่อน tag v2.3.0 เพราะ pipeline ยังไม่เคยรันจริง
4. Low ที่เหลือทยอยปิดหรือย้ายเข้า backlog ตามที่ owner ตัดสิน

เกณฑ์ปิด Phase 1 (จาก roadmap v2): ไม่มี finding ระดับสูงค้างก่อน tag v2.3.0
