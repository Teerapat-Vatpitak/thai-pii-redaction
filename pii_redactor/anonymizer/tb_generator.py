"""Thai name/address pseudonym generator using hardcoded pools (no LLM).

Deterministic: same (data_type, original, salt) -> same pseudonym.
"""
from __future__ import annotations

import hashlib
import random

MALE_NAMES = [
    "สมชาย", "วิทยา", "ประเสริฐ", "ชัยวัฒน์", "ธนพล", "วรชัย", "ปิยะ", "สุรชัย",
    "ณัฐพล", "ภาณุ", "ธีรวุฒิ", "พงศ์พิชญ์", "ชนะชัย", "กิตติ", "รัฐพล",
    "อนุชา", "ประพันธ์", "สิทธิชัย", "วิโรจน์", "สุรศักดิ์", "ธนา", "ชำนาญ",
    "บุญชัย", "ไพบูลย์", "สายัณห์", "พิทักษ์", "ศักดิ์ชาย", "ณัฐกิตติ์", "สรายุทธ",
    "วิษณุ", "ปรีชา", "ยุทธชัย", "ธีรพงศ์", "เกษม", "บุญมา", "สุภัทร",
    "ไกรสร", "อภิชาต", "วัชรพล", "นพดล",
]
FEMALE_NAMES = [
    "สมหญิง", "วิภา", "นภา", "กานดา", "สุภาพร", "วรรณา", "อรทัย", "มาลี",
    "ชุติมา", "นิภา", "สุดา", "กัญญา", "ลลิตา", "พัชรา", "อุษา",
    "นุชนาถ", "สุนิสา", "ศิริพร", "วิมล", "รัตนา", "พรพิมล", "นภัสวรรณ",
    "ชนิดา", "ทิพย์วรรณ", "ลดาวัลย์", "สิริพร", "มณีรัตน์", "ภัทราวดี",
    "ปริศนา", "อัญชลี", "สาวิตรี", "นิตยา", "กิตติยา", "สุภาวดี",
    "พรทิพย์", "รุ่งนภา", "วิลาวัณย์", "ศิริมา", "อมรรัตน์", "พิมพ์ใจ",
]
SURNAMES = [
    "สมบูรณ์", "รักไทย", "ใจดี", "มีสุข", "พงษ์สวัสดิ์", "บุญมาก", "ศรีสุข",
    "วงษ์ทอง", "เจริญสุข", "ทองคำ", "ศิริพงษ์", "ชัยมงคล", "พิมพ์ทอง",
    "บุญโต", "สุขสม", "ดวงดี", "สายทอง", "นาคสุวรรณ", "พลอยงาม",
    "แก้วใส", "เพชรสุข", "มณีรัตน์", "ทรัพย์สมบูรณ์", "ปิ่นทอง",
    "บุษบา", "ลดาวัลย์", "สุวรรณ", "เงินดี", "ทองดี", "ขาวสะอาด",
    "เขียวสด", "ฟ้าใส", "แสงทอง", "พูนทรัพย์", "สวัสดี", "รุ่งเรือง",
    "เจริญ", "มั่นคง", "ดีงาม", "สุขใจ",
]
DISTRICTS = [
    "เขตบางรัก", "เขตสาทร", "เขตพระนคร", "เขตดุสิต", "เขตบางกอกน้อย",
    "เขตบางกอกใหญ่", "เขตพระโขนง", "เขตลาดกระบัง", "เขตมีนบุรี",
    "เขตบึงกุ่ม", "อำเภอเมือง", "อำเภอบางพลี", "อำเภอสามพราน",
]


def _seeded_rng(salt: str, original: str) -> random.Random:
    seed = int.from_bytes(
        hashlib.sha256(f"{salt}:{original}".encode()).digest()[:4],
        "big",
    )
    return random.Random(seed)


def generate_tb(
    data_type: str,
    context_with_blank: str,
    *,
    salt: str,
    original: str,
) -> str:
    """Generate a pseudonym for a text-based PII entity.

    Args:
        data_type: "NAME" | "SURNAME" | "ADDRESS" | "DATE_OF_BIRTH" | etc.
        context_with_blank: sentence(s) with the original PII replaced by '___'
        salt: per-process random salt
        original: original PII (for seeding; never sent to LLM)

    Returns:
        A realistic Thai fake value
    """
    rng = _seeded_rng(salt, original)

    if data_type == "NAME":
        if "นาย" in context_with_blank:
            return rng.choice(MALE_NAMES)
        elif "นาง" in context_with_blank:
            return rng.choice(FEMALE_NAMES)
        else:
            return rng.choice(MALE_NAMES + FEMALE_NAMES)

    elif data_type == "SURNAME":
        return rng.choice(SURNAMES)

    elif data_type == "ADDRESS":
        num = rng.randint(1, 999)
        district = rng.choice(DISTRICTS)
        return f"{num} {district}"

    elif data_type == "DATE_OF_BIRTH":
        day = rng.randint(1, 28)
        month = rng.randint(1, 12)
        year = rng.randint(2490, 2540)
        return f"{day:02d}/{month:02d}/{year}"

    else:
        return f"[REDACTED_{data_type}]"
