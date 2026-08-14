# AI Guard — นโยบายความเป็นส่วนตัว / Privacy Policy

_อัปเดตล่าสุด / Last updated: 2026-08-14_

ลิงก์ถาวร / Permanent URL:
`https://github.com/Teerapat-Vatpitak/thai-pii-redaction/blob/main/docs/store/privacy-policy.md`

> สถานะ / Status: source ปัจจุบันใช้ Chrome Native Messaging และ Extension ID
> `kdjmkknedgmfphpkjhjdhmjadaelgggm` ที่เจ้าของอนุมัติ แต่ Web Store item ยัง
> เป็น Draft/unpublished และ real-browser acceptance เป็นการ load แบบ unpacked
> Current source uses Chrome Native Messaging and owner-approved Extension ID
> `kdjmkknedgmfphpkjhjdhmjadaelgggm`, but the Web Store item remains
> Draft/unpublished and real-browser acceptance used an unpacked load.

## ภาษาไทย

### การประมวลผลข้อมูล

Extension ส่งคำสั่งจาก MV3 service worker ไปยัง native host ชื่อ
`th.ac.psu.aiguard.native_host` แล้วผ่าน shared broker ไปยัง backend ส่วนตัว
บนเครื่องเดียวกัน Desktop GUI ไม่จำเป็นต้องเปิดอยู่ Production manifest ไม่มี
localhost/`127.0.0.1` host permission, HTTP fallback, analytics หรือ telemetry

Installed Extension profile ใช้ detector `thainer` ในเครื่องเท่านั้น ไม่รองรับ
remote TNER, provider ที่ต้องใช้ credential, provider selection หรือ credential
store และไม่อ่าน/ส่งต่อค่า credential ของ AI for Thai หรือ provider ใด ๆ
`fake` อยู่เฉพาะใน conformance support ภายใน

เมื่อกด Mask หรือ Restore ข้อมูลที่ส่งผ่าน native adapter/broker/backend จะอยู่
ในหน่วยความจำระหว่าง operation อย่างไรก็ตาม ช่อง input/reply และผลที่แสดงจะอยู่
ในหน่วยความจำของเอกสารแผงด้านข้างที่เปิดอยู่ จนกว่าคุณจะล้างหรือแทนที่ข้อมูล
หรือปิด/โหลดแผงใหม่ AI Guard ไม่เขียนลง Chrome storage หรือดิสก์สำหรับค่าเหล่านี้
Canonical mapping ระหว่างค่าจริงกับ placeholder อยู่ในหน่วยความจำของ private
Python backend และไม่จงใจเขียนลงดิสก์ Python session ID, mapping, backend
address, backend credential และ provider credential ไม่ถูกส่งให้ Extension
JavaScript

Service worker เก็บ broker handles ในหน่วยความจำเท่านั้น โดยแยก scope ต่อ tab
และต่อ side-panel instance เมื่อ native port หลุด, service worker restart,
browser restart, tab/panel ปิด หรือ navigation เปลี่ยน origin authority เดิมจะ
ถูกยกเลิกตามขอบเขต Extension ล้าง stale/legacy session references จาก
`chrome.storage.session` และไม่ replay operation ที่มี PII การเชื่อมต่อใหม่ต้อง
เริ่มจาก Mask ที่ผู้ใช้กดใหม่ก่อน Restore

### ข้อมูลที่เก็บในเบราว์เซอร์

| ข้อมูล | ที่เก็บ | อายุ | PII |
|---|---|---|---|
| โหมด token/surrogate | `chrome.storage.local` | จนกว่าลบ Extension/ล้างข้อมูล | ไม่ใช่ |
| marker/session state รุ่นเก่าที่อาจค้าง | `chrome.storage.session` | ล้างเมื่อ worker เริ่มและเมื่อ native disconnect | ไม่ใช้เป็น restore authority |
| ธีม side panel | `localStorage` ของ panel | จนกว่าลบ Extension/ล้างข้อมูล | ไม่ใช่ |

Extension ไม่จงใจเก็บข้อความดิบ, PII, mapping, Python session ID หรือ broker
handle แบบถาวร

### ขอบเขต DOM ของหน้า provider

In-page Mask ทำงานหลังข้อความดิบถูกพิมพ์ลง DOM ที่เว็บ AI ควบคุมแล้ว โค้ดของ
เว็บอาจเห็นหรือส่ง draft ก่อน Extension แทนที่ Native Messaging ไม่แก้ขอบเขต
ก่อนหน้านี้ หากต้องการแยกข้อความดิบให้เข้มกว่า ให้พิมพ์ใน side panel และวาง
เฉพาะผล masked ที่ตรวจแล้วลงเว็บ

### Permissions

