# Functional acceptance

Acceptance answers one question: can a user complete the feature on the real
delivery path without leaking raw PII? It is separate from the later accuracy
benchmark.

Latest recorded run: [2026-07-22 live acceptance](2026-07-22-live-run.md).

Use only the synthetic fixtures in `examples/` and this document. Evidence must
never contain request text, entity values, mappings, credentials, or provider
response bodies.

## Automated HTTP and live-provider run

Start the service with the demo enabled:

```powershell
$env:PYTHONUTF8='1'
$env:AIGUARD_DEMO='1'
.\.venv\Scripts\python.exe -m uvicorn app.server:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts\run_acceptance.py

# Explicitly consumes AI for Thai quota; needs AIFORTHAI_API_KEY.
.\.venv\Scripts\python.exe scripts\run_acceptance.py --live-pathumma --live-tner
```

The command writes a PII-free JSON record under `artifacts/acceptance/`, which
is gitignored. Exit codes are `0` pass, `1` functional failure, and `2` selected
live check blocked by missing credentials.

## Extension checklist

Precondition: current `extension/` is loaded unpacked in Chrome and the exact
candidate backend is healthy.

- [ ] On every declared site, the AI Guard bar is visible once and does not
  cover the composer/send controls.
- [ ] Paste the sick-leave fixture, press Mask, and verify the composer itself
  contains tokens while the raw phone/email/name are absent.
- [ ] Disable/stop the backend and verify Mask displays the blocking failure
  overlay and does not report success.
- [ ] Restore a synthetic reply and verify real values appear only in the
  closed-shadow overlay, not the host page DOM.
- [ ] Run two turns and verify the same source value keeps the same token.
- [ ] Repeat the basic mask on the generic side panel.
- [ ] Record Chrome version, site URL, extension version, pass/fail, and a
  screenshot containing synthetic data only.

Declared sites: ChatGPT, Codex, Gemini, Grok, Perplexity, and GLM/Z.ai. A DOM
fixture test is not a substitute for one current live-site smoke per release.

## Desktop checklist

Precondition: install the exact candidate artifact, not a dev web page.

- [ ] Launch from a clean state; one sidecar starts and `/api/health` reports
  the same product version as the desktop UI.
- [ ] Mask and restore the sick-leave fixture in token and surrogate modes.
- [ ] Generate and open a PDPA report; verify it contains aggregate fields but
  no fixture values.
- [ ] Redact `examples/sample_document.pdf`, open the result, and verify text
  selection/copy cannot recover the source text.
- [ ] Exercise settings, audit-log view, global hotkey, and updater check.
- [ ] Close the app and verify its sidecar/port is released; reopen once.
- [ ] Record installer filename/hash, OS, version, pass/fail, and synthetic-only
  screenshots.

If no candidate binary is installed or built, status is **Blocked**, not Pass.

## Playground checklist

- [ ] `/demo` is unavailable without `AIGUARD_DEMO=1` and available with it.
- [ ] The sick-leave sample highlights entities while typing.
- [ ] Fake-provider token and surrogate roundtrips restore exactly.
- [ ] Pathumma completes without raw fixture values in `ai_response_masked`.
  Unused-token warnings are valid when a conversational answer omits an entity.
- [ ] The rule-based guard shows a warning for the injection fixture and does
  not claim to block it.
- [ ] PDPA report download produces a readable PDF.
- [ ] PDF upload shows before/after previews and offers a redacted download.
- [ ] At projector width and at less than 900 px, every control remains usable.

## PDF checklist

- [ ] Text-layer fixture: entity count is non-zero, previews render, result opens.
- [ ] Extracted text from the redacted result is empty because output is
  flattened; searching/copying the fixture phone/email finds nothing.
- [ ] Every black box visually covers the complete source value at 200% zoom.
- [ ] Non-PDF input returns 400; oversized input returns 413.
- [ ] Scanned input either succeeds with OCR confidence/review metadata or
  returns the documented 503 when OCR extras are absent.
- [ ] Temporary files disappear after success and failure.

## Live provider acceptance semantics

Pathumma has two independent acceptance checks:

1. completion proves the credential, live endpoint, transport, and response
   decoder work; it records (but does not require) whether a controlled marker
   was preserved; and
2. protected roundtrip is the safety gate: raw PII must be absent from
   provider-visible text and every placeholder that is returned must restore.

A generative answer is not required to repeat every placeholder, so marker
preservation is quality telemetry rather than connectivity success. When an
answer omits one, AI Guard must report the unused pseudonym and must not invent
a restored value.

TNER must pass both the live response-shape gate and the end-to-end mapping gate
from live `PER/LOC/ORG/DTM` labels to `NAME/LOCATION/ORGANIZATION/DATE`.
