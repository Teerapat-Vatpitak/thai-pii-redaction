# Unify web + CLI ให้เหลือ core เดียว (roadmap Horizon-2 #8) — Design

- วันที่: 2026-07-16
- สถานะ: อนุมัติ design แล้ว (brainstorm ร่วมกับผู้ใช้) รอ implementation plan
- ที่มา: roadmap `2026-07-10-post-competition-longterm-roadmap.md` item #8 — gatekeeper ครบแล้ว (CI gate PR #24, benchmark v1/v2 PR #26/#27, Horizon-1 #1/#3/#4 ปิดแล้ว)

## ปัญหา

สถาปัตยกรรมปัจจุบันมี "สองสมอง" ที่ไม่ถูกรวม

- **CLI path** (`pii_redactor/pipeline.py` + `SessionVault`) เข้มงวดครบด่าน มี pre-send leak guard, vault snapshot/rollback, reverse_mapper, 3-layer output validation
- **Web path** (`app/server.py` `_tokenize` + `_make_surrogate` + `_SESSIONS`) คือทางที่ extension และ desktop ใช้จริง ยืมแค่ detectors — **ไม่ผ่าน vault, ไม่ผ่าน leak guard, ไม่ผ่าน reverse_mapper, ไม่ผ่าน validator ใดเลย**

คุณสมบัติความปลอดภัยที่โฆษณาไว้จึงไม่ครอบเส้นทางที่ผู้ใช้จริงเดิน งานนี้รวมให้เหลือสมองเดียวใน `pii_redactor/` โดย server เหลือ adapter บาง

## การตัดสินใจที่ล็อคแล้ว

| ประเด็น | ตัดสินใจ |
|---|---|
| แนวทางสถาปัตยกรรม | **A: core facade + server บาง** (module ใหม่ `session_service.py` ใน core; ปฏิเสธ B server เรียกชิ้นส่วนตรง เพราะปลูกสมองที่สองรูปย่อ และ C ยัดเข้า run_pipeline เพราะ web ไม่มี AI call ฝั่ง server) |
| API contract | **คง v2 ทุก field + เพิ่มได้เฉพาะ additive** (`warnings[]`) extension/desktop เก่าใช้ต่อได้โดยไม่ต้อง release พร้อมกัน |
| Guard UX บน `/api/sanitize` | **Hybrid ตามความมั่นใจ**: FP leak (checksum ผ่าน) → HTTP 422 ไม่คืนข้อความ; TB leak (NER เดาผิดได้) → คืนข้อความ + `warnings[]` |
| PyPI publish | **ไม่รวมรอบนี้** (เก็บเป็นงานถัดไปหลัง core API นิ่ง) |
| Version string | ไม่แตะ (คง 2.2.0) — single-source version เป็นงาน Horizon-1 #5 แยก |
| `_tokenize`/`_SESSIONS` | **ลบทิ้ง** ตาม kill-list ("path ซ้ำต้องถูกลบ ไม่ใช่ maintain") |

## สถาปัตยกรรม

### Component ใหม่

**`pii_redactor/session_service.py`** — สมองเดียวของโหมด AI Guard

- class `SessionService` ถือ `_sessions: dict[session_id → _Session]`
- `_Session` เก็บ: `SessionVault`, `EntityRegistry` **สะสมทั้ง session** (ไม่ใช่ต่อ request), `mode` (ล็อคตอนสร้าง), `salt` ประจำ session, `created`, `last_access`
- นโยบายเดิมของ `_SESSIONS` คงครบ: cap 200 (evict ตัวเก่าสุด), idle TTL 1800s, ลบ session แล้ว `vault.clear()` (null-byte overwrite) เสมอ
- methods: `sanitize(text, mode="token", session_id=None) → SanitizeResult`, `restore(session_id, text) → RestoreResult`, `drop(session_id)`

**`pii_redactor/anonymizer/token_generator.py`** — bracket-token mode ใน core

- `generate_token(data_type, ordinal) → "[ชื่อ_1]"` — ย้าย `_TOKEN_LABEL` (label ไทยต่อ type) จาก server มาเป็น single source ที่นี่
- `anonymize()` รับ param ใหม่ `mode="surrogate"|"token"` (default `surrogate` = พฤติกรรมเดิม, CLI ไม่เปลี่ยน)
- โหมด token: ordinal = จำนวน original ไม่ซ้ำของ type นั้นใน vault + 1 → เลขต่อเนื่องข้าม turn
- uniqueness checks ของ `_generate_unique_pseudonym` ใช้กับ token ด้วยเหมือนกัน

**`pii_redactor/leak_guard.py`** — guard แชร์ระหว่าง CLI กับ web

