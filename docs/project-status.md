# Project status

Updated: 2026-08-06

This is the acceptance ledger for the current roadmap. It distinguishes code
existence from evidence on the real delivery path.

This document answers one question: **what is actually finished, and what is the
evidence**. It is not the code map ([CLAUDE.md](../CLAUDE.md)) and it does not set
priority or order ([ROADMAP.md](../ROADMAP.md)). Every storefront named in the
code map must have a row here; `tests/test_docs_coverage.py` enforces that.

Benchmark note: `blind-v1` is a closed historical evidence set. Its six-reveal
budget is exhausted, so it must not be described as an active blind evaluation
or used for further tuning. A future blind measurement requires a newly frozen
`blind-v2` dataset. The exact WSL candidate at commit `ded67d3` passed the
synthetic government-form privacy gate 9/9. That is historical
exact-candidate evidence, not a run of the current HTTP-v2/PDF composition;
physical scans, handwriting, and broader real-form annotation remain outside
it.

Latest detector campaign evidence (2026-08-04): commit `fcd3b0d` closed the
enumerated bug/mechanism inventory and added adversarial recall regressions.
The local gold run (`python -m benchmark --source gold`) measured overall F2
0.947, entity recall 0.969, character coverage recall 0.986, exact-boundary
recall 0.892, and 15 false positives in the 45-document negative slice. These
are gold/synthetic local measurements, not blind generalisation evidence:
`blind-v1` is exhausted and future measurement requires `blind-v2`. The
campaign's accepted owner decisions, known OCR rerun block, and performance
interpretation are recorded in
[the 2026-08-04 campaign record](decisions/2026-08-04-weakness-closure-campaign.md).

Performance-gate follow-up (2026-08-04): `scripts/measure_perf.py` now gives
each PDF-redaction measurement an isolated temporary output directory and
removes it afterward, so concurrent local runs cannot collide on one fixed
`tmp/perf-redacted.pdf`. This closes a harness defect found during the
campaign. The committed `perf/baseline.json` remains unchanged: an unmodified
`20a9a1d` run on the same machine was already above it, and repeated runs
varied widely; the campaign's controlled in-process detector comparison
remained +7.5%, inside the 20% budget. The baseline is a local comparison
anchor, not a production SLO; recalibration requires a deliberately controlled
measurement.

Hardening control (2026-08-05): the clean `93a7108` baseline passed 1,677
Python tests, 60 root JavaScript tests, 68 Office tests, 19 Rust tests, and a
newly built packaged-sidecar smoke. Five optional OpenCV tests skipped. The
formal performance command was red on unchanged `main` because the 0.28 ms
restore anchor measured 0.40 ms; repeated controls confirmed local timing
variance, so the baseline was not moved. Exact commands, warnings, and
unverified paths are in the
[dated baseline record](acceptance/2026-08-05-hardening-baseline.md).

That control freezes the pre-fix truth at `93a7108`. Current source now stages
local sanitization on a detached session/vault graph and publishes it once only
after core processing, Section 26, guard projection, response encoding, and a
correlation-only process-audit write succeed. Failure-injection coverage
preserves the published graph, token ordinals, capacity/LRU state, and
concurrent visibility. Known-session expiry remains request-driven lifecycle
disposal outside rollback; displaced-vault cleanup after publication is best
effort. A clear generation prevents a stale provider rollback snapshot from
reviving disposed mappings.

Caller-held stateless mappings are now re-admitted under opaque
`seed:<uuid4>` entity IDs with the internal `SEEDED` provenance marker. An
identical replay returns its existing immutable record without changing
lookup, audit, or access state; a conflicting original raises a constant
value-free error before mutation. New seeds add one structural `seed` audit
row, so the retained internal audit remains free of the caller's pseudonym and
original before and after `clear()`.

Current source now applies one fail-closed outbound policy to local-session and
stateless sanitization: structured FP findings, text-based TB findings,
detector-independent contiguous runs of six or more digits, anonymization
failures, and missing replacement records return no masked result. A
caller-seeded pseudonym is reused only when nonempty, original-free, absent
from the current source text, and free of independent FP/TB/digit residual
signals; token mode also requires the product token shape for the detected data
type. Identity, embedded-original, empty, cross-type residual, and
duplicate-occurrence laundering regressions are blocked. Local-session
rejection remains inside the existing atomic transaction. The CLI repeats the
scan immediately before each outer `provider.complete()` invocation. A
self-retrying provider receives one outer validation before resending the same
immutable masked text. HTTP and worker roundtrip repeat the scan immediately
before their direct calls. HTTP returns 422 with a bounded `residual_pii`
v2 error envelope and the version-1 worker envelope returns a value-free
`residual_pii` error.

