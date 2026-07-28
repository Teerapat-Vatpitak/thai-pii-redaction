# Gold set adjudication (v3 → v4)

- Date: 2026-07-28
- Status: applied; implements Track A step 2 of [ROADMAP.md](../../ROADMAP.md)
- Standard: [docs/annotation-guidelines.md](../annotation-guidelines.md),
  written first and updated by this adjudication where the rule — not the
  corpus — was wrong

## Process

Two independent reviewers examined all 252 documents against the guidelines:
a Fable agent in a separate context (with seven mechanical sweeps through the
repo venv: `detect_fp` over stripped text, bracket-value hygiene, checksums,
negative-slice digit runs, name_no_cue cues, long_form layout, markup
balance) and Codex (read-only, same brief, plus a critique of the guideline
document itself). Their findings overlapped but diverged exactly where two
reviewers are supposed to diverge; the maintainer's session adjudicated every
disagreement by re-deriving the facts mechanically, not by trusting either
report. Reviewer 1 filed 35 findings; reviewer 2 filed 91 findings and 12
guideline critiques.

## Corpus changes (23 documents; 641 → 648 entities)

| Change | Docs | Decision basis |
|---|---|---|
| Address labels moved out of brackets (`[[ADDRESS\|เลขที่ …]]` → `เลขที่ [[ADDRESS\|…]]`) | 15 | The corpus split two ways; majority practice and the detector's own cue list treat เลขที่/บ้านเลขที่ as cues. New precedent 7. Reviewer 2 found all 15; reviewer 1 found 4. |
| Title moved out of NAME (`ด.ช.`) | md04 | Both reviewers; mechanics section. |
| Missed annotation: unmarked office line | ms15 | Both reviewers; under the broad-ownership PHONE rule it is unambiguous. |
| Negative-slice 13-digit ISBN hyphenated | ng05 | Both reviewers; negative-slice rule (now worded as "no maximal token of exactly 13 digits"). |
| One entity added after the 500-char boundary | lf06, lf11, lf12, lf13, lf14, lf15 | Recomputed mechanically: these six had no entity starting past 500, so the slice was not exercising the chunk boundary it exists for. Per-document rule now stated in the guidelines; the stricter three-zone rule applies to newly authored documents. |

## Rule fixes instead of corpus fixes

Reviewer 2 filed ~46 "over-annotations" (organizational addresses, company
bank accounts, role mailboxes, office/service phone numbers, weak-cue student
IDs) against the guideline table's narrow "personal only" wording. The
corpus's practice was consistent the other way, and the product is
recall-first — masking an organization's mailbox is cheap, missing a person's
is not. The blind set was also authored by imitating gold's conventions, so
matching the rules to practice keeps the two corpora aligned, while adopting
the narrow reading would have silently diverged them. The guideline table now
states broad ownership explicitly. This resolves those findings as
rule-was-wrong, with zero corpus edits.

Guideline critiques adopted (reviewer 2): enumerated name_no_cue cue family
(matching the test), per-document long_form wording, address-label boundary
(precedent 7), abbreviation-punctuation exception (precedent 8), maximal-13
negative wording, bank_phone reuse exemption recorded, verbatim rule stated
operationally, student_id_varied axes enumerated.

## Rejected findings, with reasons

- **THAI_ID under ใบขับขี่/ผู้เสียภาษี cues (id15, fn12, lf05)**: kept. A Thai
  personal taxpayer ID is the citizen ID by construction, and driver licenses
  print it; a mod-11-valid 13-digit identifying a person is THAI_ID
  (precedent 9). Reviewer 2 proposed cue-precedence un-labeling; rejected as
  a recall regression.
- **ms14 PHONE → BANK_ACCOUNT**: kept as PHONE. โอนเงิน…ปลายทาง + a
  mobile-format number is PromptPay (precedent 10).
- **name_no_cue role labels (13 findings)**: kept. The slice bans the
  title/naming-verb cue family only; role-introduced names are the hard case
  the slice measures.
- **ng23 14-digit run in a negative doc**: kept; the rule is scoped to
  maximal tokens of exactly 13 digits.
- **Reviewer 1's dismissals** of 33 mechanical `detect_fp` hits (negative
  look-alikes, detector junk spans, out-of-scope types such as hospital HN)
  were spot-checked and stand.

## Effect on scores

Gold scores shift slightly (boundary normalization changes exact-boundary
and character metrics; one added PHONE and six added long-form entities move
recall denominators). All existing gold and CI-floor tests pass unchanged.
Gold remains a diagnostic, not a gated-to-green set; the blind set
(blind-v1, frozen before this adjudication) is unaffected — it was authored
under gold-v3 conventions, which this adjudication deliberately preserved by
fixing rules toward practice rather than practice toward the draft rules.
