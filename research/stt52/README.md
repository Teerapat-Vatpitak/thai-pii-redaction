# STT52 research evidence

Paper title:

> Negative Controls and Complementary Span Metrics for Thai PII Redaction

The study stays frozen at gold-v3 and system commit
`d93d10b17be6783d5c684cb47f25d4156ed6fb4b`.

## Evidence

- `evidence/gold-v3-crf.json`: main system score, document bootstrap CI,
  shared-11 score, ADDRESS audit, and NER chunk counts.
- `evidence/gold-v3-crf-predictions.jsonl`: safe offsets and types only.
- `evidence/gold-v3-tokenmind-thaillm-8b.json`: external baseline score from
  the same scorer.
- `evidence/gold-v3-tokenmind-thaillm-8b-predictions.jsonl`: safe offsets and
  types only.
- `second-human-v1.json`: blind sample for an independent human reviewer.

Prediction files do not store document text or entity values.

## Main result

The unrestricted system view reports TP 561, FP 378, FN 80, and F2 0.801
(95% document bootstrap CI 0.770-0.829). The shared-11 view excludes 163
out-of-scheme predictions and reports F2 0.840 (0.811-0.866).

All 272 attempted NER chunks succeeded. No chunk was skipped.

## External baseline

The hosted Tokenmind `thaillm-8b` baseline reports TP 609, FP 72, FN 32, and
F2 0.938 (0.914-0.959). Its shared-11 F2 is 0.941 (0.916-0.961), with eight
out-of-scheme predictions.

The response cache is keyed by provider, prompt, and document text. Of 252
gold-v3 documents, all 252 synthetic documents were sent in a fresh run and
all requests succeeded. The final score was then rebuilt offline from all 252
cached responses. Eight responses had no usable rows, and two returned values
could not be located verbatim.

## Human agreement

Agreement is not available yet. A real second human must finish
`second-human-v1.json`. Do not add an agreement number to the paper before
that review is complete.
