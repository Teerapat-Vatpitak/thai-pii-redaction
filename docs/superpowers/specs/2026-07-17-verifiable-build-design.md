# Verifiable Windows Build — Design (Horizon-2 #11)

- **วันที่** 2026-07-17
- **สถานะ** approved (brainstorm เสร็จ ผู้ใช้เคาะ design แล้ว)
- **Roadmap item** #11 "[M/สูง] [ปรับ - unsigned] Reproducible + verifiable Windows build" ใน
  `docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md`
- **Decision บริบท** stay unsigned (ไม่ซื้อ Authenticode) — ความเชื่อใจมาจากความโปร่งใส/ตรวจสอบได้
  ไม่ใช่จาก cert

## ปัญหา (สถานะก่อนทำ)

1. **ไม่มีการ pin อะไรเลยในสาย build** — `requirements*.txt` เป็น `>=` ทุกตัว ไม่มี lockfile,
   `scripts/build_sidecar.py` รัน `pip install pyinstaller` แบบไม่ล็อกเวอร์ชัน,
   GitHub Actions ทุกตัว pin แค่ mutable tag (`@v4`, `@stable`) ไม่ใช่ commit SHA
   → build วันนี้กับ build เดือนหน้าบน tag เดิม ได้ binary คนละตัวโดยไม่มีใครรู้
2. **ไม่มี SHA256SUMS บน release** — hash ของ installer คำนวณมือด้วย `certutil`
   ตาม checklist ใน `packaging/README.md` ผู้ใช้ไม่มีทาง verify ไฟล์ที่โหลดมา
3. **winget/scoop hash bump เป็นมือล้วน** — ทุก release ต้องแก้ 4 ไฟล์ manifest เอง
   (`packaging/winget/*.yaml` 3 ไฟล์ + `packaging/scoop/aiguard.json`)
   `bump_version.py` ไม่แตะไฟล์กลุ่มนี้ (ถูกต้องแล้ว เพราะ manifest ชี้เวอร์ชันที่ *ปล่อยแล้ว*
   ไม่ใช่เวอร์ชันใน repo — จึงไม่อยู่ใน `_version_targets.py`)
4. **release body เป็นข้อความ generic** — ไม่มีวิธี verify ไม่มี SmartScreen note
   (README มีแล้วที่ 2 จุด แต่ release body ไม่มี)

## Decisions ที่ล็อกแล้ว (จาก brainstorm 2026-07-17)

1. **Lock ด้วย compile + hashes** — pin เวอร์ชันแน่นอนพร้อม artifact hash ติดตั้งด้วย
   `--require-hashes` ตัว compiler ใช้ **uv** (`uv pip compile --universal --generate-hashes`)
   ไม่ใช่ pip-tools เพราะ pip-tools resolve ตาม platform ที่รัน compile — compile บน Windows
   จะตัด `uvloop` (Linux-only extra ของ `uvicorn[standard]`) หลุดจาก lock ทำให้ env ฝั่ง
   ubuntu CI เพี้ยน ส่วน uv โหมด `--universal` เก็บ environment markers ครบทุก platform
   ใน lock ไฟล์เดียว และ pip ติดตั้งไฟล์นั้นด้วย `--require-hashes` ได้ตามปกติ
2. **SHA256SUMS + GitHub artifact attestation** — ทั้งคู่ ไม่ใช่แค่ checksum
   ผู้ใช้ verify ที่มาได้ด้วย `gh attestation verify` (SLSA provenance ผ่าน Sigstore
   ผูก artifact กับ commit + workflow run)
3. **winget/scoop bump เป็น local script** — ไม่ทำ CI auto-PR คงท่าที
   "nothing submitted automatically" ของ `packaging/README.md` — คน review + submit เองเสมอ
4. **Verifiable ไม่ใช่ bit-for-bit** — ไม่พยายามทำ reproducible build แบบ byte-identical
   (PyInstaller ฝัง timestamp, NSIS compression ไม่ deterministic) claim ใน README
   ต้องตรงความจริง คือพิสูจน์ *ที่มา* ได้ผ่าน attestation + ตรวจ *ความถูกต้องของไฟล์* ได้ผ่าน
   SHA256SUMS ไม่อ้างว่า rebuild แล้วได้ byte เดิม

## Design

### 1. Lockfiles (pin ชั้น Python)

ไฟล์ใหม่ที่ root (source `.txt` เดิมคง `>=` ไว้ทั้งหมด — เส้นทาง `pip install -r requirements.txt`
ของผู้ใช้ทั่วไป/library consumer ไม่เปลี่ยน)

