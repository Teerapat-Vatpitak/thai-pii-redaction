# AI Guard UI Redesign — Design Spec

> 2026-07-07. Full visual redesign of both product surfaces (MV3 browser extension + Tauri desktop app) onto one shared design system. Hand-written CSS with design tokens, self-hosted fonts, no framework, no build step. Backend and API contracts are untouched.

## Decisions locked (with the user, 2026-07-07)

- **Direction: "Vault Door" (hybrid).** Light content plane everywhere the user reads/edits; one dark anchor — the desktop sidebar becomes a deep brand-navy "vault rail" that carries the security identity once. The injected in-page bar/overlay adapt to the host page (ChatGPT/Claude) light/dark scheme.
- **Font: IBM Plex Sans Thai Looped** (OFL, self-hosted WOFF2, weights 400/500/600).
- **Popup language: switch English → Thai** (product, users, judges are Thai; OSS README stays English).
- **Dark mode: ship light-only for the desktop app and popup now**; dark token values are defined in the sheet so a later theme is a `[data-theme="dark"]` block, not a redesign. The in-page bar + overlay MUST handle both host schemes from day one (the current white overlay on a dark ChatGPT is a bug, not a missing feature).
- **Scope: full redesign — layout + tone**, both surfaces, unified tokens.
- **Workflow: spec first, then hand-code CSS, verify live in browser preview.** No design-image AI.

## Goal / non-goals

Goal: the extension and desktop app read as one maintained, premium, Thai-first security product — Linear/Arc/1Password register, "design for people, not AI," a trust cue stated once, not on every element.

Non-goals: no backend/API changes; no new screens or features; no framework/bundler introduction; no dark theme for the apps in this pass; no change to detection/redaction logic or copy semantics beyond UI microcopy and Thai localization of the popup.

## Design tokens

Single source of truth: `--*` CSS custom properties. Declared once and reused across desktop (`desktop/src/`) and extension (`extension/`). For the in-page content script, tokens are declared **on the component roots** (`.aiguard-*`), not `:root`, to avoid touching the host page, and swapped via `prefers-color-scheme`.

### Color

| Role | Token | Light | Dark (defined, shipped later) |
|---|---|---|---|
| App background | `--bg` | `#F6F7F9` | `#0D1524` |
| Surface (cards, panels) | `--surface` | `#FFFFFF` | `#131E31` |
| Raised surface (bar, toast, modal) | `--surface-raised` | `#FFFFFF` + shadow-1 | `#18253C` |
| Inset well (mono output, code) | `--well` | `#F1F4F8` | `#0F1A2C` |
| Ink | `--ink` | `#15233B` | `#E4EAF4` |
| Muted ink | `--ink-muted` | `#5B6B85` | `#97A6BF` |
| Faint ink (meta, timestamps) | `--ink-faint` | `#8A97AD` | `#6B7B96` |
| Hairline | `--line` | `#E3E9F2` | `rgba(151,166,191,.16)` |
| Strong line (inputs, focus base) | `--line-strong` | `#C6D0DF` | `rgba(151,166,191,.32)` |
| Primary | `--primary` | `#2563EB` | `#6D9BFF` |
| Primary ink | `--primary-ink` | `#FFFFFF` | `#0D1524` |
| Primary tint (hover, selected) | `--primary-soft` | `#EDF3FE` | `rgba(109,155,255,.14)` |
| OK | `--ok` / `--ok-soft` | `#15803D` / `#E8F5EC` | `#3FB26F` / `rgba(63,178,111,.14)` |
| Warn | `--warn` / `--warn-soft` | `#B45309` / `#FDF3E4` | `#D98F2B` / `rgba(217,143,43,.14)` |
| Error | `--err` / `--err-soft` | `#B91C1C` / `#FBEAEA` | `#E5636B` / `rgba(229,99,107,.14)` |

Semantic security roles (identical on all surfaces and consistent with the print brand):

| Role | Token | Light | Dark |
|---|---|---|---|
| Real PII / "before" state | `--pii` / `--pii-soft` | `#B91C1C` / `#FBEAEA` | `#F08085` / `rgba(240,128,133,.14)` |
| Redaction black (the box) | `--redact` | `#0B1220` | `#000000` + 1px `--line` edge |
| Token mode `[ชื่อ_1]` | `--token` / `--token-soft` | `#2563EB` / `#EDF3FE` | `#7AA5FF` / `rgba(122,165,255,.14)` |
| Surrogate mode | `--surrogate` / `--surrogate-soft` | `#0D9488` / `#E6F4F2` | `#3FBFB2` / `rgba(63,191,178,.14)` |

