# AI Guard browser extension

Masks Thai PII in your AI chat prompt before you send it, then restores the
real values locally from the AI's reply. The canonical token -> original vault
stays in the local backend's memory and is not deliberately persisted.

Current source uses HTTP contract v1. Its responses can contain fields with, or
allowing reconstruction of, token-to-original pairs in extension process
memory even though the extension does not deliberately persist them. It also
trusts whichever process owns the configured fixed localhost port; CORS does
not authenticate that process. The current backend source now returns no
masked result when it finds structured FP, text-based TB,
detector-independent contiguous 6+ digit residuals, or a missing replacement
record; the extension therefore has no warning-only residual result to write.
That behavior has automated source evidence only. The published 2.5.0 backend
and historical browser/store candidates predate it and must be rerun before a
package is accepted. Contract v2 with no explicit mapping DTO, strict client
validation, broker-backed identity/lifecycle, and fresh package acceptance
remain open hardening gates. Run the source extension only with a local backend
you started and trust, and review high-risk output before submitting it.

The default detector is local. If the backend is explicitly configured with
`AIGUARD_NER_ENGINE=tner`, it sends raw pre-mask chunks to AI for Thai. The
security-sensitive `session_id` is an opaque restoration reference, not the
mapping.

In-page Mask runs after raw text has been typed into the AI site's
provider-controlled DOM. Site code can observe or transmit that draft before
the extension replaces it; no localhost broker can undo that earlier boundary.
For stronger isolation, enter raw text in the side panel, review/copy the
masked result, and paste only that result into the AI site.

Works on **ChatGPT, Claude, Gemini, Grok, Perplexity, and GLM / Z.ai**. Site
DOM selectors live in `sites.js`; each site also has a heuristic generic
fallback. It may survive minor selector drift, but a changed site can make it
select a different visible matching element, so current live-site acceptance
is still required. On any other page the docked side panel (below) still
masks/restores by paste.

## Prerequisites

Start the local backend first (from the repo root):

```powershell
# Windows
./run.ps1
```

```bash
# git-bash / Linux / macOS
./run.sh
```

This serves the API at `http://localhost:8000`. Confirm it is up at
`http://localhost:8000/api/health`.

## Load the extension (unpacked)

1. Open `chrome://extensions` in Chrome (or any Chromium browser).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` folder.

## Use it

On a supported site (`chatgpt.com`, `claude.ai`, `gemini.google.com`,
`grok.com`, `perplexity.ai`, `chat.z.ai` / `chatglm.cn`) a small **AI Guard**
bar appears (bottom right):

1. Type your prompt (with names, phone numbers, IDs, etc.) in the chat box.
2. Click **Mask PII** -- the box now shows tokens like `[ชื่อ_1]`,
   `[โทรศัพท์_1]`. Send it with the site's own Send button.
3. When the AI replies (keeping the tokens), click **Restore PII** -- the
   real values are shown back in an overlay. You can also select any reply
   text first and then click Restore to restore just that selection.

Each AI message also gets its own best-effort **Restore PII** button.

### Side panel (docked workspace)

Click the extension's toolbar icon to open the **AI Guard side panel**, docked
to the side of the browser. Unlike a popup it stays open while you work: paste
text, Mask, copy the safe version, then paste the reply and Restore. Use it on
any page (not just ChatGPT/Claude), or as a fallback if a site update ever
moves the in-page bar. The panel also shows live backend status. Close it with
the toolbar icon again or the panel's own close button; drag its edge to
resize.

## When something breaks

- **"Backend offline"**: the local server is not running -- start it with
  `run.ps1` / `run.sh`. The side panel re-checks status automatically once the
  backend is back.
- **In-page bar missing or buttons do nothing**: the host site changed its
  DOM. All selectors live in `sites.js` -- update them there. Meanwhile, use
  the side panel's manual mode.
