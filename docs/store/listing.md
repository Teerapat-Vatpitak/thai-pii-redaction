# AI Guard — Chrome Web Store Listing Copy

## Single purpose statement

AI Guard detects and masks Thai personally identifiable information (PII) in
text before the user sends it to an external AI chat service (ChatGPT,
Claude, Gemini, Grok, Perplexity, GLM/Z.ai), and restores the original values
locally once the AI's reply comes back. All detection, masking, and
restoration runs against a backend on the user's own machine — nothing is
sent to a third-party server.

## Category

Productivity → Tools (closest match in the Chrome Web Store's current
category list; use whichever equivalent "Tools" / "Developer Tools" bucket
CWS presents at submission time if the exact label has changed).

## Listing copy

### ภาษาไทย

**ชื่อ (title)**

AI Guard — ปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI

**คำอธิบายสั้น (short description, ≤132 ตัวอักษร)**

ปกปิดข้อมูลส่วนบุคคลไทยก่อนส่งให้แชท AI แล้วคืนค่าในเครื่องคุณ ประมวลผลทั้งหมดในเครื่อง ไม่ส่งข้อมูลออกที่อื่น

**คำอธิบายแบบละเอียด (detailed description)**

AI Guard เป็น extension ที่ช่วยปกปิด (mask) ข้อมูลส่วนบุคคลของคนไทย เช่น ชื่อ-นามสกุล เลขบัตรประชาชน เบอร์โทรศัพท์ อีเมล ที่อยู่ วันเกิด เลขบัญชีธนาคาร ก่อนที่คุณจะส่งข้อความไปให้ AI แชทภายนอกอย่าง ChatGPT, Claude, Gemini, Grok, Perplexity หรือ GLM/Z.ai จากนั้นเมื่อ AI ตอบกลับมา extension จะคืนค่าข้อมูลจริงกลับเข้าไปในคำตอบให้อัตโนมัติ โดยที่ข้อมูลจริงไม่เคยถูกส่งออกจากเครื่องของคุณเลย

วิธีใช้งาน:
1. ติดตั้ง extension แล้วรัน backend ของ AI Guard บนเครื่องคุณ (ดูวิธีที่ README ของโปรเจกต์)
2. พิมพ์ข้อความในหน้าเว็บแชท AI ที่รองรับ แล้วกดปุ่ม "Mask PII" บนแถบลอย (หรือใช้ side panel เพื่อวางข้อความเอง)
3. ส่งข้อความที่ปกปิดแล้วให้ AI ตามปกติ
4. เมื่อ AI ตอบกลับ กดปุ่ม "Restore PII" เพื่อคืนค่าข้อมูลจริงกลับมา — ทำในเครื่องคุณเท่านั้น

จุดเด่นด้านความเป็นส่วนตัว:
- ประมวลผลทั้งหมดในเครื่องของคุณ (backend แบบ localhost) ไม่มีเซิร์ฟเวอร์ภายนอก
- ไม่มี analytics หรือ tracking
- ตาราง mapping ข้อมูลจริง↔รหัสปลอมอยู่ในหน่วยความจำเท่านั้น ไม่เขียนลงดิสก์
- รองรับ 2 โหมด: token (เช่น `[ชื่อ_1]`) หรือ surrogate (ข้อมูลปลอมที่สมจริง อ่านลื่นไหลสำหรับ AI)

โปรเจกต์นี้พัฒนาโดยนักศึกษาสำหรับ PSU Future Tech Challenge 2026 (AI Innovation
for Future Society, DIIS / PSU Cybersecurity & AI & Data Privacy Day) เป็นซอฟต์แวร์ระดับต้นแบบ (prototype)

ดูนโยบายความเป็นส่วนตัวฉบับเต็มได้ที่: `docs/store/privacy-policy.md`

### English

**Title**

AI Guard — Thai PII Protection for AI Chats

**Short description (≤132 chars)**

Masks Thai PII before sending to AI chats, restores it locally from the reply. All processing stays on your device.

**Detailed description**

AI Guard is a browser extension that masks Thai personally identifiable
information (PII) — names, national ID numbers, phone numbers, emails,
addresses, dates of birth, bank account numbers — before you send text to an
external AI chat service such as ChatGPT, Claude, Gemini, Grok, Perplexity,
or GLM/Z.ai. When the AI replies, AI Guard restores the real values back into
the reply for you. The real data is never sent off your machine.

How it works:
1. Install the extension and run the AI Guard backend on your own machine
   (see the project README).
2. Type your message on a supported AI chat site and click "Mask PII" on the
   floating bar (or use the side panel to paste text manually).
3. Send the masked text to the AI as usual.
4. When the AI replies, click "Restore PII" to restore the real values —
   done entirely on your device.

Privacy highlights:
- All processing happens on your own machine (a localhost backend) — no
  external server.
- No analytics or tracking.
- The real-data ↔ placeholder mapping lives in memory only, never written
  to disk.
- Two modes: token (e.g. `[Name_1]`) or surrogate (realistic fake data that
  reads naturally to the AI).

This project was built by students for the PSU Future Tech Challenge 2026
(AI Innovation for Future Society, DIIS / PSU Cybersecurity & AI & Data
Privacy Day). It is prototype-level software.

Full privacy policy: `docs/store/privacy-policy.md`

## Screenshot checklist

Chrome Web Store requires at least 1 screenshot at 1280x800 (or 640x400);
recommend preparing 3-5 at 1280x800:

- [ ] Floating Mask/Restore bar visible on ChatGPT, with a masked message in
      the composer (blur/replace any real personal data used in the demo
      text with placeholder text before capturing).
- [ ] Same bar on Claude.ai, showing the "Restore PII" overlay after a reply.
- [ ] Side panel open, showing the mode toggle (token/surrogate), a masked
      text result with highlighted chips, and the Copy button.
- [ ] Before/after comparison: original text with PII vs. masked text
      (can be a single composed image).
- [ ] Side panel showing the backend status indicator (green "พร้อมใช้งาน").

Promo tile (440x280) — optional, checklist only, no image produced by this
task:
- [ ] 440x280 promo tile with the AI Guard logo/name and a one-line tagline,
      matching the short description above.

## Store fields quick reference

| Field | Value |
|---|---|
| Category | Productivity → Tools |
| Privacy policy URL | `https://github.com/Teerapat-Vatpitak/thai-pii-redaction/blob/main/docs/store/privacy-policy.md` |
| Support/contact | `https://github.com/Teerapat-Vatpitak` |
| Single purpose | See statement at the top of this file |
| Host permission justification | `docs/store/permissions-justification.md` |
