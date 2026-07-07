# AI Guard UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle both product surfaces (MV3 extension + Tauri desktop app) onto one shared "Vault Door" design system — light content plane, one navy vault rail, unified tokens, self-hosted Thai font — without changing any backend, API, or detection logic.

**Architecture:** Pure hand-written CSS with CSS custom properties (design tokens), no framework, no build step. A canonical `tokens.css` is copied byte-identical into each package (`desktop/src/`, `extension/`) because the two ship separately and cannot cross-`@import`. Existing JS wiring, DOM ids, event handlers, and `fetch` calls are preserved; where a component needs new structure (segmented control, chips, drop zone, stat band, skeleton, choice cards) the render markup in the owning `screen-*.js` / `popup.js` / `content.js` changes together with its CSS. The in-page content script re-declares the same token values on its `.aiguard-*` roots and swaps them via `prefers-color-scheme` (it cannot touch the host `:root`).

**Tech Stack:** HTML/CSS/vanilla JS, Tauri v2 (desktop shell), Chrome MV3 (extension), IBM Plex Sans Thai Looped + IBM Plex Mono (self-hosted WOFF2), FastAPI backend on `127.0.0.1:8000` (unchanged).

**Design spec (source of truth):** `docs/superpowers/specs/2026-07-07-ui-redesign-aiguard-design.md`. Every token value, per-screen behavior, and microcopy string used below is defined there; consult it when a step says "per spec."

## Global Constraints

