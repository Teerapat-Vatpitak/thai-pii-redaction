# Documentation map

This directory separates current operating truth from historical decisions.
When documents disagree, use the following precedence:

1. running code and automated contract tests;
2. the current-state documents listed below;
3. accepted architecture decision records (ADRs); and
4. old proposals, plans, handoffs, and competition artifacts.

An ADR explains why a decision was made at a point in time. It is not a live
status page and does not silently override a newer current-state document.

## Current-state documents

- [Architecture and trust boundaries](architecture.md) - the core, storefronts,
  deployment contexts, and source layout.
- [Project status](project-status.md) - the feature acceptance matrix and known
  external blockers.
- [AI for Thai integration](platform/ai-for-thai.md) - hosted service shape,
  resource profile, unknown platform fields, and acceptance checklist.
- [Release process](release-process.md) - version, tag, draft release, packaging,
  and hotfix rules.
- [Functional acceptance](acceptance/README.md) - repeatable Extension, Desktop,
  Playground, PDF, Pathumma, and TNER gates.
- [Versioning proposal](versioning-proposal.md) - why the existing product line
  remains monotonic while a new AI for Thai service may start at `0.1.0`.
- [Roadmap](../ROADMAP.md) - ordered delivery gates.
- [Install from source](install-from-source.md) - local developer/runtime setup.

## Product and distribution

- [Browser extension](../extension/README.md)
- [Desktop app](../desktop/README.md)
- [Store listing](store/listing.md)
- [Extension permissions](store/permissions-justification.md)
- [Privacy policy](store/privacy-policy.md)
- [Packaging manifests](../packaging/README.md)

## Historical records

- [Decision record index](decisions/README.md)
- [Audit v2 findings](decisions/2026-07-19-audit-v2-findings.md)
- [Platform contract ADR](decisions/2026-07-22-platform-integration-contract.md)

Files outside the public repository that contain submitted forms, signatures,
member contact details, or working competition notes are not copied here. Their
commitments are summarized without personal data in the current-state docs.
