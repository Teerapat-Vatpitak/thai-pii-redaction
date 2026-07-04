# Design: AI Guard — Desktop OSS Release (Tauri)

- วันที่: 2026-07-04
- สถานะ: Draft (brainstorm เสร็จ, รอ review ก่อนทำ implementation plan)
- ขอบเขต: roadmap ระยะยาว (ไม่ใช่งานที่ต้องเสร็จก่อนนำเสนอโปสเตอร์ 10 ก.ค.)

## 1. บริบทและเป้าหมาย

ปัจจุบัน AI Guard = engine ตรวจจับ/ปกปิด PII ไทย (core `pii_redactor/`, 259 เทสต์ผ่าน) + FastAPI backend
(`app/server.py`) + browser extension (MV3) + `AIGuard.exe` (PyInstaller onefile launcher).

**North star ใหม่ (ยืนยันโดยผู้ใช้ 2026-07-04):** ปล่อยเป็น **open source ฟรี ใครเอาไปใช้ก็ได้**
เป้าคือ **adoption สูงสุด** ของเครื่องมือปกป้อง PII ภาษาไทย การประกวด PSU FTC 2026 เป็น "เวทีหนึ่ง"
ไม่ใช่ปลายทาง

เกณฑ์ตัดสินดีไซน์จึงเปลี่ยนจาก "efficient สำหรับเดโม" เป็น **"น่าเชื่อถือ + ติดตั้งง่าย + ต่อยอด/ฟอร์กได้ง่าย +
ใช้ได้กว้าง"** โดยรักษา DNA เดิม: **ข้อมูลไม่ออกนอกเครื่อง (on-device เต็ม, vault in-memory)**

## 2. Non-goals

- ไม่ทำระบบจ่ายเงิน / license key / activation / DRM (เป็น OSS ฟรี)
- ไม่ย้าย backend ขึ้น cloud (ขัด DNA privacy)
- ไม่ rewrite engine เป็นภาษาอื่น (reuse Python + เทส 259)
- ไม่ทำ mobile ในเฟสนี้ (เคยสำรวจ Android on-device + share-extension แล้ว pivot มาเดสก์ท็อป — ROI สูงกว่า)

## 3. การตัดสินใจเรื่อง License (แตะ dependency)

**เลือก: Apache-2.0** (permissive + patent grant) เพราะพันธกิจคือ adoption กว้างสุดรวมถึงในองค์กร
ซึ่งฝ่ายกฎหมายมักแบน AGPL — copyleft จะกันกลุ่มเป้าหมายออกเอง

**ผลต่อโค้ด: ต้องสลับ PyMuPDF (AGPL) → `pypdfium2` (Apache/BSD, มีใน venv แล้ว)**
โมดูลที่กระทบ:
- `pii_redactor/redactor.py` — วาดกล่องดำทับ bbox (redaction). pypdfium2 เป็น render/extract เป็นหลัก
  การ "แก้ไข" PDF (วาง annotation/ลบ content) ต้องเสริม lib permissive เช่น `pikepdf` (MPL-2.0) หรือ
  สร้าง overlay ด้วย `reportlab` (BSD) — **ไม่ใช่ drop-in ต้องออกแบบใหม่**
- `pii_redactor/ingest/text_extractor.py` — extract ข้อความ + word bbox (pypdfium2 ให้ได้)
- `pii_redactor/exporter.py` — `pdf_text` export (สร้าง PDF จากข้อความ)

> หมายเหตุ: การ migration นี้เป็น "เฟสของตัวเอง" (ดูเฟสในข้อ 10) ทำเมื่อพร้อม release permissive จริง
> ระหว่างทางถ้ายังใช้ PyMuPDF อยู่ = เป็น AGPL ชั่วคราว (build ภายใน/prototype ได้ แต่ยังไม่ประกาศ Apache-2.0)

## 4. สถาปัตยกรรม

Tauri เป็น "เปลือกผลิตภัณฑ์" ที่ให้ signed installer + auto-update + tray + global hotkey โดย **ไม่ rewrite
engine** — เรียก engine เดิมผ่าน sidecar

