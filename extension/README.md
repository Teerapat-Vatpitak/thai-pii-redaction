# AI Guard browser extension

Masks Thai PII in your ChatGPT / Claude prompt before you send it, then
restores the real values locally from the AI's reply. The PII never leaves
your machine: the extension talks only to the local backend, and the
token -> original vault stays in the backend's memory.

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

On `chatgpt.com`, `chat.openai.com`, or `claude.ai` a small **AI Guard** bar
appears (bottom right):

1. Type your prompt (with names, phone numbers, IDs, etc.) in the chat box.
2. Click **Mask PII** -- the box now shows tokens like `[ชื่อ_1]`,
   `[โทรศัพท์_1]`. Send it with the site's own Send button.
3. When the AI replies (keeping the tokens), click **Restore PII** -- the
   real values are shown back in an overlay. You can also select any reply
   text first and then click Restore to restore just that selection.

Each AI message also gets its own best-effort **Restore PII** button.

### Popup (manual fallback)

Click the extension's toolbar icon for a manual panel: paste text, Mask,
copy the safe version, then paste the reply and Restore. Use this if a site
update ever moves the in-page bar. The popup also shows backend status.

## When something breaks

- **"Backend offline"**: the local server is not running -- start it with
  `run.ps1` / `run.sh`.
- **In-page bar missing or buttons do nothing**: the host site changed its
  DOM. All selectors live in `sites.js` -- update them there. Meanwhile, use
  the popup's manual mode.
