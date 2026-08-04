# Weakness-closure campaign (Track A item 3, end to end)

Date: 2026-08-04
Status: accepted

## Context

Track A item 3 orders detection work as "scorer/boundary defects, structured
(FP) misses, NAME context coverage, ADDRESS coverage, then false-positive
reduction". The 2026-08-03 negative-slice campaign had taken the last rung
only. This campaign worked the whole ladder in one branch, driven by an
inventory that enumerated every measured weakness rather than a sample:
VEHICLE_PLATE precision, the remaining negative-slice predictions, STUDENT_ID
label honesty, DATE_OF_BIRTH and NAME misses, ADDRESS precision and character
coverage, the exact-boundary gap, and the government-form harness flake.

Every inventory entry had to carry the failing input, the code-level mechanism
with `file:line`, a proposed fix, and counterexamples the analyst had actually
run. Entries were classified `bug` / `mechanism` / `tuning` / `by_design` /
`owner_decision`, and only the first two were implemented without further
judgement.

## Decision

Close every `bug` and `mechanism` entry; leave `tuning` entries out unless the
list they extend already had a stated one-entry-per-observed-leak policy;
leave `by_design` and `owner_decision` entries alone and record them.

Two structural decisions came out of the work.

**TB de-duplication is score-first with a coverage guard.** The inventory
disagreed with itself here: one analyst measured a plain score-first flip as a
corpus-wide improvement, another constructed a class where a narrow, higher
-score cue span evicts a wide CRF span covering TWO people and unmasks the
second one. Building that counterexample through the real detection path
reproduced the leak, so the flip landed with the guard: an overlapping span may
be evicted only when every character it covers is still covered by a kept span.
Eviction can now never reduce coverage.

**A mechanism that REMOVES text is held to a higher bar than one that adds it.**
Same-line NAME hygiene, digit-run splitting, facility-designator dropping and
role-cue vetoes all trim spans, and trimming unmasks whatever it removes. The
adversarial review found seven realistic Thai sentences where the first cut of
these mechanisms left PII in the clear that `main` had masked — none of them on
the gold corpus, which showed zero regressions across all 648 annotated
entities. Trimming rules therefore may consume only tokens that are themselves
closed-lexicon evidence, and a lexicon written to mean "never STARTS a name in
prose" may not be reused to mean "never IS a name".

## Consequences

The measured effect is recorded in the branch's commit message and reproducible
with `python -m benchmark --source gold`; no accuracy number is copied into
prose here, per the roadmap's exit gate.

Left deliberately open, each needing an owner call rather than an
implementation:

- **STUDENT_ID exam-roster cues.** Admitting ผู้เข้าสอบ / ที่นั่งสอบ / ห้องสอบ /
  สอบสัมภาษณ์ into the education-context list recovers four labels with no
  measured new false positive, but reverses a documented deliberate exclusion:
  exam rosters also enumerate civil-service candidates, driving-licence
  applicants and language-test takers, who are not students. This is a
  label-honesty scope question, and every affected value is masked as
  `ID_NUMBER` either way.
- **Salutation addressees** (`เรียน` / `ถึง` + name). No cue can be added
  without collecting role nouns and place names; the miss is a CRF limitation
  the union and fine-tuned engines may already cover.
- **Generic dates on administrative documents.** Thirteen of the remaining
  negative-slice predictions are document-issue, deadline and effective dates.
  Masking them is the deliberate honest-label behaviour; carving them out is a
  masking-policy change, not a defect fix.
- **A gold self-contradiction.** `benchmark/gold.py` states that organisation
  names are deliberately absent from the negative slice, but `ng06` contains a
  real department name that the detector reads correctly. The clean fix is to
  the corpus, which requires re-adjudication.
- **No held-out set remains.** `blind-v1`'s reveal budget is exhausted, so
  nothing in this campaign could be checked for generalisation. Any future
  tuning-shaped work needs a frozen `blind-v2` first.

The government-form acceptance harness could not be run to completion on the
development machine: PaddlePaddle aborts the process with a Windows access
violation, with a failure probability that scales with the OCR work already
done in that process. The fault reproduces with the OCR code reverted to
`main`, so it is an environment fault rather than a regression from this work.

## Recall regressions found by review, and what they cost

A four-lens adversarial review ran against the finished waves and found seven
realistic Thai sentences that `main` masks and this work had stopped masking.
Every one came from a mechanism that *removes* span material — trimming a role
prefix, dropping a facility designator, vetoing a cue, truncating at a digit
run. None was visible on the gold corpus: an entity-level differential over all
252 documents showed 30 improvements and zero losses, because the corpus does
not contain the shapes involved.

The lesson is structural rather than incidental. A mechanism that adds a span
can only over-mask; a mechanism that removes one can unmask, and the corpus
that justified it will not report the damage. Two of the seven also show how a
lexicon acquires a meaning it was never given: `_LEAD_STOP` documents itself as
"words that never START a name in prose", and using it to decide what is *not*
a name unmasked `ประสงค์`, an attested given name.

All seven are fixed and pinned in `tests/test_review_recall_regressions.py`,
each test carrying the reviewer's verbatim sentence plus the precision control
the original finding was written against, so a fix cannot degenerate into a
revert.

## Performance

The perf gate is red against `perf/baseline.json`, and the branch is not why.
Measured on the development machine the same day:

| measurement | base (`20a9a1d`) | this branch | delta |
|---|---|---|---|
| `detect_all`, in-process, alternating arms, n=7 | 15.66 ms | 16.84 ms | +7.5% |
| `detect_fp`, same method, n=9 | 0.463 ms | 0.587 ms | +26.8% |
| `detect_tb`, same method, n=7 | 17.71 ms | 18.10 ms | +2.2% |

The composite path is inside the 20% budget. `detect_fp` carries the largest
relative cost — it gained the province gazetteer, the Thai-month date shape and
the estate pattern — but 0.12 ms of it, and part of that buys an entity the
base tree missed.

Cross-process runs of `scripts/measure_perf.py` disagree, reporting 20-40%
regressions. They are measuring the machine: unmodified `main` code measured
10.2-15.9 ms for `detect` in the same session against a stored baseline of
5.7 ms, so every arm is red before any change is applied, and repeated runs of
identical code span a 1.9x range. Measuring each arm first in alternating
rounds did not remove the disagreement, which is what identifies the
cross-process figure as machine state rather than an ordering artifact. The
baseline is deliberately not moved; this is the same conclusion the M4 and M6
campaigns reached on this machine.
