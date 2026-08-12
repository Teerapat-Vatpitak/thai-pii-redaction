# AI Guard — Chrome Web Store listing copy

> Candidate status (2026-08-12): owner-approved unpublished Item ID
> `kdjmkknedgmfphpkjhjdhmjadaelgggm` is bound to the Native Messaging
> production path. The item remains Draft/unpublished. Do not submit, publish,
> or claim Web Store installation acceptance; exact-ID browser evidence is an
> unpacked load. The deterministic test identity remains synthetic only.

## Single purpose

AI Guard detects and masks Thai personally identifiable information before
the user sends text to an external AI chat service, and restores the original
values locally from the reply. The installed Extension uses the local
`thainer` detector through the registered companion and shared broker. It has
no remote TNER, provider selection, credential-requiring provider, or
localhost fallback.

In-page Mask starts after raw text has entered provider-controlled page DOM.
Page code may observe or transmit the draft before replacement. Side-panel
entry is the stronger raw-entry boundary.

## Category

Productivity → Tools (confirm the current equivalent during an owner-approved
submission).

## ภาษาไทย

**ชื่อ**

AI Guard — ปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI

**คำอธิบายสั้น**

ปกปิด PII ไทยในเครื่องก่อนส่งแชท AI; side panel ช่วยแยกข้อความดิบ และไม่มี localhost fallback

**คำอธิบายแบบละเอียด**

AI Guard ช่วยตรวจและปกปิดข้อมูลส่วนบุคคลของคนไทยก่อนส่งข้อความให้ ChatGPT,
Claude, Gemini, Grok, Perplexity หรือ GLM/Z.ai และคืนค่าข้อมูลจริงจากคำตอบใน
เครื่องของผู้ใช้

Extension ใช้ Chrome Native Messaging ไปยัง Desktop companion ที่ลงทะเบียน
ไว้ จากนั้น shared broker จะเรียก private backend และ detector `thainer`
Desktop GUI ไม่ต้องเปิดอยู่ ไม่มี remote TNER, provider ที่ต้องใช้ credential,
analytics, tracking, localhost permission หรือ HTTP fallback Canonical mapping
อยู่ในหน่วยความจำของ backend และไม่ถูกส่งให้ Extension JavaScript

แต่การกด Mask ในหน้าเว็บเริ่มหลังข้อความดิบอยู่ใน DOM ที่เว็บ AI ควบคุมแล้ว
หากต้องการขอบเขตที่เข้มกว่า ให้พิมพ์ใน side panel แล้ววางเฉพาะผล masked ที่
ตรวจแล้วลงเว็บ

วิธีใช้:

1. ติดตั้ง Extension และ Desktop companion ที่ตรงกัน
2. กด Mask บนเว็บที่รองรับ หรือใช้ side panel
3. ตรวจและส่ง masked text ด้วยปุ่ม Send ของเว็บ
4. กด Restore เพื่อคืนค่าใน scope เดิมบนเครื่อง

## English

**Title**

AI Guard — Thai PII Protection for AI Chats

**Short description**

Masks Thai PII locally before AI chats; side-panel entry isolates raw text, with no localhost fallback.

**Detailed description**

AI Guard detects and masks Thai PII before text is sent to ChatGPT, Claude,
Gemini, Grok, Perplexity, or GLM/Z.ai, then restores the original values
locally from the reply.

The Extension uses Chrome Native Messaging to a registered Desktop companion.
The shared broker calls a private backend with the local `thainer` detector;
the Desktop GUI need not be running. There is no remote TNER, credential-
requiring provider, analytics, tracking, localhost permission, or HTTP
fallback. The canonical mapping remains in backend memory and is never sent to
Extension JavaScript.

In-page Mask starts after raw text is already in provider-controlled page DOM.
For stronger raw-entry isolation, type in the side panel and paste only the
reviewed masked result into the site.

How it works:

1. Install the matching Extension and Desktop companion.
2. Mask on a supported site or in the side panel.
3. Review and submit the masked text using the site's Send control.
4. Restore locally within the same tab or panel scope.

## Submission checklist

- [x] Record the owner-approved unpublished Item ID and public manifest key in
      `config/chrome-extension-identity.json`.
- [x] Build with classification `production_owner_approved`; synthetic builds
      are test-only and must be rejected.
- [x] Verify the native-host manifest contains exactly
      `chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/`.
- [x] Run exact-ID unpacked real-Chromium plus installed-companion acceptance.
- [ ] Run installed-Web-Store acceptance only if a supported unpublished-item
      mechanism exists or the owner separately authorizes review/submission.
- [x] Capture only synthetic PII in screenshots and evidence.
- [ ] Reconfirm category labels and listing length limits at submission time.

## Store fields

| Field | Value |
|---|---|
| Privacy policy | `https://github.com/Teerapat-Vatpitak/thai-pii-redaction/blob/main/docs/store/privacy-policy.md` |
| Support | `https://github.com/Teerapat-Vatpitak` |
| Permission justification | `docs/store/permissions-justification.md` |
