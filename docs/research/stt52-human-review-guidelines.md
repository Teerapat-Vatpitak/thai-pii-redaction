# STT52 second-human review guide

This is a blind review of a sample from gold-v3. The sample uses fake PII.
Do not open the gold file or ask to see its labels before you finish.

## What to mark

Use only these 11 types:

- `NAME`: a full personal name.
- `ADDRESS`: a specific address.
- `PHONE`: a phone number, but not a public short code.
- `EMAIL`: an email address.
- `THAI_ID`: a Thai national ID.
- `BANK_ACCOUNT`: a bank account number.
- `CREDIT_CARD`: a payment card number.
- `DATE_OF_BIRTH`: a date linked to birth.
- `PASSPORT`: a passport number.
- `VEHICLE_PLATE`: a vehicle plate.
- `STUDENT_ID`: a student ID.

Mark the value only. Keep labels, titles, and punctuation outside the mark.
Do not mark a value inside another marked value.

Example:

```text
ชื่อ [[NAME|สมชาย ใจดี]] โทร [[PHONE|0812345678]]
```

## How to finish

For each document:

1. Do not change the text.
2. Add `[[TYPE|value]]` around each value.
3. If there is no value, leave the text as it is.
4. Set `reviewed` to `true`.

At the top, add an opaque code such as `R02A`. Do not use a name or e-mail.
Set all three checks to `true` only when they are true.
