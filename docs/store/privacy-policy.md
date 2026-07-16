# AI Guard — นโยบายความเป็นส่วนตัว / Privacy Policy

_อัปเดตล่าสุด / Last updated: 2026-07-16_

ลิงก์ถาวรของหน้านี้ (สำหรับกรอกในฟอร์ม Chrome Web Store):
`https://github.com/Teerapat-Vatpitak/thai-pii-redaction/blob/main/docs/store/privacy-policy.md`

---

## ภาษาไทย

### สรุปสั้น

AI Guard ประมวลผลข้อมูลทั้งหมดในเครื่องของคุณเท่านั้น ไม่มีการส่งข้อความ ข้อมูลส่วนบุคคล หรือสถิติการใช้งานออกไปยังเซิร์ฟเวอร์ภายนอกใด ๆ ไม่มีการเก็บ analytics หรือ tracking

### AI Guard ทำอะไรกับข้อมูลของคุณ

Extension นี้คุยกับ backend บนเครื่องของคุณเองเท่านั้น (`http://localhost:8000` หรือ `http://127.0.0.1:8000`) ซึ่งเป็นโปรแกรมที่คุณรันเองบนเครื่องของคุณ ไม่ใช่เซิร์ฟเวอร์ของผู้พัฒนา extension และไม่ใช่บริการบนคลาวด์ใด ๆ Extension ไม่มี host permission หรือโค้ดที่เชื่อมต่อกับปลายทางอื่นนอกจากที่อยู่ localhost สองนี้

เมื่อคุณกดปุ่ม "Mask PII" (บนแถบลอยในหน้าเว็บแชท AI หรือใน side panel) extension จะอ่านข้อความจากช่องพิมพ์ (หรือข้อความที่คุณเลือก/คำตอบล่าสุดของ AI เมื่อกด "Restore PII") แล้วส่งข้อความนั้นไปยัง backend บนเครื่องของคุณผ่าน loopback เพื่อตรวจจับและปกปิดข้อมูลส่วนบุคคล (PII) เช่น ชื่อ เลขบัตรประชาชน เบอร์โทร อีเมล ที่อยู่ ก่อนที่คุณจะส่งข้อความนั้นต่อให้ AI ภายนอก (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai)

ตารางที่แปลงค่าจริง (เช่น ชื่อจริง เลขบัตรจริง) กลับไปกลับมากับรหัสปลอมที่ปกปิดไว้ ("vault") จะถูกเก็บไว้ใน **หน่วยความจำของ backend บนเครื่องคุณเท่านั้น** ไม่เคยถูกเขียนลงดิสก์ ไม่เคยถูกส่งออกจากเครื่อง และไม่เคยถูกส่งกลับมาที่ extension เอง extension เก็บไว้แค่ "session_id" (รหัสอ้างอิงเซสชัน ไม่ใช่ข้อมูลส่วนบุคคล) เพื่อบอก backend ว่าจะดึง mapping ของเซสชันไหนตอนกด "Restore PII"

### Extension เก็บอะไรไว้ในเบราว์เซอร์ของคุณบ้าง

| ข้อมูล | เก็บไว้ที่ | อายุ | มีข้อมูลส่วนบุคคลไหม |
|---|---|---|---|
| `session_id` (รหัสอ้างอิงเซสชันต่อแท็บ) | `chrome.storage.session` | ลบอัตโนมัติเมื่อปิดแท็บนั้น หรือปิดเบราว์เซอร์ | ไม่ เป็นรหัสสุ่มอ้างอิงเท่านั้น |
| ค่าที่เลือกไว้ล่าสุด (token / surrogate) | `chrome.storage.local` | อยู่ถาวรจนกว่าคุณจะลบ extension หรือล้างข้อมูล | ไม่ เป็นค่าตั้งค่า UI |
| ธีมที่เลือก (system / light / dark) | `localStorage` ของหน้า side panel | อยู่ถาวรจนกว่าคุณจะลบ extension หรือล้างข้อมูล | ไม่ เป็นค่าตั้งค่า UI |

extension ไม่เก็บข้อความที่คุณพิมพ์หรือ PII ที่ตรวจพบไว้ที่ใดเลยหลังจากประมวลผลเสร็จ ข้อมูลเหล่านั้นอยู่ในหน่วยความจำชั่วคราวของ backend ระหว่างเซสชันเท่านั้น

### สิทธิ์ (permissions) ที่ขอ และเหตุผล

