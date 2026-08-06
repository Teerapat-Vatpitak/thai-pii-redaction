# AI Guard for Microsoft 365

Office Add-in task pane สำหรับ Windows Desktop ใช้ TypeScript และ Office.js จาก
codebase เดียวกันใน Word, Excel และ PowerPoint โดยเรียก FastAPI/Vault ชุดเดิม
ผ่าน HTTPS development proxy ไม่มี detection หรือ mapping implementation แยกใน
Add-in

สถานะปัจจุบัน: **In development / real-host acceptance pending**. Adapter มีครบทั้ง
สาม host แต่ release unified manifest เปิด Word เท่านั้นจนกว่า real-host acceptance
ของ Excel และ PowerPoint จะผ่าน; XML manifests ของสอง host เป็น acceptance-only
transport โครงการนี้ยังไม่ใช่ Marketplace package และยังไม่รวม production hosting.
Source ปัจจุบันใช้ HTTP contract v2 แล้ว และ automated local composition ยืนยัน
packaged backend ผ่าน health, token sanitize และ reidentify ทั้งโดยตรงและผ่าน
HTTPS development proxy โดยใช้ certificate ที่มีอยู่เดิมและ trust อยู่แล้วเท่านั้น
พร้อมตรวจว่าไฟล์ certificate ไม่เปลี่ยน การทดสอบนี้ไม่ได้รัน Office
JavaScript/host adapter, เปิด Office host, sideload manifest, ติดตั้ง package,
เรียก provider หรือพิสูจน์ release/deployment หลักฐาน real-host เดิมยังเกิดก่อน
backend ปัจจุบัน และรายการ real-host/package ที่เปิดอยู่ทั้งแปดยังไม่เปลี่ยน

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
Insert response หลังผู้ใช้กดอย่างชัดเจนแล้ว unified manifest จึงยังเปิด Word เท่านั้น;
Excel และ PowerPoint ต้องผ่าน host-functional และ unified-transport smoke ก่อนจึง
ค่อย promote เข้า release manifest

## Trust boundary

- Add-in เรียก relative `/api/*`; Vite proxy ส่งต่อไป
  `http://127.0.0.1:8000` จึงไม่เพิ่ม wildcard CORS
- task pane ปิด operation ทุกอย่างไว้จนกว่า `GET /api/health` จะผ่าน
  `X-AIGuard-Contract-Version: 2` และ strict v2 schema; operation ถัดไปส่ง
  contract assertion เดิมและตรวจ assertion ในทุก success/error response
- `AIFORTHAI_API_KEY` อยู่ที่ backend เท่านั้น
- canonical vault อยู่ใน memory ของ backend และ task pane ไม่จงใจ persist mapping
  หรือข้อความใน `localStorage`/`sessionStorage`; strict v2 projection สร้าง DTO ใหม่
  และไม่รับ `original_text`, token/original pair, replaced collection,
  leftover value หรือ field เกินใด ๆ `session_id` ยังเป็น opaque restoration
  reference ที่มีความสำคัญด้านความปลอดภัย แต่ไม่ใช่ mapping
- API success และ safe error responses ผ่าน exact recursive schema ก่อนเข้า
  controller; response ที่ผิดรูปจะกลายเป็น error ข้อความคงที่ และ body จาก
  backend/provider จะไม่ถูกแสดงเป็น error
- health v2 แยก `control_token_required` กับ `api_key_required`; Office พร้อมทำงาน
  เมื่อ control token เปิดอยู่ได้ และปิด data-plane เมื่อ API key จำเป็น เพราะ
  task pane ไม่อ่านหรือเก็บ credential
- backend source ปัจจุบันไม่คืน masked result เมื่อพบ structured FP,
  text-based TB, เลขติดกันตั้งแต่ 6 หลักจาก detector-independent scan หรือ
  missing replacement record และ HTTP roundtrip สแกนซ้ำทันทีก่อนเรียก provider
  โดยตรง จึงไม่มี residual warning-only result ให้ Apply/Copy/Insert ฝั่ง Office
  ตรวจ `safety.status == "pass"` ซ้ำและปิด Apply/Copy/Insert เมื่อ Restore หรือ
  roundtrip incomplete/unsafe หลักฐาน automated source gates และ automated
  packaged-backend/HTTPS-development-proxy transport ผ่านแล้ว; real-host rerun
  และ unified-package acceptance ทั้งแปดยังเปิดอยู่
- detector ปกติอยู่ในเครื่อง แต่ถ้า backend เลือก
  `AIGUARD_NER_ENGINE=tner` อย่างชัดเจน จะส่ง raw pre-mask chunk ไป AI for Thai
- ปิด backend หรือ task pane แล้ว session อาจหายและ Restore ไม่ได้ ระบบต้องแจ้ง
  failure และไม่เดาข้อมูลเดิม
- คำตอบ Pathumma อาจคืนค่าไม่ครบ; Office แสดง Preview/count-only warning ได้ แต่
  ปิด Copy/Insert และห้ามเติมค่าเอง

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

Automated transport preflight ที่ไม่ติดตั้งหรือเปลี่ยน certificate ใช้:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\office_v2_composition.py --require-https
```

คำสั่งนี้ใช้เฉพาะ Office development certificate มาตรฐานที่มีอยู่และ trust
อยู่แล้ว สร้าง Office bundle/packaged sidecar แล้วตรวจ v2 โดยตรงและผ่าน HTTPS
proxy. หากไม่ใส่ `--require-https` เครื่องที่ไม่มี certificate ดังกล่าวจะผ่านเฉพาะ
build/backend checks และรายงาน HTTPS เป็น `PENDING`; ผลแบบนั้นยังไม่ใช่หลักฐานว่า
HTTPS composition ผ่าน

ทดสอบ code path ของ Excel และ PowerPoint ผ่าน local add-in-only XML manifest:

```powershell
npm run start:word:local
npm run start:excel:local
npm run start:powerpoint:local
```

คำสั่ง local XML เหล่านี้มีไว้ทำ real-host functional acceptance เท่านั้น และไม่
พิสูจน์ว่า unified manifest พร้อมเผยแพร่ แต่ละ local manifest ใช้ add-in ID แยกกัน
เพื่อไม่ให้การ sideload ข้าม host ชนกัน ปิด session ด้วย `npm run stop` สำหรับ unified,
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

`validate:manifest` ตรวจว่า release manifest เปิดเฉพาะ host ที่ผ่าน promotion gate
(ปัจจุบัน Word เท่านั้น) รวมถึง unified schema 1.25, HTTPS runtime, icon assets และ version
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
