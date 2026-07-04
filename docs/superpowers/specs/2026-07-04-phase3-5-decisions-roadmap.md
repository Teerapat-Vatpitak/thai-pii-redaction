# Phase 3-5: Decisions + Roadmap

- วันที่: 2026-07-04
- สถานะ: **Decision required for phase 3 before a detailed plan can be written.** Phases 4-5 are refined roadmap.

Phase 1 (core shell) shipped; phase 2 (tray/hotkey/audit) is planned. This doc covers phase 3 (which now needs a design decision, per research), and phases 4-5 as roadmap.

---

## Phase 3 — Apache-2.0 relicense + drop PyMuPDF (AGPL): DECISION NEEDED

### What research found (the blocker)

The design spec assumed "swap PyMuPDF -> pypdfium2 for a permissive license." Research shows this is **not a drop-in** for the redaction feature:

- **PyMuPDF today** does true redaction in ONE step: `page.add_redact_annot(rect, fill=(0,0,0))` + `page.apply_redactions()` — it both **draws the black box AND removes the underlying text** so it can't be copied/searched. (Used in `pii_redactor/redactor.py`; PyMuPDF is also used in `app/server.py` to render before/after PNG previews, and by `text_extractor.py` for word bboxes.)
- **Permissive libs** (`pypdfium2` Apache/BSD, `pikepdf` MPL, `reportlab` BSD) can easily do:
  - render pages to PNG (previews) — `pypdfium2 page.render(scale=4).to_pil()`;
  - draw black rectangles as an overlay — `reportlab` canvas + `pikepdf add_overlay`.
- **But true text removal** (so the redacted text is unrecoverable) has **no off-the-shelf equivalent**. It requires a custom `pikepdf.TokenFilter` that removes `Tj`/`TJ` text operators at the right coordinates — ~200+ lines dealing with font metrics, text matrices, multi-stream pages, ligatures. High effort, real correctness risk. Also, `pypdfium2` only gives **character-level** bboxes (no word bboxes), so `text_extractor.py`'s word-bbox path would also need rewriting.

**License reality:** bundling AGPL PyMuPDF in the **distributed app** makes the whole distributed work AGPL — "keep PyMuPDF only in redactor.py" does NOT preserve an Apache-2.0 license for the shipped app. It's all-or-nothing at distribution.

### The real fork

| Option | Redaction | License | Effort / risk | Org adoption |
|---|---|---|---|---|
| **A. Apache + permissive, VISUAL redaction default** | black box overlay; text still recoverable (downgrade) + optional true-redaction add-on (below) | Apache-2.0 core | Low-med (pypdfium2 render/extract + overlay) | Best |
| **B. Apache + permissive, TRUE redaction** | full text removal via pikepdf TokenFilter | Apache-2.0 | **High** (200+ lines, correctness risk, weeks) | Best |
| **C. Stay AGPL, keep PyMuPDF** | true redaction, unchanged | **AGPL-3.0** | ~zero | **Poor** (many orgs ban AGPL) |
| **D. Hybrid: Apache core + optional AGPL true-redaction module** | permissive visual by default; TRUE redaction if the user installs an optional `requirements-redact-true.txt` (PyMuPDF), else visual + a clear warning | Apache-2.0 core; AGPL only if user opts in | Low-med | Best (core is Apache) |

### Recommendation (to confirm)

**Option D (hybrid)** — mirrors the project's existing optional-dependency pattern (OCR, MiniLM ML): the Apache-2.0 core does rendering + extraction + **visual** redaction with pypdfium2/pikepdf/reportlab; **true** redaction is an opt-in module that uses PyMuPDF (AGPL) if `requirements-redact-true.txt` is installed, otherwise the redact endpoint returns visual redaction plus a `redaction_mode: "visual"` flag and a warning. This ships the OSS-permissive goal now, keeps true redaction available for those who accept AGPL, and defers the hard TokenFilter work — which can still be done later to make true redaction permissive (upgrading D toward B).

