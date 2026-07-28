# Fine-tuned NER results (Track A step 5, campaign 3 close)

- Date: 2026-07-28
- Status: decided — the fine-tuned engine is certified as the heavyweight
  **opt-in** engine (`AIGUARD_NER_ENGINE=finetuned`), displacing union in
  that role. The CRF stays the default (latency; see the
  [engine comparison](2026-07-28-engine-comparison-after-campaigns.md)).
  Infrastructure and design rationale: PR #97 and the
  [ONNX evaluation](2026-07-28-onnx-runtime-evaluation.md).

## What was trained

`pythainlp/thainer-corpus-v2-base-model` + fresh 11-label BIO head over
PERSON/LOCATION/ORGANIZATION/DATE/STUDENT_ID; 6,828 synthetic documents /
16,310 entities (gold-disjoint lexicons, O-only hard-negative registers
upweighted by the current detector's real hallucinations, counterfactual
pairs) + 2,000 ThaiNER-2.0 rehearsal docs; 3 epochs CPU (~40 min); dev
span-F1 0.987. Per-label confidence floors calibrated on the synthetic dev
split only (PERSON 0.92, STUDENT_ID 0.98, LOCATION 0.58), stored with the
weights. Predeclared procedure held: threshold sweep on dev, ONE gold sanity
run, then the reveal — no blind-informed tuning.

## Gold v4 (single sanity run, full ensemble)

Overall R 0.977 / P 0.741 / F2 0.918 vs the CRF ensemble's 0.935/0.813/0.908;
coverage 0.961, exact-boundary 0.887 (CRF: 0.924 / 0.769). NAME 0.965/0.928;
STUDENT_ID 0.912/0.839 with the cue-free probe slice at 0.821 (CRF: 0.607);
name_no_cue 1.000. Costs: messy-slice recall 0.931 (subword tokenizer vs OCR
noise — the CRF path remains better there) and negative-slice FPs 41 vs 33,
mostly extra DATE spans (a by-design masked type) plus a residual tail of
STUDENT_ID junk the thresholds shrank but did not eliminate.

## Blind verdict (reveal 4 of 6)

The founding question of this campaign was blind NAME precision 0.700 —
the gap reveal 3 proved unreachable by cue rules. Result:

| aggregate | reveal 3 (CRF ensemble) | reveal 4 (finetuned) |
|---|---|---|
| overall F2 | 0.898 (CI 0.877-0.916) | **0.914** (CI 0.898-0.929) |
| overall recall | 0.960 | 0.983 |
| NAME precision | 0.700 | **0.922** |
| NAME recall | 0.949 | 1.000 |
| NAME F2 | 0.886 | **0.983** |
| contextual macro F2 | 0.904 | 0.957 |
| DATE_OF_BIRTH F2 | 0.932 | 0.989 |
| STUDENT_ID recall (n=26, descriptive) | 0.731 | 0.808 at precision 1.000 |
| negative clean-doc rate | 0.346 | **0.423** |

The model-as-verifier architecture did what it was built for: on blind's
registers the extended cues stop hallucinating (they now require model
agreement) while the model supplies the missing names itself. The negative
clean rate moved the right way on blind even though it looked worse on gold —
the O-only training registers matched blind's better, which is itself
evidence the improvement is not gold-shaped.

## Standing decisions

1. Default engine: CRF, unchanged (4 ms/doc vs ~100+ ms/doc CPU; ONNX fp32
   would give ~2.4x back if this engine ever needs deployment at scale).
2. Recommended high-recall option for batch/PDF workloads:
   `AIGUARD_NER_ENGINE=finetuned` (F2 0.918 gold / 0.914 blind vs union's
   0.894 gold at the same cost class). Union remains supported but has no
   remaining niche.
3. Weights + thresholds live outside the repo (`AIGUARD_FINETUNED_MODEL_DIR`);
   reproduction = `training/` scripts + recorded seeds + data manifest hashes.
4. Reveals used: 4 of 6. Remaining budget is reserved for a future campaign
   close or a default-change decision.
5. Known limits carried forward: messy/OCR registers favor the CRF path;
   residual STUDENT_ID false positives on reference numbers; single
   fine-tune seed (three-seed variance never measured — acceptable for an
   opt-in, required before any default change).
