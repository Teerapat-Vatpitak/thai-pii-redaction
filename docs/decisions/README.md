# Design decisions

Why the code looks the way it does. These are working documents kept for the
record, not polished specification — most are written in Thai, and each is dated
by when the decision was made rather than continuously maintained.

| Document | What it decides |
|---|---|
| [2026-07-20 session handoff](2026-07-20-session-handoff.md) | State after v2.3.0 shipped: what changed, what bit us, what is still open |
| [2026-07-19 audit v2 findings](2026-07-19-audit-v2-findings.md) | Full-repo audit before v2.3.0: 59 findings with evidence, and which are closed |
| [2026-07-17 roadmap v2](2026-07-17-roadmap-v2-design.md) | Current plan: GitHub-only distribution, the Rust rewrite killed, re-audit before tagging |
| [2026-07-15 NER engine strategy](2026-07-15-ner-engine-strategy-decision.md) | Why thainer-CRF is the default and WangchanBERTa/union stay opt-in |
| [2026-07-13 Thai PII recall benchmark](2026-07-13-thai-pii-recall-benchmark-design.md) | How detection recall is measured |
| [2026-07-10 post-competition roadmap](2026-07-10-post-competition-longterm-roadmap.md) | The original three-horizon plan (superseded on ordering by roadmap v2) |
| [2026-07-07 UI redesign](2026-07-07-ui-redesign-aiguard-design.md) | The design-token system shared by the extension and desktop app |

Superseded documents and per-task implementation plans are intentionally not
published — they were written for an AI coding workflow and carry no value for a
reader of this repository.
