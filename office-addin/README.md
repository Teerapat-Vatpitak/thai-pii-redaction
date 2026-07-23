# AI Guard for Microsoft 365

Office Add-in task pane สำหรับ Windows Desktop ใช้ TypeScript และ Office.js จาก
codebase เดียวกันใน Word, Excel และ PowerPoint โดยเรียก FastAPI/Vault ชุดเดิม
ผ่าน HTTPS development proxy ไม่มี detection หรือ mapping implementation แยกใน
Add-in

สถานะปัจจุบัน: **In development / real-host acceptance pending**. Adapter ของ
ทั้งสาม host มีแล้ว แต่ release manifest เปิดเฉพาะ Word ตาม promotion gate;
Excel และ PowerPoint จะถูกเพิ่มหลัง real-host acceptance ของแต่ละ host ผ่านเท่านั้น
โครงการนี้ยังไม่ใช่ Marketplace package และยังไม่รวม production hosting

การลอง unified manifest วันที่ 2026-07-23 พบว่า `validDomains` ใส่ URL แทน
host:port ทำให้ package ลงทะเบียนแต่ Word ไม่ acquire ribbon/task pane หลังแก้เป็น
`localhost:3000` แล้ว Word acquire ribbon และเปิด task pane ได้จริง ตัว validator
ของโครงการตรวจรูปแบบนี้เพื่อกัน regression แล้ว โครงการยังมี host-specific local
XML manifests สำหรับแยกการทดสอบฟังก์ชันบนเครื่อง ไฟล์เหล่านี้ไม่ใช่ release
artifact: `manifest.dev.xml` (Word), `manifest.dev.excel.xml` และ
`manifest.dev.powerpoint.xml`

การทดสอบผ่าน local XML ในวันเดียวกันยืนยัน ribbon/task pane, backend ready และ
offline-disabled states, Detect, PDPA Analyze, token Preview/Apply/Restore แบบ
รักษาช่องว่างขอบ selection, stale-selection cancellation, mixed formatting
Copy-only และ Pathumma masked-outbound preview พร้อม unused-token warning แล้ว
ตัวตรวจ Word แยก direct formatting เป็นราย text run และไม่ใช้ชื่อ font ซึ่งอาจ
ต่างกันตาม Thai/Latin script fallback; real-host follow-up ยืนยันข้อความสม่ำเสมอ,
mixed size/color/highlight Copy-only และ token/surrogate exact Restore แล้ว
Excel follow-up ยืนยันว่าเปลี่ยนเฉพาะ text cell โดยสูตรไม่เปลี่ยน และ PowerPoint
ยืนยัน selected-text Apply/Restore พร้อม mixed/no-selection fail-closed รายละเอียด
อยู่ที่
[Office local acceptance run](../docs/acceptance/2026-07-23-office-local-run.md)
Unified Word follow-up ยืนยัน multiple-paragraph Copy-only, Pathumma preview และ
Insert response หลังผู้ใช้กดอย่างชัดเจนแล้ว งานนี้ยังไม่ครอบคลุม checklist ของทุก
host และ release manifest ยังเปิด Word เท่านั้น

## Trust boundary

- Add-in เรียก relative `/api/*`; Vite proxy ส่งต่อไป
  `http://127.0.0.1:8000` จึงไม่เพิ่ม wildcard CORS
- `AIFORTHAI_API_KEY` อยู่ที่ backend เท่านั้น
- task pane เก็บเพียงข้อความที่กำลังแสดงและ `session_id` ใน memory ห้ามเก็บ
  mapping หรือข้อความใน `localStorage`/`sessionStorage`
- ปิด backend หรือ task pane แล้ว session อาจหายและ Restore ไม่ได้ ระบบต้องแจ้ง
  failure และไม่เดาข้อมูลเดิม
- คำตอบ Pathumma อาจไม่คืน token ทุกตัว; warning คือผลที่ถูกต้องและห้ามเติมค่าเอง

## Development

ต้องใช้ Node 22.12 ขึ้นไปในสาย 22 และเปิด backend ที่ port 8000 ก่อน:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

จาก terminal อีกหน้าต่าง:

```powershell
cd office-addin
npm ci
npm run dev
```

