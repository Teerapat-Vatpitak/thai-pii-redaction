# DSAR helper (Track D #3) — locate, never reproduce

Date: 2026-08-01 Status: accepted

## Problem

PDPA มาตรา 30 gives a data subject the right to access their own personal
data. A controller who receives that request has to find, across documents
they already hold, which files mention the requester and what kinds of
personal data about them appear where — today that search is manual and
depends on someone remembering where things are filed. This item was left
blocked in the roadmap ("DSAR helper... Blocked on the same question the
receipt answered for itself — what may be retained, and for how long") until
the owner answered the retention question directly.

## What was decided

**Retention is in-memory for the duration of one run only, answered by the
owner on 2026-08-01.** Nothing derived from the request or the documents may
be written to disk beyond the artifacts the caller explicitly asked for
(`-o`/`--pdf`), and those artifacts carry no personal-data value. The subject
identifiers the controller supplies, every value the detector finds while
matching them, and all intermediate lookup state live in local variables and
die with the process — no cache, no session file, no log carrying a value.
This is the same retention posture the receipt and breach assessment already
committed to; the DSAR helper does not get a lighter rule just because its
input (a person's own identifiers) is more sensitive, if anything the reverse.

**This tool locates; it does not reproduce.** The output is a list of which
files matched and which identifier types matched in each — never a copy, a
quote, or an excerpt of the matched file's own content. The controller
answers the access request from the located files themselves. The result
also never claims the request is satisfied: locating a file is not the same
as having served its content, and the artifact says so explicitly rather
than implying completion.

**Subject identifiers are never accepted inline on the command line.** They
are supplied only through `--subject-file`, a text file the controller
prepares with one identifier per line (Thai national id, passport, phone,
email, or full name), classified by shape. A person's national ID or phone
number typed as a CLI argument would sit in shell history indefinitely on
the controller's own machine — a leak this tool would have caused, not one
it was asked to find. Requiring a file instead of a flag value closes that
specific channel.

**No masked or hashed echo of an identifier, anywhere.** Same rule breach
assessment already established for detected values — a hash of a 13-digit
Thai ID is brute-forceable in the time it takes to hash 10^13 candidates on
ordinary hardware, so it is not meaningfully different from the ID itself.
`DsarResult` carries only identifier TYPE counts (e.g. "THAI_ID 1, EMAIL 1"),
never the values; every dataclass field that could otherwise hold a raw
value is absent by construction rather than filtered late. This was tested
as the strictest privacy surface in the suite: subject values must be absent
from stdout, stderr, JSON bytes, and PDF bytes, including on every error
path (a missing subject file, a missing document, an unwritable output) —
not just the success path.

**Matching is exact canonical equality only — no fuzzy matching in v1 — and it
is value-based, not label-based.** A detected entity matches a subject
identifier when the entity's raw text, canonicalized under that subject
identifier's own type rules, equals the subject identifier's canonical value
under the same normalizer breach assessment already uses (spaced or
hyphenated Thai ID forms, mixed-case emails, `+66`/domestic phone forms, and a
name with its title stripped all collapse to one value). The detector's own
type label for the entity is never consulted: this codebase's own detection
rules make that label context-dependent (the nearest-cue-wins tiers for
bank/phone, bank/student, and student/order pairs — see `fp_detector.py`), so
the same string can be labeled `BANK_ACCOUNT` in one document and `PHONE` in
another, or a person's name folded into `ORGANIZATION` inside a company-name
phrase. Gating the match on label agreement (the first cut of this helper did,
until the final-branch review caught it) silently lost real matches and made
this tool stricter than its own recall-first design — a false negative here is
the controller telling a data subject their data is not in a document that
literally contains their phone number. This is a scope decision, not an
oversight, about what kind of matching v1 does at all: cross-document identity
resolution and error-tolerant (fuzzy) matching are both larger detection
problems than this task's job of locating on values the pipeline already
extracts cleanly; the label-independence fix does not change that scope, it
only makes the value-equality rule the spec always described actually hold.

Label-independence itself introduced a real false positive, caught by a
second scoped re-review: `canonical_value`'s PHONE fold (an 11/10-digit run
starting `66` collapses to the domestic `0...` form, because `+66 81 234
5678` and `081-234-5678` are the same number) does not require the source
text to have actually carried a `+` marker — it fires on bare digits alone.
Applying that fold to every entity regardless of label meant an unrelated
10/11-digit value (a bank account that merely starts with `66`) could
collapse to the exact same domestic string as a subject's phone by pure
digit coincidence, producing a false match this tool must not produce (a
DSAR artifact is legal evidence). The fix keeps label-independence but adds
one precision guard: a plain domestic-looking match (the entity's raw
digits already equal the subject's domestic canonical phone) is accepted
directly, and the international fold is applied only when the entity's own
raw text still carries an explicit `+66` marker. Bare `66812345678` with no
`+` is left unmatched; `+66 81 234 5678` (any spacing or surrounding label)
still matches, preserving the original fix's intent.

**The OCR near-miss gap is stated, not papered over.** A scanned page's
identifier that OCR reads one character wrong will not canonically match
the subject file even though a human reader would recognize it as the same
value. This is not a new gap this helper introduces — it is the same
detection limitation the phase-2 government-form gate already isolated
([ROADMAP.md](../../ROADMAP.md) Track A item 7: "an OCR read that is one character off...
is treated as if the value were absent — no tag, no black box"). The DSAR
result's fixed method statement names this limitation directly next to the
match count, so a zero-match result is never misread as "this document does
not concern the subject" when it may in fact mean "OCR misread the one
identifier that would have matched."

**`third_party_possible` is warn-only, and stated as heuristic.** A matched
file's row sets this flag when the file's overall PII inventory carries a
type or a count beyond what matched the subject's own identifiers — personal
data that may belong to someone else, co-located in the same document. It is
a signal for the controller to review and redact before serving a copy, not a
conclusion that a third party's data is definitely present (the extra PII
could just as easily be the subject's own data under a type they didn't list
in the subject file, or a detector false positive with no third party behind
it at all — the final-branch review reproduced both). Same house style as
breach's own `no_strong_identifiers` flag: the tool states what it observed
and stops short of an inference it cannot back up.

**A NAME-only match is flagged `weak_only`, not presented as equal evidence to
an id-backed match.** `breach.py` already treats NAME as a weak identifier for
its own `subjects_min`/`subjects_max` estimate, because spelling and OCR
variants inflate it and a common Thai name does not uniquely identify a
person. The DSAR helper matches on NAME too (the spec lists it as a valid
identifier type), but a matched file whose only matched identifier type is
NAME sets `weak_only: true` in its row, and a fixed statement (drawn verbatim
into both the JSON and the PDF, same discipline as every other method note)
says a weak-only match is evidence that *a* person with this name appears,
not that *the requester* does, and needs human confirmation before the file
is treated as concerning the subject. A file that also matched on an id,
passport, phone, or email stays `weak_only: false` even if a NAME matched
too.

**No API endpoint in v1**, mirroring the [processing receipt](2026-07-29-processing-receipt.md)
and [breach assessment](2026-08-01-breach-assessment.md) decisions: a CLI
verb (`ai_guard.py dsar locate`) that discovers files, matches, and writes
JSON and/or a Thai PDF is the whole surface for this iteration.

## A fix that came out of this work, and hardened breach too

Building this helper's shared-helper extraction (`breach.py`'s file-discovery
and canonicalization functions moved verbatim into `pii_redactor/scan_common.py`
so `dsar.py` could reuse them without duplicating logic) put the failed-file
path scrub under closer scrutiny than it had been before, and that scrutiny
found a real leak in code the breach lane had already shipped. CPython's
`OSError.__str__` embeds its filename via `%R` — Python's own `repr()` —
which backslash-escapes a Windows path, e.g. `'C:\\Users\\...\\missing.txt'`
(doubled backslashes). The existing scrub only computed plain
single-backslash and forward-slash spellings of the input path, so a real
stdlib exception's doubled-backslash spelling was never matched as a
substring and the full path leaked through both `FailedFile.reason` and the
CLI's top-level failure line. A pre-existing masking test had asserted
`str(tmp_path) not in reason`, which passed vacuously — that exact
plain-backslash string was never a literal substring of the doubled-backslash
leak in the first place, so the assertion could not have caught this even
before the fix.

The fix lives in one place: `scan_common.path_spellings(path)` now also
computes, for every spelling already found, the backslash-doubled form and
the exact `repr()`-stripped form `OSError.__str__` embeds; both
`scan_common.short_reason` (per-file scrub) and `ai_guard._scrub_known_paths`
(corpus-level scrub) call this one helper instead of duplicating the
spelling logic, so both the DSAR and the breach CLI paths were closed by the
same change. Tests were strengthened (not weakened) across `tests/test_dsar.py`,
`tests/test_dsar_cli.py`, `tests/test_breach_assessment.py`,
`tests/test_breach_cli.py`, and `tests/test_breach_pdf.py` — to assert the
doubled-backslash spelling and the bare final path component, which is what
would actually have caught the original bug. `tests/test_breach_pdf.py`
carried an analogous `str(tmp_path) not in ...` masking pattern that was out
of scope for the original fix loop; the final whole-branch review caught the
gap and it was strengthened in this same wave, not left as an in-file
follow-up marker.

## What this does not do

This helper does not resolve identity across documents beyond exact
canonical value matching, does not attempt any OCR-error tolerance, does not
serve or export the access request itself, and does not decide whether a
DSAR has been fully answered — it states which files matched, on what basis,
and what limits that finding, and stops there.
