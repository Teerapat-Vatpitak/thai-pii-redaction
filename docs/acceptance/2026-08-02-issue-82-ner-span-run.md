# Issue #82 Thai NER span regression evidence

- Evidence finalized (UTC): `2026-08-02T11:46:17Z`
- Base checkout commit: `650cdd5fe7d7448efb701b0ccf9bfcf6918951f2`
- Python: `3.13.14`
- PyThaiNLP: `5.3.4`
- python-crfsuite: `0.9.12`
- NER engine: default `thainer` (`AIGUARD_NER_ENGINE` unset)
- Fixture: `examples/prompts/02_medical_consult.txt`

The fixture and all additional probes in this record are synthetic. This
record contains offsets and labels only; it does not contain selected text,
token mappings, pseudonyms, clipboard contents, provider responses, or local
absolute paths.

## Reproduction and final behavior

The underlying CRF diagnostic reproduced the reported model output:

- `PERSON` span `[32,55]`
- nested `LOCATION` span `[59,62]`

The shared product path on the same checkout then produced these bounded
entities:

- `NAME` span `[49,62]`
- `LOCATION` span `[149,165]`
- `PHONE` span `[185,197]`

`detect_tb()` and `detect_all()` both preserved exact source slicing for every
returned entity. The nested `LOCATION` was absent from the `NAME` span.

| Test case | Result | Evidence |
|---|---|---|
| `NER-82-01` raw default CRF diagnostic | PASS | The two reported raw spans were reproduced on the pinned synthetic fixture. |
| `NER-82-02` `detect_tb()` boundary and label | PASS | One complete `NAME` span; no nested `LOCATION`; source slices matched metadata. |
| `NER-82-03` `detect_all()` aggregate boundary | PASS | The corrected `NAME` survived aggregate deduplication; the independent phone and hospital-location spans remained. |
| `NER-82-04` `/api/detect` | PASS | HTTP 200; corrected offsets and labels matched the core path. |
| `NER-82-05` `/api/sanitize` and `/api/reidentify` | PASS | HTTP 200; the name was absent from masked output and the cleaned input restored exactly with no leftover pseudonyms. |
| `NER-82-06` `SessionService` token round trip | PASS | Corrected entity metadata was registered and the original synthetic fixture restored exactly. |
| `NER-82-07` multiline cue candidate | PASS | A cross-line candidate was rejected by shared hygiene/finalization and the cue pass supplied the full synthetic name. |
| `NER-82-08` location-like surname | PASS | The two-token synthetic name stayed one `NAME`; no inner `LOCATION` was created. |
| `NER-82-09` true location after a name | PASS | The synthetic province value remained an independent `ADDRESS` after both name cases. |
| `NER-82-10` Thai combining-mark offsets | PASS | The full synthetic name span and source slices remained exact. |

The issue was reproduced at the raw model-output stage, but not as a
caller-facing defect on the latest `main`: the existing `_name_hygiene()` and
name-cue path already reject the malformed candidate and recover the complete
name. This branch adds regression coverage for that behavior; it does not add
a value-specific rule, change the NER engine, change thresholds, or change
entity IDs, vault behavior, or restore semantics.

## Detection-quality comparison

The same default-CRF commands were run before and after the branch changes.
Generated JSON reports stayed untracked under `benchmark/reports/`.

| Corpus | Documents | Gold spans | Precision | Recall | F1 | F2 | Coverage recall | Exact-boundary recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Gold v4 | 252 | 648 | 0.8143 | 0.9475 | 0.8759 | 0.9175 | 0.9439 | 0.7932 |
| Synthetic seed 42 | 200 | 600 | 0.9375 | 1.0000 | 0.9677 | 0.9868 | 0.9856 | 0.9700 |

The before and after reports were byte-equivalent in all aggregate metrics:
there were no changed benchmark predictions and no measured trade-off. Gold
`NAME` precision/recall/F1/F2 were `0.9543/0.9447/0.9495/0.9466`; gold
`ADDRESS` precision/recall/F1/F2 were `0.8657/1.0000/0.9280/0.9699`.
`LOCATION` is not a gold-v4 label, so standalone LOCATION precision/recall
are not claimed; the two targeted location-boundary cases above are the
appropriate regression evidence for this issue.

## Performance

The committed baseline run measured `detect 5.46 ms`, `sanitize 10.42 ms`,
`restore 0.32 ms`, `pdf_redact 69.79 ms`, and sampled RSS `152.4 MiB`.
The stable post-change run measured `detect 5.42 ms`, `sanitize 9.87 ms`,
`restore 0.32 ms`, `pdf_redact 70.18 ms`, and sampled RSS `152.9 MiB`;
`scripts/measure_perf.py` reported `within budget`.

One intervening local timing run reported rounded `sanitize` and `restore`
values just over the 20% timing tolerance while no runtime source had changed.
The immediate repeat passed within budget; this is recorded as environment
timing noise, not a product regression, and the baseline was not moved.

## Privacy and scope

- No raw selected text, mappings, pseudonyms, clipboard contents, provider
  responses, secrets, credentials, generated benchmark reports, model files,
  or ONNX artifacts were committed.
- No `blind-v1` data was read or used.
- No runtime behavior changed on this branch; the fix under test remains the
  existing general hygiene/cue implementation already present on `main`.