การรัน `npm run dev` จะสร้างและ trust development certificate ผ่าน
`office-addin-dev-certs` แล้วเปิด `https://localhost:3000`. จากนั้น sideload
unified manifest สำหรับ Word:

```powershell
npm run start:word
```

หาก unified manifest ไม่ถูก Office client รับ ให้ทดสอบ code path เดิมผ่าน local
add-in-only XML manifest:

```powershell
npm run start:word:local
npm run start:excel:local
npm run start:powerpoint:local
```

คำสั่งเหล่านี้มีไว้ทำ real-host functional acceptance เท่านั้น และไม่พิสูจน์ว่า
unified manifest พร้อมเผยแพร่ แต่ละ local manifest ใช้ add-in ID แยกกันเพื่อไม่ให้
การ sideload ข้าม host ชนกัน ปิด session ด้วย `npm run stop` สำหรับ unified,
`npm run stop:local` สำหรับ Word, `npm run stop:excel:local` หรือ
`npm run stop:powerpoint:local` ตาม host เครื่องทดสอบต้องใช้ Office build ที่
รองรับ unified manifest; baseline ของโครงการคือ `16.0.20131.20154`.

## Host behavior

- Word: selection ต้องไม่ว่าง เป็นหนึ่งย่อหน้า ไม่อยู่ในตาราง และ formatting
  สม่ำเสมอ จึง Apply ได้; ตัวตรวจแยก direct bold/italic/underline, size, color,
  highlight, strike-through และ subscript/superscript เป็นราย text run โดยไม่ใช้
  ชื่อ font เพื่อไม่ให้ Thai/Latin font fallback ถูกนับเป็น mixed และ selection
  เกิน 500 ตัวอักษรเป็น Preview/Copy เท่านั้น กรณีอื่น Preview/Copy เท่านั้น คำตอบ
  Pathumma แทรกหลัง selection ได้เมื่อผู้ใช้กด Insert response เท่านั้น
- Excel: ทำงานกับ selected range; เปลี่ยนเฉพาะ text cells และข้ามสูตร ตัวเลข
  วันที่ และช่องว่าง ก่อน Apply จะตรวจ address, values และ formulas ซ้ำ Ask AI
  เป็น Preview/Copy เท่านั้น
- PowerPoint: ทำงานกับ selected text range ผ่าน PowerPoint API 1.5 และปิด
  writeback เมื่อ API/formatting ไม่รองรับ ไม่แตะ notes, รูป หรือ shape อื่น Ask AI
  เป็น Preview/Copy เท่านั้น

ทุก host ทิ้งผล API ที่มาถึงช้าหาก selection เปลี่ยน และ adapter ตรวจ selection
ซ้ำก่อนเขียนกลับอีกชั้นหนึ่ง

## Verification

```powershell
npm run typecheck
npm test
npm run validate:manifest
npm run validate:manifest:upstream
npm run validate:manifest:local
npm run package:manifest
npm run build
```

`validate:manifest` ตรวจว่า release manifest ยังเปิดเฉพาะ host ที่ผ่าน promotion
gate รวมถึง unified schema 1.25, HTTPS runtime, icon assets และ version
consistency แบบ deterministic. `validate:manifest:upstream` ดึง schema 1.25
จาก Microsoft โดยตรง ตรวจ SHA-256 ที่ review แล้ว และตรวจ JSON ด้วย JSON Schema
validator; ใช้แทน CLI รุ่นที่แปลง unified ribbon fields ผิดรูปแบบ. คำสั่งนี้ต้องใช้
network และเป็น authoritative schema check ของ release transport.
`validate:manifest:local` ตรวจ XML acceptance transport ของ Word, Excel และ
PowerPoint ด้วย Microsoft validator แต่การผ่าน schema ของ XML ห้ามนำไปแทน
real-host acceptance หรือ unified-manifest promotion gate. `package:manifest`
สร้าง `out/office-addin/aiguard-office-addin-<version>.zip` แล้วตรวจว่า archive มี
`manifest.json` ที่ root และ icon outline/color ตามที่ manifest ระบุ โดย byte
ตรงกับ source. ZIP นี้เป็น app-package transport; ยังไม่ใช่หลักฐาน real-host
acceptance หรือการ promote Excel/PowerPoint.

Real-host acceptance อยู่ใน
[docs/acceptance/README.md](../docs/acceptance/README.md#office-add-in-checklist).
