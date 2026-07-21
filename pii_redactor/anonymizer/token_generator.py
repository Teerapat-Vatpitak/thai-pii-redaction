"""Bracket-token pseudonyms (e.g. [ชื่อ_1]) — the web AI-Guard default mode.

Explicit and visually robust for AI round-trips. The Thai label map is the
single source of truth (moved here from app/server.py during the core unify).
"""

from __future__ import annotations

TOKEN_LABEL: dict[str, str] = {
    "NAME": "ชื่อ",
    "SURNAME": "นามสกุล",
    "THAI_ID": "บัตรประชาชน",
    "PHONE": "โทรศัพท์",
    "EMAIL": "อีเมล",
    "ADDRESS": "ที่อยู่",
    "POSTAL_CODE": "รหัสไปรษณีย์",
    "MEDICAL_ID": "เลขเวชระเบียน",
    "BANK_ACCOUNT": "บัญชีธนาคาร",
    "CREDIT_CARD": "บัตรเครดิต",
    "DATE_OF_BIRTH": "วันเกิด",
    "PASSPORT": "พาสปอร์ต",
    "STUDENT_ID": "รหัสนักศึกษา",
    "VEHICLE_PLATE": "ทะเบียนรถ",
    "IBAN": "ไอแบน",
    "LOCATION": "สถานที่",
    "DATE": "วันที่",
    "ORGANIZATION": "องค์กร",
    "ID_NUMBER": "รหัสอ้างอิง",
}


def generate_token(data_type: str, ordinal: int) -> str:
    """Return the bracket token for the ordinal-th distinct value of a type."""
    label = TOKEN_LABEL.get(data_type, data_type)
    return f"[{label}_{ordinal}]"