**But this is genuinely the user's call**, because it trades license purity vs redaction security vs effort:
- If **true redaction must always be on and permissive** → Option B (accept weeks of hard work).
- If **AGPL is acceptable for the mission** (free-for-all, but orgs that ban AGPL can't adopt) → Option C is simplest and keeps true redaction. This would **reverse the earlier Apache-2.0 choice** — legitimate now that we know the migration cost.
- If **ship-permissive-now, upgrade-later** → Option D (recommended).

### Once decided, the phase-3 plan will cover (sketch)

1. Add `pypdfium2` render + char->word bbox aggregation; migrate `text_extractor.py` word bboxes off fitz.
2. Migrate `app/server.py` before/after PNG rendering to `pypdfium2`.
3. Redaction: reportlab+pikepdf overlay (visual) [Options A/D]; + TokenFilter true removal [Option B]; or optional PyMuPDF module [Option D].
4. Add `redaction_mode` to `/api/redact-pdf` response + surface it in the desktop Redact screen.
5. LICENSE (Apache-2.0) + NOTICE + README license section; remove PyMuPDF from core requirements [A/B/D].
6. Full redaction regression tests (`tests/test_step12_redact_pdf`), incl. a "text is not recoverable" assertion for true-redaction paths.

---

## Phase 4 — Distribution (roadmap; plan when phase 3 lands)

Goal: make the app trivially installable + updatable as free OSS. Depends on phase-3 (final license) + a stable build.

- **Auto-update:** `tauri-plugin-updater` — generate a signing keypair (`tauri signer generate`), host a static `latest.json` update manifest + signed artifacts on GitHub Releases, add the updater plugin + endpoint to `tauri.conf.json`. (Signing here is Tauri's own artifact signing, separate from OS code-signing.)
- **Package managers:** a winget manifest (`microsoft/winget-pkgs` PR) and a Scoop bucket manifest, both pointing at the GitHub Releases NSIS installer.
- **Code-signing (OS):** decide among unsigned (SmartScreen warns until reputation builds — acceptable for early OSS), a self-signed cert (no SmartScreen benefit), or a paid OV/EV cert (removes the warning, costs money). Recommendation for a free OSS launch: **ship unsigned first**, document the SmartScreen "More info -> Run anyway" step, and revisit a cert if adoption warrants.
- **Release automation:** a GitHub Actions workflow that runs `build-sidecar.ps1` + `tauri build` on a Windows runner and attaches the installer + update manifest to a Release.
- **Decisions to make then:** buy a cert or not; winget + scoop or just GitHub Releases; auto-update cadence.

## Phase 5 — macOS / Linux (roadmap; furthest out)

Goal: cross-platform. Tauri is cross-platform; the friction is the **Python sidecar** (PyInstaller is per-OS).

- Build `AIGuard` sidecar for macOS + Linux via PyInstaller on each OS (CI matrix); stage as `aiguard-<target-triple>` per Tauri's externalBin convention.
- macOS specifics: the sidecar/tray/quit lifecycle needs an explicit `app_handle.exit(0)` on window close (window-close doesn't exit on macOS); notarization for distribution; tray template-icon.
- Linux specifics: tray needs an icon or menu to appear; AppImage/deb packaging via Tauri bundler; global-shortcut/clipboard behavior varies by X11/Wayland.
- Verify the sidecar process-tree kill (`taskkill` is Windows-only) — needs a per-OS kill (`kill`/`pkill` on Unix) in `sidecar.rs`.
- **Decisions to make then:** which OSes to prioritize; notarization (needs an Apple developer account); packaging formats.

---

## Summary of what's planned vs pending

- **Ready to execute:** `plans/2026-07-04-followups-sidecar-trim.md`, `plans/2026-07-04-phase2-tray-hotkey-audit.md`.
- **Blocked on one decision:** phase 3 (pick A/B/C/D above) — then a detailed plan gets written.
- **Roadmap (plan later):** phases 4-5 (depend on phase-3 license + external decisions like certs/notarization).
