"""Value-free failure metadata for an explicitly selected remote NER."""

from __future__ import annotations

from typing import Literal

NERFailureCode = Literal["ner_incomplete", "ner_unavailable"]
NERFailureCategory = Literal["configuration", "dependency", "network", "upstream"]

_UNAVAILABLE_CATEGORIES = {
    "configuration",
    "dependency",
    "network",
    "upstream",
}


class NERFailureError(RuntimeError):
    """A failed explicit NER request with only fixed public metadata."""

    def __init__(
        self,
        code: NERFailureCode,
        *,
        category: NERFailureCategory,
        count: int = 1,
    ) -> None:
        if code not in {"ner_incomplete", "ner_unavailable"}:
            raise ValueError("unsupported NER failure code")
        if code == "ner_incomplete":
            safe_category: NERFailureCategory = "upstream"
        elif category in _UNAVAILABLE_CATEGORIES:
            safe_category = category
        else:
            safe_category = "dependency"
        self.code: NERFailureCode = code
        self.category: NERFailureCategory = safe_category
        self.retryable = code == "ner_unavailable" and safe_category in {
            "network",
            "upstream",
        }
        safe_count = count if type(count) is int and count >= 0 else 0
        self.count = max(1, safe_count) if code == "ner_incomplete" else safe_count
        super().__init__(code)


def ner_failure_metadata(
    error: NERFailureError,
) -> tuple[NERFailureCode, NERFailureCategory, int]:
    """Copy and normalize fixed fields before the source graph is discarded."""

    try:
        code = object.__getattribute__(error, "code")
        category = object.__getattribute__(error, "category")
        count = object.__getattribute__(error, "count")
        normalized = NERFailureError(code, category=category, count=count)
    except BaseException:
        normalized = NERFailureError(
            "ner_unavailable",
            category="dependency",
            count=0,
        )
    return normalized.code, normalized.category, normalized.count