- No backend/API changes. No change to detection, redaction, anonymizer, audit, or vault logic. UI + Thai microcopy only.
- No framework, no bundler, no CDN. Fonts are self-hosted WOFF2 referenced by local `@font-face`.
- One primary (filled) button per view; everything else is hairline-secondary or ghost.
- Red (`--pii`/`--err`) is reserved for real PII and errors only — never decorative. Token mode = blue (`--token`), surrogate mode = teal (`--surrogate`).
- Thai UI copy: no em/en dash in Thai; separate clauses with a space; do not end Thai sentences with a period. Keep loanwords (Token, Surrogate, PDF, OCR) in Latin.
- Nothing below 1.5 line-height for Thai text. Buttons/inputs `padding-block: 8px` minimum so tone/vowel marks never clip.
- Ship light theme only for the desktop app and popup; the in-page bar + overlay must handle both host schemes. Dark token values exist in the sheet but are not wired to a theme switch in this pass.
- `tokens.css` in `desktop/src/` and `extension/` must stay byte-identical.
- Commit messages follow Conventional Commits (`feat(ui):`, `style(ui):`). Do NOT add a Co-Authored-By: Claude trailer (repo owner's rule).

## File map

Foundation (both packages):
- Create `desktop/src/fonts/` + `extension/fonts/` — self-hosted WOFF2 (Plex Sans Thai Looped 400/500/600, Plex Mono 400/500).
- Create `desktop/src/tokens.css` and `extension/tokens.css` — identical token sheet + `@font-face`.

Desktop (`desktop/src/`):
- Modify `index.html` — link `tokens.css`; shell markup (vault rail, screen header slot, boot).
- Rewrite `styles.css` — shell + shared component classes (buttons, cards, chips, banners, segmented control, tables, skeleton, stat band, drop zone) on tokens.
- Modify `app.js` — screen-header helper, update-toast, active-nav indicator (no logic change to routing/health).
- Modify `screen-text.js`, `screen-redact.js`, `screen-report.js`, `screen-settings.js`, `screen-audit.js` — render new markup/classes + states.

Extension (`extension/`):
- Modify `popup.html`, `popup.css`, `popup.js` — Thai UI, tokens, shared components.
- Modify `content.css`, `content.js` — host-adaptive bar + overlay + per-message chip, Thai strings.
- Modify `manifest.json` — ensure `fonts/*` are packaged / `web_accessible_resources` as needed.

## Verification model

There is no unit-test suite for CSS. Each task's "verify" step means: open the surface in a browser preview against the running backend and confirm the listed states render correctly. Keep the FastAPI backend running for all desktop/popup verification:

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m uvicorn app.server:app --port 8000
```

- **Desktop CSS iteration:** serve the static frontend and load it in the preview — `preview_start` a static server rooted at `desktop/src/` (see Task 3 for the launch.json entry), backend on 8000. Final visual check in the real Tauri shell (`cd desktop; npm run tauri dev`) once per phase, not per step.
- **Popup:** open `extension/popup.html` in the preview with the backend up.
- **In-page bar/overlay:** load `extension/` unpacked in Chrome, visit a light and a dark ChatGPT/Claude page. For fast CSS-only iteration, a local static harness page that includes `content.css` and mounts the `.aiguard-*` markup under both `color-scheme: light` and `dark` is acceptable; the real host check is the acceptance gate.
- After each task: confirm `git status` is clean post-commit and the Python test suite still collects/passes (no backend regressions): `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q` → expect 274 passed.

---

## Task 1: Self-host fonts

**Files:**
- Create: `desktop/src/fonts/` and `extension/fonts/` with WOFF2 files.
- (font-face declarations live in `tokens.css`, Task 2.)

**Steps:**

- [ ] **Step 1: Obtain WOFF2 files.** Download IBM Plex Sans Thai Looped (weights 400, 500, 600) and IBM Plex Mono (400, 500) as WOFF2 from the IBM Plex project (OFL-1.1). Source: the `@ibm/plex-sans-thai-looped` and `@ibm/plex-mono` npm packages or the IBM/plex GitHub release. Place, using these exact names:
  - `desktop/src/fonts/IBMPlexSansThaiLooped-Regular.woff2` (400)
  - `.../IBMPlexSansThaiLooped-Medium.woff2` (500)
  - `.../IBMPlexSansThaiLooped-SemiBold.woff2` (600)
  - `.../IBMPlexMono-Regular.woff2` (400)
  - `.../IBMPlexMono-Medium.woff2` (500)
  Copy the same five files into `extension/fonts/`.

- [ ] **Step 2: Record licensing.** Append the OFL notice for both families to `NOTICE` (the repo already ships Apache-2.0 + NOTICE). One line each: family name, copyright, "licensed under SIL OFL 1.1", and the upstream URL.

- [ ] **Step 3: Verify files are valid WOFF2.** Confirm each file's header magic is `wOF2`:

Run:
```bash
for f in desktop/src/fonts/*.woff2; do printf '%s ' "$f"; head -c4 "$f"; echo; done
```
Expected: each line prints the path followed by `wOF2`.

- [ ] **Step 4: Commit.**
```bash
git add desktop/src/fonts extension/fonts NOTICE
git commit -m "feat(ui): self-host IBM Plex Sans Thai Looped + Plex Mono (OFL)"
```

---

## Task 2: Canonical token sheet

**Files:**
- Create: `desktop/src/tokens.css`
- Create: `extension/tokens.css` (byte-identical copy)

**Interfaces:**
- Produces: the full `--*` custom-property vocabulary and the `--font-ui` / `--font-mono` stacks consumed by every later task.

- [ ] **Step 1: Write `desktop/src/tokens.css`.** Declare `@font-face` for the five files, then the light token set on `:root` and the dark set on `:root[data-theme="dark"]` (defined now, not switched this pass). Use the exact values from the spec §Design tokens. Skeleton:

```css
@font-face { font-family:"IBM Plex Sans Thai Looped"; font-weight:400; font-style:normal; font-display:swap; src:url("fonts/IBMPlexSansThaiLooped-Regular.woff2") format("woff2"); }
@font-face { font-family:"IBM Plex Sans Thai Looped"; font-weight:500; font-style:normal; font-display:swap; src:url("fonts/IBMPlexSansThaiLooped-Medium.woff2") format("woff2"); }
@font-face { font-family:"IBM Plex Sans Thai Looped"; font-weight:600; font-style:normal; font-display:swap; src:url("fonts/IBMPlexSansThaiLooped-SemiBold.woff2") format("woff2"); }
@font-face { font-family:"IBM Plex Mono"; font-weight:400; font-style:normal; font-display:swap; src:url("fonts/IBMPlexMono-Regular.woff2") format("woff2"); }
@font-face { font-family:"IBM Plex Mono"; font-weight:500; font-style:normal; font-display:swap; src:url("fonts/IBMPlexMono-Medium.woff2") format("woff2"); }

:root {
  --font-ui:"IBM Plex Sans Thai Looped","Leelawadee UI","Thonburi","Noto Sans Thai","Segoe UI",sans-serif;
  --font-mono:"IBM Plex Mono","IBM Plex Sans Thai Looped",Consolas,monospace;

  --bg:#F6F7F9; --surface:#FFFFFF; --surface-raised:#FFFFFF; --well:#F1F4F8;
  --ink:#15233B; --ink-muted:#5B6B85; --ink-faint:#8A97AD;
  --line:#E3E9F2; --line-strong:#C6D0DF;
  --primary:#2563EB; --primary-ink:#FFFFFF; --primary-soft:#EDF3FE;
  --ok:#15803D; --ok-soft:#E8F5EC; --warn:#B45309; --warn-soft:#FDF3E4; --err:#B91C1C; --err-soft:#FBEAEA;
  --pii:#B91C1C; --pii-soft:#FBEAEA; --redact:#0B1220;
  --token:#2563EB; --token-soft:#EDF3FE; --surrogate:#0D9488; --surrogate-soft:#E6F4F2;
  --vault-bg:#0F1D33; --vault-ink:#D5DEED; --vault-muted:#8DA0BF; --vault-active-bg:rgba(255,255,255,.07);

  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --s7:48px;
  --r-sm:6px; --r-md:10px; --r-lg:14px;
  --shadow-1:0 4px 16px rgba(21,35,59,.10); --shadow-2:0 16px 48px rgba(21,35,59,.22);
  --t-fast:120ms ease-out; --t-med:180ms cubic-bezier(.2,0,0,1); --t-slow:240ms cubic-bezier(.2,0,0,1);
}

:root[data-theme="dark"] {
  --bg:#0D1524; --surface:#131E31; --surface-raised:#18253C; --well:#0F1A2C;
  --ink:#E4EAF4; --ink-muted:#97A6BF; --ink-faint:#6B7B96;
  --line:rgba(151,166,191,.16); --line-strong:rgba(151,166,191,.32);
  --primary:#6D9BFF; --primary-ink:#0D1524; --primary-soft:rgba(109,155,255,.14);
  --ok:#3FB26F; --ok-soft:rgba(63,178,111,.14); --warn:#D98F2B; --warn-soft:rgba(217,143,43,.14); --err:#E5636B; --err-soft:rgba(229,99,107,.14);
  --pii:#F08085; --pii-soft:rgba(240,128,133,.14); --redact:#000000;
  --token:#7AA5FF; --token-soft:rgba(122,165,255,.14); --surrogate:#3FBFB2; --surrogate-soft:rgba(63,191,178,.14);
}

@media (prefers-reduced-motion: reduce) {
  :root { --t-fast:1ms; --t-med:1ms; --t-slow:1ms; }
}
```

- [ ] **Step 2: Copy to the extension.** Copy the finished file to `extension/tokens.css` verbatim (font `src` paths are relative — `fonts/...` resolves inside each package). Confirm identical:

Run:
```bash
diff desktop/src/tokens.css extension/tokens.css && echo IDENTICAL
```
Expected: `IDENTICAL`.

- [ ] **Step 3: Commit.**
```bash
git add desktop/src/tokens.css extension/tokens.css
git commit -m "feat(ui): add shared design-token sheet (Vault Door)"
```

---

## Task 3: Desktop shell — vault rail, content plane, boot, update toast

**Files:**
- Modify: `desktop/src/index.html` (link tokens.css; rail + header markup; boot)
- Modify: `desktop/src/styles.css` (replace body/base + shell rules; add shared component classes)
- Modify: `desktop/src/app.js` (active-nav 2px indicator; `renderScreenHeader(title, desc)` helper; update banner → toast)
- Create: `.claude/launch.json` entry for static preview (if not present)

**Interfaces:**
- Produces: shared classes reused by Tasks 4-8 — `.btn`/`.btn--primary`/`.btn--secondary`/`.btn--ghost`/`.btn--danger`, `.card`, `.chip`/`.chip--token`/`.chip--surrogate`/`.chip--redact`, `.banner`/`.banner--warn`/`.banner--err`/`.banner--ok`, `.seg`/`.seg__opt`, `.well`, `.stat`/`.stat__num`, `.table`, `.skeleton`, `.dropzone`, `.screen-header`. Later tasks consume these; keep the names stable.
- Produces: `renderScreenHeader(title, desc)` returning the header HTML string; `app.js` calls it at the top of each screen render.

- [ ] **Step 1: Add the static preview launch config.** Add to `.claude/launch.json` a server that serves `desktop/src` (e.g. `python -m http.server 5599 --directory desktop/src`, port 5599). This is dev-preview only, not shipped.

- [ ] **Step 2: Link tokens + set base type.** In `index.html` add `<link rel="stylesheet" href="tokens.css" />` before `styles.css`. In `styles.css` set `body { font-family:var(--font-ui); color:var(--ink); background:var(--bg); font-size:14px; line-height:1.5; }` and remove the Tailwind-gray hardcodes.

- [ ] **Step 3: Build the vault rail.** Restyle `.sidebar` to `background:var(--vault-bg); color:var(--vault-ink); width:232px`. Wordmark row (shield icon 20px + "AI Guard" Plex 600/16). `.nav-item` 14/500, `color:var(--vault-muted)`; `.nav-item.active { color:var(--vault-ink); background:var(--vault-active-bg); box-shadow: inset 2px 0 0 var(--primary); }` (replaces the solid-blue pill). Rail footer = the single trust cue: status dot + `ทำงานในเครื่อง · localhost:8000` at 12/`--vault-muted`; keep the existing `#status`/`#status-text` ids and online/offline toggle logic.

- [ ] **Step 4: Screen-header pattern + shared components.** Add `.screen-header` (title 20/600 + one 13px `--ink-muted` description line) and implement `renderScreenHeader()` in `app.js`. Write the shared component classes listed in Interfaces on tokens: hairline-first cards (`1px solid var(--line)`, no shadow), one `.btn--primary` filled style + secondary (hairline) + ghost + danger (`--err` text, hairline). Add `.well` (mono block, `--well` bg, hairline, `--r-md`, `font-family:var(--font-mono)`, `white-space:pre-wrap`). Focus ring: `outline:2px solid var(--primary); outline-offset:-1px` on inputs/buttons.

- [ ] **Step 5: Update banner → toast.** Change the `.update-banner` (full-width blue bar) to a bottom-right L1 toast: `position:fixed; right:var(--s5); bottom:var(--s5); background:var(--surface-raised); border:1px solid var(--line); box-shadow:var(--shadow-1); border-radius:var(--r-md)`, with an icon dismiss button. Keep the existing updater event wiring in `app.js` intact; only the markup/class changes.

- [ ] **Step 6: Verify shell.** Start backend (8000) + static preview (5599). Load the app. Confirm: rail is navy with the wordmark, active nav shows the 2px left indicator (click through all 5 items), rail footer shows the localhost status and flips to offline styling when the backend is stopped, boot spinner uses `--primary`, and the update toast (trigger via the updater mock/event if available, else temporarily render it) sits bottom-right. Check Thai renders in Plex (not Tahoma) via `preview_inspect` on `.brand` → `font-family` resolves to IBM Plex Sans Thai Looped.

- [ ] **Step 7: Commit.**
```bash
git add desktop/src/index.html desktop/src/styles.css desktop/src/app.js .claude/launch.json
git commit -m "feat(ui): desktop vault-rail shell + shared components"
```

---

## Task 4: Desktop — Mask/Restore screen

**Files:**
- Modify: `desktop/src/screen-text.js`
- Modify: `desktop/src/styles.css` (segmented control, token/surrogate chips, result card states)

**Interfaces:**
- Consumes: shared classes + `renderScreenHeader` from Task 3.
- Produces: `.seg`/`.seg__opt` segmented control and the pseudonym-chip render pattern reused by the popup (Task 9).

- [ ] **Step 1: Segmented mode control.** Replace the token/surrogate radios with a `.seg` two-option segmented control under the screen header (selected `.seg__opt` = `--primary` text + `--primary-soft` wash + hairline). Keep the existing mode value + the `/api/sanitize` `mode` param wiring; only the control markup changes. Settings still holds the default (Task 7).

- [ ] **Step 2: Input + one primary action.** Input `textarea` on `--surface` with hairline + focus ring. Action row: one `.btn--primary` `ปกปิดข้อมูล`; `คัดลอก` is `.btn--secondary` that morphs its label to `คัดลอกแล้ว` for 1.2s on click.

- [ ] **Step 3: Result card with pseudonym chips.** Render masked output in a `.well`, wrapping each returned entity/pseudonym in a chip span: token mode `.chip--token` (`--token-soft`/`--token`), surrogate mode `.chip--surrogate` (teal). Use the API's `entities[]` spans to wrap; the masked count becomes a 12px `--ink-faint` meta line under the card (not a paragraph).

- [ ] **Step 4: Restore section + states.** Separate restore from mask with a hairline (remove any `<hr>`). Restore textarea + `.btn--primary` `คืนค่า`. On `/api/reidentify`, if `leftover_tokens` is non-empty render a `.banner--warn` inline (not raw red). On any request error render a `.banner--err` with a retry affordance above the action row.

- [ ] **Step 5: Verify states.** With backend up, paste Thai text containing a name + phone + national ID. Confirm: token mode shows blue chips, switching to surrogate re-runs and shows teal chips; copy morphs and reverts; restore returns originals; force an error (stop backend) → `--banner--err` + retry; craft a reply with an unknown `[token_9]` → leftover warn banner. Screenshot token-mode and surrogate-mode result cards.

- [ ] **Step 6: Commit.**
```bash
git add desktop/src/screen-text.js desktop/src/styles.css
git commit -m "feat(ui): redesign Mask/Restore screen with mode segmented control + pseudonym chips"
```

---

## Task 5: Desktop — Redact PDF screen

**Files:**
- Modify: `desktop/src/screen-redact.js`
- Modify: `desktop/src/styles.css` (dropzone, processing row, before/after matte, field chips)

**Interfaces:**
- Consumes: shared classes; `.chip--redact`, `.banner--warn` from Task 3.

- [ ] **Step 1: Drop zone.** Replace the native file input with `.dropzone` (dashed `--line-strong`, `--r-md`, muted doc icon, `วางไฟล์ PDF ที่นี่ หรือคลิกเลือกไฟล์`). Support both click-to-pick and drag-drop; keep the existing multipart `pdf_file` POST to `/api/redact-pdf`.

- [ ] **Step 2: Processing row.** While awaiting the response, show a designed row: filename + small spinner + step text at 13/`--ink-muted` (`กำลังตรวจและปกปิด...`). One in-flight spinner only.

- [ ] **Step 3: Result — before/after + summary.** Render `before_png_b64` / `after_png_b64` side by side on a `.well` matte, 1px hairline, 11px overline labels `ก่อน` (with a `--pii` tick) / `หลัง` (with a `--redact` tick). Summary as a definition list: `ชนิดไฟล์` (source_type) / `PII ที่พบ` (entity_count) / `ความมั่นใจ OCR` (ocr_confidence). Render `fields[]` as small `.chip--redact` chips. If `human_review` is true, show `.banner--warn` `ควรตรวจซ้ำด้วยตนเอง (ความมั่นใจ OCR ต่ำ)`. Download is the screen's one `.btn--primary`.

- [ ] **Step 4: Verify.** POST a sample text-layer PDF (`examples/sample_document.pdf`). Confirm dropzone accepts drag + click, processing row appears, before/after previews render with the colored ticks, field chips list the redacted types, download works. If a scanned PDF path returns 503 (OCR deps absent), confirm it renders as a `.banner--err`, not a crash. Screenshot the result card.

- [ ] **Step 5: Commit.**
```bash
git add desktop/src/screen-redact.js desktop/src/styles.css
git commit -m "feat(ui): redesign Redact PDF screen (dropzone, before/after, field chips)"
```

---

## Task 6: Desktop — PDPA Report screen

**Files:**
- Modify: `desktop/src/screen-report.js`
- Modify: `desktop/src/styles.css` (stat band, grade chip, breakdown table, recommendation rows)

**Interfaces:**
- Consumes: shared `.stat`/`.stat__num`, `.table`, `.chip`, `.banner`.

- [ ] **Step 1: Stat band.** Render `overall_score` as `.stat__num` (30px tabular) + a flat grade chip colored by band (ok/warn/err tint) + `risk_label`. Put `reid` score and the high-risk-combo flag as a second stat in the same row. One restrained stat band, no bolded inline prose.

- [ ] **Step 2: Section 26 + breakdown.** `section26[]` as list rows with the category in a 12px tinted tag; semantic hits (`source:"semantic"`) get a quiet `semantic` tag in `--ink-faint` (not "(AI)"). `breakdown[]` as a `.table`: hairline rows, right-aligned tabular counts, FP/TB as 11px chips.

- [ ] **Step 3: Recommendations + empty state.** `recommendations[]` as rows with a 2px left border in the level color and the level word set in that color — no `[bracket]` labels. Before the first analysis, render a centered 13px `--ink-muted` line, not a blank div.

- [ ] **Step 4: Verify.** Analyze Thai text with a national ID + a health phrase. Confirm the stat band, grade chip color matches the band, section26 rows show tags (and a semantic tag if the ML detector is installed), breakdown table aligns numerically, recommendations show colored left borders. Confirm the pre-analysis empty state. Screenshot.

- [ ] **Step 5: Commit.**
```bash
git add desktop/src/screen-report.js desktop/src/styles.css
git commit -m "feat(ui): redesign PDPA Report screen (stat band, tags, breakdown table)"
```

---

## Task 7: Desktop — Settings screen

**Files:**
- Modify: `desktop/src/screen-settings.js`
- Modify: `desktop/src/styles.css` (choice cards, mode swatches, danger button)

**Interfaces:**
- Consumes: shared classes; teaches the mode colors once (token chip + teal swatch).

- [ ] **Step 1: Choice cards.** Replace the default-radio rows for the mode setting with choice cards: 1px hairline card per option, selected = `--primary` border + `--primary-soft` wash, 14/500 label + 13px muted one-liner. The token option shows an actual `[ชื่อ_1]` `.chip--token`; the surrogate option shows a teal swatch. Keep the persisted default-mode value + storage wiring.

- [ ] **Step 2: Danger + update card.** Restyle `ออกจากโปรแกรม` as `.btn--danger` (hairline border + `--err` text), not the loud blue it is now. Keep the update card flow: status at 13/muted, release notes in a `.well` block.

- [ ] **Step 3: Verify.** Toggle the mode choice cards (selected wash + border), confirm the persisted default survives a reload, confirm the quit button reads as quiet-danger and still triggers the existing quit command, confirm the update card renders. Screenshot.

- [ ] **Step 4: Commit.**
```bash
git add desktop/src/screen-settings.js desktop/src/styles.css
git commit -m "feat(ui): redesign Settings screen (choice cards, quiet-danger quit)"
```

---

## Task 8: Desktop — Audit Log screen

**Files:**
- Modify: `desktop/src/screen-audit.js`
- Modify: `desktop/src/styles.css` (table, skeleton rows, refresh)

**Interfaces:**
- Consumes: shared `.table`, `.skeleton`.

- [ ] **Step 1: Real table.** Sticky 12/500 `--ink-muted` header row, hairline row separators (no zebra), timestamp 12/`--ink-faint`, step in 12px mono, latency right-aligned tabular. Keep the existing audit fetch + row shape.

- [ ] **Step 2: Loading + empty + refresh.** Loading = 5 static `.skeleton` rows (no shimmer). Empty = one centered `--ink-muted` line `ยังไม่มีบันทึก`. Refresh = an icon button beside an `อัปเดตล่าสุด HH:mm` meta line. Keep the existing `ไม่มีข้อมูลส่วนบุคคล` description line (factual scope).

- [ ] **Step 3: Verify.** Load the screen: confirm skeleton on first load, table renders with aligned tabular latency, empty-state line when the log is empty, refresh updates the timestamp. Screenshot.

- [ ] **Step 4: Commit.**
```bash
git add desktop/src/screen-audit.js desktop/src/styles.css
git commit -m "feat(ui): redesign Audit Log screen (table, skeleton, empty state)"
```

- [ ] **Step 5: Phase gate — real Tauri shell.** Run `cd desktop; npm run tauri dev` once and click through all 5 screens in the actual app window (not just the static preview) to confirm fonts, rail, and layouts hold in the WebView. Fix any WebView-specific gaps, then re-commit if needed.

---

## Task 9: Extension — popup redesign + Thai localization

**Files:**
- Modify: `extension/popup.html` (link tokens.css; Thai copy; component markup)
- Modify: `extension/popup.css` (`@import "tokens.css"`; components on tokens)
- Modify: `extension/popup.js` (Thai strings; segmented control; token-chip render)

**Interfaces:**
- Consumes: the token sheet (Task 2) + the segmented-control and pseudonym-chip patterns (Task 4), reimplemented in the popup's own CSS (cannot import desktop CSS).

- [ ] **Step 1: Tokens + Thai shell.** `@import "tokens.css"` at the top of `popup.css`; set body to `var(--font-ui)`, 360px wide. Header: wordmark + the connection status as the single status element (`พร้อมใช้งาน v2.0.0` / `backend ยังไม่ทำงาน — เปิดแอป AI Guard`). Translate all popup copy to Thai; keep Token/Surrogate/PDF loanwords in Latin. The "Manual mode…" hint becomes one 12px muted line under the header.

- [ ] **Step 2: Components.** Mode radios → the same `.seg` segmented control, persisting to `chrome.storage` as today. Two labeled textareas (14/500 labels). Mask = `.btn--primary`, Copy = `.btn--secondary`, Restore = primary-when-armed. Message line under the action row in `--ok`/`--err`. Output `pre` → `.well` mono block with pseudonym chips (token/surrogate).

- [ ] **Step 3: Verify.** Open `extension/popup.html` in the preview with backend up. Confirm Thai copy throughout, status reflects backend up/down, segmented control persists across reopen, mask shows chips, copy + restore work. Confirm the font resolves to Plex via `preview_inspect`. Screenshot.

- [ ] **Step 4: Commit.**
```bash
git add extension/popup.html extension/popup.css extension/popup.js
git commit -m "feat(ui): redesign extension popup + Thai localization"
```

---

## Task 10: Extension — in-page bar + overlay (host-adaptive)

**Files:**
- Modify: `extension/content.css` (scheme-aware `.aiguard-*` tokens; bar, overlay, chip)
- Modify: `extension/content.js` (Thai strings; overlay markup if needed)
- Modify: `extension/manifest.json` (package `fonts/*` if referenced; otherwise no change — bar uses the system stack)

**Interfaces:**
- Self-contained; must not touch the host `:root`. Declares tokens on `.aiguard-bar`, `.aiguard-overlay-back`, `.aiguard-overlay`, `.aiguard-msg-chip` roots and overrides them under `@media (prefers-color-scheme: dark)`.

- [ ] **Step 1: Scheme-aware component tokens.** At the top of `content.css`, declare the needed subset of tokens **on the `.aiguard-*` component roots** (light values), then override the same properties inside `@media (prefers-color-scheme: dark)` with the dark values (surface `#18253C`, ink `#E4EAF4`, hairline `rgba(255,255,255,.12)`, primary `#6D9BFF`). Use the system Thai stack (`"Leelawadee UI","Thonburi","Noto Sans Thai",system-ui,sans-serif`) — no `@font-face` here.

- [ ] **Step 2: Bar.** Restyle `.aiguard-bar` to `--surface-raised` + hairline + `--shadow-1`, `--r-lg`, 20px logo. `Mask PII` filled primary; `Restore PII` ghost **with a visible 1px border in both schemes** (fix the light-only border). Status text 12px truncating at 180px.

- [ ] **Step 3: Overlay (fix the white-on-dark bug).** Scrim `rgba(11,18,32,.55)`; card `.aiguard-overlay` = `--surface-raised` at `--r-lg` + `--shadow-2`; title row with a 28px-hit-target close icon button; restored text in a `--well` reading block 14/22; meta line showing replaced count with leftover count in `--warn` when non-zero. Entry: 240ms fade + scale (respect reduced-motion).

- [ ] **Step 4: Per-message chip + Thai strings.** Style the per-message affordance as `.aiguard-msg-chip` (12/500, `--primary-soft` bg + `--primary` text, `--r-sm`) instead of the current button look. Move content.js status strings (e.g. `Backend offline - run run.ps1`) to Thai.

- [ ] **Step 5: Verify on real hosts.** Load `extension/` unpacked in Chrome. On a **light** ChatGPT/Claude page and a **dark** one: confirm the bar reads correctly in both, the ghost Restore button has a visible border in both, the overlay uses the dark card on the dark host (no white flashbang), the per-message chip reads as a quiet affordance, and Thai strings show. Screenshot both schemes.

- [ ] **Step 6: Commit.**
```bash
git add extension/content.css extension/content.js extension/manifest.json
git commit -m "feat(ui): host-adaptive in-page bar + overlay, Thai strings"
```

---

## Final acceptance

- [ ] All 5 desktop screens + popup + in-page bar/overlay use only token values (grep for stray hardcoded hexes in the touched files: `git grep -nE "#[0-9A-Fa-f]{6}" -- desktop/src extension | grep -v tokens.css` should return only intentional exceptions like the SVG logo).
- [ ] One filled primary button per view (visual pass).
- [ ] `tokens.css` byte-identical across packages: `diff desktop/src/tokens.css extension/tokens.css`.
- [ ] Backend suite unaffected: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q` → 274 passed.
- [ ] In-page overlay verified on both a light and a dark host page.
- [ ] `git status` clean; branch `feat/ui-redesign` holds the series.

## Self-review notes (author)

- Spec coverage: shell → T3; Mask/Restore → T4; Redact → T5; Report → T6; Settings → T7; Audit → T8; popup + Thai → T9; in-page host-adaptive + overlay bug → T10; tokens/fonts/dark-values-defined → T1-2; popup-language & light-only decisions honored in T9/T2. No spec section left unassigned.
- The dark theme is intentionally not switched on for the apps (spec out-of-scope); dark values live in tokens.css for the in-page media-query swap and future app theming.
- Fonts are a hard prerequisite (T1) for every visual task; do not reorder after T2.
