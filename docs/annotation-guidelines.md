# Benchmark annotation guidelines

The standard for annotating the gold set (`benchmark/data/gold.jsonl`), for
authoring any blind-set version, and for adjudicating disputes. When a
document and these rules disagree, either the document is wrong (fix it) or
the rule is wrong (change the rule in its own PR, then re-check the corpora
against it). Do not resolve a dispute by inventing an unwritten convention.

Mechanics are enforced by `tests/test_benchmark_gold.py` and
`benchmark/blind.py validate_draft`; this file records the judgment calls a
validator cannot make.

## Markup mechanics

- Inline markup: `[[TYPE|value]]`. No nesting, no overlap, values are a
  single line, spans are exactly the PII value.
- Contextual cues stay OUTSIDE the brackets: titles (นาย/นาง/นางสาว/ดร.),
  field labels (ที่อยู่ / เบอร์โทร / เลขบัญชี / เกิดวันที่), and surrounding
  punctuation are context, not PII value.
- A value reads verbatim from the document — no normalization inside the
  brackets. If the document writes a phone with Thai digits or stray spaces
  (messy slice), the value carries them.

## The 11 types

Only these types are annotated: NAME, ADDRESS, PHONE, EMAIL, THAI_ID,
BANK_ACCOUNT, CREDIT_CARD, DATE_OF_BIRTH, PASSPORT, VEHICLE_PLATE,
STUDENT_ID.

The corpora label **ground truth from the document's fiction**, not detector
behavior: if the document presents a value as a phone number, it is PHONE
whether or not any engine can find it. The product is recall-first — masking
an organization's mailbox or a company account is cheap, missing a person's
is not — so ownership rules below are deliberately broad.

| Type | Annotate | Do not annotate |
|---|---|---|
| NAME | Full personal names (first + last), first names when clearly a specific private person in context | Single-word nicknames, kinship references (พี่เอ), public figures acting in public capacity, organization names |
| ADDRESS | Any specific locatable address presented as an address — residential or organizational (house number + street/soi/tambon chain, building + road + district) | Vague neighborhood mentions (แถวลาดพร้าว), standalone room/house numbers outside an address context |
| PHONE | Any telephone number — personal, direct-line, office, or service — in any Thai format | Public short-code hotlines (1669, 1112, 4-digit numbers) |
| EMAIL | Any email address, including organizational role mailboxes (registrar@, billing@) | — |
| THAI_ID | Any mod-11-valid 13-digit value presented as identifying a person, whatever the surrounding document calls itself (บัตรประชาชน, ใบขับขี่, เลขผู้เสียภาษีบุคคล — a Thai personal taxpayer ID *is* the national ID) | Corporate registration numbers presented as an organization's (avoid 13-digit look-alikes entirely in negative docs) |
| BANK_ACCOUNT | Any bank-account number — personal, merchant, or company | Bill/invoice reference numbers |
| CREDIT_CARD | 13-16 digit card numbers (must pass Luhn) | Loyalty-card and gift-card numbers |
| DATE_OF_BIRTH | A date tied to birth by cue (เกิด / วันเกิด / ว.ด.ป. เกิด) | Business dates, appointment dates (those are DATE to the detector, and unannotated here) |
| PASSPORT | Passport numbers (Thai format `[A-Z]{2}\d{7}` or cue-bearing general format) | Visa/work-permit reference numbers without a passport cue |
| VEHICLE_PLATE | Thai license plates | Lot numbers, equipment/asset codes that merely resemble plates |
| STUDENT_ID | Codes the document's fiction presents as a student/enrollee code, with or without an explicit cue word (weak-cue documents are deliberate detector probes) | Order/receipt numbers even when 8-12 digits |

Quasi-identifiers the DETECTOR flags on purpose but the corpora never label:
organization names, provinces/districts standing alone, postal codes, generic
dates. A detector prediction of those types on a benchmark document is scored
as a false positive by construction — that cost is accepted and consistent
across gold and blind; do not "fix" it by adding those types to a corpus.

## Judgment-call precedents

Recorded so adjudication is repeatable. Each traces to an existing corpus
decision; add new precedents here when a new dispute is settled.

1. **Standalone room/hotel/house numbers are not PII** outside an address
   chain (gold `id23` leaves a hotel room number unannotated).
2. **Single-word names are not annotated.** The corpus has no one-word NAME
   precedent; a bare nickname after a kinship word (พี่/น้อง/ป้า) stays
   unannotated. A full first-last name is always annotated, cue or not.
