# Breach assessment mode (Track D #2) — an honest range, not a headcount

Date: 2026-08-01 Status: accepted

## Problem

PDPA section 37(4) gives a controller 72 hours from becoming aware of a
qualifying breach to notify the PDPC. A controller who just found a set of
leaked or exposed documents needs, fast, what kind of personal data is in
them and roughly how many people are affected — not a guess, and not a tool
that quietly invents a single confident number it cannot back up. The product
already detects PII per document; this feature aggregates that detection
across a set of files without keeping anything the rest of the product
refuses to keep.

## Options not taken, and why

**A single point estimate of affected subjects.** The obviously useful
number, and the one an implementer is tempted to produce by simply taking
the largest distinct-value count seen anywhere. It is also the number most
likely to be wrong in a specific, dangerous direction: it invites reading
"we found N people" as ground truth for a legal notification when the tool
has no cross-document identity resolution at all. A single number that looks
authoritative but rests on an unstated assumption is worse than a range that
states its assumption in the same breath.

**Cross-document / cross-type person linkage** (matching a name in one file
to a Thai ID in another as the same person). This is the only way to turn
the range into a real count, and it is out of scope for v1 on purpose — it
is a much larger detection problem (fuzzy name matching, address matching,
household inference) than aggregating what the existing detectors already
found. Promising it silently, or attempting a shallow version of it, would
make the range look more resolved than the evidence supports.

**Hashing values before counting them**, to let a future feature reconstruct
identity across runs without storing plaintext. Rejected: a Thai national ID
is 13 digits. A hash of a 13-digit space is brute-forceable in the time it
takes to hash 10^13 candidates on ordinary hardware, so a hash of an ID is
not meaningfully different from the ID itself for this decision's purposes.
Hashes count as values here, and no artifact this feature produces may carry
one.

## What was decided

**The estimate is a range, not a headcount, with the method stated next to
it.** For each strong identifier type found — Thai national ID, passport,
phone, email, each canonicalized so the same value typed two ways collapses
to one distinct entry — `subjects_min` is the largest distinct-value count
among those types: the same canonical value under one type can only ever
describe one subject, so no single type can overcount. `subjects_max` is the
sum of those distinct counts: true only if no subject appears under two or
more identifier types, which is exactly the range's stated, unverified
assumption, not a hidden one. The same method-statement string is built once
in `pii_redactor/breach.py` and consumed verbatim by both the JSON output and
the PDF renderer, so the two artifacts cannot describe the estimate two
different ways.

**NAME is excluded from both bounds as a weak identifier.** A name has
spelling variants, OCR noise, and honorific-title differences that a Thai
national ID or an email address does not; folding it into the strong-type
bounds would let the noisiest signal set the range. `NAME`'s own distinct
count is still computed and reported, with a note explaining why it stands
apart, so a reader is not left wondering why it is missing.

**No cross-type or cross-document linkage in v1**, as above — the range's
assumption names this limitation directly rather than the report implying a
resolved count.

**Hashes count as values and are excluded**, as above — the distinct-value
sets that back the estimate are plain in-memory `set[str]` objects, computed
once per run and dropped with the process. Nothing in `to_json_dict()` or the
PDF is a value, an excerpt, a hash of a value, or OCR text; every field is a
count, a type or category name, or a version string.

**No API endpoint in v1**, mirroring the [section 39 processing receipt
decision](2026-07-29-processing-receipt.md): a CLI verb
(`ai_guard.py breach assess`) that discovers files, aggregates, and writes
JSON and/or a Thai PDF is the whole surface for this iteration.

**Failure reasons are path-stripped.** A file that cannot be processed
becomes a `FailedFile` row (basename + a short reason), so the assessment
keeps going instead of failing the whole run over one bad file. The first
implementation built that reason from `f"{type(exc).__name__}: {exc}"`
directly, which is faithful to the exception but not to the privacy
contract: several stdlib exceptions — `FileNotFoundError` chief among them —
embed the full operand path in their own message, so a directory name the
controller never intended to disclose (their own local filesystem layout)
flowed straight into both the JSON and the PDF. `_short_reason()` folds every
plausible spelling of the input path (as given, resolved, both slash
directions) down to the bare basename — which the report already shows
elsewhere — before the reason string is built, and joins the exception class
to its message with a space rather than a Western colon, since this string
can reach Thai-facing CLI and PDF output.

## Deviations from the design draft, recorded here rather than left implicit

- The draft's prose used `NATIONAL_ID` for the Thai identifier type; the
  codebase's real `Entity.data_type` label is `THAI_ID`, and the shipped
  code uses that, matching what every other detector, the receipt, and the
  benchmark already call it.
- Phone normalization folds a `+66` international form — mobile (9 digits
  after `66`) or landline (8 digits after `66`) — to its domestic `0`-prefixed
  form, so the same number typed two ways collapses to one distinct value.
  The design draft's own test list only named ID-spacing and email-case
  normalization explicitly; this is a direct reading of "PHONE (normalized)"
  rather than a new requirement, and is covered by dedicated tests in both
  directions.

## What this does not do

Section 37(4) has parts a tool cannot answer for a controller: whether the
breach is "likely to result in a risk to the rights and freedoms of the data
subject" (the threshold that triggers notification at all), who the
controller's data protection officer is, what containment steps were taken,
and what the notification's own text should say beyond the evidence. The
assessment states what was found and how the range was derived, and stops
there — it never asserts that notification is required, and it never invents
a point estimate the evidence does not support.