| ไฟล์ | compile จาก | ใครใช้ |
|---|---|---|
| `requirements.lock` | `requirements.txt` + `requirements-web.txt` | CI job `pytest` (windows + ubuntu) |
| `requirements-build.lock` | `requirements.txt` + `requirements-web.txt` + `requirements-build.txt` (ใหม่ ใส่ PyInstaller floor) | CI job `windows-exe-smoke`, `release.yml` ทั้ง 3 OS, `smoke-crossplatform.yml` |

- `requirements-build.txt` (ใหม่) — ประกาศ `pyinstaller>=6.0` เป็น source
  ของ build tooling แล้วให้ lock เป็นตัว pin เวอร์ชันแน่นอน
- `scripts/lock_deps.py` (ใหม่) — wrapper รัน `uv pip compile --universal --generate-hashes`
  ด้วย input/output ที่ถูกต้องทั้งสองไฟล์ กันจำ command ผิดตอน regenerate
  (ติดตั้ง uv ผ่าน `pip install uv` ตอนรัน — ตัว uv เองไม่ต้อง pin แน่น เพราะ output lock
  ถูก review ใน diff เสมอ และการ regenerate เป็น dev-time action ไม่ใช่ CI-time)
- `scripts/build_sidecar.py` — เปลี่ยน `pip install --quiet pyinstaller` เป็น
  `pip install --quiet --require-hashes -r requirements-build.lock`
  (idempotent — env ที่ติดตั้งครบแล้วจะผ่านเร็ว และ local dev ได้ PyInstaller
  ตัวเดียวกับ CI/release เสมอ)
- CI (`ci.yml`)
  - `pytest` (ทั้ง 2 OS) — ติดตั้งจาก `requirements.lock --require-hashes`
  - `windows-exe-smoke` — ติดตั้งจาก `requirements-build.lock --require-hashes`
    (แทน core+web เดิม แล้วปล่อยให้ `build_sidecar.py` install ซ้ำแบบ no-op)
  - `pytest-core-only` — **คงเดิม** ติดตั้งจาก `requirements.txt` เปล่าๆ **โดยตั้งใจ**
    job นี้คือ guard ของเส้นทาง install แบบผู้ใช้ทั่วไป (unpinned `>=`) — ถ้า dep ใหม่
    แตก compat กับ floor ใน `.txt` job นี้คือคนจับ
- `release.yml` + `smoke-crossplatform.yml` — ติดตั้งจาก `requirements-build.lock`
- **ไม่ lock** `requirements-ml.txt` / `requirements-ocr.txt` — ไม่เข้า exe และไม่มี CI job ไหนติดตั้ง
- **ไม่มี lock drift gate ใน CI** — `pip-compile`/`uv compile` output ไม่ deterministic
  ข้ามเวลา (เวอร์ชันใหม่โผล่บน PyPI) gate แบบ regenerate-แล้ว-diff จะพังแบบสุ่ม
  ถ้าคนเพิ่ม dep ใน `.txt` แล้วลืม regenerate lock → CI ที่ติดตั้งจาก lock จะ fail
  ตอน import ใน test เอง (ยอมรับ signal ทางอ้อมนี้) เสริมด้วย test เบาๆ ข้อ 6

### 2. SHA-pin GitHub Actions

- Pin `uses:` ทุกตัวใน `ci.yml`, `release.yml`, `smoke-crossplatform.yml` เป็น
  **full 40-char commit SHA** พร้อม comment `# vX.Y.Z` ต่อท้ายบรรทัด
  ครอบคลุม `actions/checkout`, `actions/setup-python`, `actions/setup-node`,
  `dtolnay/rust-toolchain`, `swatinem/rust-cache`, `tauri-apps/tauri-action`
  และตัวใหม่ `actions/attest-build-provenance`
- **Gotcha `dtolnay/rust-toolchain@stable`** — action ตัวนี้อ่านชื่อ toolchain จาก *ref* ที่เรียก
  (`@stable` = toolchain stable) พอ pin เป็น SHA ต้องส่ง input `toolchain: stable`
  แทนอย่างชัดเจน ไม่งั้น toolchain resolution พัง
- `.github/dependabot.yml` (ใหม่) — ecosystem `github-actions` รอบ weekly
  เปิด PR อัปเดต SHA ให้เอง (pin โดยไม่มี updater = เน่าคาที่)
  ไม่เปิด ecosystem `pip` ในรอบนี้ (ลด noise — lock regenerate มือผ่าน `lock_deps.py` พอ)

### 3. Release verifiability (`release.yml`)