- **storage** — เก็บค่าที่เลือก (token/surrogate) และ `session_id` ชั่วคราวตามตารางด้านบน
- **clipboardWrite** — ใช้เฉพาะตอนคุณกดปุ่ม "คัดลอก" ใน side panel เพื่อคัดลอกข้อความที่ปกปิดแล้วไปยัง clipboard ของคุณ extension ไม่มีการอ่าน clipboard
- **sidePanel** — เปิดพื้นที่ทำงาน side panel ที่ docked ข้างเบราว์เซอร์
- **host_permissions** (`http://localhost:8000/*`, `http://127.0.0.1:8000/*`) — ให้ extension เรียก backend บนเครื่องคุณเองข้าม origin ได้ (ไม่ใช่เซิร์ฟเวอร์ภายนอก)
- **content scripts** บนเว็บแชท AI ที่รองรับ (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai) — ใช้แสดงแถบ Mask/Restore บนหน้าเว็บ และอ่าน/เขียนข้อความในช่องพิมพ์เพื่อปกปิด/คืนค่า PII เท่านั้น

### สิ่งที่ AI Guard ไม่ทำ

- ไม่มี analytics, telemetry หรือ tracking ใด ๆ
- ไม่ส่งข้อมูลใด ๆ ไปยังเซิร์ฟเวอร์ของผู้พัฒนา หรือบุคคลที่สาม
- ไม่ขายหรือแบ่งปันข้อมูลผู้ใช้กับใคร
- ไม่เก็บ mapping ระหว่างข้อมูลจริงกับรหัสปลอมไว้ถาวร (อยู่ในหน่วยความจำเท่านั้น หายเมื่อ backend ปิดหรือ session หมดอายุ)

### ติดต่อ

ช่องทางติดต่อผู้ดูแลโปรเจกต์: โปรไฟล์ GitHub ของผู้ดูแล — `https://github.com/Teerapat-Vatpitak`

---

## English

### Summary

AI Guard processes everything locally on your own machine. It never sends your text, detected PII, or usage statistics to any external server. There is no analytics or tracking of any kind.

### What AI Guard does with your data

This extension only talks to a backend running on your own machine (`http://localhost:8000` or `http://127.0.0.1:8000`) — a program you run yourself, not a server operated by the extension's developer and not any cloud service. The extension has no host permissions or code that reach any endpoint other than these two localhost addresses.

When you click "Mask PII" (on the floating bar shown on supported AI chat sites, or in the side panel), the extension reads the text from the composer box (or your text selection / the AI's latest reply, when you click "Restore PII") and sends that text to the backend on your machine over loopback, so it can detect and mask personally identifiable information (PII) — such as names, national ID numbers, phone numbers, emails, addresses — before you send that text on to an external AI (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai).

The mapping between real values (e.g. a real name or ID number) and the fake placeholders used to mask them (the "vault") is kept **only in the memory of the backend running on your machine**. It is never written to disk, never leaves your machine, and is never sent back to the extension itself. The extension only keeps a `session_id` (a session reference, not personal data) so the backend knows which session's mapping to use when you click "Restore PII".

### What the extension stores in your browser

| Data | Stored in | Lifetime | Contains PII? |
|---|---|---|---|
| `session_id` (per-tab session reference) | `chrome.storage.session` | Cleared automatically when that tab or the browser closes | No — a random reference only |
| Your last-selected mode (token / surrogate) | `chrome.storage.local` | Persists until you remove the extension or clear its data | No — a UI preference |
| Your selected theme (system / light / dark) | `localStorage` of the side panel page | Persists until you remove the extension or clear its data | No — a UI preference |

The extension does not store the text you type or any detected PII anywhere after processing. That data exists only in the backend's temporary in-memory session state.

### Permissions requested, and why

- **storage** — stores the mode preference (token/surrogate) and the temporary `session_id`, per the table above.
- **clipboardWrite** — used only when you click the "Copy" button in the side panel, to copy the masked text to your clipboard. The extension never reads the clipboard.
- **sidePanel** — opens the docked side-panel workspace.
- **host_permissions** (`http://localhost:8000/*`, `http://127.0.0.1:8000/*`) — lets the extension call the backend running on your own machine across origins (not an external server).
- **content scripts** on the supported AI chat sites (ChatGPT, Claude, Gemini, Grok, Perplexity, GLM/Z.ai) — used to show the Mask/Restore bar on the page, and to read/write the composer text, solely to mask/restore PII.

### What AI Guard does not do

- No analytics, telemetry, or tracking of any kind.
- No data is sent to the developer's servers or any third party.
- No data is sold or shared with anyone.
- No permanent storage of the mapping between real data and the fake placeholders (it lives in memory only, and is gone when the backend stops or the session expires).

### Contact

Maintainer contact: maintainer's GitHub profile — `https://github.com/Teerapat-Vatpitak`