```
┌──────────────── AI Guard.app (Tauri, installer เดียว) ─────────────────┐
│                                                                         │
│  Rust core                                                              │
│   - spawn/หยุด sidecar (AIGuard.exe), health-poll, restart, kill        │
│   - system tray + global hotkey (mask/restore ได้ทุกแอปในเครื่อง)        │
│   - single-instance guard, port-fallback, auto-update, auto-start       │
│                                                                         │
│  Webview dashboard (HTML/JS)  ──HTTP──►  127.0.0.1:8000                 │
│   - Redact PDF (ลากวาง)                        │                        │
│   - รายงาน PDPA / re-id risk / ม.26            ▼                        │
│   - Text panel (mask/restore วางมือ)     AIGuard.exe (sidecar)          │
│   - Settings / โหมด token·surrogate      = engine เดิม, 259 เทส         │
│   - Audit log viewer                     = FastAPI /api/*               │
└─────────────────────────────────────────────────────────────────────────┘
        +  Browser extension (Chrome Web Store) = หน้าร้านแชตในหน้าเว็บ
```

**หลักการ "Single Brain, Multiple Storefronts" ที่เป็นสินค้าจริง:** engine เดียว, หลายจุดสัมผัส —
tray+hotkey (ทุกแอป), dashboard (เอกสาร/รายงาน), extension (แชตในเบราว์เซอร์)

**tray+hotkey ไม่ใช่ทางเลือกที่แข่งกับ Tauri — Tauri เป็นตัวส่งมอบมัน** (Tauri มี global-shortcut + tray
+ updater ในตัว)

## 5. Components

### A. Rust core (ใหม่ — glue code, ไม่มี business logic)
- Sidecar lifecycle: spawn `AIGuard.exe`, health-poll `/api/health`, auto-restart on crash, kill on exit
- System tray (แสดง/ซ่อนหน้าต่าง, สถานะ, ออก)
- Global hotkey: เลือกข้อความที่ไหนก็ได้ → hotkey → mask ลง clipboard; อีก hotkey → restore
- single-instance guard (กัน spawn backend ซ้ำ), port-fallback (8000 → ว่างถัดไป)
- auto-update, auto-start on login (opt-in)

### B. Webview dashboard (ใหม่ — HTML/JS)
| หน้าจอ | API เดิมที่ใช้ |
|---|---|
| Dashboard/สถานะ | `/api/health` |
| Redact PDF (ลากวาง, before/after, ดาวน์โหลด) | `/api/redact-pdf` |
| รายงาน PDPA (re-id risk, ม.26, breakdown, คำแนะนำ) | `/api/analyze` |
| Text panel (mask/restore วางมือ, สลับ token/surrogate) | `/api/sanitize`, `/api/reidentify` |
| Settings (โหมด, NER engine, idle timeout, ลิงก์ extension) | — |
| Audit log viewer | `/api/audit-log` (ใหม่ — ดูข้อ 6) |

### C. Backend / sidecar (reuse ~100%)
- endpoints ที่มี: health, sanitize, reidentify, analyze, redact-pdf
- เพิ่มใหม่จุดเดียว: `GET /api/audit-log`

### D. Browser extension (reuse + ขึ้น Web Store)
- โค้ดเดิม MV3 (`extension/`) — เพิ่มการเผยแพร่ผ่าน Chrome Web Store แทน load unpacked

## 6. Audit log (ตัดสินใจแล้ว: แนวทาง (ก) + แยก log)

- **ประเด็นซ่อน (ต้องแก้ก่อน):** web path (`_SESSIONS` ใน `app/server.py`) ปัจจุบัน **ไม่เรียก `audit.py`** →
  action ผ่าน GUI ยังไม่มี audit record ต้อง **ต่อ audit-write เข้ากับ server endpoints ก่อน**
- **Read path = (ก) `GET /api/audit-log`** (อ่าน JSONL ที่ `audit.py` เขียน, ไม่มี PII) — สอดคล้อง one-API,
  เลี่ยงปัญหา path ไฟล์ต่างกันระหว่างรันจาก source กับ .exe (frozen) ที่ Rust อ่านตรงจะเปราะ
- **Process/crash log = Rust จับ stdout/stderr ของ sidecar** แยกต่างหาก (Rust เป็นคน spawn) ใช้ debug ตอน
  backend ล่ม — ซึ่ง endpoint ทำไม่ได้

## 7. Data flows

