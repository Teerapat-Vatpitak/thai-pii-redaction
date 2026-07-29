# AGENTS.md

Use this file for durable repository rules. Load detailed architecture, status,
acceptance, or release documents only when the task needs them.

## Operating truth

Resolve conflicts in this order:

1. running code and automated contract tests;
2. `docs/project-status.md`, `docs/architecture.md`, and `ROADMAP.md`;
3. accepted ADRs under `docs/decisions/`;
4. historical plans, handoffs, proposals, and competition artifacts.

Start non-trivial work by checking `git status`, the current branch, the
relevant current-state document, and the affected execution path. Preserve
unrelated user changes and untracked files.

## Delivery loop

This repository does not use pull requests for its own work. Work happens on a
short-lived branch, CI runs on every branch push, and a green run is squashed
into `main` as a single commit. Never commit directly to `main`.

Run the loop end to end without stopping to ask between steps:

1. branch from `main`;
2. implement, writing tests first for new behavior;
3. push, and wait for every CI job to pass — not most of them;
4. squash into `main`;
5. report in three lines: what changed, why, and what the evidence was.

Stop and ask the owner in exactly four cases: a fork in the road that changes
product direction; a decision that meets the ADR bar below; an outward-facing
action such as deploying, submitting to a store, creating a public repository,
or sending anything to a third party; or a measured regression you cannot
explain.

A change that meets the ADR bar also gets an independent review from a subagent
running in a separate context before it lands. Verify every claim that review
makes against the code before acting on it; reviewers have been confidently
wrong in this repository before.

## Product boundaries

- Keep one core under `pii_redactor/`; storefronts call the shared FastAPI/core
  path and must not implement separate detection, vault, or provider logic.
- Local AI Guard keeps the pseudonym-to-original mapping in memory. Browser and
  Office clients may hold `session_id`, never the mapping or credentials.
- Hosted AI for Thai processing is stateless by default. Do not claim that raw
  PII stays on the user's device in the hosted path.
- Scan external-AI outbound text for structured and text-based PII and fail
  closed on a residual leak.
- Treat PDPA Section 26 and prompt-injection findings as warn/report signals,
  not automatic blocking or redaction.
- Prefer recall over precision, but keep type labels honest and preserve source
  spans.
- Preserve PDF bbox coordinates. Do not add OCR deskew unless redaction
  coordinates are transformed with it.
- Never place raw PII, mappings, credentials, provider bodies, or restored
  answers in logs, screenshots, fixtures, acceptance artifacts, or errors.
- Use synthetic PII for tests and demonstrations.

## Current delivery order

This file carries rules, not status. Ordered tracks live in `ROADMAP.md` and
current blockers in `docs/project-status.md`; read those before starting work
rather than trusting a summary here that ages.

Two lanes ship in parallel and share one core. The local lane (extension,
desktop, CLI, Office add-in) keeps everything on the user's machine. The hosted
lane is an HTTP/FastAPI adapter behind the AI for Thai reverse proxy, built to
accept a wider surface than local does — more input kinds, more call shapes,
more LLM providers. Keep that adapter replaceable, and never invent limits or
policies the participant guide has not confirmed. The queue worker stays a
local failure/retry emulator, not a delivery path.

## Environment and commands

Windows PowerShell is the primary local shell. Set UTF-8 before Python and call
the repository virtual environment directly:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Use the repository skill `$aiguard-change-workflow` for task routing and the
complete check matrix, including the JS, Rust, Office, and version gates. Run
focused tests while iterating and the affected lane's complete gate before the
branch lands.

Optional dependencies stay optional:

- `requirements-web.txt`: FastAPI/uvicorn
- `requirements-ml.txt`: WangchanBERTa/union and semantic detection
- `requirements-ocr.txt`: scanned/hybrid PDF OCR

Do not silently fall back when an explicitly selected optional engine is
unavailable.

## Change and review rules

- Use `rg`/`rg --files` for discovery and `apply_patch` for manual edits.
- Add or update tests for behavior changes, including failure and privacy paths.
- Keep real-host, live-provider, and packaged-runtime acceptance distinct from
  mocks and schema validation. Never mark a checkbox from weaker evidence.
- Update current-state docs when behavior, status, limitations, or gates
  change. Do not rewrite historical ADRs to describe the present.
- Review the final diff for PII exposure, duplicated core logic, stale claims,
  version drift, and unrelated changes.
- Committing, pushing, and squashing into `main` are part of the loop above and
  need no separate approval. Releasing, deploying, publishing, operating
  desktop applications, and anything that leaves this machine still require the
  owner's word.

## Performance gate

A change that touches `pii_redactor/` or `app/` runs
`scripts/measure_perf.py` before it lands, and the commit carries the numbers.
The script measures detect, sanitize, restore, and PDF redaction in-process
against `perf/baseline.json`.

The budget is 20% on time and 15% on resident memory. Past either, the commit
either explains what the slowdown buys or the change does not land. Moving the
baseline is allowed when the change is deliberate; the reason goes in the same
commit.

This gate runs locally, not in CI. Timings on a shared runner are too noisy to
gate on, and a gate that fires at random is a gate everyone learns to ignore.

## Documentation discipline

- An ADR is for decisions that are expensive to reverse: architecture, a public
  contract, or destroyed data. A decision that reverses by deleting a file
  belongs in a commit message, not a new document.
- Update a document when the thing it describes changes, not when work happens
  near it. `CLAUDE.md` changes when the code map does, `docs/project-status.md`
  when an acceptance state crosses a line, `ROADMAP.md` when a track changes
  state.
- Documentation ships in the same commit as the change that made it true. A
  commit that touches only documents, written to describe work already
  committed, should not exist. Work whose product is the document itself is the
  exception.
- `CHANGELOG.md` is written while preparing a release, not once per change.
- A superseded ADR is left as it was; `docs/decisions/README.md` carries the
  status.

## Version and release

`VERSION` is the product source of truth. Use
`scripts/bump_version.py <X.Y.Z>`; do not hand-edit synchronized version
targets. The fallback literal in `app/server.py` must be updated deliberately
at release.

Development and acceptance work does not bump the version. Follow
`docs/release-process.md` before creating a tag or publishing a release.

## Definition of done

A change is complete only when the caller-facing path works, relevant positive
and failure tests pass, privacy/trust boundaries remain intact, current-state
documentation is honest, version checks pass when applicable, and
`git diff --check` is clean. Report skipped, blocked, or real-host-only gates
explicitly.

## Reference map

- `docs/README.md`: documentation precedence and index
- `docs/architecture.md`: architecture and trust boundaries
- `docs/project-status.md`: current evidence and blockers
- `ROADMAP.md`: ordered delivery gates
- `docs/acceptance/README.md`: real-path acceptance
- `docs/platform/ai-for-thai.md`: hosted integration contract
- `docs/release-process.md`: version, tag, and release workflow
