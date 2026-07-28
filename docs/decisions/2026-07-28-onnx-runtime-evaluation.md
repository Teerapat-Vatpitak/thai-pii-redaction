# ONNX runtime evaluation for thainer-corpus-v2 (Track A step 6)

- Date: 2026-07-28
- Status: evaluated — not adopted now; kept as the deployment path IF a
  future model earns a default change on accuracy. Companion to the
  [engine comparison](2026-07-28-engine-comparison-after-campaigns.md).

## Method

`pythainlp/thainer-corpus-v2-base-model` (the model behind
`AIGUARD_NER_ENGINE=wangchanberta` and half of `union`) exported with
`torch.onnx.export` (opset 17, dynamic axes) and dynamically quantized to
int8 with onnxruntime. Measured on 60 chunks (~460 chars avg) drawn from the
open gold corpus, single-thread-default CPU, warmed, per-chunk latency at
batch 1 — the shape the stride-chunk pipeline actually issues. The blind set
was not touched. onnx/onnxruntime were installed ad hoc for this evaluation
and are deliberately NOT added to any requirements file.

## Results

| runtime | model size | parity vs torch | ms/chunk | speedup |
|---|---:|---|---:|---:|
| torch CPU (current) | 419 MB (fp32 weights) | — | 51.2 | 1.0x |
| ONNX fp32 | 419 MB | **exact**: 60/60 identical tag sequences, 0/2836 tag diffs, max logit delta 2e-5 | 21.2 | 2.42x |
| ONNX int8 (dynamic) | 105 MB | **broken**: 6/60 identical sequences, 262/2836 tags differ (9.2%) | 10.1 | 5.06x |

## Decision

1. **int8 fails the roadmap's output-parity requirement outright.** A 9.2%
   tag divergence is a different model, not a faster one; adopting it would
   require calibration-based quantization plus a full accuracy re-benchmark,
   and nothing currently motivates that work.
2. **fp32 ONNX is a genuine free 2.4x with exact parity** — but speed was
   not what killed the heavyweight engines. The engine comparison rejected
   union on precision (-0.073, +12 negative-slice FPs), which no runtime can
   fix. Even at 2.4x, the WangchanBERTa path stays roughly an order of
   magnitude slower than the 4 ms/doc CRF while scoring lower F2.
3. **Therefore nothing ships now.** The evaluated path matters as
   groundwork: if Track A step 5 (a fine-tuned Thai NER model) ever beats
   the CRF-plus-cues detector on accuracy, ONNX fp32 is the deployment
   runtime — with these parity/latency numbers as the baseline expectation
   and int8 explicitly requiring recalibration and re-scoring.

## What this leaves as Track A's only open lever

Steps 1-4 and 6 are done. The remaining accuracy gaps (blind NAME precision
0.700 with the cue approach measured as exhausted in reveal 3; the cue-free
STUDENT_ID probes) can no longer be reached by rules, runtime, or existing
engines — a fine-tuned model (step 5) is the one lever left, and the roadmap
gates it on exactly this kind of locked evidence. That is an investment
decision, not a code change, and it stays with the maintainer.
