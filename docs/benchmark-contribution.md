# Contributing to the benchmark

Detection accuracy in this project is measured rather than asserted, which only
works while the corpus behind the measurement stays trustworthy. That makes the
gold set the one part of the tree that is governed instead of open: every value
in it is fabricated, every label follows
[the annotation guidelines](annotation-guidelines.md), and every change lands
with a record of who decided what.

A document that probes a detector behavior nothing currently covers is one of
the most valuable contributions this repository can receive. This page is the
route for offering one.

## Before writing anything

Read [annotation-guidelines.md](annotation-guidelines.md) end to end, including
the slice contract for the slice you have in mind. The guidelines carry
adjudicated precedents — cases two reviewers already argued about — so a
proposal that contradicts one will be sent back to it.

Then read the docstring at the top of `benchmark/gold.py`. It states the current
set version, the two layers, and why the `negative` slice exists. Composition
figures live there and in generated reports, never in hand-typed prose.

**The blind set is off limits.** `benchmark/data/blind-*.enc` exists to measure
whether gold-set tuning generalizes, and reading it destroys that. Do not
decrypt it, print it, or ask an assistant to. Contributions are never sourced
from it, and its scoring protocol
([2026-07-28](decisions/2026-07-28-blind-set-protocol.md)) is maintainer-only.

## The route

1. **Open a benchmark issue first** using the "Benchmark document proposal"
   form. Put the document, its markup, its slice, and the behavior it measures
   in the issue. Agreement on slice and labels happens there.
2. **Then open a pull request** against `benchmark/data/gold.jsonl` once the
   labeling is settled. A PR that arrives before the issue usually has to be
   relabeled after review, which wastes your work rather than the reviewer's.

A label challenge against an existing document follows the same route: the
issue argues the rule, and the PR applies the outcome.

## What a document looks like

`benchmark/data/gold.jsonl` holds one JSON object per line with four fields:

```json
{"doc_id": "nc07", "slice": "name_no_cue", "layer": "balanced", "annotated": "ผู้จัดการฝ่ายขาย [[NAME|วิชัย ประสงค์ดี]] อนุมัติใบเบิก..."}
```

`annotated` carries the document with entities marked inline as
`[[TYPE|value]]`. `parse_gold()` strips the markup and derives the spans, so
the text and its annotation are physically incapable of drifting apart — which
is why the markup is the submission format and a separate span list is not
accepted. A `negative` document carries no markup at all.

`doc_id` is unique across the set and conventionally short. `layer` follows the
slice (`SLICE_LAYERS` in `benchmark/gold.py` is the authority); `negative` is
its own layer because it is scored differently.

## Validate locally before opening the PR

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests/test_benchmark_gold.py
```

That file is the real gate, and it checks more than syntax: span round-trip,
unique `doc_id`, slice/layer agreement, every type reaching a reportable n,
mod-11 / Luhn validity for `THAI_ID` and `CREDIT_CARD`, no PII value reused
across documents, the `name_no_cue` cue ban, the `long_form` chunk-boundary
guarantee, the `student_id_varied` one-axis rule, and the `negative` slice
carrying no labels.

Then score the set so the effect on the reported numbers is visible in the PR:

```powershell
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m benchmark --source gold
```

Reports are written under `benchmark/reports/`, which is gitignored on purpose.
Quote figures from a run the reviewer can reproduce; never commit a report or
paste a number that has no generated source behind it.

## Change control

A change to `benchmark/data/gold.jsonl` bumps the set version in
`benchmark/gold.py`'s docstring and lands with its own authoring or
adjudication record under `docs/decisions/`. Published numbers name the version
they were measured on, so a silent edit would strand every figure already in
print.

Adjudication is review-then-fix: reviewers list findings against the
guidelines, and fixes are applied only for rule violations. A document is never
edited to make the current detector look better — that inverts what the set is
for, and the resulting number stops meaning anything.

## What gets turned away

- Real documents, redacted real documents, or real documents with the names
  swapped. Shape-preserving fabrication is the standard, and there is no
  exception for "it was already public".
- Values reused across documents, which quietly turns a recall measurement into
  a memorization measurement. The `bank_phone` pair is the single recorded
  exception and is test-exempted.
- Volume for its own sake. The set is a diagnostic; a document earns its place
  by measuring something the existing slices cannot.
- Anything in the `negative` slice carrying a maximal token of exactly 13
  digits, even a checksum-invalid one — it reads as a national-ID look-alike and
  turns a clean negative into a detector-behavior probe.

## Contributions that are not documents

Scorer changes, new slices, and new entity types are design changes rather than
data changes: open a proposal issue, and expect the discussion to start from
what the change makes measurable that is not measurable today. The LLM-detector
lane (`benchmark/llm_strategy.py`) accepts new providers, but its cache stores
parsed `(type, value)` pairs only — never a provider's response body — and that
constraint is not negotiable in a PR.
