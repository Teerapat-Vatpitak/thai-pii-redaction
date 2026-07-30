from __future__ import annotations

from dataclasses import dataclass

SHARED_ENTITY_TYPES = (
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
)
SHARED_ENTITY_TYPE_SET = frozenset(SHARED_ENTITY_TYPES)
OUT_OF_SCHEME_TYPE = "OUT_OF_SCHEME"


@dataclass(frozen=True)
class GoldSpan:
    start: int
    end: int
    entity_type: str


@dataclass
class Sample:
    text: str
    spans: list[GoldSpan]
    template_id: str
    slice: str