Job ใหม่ `checksums-and-attest` รันหลัง matrix `build` ครบทั้ง 3 OS (`needs: build`)
บน `ubuntu-latest`

1. ดาวน์โหลด asset ทุกตัวจาก **draft** release ของ tag ปัจจุบันด้วย `gh` CLI
   (`GITHUB_TOKEN` มี `contents: write` อยู่แล้ว — hash สิ่งที่ผู้ใช้จะดาวน์โหลดจริง
   จับ corruption ระหว่าง upload ได้ด้วย) หมายเหตุ implementation — draft release
   ยังไม่มี tag ref จริง ถ้า `gh release download <tag>` resolve draft ไม่ได้
   ให้ fallback หา release id ผ่าน `gh api repos/.../releases` แล้วโหลด asset ราย id
   (เก็บรายละเอียดไว้เลือกตอน implement)
2. สร้าง `SHA256SUMS` (`sha256sum <ทุก asset> > SHA256SUMS` ชื่อไฟล์ล้วน ไม่มี path)
   แล้ว `gh release upload` กลับขึ้น release
3. เรียก `actions/attest-build-provenance` กับ asset ทุกตัว **รวม `SHA256SUMS` เอง**
   — job permissions ต้องมี `id-token: write`, `attestations: write`, `contents: write`
4. เปลี่ยน `releaseBody` ใน tauri-action จากข้อความ generic เป็น template ที่มี
   - วิธี verify checksum (`certutil -hashfile <file> SHA256` ฝั่ง Windows / `sha256sum -c` ฝั่ง unix)
   - วิธี verify ที่มา (`gh attestation verify <file> -R Teerapat-Vatpitak/thai-pii-redaction`)
   - SmartScreen note "More info → Run anyway" (unsigned โดยตั้งใจ + ลิงก์ SECURITY.md)

README เพิ่ม section **"Verify your download"** — อธิบายทั้งสองวิธี และเขียนตรงไปตรงมาว่า
สิ่งที่พิสูจน์ได้คือ (ก) ไฟล์ไม่ถูกแก้ระหว่างทาง (ข) ไฟล์ถูก build โดย GitHub Actions
จาก commit ที่ระบุ — **ไม่ใช่** bit-for-bit reproducibility

### 4. winget/scoop bump script

`scripts/update_packaging.py <tag>` (ใหม่ pure stdlib — urllib ไม่พึ่ง httpx
ให้รันได้แบบเดียวกับ `check_version.py` โดยไม่ต้อง pip install)

- default tag = `v` + เนื้อหาไฟล์ `VERSION` (override ได้ด้วย argument)
- ดาวน์โหลด `SHA256SUMS` จาก **published** release ของ tag นั้น
  (bump packaging เกิดหลัง publish เสมอ — draft ไม่เกี่ยว)
- หา entry ของ installer `AI.Guard_<version>_x64-setup.exe` แล้ว rewrite 4 ไฟล์
  - `packaging/winget/Teerapat-Vatpitak.AIGuard.yaml` — `PackageVersion`
  - `packaging/winget/Teerapat-Vatpitak.AIGuard.installer.yaml` — `PackageVersion`,
    `InstallerUrl`, `InstallerSha256`, `DisplayVersion` ใน AppsAndFeaturesEntries
  - `packaging/winget/Teerapat-Vatpitak.AIGuard.locale.en-US.yaml` — `PackageVersion`
  - `packaging/scoop/aiguard.json` — `version`, `url` (คง suffix `#/dl.7z`), `hash`
- **fail loudly, no partial writes** — parse + เตรียมเนื้อหาใหม่ครบทั้ง 4 ไฟล์ก่อน
  แล้วค่อยเขียนรวดเดียว ถ้าหา installer entry ไม่เจอ / pattern ในไฟล์ไม่ match ตามคาด
  → exit non-zero โดยไม่แตะไฟล์ใดเลย
- อัปเดต checklist "Updating for a new release" ใน `packaging/README.md`
  ให้ขั้นแรกเป็นรันสคริปต์นี้ (แทน gh download + certutil มือ) คงขั้น review/validate/submit เดิม

### 5. Error handling

- **lock ตกรุ่นจาก `.txt`** — ไม่มี gate แยก CI จะ fail เองตอน import (ดูข้อ 1)
  บวก test ระดับชื่อ package ในข้อ 6 จับเคสลืม regenerate แบบพื้นฐาน
- **`--require-hashes` เจอ hash ไม่ตรง** — pip หยุดติดตั้งทันที นี่คือ behavior ที่ต้องการ
  (supply-chain guard) แก้โดย regenerate lock ผ่าน `lock_deps.py` แล้ว review diff
