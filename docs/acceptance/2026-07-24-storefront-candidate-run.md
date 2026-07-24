# Storefront candidate follow-up — 2026-07-24

Candidate runtime: product `2.5.0`. Clean release-preparation commit
`e91a124168895464b7159f543bedbc115e4d1c54` passed the repeatable non-quota
acceptance gates. The live-provider supplement was captured earlier from the
same runtime changes with a dirty working tree and remains identified
separately below.

This record contains outcomes, counts, and references only. It contains no raw
request text, mappings, provider response bodies, credentials, or screenshots.

## Repeatable HTTP and live-provider acceptance

Clean evidence:
`artifacts/acceptance/acceptance-20260723T182256Z.json` (gitignored), reporting
version 2.5.0, the exact commit above, `git_dirty: false`, and **7 pass, 0 fail,
0 blocked** for health, demo enablement, fake protected roundtrip, guard
warning semantics, PDPA PDF, text-layer PDF redaction, and non-PDF rejection.

Live supplement:
`artifacts/acceptance/acceptance-20260723T180919Z.json` (gitignored).

The runner completed with **11 pass, 0 fail, 0 blocked**:

| Gate | Result |
|---|---|
| API health and demo enablement | Pass |
| Fake protected roundtrip | Pass |
| Prompt-injection warning semantics | Pass |
| PII-free PDPA report | Pass |
| Text-layer PDF redaction, previews, and flattened output | Pass |
| Non-PDF rejection | Pass (400) |
| Pathumma completion | Pass |
| Pathumma protected roundtrip | Pass |
| Live TNER tagging | Pass |
| Live TNER pipeline mapping | Pass |

The Pathumma protected-roundtrip result reported an unused-token warning when
the generative response omitted a placeholder. That is expected warning
semantics, not a restoration success claim for an omitted token.

## Browser extension

Chrome checks on the candidate completed the basic synthetic Mask flow on each
declared site: ChatGPT, Claude, Gemini, Grok, Perplexity, and GLM/Z.ai. The
candidate also showed a blocking backend-offline result and preserved same
session token consistency across two unsent turns.

This follow-up does **not** record a new generic side-panel Mask run, a new
Restore/closed-shadow inspection, or per-site URLs/screenshots. The generic
side-panel and browser Restore evidence therefore remains the 2026-07-23
carry-forward record; it must not be represented as a fresh 2.5.0 run.

## Playground, report, and PDF

The basic playground interaction was exercised on the candidate. The HTTP
runner verified report generation and the text-layer PDF API path, including
preview payloads and flattened output. Headless browser regressions now cover
the page wiring from successful report/PDF responses to safe download names.

Those headless checks do not drive a browser file chooser or prove that a
download opened. Browser report/PDF download-open, visual redaction coverage,
oversized-upload, OCR-unavailable, and temporary-file observations remain
carry-forward evidence from the 2026-07-23 storefront run.

## Installer and publication

Tag `v2.5.0` points to merge commit
`24914ab54fc8e8338ca529dd5c20a79f51d749c0`. PR CI, main CI,
cross-platform smoke, release metadata preflight, and the Windows/macOS/Linux
release build completed successfully in GitHub Actions. The 10 files listed in
the generated `SHA256SUMS` matched their downloaded bytes, and all 10 verified
against GitHub build provenance.

The downloaded Windows installer had SHA256
`2d4780f2ebc2e4555ebe99bbc56aca340543411cc9430d960395095e7684eb7e`
and product/file version 2.5.0. Its silent upgrade exited successfully and
registered AI Guard 2.5.0. The installed binary launched a sidecar reporting
health version 2.5.0; token and surrogate sessions restored exactly; the fake
provider roundtrip restored exactly while provider-visible text excluded the
synthetic originals; and closing Desktop exited the app and released port
8000.

The release was published as GitHub Latest on 2026-07-24 local time. Public
`latest.json` and ranged installer download checks returned successful HTTP
responses before the packaging metadata was updated.

The Extension, Playground, report, and PDF production sources are unchanged
from the 2026-07-23 accepted release path, apart from the synchronized Extension
manifest version. Accordingly the previous real-browser artifact evidence is
retained as lineage evidence, while this record identifies exactly which
interactions were repeated on the 2.5.0 candidate.
