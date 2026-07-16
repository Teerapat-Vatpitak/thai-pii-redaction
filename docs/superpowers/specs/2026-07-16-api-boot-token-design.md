# Localhost API boot token (Horizon-1 #2 ส่วนที่เหลือ) — Design

- วันที่: 2026-07-16
- สถานะ: การตัดสินใจล็อคโดย controller ร่วมกับผู้ใช้ (lane B ของงานขนาน)
- ขอบเขต: ปิด roadmap Horizon-1 #2 ส่วนที่ค้าง — random boot token กัน drive-by request บน control plane ของ backend localhost

## หลักคิด

Backend ฟังบน localhost และมี CORS/TrustedHost แล้ว แต่ endpoint ทำลายล้าง (`/api/shutdown`) พิสูจน์ตัวผู้เรียกด้วย header `X-AIGuard-Local` ซึ่งเป็นค่าคงที่ ใครก็ส่งได้ งานนี้เพิ่ม shared secret ที่เกิดตอน boot โดย **ไม่ทำ extension เดิมพัง**: บังคับ token เฉพาะ control plane และเฉพาะเมื่อ token ถูกตั้ง (grace path)

## การตัดสินใจที่ล็อคแล้ว

| ประเด็น | ตัดสินใจ |
|---|---|
| แหล่ง token | env var `AIGUARD_TOKEN` — server อ่านตอน import เก็บใน module var `_BOOT_TOKEN` (unset/ว่าง = enforcement ปิด พฤติกรรมเดิมทุกอย่าง) |
| ขอบเขต enforcement เฟสนี้ | เฉพาะ **control plane**: `POST /api/shutdown` และ `DELETE /api/session/{id}` — **ไม่บังคับ** `sanitize`/`reidentify` เพราะ extension ยังไม่มีช่องรับ token จนกว่าจะมี native messaging (Horizon-3 #16) บันทึกข้อจำกัดนี้ใน spec/README ชัดๆ |
| กติกา header | เมื่อ `_BOOT_TOKEN` ตั้งไว้: ต้องส่ง `X-AIGuard-Token` ตรงเป๊ะ (เทียบด้วย `secrets.compare_digest`) ไม่งั้น 403; เมื่อไม่ตั้ง: `/api/shutdown` ใช้กติกา `X-AIGuard-Local` เดิม, `DELETE /api/session` เปิดเหมือนเดิม (backward compatible 100%) |
| Capability discovery | `/api/health` เพิ่ม field additive `"capabilities": {"token_required": bool}` ให้ client ใหม่ตรวจได้ (ตาม mitigation ใน roadmap เรื่อง capability field) |
| launcher.py (exe/sidecar) | ถ้า `AIGUARD_TOKEN` ยังไม่ตั้ง ให้ generate `secrets.token_hex(16)` แล้วตั้งใน `os.environ` ก่อน import server เพื่อให้ in-process uvicorn เห็น — ห้าม print/log ค่า token เด็ดขาด |
| desktop (Tauri) | `sidecar.rs::spawn()` generate token (ใช้ `uuid::Uuid::new_v4()` หรือ rand ที่มีอยู่ใน deps — ห้ามเพิ่ม dependency ใหม่ถ้าเลี่ยงได้ ใช้ uuid ที่ tauri มีอยู่แล้วผ่าน `tauri::Uuid` หรือสร้างจาก `std` ผ่านเวลา+พิด ถ้าไม่มี ให้เพิ่ม dep `rand` เวอร์ชันเบา) ส่งเป็น env ให้ sidecar ตอน spawn เก็บใน state; `kill()` แนบ `X-AIGuard-Token` ตอนยิง `/api/shutdown` (คง `X-AIGuard-Local` ไว้ด้วยเพื่อเข้ากันกับ backend เก่า); กรณี `spawn()` เจอ backend ที่รันอยู่แล้ว (ไม่ได้ spawn เอง) → ไม่มี token → `kill()` ส่งแบบเดิม (backend dev mode ไม่ enforce อยู่แล้ว) |
| desktop frontend (api.js) | ไม่บังคับแก้ในเฟสนี้ (frontend ไม่เรียก shutdown/delete-session; ถ้าเรียก delete-session ที่ไหน ให้เพิ่ม Tauri command ขอ token จาก state แล้วแนบ header) |
| extension | ไม่แตะเลยในเฟสนี้ |

## กติกาของ lane (ห้ามละเมิด)

- ห้ามแก้ `CLAUDE.md` (controller อัปเดตหลัง merge)
- ห้ามแก้ `tests/test_step11_api.py`, `tests/test_api_hardening.py` (สอง test นี้ต้องยังเขียวเป๊ะ — พิสูจน์ grace path ว่า default ไม่เปลี่ยน)
- commit message ห้ามมี `Co-Authored-By: Claude` trailer
- ห้าม log/print ค่า token ที่ไหนทั้งสิ้น (รวมถึงใน error message และ test output)

## Testing

- `tests/test_api_token.py` ใหม่ (monkeypatch `server._BOOT_TOKEN` ตรงๆ ไม่ต้อง reload module):
  - token ตั้ง + header ถูก → shutdown 200 (monkeypatch `_schedule_exit` แบบเดียวกับ hardening test), delete-session ทำงาน
  - token ตั้ง + header ผิด/ขาด → 403 ทั้งสอง endpoint และ `X-AIGuard-Local` เดี่ยวๆ ใช้ไม่ได้เมื่อ token ตั้ง
  - token ไม่ตั้ง → พฤติกรรมเดิม (shutdown ต้องมี X-AIGuard-Local, delete-session เปิด)
  - `/api/health` มี `capabilities.token_required` ถูกต้องทั้งสองโหมด
  - response 403 ไม่มีค่า token สะท้อนกลับ
- Rust: ถ้า `cargo test` รันไม่ได้ใน worktree (placeholder sidecar binary ไม่อยู่) ให้ระบุใน report แล้วพึ่ง CI; อย่างน้อย `cargo check` หรืออ่าน compile ผ่านๆ ถ้าทำได้
- JS: `node --check` กับไฟล์ที่แตะ
- full suite pytest ต้องเขียวก่อนเปิด PR