This is current-source automated evidence only. Historical packaged,
storefront, and live-provider evidence predates the outbound-policy change and
must be rerun. Current HTTP v2 removes mapping-oriented fields, raw Section 26
matches, and prompt-guard excerpts/rationales; first-party clients validate
exact response schemas and safety state. Token mode now combines a random
vault-generation tag with an unpredictable per-token nonce. Regressions show
that stale and guessed tokens remain foreign in the exercised drop, restart,
expiry, eviction, and same-session preplay cases. The random 64-bit tag plus
approximately 94-bit nonce makes accidental identity reuse and future-token
preplay computationally impractical; this is probabilistic separation, not
impossibility. These changes do not close the remaining
baseline gaps. There is no
general expiry sweep, so an idle entry can remain until it is accessed,
explicitly dropped, evicted, or the process ends; the fixed localhost data
plane does not authenticate the process that owns the port; explicit TNER chunk
failures can degrade to partial detection; shared provider roundtrip
orchestration is not yet one choke point; and PDF boxes are selected through
global original-text-fragment matching rather than authoritative source
offsets. Their effects in real browsers, installed Desktop, Office hosts, live
providers, or official platforms remain inferred or unverified unless a dated
record exercises that composition.

The 2026-08-06 exact-current formal performance command is red against the
stale committed anchors: detect `7.95 ms` versus `5.73 ms` (`+39%`), sanitize
`23.63 ms` versus `10.08 ms` (`+134%`), PDF `83.86 ms` versus `67.67 ms`
(`+24%`), restore `0.28 ms` versus `0.28 ms`, and resident memory `151.4 MiB`
versus `151.4 MiB`. Because unchanged code is also variable on this machine, a
three-pair alternating comparison against exact base `c533ec9`, using 20
iterations per process, compared the medians of the three process medians.
Candidate versus base was detect `9.78/9.49 ms` (`+3.1%`), sanitize
`28.69/18.37 ms` (`+56.2%`), restore `0.38/0.64 ms` (`-40.6%`), PDF
`131.22/111.28 ms` (`+17.9%`), and resident memory `153.8/154.7 MiB`
(`-0.6%`). Profiling attributes the sanitize delta to the approved longer
token identity crossing the 500-character outbound TB-NER chunk boundary; the
full original sanitized text is still scanned, and masking trusted ranges was
rejected because it hid adjacent residual PII. The exact-candidate sanitize
delta exceeds the repository's 20% time budget. The owner explicitly accepted
this measured privacy/security trade on 2026-08-06 so full original-text
residual scanning remains intact; this is not evidence that the performance
budget passed. The committed baseline remains unchanged, and formal and
same-environment results are kept separate.

## Status vocabulary

- **Verified** - implemented and covered on its intended automated/runtime path.
- **Verified locally** - passed a repeatable local runtime or emulator check,
  but is not evidence from the release transport or hosted platform.
- **Acceptance pending** - implemented, but a real provider, browser, package,
  or platform run is still required.
- **Hardening open** - dated evidence remains valid for its exact candidate,
  but a verified current gap blocks treating the affected path as accepted
  until the fix and its required recertification pass.
- **Blocked externally** - the remaining step needs a third-party contract,
  provider/platform state, or another change outside owner control. Owner-gated
  outward actions are labeled separately.
- **Optional** - supported only when an explicit extra is installed/configured;
  absence must fail clearly.
- **Documented** - a document deliverable, not code: the claims were checked
  against their sources and the codebase; there is no runtime path to verify.
- **Deferred** - intentionally out of current scope; the list lives in
  [ROADMAP.md](../ROADMAP.md).