Vault rail (desktop sidebar; same in both schemes — already dark):
`--vault-bg: #0F1D33`, `--vault-ink: #D5DEED`, `--vault-muted: #8DA0BF`, `--vault-active-bg: rgba(255,255,255,.07)`, active indicator = 2px inset bar in `--primary`.

Color rules:
- Token mode is blue (mechanical, visibly masked); surrogate is teal (plausible fake — deliberately not blue, so the user always knows which mode produced an output).
- Red is reserved for real PII and errors only. Never decorative.
- Grades/badges are flat tinted chips (`*-soft` background + solid text). No gradients anywhere.

### Typography

Primary: `"IBM Plex Sans Thai Looped"`, self-hosted WOFF2 in `desktop/src/fonts/` and `extension/fonts/`, weights 400/500/600. Looped Thai keeps ผ/พ, บ/ป, ค/ด unambiguous at 13–14px; ships a matched Latin for mixed strings; has real tabular figures for scores/counts/tables.

```css
--font-ui:   "IBM Plex Sans Thai Looped", "Leelawadee UI", "Thonburi",
             "Noto Sans Thai", "Segoe UI", sans-serif;
--font-mono: "IBM Plex Mono", "IBM Plex Sans Thai Looped", Consolas, monospace;
```

The mono stack falls back to the Thai face because tokens like `[ชื่อ_1]` contain Thai. **Exception:** the injected in-page bar/overlay uses the system stack (`"Leelawadee UI", "Thonburi", "Noto Sans Thai", system-ui, sans-serif`) — no `@font-face` injection into host pages (weight + CSP/FOUT risk for ~10 words of UI).

Type scale (Thai needs air for tone/vowel marks — nothing below 1.5 line-height; no letter-spacing tricks; no uppercase-for-hierarchy since Thai has no case; hierarchy = size, weight, color only):

| Step | Size/line | Weight | Use |
|---|---|---|---|
| Caption | 12/18 | 400 | timestamps, table meta, overlay meta |
| Small | 13/20 | 400–500 | status text, secondary buttons, table cells |
| Body | 14/22 | 400 | default; inputs, paragraphs |
| Label | 14/22 | 500 | buttons, form labels, nav items |
| Title | 16/26 | 600 | card/section titles |
| Screen | 20/30 | 600 | screen headers |
| Stat | 30/38 | 600, tabular | the one big number per screen (PDPA score) |

Buttons/inputs use `padding-block: 8px` minimum so ไ/ใ/โ ascenders and stacked tone marks never clip. Numeric tables/scores use `font-variant-numeric: tabular-nums`.

### Spacing / radii / elevation / motion

- **Spacing** (4px base): `--s1..--s7` = 4, 8, 12, 16, 24, 32, 48. Content column max-width 720px on text-heavy screens (Mask/Restore, Report input); Redact and Audit may go wider.
- **Radii**: `--r-sm: 6px` (chips, small controls), `--r-md: 10px` (buttons, inputs, cards), `--r-lg: 14px` (modal, floating bar). No full pills except the 8px status dot.
- **Elevation** (hairline-first): L0 cards = `1px solid var(--line)`, no shadow. L1 (floating bar, toast) = `0 4px 16px rgba(21,35,59,.10)`. L2 (overlay modal) = `0 16px 48px rgba(21,35,59,.22)`. Never colored shadows or glows.
- **Motion**: `--t-fast: 120ms ease-out` (hover/press, focus ring); `--t-med: 180ms cubic-bezier(.2,0,0,1)` (result-card reveal = opacity + 4px translate, banner entry); `--t-slow: 240ms` same easing (overlay scrim fade + card scale .98→1). Allowed: those, the boot spinner, one in-flight spinner per async action. Not allowed: screen-switch transitions (tab change instant), pulsing status dots, skeleton shimmer (static skeletons only), any looping/decorative animation. `prefers-reduced-motion: reduce` → transforms off, opacity-only, durations 1ms.

## Per-surface application

### Desktop app (`desktop/src/`)

