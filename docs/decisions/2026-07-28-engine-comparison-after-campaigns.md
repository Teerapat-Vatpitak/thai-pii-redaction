# Engine comparison after accuracy campaigns 1-2 (Track A step 4)

- Date: 2026-07-28
- Status: decided — the offline CRF stays the default; union/WangchanBERTa
  remain opt-in. Supersedes the *recommendation* direction of the
  [2026-07-15 NER engine strategy ADR](2026-07-15-ner-engine-strategy-decision.md)
  (whose measurements were correct for the detector as it existed then).

## Measurement

All four strategies scored on gold v4 with the shared scorer, same machine,
CPU-only, model load excluded from the clock (`ml` extras installed for this
run; they remain excluded from the packaged exe and hosted core image).
Campaigns 1-2 (PRs #90, #91, #93) are in the baseline — that is the point:
the question was whether the heavyweight engines still add anything after the
cue/coalescing work.

| strategy | wall (252 docs) | recall | precision | F2 | coverage | exact | negative FPs | clean rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **crf** (default) | **1.1 s** | 0.935 | 0.813 | **0.908** | 0.924 | 0.769 | 33 | 0.400 |
| wangchanberta | 29.3 s | 0.849 | 0.751 | 0.827 | 0.824 | 0.713 | 34 | 0.444 |
| union | 30.4 s | 0.943 | 0.740 | 0.894 | 0.914 | 0.747 | 45 | 0.311 |
| route | 30.4 s | 0.935 | 0.818 | 0.909 | 0.897 | 0.756 | 33 | 0.400 |

Per-type, every difference sits in the TB types (the FP layer is shared):
NAME crf 0.905/0.952 vs union 0.925/0.925 (+0.020 R, -0.027 P) vs
wangchanberta alone 0.618/0.918; ADDRESS recall 1.000 everywhere with
union/route precision slightly ahead (0.892/0.921 vs 0.866); DATE_OF_BIRTH
+0.022 R for the WangchanBERTa side.

## Decision and reasoning

1. **The 2026-07-15 landscape no longer exists.** Union's advantages were
   ADDRESS coverage and names the CRF missed. Address coalescing (PR #91)
   took CRF ADDRESS recall to 1.000, and the role-cue pass (PR #93) — which
   is engine-independent — closed most of the NAME gap. What union still adds
   (+0.008 overall recall) now costs -0.073 precision, +12 false positives on
   no-PII documents, and ~27x the compute.
2. **Route ties CRF** (F2 0.909 vs 0.908, +0.005 precision) — inside noise,
   for the same 27x cost. Not worth carrying two models for.
3. **No blind reveal was spent.** A reveal is justified for an engine-default
   *change*; the gold measurement rejects the change, and union relative to
   CRF can only add spans, so on the blind set — whose known weak spot is
   NAME precision — it would move the wrong way. Budget stays 3 of 6 used.
4. WangchanBERTa alone regressed relative to its 2026-07-15 showing because
   the shared cue passes now duplicate what it was good at, while its NAME
   recall on cue-less names was always worse than the CRF's (the 2026-07-14
   gold finding).

`AIGUARD_NER_ENGINE=wangchanberta|union` remain supported and opt-in,
unchanged. The benchmark CLI now accepts `--engine union` so this comparison
is reproducible in one flag.

## What would reopen this decision

A corpus (gold growth or blind rotation) where TB-type recall gaps reappear;
an ONNX/quantized runtime that removes the 27x cost factor (Track A step 6);
or a fine-tuned Thai NER model (step 5) — each gets measured on the same
corpus and scorer before touching the default.