## Core and API

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Structured + Thai NER detection | Verified | Shared `detect_all` path, regression tests, a dated pre-current-candidate Docker smoke, and Issue #82 coverage for malformed default-CRF cross-line/nested spans. Existing name hygiene and cue recovery produce bounded `NAME` spans while preserving independent following addresses; the Issue #82 fix required no value-specific rule or engine change. The later Track A weakness-closure campaign added bounded detector safeguards; its latest metrics and limitations are recorded above. |
| Detection benchmark | Verified | `python -m benchmark` scores synthetic and hand-authored gold corpora (including a negative slice) at entity, character, and exact-boundary level, plus an engine/strategy comparison and an external LLM baseline. Gold is at v4: adjudicated 2026-07-28 by two independent reviewers against [annotation-guidelines.md](annotation-guidelines.md) ([record](decisions/2026-07-28-gold-adjudication.md)). The latest local gold result is recorded above; reports are generated locally and gitignored. |
| Government-form phase-2 probe harness | Verified locally | Source and sanitized-artifact hashes are pinned for official blank คร.1, ภ.ง.ด.91 and สปส.1-03; raw downloads are not committed, and tests reject metadata or hidden payload structures in the page-only copies. The strict runner builds and checks all nine synthetic inputs in one process, including real OCR, pixel coverage, residual, declared-decoy extraction, cardinality, unique-alignment, repository-state, dependency, and PII-free evidence checks. A current-tree WSL rerun at commit `ded67d3` completed all 9/9 inputs with 0 gate failures: 45/45 values removed, 0 exposed, 0 unmeasurable, residual OCR measured on 9/9, and no decoy false hits. The runner summary was conservatively labeled `functional_pass_repository_dirty` during the WSL run; immediately afterward both Windows and WSL `git status` were clean at the same commit. This is current-tree functional evidence, not general-form accuracy: synthetic expectations remain developer-authored and not independently adjudicated; ท.ร.6, physical scans, handwriting, and broader real-form annotation remain outside this evidence. Runtime remains a limitation: the WSL run took about 34 minutes and peaked near 8 GiB RSS, while the Windows run still has a 30-minute timeout/access-violation history. Exact sources, commands, results and limitations: [gov-doc-phase2.md](research/gov-doc-phase2.md) (2026-08-04 addenda), the superseded [dated failed-gate record](acceptance/2026-07-31-government-form-synthetic-run.md), and the gitignored run directory `benchmark/reports/gov-forms-2026-08-04-wsl-current-60m`. |
| Blind evaluation set | Verified | `blind-v1` frozen 2026-07-28: 185 documents / 479 entities across the 11 types plus a 52-document negative slice, authored and reviewed in isolated contexts and committed only as an authenticated blob + lock (counts pinned in `benchmark/data/blind-v1.lock.json`). Scoring is aggregate-only under a 6-reveal budget with a hash-chained committed audit log. Reveals used — the freeze baseline; campaign 1 (PRs #90-#91), which generalized (F2 0.837 to 0.903, non-overlapping CIs); campaign 2 (PR #93, NAME cues), which did NOT generalize (blind F2 flat, NAME precision 0.748 to 0.700) and pointed at engine-level work; campaign 3 (PR #97 + the fine-tune), which answered campaign 2's open question — blind NAME precision 0.700 to 0.922 at recall 1.000, overall F2 0.914, negative clean rate 0.346 to 0.423 ([results](decisions/2026-07-28-finetuned-ner-results.md)); and campaign 4 (the gov-form OCR detection gaps, main `553c8af`, owner-approved reveal on 2026-08-02, default CRF engine), which was generalization-neutral by design expectation — overall F2 0.8977 to 0.8981 (flat, within the 0.877-0.916 CI), precision and both family macros unchanged, negative slice byte-identical (54 FP, clean rate 0.346) — while character coverage recall rose 0.914 to 0.929 and exact-boundary recall 0.614 to 0.639 with one fewer false positive: no overfit to gold, no regression, and the campaign's OCR-specific gains are not expressible on a prose corpus (they are evidenced by the gov-form gate instead). Reveal 6 (same day, also owner-approved) spent the final reveal re-certifying the fine-tuned opt-in engine on the same code, since the campaign changed rule layers that engine shares: overall F2 0.914 to 0.916, exact-boundary recall 0.647 to 0.666, coverage recall 0.919 to 0.931, NAME precision 0.922 to 0.915 at recall 1.000 (within noise), negative slice identical (54 FP, clean rate 0.423) — the reveal-4 certification stands on current main. The budget is EXHAUSTED at 6 of 6; any future blind measurement requires a frozen blind-v2. Protocol: [2026-07-28 ADR](decisions/2026-07-28-blind-set-protocol.md). |
| Token and surrogate sanitization | Hardening open | New and existing sessions have automated coverage across core, Section 26, guard, response-render, audit-write, and outbound-policy failure seams; a separate cap-full regression preserves the selected victim and LRU state. For non-expiry pre-publication failures, published state, ordinals, timestamps, and concurrent restore/drop visibility remain unchanged. Current source returns no result for structured FP, text-based TB, detector-independent contiguous 6+ digit, anonymization, or missing-replacement failures. Caller mappings cannot reuse empty, identity, embedded-original, source-pre-existing, independently residual-looking, or wrong-token-type pseudonyms. Token mode mints `[<label>_<generation-tag>_<token-nonce>_<ordinal>]`; the non-secret tag carries 64 random bits and each newly minted token adds an approximately 94-bit nonce. This makes accidental identity reuse and preplay computationally impractical rather than impossible. The tag and complete tokens survive transaction clone/snapshot and are invalidated by `clear()`. Strict HTTP-v2 projection/client behavior has automated source evidence; package recertification remains open. |
| Local multi-turn re-identification | Hardening open | The backend vault, TTL/LRU, collision, and concurrency behavior have automated coverage. Shared-vault seed hardening rejects conflicting caller-held mappings and retains only opaque seed IDs in its structural audit; those seed paths serve stateless prior mappings rather than normal `SessionService` sessions. Direct restore defects surface as a fixed `RestoreTransactionError`, and expiry translation has no retained exception context. Current v2 sanitize/reidentify responses expose no explicit mapping DTO or original/token pairs. Namespaced-token regressions cover drop, restart, expiry, and eviction under token and surrogate replacement modes: stale text remains unchanged with zero replacements and one count-only foreign warning in the exercised cases. A separate regression shows a guessed future token remains foreign after the corresponding ordinal is later minted. Expiry remains request-driven, with cleanup on session access, explicit drop, cap-driven eviction, or process exit rather than a general sweep. |
| Stateless core and worker sanitization | Hardening open | The in-process stateless result returns a transient mapping to its adapter for immediate restoration; the version-1 worker wire result omits it unless `include_mapping` is the exact JSON boolean `true`. Current-source regressions cover exact seed replay, conflict rejection, opaque IDs, audit retention after clear, detached cloning, every outbound residual class, missing replacement records, fixed value-free direct-core processing errors, throwaway-vault cleanup, and value-free `residual_pii` worker errors. Fresh stateless token calls use independent generation tags and per-token nonces; an explicit prior mapping with one admissible tag can continue that chain and reuse complete tokens. Exact grammar plus the residual policy must pass before a seeded token can be reused or select the minting namespace. The worker remains a local emulator, not official hosted delivery; shared provider orchestration and official acceptance remain open. |
| Protected provider roundtrip | Hardening open | The 2026-07-23 live Pathumma run remains historical evidence for that exact candidate: raw synthetic PII stayed out of provider-visible text and every returned token restored. Current-source regressions prove that the CLI rescans before each outer provider invocation and that HTTP/worker adapters rescan immediately before their direct provider call, rejecting residuals with safe errors. A provider declaring `handles_retries=True` receives one outer validation before its one outer invocation and may resend the same immutable masked text internally. The CLI wrapper contains snapshot, capability, validation, provider, response-tail, and rollback failures and exposes only fixed safe categories. Tokenmind's current internal loop uses one total timeout and honors `Retry-After`, which does not yet match the locked shared-orchestration target of up to three 60-second attempts with fixed 1/2-second backoff. HTTP and worker still bypass the CLI retry/rollback orchestrator, so shared orchestration remains open. The changed source path needs fresh live-provider acceptance, and official hosted deployment remains a separate platform gate. |
| PDPA JSON analysis | Verified | Shared analyzer and API tests. |
| PDPA section 39 processing receipt | Verified | `ai_guard.py receipt issue\|verify` plus `pii_redactor/receipt.py`; 41 tests covering the digest contract, the PII-free property of both the JSON and the PDF, and the five verify outcomes. An independent adversarial review in a separate context (2026-07-29) found that the first implementation verified only the two digests, leaving every figure a reader actually looks at — entity/FP/TB counts, per-type counts, file size, source type — editable with no effect on the verdict; both sides now derive from one `_claims()` builder and a parametrised test forges each field in turn. The determinism claim is measured, not asserted: three subprocesses under `PYTHONHASHSEED` 0, 1 and `random` return one digest, and the test fails if that digest is the empty-result one. Note what that does *not* show: it varies the hash seed only, so machine- and dependency-independence remains unproven — which is why the receipt now records the PyThaiNLP version, the loose `>=` floor being the likeliest real cause of a mismatch. No HTTP endpoint by design ([record](decisions/2026-07-29-processing-receipt.md)). |
| PDPA section 37(4) breach assessment | Verified | `ai_guard.py breach assess` plus `pii_redactor/breach.py` and `pii_redactor/breach_pdf.py`; 42 tests across `tests/test_breach_assessment.py` (19), `tests/test_breach_cli.py` (15), and `tests/test_breach_pdf.py` (8) covering the affected-subject estimate's min/max bounds on crafted overlaps (all four strong identifier types, including `PASSPORT`), id/phone/email normalization (including a `+66` mobile or landline form folding to its domestic digits), exit codes 0/2/1, and the PII-free property of both the JSON and the PDF. No new retention: the distinct-value sets behind the estimate are plain in-memory sets dropped with the process, and the estimate itself is a range with a stated method and assumption, never a point estimate — no cross-document or cross-type person linkage is attempted. A review round found the first cut's failed-file reason leaked the full input path via stdlib exception messages (e.g. `FileNotFoundError`'s own text); every spelling of the path is now scrubbed to a bare basename before it reaches either artifact, and the same scrub now covers a corpus-level failure that escapes `assess_breach` itself. A second review round (2026-08-01) found and closed three gaps: a directory scan dropped non-`.txt`/`.pdf` files with no signal that anything was skipped (`files.skipped` now reports the count and basenames in the JSON, the PDF, and the CLI summary, and `files.total` counts everything the scan found rather than just what survived that filter); a failed `-o` JSON write after a successful `--pdf` write left a complete assessment PDF on disk for a run reporting a hard failure (the PDF this run wrote is now deleted, and the error message says so); and a corpus with no strong identifier rendered a literal "0-0 คน" headline, which reads as "nobody affected" rather than "no strong identifier found" (`subjects.no_strong_identifiers` now drives distinct wording in both the CLI and the PDF). No HTTP endpoint by design ([record](decisions/2026-08-01-breach-assessment.md)). |
| PDPA มาตรา 30 DSAR helper | Verified | `ai_guard.py dsar locate` plus `pii_redactor/dsar.py` and `pii_redactor/dsar_pdf.py`; 57 tests across `tests/test_dsar.py` (27), `tests/test_dsar_cli.py` (20), and `tests/test_dsar_pdf.py` (10) covering subject-line classification by shape, id/phone/email/name canonical matching (spaced/hyphenated ids, a `+66` or domestic phone form, case-insensitive email, a name with or without its title), value-based matching that ignores the detector's own type label for an entity (a phone the detector tags `BANK_ACCOUNT`, a name it tags `ORGANIZATION`, both still match, with a negative control confirming an unrelated value under the same label does not), one precision guard on that label-independence (a bare digit run merely starting `66`, e.g. an unrelated bank account, is never folded into a false phone match — only an entity whose own raw text still carries an explicit `+66` marker gets the international-to-domestic fold), the `weak_only` flag on a NAME-only match, the `third_party_possible` flag (including its own fixed note stating the flag is heuristic), exit codes 0/2/1, and the PII-free property of both the JSON and the PDF. This helper LOCATES, nothing more: it never copies, quotes, or excerpts a matched file's content, and the artifact never claims the access request is satisfied — the controller still serves it from the located files themselves. Subject identifiers are read only from a `--subject-file`, never accepted inline on the command line, so no value can enter shell history; no value or masked/hashed form of an identifier reaches stdout, stderr, the JSON, or the PDF on any tested path, including error paths (a whole-branch review found and closed the one exception that had skipped the path scrub other error paths already used). Matching is exact canonical equality only, no fuzzy matching, so an OCR misread of a scanned identifier will not match even where a human reader would recognize it as the same value — a known Track A limitation the artifact states rather than papering over. Reuses breach's own scan chain (`extract`/`clean`/`detect_all`/`assess_reid_risk`); its file-discovery and canonicalization helpers are now a pure move into shared `pii_redactor/scan_common.py` (the module's own `path_spellings` helper was extended afterward, which is not the same claim), with breach's own test files passing unmodified. A fix that came out of this work — repr-escaped doubled-backslash path spellings slipping past the existing scrub in a real stdlib `OSError` message — also hardened breach's own failed-file reason. No HTTP endpoint by design ([record](decisions/2026-08-01-dsar-helper.md)). |
| Thai PDPA PDF report | Verified | Whitelisted PII-free renderer and end-to-end tests. A second Windows font defect was found and fixed on 2026-07-29: `FONT_CANDIDATES` carried exactly one Windows entry, a Sarabun path no Windows edition ships, so every Windows machine except the developer's fell through to Helvetica and rendered Thai as black boxes — the packaged exe bundles no font at all, so that was every packaged user. Leelawadee UI (shipped with every Windows edition) is now a second candidate, which in turn exposed a reportlab defect: `PDFTextObject.setRise`'s "optimize out r0 Ts r1 Ts" branch rewrites the emitted operator without storing the new rise, stranding runs of text above the baseline for any font that positions marks by offset rather than glyph substitution. Repaired in `thai_pdf_text._install_rise_fix()`, applied conditionally via a behavioural probe so an upstream fix stops the patch cleanly. Measured on "รายงานความเสี่ยงข้อมูลส่วนบุคคล" at 26pt: 15 distinct glyph baselines before, 11 after, and the visible span "ยงข้อมูลส" returns to the baseline. The underlying exposure — that the product shipped no font and depended on whatever the machine had — is closed: `pii_redactor/fonts/IBMPlexSansThaiLooped-Regular.ttf` (OFL-1.1, converted from the WOFF2 already vendored for the UI, container change only) is now the first candidate and ships in both the wheel and the exe, so a report renders identically wherever it was produced. Thai text shaping had been broken from the renderer's introduction until earlier the same day: reportlab draws glyphs in code-point order unless HarfBuzz shaping is enabled, so every tone mark stacking on an upper vowel was dropped or misplaced — 23 literals in this report, including its own title and the `ADDRESS` label. Fixed by enabling reportlab's built-in shaping (`uharfbuzz`, now a core dependency) and drawing through `pii_redactor/thai_pdf_text.draw_text`, which pairs an invisible real-character layer with the visible shaped glyphs so the page stays searchable. Verified against headless Chrome as a reference renderer: mark positions match on every test word. Two accepted limitations: copying a whole page repeats each shaped line, and `pdfminer`/`pdfplumber` cannot reconstruct stacked Thai marks from any producer (measured — headless Chrome output fails the same way), so extraction-based tooling should use the `.txt` export instead. |
| PDF redaction and preview | Hardening open | Historical text-layer and optional OCR positive paths are covered end to end and flattened. Current-source regressions clear traceback frames, exception chaining, arguments, ordinary custom attributes, and common built-in payload slots from swallowed pdfplumber, page-enumeration, dependency/encoding, and OCR-retry errors before fallback; retained-error tests cover the ordinary exception links and payload forms used by these paths. Python's read-only `BaseExceptionGroup` message/member shell cannot be overwritten safely and is instead dropped without logging/export after its members are recursively scrubbed. Current `WordBbox` values still have no authoritative source interval; the redactor does not consume `Entity.span`, instead globally substring-matching normalized `Entity.original_text` fragments to boxes and excluding one-character boxes. Exact repeated-value/decoy, negative-pixel, and missing-box behavior requires fresh acceptance. |
| Prompt-injection signals | Verified | Thai/English explicit rules plus a bounded normalization/intent layer; the five previously recorded bypasses are now passing regressions with ordinary-language negative controls. Canonical behavior remains warn-only. |
| Local HTTP authentication | Hardening open | A control-plane boot token protects shutdown/session disposal when configured, and current v2 separates that capability from the optional data-plane API key. Neither secret is returned to browser or Office code. When the local API key is unset, PII-bearing fixed-port endpoints still do not authenticate the process owning localhost port 8000; CORS and host validation are not server identity. The accepted direction is a native broker; hosted caller authentication remains a separate platform gate. |
| Public errors and audit logs | Hardening open | Current-source API process-audit callers use fresh non-authorizing operation UUIDs for sanitize, reidentify, and roundtrip; local disk/stdout regressions reject live session IDs, originals, and pseudonyms. Successful sanitize records `prepared` before publication, while a safe blocked-attempt record may remain after rejection. HTTP endpoint and pre-response-start JSON-render containment, fixed request-validation responses, direct stateless/local-session sanitize and restore translation, provider translation, PDF/OCR swallowed-error disposal, and worker handler/runner barriers sever retained ordinary exception graphs and common mutable payload fields before emitting fixed failures or continuing a fallback. Ordinary `ExceptionGroup` members are recursively scrubbed, while the read-only group shell is dropped without logging/export rather than corrupted; direct or grouped process signals may propagate. Otherwise-unhandled downstream HTTP exceptions that reach the endpoint decorator become a fixed 500 rather than exporting their detail; provider and PDF boundaries retain their explicit safe 5xx/422 translations. Internal seed audit rows use opaque `seed:<uuid4>` entity IDs, exact replay adds no row, and conflict errors carry no values; retained rows remain structural after `clear()`. Current HTTP v2 uses exact stable-code envelopes without exception messages, provider bodies, excerpts, mappings, or credentials. Some worker envelope/log paths still expose reduced exception type names, so worker cleanup remains separate provider-orchestration work. The process-audit schema retains the legacy `session_id` field name, operation-specific files still have no timed retention policy, and published 2.5.0 predates these current hardening changes. Official platform-visible logging remains open. |

## Compliance documents

| Deliverable | Status | Evidence / remaining gate |
|---|---|---|
| Standards mapping (ISO/IEC 20889 + มรด. 6:2566) | Documented | [docs/standards-mapping.md](standards-mapping.md), delivered 2026-08-01: a correspondence document, explicitly not a conformance claim. Grounded in what was actually readable: a publicly served ISO/IEC 20889 preview covering the complete terms clause (3.1-3.39), Clauses 1 through the start of 7.2, and the full table of contents — clauses 8-12 and the annexes are cited by title only, and the document says so; and the full 103-page มรด. 6:2566 PDF from the DGA standards site, read end to end, which defines no de-identification technique and references neither ISO/IEC 20889 nor any de-identification standard (the only ISO citations are 27001 and 11179) — so the มรด. mapping is at governance-practice level (classification, security/privacy dimension, breach-as-risk, the Data Agents processing-record duty), each row naming what the tool supports rather than claiming the practice is thereby satisfied. Every technique family the tool does NOT implement is listed by clause title, and the re-identification risk score is explicitly disclaimed as a heuristic, not a Clause-10 formal model. An adversarial review checked every ISO term number, every มรด. page citation, the negative claims, and every code claim against the repository before this row was written. |

## Integrations and storefronts

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Pathumma provider | Hardening open | Repeatable live completion and protected-roundtrip checks passed for the dated 2026-07 candidate; marker preservation remains quality telemetry because a generative response need not repeat every entity. The current outbound-policy source path postdates that live run and must be rerun against Pathumma. |
| AI for Thai TNER engine | Hardening open | The live parallel `words`/`POS`/`tags` shape and end-to-end `PER/LOC/ORG/DTM` mapping passed on 2026-07-23. Explicit TNER receives raw chunks, and current chunk exceptions can be skipped, allowing incomplete detection. Whole-request `ner_unavailable`/`ner_incomplete` behavior is not implemented or live-validated. |
| Browser extension | Hardening open | The exact 2026-07 unpacked candidate passed the recorded live Mask, backend-offline, closed-shadow Restore, consistency, and side-panel checks. That evidence remains historical and predates the current backend residual/v2/token-identity changes. Current source validates exact v2 health and operation schemas, rejects malformed/unsafe responses before a composer or copy write, and treats a stale namespaced token as unsafe. Authenticated backend identity, broker-backed lifecycle disposal, and fresh browser/package evidence remain open. Separately, raw text typed into an AI site's provider-controlled DOM can be observed before in-page Mask acts; the side panel is the stronger raw-entry boundary, and making it mandatory would require an owner product decision. |
| Desktop app | Hardening open | The published Windows `2.5.0` installer passed its exact installed-artifact checklist and Issue #69 revalidation; the [dated record](acceptance/2026-08-02-desktop-2.5.0-issue-69-run.md) remains valid for that artifact. It predates the current transaction/audit, outbound-policy, v2, and token-identity source changes. Current web and Rust hotkey paths validate strict v2 responses, reuse the prior session, retry fresh only for exact expiry/mode errors, and block unsafe clipboard writes. Authenticated broker work, session disposal, and new packaged/installed-artifact evidence remain open. |
| Microsoft 365 Add-in | Acceptance pending | The shared task pane, host adapters, memory-only session state, writeback guards, and Word-only release-manifest gate remain in source. Current Office code validates exact v2 health/operation DTOs, gates readiness only on `api_key_required`, accepts control-plane protection without asking JavaScript for that credential, and blocks malformed/incomplete/unsafe Apply, Insert, or Copy paths. Automated manifest/type/build/unit gates cover that source composition, but the historical local XML evidence predates the current backend changes. Packaged-backend/HTTPS-proxy composition remains open. The eight real-host/package gates remain unchanged: Word table and missing-key/provider/expired-session; Excel changed-value/formula cancellation and Pathumma Copy-only; PowerPoint unselected-content isolation, missing API 1.5, and Pathumma Copy-only; then the exact promoted three-host unified-package activation run. |
| CLI | Verified | Sanitize/report/receipt and end-to-end pipeline tests pass. Current source rescans before each outer provider invocation; self-retrying providers receive one outer validation before their single invocation. This guard has automated evidence, while the changed provider path still needs the fresh live run tracked under Protected provider roundtrip. |
| Demo playground | Hardening open | The exact 2026-07-23 browser candidate passed token/surrogate roundtrip, protected Pathumma, guard warning, responsive layouts, report download/open, and positive PDF preview/download checks; that dated evidence remains historical and predates the current backend residual/v2/token changes. Current source validates strict v2 health/operation responses and fails residual or malformed results closed. Shared provider-orchestration parity, exact PDF source-to-box alignment, and fresh browser/live evidence remain open. |
| Scanned-PDF OCR | Optional | Dated pre-current-candidate evidence covers a Python 3.13 full environment, focused OCR/PDF tests, and real Thai PaddleOCR inference. The extra remains excluded from the packaged exe and hosted core image; the current HTTP-v2/PDF composition has not rerun that real inference. |
| WangchanBERTa/union and semantic detector | Optional | Requires ML extras; never selected silently. |
| Fine-tuned NER engine | Optional | `AIGUARD_NER_ENGINE=finetuned` + `AIGUARD_FINETUNED_MODEL_DIR`; weights and dev-calibrated thresholds live outside the repo, reproducible from `training/` (seeded, gold-disjoint, contamination-checked). Certified as the heavyweight opt-in by blind reveal 4: overall F2 0.914, NAME precision 0.700 to 0.922 at recall 1.000 ([results record](decisions/2026-07-28-finetuned-ner-results.md)). The CRF remains the default on latency. |

## Platform and delivery

| Feature | Status | Evidence / remaining gate |
|---|---|---|
| Docker image | Hardening open | The 2026-07-24 image built/booted non-root with the offline CRF model baked in and measured 115,898,138 bytes. That evidence is historical: current source changed the entrypoint to `app.hosted`, made API-key/provider configuration mandatory, and reduced the route surface. Context exclusions and the exact smoke are encoded in tests/CI, but the changed image needs a fresh build/boot/route-surface run before its status can be promoted. |
| Resource profile | Hardening open | On the dated 2026-07 container candidate, a local workload under 1 CPU/1 GiB completed with a 177.2 MiB post-workload sample; token sanitize plus restore was 29.8 ms and PDF redact 256.5 ms. The current `app.hosted` image and HTTP-v2/token composition have not rerun that profile. The requested platform profile remains 1 vCPU, 1 GB RAM, 10 GB disk, no GPU; peak/p95 on official infrastructure is still open. |
| Queue worker operations (provisional) | Verified locally | Detect, sanitize, analyze, restore, and roundtrip contract tests pass through the internal version-1 envelope. Current sanitize/roundtrip source rejects residuals with a bounded, value-free `residual_pii` error and roundtrip rescans immediately before its direct provider call. This remains a local emulator/compatibility boundary, not the official participant delivery path. |
| Provisional queue transport/envelope | Deferred | The HTTP-poll transport and job envelope are retained for local failure/retry evidence only. The official participant guide selects an HTTP/FastAPI service behind a same-origin reverse proxy, so queue polling is not being promoted into the platform adapter. |
| Official platform HTTP adapter | Acceptance pending | Main now contains `app.hosted`, a generic strict-v2 candidate that requires API-key/provider configuration and hard-allows health, detect, analyze, guard, sanitize, reidentify, and roundtrip. Its sanitize/reidentify pair is stateful in process; roundtrip is request-transient. This is not confirmation that those are the official public routes or lifecycle. The separately versioned `aiguard-aift` port remains a v1 nginx-backed candidate with its own older six-endpoint contract and is out of scope for this campaign. Prefix behavior, public routes/auth, disposal, logs, deployment, and a real platform run remain externally gated. |
| Official AI for Thai deployment | Acceptance pending | GitLab sign-in and Maintainer rights in the team subgroup are verified. The separate `aiguard-aift` port has a vendored core slice, nginx adapter, and OCR-baked image. Its full local Docker phase (ก-ฌ checklist, fail-loud/503 failure modes, and service-level soak) is exact historical evidence for its pre-F09 core, not current fail-closed evidence. The deployment shell is locally prepared, but a separately authorized core re-vendor plus privacy/soak rerun is required before the owner-gated GitLab project creation/push. The platform acceptance run remains owner-gated. See the [tokenmind detector + port ADR](decisions/2026-07-28-tokenmind-detector-and-aift-port.md). |
| Platform LLM endpoint | Acceptance pending | The platform issued an endpoint, model identifier, and secret out of band. No secret or account identifier is stored here. Request/response compatibility and authentication placement were proven against the live gateway for the dated candidate: the 2026-07-28 acceptance run passed 9/9 with two checks calling thaillm-8b directly (`tokenmind.completion`, `tokenmind.protected_roundtrip`), and the separate v1 port reached the same model through nginx key injection, including a 222-request light soak with no 5xx. All of that evidence predates F09; neither the sibling nor the main repository's changed outbound path has been rerun live. The model was separately scored as a detector on gold v4 ([ADR](decisions/2026-07-28-tokenmind-detector-and-aift-port.md)). Quota, acceptable-use and logging policy, timeout ownership, and a roundtrip originating from platform infrastructure rather than a developer machine still require confirmation and acceptance. |
| Retry/failure emulator | Verified locally | The repeatable local runner passes duplicate/conflict, failed submit, same-process provider idempotency, malformed/version/size, provider-timeout, handler-crash, concurrency, and honeytoken cases. It does not claim cross-process exactly-once or official ack/nack semantics. |
| Load/soak and official failure acceptance | Blocked externally | Meaningful platform soak, restart behavior, platform-visible log/resource evidence, and retry ownership require external contract/platform evidence. An owner-gated GitLab project creation/push and a separately authorized sibling core sync are additional prerequisites. |
| Version/tag/release pipeline | Verified | v2.5.0 is published as Latest from exact merge commit `24914ab`. PR, main CI, cross-platform smoke, release metadata preflight, Windows/macOS/Linux builds, checksums, and provenance all passed. All 10 files listed in `SHA256SUMS` matched locally and verified against GitHub build provenance. The exact Windows installer upgraded the registered app to 2.5.0; binary/API versions agreed; token, surrogate, and fake-provider roundtrips passed; and closing Desktop released its sidecar and port. The unpublished v2.4.1 draft/tag remains superseded and is not moved or reused. Distribution is the release asset itself; the package-manager manifests were removed on 2026-07-29 ([record](decisions/2026-07-29-store-distribution-and-signing.md)). |

## Internal-plan differences resolved here

- `block_on_guard=true` appeared in a working design but is not part of the
  submitted proposal or current API contract. Warn-only is the accepted design.
- Local `/api/reidentify` remains stateful by design. Hosted HTTP roundtrip is
  the preferred restoration flow because it consumes the mapping within one
  request and does not export it.
- The hosted service does not claim raw PII remains on the user's device.
- Detection accuracy remains the roadmap's declared normal Track A priority.
  The owner-approved eight-phase privacy/security/correctness hardening campaign
  is an explicit temporary exception, not a claim that Track A is complete.
  Remaining Office and platform items are acceptance gates tracked above, not
  deferred scope.
