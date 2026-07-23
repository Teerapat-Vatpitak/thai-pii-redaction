---
name: aiguard-change-workflow
description: Plan, implement, verify, document, and prepare AI Guard repository changes. Use for feature work, fixes, refactors, acceptance work, documentation synchronization, versioning, release preparation, or GitHub handoff in thai-pii-redaction; also use when the user says to continue the project, assess what comes next, or split AI Guard work across agents.
---

# AI Guard Change Workflow

Use one evidence-driven loop for every repository change.

## 1. Establish scope and truth

1. Inspect `git status`, branch/upstream, and the requested files or failing
   path. Preserve unrelated changes.
2. Read only the current-state sources needed:
   - `docs/project-status.md` for evidence and blockers;
   - `ROADMAP.md` for order and deferrals;
   - `docs/architecture.md` for trust boundaries;
   - `docs/acceptance/README.md` for real-path gates;
   - `docs/release-process.md` for version/tag/release work.
3. Trace the real caller-to-core path before proposing a new implementation.
   Reuse `pii_redactor/` and the existing API instead of duplicating detection,
   vault, or provider logic in a storefront.

## 2. Classify the lane

Choose the smallest affected lane: core/API, extension, desktop, Office,
playground/PDF, AI for Thai worker/platform, documentation, or release.
Separate functional implementation from real-host/live-provider/deployment
acceptance. Do not expand benchmark or accuracy work while an earlier
functional gate in `ROADMAP.md` remains open unless the user explicitly changes
priority.

When the user explicitly requests parallel agents, delegate bounded read-only
work to `aiguard_explorer`, `aiguard_reviewer`, or
`aiguard_docs_auditor`. Keep implementation ownership with one agent unless
file scopes are disjoint.

## 3. Define done before editing

State the caller-visible outcome, affected trust boundary, failure behavior,
tests, and documentation evidence. Distinguish:

- automated/mocked verification;
- local runtime or packaged-runtime verification;
- real browser/Office host acceptance;
- live Pathumma/TNER acceptance;
- official AI for Thai deployment acceptance.

Never promote a result from one level to a stronger level.

## 4. Implement narrowly

- Preserve in-memory mapping and outbound leak guards.
- Keep raw PII and mappings out of logs, errors, screenshots, and artifacts.
- Use synthetic fixtures.
- Keep optional ML/OCR engines explicit and fail clearly when selected but
  unavailable.
- Preserve source spans and PDF bbox coordinate integrity.
- Do not broaden CORS, credentials, public endpoints, release hosts, or platform
  claims without a requirement and tests.
- Do not bump `VERSION` during ordinary development or acceptance.

## 5. Verify by affected lane

Read [references/check-matrix.md](references/check-matrix.md), run focused
checks during iteration, then run the complete gate for every affected lane.
Run `git diff --check` and review the final diff regardless of lane.

If a check is skipped, xfailed, unavailable, or blocked, report why. A skipped
optional dependency is not a pass for that optional feature.

## 6. Synchronize current truth

Update current-state documentation when behavior, limitations, evidence, or
roadmap gates change. Keep acceptance boxes open until the exact delivery path
passes. Do not rewrite historical ADRs to match new behavior.

For platform work, label unissued envelope, resource, timeout, retry, logging,
and registry details as unknown or provisional. For Office, keep the unified
release manifest Word-only until Excel and PowerPoint host gates pass.

## 7. Publish only when requested

Before commit/push/PR:

1. separate unrelated user files;
2. group changes into reviewable commits;
3. rerun release-relevant checks from the committed tree;
4. push a feature branch and use a PR into `main`;
5. wait for CI and inspect real logs before merging;
6. delete only branches proven merged and without open work.

Do not deploy, release, tag, merge, or delete branches from a general
implementation request.
