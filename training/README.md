# Fine-tuning lane (Track A step 5)

Everything needed to train the opt-in `AIGUARD_NER_ENGINE=finetuned` model.
Weights are never committed; the engine loads them from
`AIGUARD_FINETUNED_MODEL_DIR` (keep it outside the repository).

- `lexicons.json` — fabricated Thai value pools and phrase banks, built
  disjoint from the gold set's annotated values and from the product's
  surrogate pools (so a surrogate is never a token the model overfits to).
- `generate_data.py` — synthetic BIO training data in the model label space
  (PERSON / LOCATION / ORGANIZATION / DATE / STUDENT_ID), with a
  generator-disjoint dev split, O-only hard-negative registers, counterfactual
  pairs, and ThaiNER-2.0 rehearsal so LOC/ORG/DATE are not forgotten.
  Re-asserts gold-contamination checks on every run. Outputs are
  reproducible from the seed and are not committed (`*.jsonl` is ignored).
- `train.py` — HF Trainer fine-tune of `pythainlp/thainer-corpus-v2-base-model`
  with a fresh 11-label BIO head; checkpoint selection on dev span-F1, never
  on gold. `--max-steps 100` is the CPU pilot.

Training dependencies beyond `requirements-ml.txt`: `datasets` (see
`requirements-train.txt`). These never enter the runtime, the exe, or the
hosted image.

Evaluation happens through the normal benchmark
(`python -m benchmark --source gold --engine finetuned`) so the model is
scored under the full product ensemble. The decision gates and the
model-as-verifier name-cue policy are recorded in
`docs/decisions/` (fine-tuning ADR) and `pii_redactor/detectors/tb_detector.py`.
