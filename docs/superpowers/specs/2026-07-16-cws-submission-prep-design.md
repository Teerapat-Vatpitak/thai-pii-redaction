# Chrome Web Store submission prep (Horizon-1 #6) — Design

- วันที่: 2026-07-16
- สถานะ: การตัดสินใจล็อคโดย controller (ชิ้นปิดท้าย Horizon 1 ตามคำสั่ง "ทำต่อตามแผนให้เสร็จ")
- ขอบเขต: เตรียม artifact ทุกอย่างที่อยู่ใน repo ได้ — การ submit จริง (บัญชี dev, ค่าธรรมเนียม, อัปโหลด) เป็น action ของ owner

## การตัดสินใจที่ล็อคแล้ว

| ประเด็น | ตัดสินใจ |
|---|---|
| i18n ระดับ manifest | เพิ่ม `extension/_locales/th/messages.json` + `extension/_locales/en/messages.json`; `manifest.json` ใช้ `default_locale: "th"` และ `__MSG_appName__`/`__MSG_appDesc__` สำหรับ `name`/`description` (UI ภายใน extension เป็นภาษาไทยอยู่แล้ว ไม่แตะ) |
| ชื่อ/คำอธิบาย | th name: `AI Guard — ปกปิดข้อมูลส่วนบุคคลก่อนส่งให้ AI` / en name: `AI Guard — Thai PII Protection for AI Chats` (CWS จำกัด name ≤45 ตัวอักษร ต้องตรวจความยาวจริงใน test); description ≤132 ตัวอักษร สื่อว่า mask ก่อนส่ง restore ในเครื่อง ประมวลผล local ทั้งหมด |
| Privacy policy | `docs/store/privacy-policy.md` สองภาษา (th ก่อน en ตาม) เนื้อหาตามจริงเท่านั้น: ประมวลผลในเครื่องทั้งหมด, extension คุยเฉพาะ backend บน localhost:8000, ไม่มี analytics/tracking/external transmission, เก็บแค่ `session_id` ใน `chrome.storage.session` (หายเมื่อปิด browser) และ mode preference ใน `chrome.storage.local`, ข้อความที่ mask ส่งไป backend ในเครื่องเท่านั้น vault ไม่เคยออกนอกเครื่อง; ระบุ contact = ช่องทางบน GitHub profile ของ maintainer; URL ที่จะกรอกใน CWS = GitHub blob URL ของไฟล์นี้ |
| Permission justification | `docs/store/permissions-justification.md` (en เพราะ reviewer ของ CWS อ่าน): `storage` (mode preference + session_id ชั่วคราว), `clipboardWrite` (ปุ่ม copy ข้อความที่ mask แล้วใน side panel), `sidePanel` (พื้นที่ทำงาน docked), host_permissions `localhost/127.0.0.1:8000` (backend ในเครื่อง — จุดขายด้าน privacy), content scripts บน 6 โดเมน AI (inject แถบ Mask/Restore) พร้อมเหตุผลว่าทำไม broad host แต่ละอันจำเป็น |
| Listing copy | `docs/store/listing.md`: title/short desc/detailed desc ทั้ง th+en, category = Productivity → Tools (หรือใกล้เคียงที่ CWS มี), screenshot checklist (1280x800 อย่างน้อย 1 ภาพ แนะนำ 3-5: แถบ mask บน ChatGPT/Claude, side panel, before/after), promo tile 440x280 optional, ลิงก์ privacy policy, single purpose statement |
| Packaging script | `scripts/package_extension.py` (stdlib เท่านั้น): zip เนื้อหา `extension/` (ยกเว้น README.md) เป็น `dist/aiguard-extension-<VERSION>.zip` โดยอ่านเลขจากไฟล์ `VERSION` และ validate ว่า manifest version ตรงกับ VERSION ก่อน zip (ไม่ตรง → exit 1 ชี้ให้รัน bump_version) |
| Tests | `tests/test_extension_locales.py` (stdlib): messages.json ทั้งสอง locale parse ได้และมี key ตรงกัน; manifest มี `default_locale` และ `name`/`description` เป็น `__MSG_*__` ที่มีใน messages; en/th name ≤45 chars, description ≤132 chars; `package_extension.py` สร้าง zip ที่มี manifest.json และไม่มี README.md (ใช้ tmp_path) |
| สิ่งที่ไม่ทำ | ไม่แก้ UI strings ใน extension, ไม่ทำ promo image จริง (checklist พอ), ไม่ submit จริง, ไม่แตะ CLAUDE.md (controller sync หลัง merge), ไม่แตะ `tests/test_step11_api.py`/`test_api_hardening.py` |

## หมายเหตุ

การเปลี่ยน `name` ใน manifest เป็น `__MSG_appName__` มีผลกับชื่อที่โชว์ใน chrome://extensions — ต้องมี `_locales` ครบไม่งั้น Chrome โหลดไม่ขึ้น test จึงต้อง validate โครงให้แน่น commit message ห้ามมี Co-Authored-By: Claude trailer เช่นเดิม
