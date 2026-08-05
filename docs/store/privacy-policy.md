# AI Guard — นโยบายความเป็นส่วนตัว / Privacy Policy

_อัปเดตล่าสุด / Last updated: 2026-08-05_

ลิงก์ถาวรของหน้านี้ (สำหรับกรอกในฟอร์ม Chrome Web Store):
`https://github.com/Teerapat-Vatpitak/thai-pii-redaction/blob/main/docs/store/privacy-policy.md`

---

## ภาษาไทย

### สรุปสั้น

ส่วน Extension และ backend ของ AI Guard ใช้ detector ในเครื่องโดย default ไม่มีการส่งข้อความไปยังเซิร์ฟเวอร์ของผู้พัฒนา และไม่มี analytics หรือ tracking หากผู้ใช้เลือก TNER แบบ remote อย่างชัดเจน backend จะส่งข้อความดิบก่อนปกปิดเป็นช่วง ๆ ไปยัง AI for Thai เมื่อคุณกดส่งข้อความในหน้าเว็บแชท ข้อความนั้นจะถูกส่งไปยังบริการ AI ที่คุณเลือกตามการทำงานปกติของเว็บนั้น

### AI Guard ทำอะไรกับข้อมูลของคุณ

Extension เรียก backend บนเครื่องของคุณโดยตรงเท่านั้น (`http://localhost:8000` หรือ `http://127.0.0.1:8000`) ซึ่งไม่ใช่เซิร์ฟเวอร์ของผู้พัฒนา extension ตัว extension ไม่มี host permission หรือโค้ดที่เรียกปลายทางอื่น แต่ backend จะเรียก AI for Thai หากผู้ใช้ตั้งค่า `AIGUARD_NER_ENGINE=tner` อย่างชัดเจน Source build ปัจจุบันยังไม่ยืนยันตัวตนของ process ที่ครอบครอง port 8000 ดังนั้นควรใช้กับ backend ที่คุณเปิดและเชื่อถือเท่านั้น ระบบ native broker สำหรับ packaged build ยังเป็น hardening gate ที่เปิดอยู่

เมื่อคุณกดปุ่ม "Mask PII" (บนแถบลอยในหน้าเว็บแชท AI หรือใน side panel) extension จะอ่านข้อความจากช่องพิมพ์ (หรือข้อความที่คุณเลือก/คำตอบล่าสุดของ AI เมื่อกด "Restore PII") แล้วส่งข้อความนั้นไปยัง backend ผ่าน loopback เพื่อตรวจจับและปกปิด PII ก่อนส่งต่อให้ AI ภายนอก Source build v1 ปัจจุบันยังเขียนผลกลับได้เมื่อพบ text-based residual warning จึงยังไม่ใช่ fail-closed production package ผู้ใช้ต้องตรวจผลก่อนกดส่ง

เมื่อใช้ปุ่ม Mask ในหน้าเว็บ ข้อความดิบถูกพิมพ์ลงใน DOM ที่ควบคุมโดยเว็บ AI ก่อน extension ทำงาน โค้ดของเว็บอาจเห็นหรือส่ง draft นั้นได้ก่อนถูกแทนที่ Contract v2 และ native broker แก้ขอบเขตนี้ไม่ได้ หากต้องการขอบเขตที่เข้มกว่า ให้พิมพ์ข้อความดิบใน side panel แล้วนำเฉพาะผลที่ปกปิดและตรวจแล้วไปวางในเว็บ AI

ตารางหลักที่แปลงค่าจริงกลับไปกลับมากับรหัสปลอม ("vault") อยู่ใน **หน่วยความจำของ backend บนเครื่องคุณ** และไม่มีการจงใจเขียนลงดิสก์ แต่ HTTP contract v1 ปัจจุบันส่ง field ที่มีหรือใช้ประกอบ token-to-original mapping กลับมาในหน่วยความจำของ extension ได้ แม้ extension จะไม่จงใจเก็บ field เหล่านี้แบบถาวร เป้าหมายของ contract v2 คือไม่ส่ง explicit mapping DTO และให้ extension เก็บ `session_id` แบบ opaque ซึ่งเป็นรหัสอ้างอิงที่มีความสำคัญด้านความปลอดภัย

### Extension เก็บอะไรไว้ในเบราว์เซอร์ของคุณบ้าง

