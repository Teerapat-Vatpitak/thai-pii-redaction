# AI Guard — Chrome Web Store Listing Copy

## Single purpose statement

AI Guard detects and masks Thai personally identifiable information (PII) in
text before the user sends it to an external AI chat service (ChatGPT,
Claude, Gemini, Grok, Perplexity, GLM/Z.ai), and restores the original values
locally once the AI's reply comes back. The extension calls a backend on the
user's machine. Detection is local by default; explicitly selected remote TNER
sends raw pre-mask chunks from that backend to AI for Thai.

The current source candidate is not accepted as a fail-closed production store
package. Its backend source now rejects structured FP, text-based TB,
detector-independent contiguous 6+ digit residuals, and missing replacement
records, but contract v1 still exposes mapping-bearing response fields and
direct fixed-port localhost operation does not authenticate server identity.
The published 2.5.0 backend and historical store/browser evidence predate the
new outbound policy. Contract v2, the native broker, and fresh package/browser
acceptance must land before this copy is used for a new package.

In-page Mask acts only after raw text has been entered into the AI site's
provider-controlled DOM, whose code can observe or transmit the draft. For the
stronger isolation boundary, users must enter raw text in the extension side
panel and paste only the reviewed masked result into the site.

## Category

Productivity → Tools (closest match in the Chrome Web Store's current
category list; use whichever equivalent "Tools" / "Developer Tools" bucket
CWS presents at submission time if the exact label has changed).

## Listing copy

### ภาษาไทย

**ชื่อ (title)**

AI Guard — ปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI

**คำอธิบายสั้น (short description, ≤132 ตัวอักษร)**

ปกปิด PII ไทยก่อนส่งแชท AI; side panel แยกข้อความดิบได้ดีกว่า Detector ในเครื่องเป็น default; remote TNER ต้องเลือกเอง

**คำอธิบายแบบละเอียด (detailed description)**

AI Guard เป็น extension ที่ช่วยตรวจและปกปิด (mask) ข้อมูลส่วนบุคคลของคนไทยก่อนที่คุณจะส่งข้อความไปให้ AI แชทภายนอกอย่าง ChatGPT, Claude, Gemini, Grok, Perplexity หรือ GLM/Z.ai จากนั้นเมื่อ AI ตอบกลับมา extension จะคืนค่าข้อมูลจริงในเครื่อง Detector ปกติทำงานใน backend บนเครื่อง; หากผู้ใช้เลือก remote TNER อย่างชัดเจน backend จะส่งข้อความดิบก่อนปกปิดเป็นช่วง ๆ ไปยัง AI for Thai

Backend source ปัจจุบันปิดกั้น structured FP, text-based TB, เลขติดกันตั้งแต่ 6 หลักที่ detector ไม่พบ และ missing replacement record แล้ว แต่ source build v1 ยังไม่ใช่ production package ที่ผ่าน acceptance เพราะ response ยังมี field ที่เกี่ยวกับ mapping และ client ยังไม่ยืนยันตัวตน process ที่ครอบครอง localhost port หลักฐาน store/browser และ backend ที่เผยแพร่ใน Desktop 2.5.0 เกิดก่อน outbound policy ใหม่นี้ ระบบ contract v2, native broker และการทดสอบ package/browser ใหม่ยังเป็น gate ที่เปิดอยู่

การกด Mask ในหน้าเว็บเริ่มหลังจากข้อความดิบอยู่ใน DOM ที่เว็บ AI ควบคุมแล้ว โค้ดเว็บอาจเห็นหรือส่ง draft ก่อน extension แทนที่ หากต้องการขอบเขตที่เข้มกว่า ต้องพิมพ์ข้อความดิบใน side panel แล้วนำเฉพาะผลที่ปกปิดและตรวจแล้วไปวางในเว็บ

