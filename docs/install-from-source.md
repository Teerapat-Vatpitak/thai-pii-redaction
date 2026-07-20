# Running from source

The installer on the [releases page](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/releases/latest)
bundles everything and needs no Python. This page is the developer path: run the
same backend from a checkout.

## Requirements

Python 3.11+ and git.

## Start the backend

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

The script creates a virtual environment and installs dependencies on first run
(a few minutes). The first Thai NER run downloads a ~2 MB model, so it needs
internet once. The backend then listens on `http://localhost:8000` — the same
one the desktop app bundles.

Check it: open `http://localhost:8000/api/health` and you should see
`{"status":"ok"}` with the current version. Interactive API docs are at
`http://localhost:8000/docs`.

## Browser extension

The extension talks to that local backend, so it works with either the desktop
app or this from-source backend.

1. Open `chrome://extensions` in any Chromium browser.
2. Turn on **Developer mode**.
3. Click **Load unpacked** and select the `extension/` folder.
4. Pin the AI Guard extension. Its icon opens the docked side panel; the in-page
   bar activates on `chatgpt.com`, `claude.ai`, `gemini.google.com`, `grok.com`,
   `perplexity.ai`, and `chat.z.ai` / `chatglm.cn`.

Using it: type a prompt containing PII, click **Mask PII**, send with the site's
own Send button, then click **Restore PII** on the reply.

See [extension/README.md](../extension/README.md) for details.

## Command line

```bash
python ai_guard.py report examples/prompts/02_medical_consult.txt
python ai_guard.py sanitize examples/prompts/01_sick_leave_email.txt
python demo_cli.py
```

Sample inputs live in `examples/`.

## Optional: semantic sensitive detector

PDPA Section 26 categories are found by keyword scan by default. An optional
MiniLM sentence-embedding pass catches free-form phrasing the keywords miss:

```bash
pip install -r requirements-ml.txt
```

It is non-generative — it only flags spans already present in your text, so it
cannot invent PII. Without it, the keyword scan runs alone and nothing breaks.

The same extra enables the opt-in WangchanBERTa and `union` NER engines
(`AIGUARD_NER_ENGINE`); see
[docs/decisions/2026-07-15-ner-engine-strategy-decision.md](decisions/2026-07-15-ner-engine-strategy-decision.md)
for why the CRF engine is the default.

## Tests

```bash
python -m pytest        # Python
npm run test:js         # extension harness (vitest + jsdom)
cd desktop/src-tauri && cargo test    # Tauri shell
```

On Windows, set `PYTHONUTF8=1` first so Thai text is not mangled by the console
code page.

## Build the desktop app

```powershell
python scripts/build_sidecar.py     # PyInstaller backend -> Tauri sidecar
cd desktop && npm install && npm run tauri build
```

Requires the Rust toolchain and Node. Output lands in
`desktop/src-tauri/target/release/bundle/`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Backend offline" in the extension | The backend is not running — launch the desktop app or the `run` script. |
| Port 8000 already in use | Stop the process using it, or a previous backend instance. |
| SmartScreen blocks the installer | Expected for an unsigned build: **More info → Run anyway**. |
| Extension bar does not appear | Reload the chat tab after loading the extension. |
| Thai text shows as `?` in the terminal | Set `PYTHONUTF8=1`. |