| ข้อมูล | เก็บไว้ที่ | อายุ | มีข้อมูลส่วนบุคคลไหม |
|---|---|---|---|
| `session_id` (รหัสอ้างอิงเซสชันต่อแท็บ) | `chrome.storage.session` | extension ลบเมื่อ Chrome แจ้งว่าปิดแท็บ; Chrome ล้าง session storage เมื่อจบ browser session | ไม่ใช่ mapping แต่เป็น bearer-like session reference ที่ต้องป้องกัน |
| ค่าที่เลือกไว้ล่าสุด (token / surrogate) | `chrome.storage.local` | อยู่ถาวรจนกว่าคุณจะลบ extension หรือล้างข้อมูล | ไม่ เป็นค่าตั้งค่า UI |
| ธีมที่เลือก (system / light / dark) | `localStorage` ของหน้า side panel | อยู่ถาวรจนกว่าคุณจะลบ extension หรือล้างข้อมูล | ไม่ เป็นค่าตั้งค่า UI |

extension ไม่จงใจเก็บข้อความที่คุณพิมพ์, PII หรือ mapping แบบถาวร ข้อมูลและ response object อาจอยู่ชั่วคราวในหน่วยความจำระหว่างประมวลผล; canonical vault อยู่ในหน่วยความจำของ backend

### Audit log ของ backend

Backend v1 เขียน process/security audit เป็นไฟล์ JSONL ในโฟลเดอร์ log ของ source/packaged app (หรือ stdout เมื่อเปิดโหมด hosted) โดยไม่ใส่ข้อความดิบ, pseudonym หรือ mapping source ปัจจุบันใช้ operation UUID ใหม่ที่ไม่มีสิทธิ์ restore สำหรับชื่อไฟล์และ entry ของ sanitize/reidentify/roundtrip แต่ชื่อ field เดิมยังเป็น `session_id`; เทส local ครอบคลุมทั้งโหมดไฟล์และ configured stdout `/api/audit-log` ไม่ส่ง field นี้ออกมา ในโหมดไฟล์ แต่ละ operation สร้างไฟล์เฉพาะและไฟล์เหล่านี้ไม่มีการลบตามเวลาอัตโนมัติ ส่วนโหมด stdout ไม่สร้างไฟล์ Backend ที่เผยแพร่ใน Desktop 2.5.0 ยังใช้ live session ID สำหรับ audit event ของ sanitize/reidentify; event ของ roundtrip ใช้ label คงที่ที่ไม่ใช่ session ID และยังไม่มี package ที่รวม correlation change ปัจจุบันผ่าน acceptance

### สิทธิ์ (permissions) ที่ขอ และเหตุผล

- **storage** — เก็บค่าที่เลือก (token/surrogate) และ `session_id` ชั่วคราวตามตารางด้านบน
- **clipboardWrite** — ใช้เฉพาะตอนคุณกดปุ่ม "คัดลอก" ใน side panel เพื่อคัดลอกข้อความที่ปกปิดแล้วไปยัง clipboard ของคุณ extension ไม่มีการอ่าน clipboard
- **sidePanel** — เปิดพื้นที่ทำงาน side panel ที่ docked ข้างเบราว์เซอร์
- **host_permissions** (`http://localhost:8000/*`, `http://127.0.0.1:8000/*`) — ให้ extension เรียก backend บนเครื่องคุณเองข้าม origin ได้ (ไม่ใช่เซิร์ฟเวอร์ภายนอก)
- **content scripts** บนเว็บแชท AI ที่รองรับ (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai) — ใช้แสดงแถบ Mask/Restore และหา composer/reply ที่น่าจะตรงผ่าน site selector กับ generic fallback เมื่อผู้ใช้กดปุ่ม หากเว็บเปลี่ยน selector fallback อาจเลือก element ที่มองเห็นอื่นซึ่งตรงเงื่อนไข

### สิ่งที่ AI Guard ไม่ทำ

- ไม่มี analytics, telemetry หรือ tracking ใด ๆ
- ไม่ส่ง backend call หรือ telemetry ไปยังเซิร์ฟเวอร์ของผู้พัฒนา; ข้อความที่ผู้ใช้กดส่งในหน้าเว็บจะไปยังบริการ AI ที่ผู้ใช้เลือก
- AI Guard ไม่ขายข้อมูลหรือส่งข้อมูลให้ผู้พัฒนา; ข้อความที่ผู้ใช้กดส่งจะถูกประมวลผลโดยบริการ AI ที่ผู้ใช้เลือก
- ไม่เก็บ mapping ระหว่างข้อมูลจริงกับรหัสปลอมไว้ถาวร canonical vault จะถูกทิ้งเมื่อ backend ปิด, session ถูกลบ/evict หรือเมื่อ service ตรวจพบ idle expiry ในการทำงานครั้งถัดไป

### ติดต่อ

ช่องทางติดต่อผู้ดูแลโปรเจกต์: โปรไฟล์ GitHub ของผู้ดูแล — `https://github.com/Teerapat-Vatpitak`