วิธีใช้งาน:
1. ติดตั้ง extension แล้วรัน backend ของ AI Guard บนเครื่องคุณ (ดูวิธีที่ README ของโปรเจกต์)
2. พิมพ์ข้อความในหน้าเว็บแชท AI ที่รองรับ แล้วกดปุ่ม "Mask PII" บนแถบลอย (หรือใช้ side panel เพื่อวางข้อความเอง)
3. ส่งข้อความที่ปกปิดแล้วให้ AI ตามปกติ
4. เมื่อ AI ตอบกลับ กดปุ่ม "Restore PII" เพื่อคืนค่าข้อมูลจริงกลับมา — ทำในเครื่องคุณเท่านั้น

จุดเด่นด้านความเป็นส่วนตัว:
- detector ปกติ, masking, restoration และ canonical vault อยู่ใน backend บนเครื่อง; remote TNER เป็นตัวเลือกที่ส่ง raw chunk ไป AI for Thai
- ไม่มี analytics หรือ tracking
- canonical mapping อยู่ในหน่วยความจำและไม่จงใจเขียนลงดิสก์; contract v1 ยังส่ง mapping-bearing field เข้า memory ของ extension และต้องถูกตัดออกใน v2
- รองรับ 2 โหมด: token (เช่น `[ชื่อ_1]`) หรือ surrogate (ข้อมูลปลอมที่สมจริง อ่านลื่นไหลสำหรับ AI)

AI Guard เป็นโปรเจกต์ open source ภายใต้สัญญาอนุญาต Apache-2.0 ตรวจสอบซอร์สโค้ดทั้งหมดได้ที่ GitHub

ดูนโยบายความเป็นส่วนตัวฉบับเต็มได้ที่: `docs/store/privacy-policy.md`

### English

**Title**

AI Guard — Thai PII Protection for AI Chats

**Short description (≤132 chars)**

Masks Thai PII before AI chats; side-panel entry gives stronger isolation. Default detection is local; remote TNER is opt-in.

**Detailed description**

AI Guard is a browser extension that masks Thai personally identifiable
information (PII) — names, national ID numbers, phone numbers, emails,
addresses, dates of birth, bank account numbers — before you send text to an
external AI chat service such as ChatGPT, Claude, Gemini, Grok, Perplexity,
or GLM/Z.ai. When the AI replies, AI Guard restores the real values back into
the reply for you. The default detector runs in the local backend. If the user
explicitly selects remote TNER, the backend sends raw pre-mask chunks to AI for
Thai.

The current v1 source build is not yet an accepted fail-closed production
package. Current backend source rejects structured FP, text-based TB,
detector-independent contiguous 6+ digit residuals, and missing replacement
records. Responses still carry mapping-bearing fields, however, and fixed-port
clients do not authenticate the localhost process. The published 2.5.0 backend
and historical store/browser evidence predate the new outbound policy.
Contract v2, the native broker, and fresh package/browser acceptance remain
open.

In-page Mask acts after raw text is already in the AI site's
provider-controlled DOM, whose code can observe or transmit the draft. For the
stronger boundary, enter raw text in the side panel and paste only the reviewed
masked result into the site.

How it works:
1. Install the extension and run the AI Guard backend on your own machine
   (see the project README).
2. Type your message on a supported AI chat site and click "Mask PII" on the
   floating bar (or use the side panel to paste text manually).
3. Send the masked text to the AI as usual.
4. When the AI replies, click "Restore PII" to restore the real values —
   done entirely on your device.

Privacy highlights:
- Default detection, masking, restoration, and the canonical vault run in the
  local backend; remote TNER is an explicit option that sends raw chunks to AI
  for Thai.
- No analytics or tracking.
- The canonical real-data ↔ placeholder mapping lives in memory and is not
  deliberately written to disk. Contract v1 still places mapping-bearing
  fields in extension memory; contract v2 must remove those DTO fields.
- Two modes: token (e.g. `[Name_1]`) or surrogate (realistic fake data that
  reads naturally to the AI).

AI Guard is an open-source project under the Apache-2.0 license. The full
source code is available on GitHub.

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