- **`update_packaging.py`** — ทุก failure path (HTTP error, entry ไม่เจอ, pattern ไม่ match)
  ต้องออก non-zero พร้อมข้อความชี้สาเหตุ และไม่เขียนไฟล์ครึ่งเดียว
- **`checksums-and-attest` job พัง** — release ยังเป็น draft อยู่ (tauri-action สร้าง draft)
  คนต้อง publish มือเสมอ จึงเห็น job แดงก่อน publish ได้ ไม่มีความเสี่ยง release
  หลุดออกไปโดยไม่มี checksums

### 6. Testing

- `tests/test_update_packaging.py` (ใหม่) — unit ล้วนบน tmp copy ของ manifest จริง
  - parse `SHA256SUMS` format (ชื่อไฟล์มี space/รูปแบบ `hash  filename`)
  - rewrite ครบ 4 ไฟล์ ค่าใหม่ถูกตำแหน่ง ค่าที่ไม่เกี่ยวไม่ขยับ (byte-level นอก field ที่แก้)
  - idempotence — รันซ้ำด้วย input เดิม ไฟล์ไม่เปลี่ยน
  - failure modes — installer entry หาย / pattern ไม่ match → SystemExit non-zero
    และไฟล์ทั้ง 4 ไม่ถูกแตะ (no partial writes)
  - network layer ถูก mock — ไม่มี test ไหนยิง HTTP จริง
- `tests/test_lock_coverage.py` (ใหม่) — เบาๆ ระดับชื่อ ทุก package ใน
  `requirements.txt` + `requirements-web.txt` ต้องปรากฏใน `requirements.lock`
  (normalize ชื่อ `-`/`_`/case ตาม PEP 503) และ `pyinstaller` ต้องอยู่ใน
  `requirements-build.lock` — จับเคสลืม regenerate แบบหยาบโดยไม่ต้อง resolve จริง
- `scripts/lock_deps.py` — ถ้า factor argument-construction แยกได้จะ unit test เฉพาะส่วนนั้น
  ไม่บังคับ (สคริปต์สั้น ความเสี่ยงต่ำ)
- **สิ่งที่ทดสอบก่อน merge ไม่ได้ (ประกาศตรงๆ)** — job `checksums-and-attest` ใน
  `release.yml` รันจริงได้ครั้งแรกตอน tag release หน้าเท่านั้น (สถานะเดียวกับ mac/linux
  legs เดิมของไฟล์นี้ ซึ่ง header ไฟล์ประกาศ UNTESTED อยู่แล้ว) — ต้อง review log
  ของ run แรกก่อนเชื่อ ส่วนการแก้ CI (`ci.yml` ติดตั้งจาก lock) พิสูจน์ตัวเองบน PR แรกทันที

## สิ่งที่อยู่นอก scope (ตั้งใจตัด)

- Bit-for-bit reproducible build (decision ข้อ 4)
- Authenticode / code signing ทุกชนิด (decision "stay unsigned" ระดับ roadmap)
- CI auto-PR bump manifest (decision ข้อ 3 — local script พอ)
- Lock ของ `requirements-ml.txt` / `requirements-ocr.txt`
- Dependabot ecosystem `pip`
- PyPI publish ของ `pii_redactor` (roadmap แยก)

## ไฟล์ที่แตะ (สรุป)

| ไฟล์ | การเปลี่ยนแปลง |
|---|---|
| `requirements.lock`, `requirements-build.lock`, `requirements-build.txt` | ใหม่ |
| `scripts/lock_deps.py`, `scripts/update_packaging.py` | ใหม่ |
| `tests/test_update_packaging.py`, `tests/test_lock_coverage.py` | ใหม่ |
| `.github/dependabot.yml` | ใหม่ |
| `.github/workflows/ci.yml` | SHA-pin ทุก action + pytest/exe-smoke ติดตั้งจาก lock |
| `.github/workflows/release.yml` | SHA-pin + ติดตั้งจาก build lock + job `checksums-and-attest` + releaseBody ใหม่ |
| `.github/workflows/smoke-crossplatform.yml` | SHA-pin + ติดตั้งจาก build lock |
| `scripts/build_sidecar.py` | ติดตั้ง PyInstaller จาก `requirements-build.lock` |
| `README.md` | section "Verify your download" |
| `packaging/README.md` | checklist ชี้ `update_packaging.py` |
| `CLAUDE.md` | sync หลัง merge (ตาม workflow เดิม — controller ทำ ไม่ใช่ lane) |