---

## English

### Summary

The AI Guard extension and backend use a local detector by default. They do not send text to the developer's servers, and there is no analytics or tracking. If the user explicitly selects remote TNER, the backend sends raw pre-mask chunks to AI for Thai. When you submit composer text on an AI chat site, it is sent to the AI service you selected as part of that site's normal operation.

### What AI Guard does with your data

This extension directly talks only to a backend running on your own machine (`http://localhost:8000` or `http://127.0.0.1:8000`), not a server operated by the extension's developer. The extension has no host permissions or code that reach another endpoint. The backend is local by default but calls AI for Thai if the user explicitly configures `AIGUARD_NER_ENGINE=tner`. The current source build does not authenticate which process owns port 8000, so use it only with a backend you started and trust. A native broker for packaged operation is an open hardening gate.

When you click "Mask PII" (on the floating bar shown on supported AI chat sites, or in the side panel), the extension reads the likely composer element (or your selection / a likely reply element for Restore) and sends that text to the backend over loopback so it can detect and mask PII before you send it to an external AI. The current v1 source build can write output after a text-based residual warning, so it is not yet an accepted fail-closed production package. Review the result before submitting it.

For in-page Mask, raw text is already typed into the AI site's provider-controlled DOM before the extension acts. Site code can observe or transmit that draft before replacement; contract v2 and a native broker cannot remove this earlier boundary. For stronger isolation, enter raw text in the side panel and paste only the reviewed masked result into the AI site.

The canonical mapping between real values and fake placeholders (the "vault") is kept **in the memory of the backend running on your machine** and is not deliberately written to disk. Current HTTP contract v1 can return fields containing, or permitting reconstruction of, token-to-original pairs in extension process memory, although the extension does not deliberately persist them. Contract v2 is intended to return no explicit mapping DTO and leave the extension with an opaque, security-sensitive `session_id`.

### What the extension stores in your browser

| Data | Stored in | Lifetime | Contains PII? |
|---|---|---|---|
| `session_id` (per-tab session reference) | `chrome.storage.session` | The extension clears it on Chrome's tab-removed event; Chrome clears session storage when the browser session ends | Not the mapping, but a bearer-like session reference that must be protected |
| Your last-selected mode (token / surrogate) | `chrome.storage.local` | Persists until you remove the extension or clear its data | No — a UI preference |
| Your selected theme (system / light / dark) | `localStorage` of the side panel page | Persists until you remove the extension or clear its data | No — a UI preference |

The extension does not deliberately persist the text you type, detected PII, or a mapping. Text and response objects can exist transiently in process memory while a request is handled; the canonical vault remains in backend memory.

### Backend audit logs

The v1 backend writes process/security audit JSONL to the source or packaged
application log directory (or stdout when hosted mode is enabled). It does not
write request text, pseudonyms, or the mapping. Current source uses a fresh
non-authorizing operation UUID for sanitize, reidentify, and roundtrip
filenames and entries, while retaining the legacy `session_id` field name.
Local tests cover disk and configured stdout, and `/api/audit-log` omits the
field. In file mode, each operation creates an operation-specific file and
those files have no timed automatic deletion; configured stdout mode creates no
file. The backend published with Desktop 2.5.0 still uses the live session ID
for sanitize/reidentify audit events; its roundtrip event used a fixed
non-session label. No package containing the current correlation change has
been accepted.

### Permissions requested, and why

- **storage** — stores the mode preference (token/surrogate) and the temporary `session_id`, per the table above.
- **clipboardWrite** — used only when you click the "Copy" button in the side panel, to copy the masked text to your clipboard. The extension never reads the clipboard.
- **sidePanel** — opens the docked side-panel workspace.
- **host_permissions** (`http://localhost:8000/*`, `http://127.0.0.1:8000/*`) — lets the extension call the backend running on your own machine across origins (not an external server).
- **content scripts** on supported AI chat sites (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai) — show the Mask/Restore bar and locate a likely composer/reply through site selectors plus generic fallbacks when the user invokes an action. If a site changes, a fallback can select another visible matching element.

### What AI Guard does not do

- No analytics, telemetry, or tracking of any kind.
- No backend call or telemetry is sent to the developer's servers; composer text you choose to submit is sent by the page to your selected AI service.
- AI Guard does not sell data or send it to the developer; text you submit is handled by the AI service you selected.
- No deliberate permanent storage of the mapping. The canonical vault is dropped when the backend stops, the session is deleted/evicted, or a later service operation observes idle expiry.

### Contact

Maintainer contact: maintainer's GitHub profile — `https://github.com/Teerapat-Vatpitak`