3. **Vague area mentions are not ADDRESS.** แถว/ย่าน + district is context;
   an address is annotated from the first locatable component (house number,
   named soi/road with number, or a tambon/amphoe/province chain).
4. **Only public short-code hotlines are excluded from PHONE.** Office lines,
   department numbers, and call-center numbers in normal phone formats are
   annotated (2026-07-28 adjudication: broad ownership matches corpus
   practice and the recall-first product).
5. **DATE_OF_BIRTH requires a birth cue.** A bare date near a person is not a
   birth date; without the cue it stays unannotated (the detector's honest-label
   rule mirrors this).
6. **A value inside another annotated value is never separately annotated**
   (no nesting): the outermost natural unit wins (a full address containing a
   postal code is one ADDRESS).
7. **Address labels stay outside the brackets**: เลขที่ / บ้านเลขที่ / ที่อยู่
   are cues; the ADDRESS span starts at the house-number digits or first named
   locatable component (normalized corpus-wide in the 2026-07-28
   adjudication).
8. **Punctuation intrinsic to the value stays inside**: abbreviations and
   initials (กทม., กรุงเทพฯ, `Nattaya S.`) keep their marks; sentence and
   delimiter punctuation stays outside.
9. **A mod-11-valid 13-digit personal identifier is THAI_ID regardless of the
   document type around it** (driver licenses print the citizen ID; a Thai
   personal taxpayer ID is the citizen ID). Nearest-cue precedence applies to
   choosing between PII types, not to un-labeling valid national IDs.
10. **A phone number as a transfer destination stays PHONE** (PromptPay:
    โอนเงิน...ปลายทาง + a mobile-format number is a phone used for payment,
    not a bank account; gold `ms14`).

## Negative slice

Documents with zero annotations and zero PII of the 11 types, carrying
look-alikes that must not be flagged: receipt/invoice/order numbers, case and
statute numbers, ISBN, prices, lot/tracking numbers, public hotlines.
Organization names and provinces are allowed and expected (see
quasi-identifiers above). No maximal digit token of exactly 13 digits may
appear — even a checksum-invalid one reads as a national-ID look-alike and
turns the document into a detector-behavior probe rather than a clean
negative. Longer tokens (14+ digits) that the document identifies as non-PII
codes are allowed (gold `ng23`).

## Slice contracts

- `name_no_cue`: no title or verb-of-naming cue directly before the NAME —
  the banned family is exactly the test-pinned lists: titles
  นาย/นาง/นางสาว/น.ส./ด.ช./ด.ญ./เด็กชาย/เด็กหญิง and intros
  ลงชื่อ/ผมชื่อ/ดิฉันชื่อ/ชื่อ. Occupational and discourse roles
  (ผู้จัดการ, พยาน, ลูกค้า) are allowed — names introduced only by role words
  are exactly the hard case this slice exists to measure.
- `long_form`: > 500 chars; every document must have at least one entity
  starting before char 450 and at least one starting after char 500 (the
  stride-chunk boundary), enforced per document since v4. Newly authored
  long-form documents should meet the stricter three-zone placement
  (before 450 / 450-550 / after 550) used by the blind set.
- `messy`: OCR-like noise is the point — Thai digits, stray spaces, broken
  wraps. Values still read verbatim, noise included.
- `student_id_varied`: varies one format/context axis per document relative
  to the plain cue-adjacent form — digit count, separators, spacing/gluing,
  cue language, cue distance, or cue strength (weak/absent cue documents are
  deliberate probes of the detector's cue dependence).
- Checksum-bearing values are always valid (mod-11 / Luhn); PII values are
  never reused across documents, with one recorded exception: the
  `bank_phone` slice reuses a value across its paired documents by design
  (the pair varies the cue, not the number; test-exempted).
- Verbatim rule, operationally: the document's source text is `annotated`
  with the markup tokens removed; a validator must be able to reconstruct
  every span from that stripped text (this is exactly what `parse_gold`
  round-trip tests enforce).

## Change control

- The gold set is versioned in `benchmark/gold.py`'s docstring; a change to
  `data/gold.jsonl` bumps that version and lands with its own adjudication or
  authoring record under `docs/decisions/`.
- Adjudication is review-then-fix: reviewers list findings against these
  rules; fixes are applied only for rule violations, never to make a document
  easier for the current detector.
- The blind set follows the same rules but is authored/reviewed only in
  isolated contexts and never opened afterward
  ([protocol](decisions/2026-07-28-blind-set-protocol.md)).