- ดึง logic จาก `ai_client._validate_pre_send` (position-based pseudonym ranges + per-segment remainder scan + cue-preserving `_cue_leak_in_window` ที่แก้ใน PR #33/#34) ออกเป็นฟังก์ชัน pure `scan_outbound_leaks(text, vault) → list[Entity]` (ไม่ raise)
- `ai_client._validate_pre_send` เรียกตัวนี้แล้ว raise ทุกกรณี (พฤติกรรม CLI เดิมเป๊ะ)
- `SessionService.sanitize` เรียกตัวเดียวกันแล้วใช้นโยบาย hybrid

**`SessionVault.get_by_original(original) → VaultRecord | None`** — lookup เพิ่มสำหรับ token consistency ข้าม turn (scan `_table` O(n) พอ ขนาด vault ต่อ session เล็ก)

### สิ่งที่ลบ

- `app/server.py`: `_tokenize`, `_make_surrogate`, `_SESSIONS` dict + eviction/TTL helpers, `_TOKEN_LABEL` — endpoint เหลือ adapter แปลง JSON เข้าออก `SessionService` เท่านั้น

### สิ่งที่ไม่เปลี่ยน

- `run_pipeline` เดิน 8 ขั้นเดิม (มี `send_to_ai` ฝั่งตัวเอง) แค่ guard ชี้ module แชร์
- `/api/analyze`, `/api/redact-pdf`, `/api/health`, `/api/audit-log` ไม่แตะ
- detection ensemble (`detect_all` + `dedupe_spans` กลาง) ใช้ร่วมอยู่แล้วตั้งแต่ PR #34

## Data flow

### `sanitize` (หนึ่งการกด Mask)

1. ไม่มี `session_id` → สร้าง session ใหม่ (สุ่ม salt, ล็อค mode) / มี → ดึง session เดิม เช็ค TTL ก่อน (หมดอายุ/ไม่รู้จัก → 404) mode ที่ส่งมาขัดกับของ session → 400
2. `detect_all(text)` → entities ใหม่ต่อเข้า registry สะสมของ session
3. `anonymize(text, registry_turn_นี้, vault, salt=session_salt, mode=session_mode)` — ความสม่ำเสมอข้าม turn: surrogate จาก salt เดิม (deterministic ต่อ original), token จาก `vault.get_by_original`
4. `scan_outbound_leaks(sanitized, vault)` → FP leak → 422; TB leak → `warnings[]`
5. คืน `{session_id, original_text, sanitized_text, entities[], entity_type_counts, section26[]}` (v2 ครบ) + `warnings[]`

### `restore` (กด Restore)

1. ดึง session (404 ถ้าหมดอายุ) → `reverse_map(ai_text, registry_สะสม, vault)` longest-first เหมือน CLI
2. output validator 3 ชั้น — **ทุก finding เป็น warning ไม่ block** เพราะทิศทางข้อมูลคือขาเข้า ไม่มีอะไรรั่วออกนอกเครื่องแล้ว (เช่น Layer 1 เจอ PII ที่ AI แต่งใหม่ → `ai_generated_pii:THAI_ID`)
3. คืน `{restored_text, replaced[], replaced_count, leftover_tokens}` (v2 ครบ) + `warnings[]`

## ตาราง error

| เหตุการณ์ | ผล |
|---|---|
| session ไม่รู้จัก / หมดอายุ TTL | 404 |
| mode ขัดกับ session เดิม | 400 |
| FP leak หลัง anonymize | 422 พร้อมชนิด (ห้ามมีค่า PII ใน response) |
| `_generate_unique_pseudonym` exhausted (ValueError) | 422 — mask ไม่สำเร็จจริง ห้ามคืนข้อความ |
| TB leak / validation findings ตอน restore | 200 + `warnings[]` |

## Testing

1. **Contract net**: `tests/test_step11_api.py` + `tests/test_api_hardening.py` ต้องผ่านโดยแก้น้อยที่สุด — แตะได้เฉพาะ test ที่จิ้ม internal `_SESSIONS` ตรง (เปลี่ยนเป็นจิ้ม `SessionService`) test ที่ assert response shape ห้ามแก้ นี่คือหลักฐานว่า contract v2 ไม่แตก
2. **Unit ใหม่** `tests/test_session_service.py`: token/surrogate ordinal, multi-turn consistency (original เดิม → pseudonym/token เดิมข้าม turn, เลขไม่ชน), TTL/cap/evict + null-byte clear, hybrid guard (FP → 422-equivalent error, TB → warnings), restore warnings (AI แต่ง PII), `token_generator`, `vault.get_by_original`
3. **E2E**: จำลอง flow extension เต็มวงทั้งสองโหมด หลาย turn ใน session เดียว + salt sweep (หลาย salt × ไฟล์ตัวอย่างจริง `examples/prompts/*` + `tests/sample_thai.txt`) กัน guard false positive บนเส้นทางใหม่ แบบเดียวกับที่ใช้จับ flake ใน PR #34

## ความเสี่ยงที่รับไว้

- test hardening บางตัวต้อง migrate จาก `_SESSIONS` internals ไป `SessionService` (ยอมรับ — internal ไม่ใช่ contract)
- `/api/sanitize` เข้มขึ้น มี 422 ที่เดิมไม่มี — เป็นความตั้งใจของงานนี้ (extension เดิมที่ไม่รู้จัก 422 จะ error ตอน mask ซึ่งถูกต้องกว่าปล่อยรั่ว และเกิดเฉพาะกรณี FP leak ที่วัดแล้วโอกาสต่ำมากหลัง PR #33/#34: 0/240 salt sweep)
- multi-turn เปลี่ยน semantic จาก "session ใหม่ทุก mask" เป็น "extension เลือกส่ง session_id เดิมได้" — backward compatible เพราะ param เป็น optional

## นอกขอบเขต (รอบหน้า)

- PyPI publish ของ `pii_redactor`
- Version bump / single-source VERSION (Horizon-1 #5)
- random boot token `X-AIGuard-Token` (Horizon-1 #2 ที่เหลือ)
- การอัปเดต extension/desktop ให้ "ใช้ประโยชน์" จาก warnings[] และ multi-turn (contract รองรับแล้ว ฝั่ง UI ตามทีหลังได้)
