# Single-source version + OSS front door (Horizon-1 #5) — Design

- วันที่: 2026-07-16
- สถานะ: การตัดสินใจล็อคโดย controller ร่วมกับผู้ใช้ (lane A ของงานขนาน)
- ขอบเขต: ปิด roadmap Horizon-1 #5 — "VERSION ไฟล์เดียว + bump script + CI drift check; และเพิ่ม ROADMAP.md, CONTRIBUTING, SECURITY.md, CHANGELOG"

## การตัดสินใจที่ล็อคแล้ว

| ประเด็น | ตัดสินใจ |
|---|---|
| Source of truth | ไฟล์ `VERSION` ที่ root เนื้อหา `2.2.0` + newline (ไม่ bump รอบนี้ — เลขต้องตรง release จริงล่าสุด) |
| Runtime read | `app/server.py` อ่าน `VERSION` ครั้งเดียวตอน import (helper `_read_version()` มี fallback `"2.2.0"` เมื่อไฟล์หาไม่เจอ เช่นใน frozen exe เก่า) ใช้ทั้งใน `FastAPI(version=...)` และ `/api/health` — `tests/test_step11_api.py` pin `"2.2.0"` อยู่ ต้องเขียวโดยไม่แก้ test |
| Frozen exe | เพิ่ม `VERSION` เข้า PyInstaller datas ใน `scripts/build_sidecar.py` และ `_read_version()` รองรับ `sys._MEIPASS` |
| Bump script | `scripts/bump_version.py <new>` เขียนทับ version field ใน: `VERSION`, `extension/manifest.json`, `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/Cargo.lock` (เฉพาะ package `desktop`), `desktop/package.json` (ถ้ามี field version) — ไม่แตะ `packaging/` (มี hash ต่อ release ต้อง regenerate ตอน release จริง) |
| Drift check | `scripts/check_version.py` เทียบทุกไฟล์ข้างบนกับ `VERSION` ไม่ตรง exit 1 พร้อมรายการไฟล์ที่เพี้ยน; เพิ่ม step ใน `.github/workflows/ci.yml` (job เบาๆ ubuntu ไม่ต้องลง deps — pure stdlib) |
| ROADMAP.md | root, ภาษาไทยปนอังกฤษได้ สรุป 3 horizon + สถานะปัจจุบัน (#1 #3 #4 #8 เสร็จ, #2 บางส่วน, #5 งานนี้) ลิงก์ไป `docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md` เป็น detail |
| CONTRIBUTING.md | root, อังกฤษ: dev setup (venv, requirements แยกชั้น, PYTHONUTF8 บน Windows), รัน pytest, โครง repo ย่อ, PR conventions (conventional commits, CI ต้องเขียว, no hand-written volatile numbers) |
| SECURITY.md | root, อังกฤษ: supported version (latest release), report ผ่าน GitHub Security Advisories (private vulnerability reporting) ไม่เปิด public issue, threat model ย่อ (localhost-only backend, vault in-memory, no cloud) |
| CHANGELOG.md | root, รูปแบบ Keep a Changelog + SemVer; backfill สามรุ่นจาก git tags: v1.0.0, v2.0.0, v2.2.0 (สรุปหยาบจากประวัติ ไม่ต้องละเอียดทุก commit) + section Unreleased ที่มีของหลัง v2.2.0 (recall fixes, benchmark, union NER, unify core) |

## กติกาของ lane (ห้ามละเมิด)

- ห้ามแก้ `CLAUDE.md` (controller อัปเดตหลัง merge เพื่อกันชนกับ lane อื่น)
- ห้ามแก้ `tests/test_step11_api.py`, `tests/test_api_hardening.py`
- ห้ามแตะ `pii_redactor/` ยกเว้นไม่จำเป็นจริง (lane นี้ไม่ควรต้องแตะเลย)
- commit message ห้ามมี `Co-Authored-By: Claude` trailer
- ไม่ bump เลข version ใดๆ — งานนี้คือ "ท่อ" ไม่ใช่ release

## Testing

- unit test ใหม่ `tests/test_version_source.py`: `/api/health` version ตรงกับเนื้อหาไฟล์ `VERSION`; `_read_version()` fallback เมื่อไฟล์หาย; `scripts/check_version.py` จับ drift จริง (สร้าง temp copy แล้วแก้เลขหนึ่งไฟล์ → exit 1) และผ่านเมื่อตรง (exit 0); `scripts/bump_version.py` บน temp copy เขียนครบทุกไฟล์แล้ว check_version ผ่าน
- full suite ต้องเขียวก่อนเปิด PR
