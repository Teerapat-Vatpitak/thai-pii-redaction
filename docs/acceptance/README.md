# Functional acceptance

Acceptance answers one question: can a user complete the feature on the real
delivery path without leaking raw PII? It is separate from the later accuracy
benchmark.

Diagnostic and failed-gate records:

- [2026-07-31 Government-form synthetic regression (functional fail)](2026-07-31-government-form-synthetic-run.md)

Detection regression record:

- [2026-08-02 Issue #82 Thai NER span regression](2026-08-02-issue-82-ner-span-run.md)

Other acceptance and qualified runtime records:

- [2026-08-09 Phase 8 native-broker Desktop migration](2026-08-09-phase-8-native-broker-desktop.md)
- [2026-08-08 Phase 8 native-broker data plane, ownership, and disposal](2026-08-08-phase-8-native-broker-data-plane.md)
- [2026-08-08 Phase 8 authenticated native-broker bootstrap and health](2026-08-08-phase-8-native-broker-bootstrap.md)
- [2026-08-08 Phase 8 native-broker protocol and cross-language conformance](2026-08-08-phase-8-native-broker-protocol.md)
- [2026-08-07 Phase 8 authoritative PDF source intervals](2026-08-07-phase-8-pdf-source-intervals.md)
- [2026-08-07 Phase 8 shared provider orchestration](2026-08-07-phase-8-provider-orchestration.md)
- [2026-08-07 Phase 8 explicit-TNER fail-closed source hardening](2026-08-07-phase-8-tner-fail-closed.md)
- [2026-08-06 F-06 eager session lifecycle and authenticated disposal](2026-08-06-f06-session-lifecycle.md)
- [2026-08-06 Office v2 packaged-backend and HTTPS proxy preflight](2026-08-06-office-v2-composition.md)
- [2026-08-06 F-09 outbound fail-closed policy](2026-08-06-f09-outbound-fail-closed.md)
- [2026-08-05 F-04 vault seed and audit hygiene](2026-08-05-f04-vault-seed-hygiene.md)
- [2026-08-05 F-01 transactional sanitize](2026-08-05-f01-transactional-sanitize.md)
- [2026-08-05 hardening baseline at `93a7108`](2026-08-05-hardening-baseline.md)
- [2026-07-24 Pathumma/TNER and HTTP live acceptance](2026-07-24-live-run.md)
- [2026-07-22 Pathumma/TNER live acceptance](2026-07-22-live-run.md)
- [2026-07-23 Storefront release acceptance](2026-07-23-storefront-release-run.md)
- [2026-07-24 Storefront candidate follow-up](2026-07-24-storefront-candidate-run.md)
- [2026-07-24 Desktop 2.5.0 installed-artifact acceptance](2026-07-24-desktop-2.5.0-run.md)
- [2026-07-24 Provisional worker emulator acceptance](2026-07-24-worker-emulator-run.md)
- [2026-07-24 Hosted Docker local acceptance](2026-07-24-docker-run.md)
- [2026-07-23 Office local Word evidence](2026-07-23-office-local-run.md)
- [2026-07-24 Office 2.5.0 local acceptance and promotion preparation](2026-07-24-office-2.5.0-run.md)

Use only the synthetic fixtures in `examples/`, this document, and
`benchmark/data/probe/gov_forms/manifest.json` with its generated corpus.
Evidence must never contain request text, entity values, mappings, credentials,
or provider response bodies.

Checked boxes and dated records below remain evidence of what the exact named
commits and artifacts passed. They are not revoked. The hardening campaign
identified additional gates those runs did not exercise; a modified API/client,
broker, lifecycle, TNER, provider-orchestration, or PDF candidate requires
fresh evidence at the corresponding automated, packaged, real-host,
live-provider, or official-platform level.

The open hardening recertification boundaries are:

- recursive response minimization and fail-closed contract-version/schema
  mismatch;
- no composer, clipboard, document, or provider write after any residual-PII
  signal;
- a broker-admitted local backend boundary before a PII-bearing broker-v1
  installed-client request, within the accepted unsigned-distribution limits;
- no live restoration session ID or other bearer authority in audit filenames,
  entries, stdout, public audit/log projections, or retained evidence; local
  operation responses may return the opaque `session_id` needed for restoration;
- packaged eager backend expiry, session continuity, and broker-backed client
  disposal;
- fresh live certification of current-source whole-request failure for any
  failed or incomplete explicitly selected TNER chunk;
- fresh live/package certification of the current shared provider guards,
  retries, rollback, and safe error semantics; and
- exact entity-span-to-PDF-box alignment with untouched negative-control
  pixels.

The 2026-08-07 Phase 8 TNER record closes the automated current-source portion
of its bullet only. It does not mark the fresh live response/mapping gate
passed. The Phase 8 provider-orchestration record likewise closes only its
automated current-source portion; live-provider, packaged/installed, real-host,
release, deployment, and official-platform recertification remain open. None
of the other bullets is marked passed by this index or by the 2026-08-05
baseline.

The F-01 record closes current-source automated transaction and API audit-ID
checks only. Published-package and official-platform recertification remain
open, as do the other hardening boundaries above.

The F-04 record closes current-source automated vault seed/audit and
public-method locking checks only; public wire, packaged/installed, real-host,
live-provider, release, deployment, and official-platform recertification
remain open.

The F-09 record closes current-source automated outbound residual blocking and
generic sidecar smoke checks only. Current unreleased source now implements
HTTP v2 response minimization and strict first-party client schemas; matching
packaged/installed, real-host, live-provider, authenticated local-process,
broker-backed client lifecycle, and official-platform evidence remains open.

The 2026-08-08 Slice 2 native-broker record covers authenticated platform IPC,
single-instance bootstrap, broker-owned private-backend startup, protocol-v1
health, and deterministic process teardown only. It does not establish the
broker data plane, session ownership/disposal, Chrome Native Messaging,
Extension or Desktop migration, Office support, installer/update migration, or
installed-artifact acceptance.

The 2026-08-08 Slice 3 native-broker record covers the source/runtime data
plane: strict private HTTP-v2 forwarding, connection/scope/session ownership,
confirmed disposal, non-replayable uncertain completion, protocol deadlines,
and backend-generation invalidation. It does not establish Chrome Native
Messaging, Extension or Desktop migration, Office support, installer/update
migration, installed-artifact acceptance, or a release.

The 2026-08-09 Slice 4 record covers the Desktop source migration: production
package JavaScript crosses typed allowlisted Tauri commands, authenticated
Desktop admission, UI/hotkey scopes, broker session handles, fail-closed native
copy/file publication, and frozen broker/backend cleanup. Its evidence is split
by delivery path. The twelve-launch Windows NSIS result is historical
dirty-tree evidence. A clean predecessor passed an installed Windows NSIS smoke;
a later predecessor passed a relocated macOS app job in a workflow that failed
on Linux. Earlier predecessor `8be9523` passed 14/14 CI, including installed
Windows NSIS, and passed relocated macOS; its cross-platform workflow was red
because Linux process inspection failed on an unrelated protected same-UID
process before Desktop launch. That diagnostic harness failure supplied no
Linux DEB/AppImage result. Predecessor `6ad3422` contains the reviewed
candidate-filter repair and passed all 14 jobs in
[CI run 31328047804](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047804),
including the two-run installed Windows NSIS smoke. Its
[cross-platform package run 31328047802](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31328047802)
is red: relocated macOS and extracted DEB passed, but AppImage component digest
verification failed before AppImage Desktop launch because packaging mutated
the bytes after the pre-bundle hashes.

Predecessor `3836024` seals the AppImage manifest from actual
post-linuxdeploy bytes and repacks with a checksum-pinned plugin.
[CI run 31329794579](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794579)
passed, but
[cross-platform package run 31329794568](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31329794568)
is red: macOS passed and Linux failed finalization before package smoke because
the first runtime-prefix guard did not allow appimagetool's defined digest
rewrite.

Predecessor `73dcca4` narrowed that verifier and passed all 14 jobs in
[CI run 31345691672](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691672),
including installed Windows NSIS. Its
[cross-platform package run 31345691667](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31345691667)
is red: relocated macOS and extracted DEB passed, but the AppImage harness
bypassed the outer runtime/`AppRun` and produced no marker. Its 76 focused
package/workflow tests and exact-delta independent review remain valid
predecessor evidence.

Predecessor `8194c23` added a separate canonical private marker root and the
faithful AppImage entrypoint. Its
[CI run 31348501253](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501253)
is red, 10/14, because four Rust jobs exposed only non-portable path spelling in
the new canonical-root unit test; its installed-Windows NSIS job nevertheless
passed. Its separate
[cross-platform package run 31348501256](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31348501256)
passed 2/2: relocated macOS, directly smoked extracted DEB, and the finalized
outer AppImage followed by a re-attested warm `AppRun` all passed. The AppImage
recorded
`execution_mode=outer_appimage_extract_and_run_then_verified_apprun`; the
independent extracted layout attested bytes and was not the launched package.

Last fully gated executable checkpoint `492dad34361b09d7ffa58fa192a2447de7414418`
repairs only that cross-platform test construction. Local focused Python tests
pass 100 with one expected Windows Unix-mode skip. Full local Rust runs of 19
default and 26 all-feature tests preceded the final portability-only edit;
afterward, the exact private-root test passed on Windows and real WSL, and exact
CI confirms all 26 Desktop tests on Ubuntu, Windows, and macOS. Affected
formatting/lint gates pass.
[CI run 31349781519](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781519)
and
[cross-platform package run 31349781518](https://github.com/Teerapat-Vatpitak/thai-pii-redaction/actions/runs/31349781518)
passed 14/14 and 2/2 respectively. The current checkpoint passed two launches
from the exact isolated Windows NSIS installation, two relocated macOS
launches, two direct extracted-DEB launches, and the exact finalized outer
AppImage `--appimage-extract-and-run` launch followed by a re-attested warm
`AppRun`; every path left zero broker/backend process delta. Installed Windows
NSIS, relocated macOS app, extracted DEB, and outer-AppImage plus warm `AppRun`
are distinct evidence classes. The last three are not interchangeable
installation evidence, and this AppImage mode is not normal FUSE/double-click
evidence.

The owner-decision correction after clean branch head `fcdbeed` implements a
credential-free installed Desktop/native-broker profile: local `thainer`, a
`fake`-only backend allowlist for internal conformance, no webview provider
command, stable pre-launch rejection of unsupported selectors, and safe
name-allowlisted child environments with a fixed profile at both seams. Focused source regressions cover
inherited environment, warm-broker attach, unsupported remote/credential-backed
selection, backend startup, and pre-backend Desktop provider rejection. This is
provisional working-candidate evidence; exact-head full CI, package smoke, and
independent review remain pending.

The earlier configuration-ownership P1 is closed and Slice 4 is integrated
after exact branch CI, package smoke, and independent review. Slices 5--6 have
not started. The record does not establish Chrome Native
Messaging or Extension migration (Slice 5), manual visual/updater/relocation,
upgrade/interrupted-upgrade/stale-cleanup/uninstall recertification (Slice 6),
Office broker support, live-provider/TNER evidence, a release, deployment, or
official hosted acceptance.

The F-06 record now has status **merged; main CI green; Phase 8 deferred**. The
first merge review rejected `f968833` with six lifecycle, authorization,
logging, and documentation blockers. Corrective local regressions cover
post-success-only restore refresh, sole managed TTL authority, canonical replay
identity, in-lock expiry validation, real-Uvicorn route redaction, and
session-isolated cleanup. Final branch head `2e147481` passed 11/11 jobs, two
read-only reviewers found no blocker on that exact head, and main integrated it
through history-preserving merge `eb0c45c`. Post-merge CI passed 11/11 and
cross-platform smoke passed 2/2. This source integration does not provide a
native broker, browser/Extension disposal, a broker-admitted local process
boundary, or packaged/installed evidence. Office remains outside broker v1;
its disposal and real-host acceptance remain open under the unchanged
web-add-in architecture.

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

The checked storefront/PDF boxes below describe their cited 2026-07 or
published-2.5.0 candidates. They are historical evidence, not acceptance of the
current HTTP-v2, outbound-policy, or token-identity source candidate. Only a new
dated record against the exact candidate can promote those paths.

## Extension checklist

Historical precondition: the exact 2026-07-23 `extension/` candidate is loaded
unpacked in Chrome and its matching candidate backend is healthy.

- [x] On every declared site, the AI Guard bar is visible once and does not
  cover the composer/send controls.
- [x] Paste the sick-leave fixture, press Mask, and verify the composer itself
  contains tokens while the raw phone/email/name are absent.
- [x] Disable/stop the backend and verify Mask displays the blocking failure
  overlay and does not report success.
- [x] Restore a synthetic reply and verify real values appear only in the
  closed-shadow overlay, not the host page DOM.
- [x] Run two turns and verify the same source value keeps the same token.
- [x] Repeat the basic mask on the generic side panel.
- [x] Record Chrome version, site URL, extension version, pass/fail, and a
  screenshot containing synthetic data only.

Declared sites: ChatGPT, Claude, Gemini, Grok, Perplexity, and GLM/Z.ai. A DOM
fixture test is not a substitute for one current live-site smoke per release.

The exact candidate follow-up recorded on 2026-07-24 completed the basic Mask
smoke on all six declared sites; backend-offline blocking and same-session
token consistency also passed. The generic side-panel Mask was **not** re-run
in that follow-up, so its prior evidence remains carry-forward only. See the
[candidate record](2026-07-24-storefront-candidate-run.md); do not infer an
unrecorded Restore/side-panel result from the all-sites Mask smoke.
Between those exact 2026-07-23 and 2026-07-24 candidates, the only
`extension/` change was the synchronized manifest version. The checked Restore,
side-panel, and screenshot rows therefore retain the 2026-07-23 real-browser
evidence rather than claiming a new run. Current source has changed since both.

## Desktop checklist

Precondition: install the exact candidate artifact, not a dev web page.

- [x] Launch from a clean state; one sidecar starts and `/api/health` reports
  the same product version as the desktop UI.
- [x] Mask and restore the sick-leave fixture in token and surrogate modes.
- [x] Generate and open a PDPA report; verify it contains aggregate fields but
  no fixture values.
- [x] Redact `examples/sample_document.pdf`, open the result, and verify text
  selection/copy cannot recover the source text.
- [x] Exercise settings, audit-log view, global hotkey, and updater check.
- [x] Close the app and verify its sidecar/port is released; reopen once.
- [x] Record installer filename/hash, OS, version, pass/fail, and synthetic-only
  screenshots.

If no candidate binary is installed or built, status is **Blocked**, not Pass.

The exact published Windows `2.5.0` installer completed this checklist on
2026-07-24 and was revalidated for Issue #69 on 2026-08-02. Visual evidence
was inspected in the operator session but not committed; the dated records
contain only version, hashes, aggregate outcomes, and privacy-safe
observations. See the [Issue #69 run record](2026-08-02-desktop-2.5.0-issue-69-run.md).

Those checked boxes remain historical pre-broker evidence. Slice 4's automated
package smoke is not a rerun of this manual checklist: it does not establish
visual inspection, settings/global-hotkey behavior, updater check or install,
supported-path relocation, upgrade, interrupted upgrade, stale cleanup, or
uninstall for executable checkpoint `492dad3`.

## Playground checklist

- [x] `/demo` is unavailable without `AIGUARD_DEMO=1` and available with it.
- [x] The sick-leave sample highlights entities while typing.
- [x] Fake-provider token and surrogate roundtrips restore exactly.
- [x] Pathumma completes without raw fixture values in `ai_response_masked`.
  Unused-token warnings are valid when a conversational answer omits an entity.
- [x] The rules + intent guard shows a warning for the injection fixture and does
  not claim to block it.
- [x] PDPA report download produces a readable PDF.
- [x] PDF upload shows before/after previews and offers a redacted download.
- [x] At projector width and at less than 900 px, every control remains usable.

The exact 2026-07-24 candidate follow-up covered the basic live playground flow and
the PII-free HTTP runner. It also added headless regressions for report and
redacted-PDF download wiring. Those tests do not prove that a browser completed
or opened either download; browser artifact evidence is carried forward from
the exact 2026-07-23 storefront run. Between those two historical candidates,
no production playground/PDF implementation changed; the later candidate added
the missing headless artifact regressions. Current source has changed since
both.

## Office Add-in checklist

Automated packaged-backend/HTTPS-development-proxy composition is a preflight
below both Office acceptance levels. It builds the Office bundle, boots the
packaged backend, fetches the development task-pane entry, and drives strict-v2
API calls through Vite, but it does not execute Office JavaScript or an Office
host and closes no checklist item.

Office evidence has two acceptance levels that must not be combined:

1. **Local host-functional acceptance** runs the exact branch/candidate backend
   and `office-addin/` HTTPS development server through a Microsoft-validated
   host-specific XML transport. It proves task-pane behavior in that host, but
   does not prove the release package or unified acquisition path.
2. **Packaged unified-manifest acceptance** installs the exact promoted package
   and proves that its ribbon/task pane visibly activates in every promoted host.
   The current release manifest is deliberately Word-only; the three-host
   package is not promoted until Excel and PowerPoint host gates pass. Only this
   level closes the Office distribution gate.

Use synthetic PII only. Record Office host, full build number, add-in commit,
backend version, transport, and pass/fail. Do not capture raw selection,
mapping, provider body, credential, or restored answer in logs/test artifacts.

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

Local Office evidence on 2026-07-23: the Microsoft-validated XML transports
showed the AI Guard ribbon/task pane; health ready and backend-offline/disabled
states passed; Detect and PDPA Analyze left the document unchanged; token
Preview left it unchanged; explicit Apply and Restore returned the synthetic
selection exactly, including its boundary space. Changing selection before
Apply was cancelled without modifying either selection, and a deliberate
bold/non-bold range stayed Copy-only. A live Pathumma call showed only a token
in masked outbound, kept the response preview-only, and surfaced
`unused_pseudonyms:1` when the model did not repeat the token. The run also
exposed a false mixed-font result for ordinary Thai + Latin text; the bounded
per-run formatting fix now fails closed when Office cannot prove uniformity. A
clean-candidate follow-up passed its Word real-host rerun, token and surrogate
exact restore, and mixed size/color/highlight Copy-only behavior. Excel changed
only a selected text cell while preserving the formula byte-for-byte and
cancelled a stale-range Apply. PowerPoint changed and restored only selected
uniform text, while mixed size and no-selection cases performed no writeback.
See the [run record](2026-07-23-office-local-run.md). This is a partial
functional slice, not full host or unified distribution/promotion acceptance.

The same run record also contains the unified Word follow-up: ribbon/task-pane
acquisition, multiple-paragraph Preview/Copy-only behavior, protected Pathumma
preview, and explicit Insert response passed. Table and real-host failure cases
remain open; Excel/PowerPoint were not yet present in that historical unified
manifest.

The 2.5.0 preparation record adds local XML evidence for all three hosts, plus
authoritative validation, deterministic packaging, and exact 2.5.0 acquisition
metadata for a proposed three-host unified manifest. The current release
manifest remains Word-only until the remaining host gates pass. Packaged
custom-ribbon visibility remains an Office client-cache/distribution follow-up
and is not represented as Marketplace acceptance.

### Local host-functional acceptance

#### Word

- [x] Task pane health check passes when the backend is running; when stopped,
  every action is disabled and the document stays unchanged.
- [x] Detect and PDPA Analyze read a non-empty selection without changing it.
- [x] Token and surrogate Mask previews do not change the document; explicit
  Apply masks one uniform-format paragraph and Restore returns every character.
- [x] Change selection after Preview and before Apply; the operation cancels and
  neither selection is modified.
- [x] Mixed formatting and multiple paragraphs remain Preview/Copy-only.
- [ ] Table content remains Preview/Copy-only.
- [x] Ask Pathumma shows the masked outbound and restored response. Raw fixture
  values are absent from provider-visible text and no response is inserted
  until Insert response is pressed.
- [ ] Missing `AIFORTHAI_API_KEY`, provider failure, and expired session display
  explicit failures without document corruption or a guessed restoration.
- [x] A response that omits one token displays a leftover/unused-token warning.

#### Excel

- [x] Selected range containing text, formulas, numbers, dates, and blanks
  previews skipped cells and changes only text cells on Apply.
- [x] Capture formulas before/after and verify every formula is byte-for-byte
  unchanged; changing the selected range before Apply cancels the write.
- [ ] Changing a cell value or formula before Apply cancels the write.
- [x] Restore works per text cell in the same task-pane session.
- [ ] Ask Pathumma provides Preview/Copy only and never writes a cell.

#### PowerPoint

- [x] A uniform selected text range can Preview/Apply Mask and Restore.
- [ ] No unselected shape, slide, note, image, or text range changes.
- [x] Mixed formatting or no text selection shows Copy-only/unsupported
  behavior and performs no writeback.
- [ ] Missing PowerPoint API 1.5 shows unsupported behavior and performs no
  writeback.
- [ ] Ask Pathumma provides Preview/Copy only and never changes the deck.

The automated mock suite is necessary but does not satisfy these real-host
items by itself. Checked items above were completed through real Office hosts
using Microsoft-validated local XML transports.

### Packaged unified-manifest acceptance

- [x] The current Word-only manifest passes authoritative schema validation and
  packages deterministically. The acceptance-only XML transports for Excel and
  PowerPoint also pass their schema checks.
- [ ] Install the exact promoted package only after the Excel and PowerPoint
  host gates pass, then verify that the AI Guard ribbon and task pane visibly
  activate in Word, Excel, and PowerPoint. Record all three host builds and the
  package hash. Local XML runs, schema validation, and acquisition metadata do
  not close this gate.

## PDF checklist

- [x] Text-layer fixture: entity count is non-zero, previews render, result opens.
- [x] Extracted text from the redacted result is empty because output is
  flattened; searching/copying the fixture phone/email finds nothing.
- [x] Every black box visually covers the complete source value at inspection zoom.
- [x] Non-PDF input returns 400; oversized input returns 413.
- [x] Scanned input either succeeds with OCR confidence/review metadata or
  returns the documented 503 when OCR extras are absent.
- [x] Temporary files disappear after success and failure.

On the 2026-07-24 candidate, the HTTP runner passed the text-layer redaction,
preview payload, flattened-output, and non-PDF checks. Browser download/open,
visual coverage, oversized-upload, OCR-unavailable, and temporary-file
observations are carry-forward evidence from 2026-07-23 unless explicitly
rerun on a clean release candidate. Current HTTP-v2 response projection and
client changes invalidate any claim that this composition was rerun unchanged;
exact-candidate package/browser/PDF acceptance remains open.

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
