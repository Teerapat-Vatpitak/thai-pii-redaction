"""Deterministic synthetic Thai PII corpus with exact ground-truth spans.

Values reuse the existing generators (single source of truth for formats), so
a synthetic THAI_ID passes the same mod-11 the detector checks, etc. Two slices:
`core` (spread across entity types) and `hard_case` (known recall-leak shapes).
"""

from __future__ import annotations

import random

from pii_redactor.anonymizer import fp_generator as fg
from pii_redactor.anonymizer.tb_generator import (
    DISTRICTS,
    FEMALE_NAMES,
    MALE_NAMES,
    SURNAMES,
)

from .types import GoldSpan, Sample

ENTITY_TYPES = [
    "THAI_ID",
    "PHONE",
    "EMAIL",
    "BANK_ACCOUNT",
    "CREDIT_CARD",
    "PASSPORT",
    "VEHICLE_PLATE",
    "STUDENT_ID",
    "DATE_OF_BIRTH",
    "NAME",
    "ADDRESS",
]


def _sample_value(entity_type: str, rng: random.Random) -> str:
    if entity_type == "THAI_ID":
        return fg._gen_thai_id(rng)
    if entity_type == "CREDIT_CARD":
        return fg._gen_credit_card(rng)
    if entity_type == "PHONE":
        return fg._gen_phone(rng)
    if entity_type == "PASSPORT":
        return fg._gen_passport(rng)
    if entity_type == "VEHICLE_PLATE":
        return fg._gen_vehicle_plate(rng)
    if entity_type == "EMAIL":
        return fg._gen_email(rng)
    if entity_type == "BANK_ACCOUNT":
        return fg._gen_bank_account(rng, "000-0-00000-0")
    if entity_type == "STUDENT_ID":
        # 8 digits: unambiguous vs BANK_ACCOUNT (10 digits, higher detector score)
        return "".join(str(rng.randint(0, 9)) for _ in range(8))
    if entity_type == "DATE_OF_BIRTH":
        return fg._gen_date(rng, "01/01/2530")
    if entity_type == "NAME":
        male = rng.random() < 0.5
        title = "นาย" if male else rng.choice(["นาง", "นางสาว"])
        first = rng.choice(MALE_NAMES if male else FEMALE_NAMES)
        return f"{title}{first} {rng.choice(SURNAMES)}"
    if entity_type == "ADDRESS":
        num = rng.randint(1, 999)
        district = rng.choice(DISTRICTS)
        # Half the addresses (by num parity) take a "ซอย N" soi form so the
        # corpus exercises the plate-precision trap where ซอย + digits looks like
        # a VEHICLE_PLATE (guarded by fp_detector._PLATE_STOPWORDS). Derived from
        # the same two rng draws as before -- no extra draw -- so every other
        # entity value in the corpus stays byte-identical.
        if num % 2 == 0:
            return f"{num} ซอย {num % 60 + 1} {district}"
        return f"{num} {district}"
    raise ValueError(entity_type)


def _intl_phone(rng: random.Random) -> str:
    # +66 mobile carries 9 digits (drops the national leading 0)
    body = "".join(str(rng.randint(0, 9)) for _ in range(9))
    return f"+66{body}"


# (template_id, format_string, [(placeholder_key, entity_type), ...])
_CORE_TEMPLATES = [
    (
        "email_sick",
        "เรียนหัวหน้า {name} ขอลาป่วยวันนี้ ติดต่อกลับได้ที่ {phone} หรืออีเมล {email}",
        [("name", "NAME"), ("phone", "PHONE"), ("email", "EMAIL")],
    ),
    (
        "gov_form",
        "ข้าพเจ้า {name} เลขบัตรประชาชน {thai_id} เกิดวันที่ {dob} อยู่บ้านเลขที่ {addr}",
        [("name", "NAME"), ("thai_id", "THAI_ID"), ("dob", "DATE_OF_BIRTH"), ("addr", "ADDRESS")],
    ),
    (
        "bank_complaint",
        "ผม {name} บัญชีธนาคาร {bank} บัตรเครดิต {cc} ขอร้องเรียนธุรกรรม",
        [("name", "NAME"), ("bank", "BANK_ACCOUNT"), ("cc", "CREDIT_CARD")],
    ),
    (
        "apply",
        "ผู้สมัคร {name} หนังสือเดินทาง {passport} ทะเบียนรถ {plate} รหัสนักศึกษา {sid}",
        [
            ("name", "NAME"),
            ("passport", "PASSPORT"),
            ("plate", "VEHICLE_PLATE"),
            ("sid", "STUDENT_ID"),
        ],
    ),
]

# hard-case templates mirror tests/test_recall_leaks.py: the value is glued to
# Thai text or in +66 form -- shapes that used to slip past the detectors.
_HARD_TEMPLATES = [
    ("glued_id", "เลขบัตรประชาชน{thai_id}ครับ", [("thai_id", "THAI_ID")]),
    ("glued_email", "อีเมลผมคือ{email}ครับ", [("email", "EMAIL")]),
    ("intl_phone", "โทรหาผมที่ {phone_intl} ได้เลย", [("phone_intl", "PHONE")]),
]

_SLOT_KEY_TO_TYPE = {
    "name": "NAME",
    "phone": "PHONE",
    "email": "EMAIL",
    "thai_id": "THAI_ID",
    "dob": "DATE_OF_BIRTH",
    "addr": "ADDRESS",
    "bank": "BANK_ACCOUNT",
    "cc": "CREDIT_CARD",
    "passport": "PASSPORT",
    "plate": "VEHICLE_PLATE",
    "sid": "STUDENT_ID",
    "phone_intl": "PHONE",
}


def _render(template, rng: random.Random, slice_: str) -> Sample:
    tid, fmt, slots = template
    text = fmt
    spans = []
    for key, etype in slots:
        if key == "phone_intl":
            value = _intl_phone(rng)
        else:
            value = _sample_value(etype, rng)
        marker = "{" + key + "}"
        idx = text.index(marker)
        text = text[:idx] + value + text[idx + len(marker) :]
        spans.append(GoldSpan(idx, idx + len(value), etype))
    return Sample(text=text, spans=spans, template_id=tid, slice=slice_)


def build_corpus(seed: int = 42, size: int = 200) -> list[Sample]:
    rng = random.Random(seed)
    samples: list[Sample] = []
    n_hard = max(len(_HARD_TEMPLATES), size // 5)
    for i in range(size):
        if i < n_hard:
            template = _HARD_TEMPLATES[rng.randrange(len(_HARD_TEMPLATES))]
            samples.append(_render(template, rng, "hard_case"))
        else:
            template = _CORE_TEMPLATES[rng.randrange(len(_CORE_TEMPLATES))]
            samples.append(_render(template, rng, "core"))
    return samples
