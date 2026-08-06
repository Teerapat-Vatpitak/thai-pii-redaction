"""Session-namespaced bracket tokens used by token-mode pseudonymization.

Explicit and visually robust for AI round-trips. The Thai label map is the
single source of truth (moved here from app/server.py during the core unify).
"""

from __future__ import annotations

import re
import secrets

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

TOKEN_NAMESPACE_BITS = 64
TOKEN_NAMESPACE_LENGTH = 25
TOKEN_NONCE_LENGTH = 20
_TOKEN_NAMESPACE_ALPHABET = "abcdef"
_TOKEN_NONCE_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_TOKEN_DATA_TYPE_BY_LABEL = {label: data_type for data_type, label in TOKEN_LABEL.items()}
_TOKEN_NAMESPACE = re.compile(r"[a-f]{25}")
_TOKEN_NONCE = re.compile(r"[a-z]{20}")
_TOKEN_ORDINAL = re.compile(r"[1-9][0-9]*")
_TOKEN_MAX_LENGTH = 130


def new_token_namespace() -> str:
    """Return a random, non-secret generation tag for one vault lifecycle."""
    value = secrets.randbits(TOKEN_NAMESPACE_BITS)
    encoded: list[str] = []
    for _ in range(TOKEN_NAMESPACE_LENGTH):
        value, digit = divmod(value, len(_TOKEN_NAMESPACE_ALPHABET))
        encoded.append(_TOKEN_NAMESPACE_ALPHABET[digit])
    return "".join(reversed(encoded))


def is_valid_token_namespace(namespace: str) -> bool:
    """Return whether a namespace has the exact product shape."""
    return _TOKEN_NAMESPACE.fullmatch(namespace) is not None


def new_token_nonce() -> str:
    """Return an unpredictable, non-secret identity for one minted token."""
    return "".join(secrets.choice(_TOKEN_NONCE_ALPHABET) for _ in range(TOKEN_NONCE_LENGTH))


def _token_parts(candidate: str) -> tuple[str, str, str, int] | None:
    """Parse one exact current token without interpreting its label."""
    if (
        not isinstance(candidate, str)
        or len(candidate) > _TOKEN_MAX_LENGTH
        or not candidate.startswith("[")
        or not candidate.endswith("]")
    ):
        return None
    inner = candidate[1:-1]
    if any(char in inner for char in "[]\r\n"):
        return None
    identity, ordinal_separator, ordinal_text = inner.rpartition("_")
    namespaced_identity, nonce_separator, nonce = identity.rpartition("_")
    label, namespace_separator, namespace = namespaced_identity.rpartition("_")
    if not ordinal_separator or not nonce_separator or not namespace_separator or not label:
        return None
    if _TOKEN_ORDINAL.fullmatch(ordinal_text) is None:
        return None
    if not is_valid_token_namespace(namespace):
        return None
    if _TOKEN_NONCE.fullmatch(nonce) is None:
        return None
    return label, namespace, nonce, int(ordinal_text)


def token_namespace_from_candidate(candidate: str) -> str | None:
    """Return an exact current token's vault-generation tag, if present."""
    parts = _token_parts(candidate)
    return None if parts is None else parts[1]


def token_data_type_from_candidate(candidate: str) -> str | None:
    """Return the supported data type encoded by one exact current token."""
    parts = _token_parts(candidate)
    return None if parts is None else _TOKEN_DATA_TYPE_BY_LABEL.get(parts[0])


def token_ordinal_from_candidate(
    candidate: str,
    data_type: str,
    *,
    allow_legacy: bool = False,
) -> int | None:
    """Return one exact token's ordinal when its label matches ``data_type``."""
    if not isinstance(candidate, str) or len(candidate) > _TOKEN_MAX_LENGTH:
        return None
    label = TOKEN_LABEL.get(data_type, data_type)
    parts = _token_parts(candidate)
    if parts is not None and parts[0] == label:
        return parts[3]
    if not allow_legacy:
        return None
    prefix = f"[{label}_"
    if not candidate.startswith(prefix) or not candidate.endswith("]"):
        return None
    ordinal_text = candidate[len(prefix) : -1]
    if _TOKEN_ORDINAL.fullmatch(ordinal_text) is None:
        return None
    return int(ordinal_text)


def generate_token(
    data_type: str,
    ordinal: int,
    *,
    namespace: str,
    nonce: str,
) -> str:
    """Return one session-scoped bracket token."""
    if not is_valid_token_namespace(namespace):
        raise ValueError("invalid token namespace")
    if _TOKEN_NONCE.fullmatch(nonce) is None:
        raise ValueError("invalid token nonce")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ValueError("invalid token ordinal")
    label = TOKEN_LABEL.get(data_type, data_type)
    return f"[{label}_{namespace}_{nonce}_{ordinal}]"


def is_token_for_data_type(
    candidate: str,
    data_type: str,
    *,
    allow_legacy: bool = False,
) -> bool:
    """Return whether a caller-held token has a valid product shape."""
    if not isinstance(candidate, str) or len(candidate) > _TOKEN_MAX_LENGTH:
        return False
    label = TOKEN_LABEL.get(data_type, data_type)
    legacy_prefix = f"[{label}_"
    if (
        allow_legacy
        and candidate.startswith(legacy_prefix)
        and candidate.endswith("]")
        and _TOKEN_ORDINAL.fullmatch(candidate[len(legacy_prefix) : -1]) is not None
    ):
        return True
    parts = _token_parts(candidate)
    return parts is not None and parts[0] == label