```
เปิดแอป:  Rust spawn sidecar → poll /api/health จนพร้อม → เปิด dashboard
Hotkey:   เลือกข้อความ (ทุกแอป) → hotkey → /api/sanitize → เขียน clipboard;  อีก hotkey → /api/reidentify
Redact:   ลาก PDF → /api/redact-pdf → before/after + ดาวน์โหลด
PDPA:     /api/analyze → เกรด + risk + ม.26 + คำแนะนำ
ปิดแอป:   Rust kill sidecar (ไม่ทิ้ง orphan)
```

## 8. Error handling (ส่วนใหญ่อยู่ที่ sidecar lifecycle)

| เหตุการณ์ | รับมือ |
|---|---|
| sidecar start ไม่ขึ้น (พอร์ตชน/โมเดลหาย/crash) | Rust จับ stderr → GUI โชว์ error + retry |
| พอร์ต 8000 ไม่ว่าง | Rust หา fallback port แล้วบอก GUI |
| backend crash กลางทาง | health-poll เจอ → auto-restart + แจ้ง; vault in-memory หาย (mask ใหม่) |
| OCR/ML ไม่ได้ bundle | endpoint คืน 503 พร้อมข้อความอยู่แล้ว → GUI graceful |
| PDF ใหญ่/ช้า | loading state + timeout + error |

## 9. Reuse vs เขียนใหม่

- **Reuse 100%:** engine `pii_redactor/` + เทส 259 + API endpoints เดิม + extension MV3
- **เขียนใหม่:** Rust shell (lifecycle/tray/hotkey/updater), webview dashboard (HTML/JS)
- **แก้ backend เล็ก:** เพิ่ม `/api/audit-log` + ต่อ audit-write เข้า endpoints
- **Migration (เฟสของตัวเอง):** PyMuPDF → pypdfium2 (+ pikepdf/reportlab) เพื่อ Apache-2.0

## 10. เฟสการทำ (แต่ละเฟสส่งของได้)

1. **Core shell:** Tauri + sidecar (AIGuard.exe) + dashboard (redact PDF / PDPA / text panel / settings) —
   ได้แอปเดสก์ท็อป on-device ที่ทำงานจริง ครบฟังก์ชั่นหลัก
2. **Universal input:** tray + global hotkey (mask/restore ทุกแอป) + audit viewer
3. **OSS-permissive:** migration PyMuPDF → pypdfium2, ประกาศ Apache-2.0, LICENSE + README + build docs
4. **Distribution:** GitHub Releases + winget/Scoop + ขึ้น extension บน Chrome Web Store + auto-update
5. **(ภายหลัง)** macOS/Linux builds

## 11. Distribution & release (OSS ฟรี)

- GitHub Releases (installer .msi/.exe), winget/Scoop/Chocolatey manifest
- Chrome Web Store สำหรับ extension (ฟรี)
- Code-signing = optional (OV/EV cert ลด SmartScreen warning; OSS จำนวนมากแจก unsigned ได้ก่อน)
- LICENSE (Apache-2.0), NOTICE, README build/run, CONTRIBUTING

## 12. Risks & tradeoffs (พูดตรง)

- **Polyglot = กำแพง contributor:** Rust + JS + Python ทำให้คนมาช่วยยากขึ้น (คนรู้ Rust น้อยกว่า Python).
  ผู้ใช้เลือก Tauri โดยรู้ trade-off นี้แล้ว — บันทึกไว้เป็นความเสี่ยง ถ้า contribution สำคัญกว่า polish
  ในอนาคต ทางเลือก "web UI จาก backend เดิม (ไม่มี Rust)" ยังกลับไปได้
- **pypdfium2 migration:** redaction (วาดกล่องดำ) ไม่ใช่ drop-in — ต้องออกแบบ PDF-editing ใหม่ด้วย lib permissive
- **Tauri sidecar cold start:** PyInstaller onefile แตกไฟล์ temp ทุกครั้ง — ช้ากว่ารันตรง; พิจารณา onedir
  หรือ service ที่รันค้าง
- **global hotkey ชนกับแอปอื่น:** ต้องให้ผู้ใช้ตั้ง hotkey เองได้

## 13. Open questions

- เลือก hotkey เริ่มต้นอะไร (ต้องไม่ชนของนิยม)
- ต้องมี macOS/Linux ในเฟสแรกไหม หรือ Windows-only ก่อน (ปัจจุบัน sidecar = PyInstaller ต่อ OS)
- redaction ด้วย pypdfium2: ใช้ pikepdf (MPL) หรือ reportlab (BSD) เป็นตัวช่วย — เคาะตอน migration