- `storage` — เก็บเฉพาะ UI preference และล้าง stale session state
- `clipboardWrite` — คัดลอก masked text หลังผู้ใช้กด Copy; ไม่อ่าน clipboard
- `sidePanel` — เปิดพื้นที่ทำงานแบบ docked
- `nativeMessaging` — เชื่อม service worker กับ native host ที่ลงทะเบียนไว้
- content-script matches แบบเจาะจง — แสดง Mask/Restore บน ChatGPT, Claude,
  Gemini, Grok, Perplexity, Z.ai, ChatGLM และ BigModel

ไม่มี production loopback `host_permissions`, broad host permission,
analytics, tracking หรือการขายข้อมูล

### Chrome Web Store Limited Use

AI Guard ยืนยันว่าการใช้ข้อมูลที่ได้รับจาก Google APIs จะเป็นไปตาม
[Chrome Web Store User Data Policy](https://developer.chrome.com/docs/webstore/program-policies/limited-use/)
รวมถึงข้อกำหนด Limited Use คำยืนยันนี้ใช้แม้ข้อมูลผู้ใช้จะประมวลผลเฉพาะบน
อุปกรณ์ของผู้ใช้ Installed Extension ใช้ข้อมูลเฉพาะเพื่อวัตถุประสงค์เดียวที่
เปิดเผยไว้ด้านบน และไม่ขาย ไม่ใช้เพื่อการโฆษณาหรือประเมินความน่าเชื่อถือทาง
เครดิต และไม่ส่งข้อมูลให้ผู้ดูแลหรือ data broker

## English

### Data processing

The Extension sends operations from its MV3 service worker to the registered
native host `th.ac.psu.aiguard.native_host`, then through the shared broker to
a private backend on the same device. The Desktop GUI does not need to be
running. The production manifest has no localhost/`127.0.0.1` host permission,
HTTP fallback, analytics, or telemetry.

The installed Extension profile uses only the local `thainer` detector. It
does not support remote TNER, credential-requiring providers, provider
selection, or a credential store, and it does not read or forward AI for Thai
or provider credential values. `fake` remains internal conformance support.

Values passing through the native adapter, broker, and backend exist in process
memory while an operation runs. Input/reply fields and displayed masked or
restored output remain in the live side-panel document memory until you clear
or replace them, or the panel is closed or reloaded. They are not written to
Chrome storage or disk by AI Guard. The canonical real-value-to-placeholder
mapping remains in the private Python backend's memory and is not deliberately
written to disk. Python session IDs, mappings, backend addresses/credentials,
and provider credentials never reach Extension JavaScript.

The service worker keeps broker handles only in memory and uses a separate
scope for every tab and side-panel instance. Native disconnect, worker or
browser restart, tab/panel close, and cross-origin navigation invalidate the
affected authority. The Extension clears stale/legacy session references from
`chrome.storage.session` and never replays a PII-bearing operation. After a
new connection, a new user-initiated Mask is required before Restore.

### Browser storage

| Data | Storage | Lifetime | PII |
|---|---|---|---|
| token/surrogate mode | `chrome.storage.local` | until removal or data clear | No |
| stale/legacy session marker state | `chrome.storage.session` | cleared at worker startup and native disconnect | Never used as restore authority |
| side-panel theme | panel `localStorage` | until removal or data clear | No |

The Extension does not deliberately persist raw text, PII, mappings, Python
session IDs, or broker handles.

### Provider-page DOM boundary

In-page Mask acts only after raw text is already in the AI site's
provider-controlled DOM. Site code may observe or transmit that draft before
replacement. Native Messaging cannot remove that earlier boundary. For
stronger raw-entry isolation, type in the side panel and paste only the
reviewed masked result into the site.

### Permissions

- `storage` — UI preference and fail-closed stale-session cleanup only
- `clipboardWrite` — copies validated masked text after a user click; never reads
- `sidePanel` — opens the docked workspace
- `nativeMessaging` — connects the service worker to the registered local host
- exact content-script matches — provide Mask/Restore controls on ChatGPT,
  Claude, Gemini, Grok, Perplexity, Z.ai, ChatGLM, and BigModel

There is no production loopback `host_permissions`, broad host permission,
analytics, tracking, or sale of user data.

### Chrome Web Store Limited Use

AI Guard affirms that its use of information received from Google APIs will
adhere to the
[Chrome Web Store User Data Policy](https://developer.chrome.com/docs/webstore/program-policies/limited-use/),
including the Limited Use requirements. This affirmation applies even when
user data is processed only on the user's device. The installed Extension uses
that data only for the single purpose disclosed above and does not sell it, use
it for advertising or creditworthiness, or transfer it to the maintainer or a
data broker.

## ติดต่อ / Contact

Maintainer: `https://github.com/Teerapat-Vatpitak`