**Shell (`index.html`, `styles.css`, `app.js`).** Sidebar → vault rail (`--vault-bg`, 232px): wordmark top (Plex 600, 16px, shield icon 20px); five nav items 14/500 with quiet 16px stroke icons; active = `--vault-active-bg` fill + 2px left `--primary` bar (replaces the solid-blue active pill). Rail footer is the product's single trust cue: status dot + "ทำงานในเครื่อง · localhost:8000" at 12/`--vault-muted`. Content plane on `--bg` with a consistent screen-header pattern (Screen title 20/600 + one 13px muted description line), replacing the ad-hoc `h2 + p`. Update banner: drop the full-width blue bar for an L1 toast bottom-right of the content plane (`--surface-raised` + hairline, icon dismiss). Boot screen: `--bg`, brand mark above the spinner (spinner `--primary`), existing Thai status line kept.

**Mask/Restore (`screen-text.js`).** token/surrogate mode → segmented control under the header (it changes output semantics, so it lives where the decision happens; Settings keeps only the default). Input textarea on `--surface`. One primary "ปกปิดข้อมูล"; Copy is secondary with a 1.2s label morph to "คัดลอกแล้ว". Result card: masked text in a `--well` mono block where the render wraps each pseudonym in a chip span — `--token-soft`/`--token` in token mode, `--surrogate-soft`/`--surrogate` in surrogate mode — so the user sees what was masked; the count becomes a 12px meta line. Restore section split by hairline (remove `<hr>`); leftover tokens → `--warn-soft` inline banner. Errors → `--err-soft` banner with retry, inline above the action row.

**Redact PDF (`screen-redact.js`).** Native file input → drop zone (dashed `--line-strong`, `--r-md`, muted doc icon, "วางไฟล์ PDF ที่นี่ หรือคลิกเลือกไฟล์"). Processing = designed row: filename, small spinner, step text 13/muted. Result: before/after previews side by side on a `--well` matte, 1px hairline, 11px overline labels ก่อน / หลัง — "before" carries a `--pii` tick, "after" a `--redact` tick. Summary → definition list (ชนิดไฟล์ / PII ที่พบ / ความมั่นใจ OCR); `human_review: true` → `--warn-soft` banner "ควรตรวจซ้ำด้วยตนเอง (ความมั่นใจ OCR ต่ำ)". `fields[]` (already returned by the API) → small `--redact`-inked chips listing what was blacked out. Download is the screen's one primary button.

**PDPA Report (`screen-report.js`).** Score gets the stat treatment: 30px tabular number + flat grade chip (color by band ok/warn/err) + risk label, with the re-id score and high-risk-combo flag as a second stat in the same row — one restrained stat band, not bolded inline prose. Section 26 hits: list rows with category as a 12px tinted tag; semantic hits get a quiet "semantic" tag in `--ink-faint` (not "(AI)"). Breakdown table: hairline rows, right-aligned tabular counts, FP/TB as 11px chips. Recommendations: rows with a 2px left border in the level color and the level word in that color — no `[bracket]` labels. Pre-analysis empty state: centered 13px muted line, not a blank div.

**Settings (`screen-settings.js`).** Radio rows → choice cards: 1px hairline card per option, selected = `--primary` border + `--primary-soft` wash, 14/500 label + 13px muted one-liner; the token option shows an actual `[ชื่อ_1]` token chip, the surrogate option a teal swatch — mode colors are taught here, once. "ออกจากโปรแกรม" → quiet destructive-secondary (hairline border, `--err` text), not the loud blue it is now. Update card keeps its flow with status 13/muted and release notes in a `--well` block.

**Audit Log (`screen-audit.js`).** Real table: sticky 12/500 muted header row, hairline row separators, no zebra; timestamp 12/`--ink-faint`, step 12px mono, latency right-aligned tabular. Refresh → icon button beside an "อัปเดตล่าสุด HH:mm" meta line. Loading = 5 static skeleton rows; empty = one centered muted line "ยังไม่มีบันทึก". The existing "ไม่มีข้อมูลส่วนบุคคล" description stays (factual scope, not a repeated trust plea).

### Extension popup (`extension/popup.{html,css,js}`)

Same token sheet, 360px wide, **Thai UI**. Header: wordmark + connection status as the single status element (dot + "พร้อมใช้งาน v2.0.0" / "backend ยังไม่ทำงาน — เปิดแอป AI Guard"). Mode radios → the same segmented control as desktop, persisting to `chrome.storage` as today. Two labeled textareas (14/500 labels); Mask primary, Copy secondary, Restore primary-when-armed; message line under the action row in ok/err color. Output `pre` → the `--well` mono block with token chips. "Manual mode…" hint → one 12px muted line under the header. Fonts self-hosted in the extension package (`chrome-extension://` local, no CDN).

