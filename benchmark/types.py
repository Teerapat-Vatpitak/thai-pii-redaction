from __future__ import annotations

from dataclasses import dataclass


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
