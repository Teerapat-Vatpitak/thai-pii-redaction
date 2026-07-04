# Follow-ups: Sidecar Trim + Clipboard Error Handling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Shrink the bundled `AIGuard.exe` sidecar from ~150MB by excluding PyTorch (pulled in transitively by `--collect-all pythainlp`), and add clipboard-write error handling to the desktop text screen (final-review minor #6).

**Architecture:** Two independent, small changes. (1) `build_exe.ps1` — replace `--collect-all pythainlp` with targeted `--collect-submodules` for only the modules the base engine uses, and exclude the torch-importing PyThaiNLP submodules. (2) `desktop/src/screen-text.js` — wrap `navigator.clipboard.writeText` in try/catch with user feedback.

**Tech Stack:** PowerShell + PyInstaller; vanilla JS.

## Global Constraints

- The base engine must keep working after the trim: regex/checksum FP, thainer-CRF NER (`NER(engine="thainer")` via `pythainlp.tag`), Thai tokenization (`pythainlp.tokenize`), corpus dictionary (`pythainlp.corpus`), PDF redaction. If NER stops detecting names after the trim, the exclude list is too aggressive — roll back the specific exclude.
- Windows. Run python via the venv: `PYTHONUTF8=1 ./.venv/Scripts/python.exe ...`.
- Do not touch `pii_redactor/` or `app/`.
- This is a follow-up to phase 1 (already on main). Work on a branch off main; finish with a PR.

---

### Task 1: Trim PyTorch from the sidecar

**Files:**
- Modify: `build_exe.ps1` (the PyInstaller invocation)

**Interfaces:**
- Produces: a smaller `dist/AIGuard.exe` that still runs the base engine offline.

**Root cause (from research):** `--collect-all pythainlp` recursively collects every PyThaiNLP submodule, including neural ones with top-level `torch` imports (`transliterate.thai2rom`, `transliterate.thaig2p`, `wangchanberta`, `spell.wanchanberta_thai_grammarly`, `ulmfit`, `chat`, `generate`, `lm`, `parse`). PyInstaller then pulls `torch` (~90MB+) into the graph even though `--exclude-module torch` is present, because the *import statements* in those submodules are analyzed. The base engine only uses `pythainlp.tokenize`, `pythainlp.tag`, `pythainlp.corpus`, `pythainlp.soundex` — none of which need torch.

- [ ] **Step 1: Record the current exe size (baseline)**

```powershell
(Get-Item dist/AIGuard.exe -ErrorAction SilentlyContinue).Length
```
Expected: ~150000000+ (or "no such file" if not built yet — build once with `./build_exe.ps1` first to get the baseline).

- [ ] **Step 2: Edit the PyInstaller invocation in `build_exe.ps1`**

Replace the single line `--collect-all pythainlp ` inside the `& $python -m PyInstaller ...` command with four targeted `--collect-submodules` lines, and add the torch-importing PyThaiNLP submodules (plus `safetensors.torch`) to the `--exclude-module` list. The full command becomes:

```powershell
& $python -m PyInstaller --noconfirm --onefile --name AIGuard `
    --python-option "X utf8=1" `
    --collect-submodules pythainlp.tokenize `
    --collect-submodules pythainlp.tag `
    --collect-submodules pythainlp.corpus `
    --collect-submodules pythainlp.soundex `
    --collect-all pycrfsuite `
    --collect-all pdfplumber `
    --collect-all pymupdf `
    --collect-submodules uvicorn `
    --hidden-import pycrfsuite `
    --exclude-module torch `
    --exclude-module sentence_transformers `
    --exclude-module transformers `
    --exclude-module paddleocr `
    --exclude-module paddlepaddle `
    --exclude-module paddle `
    --exclude-module cv2 `
    --exclude-module pythainlp.transliterate `
    --exclude-module pythainlp.wangchanberta `
    --exclude-module pythainlp.spell `
    --exclude-module pythainlp.chat `
    --exclude-module pythainlp.generate `
    --exclude-module pythainlp.lm `
    --exclude-module pythainlp.parse `
    --exclude-module pythainlp.translate `
    --exclude-module pythainlp.ulmfit `
    --exclude-module safetensors.torch `
    @dataArgs `
    launcher.py
