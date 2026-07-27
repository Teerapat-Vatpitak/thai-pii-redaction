# Blind evaluation set protocol (blind-v1)

- Date: 2026-07-28
- Status: accepted; implements Track A step 1 of [ROADMAP.md](../../ROADMAP.md)
- Reviewed by: maintainer, with an adversarial design review by a second model
  (Codex) whose accepted objections are folded in below

## Problem

All detector tuning so far is evaluated on `benchmark/data/gold.jsonl`, which
is openly readable and inspected constantly during development. That makes it
a development set: a fix tuned against it cannot show generalization. Track A
therefore requires a held-out corpus that is never inspected during detector
work.

The unusual constraint is *who* must be blinded. Development here is done by a
solo maintainer working with AI coding agents that routinely grep and read the
entire repository. A plaintext blind file would leak into future agent
contexts through search results, test output, and casual reads — that
contamination path is more likely than deliberate human peeking. The
mechanisms below are therefore aimed at accidental disclosure and
self-deception, not at adversaries.

## Decisions

### Storage and blinding

- The corpus is committed only as an authenticated, obfuscated blob
  `benchmark/data/blind-v1.enc` (committing it keeps backup and portability;
  plaintext never enters the repository worktree).
- The cipher is an HMAC-SHA256 counter-mode keystream with a random per-freeze
  nonce and a separate authentication MAC (`benchmark/blind.py`). This is
  stdlib-only and is documented as **blinding, not security**: anyone holding
  the key can decrypt, which is the intended behavior. (Codex preferred an
  established tool such as `age`; rejected to keep the evaluation path free of
  new dependencies on Windows. Its keystream-construction fixes — per-version
  nonce, separate enc/auth subkeys, authenticated header — are adopted.)
- The key lives outside the repository and is supplied only via
  `AIGUARD_BLIND_KEY_FILE`. There is no default key location, so routine
  tooling cannot stumble into the plaintext. The maintainer keeps the key and
  a plaintext copy backed up outside the repository.
- `benchmark/data/blind-v1.lock.json` pins plaintext and ciphertext SHA-256
  plus aggregate composition (document/slice/type counts) and the reveal
  budget. Scoring refuses any corpus that does not match the lock.

### Authoring and pre-freeze QA

- The corpus was authored by an isolated agent context, to a plaintext file
  outside the repository, and its content never entered the main development
  context. Residual risk: the authoring transcript exists on the local disk;
  accepted and recorded here.
- Checksum-bearing values (THAI_ID mod-11, CREDIT_CARD Luhn) come from
  pre-generated valid pools so authoring errors cannot produce invalid
  structured values.
- A second, independent agent context reviews the draft before freeze (missed
  unmarked PII, wrong labels, span glitches) and certifies the negative slice
  as PII-free. "No markup present" is not treated as negative-slice purity.
- One pre-freeze disagreement pass against the current detector is allowed,
  executed only inside the isolated reviewer context, under fix-only rules:
  it may correct objectively wrong or missing annotations; it may NOT delete,
  rewrite, or replace documents because the detector finds them hard.
  Aggregate edit-reason counts are recorded in the freeze report.
- Automated freeze validation (`benchmark/blind.py validate_draft`) rejects
  unknown types, unbalanced/nested markup, duplicate ids, layer mismatches,
  checksum failures, cross-document value reuse, negative-slice violations
  (including any 13-digit run), missing long-form boundary-zone entities, and
  per-type minimum shortfalls. Validation output is `(doc_id, error-kind)`
  only — never values, unlike the gold-set validators.

### Scoring and the reveal budget

- `python -m benchmark --source blind --reason "..."` is the only scoring
  path. Output is aggregate-only: overall metrics with a document-level
  bootstrap 95% CI on entity F2, predeclared family macros, per-type rows
  (labeled *descriptive* under n=50), and negative-slice false-positive
  metrics. No document text, entity values, or per-document diffs, on any
  path including errors.
- Metric families are predeclared in `benchmark/blind.py`
  (structured = THAI_ID, CREDIT_CARD, BANK_ACCOUNT, PHONE, EMAIL, PASSPORT,
  VEHICLE_PLATE, STUDENT_ID; contextual = NAME, ADDRESS, DATE_OF_BIRTH), so
  pooling cannot be invented after seeing results. The primary metric is
  overall entity-level F2; everything else is secondary.
- Every run appends a hash-chained entry to the committed
  `benchmark/data/blind-scores.jsonl`: timestamp, reason, engine, corpus and
  ciphertext hashes, benchmark-code digest, git HEAD and dirty flag, metrics,
  and the previous entry's hash. `--verify-blind-log` checks the chain. Old
  entries are never edited; corrections are appended.
- **Reveal budget: 6 for blind-v1** (the freeze baseline plus five
  checkpoints). Runs beyond the budget still execute but are permanently
  marked `over_budget: true`. Legitimate reveal reasons are: freeze baseline,
  end of a named tuning campaign, a release, or an engine-default decision.
  Routine development must use the gold set.
- The freeze baseline is revealed (recorded as reveal 1). A revealed result
  that then drives further tuning weakens v1 as a holdout; the budget and the
  audit log exist to keep that cost visible rather than pretend it is zero.
- The LLM benchmark (`benchmark/llm_strategy.py`, `scripts/run_llm_benchmark*`)
  must never touch the blind set — it sends document text to hosted
  providers. A regression test pins that those files do not reference the
  blind module.

### Versioning and rotation

- Any edit to the corpus creates `blind-v2` with a new lock; `blind-v1` and
  its log entries remain archived and valid *for v1*.
- Valid rotation reasons are predeclared: reveal-budget exhaustion, a
  confirmed annotation defect, or corpus exposure (the plaintext entering a
  development context). **A disappointing score is not a rotation reason.**

## Known limitations

- The key file is readable by any process running as the same OS user,
  including coding agents that go looking for it. The protocol relies on the
  no-default-discovery rule plus the audit log, not OS-level isolation.
  (Codex recommended a separate OS account or signed evaluator environment;
  rejected as disproportionate for a solo prototype — revisit if the project
  gains contributors who tune the detector.)
- Per-type counts (~25-70) make small per-type deltas noise; the protocol
  mitigates by CI-on-primary-metric, family macros, and the *descriptive*
  label rather than by pretending per-type deltas are significant.
- The scorer's overlap-based entity matching is part of the frozen evaluator;
  its digest is recorded per run so a scorer change cannot silently masquerade
  as a detector improvement.
