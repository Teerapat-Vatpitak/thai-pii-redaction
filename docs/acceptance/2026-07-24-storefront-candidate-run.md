# Storefront candidate follow-up — 2026-07-24

Candidate runtime: product `2.5.0`, code commit
`ad1a11d8f2299ea3ec52f9166cae9b09d440d542`. The captured HTTP evidence marks
the working tree dirty, so this is **provisional candidate evidence**, not
release-commit evidence. Reproduce release gates from a clean candidate
checkout before tagging or publishing.

This record contains outcomes, counts, and references only. It contains no raw
request text, mappings, provider response bodies, credentials, or screenshots.

## Repeatable HTTP and live-provider acceptance

Evidence: `artifacts/acceptance/acceptance-20260723T180919Z.json` (gitignored).

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

## Remaining candidate evidence

- Repeat the applicable release checks from a clean checkout, because the
  recorded HTTP run was dirty.
- If release policy requires fresh browser artifact evidence, re-run the
  report/PDF download-open and visual inspection manually; this record does
  not promote the headless tests into real-browser acceptance.
