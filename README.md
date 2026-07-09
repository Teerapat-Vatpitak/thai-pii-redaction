<p align="center">
  <img src="assets/logo.png" alt="AI Guard logo" width="140" />
</p>

# AI Guard — Thai PII Redaction

<p align="center">
  <a href="https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest"><img src="https://img.shields.io/github/v/release/Teerapat-Vatpitak/thai-pii-redaction?label=release" alt="Latest release" /></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platforms" />
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0" /></a>
</p>

Mask Thai personal data (PII) before sending it to an external AI, then restore the real values locally. Everything runs on your machine — raw PII never leaves the device (PDPA-friendly).

PSU Future Tech Challenge 2026 · AI Innovation for Future Society (Prototype)

<p align="center">
  <img src="assets/demo-before-after.png" alt="AI Guard before and after: real Thai PII on the left, masked tokens on the right" width="760" />
</p>

## What it does

- **AI Guard** — on ChatGPT, Claude, Gemini, Grok, Perplexity, or GLM / Z.ai, replace PII with tokens (`[ชื่อ_1]`) or realistic fake data before sending, then restore the real values from the reply. (On any other page, the docked side panel does the same by paste.)
- **True PDF redaction** — black out PII in a PDF (removed from the text layer), returns the redacted file + before/after preview.
- **PDPA report** — risk score plus Section 26 sensitive-data flags (health, religion, …).

Detection runs locally: regex + checksum (Thai ID mod-11, phone, email, …) and Thai NER (PyThaiNLP). No cloud AI is used to detect.

## Installation

The recommended way to run AI Guard is the desktop app: a native installer that bundles the backend, so there is no Python setup. A from-source / pip path is also available for developers.

### Option A · Desktop app installer (recommended)

1. Download the installer for your platform from the [Releases page](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest):
   - **Windows** (tested, primary platform): `AI.Guard_<version>_x64-setup.exe`
   - **macOS** (experimental — built in CI, not yet verified on real hardware): `AI.Guard_<version>_aarch64.dmg`
   - **Linux** (experimental — built in CI, not yet verified on real hardware): `AI.Guard_<version>_amd64.deb` or `AI.Guard_<version>_amd64.AppImage`
2. Run the installer and launch AI Guard. The backend is bundled and starts with the app — no Python, no separate install, works offline.
3. The app is not code-signed. On first run, Windows SmartScreen may show an "unknown publisher" warning — click **More info → Run anyway** to continue.

### Option B · From source (developer alternative)

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

The script creates a virtual environment and installs dependencies on first run (a few minutes). The first time Thai NER runs it downloads a ~2 MB model (needs internet once). This starts the same backend the desktop app bundles, at `http://localhost:8000` — useful for the browser extension UI below, or for hitting the API directly.

**Verify either option:** open `http://localhost:8000/api/health` → you should see `{"status":"ok"}` with the current version.

### Optional: browser extension (ChatGPT / Claude in-page UI)

The extension talks to the same local backend, so it works with either install option above (desktop app or from-source).

1. Open `chrome://extensions` in Chrome / Edge (any Chromium browser).
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked** and select the `extension/` folder from this repo (clone or download the repo to get it).
4. Pin the **AI Guard** extension so its toolbar icon is handy — clicking it opens the docked **side panel**. The in-page bar activates on `chatgpt.com`, `claude.ai`, `gemini.google.com`, `grok.com`, `perplexity.ai`, and `chat.z.ai` / `chatglm.cn`.

See `extension/README.md` for details.

**Using it:**

1. Type a prompt containing PII into the chat box.
2. Click **Mask PII** (the floating AI Guard bar) — your text becomes tokens or fake data.
3. Send it with the site's normal Send button.
4. When the AI replies, click **Restore PII** to see the real values.

### Troubleshooting

- **"Backend offline" in the extension** — the backend isn't running. Launch the desktop app, or start it via the `run` script (Option B).
- **Port 8000 already in use** — close whatever is using it, or stop a previous backend instance.
- **SmartScreen blocks the installer** — expected for an unsigned build; choose *More info → Run anyway*.
- **Extension bar doesn't appear** — reload the ChatGPT/Claude tab after loading the extension.

## Mask modes

| Mode | Output | Use when |
|---|---|---|
| `token` (default) | `[ชื่อ_1]`, `[โทรศัพท์_1]` | you want masking to be obvious |
| `surrogate` | realistic fake data (valid checksums) | you want the AI to read it naturally |

Switch in the extension side panel.

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

(Not included in the desktop app or the packaged builds.)

## Privacy

The token↔original vault is in memory only — never written to disk or sent over the network. The extension stores only a `session_id`. The external AI sees only masked text.

## Tests

```
PYTHONUTF8=1 python -m pytest
```

## More

Architecture and module map: [`CLAUDE.md`](CLAUDE.md).

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). PDF handling uses the permissively licensed pypdfium2 / reportlab / pdfplumber (PyMuPDF/AGPL is no longer used).

## Build the desktop app yourself

See `desktop/README.md` and `packaging/README.md` for the Tauri build (bundles the backend via `desktop/build-sidecar.ps1`).
