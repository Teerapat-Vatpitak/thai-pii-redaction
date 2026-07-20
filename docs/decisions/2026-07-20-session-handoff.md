# Handoff — 2026-07-20

State at the end of the session that closed roadmap v2 Phase 1 and shipped
v2.3.0. Written for whoever (or whatever) picks this up next.

## Where the project is

- `main` = `4427104`, pushed and in sync. 247 tracked files. `VERSION` = 2.3.0.
- **v2.3.0 is published** — 11 assets, not a draft, provenance attested.
- No open PRs. All Dependabot PRs (#42-#45) merged.
- Python 535 pass / 6 skip · JS 36 pass · Rust 13 pass · ruff clean.

## What happened this session

**Full-repo audit (v2).** Six parallel agents, 59 findings, all with file:line
evidence, recorded in
[2026-07-19-audit-v2-findings.md](2026-07-19-audit-v2-findings.md). The
previous "tier 1-6" audit left no artifact, so it did not count as done.

**Closed: 1 critical + 5 high, all TDD (red test first).**

| id | What it was |
|---|---|
| DET-3 | OCR deskew put bboxes in a rotated space while redaction painted the unrotated page — black boxes missed the PII on skewed scans |
| DET-1 | Thai landlines are 9 digits; the regex demanded 10, so none were ever detected |
| DET-2 | The plate regex claimed a long number's leading digits and dedup then dropped the checksum-valid national ID |
| VAULT-1 | Reverse mapping spliced a surrogate that was a substring of a longer token, injecting real PII mid-token |
| EXT-1 | The extension minted a new session per mask, so restoring an older reply used the wrong vault — wrong person's data |
| DESK-1 | The desktop hotkey treated every failure as success, leaving raw PII in the clipboard |

**Closed: REL-1/2/3 (release gates), REL-12 (pinned toolchains), REL-13.**

**Housekeeping.** Dead text-cleaner stages 4/5/6 removed (verified against
running code first — the kill-list entry was explicitly marked unverified).
ROADMAP regenerated. Rust specs marked superseded. Repo cleaned 289 → 247
tracked files. README rewritten 147 → 105 lines. `pyproject.toml` + ruff +
pre-commit + `.editorconfig` adopted.

**History rewritten.** Claude co-author trailers (14 commits) and a
third-party PSU PDF purged. All SHAs changed.

## Things that bit us — do not relearn these

1. **Adversarial verification found what TDD missed.** After each batch of
   fixes, independent agents were told to *defeat* the fix. They broke four of
   them: DET-2 only handled unseparated digits (real Thai IDs use dashes),
   VAULT-1's rule wrongly applied Thai logic to Latin text, EXT-1 missed the
   side panel, DESK-1 accepted an empty masked string. Tests written by the
   person who wrote the fix share the fix's blind spots.

2. **A gate can break the thing it protects.** The first REL-3 attempt added
   `actions/checkout` to the checksums job, which materialised the repo's
   tracked `assets/` dir, so `mkdir assets` failed under `bash -e` and killed
   the job — no SHA256SUMS, no attestation, on every release. The download dir
   is now `release-assets/` with a guard test. `mkdir -p` would have been the
   wrong fix: it leaves the repo's own PNGs in the attested set.

3. **`Everything up-to-date` is not `correct`.** After the history rewrite, a
   `git fetch --tags --force` pulled the *old* tags back over the rewritten
   ones, so `git push --force --tags` reported nothing to do while every tag
   still pinned the old history. Always verify refs point where you intended,
   not just that the push succeeded.

4. **Merging a Dependabot PR was a release prerequisite.** tauri-action 0.6.2
   names macOS `.app.tar.gz` without a version; the REL-3 gate rejects
   unversioned assets, so the first tagged release would have failed. v1.0.0
   fixed the naming. Unrelated-looking work can be load-bearing.

5. **The formatter must land in its own commit** with the SHA recorded in
   `.git-blame-ignore-revs` — and that SHA must be repointed if history is
   later rewritten, or the file silently stops working.

## Open work

**Not blockers.** All tracked in the findings doc.

- 47 medium/low audit findings. Highest value: VAULT-2 (session eviction is by
  creation time, not LRU, so the *active* session gets dropped), VAULT-3 (no
  locking while FastAPI runs handlers in a threadpool), VAULT-4 (pseudonyms
  written to the on-disk audit log), API-1 (`/api/redact-pdf` is `async def`
  but blocks the event loop).
- **Intel Mac is unsupported** — `latest.json` only carries `darwin-aarch64`
  because the runner is Apple Silicon. Needs a `macos-13` matrix entry.
- **`thai_dictionary_v1.0.csv` licence unverified.** An agent claimed CC BY-SA
  4.0 (copyleft, which would matter — PyMuPDF was purged to stay permissive).
  It could not be confirmed from PyThaiNLP's catalog and was therefore **not**
  written into NOTICE. The NER model's CC BY-4.0 attribution *was* verified and
  added.
- **Old history is still reachable by SHA** through GitHub's 50 permanent
  pull-request refs. Only GitHub Support running gc can remove it.
- REL-2's model-pin check is silent on success, so logs cannot prove it ran.

## Conventions this repo now holds itself to

- Conventional Commits. No `Co-Authored-By: Claude` trailers, ever.
- `VERSION` is the single source of truth; `scripts/bump_version.py` writes it,
  and `app/server.py`'s fallback literal is the one place bumped by hand.
- ruff is kept **green** so CI can enforce it; style-only rules are listed under
  `ignore` in `pyproject.toml` marked deferred, not endorsed.
- Every build input pinned (lockfiles, action SHAs, NER model SHA256,
  pip/Rust/Node versions). The single exception — apt packages — is named in
  the release workflow header rather than glossed over.
- Findings need an artifact. A claim with no reproducible evidence counts as
  not done.
