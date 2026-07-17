# JS/Rust test harness (Horizon-2 #13 — แกน test) — Design

- วันที่: 2026-07-17
- สถานะ: อนุมัติ design แล้ว (brainstorm ร่วมกับผู้ใช้) รอ implementation plan
- ที่มา: roadmap `2026-07-10-post-competition-longterm-roadmap.md` item #13 — "1,400 บรรทัดที่ไม่มี test เลยคือหนี้ที่ใหญ่ที่สุดสำหรับ solo maintainer"

## ขอบเขตที่เคาะแล้ว

| ชิ้น | รอบนี้? |
|---|---|
| (a) vitest+jsdom สำหรับ logic ล้วนของ extension | **ทำ** |
| (c) Rust integration test เรื่อง sidecar kill order | **ทำ** |
| CI wiring (job `js tests`) | **ทำ** |
| (b) Playwright fixture pages เลียน DOM สดของแต่ละ site | เลื่อน (รอบหน้า) |
| (d) selector-drift badge ใน UI | เลื่อน (เป็น product feature ต้องออกแบบ UX) |

ข้อจำกัดที่ยอมรับและบันทึกไว้ตรงนี้: HTML fixture คงที่จับ "logic ผิด" ได้ แต่จับ "เว็บจริงเปลี่ยน DOM" ไม่ได้ — อย่างหลังเป็นหน้าที่ของ (b)+(d)

## การตัดสินใจที่ล็อคแล้ว

| ประเด็น | ตัดสินใจ |
|---|---|
| Toolchain | `package.json` ใหม่ที่ root, devDependencies เฉพาะ `vitest` + `jsdom`, commit `package-lock.json` ด้วย (reproducible); ไม่มี bundler ไม่มี transpile |
| การทำให้ import ได้ | **export shim แบบ additive** ท้ายไฟล์ MV3: `if (typeof module !== "undefined" && module.exports) { module.exports = {...}; }` — พฤติกรรมใน browser ไม่เปลี่ยนแม้แต่ byte เดียวของ path เดิม ทำเฉพาะไฟล์ที่จะเทสต์ (เริ่ม `extension/sites.js`; `content.js`/`background.js` เฉพาะส่วน pure ที่แยก/expose ได้โดยไม่รื้อโครง — ถ้าแยกไม่ได้สะอาดให้ข้ามไว้ก่อน ไม่บังคับรื้อ) |
| ที่อยู่ของ test | `extension/tests/*.test.js` + fixtures ใน `extension/tests/fixtures/*.html` (DOM snapshot ย่อส่วนต่อ site เขียนมือจาก selector ที่ `sites.js` ใช้จริง ไม่ใช่ dump ทั้งหน้า) |
| สิ่งที่ test ชั้นแรกต้องครอบ | ต่อ site ทั้ง 6 (ChatGPT/Claude/Gemini/Grok/Perplexity/GLM·Z.ai): `composer()` เจอช่องพิมพ์จาก fixture, `assistantMessages()` คืนข้อความ; hostname → site matching; generic fallback เมื่อ hostname ไม่รู้จัก; พฤติกรรม fallback เมื่อ selector หลักไม่เจอ (คืน generic/ค่าว่างตามโค้ดจริง ไม่ throw) |
| Rust kill-order test | ใน `desktop/src-tauri` (unit/integration ตามโครงที่มี) gated `#[cfg(windows)]`: (1) shutdown POST ต้องมี header ถูกต้อง — พิสูจน์ด้วย mock listener จาก `std::net::TcpListener` (ห้ามเพิ่ม dependency ใหม่); (2) fallback `taskkill /T /F` ฆ่า process tree จริง — spawn เหยื่อ (`cmd /c timeout` หรือเทียบเท่า) แล้ว assert ตายทั้ง tree; อนุญาต refactor แบบ extract-function เท่านั้นถ้า `kill()` ผูกแน่นเกิน test ไม่ได้ ห้ามเปลี่ยนพฤติกรรม |
| CI | job ใหม่ `js tests (vitest)` บน ubuntu-latest: `npm ci` + `npx vitest run`; คง job `node --check` เดิมไว้ (ครอบไฟล์ที่ยังไม่มี test); kill-order test เข้า job `cargo test` เดิมอัตโนมัติ |
| นอกขอบเขต | ไม่แตะ Python ใดๆ; ไม่แตะ CLAUDE.md (controller sync หลัง merge); ไม่แตะ `tests/test_step11_api.py`/`test_api_hardening.py`; ไม่เพิ่ม eslint (คนละเรื่องกับ harness); desktop/src JS เอาไว้รอบถัดไปถ้า extension เสร็จแล้วเหลือแรง |

## Gate

1. Extension ยังโหลดใน Chrome ได้เหมือนเดิม (shim เป็น additive ล้วน — ยืนยันด้วยการไม่แตะโค้ด path เดิม + `node --check` ผ่านทุกไฟล์)
2. vitest ทั้งชุดเขียวทั้งบน Windows (local) และ ubuntu (CI)
3. `cargo test` เขียวรวม test ใหม่
4. full suite Python ไม่กระทบ (ไม่มีไฟล์ Python ถูกแตะ — ยืนยันด้วย git diff)
5. ไม่มี dependency ใหม่ฝั่ง Rust และฝั่ง JS มีแค่ vitest+jsdom (dev เท่านั้น ไม่เข้า package ของ extension)

## ความเสี่ยงที่รับไว้

- Fixture เขียนมือจะ drift จากเว็บจริงได้ — เป็นข้อจำกัดที่ประกาศแล้ว รอบ (b) แก้
- shim ทำให้ไฟล์ MV3 มี branch `module.exports` ที่ Chrome ไม่ใช้ — dead branch ใน browser โดยตั้งใจ แลกกับ testability โดยไม่มี bundler
- kill-order test ผูกกับ Windows (`taskkill`) — gated `#[cfg(windows)]` และ CI cargo job รันบน Windows อยู่แล้ว
