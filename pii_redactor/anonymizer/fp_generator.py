"""Format-preserving pseudonym generator for structured PII entities.

Deterministic: same (data_type, original, salt) -> same pseudonym always.
Uses seeded random: seed = int.from_bytes(SHA256(f"{salt}:{original}").digest()[:4], 'big')
"""
from __future__ import annotations

import hashlib
import random


def _seeded_rng(salt: str, original: str, attempt: int = 0) -> random.Random:
    # attempt=0 keeps the historical seed so existing pseudonyms stay stable;
    # attempt>0 re-rolls deterministically when a collision must be resolved.
    material = f"{salt}:{original}" if attempt == 0 else f"{salt}:{original}:{attempt}"
    seed = int.from_bytes(
        hashlib.sha256(material.encode()).digest()[:4],
        "big",
    )
    return random.Random(seed)


def _gen_thai_id(rng: random.Random) -> str:
    """Generate a valid Thai ID (passes mod-11 checksum)."""
    digits = [rng.randint(1, 9)]
    digits += [rng.randint(0, 9) for _ in range(11)]
    weights = [13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(d * w for d, w in zip(digits, weights))
    check = (11 - (total % 11)) % 10
    return "".join(str(d) for d in digits) + str(check)


def _gen_phone(rng: random.Random) -> str:
    """Generate Thai mobile: 0[6-9]X-XXX-XXXX."""
    prefix = rng.choice(["06", "07", "08", "09"])
    mid = rng.randint(0, 9)
    rest = "".join(str(rng.randint(0, 9)) for _ in range(7))
    return f"{prefix}{mid}-{rest[:3]}-{rest[3:]}"


def _gen_email(rng: random.Random) -> str:
    """Generate fake email: [name].[number]@example.com"""
    NAMES = [
        "alice", "bob", "carol", "dave", "eve", "frank", "grace", "henry",
        "iris", "jack", "kate", "leo", "mary", "nora", "oscar", "paul",
    ]
    DOMAINS = ["example.com", "test.co.th", "mail.example.org", "fake.ac.th"]
    name = rng.choice(NAMES)
    num = rng.randint(100, 9999)
    domain = rng.choice(DOMAINS)
    return f"{name}.{num}@{domain}"


def _gen_bank_account(rng: random.Random, original: str) -> str:
    """Generate bank account matching original length."""
    length = len(original.replace("-", "").replace(" ", ""))
    return "".join(str(rng.randint(0, 9)) for _ in range(length))


def _gen_date(rng: random.Random, original: str) -> str:
    """Generate date in same format as original."""
    sep = "/" if "/" in original else "-"
    day = rng.randint(1, 28)
    month = rng.randint(1, 12)
    parts = original.replace("-", "/").split("/")
    if len(parts) == 3 and len(parts[2]) == 4:
        year = rng.randint(2490, 2560)
    else:
        year = rng.randint(60, 99)
    return f"{day:02d}{sep}{month:02d}{sep}{year}"


def _gen_credit_card(rng: random.Random) -> str:
    """Generate Luhn-valid 16-digit credit card number."""
    digits = [rng.randint(0, 9) for _ in range(15)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - (total % 10)) % 10
    all_digits = digits + [check]
    s = "".join(str(d) for d in all_digits)
    return f"{s[:4]}-{s[4:8]}-{s[8:12]}-{s[12:]}"


def _gen_passport(rng: random.Random) -> str:
    """Generate Thai passport: AA followed by 7 digits."""
    letters = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(2))
    nums = "".join(str(rng.randint(0, 9)) for _ in range(7))
    return letters + nums


def _gen_vehicle_plate(rng: random.Random) -> str:
    """Generate Thai vehicle plate: 2 Thai consonants + 4 digits."""
    CONSONANTS = "กขฃคฅฆงจฉชซฌญฎฏฐฑฒณดตถทธนบปผฝพฟภมยรลวศษสหฬอฮ"
    c1 = rng.choice(CONSONANTS)
    c2 = rng.choice(CONSONANTS)
    nums = "".join(str(rng.randint(0, 9)) for _ in range(4))
    return f"{c1}{c2} {nums}"


def _gen_generic(rng: random.Random, original: str) -> str:
    """Fallback: same length, same char class (digit->digit, letter->letter)."""
    result = []
    for ch in original:
        if ch.isdigit():
            result.append(str(rng.randint(0, 9)))
        elif ch.isalpha():
            result.append(rng.choice("abcdefghijklmnopqrstuvwxyz"))
        else:
            result.append(ch)
    return "".join(result)


def generate_fp(data_type: str, original: str, *, salt: str, attempt: int = 0) -> str:
    """Generate a format-preserving pseudonym for a given entity.

    Deterministic: same (data_type, original, salt, attempt) -> same pseudonym.
    Uses seeded random: seed = int.from_bytes(SHA256(f"{salt}:{original}").digest()[:4], 'big')

    Args:
        data_type: entity type (THAI_ID, PHONE, EMAIL, etc.)
        original: the real PII value
        salt: per-process random salt (never stored)
        attempt: collision re-roll counter; 0 = the stable deterministic value

    Returns:
        A format-preserving fake string
    """
    rng = _seeded_rng(salt, original, attempt)

    if data_type == "THAI_ID":
        return _gen_thai_id(rng)
    elif data_type == "PHONE":
        return _gen_phone(rng)
    elif data_type == "EMAIL":
        return _gen_email(rng)
    elif data_type == "BANK_ACCOUNT":
        return _gen_bank_account(rng, original)
    elif data_type == "DATE_OF_BIRTH":
        return _gen_date(rng, original)
    elif data_type == "CREDIT_CARD":
        return _gen_credit_card(rng)
    elif data_type == "PASSPORT":
        return _gen_passport(rng)
    elif data_type == "VEHICLE_PLATE":
        return _gen_vehicle_plate(rng)
    elif data_type == "IBAN":
        return _gen_generic(rng, original)
    elif data_type == "STUDENT_ID":
        return "".join(str(rng.randint(0, 9)) for _ in range(len(original)))
    elif data_type == "DATE":
        return _gen_date(rng, original)
    elif data_type == "ID_NUMBER":
        return "".join(str(rng.randint(0, 9)) for _ in range(len(original)))
    else:
        return _gen_generic(rng, original)
