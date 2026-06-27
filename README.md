# AI Guard — Thai PII Redaction

Mask Thai personal data (PII) before sending it to an external AI, then restore the real values locally. Everything runs on your machine — raw PII never leaves the device (PDPA-friendly).

PSU Future Tech Challenge 2026 · AI Innovation for Future Society (Prototype)

## What it does

- **AI Guard** — on ChatGPT / Claude, replace PII with tokens (`[ชื่อ_1]`) or realistic fake data before sending, then restore the real values from the reply.
- **True PDF redaction** — black out PII in a PDF (removed from the text layer), returns the redacted file + before/after preview.
- **PDPA report** — risk score plus Section 26 sensitive-data flags (health, religion, …).

Detection runs locally: regex + checksum (Thai ID mod-11, phone, email, …) and Thai NER (PyThaiNLP). No cloud AI is used to detect.

## Quick start

**1. Start the backend** (choose one)

- **Easiest — Windows:** double-click `AIGuard.exe` (no Python needed). Build it once with `./build_exe.ps1`, or grab it from Releases.
- **From source:** `./run.ps1` (Windows) or `./run.sh` (Linux/macOS). Creates a venv and installs deps on first run.

Verify: open `http://localhost:8000/api/health` → `{"status":"ok"}`.

**2. Load the browser extension**

`chrome://extensions` → enable **Developer mode** → **Load unpacked** → select `extension/`. (See `extension/README.md`.)

**3. Use it on ChatGPT / Claude**

Type a prompt with PII → **Mask PII** → send with the site's button → when the AI replies, **Restore PII**.

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

## Privacy

The token↔original vault is in memory only — never written to disk or sent over the network. The extension stores only a `session_id`. The external AI sees only masked text.

## Tests

```
PYTHONUTF8=1 python -m pytest
```

## More

Architecture and module map: [`CLAUDE.md`](CLAUDE.md). Note: PyMuPDF is AGPL-licensed.
