# Office local acceptance run - 2026-07-23

Status: **provisional functional evidence; unified distribution gate remains
open**.

This run used the Microsoft-validated Word-only `office-addin/manifest.dev.xml`
transport against the local FastAPI backend and HTTPS Vite task pane. It used
synthetic PII only. No raw selection, mapping, provider response, credential,
or screenshot was saved as an artifact.

## Candidate identity

- Product version: `2.4.0` (no development version bump)
- Original-run branch: `codex/office-addin`
- Office host: Word for Windows Desktop
- Reported host baseline: `16.0.20131.20154`
- Evidence state: dirty development tree; repeat release gates from a clean
  candidate checkout
- Distribution path under test: local add-in-only XML, not the release unified
  manifest

## Passed on the real Word host

- Ribbon and task pane opened through the local XML manifest.
- Backend health-ready state enabled actions; stopping the backend disabled
  actions and left the document unchanged; reconnecting restored readiness.
- Detect and PDPA Analyze read a non-empty selection without changing it.
- Token Preview did not change the document; explicit Apply masked the selected
  text and Restore returned it exactly, including boundary whitespace.
- Changing the selection after Preview made Apply fail with the stale-selection
  message and changed neither the old nor the new selection.
- A deliberately bold/non-bold selection stayed Preview/Copy-only.
- A live Pathumma call exposed only a token in masked outbound, did not insert a
  response automatically, and surfaced the unused-pseudonym warning when the
  provider omitted that token.

## Defect found and current fix state

Word's aggregate `Range.font` reports ordinary Thai + Latin text as mixed
because of script-font fallback and automatic theme properties. That made a
visually uniform Thai sentence Copy-only. The adapter now checks direct
bold/italic/underline state per text run and keeps selections over 500
characters Copy-only. The fallback also fails closed when Office cannot prove
uniform formatting. Automated tests cover uniform Thai/Latin fallback, a real
bold/non-bold mix, an indeterminate aggregate response, and the 500-character
bound. The final real-host rerun of the new per-run checker was interrupted and
remains mandatory before Word acceptance can close.

## Still open after the original run

The follow-up sections below close some of these original-run items while
preserving this chronological record.

- Unified-manifest acquisition/ribbon/task-pane on the release transport
- Surrogate Preview/Apply/Restore on the current candidate
- Table and multiple-paragraph Copy-only checks
- Explicit Insert response action after a live Pathumma result
- Missing-key, provider-failure, and expired-session real-host failures
- Final real-host regression of the per-run formatting checker
- All Excel and PowerPoint real-host scenarios

After this run, separate Microsoft-validated local XML transports were prepared
for Excel and PowerPoint. That preparation is non-UI evidence only; neither host
was opened or counted as accepted.

The local XML result may be cited as functional isolation evidence only. It
must not be used to mark Word, the unified package, or the Office lane Done.

## Clean-candidate follow-up

A follow-up run used the same host-specific local XML transports from the clean
`codex/office-format-acceptance` candidate at commit `ed3d65f`. Product and
backend version remained `2.4.0`. The run again used synthetic PII only and did
not save selections, mappings, restored text, provider bodies, credentials, or
screenshots.

Automated Office gates on this candidate passed manifest validation,
type-checking, build, and all 59 tests. The real-host follow-up added this
functional evidence:

### Word

- A visually uniform Thai + Latin selection was writable after the adapter
  ignored script-font fallback while checking direct formatting.
- Mixed font size, color, or highlight remained Preview/Copy-only.
- Token and surrogate Preview/Apply/Restore each returned the selection exactly.

Word remains partial. Table and multiple-paragraph handling, explicit Insert
response, missing-key/provider-failure/session-expiry behavior, and the release
unified manifest still require real-host acceptance.

### Excel

- A selected range containing text, a formula, a number, a date, and a blank
  reported every skipped non-text cell before Apply.
- Apply changed only the text cell. The formula remained byte-for-byte
  unchanged, and Restore returned the text cell exactly.
- Changing the selected range after Preview made Apply fail without changing
  the worksheet.

Excel remains partial. Ask Pathumma Preview/Copy-only behavior still requires a
real-host run, and the host remains absent from the release manifest.

### PowerPoint

- A uniform selected text range supported Preview/Apply/Restore.
- An unselected placeholder stayed unchanged.
- Mixed font size stayed Preview/Copy-only, and no text selection produced an
  explicit failure without changing the deck.

PowerPoint remains partial. Additional shape/slide/note/image isolation, the
unsupported-API 1.5 fallback, Ask Pathumma Preview/Copy-only behavior, and the
release manifest promotion gate remain open.

This follow-up closes the previously recorded Word formatting-rerun item. It
does not close any host section or the unified distribution gate.

## Unified Word follow-up

The `codex/release-2.5.0-acceptance` candidate at code commit `6bd10d1`
corrected `validDomains` from a URL to the required `localhost:3000` host and
port form and added a deterministic validation guard. The unified Word package
then registered successfully, Word acquired the AI Guard ribbon, and the task
pane opened against backend version `2.4.0`.

Using synthetic PII only on that unified transport:

- a multiple-paragraph selection produced a masked preview but remained
  Preview/Copy-only, with no document writeback;
- a protected Pathumma roundtrip displayed masked outbound and restored
  response text without changing the document automatically; and
- the response was inserted after the selected text only after the explicit
  Insert response action.

No selection, mapping, provider body, credential, restored answer, or
screenshot from this run was persisted as a repository artifact. The temporary
unified sideload, backend, and HTTPS development server were stopped after the
run.

This closes Word unified acquisition, multiple-paragraph fail-closed, and
explicit response insertion evidence. Word table handling, missing-key,
provider-failure, and expired-session real-host cases remain open. Excel and
PowerPoint are still absent from the release unified manifest and no Office
host section is fully accepted yet.
