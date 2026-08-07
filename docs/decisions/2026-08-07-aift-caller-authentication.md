# การยืนยันผู้เรียกสำหรับ AI for Thai

- วันที่: 2026-08-07
- สถานะ: ยอมรับแล้วโดยเจ้าของโครงการ
- ขอบเขต: deployment port `aiguard-aift` เท่านั้น ไม่เปลี่ยน API ของผลิตภัณฑ์
  local-first ใน repository หลัก

## บริบท

Participant Guide กำหนด reverse proxy, route prefix, port, CI, resource,
secret และ log shape แต่ไม่ได้กำหนด caller authentication เดิม nginx ของ
deployment port ใส่ `X-AIGuard-Key` ให้ทุกคำขอ จึงยืนยันได้เพียงว่า nginx
เรียก core ที่ถูกต้อง ไม่ได้ยืนยันตัวผู้ใช้จากอินเทอร์เน็ต

การเปิด business API แบบ anonymous ทำให้บุคคลทั่วไปใช้โควตา LLM และงาน OCR/PDF
ราคาแพงได้ Rate limit ลดโหลดได้แต่ไม่ใช่ identity boundary ขณะที่การส่ง
`AIGUARD_API_KEY` หรือ provider key ไปที่ JavaScript จะทำให้ secret สาธารณะ

## การตัดสินใจ

1. หน้า static `/` และ health endpoint เป็น public ส่วน `detect`, `guard`,
   `roundtrip`, `redact-pdf` และ `analyze-report` ทุก alias ต้องผ่าน
   caller-auth ก่อนถึง shared FastAPI core
2. ผู้ใช้ส่ง access code ครั้งเดียวที่ same-origin login endpoint ระบบเทียบ
   code แบบ constant-time แล้วแลกเป็น cookie `__Host-aift_session`
3. Cookie เป็น token แบบ stateless มี nonce สุ่มและเวลาหมดอายุ 30 นาที ลงนาม
   HMAC-SHA256 ด้วย signing key แยกต่างหาก และผูกกับ access code ปัจจุบัน
   การเปลี่ยน access code หรือ signing key จึงยกเลิก cookie เดิมทั้งหมด
4. Cookie ใช้ `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/` และไม่มี
   `Domain` JavaScript ไม่อ่านหรือเก็บ access code/cookie ใน
   `localStorage` หรือ `sessionStorage`
5. Browser request ที่ระบุ cross-site context ถูกปฏิเสธ และ `Origin` ที่มีมา
   ต้องตรง allowlist แบบ exact match API client ที่ไม่ใช่ browser ใช้ cookie
   jar หลัง login ได้โดยไม่ต้องส่ง `Origin`
6. Login มี rate limit แยก Logout ล้าง cookie ฝั่ง browser และไม่สร้าง
   server-side session การถอนสิทธิ์ราย cookie ไม่อยู่ในขอบเขตนี้; หากต้องตัด
   สิทธิ์ทันทีให้ rotate access code หรือ signing key
7. Secret ทั้งสี่หน้าที่ต้องแยกกัน:
   - `APP_AIFT_ACCESS_CODE` ยืนยันผู้เรียก
   - `APP_AIFT_COOKIE_SIGNING_KEY` ลงนาม cookie
   - `APP_AIGUARD_API_KEY` ยืนยัน deployment proxy ต่อ core
   - `APP_TOKENMIND_API_KEY` ยืนยัน core ต่อ provider

   ก่อน deploy ต้องตั้งทั้งหมดเป็น Protected + Masked GitLab CI variables
   และส่งผ่านไฟล์ environment ชั่วคราวแบบ mode 600 ที่ deploy job ลบเมื่อจบ
   ไม่มีค่าใดอยู่ใน frontend bundle, repository, log, error หรือ acceptance
   artifact
8. Auth failure ใช้ status/code คงที่และไม่ echo credential, cookie, request
   body หรือ exception detail Response ทุกทางเป็น `no-store`
9. Auth เป็น deployment wrapper บาง ๆ รอบ shared FastAPI app ไม่ fork
   detection, mapping, provider, PDF หรือ restoration logic Response ของ
   business route ใช้ projection ที่ลดข้อมูลของ HTTP v2 และไม่คืน mapping
   DTO หรือ token-bearing entity projection

## ผลที่ตามมา

- Shared access code เป็น admission gate ไม่ใช่บัญชีผู้ใช้ และไม่มี
  per-user identity/audit claim
- Cookie อายุสั้นลดช่วงเวลาของ credential ที่ถูกขโมย แต่ไม่แทน TLS,
  platform access control, rate limit หรือ provider quota
- Local HTTP test ต้องส่ง cookie header ที่ได้จาก login เอง เพราะ cookie
  `Secure` จะถูก browser ส่งอัตโนมัติเฉพาะ HTTPS; official browser acceptance
  ต้องรันผ่าน hostname ของแพลตฟอร์ม
- การเพิ่ม account, SSO, per-user quota หรือ persistent revocation store
  เป็น decision ใหม่ ไม่แอบเพิ่มใน port นี้
- GitLab creation, first push และ deployment ยังคง owner-gated แยกจาก ADR นี้

## ทางเลือกที่ไม่เลือก

- **Anonymous + rate limit** — ไม่ยืนยันผู้เรียกและยังเปิดโควตา LLM/OCR
- **ฝัง API key ในหน้าเว็บ** — ผู้ใช้ทุกคนอ่าน secret ได้
- **ให้ browser ส่ง internal core key** — รวม trust boundary สองชั้นและทำให้
  rotate/backend isolation ยากขึ้น
- **สร้างระบบ account/database ตอนนี้** — เพิ่ม retention และ operational
  surface เกินความต้องการของ participant deployment

## หลักฐานที่ต้องผ่านก่อน deploy

- login สำเร็จ/ล้มเหลว, cookie flags, tamper, expiry, logout และ secret rotation
- unauthenticated/invalid/cross-site business request ไม่ถึง core
- public health ยังทำงาน และ exact nginx allowlist ยังปิด route ภายใน
- frontend ไม่เก็บ credential และจัดการ 401 โดยล้างสถานะในหน่วยความจำ
- web/api/core runtime log ไม่มี synthetic honeytoken, cookie หรือ query value
- live Tokenmind roundtrip ใช้ข้อมูลสังเคราะห์ ผ่าน outbound residual guard
  และ response ไม่มี mapping/reconstructable token projection
