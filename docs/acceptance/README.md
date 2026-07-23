# Functional acceptance

Acceptance answers one question: can a user complete the feature on the real
delivery path without leaking raw PII? It is separate from the later accuracy
benchmark.

Latest recorded runs:

- [2026-07-22 Pathumma/TNER live acceptance](2026-07-22-live-run.md)
- [2026-07-23 Office local Word evidence](2026-07-23-office-local-run.md)

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
live check blocked by missing credentials. Evidence records the full Git commit
and a `git_dirty` flag; any credential-bearing URL components are discarded.
Treat a dirty-tree record as provisional evidence and reproduce release gates
from a clean candidate checkout.

For the full optional acceptance environment, use Python 3.13 and install the
four dependency groups together before running the complete suite:

```powershell
$env:PYTHONUTF8='1'
uv venv --python 3.13 .venv-full
uv pip install --python .venv-full\Scripts\python.exe `
  -r requirements.txt -r requirements-web.txt `
  -r requirements-ml.txt -r requirements-ocr.txt
uv pip check --python .venv-full\Scripts\python.exe
.\.venv-full\Scripts\python.exe -m pytest -q -ra
```

Keep this environment outside release packaging. ML/OCR are optional product
paths and remain excluded from the frozen desktop sidecar and hosted core image.

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

Declared sites: ChatGPT, Claude, Gemini, Grok, Perplexity, and GLM/Z.ai. A DOM
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
- [ ] The rules + intent guard shows a warning for the injection fixture and does
  not claim to block it.
- [ ] PDPA report download produces a readable PDF.
- [ ] PDF upload shows before/after previews and offers a redacted download.
- [ ] At projector width and at less than 900 px, every control remains usable.

## Office Add-in checklist

Precondition: run the exact branch/candidate backend and `office-addin/` HTTPS
development server, sideload its unified manifest, and use synthetic PII only.
Record Office host, full build number, add-in commit, backend version, and
pass/fail. Do not capture raw selection, mapping, provider body, credential, or
restored answer in logs/test artifacts.

The original Word-only unified package registered and launched Word but did not
acquire its ribbon/task pane. The manifest declared `validDomains` as a URL
instead of a host and port. After correcting it to `localhost:3000`, Word
acquired the AI Guard ribbon and opened the task pane on 2026-07-23.
The host-specific local add-in-only manifests may be used to isolate task-pane
and host behavior from tenant acquisition: `manifest.dev.xml` for Word,
`manifest.dev.excel.xml` for Excel, and `manifest.dev.powerpoint.xml` for
PowerPoint. They use separate add-in IDs and are acceptance-only; schema
validation or a functional pass on them cannot close the unified-manifest
promotion gate.

Local Office evidence on 2026-07-23: the Microsoft-validated XML transports showed
the AI Guard ribbon/task pane; health ready and backend-offline/disabled states
passed; Detect and PDPA Analyze left the document unchanged; token Preview left
it unchanged; explicit Apply and Restore returned the synthetic selection
exactly, including its boundary space. Changing selection before Apply was
cancelled without modifying either selection, and a deliberate bold/non-bold
range stayed Copy-only. A live Pathumma call showed only a token in masked
outbound, kept the response preview-only, and surfaced `unused_pseudonyms:1`
when the model did not repeat the token. The run also exposed a false mixed-font
result for ordinary Thai + Latin text; the bounded per-run formatting fix now
fails closed when Office cannot prove uniformity. A clean-candidate follow-up
passed its Word real-host rerun, token and surrogate exact restore, and mixed
size/color/highlight Copy-only behavior. Excel changed only a selected text cell
while preserving the formula byte-for-byte and cancelled a stale-range Apply.
PowerPoint changed and restored only selected uniform text, while mixed size and
no-selection cases performed no writeback. See the
[run record](2026-07-23-office-local-run.md). This is a partial functional
slice, not full host or unified distribution/promotion acceptance; the
checkboxes remain unchecked until their whole scenario passes on the release
transport.

The same run record also contains the unified Word follow-up: ribbon/task-pane
acquisition, multiple-paragraph Preview/Copy-only behavior, protected Pathumma
preview, and explicit Insert response passed. Table and real-host failure cases
remain open, and Excel/PowerPoint have not yet been promoted into the unified
release manifest.

### Word

- [ ] Task pane health check passes when the backend is running; when stopped,
  every action is disabled and the document stays unchanged.
- [ ] Detect and PDPA Analyze read a non-empty selection without changing it.
- [ ] Token and surrogate Mask previews do not change the document; explicit
  Apply masks one uniform-format paragraph and Restore returns every character.
- [ ] Change selection after Preview and before Apply; the operation cancels and
  neither selection is modified.
- [ ] Mixed formatting, table content, and multiple paragraphs remain
  Preview/Copy-only.
- [ ] Ask Pathumma shows the masked outbound and restored response. Raw fixture
  values are absent from provider-visible text and no response is inserted
  until Insert response is pressed.
- [ ] Missing `AIFORTHAI_API_KEY`, provider failure, backend shutdown, and
  expired session display explicit failures without document corruption or a
  guessed restoration.
- [ ] A response that omits one token displays a leftover/unused-token warning.

### Excel

- [ ] Selected range containing text, formulas, numbers, dates, and blanks
  previews skipped cells and changes only text cells on Apply.
- [ ] Capture formulas before/after and verify every formula is byte-for-byte
  unchanged; changing a value/formula/range before Apply cancels the write.
- [ ] Restore works per text cell in the same task-pane session.
- [ ] Ask Pathumma provides Preview/Copy only and never writes a cell.

### PowerPoint

- [ ] A uniform selected text range can Preview/Apply Mask and Restore.
- [ ] No unselected shape, slide, note, image, or text range changes.
- [ ] Mixed formatting, no text selection, or missing PowerPoint API 1.5 shows
  Copy-only/unsupported behavior and performs no writeback.
- [ ] Ask Pathumma provides Preview/Copy only and never changes the deck.

The automated mock suite is necessary but does not satisfy these real-host
items. Keep status **Acceptance pending** until all three host sections pass.

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
