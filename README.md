<p align="center">
  <img src="assets/logo.png" alt="AI Guard logo" width="140" />
</p>

# AI Guard — Thai PII Redaction

Mask Thai personal data (PII) before sending it to an external AI, then restore the real values locally. Everything runs on your machine — raw PII never leaves the device (PDPA-friendly).

PSU Future Tech Challenge 2026 · AI Innovation for Future Society (Prototype)

## What it does

- **AI Guard** — on ChatGPT / Claude, replace PII with tokens (`[ชื่อ_1]`) or realistic fake data before sending, then restore the real values from the reply.
- **True PDF redaction** — black out PII in a PDF (removed from the text layer), returns the redacted file + before/after preview.
- **PDPA report** — risk score plus Section 26 sensitive-data flags (health, religion, …).

Detection runs locally: regex + checksum (Thai ID mod-11, phone, email, …) and Thai NER (PyThaiNLP). No cloud AI is used to detect.

## Installation

The tool is two parts: a **local backend** (the engine) and a **browser extension** (the UI on ChatGPT/Claude). Install the backend one of two ways, then add the extension.

### Step 1 — Start the backend

**Option A · Windows .exe (recommended, no Python needed)**

1. Download `AIGuard.exe` from the [Releases page](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases).
2. Double-click it. Windows SmartScreen may warn about an unknown publisher (the build is unsigned) — click **More info → Run anyway**.
3. A console window opens and your browser opens to the API docs. The backend is now running at `http://localhost:8000`.
4. Keep the window open while you use the tool; close it to stop.

The `.exe` is self-contained — it bundles the Thai NER model and works offline. No Python, no install.

**Option B · From source (Windows / Linux / macOS)**

Prerequisites: **Python 3.11+** and **git**.

```bash
git clone https://github.com/Teerapat-Vatpitak/thai-pii-redaction.git
cd thai-pii-redaction
```
```powershell
./run.ps1     # Windows (PowerShell)
```
```bash
./run.sh      # Linux / macOS / git-bash
```

The script creates a virtual environment and installs dependencies on first run (a few minutes). The first time Thai NER runs it downloads a ~2 MB model (needs internet once).

**Verify either option:** open `http://localhost:8000/api/health` → you should see `{"status":"ok","version":"2.0.0"}`.

### Step 2 — Add the browser extension

1. Open `chrome://extensions` in Chrome / Edge (any Chromium browser).
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked** and select the `extension/` folder from this repo. (With the `.exe`, clone or download this repo to get the `extension/` folder — only the backend needs no Python.)
4. Pin the **AI Guard** extension so you can reach its popup. It activates on `chatgpt.com`, `chat.openai.com`, and `claude.ai`.

See `extension/README.md` for details.

### Step 3 — Use it on ChatGPT / Claude

1. Type a prompt containing PII into the chat box.
2. Click **Mask PII** (the floating AI Guard bar) — your text becomes tokens or fake data.
3. Send it with the site's normal Send button.
4. When the AI replies, click **Restore PII** to see the real values.

### Troubleshooting

- **"Backend offline" in the extension** — the backend isn't running. Start the `.exe` or `run` script (Step 1).
- **Port 8000 already in use** — close whatever is using it, or stop a previous backend instance.
- **SmartScreen blocks the .exe** — expected for an unsigned build; choose *More info → Run anyway*.
- **Extension bar doesn't appear** — reload the ChatGPT/Claude tab after loading the extension.

## Mask modes

| Mode | Output | Use when |
|---|---|---|
| `token` (default) | `[ชื่อ_1]`, `[โทรศัพท์_1]` | you want masking to be obvious |
| `surrogate` | realistic fake data (valid checksums) | you want the AI to read it naturally |

Switch in the extension popup.

## Try the examples

In `examples/` (all PII is fabricated): three realistic Thai prompts and a sample Thai PDF. Explore the API at `http://localhost:8000/docs`, or:

```bash
curl -X POST http://localhost:8000/api/sanitize \
  -H "Content-Type: application/json" \
  -d '{"text":"ผมชื่อสมชาย ใจดี โทร 081-234-5678","mode":"surrogate"}'
```

## Optional: semantic sensitive detector

Catches free-form Section 26 content keywords miss (e.g. "ป่วยเป็นเบาหวาน") via a MiniLM model:

```
pip install -r requirements-ml.txt   # large; the feature self-disables if absent
```

(Not included in the `.exe`.)

## Privacy

The token↔original vault is in memory only — never written to disk or sent over the network. The extension stores only a `session_id`. The external AI sees only masked text.

## Tests

```
PYTHONUTF8=1 python -m pytest
```

## More

Architecture and module map: [`CLAUDE.md`](CLAUDE.md). Note: PyMuPDF is AGPL-licensed.

## Build the .exe yourself

```powershell
./build_exe.ps1     # -> dist/AIGuard.exe
```