### In-page bar + overlay (`extension/content.{css,js}`)

All styling isolated under `.aiguard-`, tokens on component roots, swapped by `prefers-color-scheme`.

- **Bar**: `--surface-raised` + hairline + L1 shadow, `--r-lg`, 20px logo, "Mask PII" filled primary, "Restore PII" ghost **with a visible 1px border in both schemes** (current ghost has border on light only), status text 12px truncating at 180px. Dark host: surface `#18253C`, ink `#E4EAF4`, hairline `rgba(255,255,255,.12)`, primary `#6D9BFF`. System Thai font stack — no webfont injection.
- **Overlay** (currently hard-coded white — flashbangs on dark ChatGPT): scheme-aware component tokens; scrim `rgba(11,18,32,.55)`, card `--surface-raised` at `--r-lg`/L2, title row with a 28px-hit-target close icon button, restored text in a `--well` reading block 14/22, meta line showing replaced count with leftover count in `--warn` when nonzero. Entry: 240ms fade + scale.
- **Per-message chip**: 12/500, `--primary-soft` bg + `--primary` text (dark-host variants), `--r-sm` — a quiet affordance, not a mystery button.
- Both surfaces stay in the navy/blue/hairline vocabulary but deliberately quiet — guests in someone else's app. content.js status strings ("Backend offline - run run.ps1") move to Thai.

## Why this reads premium, not generic (design rationale)

1. **Three palettes → one sheet.** Desktop Tailwind grays, popup navy, print navy/blue now all resolve to the same custom properties — the strongest "designed, maintained" signal a flagship OSS release can send.
2. **~Six primary buttons per screen → one.** Copy, Refresh, Download, Quit are all solid blue today, so nothing is primary. One filled button per view; the rest hairline-secondary or ghost.
3. **Default fonts → a chosen Thai face.** Segoe/Tahoma reads "unstyled Windows app" to Thai users. Plex Sans Thai Looped + tabular figures + the Thai-aware mono fallback says someone chose this.
4. **Raw browser widgets → composed controls.** Native file input, default radios, `<hr>` are the loudest "no designer here" tells — replaced by drop zone, choice cards, segmented control, hairline dividers (all cheap in plain CSS).
5. **Copy doing layout's job → placement doing it.** "โหมด: token (เปลี่ยนได้ที่ Settings)" apologizes for a layout decision. Put the switch on the screen where it acts; the sentence disappears.
6. **Trust pleas everywhere → one structural cue.** The vault rail footer states "ทำงานในเครื่อง" once; repetition reads as insecurity — the opposite of a vault.
7. **Data as prose → data as form.** Scores bolded mid-sentence and "ปกปิด N รายการ" paragraphs become a stat band, grade/token chips, and 12px meta lines. Same information, typographic shape.
8. **Two states → four.** Every async surface gets designed empty/loading/error/success (skeleton audit rows, redact progress row, tinted inline error + retry) — what a live-backend app demands from design.

## Implementation notes

- Define the `--*` token set once as canonical, then place an identical `tokens.css` in **each** package (`desktop/src/tokens.css` and `extension/tokens.css`) — the extension and desktop ship as separate packages with no build step, so they cannot `@import` across each other; keep the two copies byte-identical. `desktop/src/styles.css` and `extension/popup.css` each `@import "tokens.css"`. The content script cannot share a `:root`, so it re-declares the same values on the `.aiguard-*` roots.
- Self-host IBM Plex Sans Thai Looped + IBM Plex Mono WOFF2 under each package's `fonts/` and reference via local `@font-face` (offline/local — no external CDN). Update the extension MV3 `web_accessible_resources` / packaging so the font files ship.
- Keep all existing JS wiring, DOM ids, event handlers, and API calls; this is a restyle + markup-composition pass, not a logic rewrite. Where a component needs new structure (segmented control, choice cards, chips, drop zone, skeleton, stat band), change the render markup in the relevant `screen-*.js` / `popup.js` / `content.js` and its CSS together.
- Verify each surface live in browser preview (desktop via the Tauri dev shell / the `desktop/src` static pages against the running backend; popup + content by loading the unpacked extension). Check the real states: loading, empty, success, error, and the in-page bar/overlay on both a light and a dark host.

## Out of scope / future

- Dark theme for the desktop app and popup (tokens are defined; ship as a `[data-theme="dark"]` pass later).
- Any icon set beyond simple inline stroke SVGs.
- Backend, detection, redaction, and audit logic — unchanged.
