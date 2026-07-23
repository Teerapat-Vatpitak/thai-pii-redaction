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

Make committed features work on their real delivery path before expanding the
benchmark or tuning accuracy. Current status and blockers live in
`docs/project-status.md`; ordered gates live in `ROADMAP.md`.

The Microsoft 365 lane is Word -> Excel -> PowerPoint. Keep the release
manifest Word-only until Excel and PowerPoint real-host acceptance passes.
Local XML manifests are acceptance transports, not release evidence.

The AI for Thai job envelope and transport remain provisional until the
platform issues the official account and specification. Keep the platform
adapter replaceable and do not invent confirmed limits or policies.

## Environment and commands

Windows PowerShell is the primary local shell. Set UTF-8 before Python and call
the repository virtual environment directly:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Common component checks:

```powershell
npm run test:js
cd desktop\src-tauri; cargo test
cd office-addin; npm run validate:manifest; npm run typecheck; npm test; npm run build
.\.venv\Scripts\python.exe scripts\check_version.py
```

Use the repository skill `$aiguard-change-workflow` for task routing and the
complete check matrix. Run focused tests while iterating and the affected
lane's complete gate before handoff.

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
- Do not commit, push, merge, release, deploy, delete branches, or operate
  desktop applications unless the user requests that action.

## Version and release

`VERSION` is the product source of truth. Use
`scripts/bump_version.py <X.Y.Z>`; do not hand-edit synchronized version
targets. The fallback literal in `app/server.py` must be updated deliberately
at release. Update packaging manifests only after the release publishes
`SHA256SUMS`.

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