```

Leave the `$dataArgs` block (bundling the `thai-ner-1-4.crfsuite` model) and the rest of the script unchanged.

- [ ] **Step 3: Rebuild the exe**

```powershell
$env:PYTHONUTF8='1'; ./build_exe.ps1
```
Expected: build completes, prints `Built: dist\AIGuard.exe`.

- [ ] **Step 4: Verify the size dropped**

```powershell
(Get-Item dist/AIGuard.exe).Length
```
Expected: substantially smaller than the Step 1 baseline (torch is ~90MB+; expect roughly 40-70MB). If it did not shrink, torch is still being collected — inspect `build/AIGuard/warn-AIGuard.txt` for what imports torch and add that module to `--exclude-module`.

- [ ] **Step 5: Smoke-test that NER + the API still work in the trimmed exe**

Start the trimmed exe and confirm the base engine still detects a Thai name (the risk of over-excluding is that `pythainlp.tag` NER breaks):

```powershell
Start-Process -FilePath dist/AIGuard.exe
Start-Sleep -Seconds 8
$body = @{ text = "สวัสดีครับ ผมชื่อสมชาย ใจดี เบอร์ 0812345678"; mode = "token" } | ConvertTo-Json
$r = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/sanitize -Method Post -Body $body -ContentType "application/json; charset=utf-8"
$r.entities | ForEach-Object { $_.data_type }
Get-Process AIGuard -ErrorAction SilentlyContinue | Stop-Process -Force
```
Expected: the entity `data_type` list includes `NAME` (proves thainer NER still loads) and `PHONE`. If `NAME` is missing but `PHONE` is present, NER broke — remove `--exclude-module pythainlp.tag`-adjacent excludes one at a time (most likely culprit: an exclude that `pythainlp.tag` transitively needs) and rebuild until `NAME` returns.

> Note: `Start-Sleep` here is intentional — waiting for the frozen exe (PyInstaller onefile) to unpack and start uvicorn before the health/API call. This is a build-verification script, not app code.

- [ ] **Step 6: Commit**

```powershell
git add build_exe.ps1
git commit -m "build: trim PyTorch from sidecar (targeted pythainlp submodules, exclude neural modules)"
```

---

### Task 2: Clipboard-write error handling in the text screen (review minor #6)

**Files:**
- Modify: `desktop/src/screen-text.js` (the `#t-copy` click handler)

**Interfaces:**
- Consumes: nothing new.
- Produces: the Copy button gives feedback and never fails silently.

- [ ] **Step 1: Replace the Copy handler**

In `desktop/src/screen-text.js`, find:

```javascript
  $("#t-copy").addEventListener("click", () => {
    navigator.clipboard.writeText($("#t-masked").textContent);
  });
```

Replace with:

```javascript
  $("#t-copy").addEventListener("click", async () => {
    const btn = $("#t-copy");
    try {
      await navigator.clipboard.writeText($("#t-masked").textContent);
      const prev = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = prev; }, 1200);
    } catch (e) {
      $("#t-err").textContent = "คัดลอกไม่สำเร็จ: " + e.message;
      $("#t-err").classList.remove("hidden");
    }
  });
```

- [ ] **Step 2: Verify (manual, or via preview)**

Serve `desktop/src` (`.claude/launch.json` config `aiguard-frontend`) + a running backend, Mask some text, click **Copy** → the button flashes "Copied". (No automated test — this is a UI affordance.)

- [ ] **Step 3: Commit**

```powershell
git add desktop/src/screen-text.js
git commit -m "fix(desktop): clipboard copy gives feedback and handles write errors (review #6)"
```

---

## Not in scope (noted, no task)

- **Review minor #7** (Settings "Chrome Web Store — coming soon" copy): non-code. Just do not claim a published Web Store extension in the poster/demo until it is actually published. The in-app copy already says "coming soon" and is accurate.

## Self-Review

- **Coverage:** sidecar trim (Task 1) + clipboard #6 (Task 2) + #7 noted. Matches the two follow-ups + the non-code note.
- **Placeholder scan:** none — the build_exe.ps1 command and the JS handler are complete.
- **Risk:** Task 1's excludes could over-prune and break NER; Step 5 is the guard, with an explicit rollback instruction. This is the one empirical risk and it is verified in-task.
