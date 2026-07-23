# Office local acceptance run - 2026-07-23

Status: **provisional functional evidence; unified distribution gate remains
open**.

This run used the Microsoft-validated Word-only `office-addin/manifest.dev.xml`
transport against the local FastAPI backend and HTTPS Vite task pane. It used
synthetic PII only. No raw selection, mapping, provider response, credential,
or screenshot was saved as an artifact.

## Candidate identity

- Product version: `2.4.0` (no development version bump)
- Branch: `codex/office-addin`
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

## Still open

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
