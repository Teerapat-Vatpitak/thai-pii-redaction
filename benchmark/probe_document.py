"""Measure what happens to a known set of fabricated values inside one document.

This is the instrument for the paired-probe step of the Thai government
document plan: take a document plus a JSON list of the field/value pairs it is
supposed to contain, and report six things about that document's trip through
the product.

    python -m benchmark.probe_document <document> <expectations.json> [--json out]

The six measurements, in the order they are reported:

1. extraction survival  -- did each expected value survive ingest at all
2. extraction order     -- did the values come out in the order they were placed
3. OCR character accuracy -- per-value edit distance (scans only)
4. legacy-11 detection  -- did detect_all find it, with the type the field claims
5. redaction coverage   -- share of the value's bboxes actually painted black
6. residual PII         -- is the value gone from the redacted output

Each measurement reports per value, not as a single total. A total hides which
value failed, and on a form the identity of the failing field is the finding.

WHY MEASUREMENT 6 IS THE DANGEROUS ONE
--------------------------------------
"The value is not in the redacted PDF's extracted text" is a claim a text
extractor can make for two completely different reasons: the value was really
removed, or the extractor cannot read the page. This project produces both
kinds of document. `redactor.py` flattens to an image, so the redacted output
has NO text layer at all and every text-only residual check passes vacuously.
And `thai_pdf_text.draw_text` writes an invisible real-character layer under
the shaped glyphs, which pdfplumber interleaves by coordinate -- so even a
document that HAS a text layer can return "081-234-5678" as
"008811--223344--55667788" and defeat a substring check.

So measurement 6 never reports a clean result it did not earn. It states how
many characters of text layer it actually read, marks the text arm `vacuous`
when there is nothing to read, and falls back on the rendered pixels
(measurement 5's black coverage plus an ink check in the strip above each box,
which is where a Thai ascender leaks past an under-padded rectangle) for the
part of the verdict that is actually evidence.

WHAT THIS INSTRUMENT CANNOT DO
------------------------------
- OCR can miss readable ink. A negative OCR result does not prove removal
  unless the source value also has aligned geometry and full pixel coverage.
- The ink check above each box stops at the redaction pad's boundary
  (REDACT_PAD_TOP_PT), because on tight leading anything beyond it is the
  legitimate previous line. A glyph fragment surviving further above the box
  than the pad reaches would need the OCR check above to be seen.
- Measurements 5 and 6 need aligned word boxes. Text PDFs get them from the
  text layer; scans get them from OCR.
- The column heuristic behind measurement 2 is a heuristic. An expectations
  file may declare `layout` and override it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The 11 types docs/annotation-guidelines.md defines. A field that claims a
# type outside this set is reported, never scored: the detector emits 18 types
# and the extra 7 are quasi-identifiers the corpora deliberately do not label,
# so calling them right or wrong here would invent a rule that document does
# not contain.
LEGACY_11 = frozenset(
    {
        "NAME",
        "ADDRESS",
        "PHONE",
        "EMAIL",
        "THAI_ID",
        "BANK_ACCOUNT",
        "CREDIT_CARD",
        "DATE_OF_BIRTH",
        "PASSPORT",
        "VEHICLE_PLATE",
        "STUDENT_ID",
    }
)

# A row's words are considered one horizontal run until a gap this wide opens
# up. Word spacing on the sample document runs 3-6pt and the widest legitimate
# label/value gap measured there is under 10pt, so 48pt (two thirds of an inch)
# only fires on something structural.
COLUMN_GAP_PT = 48.0

# Two words share a row if their vertical centres are within this fraction of
# the median glyph height.
ROW_TOLERANCE_RATIO = 0.6

# Pixel intensity (0-255, greyscale) at or below which a pixel counts as an
# opaque redaction box, and at or above which it counts as clean background.
# Anything strictly between the two is an anti-aliased glyph edge -- surviving
# ink. `redactor.py` writes a lossless palette image and PIL fills rectangles
# without anti-aliasing, so a solid box has no intermediate pixels of its own;
# the same thresholds are already used by tests/test_step12_redact_pdf.py.
INK_BLACK_MAX = 10
INK_WHITE_MIN = 250

# Height of the strip checked above each redacted word box, in PDF points.
# The known failure mode is a Thai tone mark or tall consonant rendering above
# the word bbox's nominal top and poking out of a too-tight rectangle
# (redactor.py carries REDACT_PAD_TOP_PT = 5.0 for exactly this). Only the top
# strip is checked: a left/right/bottom halo would sit on the unredacted field
# LABEL, which is legitimately inked and would make every value look like a
# leak. The strip must not be TALLER than the box's own top pad either: on
# tight leading (12pt text at 14-16pt spacing, the norm on dense Thai
# government forms) anything above the pad is the legitimate previous line,
# whose anti-aliased glyph edges would read as a leak on a perfectly covered
# value. So the strip inspects exactly the zone the pad owns — a correct paint
# leaves it solid black; a box painted short or in the wrong coordinate space
# leaves glyph edges in it. A test pins this to redactor.REDACT_PAD_TOP_PT.
INK_STRIP_PT = 5.0

# A value counts as fully covered at this black fraction. Not 1.0 exactly, so a
# single boundary pixel from integer truncation of the bbox does not read as a
# leak.
COVERAGE_FULL = 0.999

# Render scale, points -> pixels. Capped: rasterizing a large page at a high
# scale is how a probe run turns into a multi-gigabyte process.
DEFAULT_RENDER_SCALE = 2.0
MAX_RENDER_SCALE = 2.0

# Guard on the O(len(value) * len(text)) approximate-match DP in measurement 3.
MAX_EDIT_DISTANCE_CELLS = 20_000_000

# Use close OCR matches only when they are reliable.
OCR_ALIGNMENT_MIN_ACCURACY = 0.8


@dataclass(frozen=True)
class ExpectedValue:
    """One fabricated field/value pair the document is supposed to contain."""

    index: int
    field: str
    value: str
    type: str
    region: dict[str, float | int] | None = None


@dataclass(frozen=True)
class AlignedWord:
    """A word bbox pinned to its character span in the extracted text."""

    start: int
    end: int
    page: int
    x: float
    y: float
    width: float
    height: float


# ── expectations file ──────────────────────────────────────────────────────


def load_expectations(path: str | Path) -> dict[str, Any]:
    """Read and validate an expectations JSON file.

    Shape::

        {
          "layout": "single_column" | "multi_column" | "unknown",   # optional
          "fields": [{
            "field": "...", "value": "...", "type": "NAME",
            "region": {"page": 1, "x": 10, "y": 20, "width": 30, "height": 12}
          }, ...],
          "decoys": ["value that must NOT be in the document", ...]  # optional
        }

    `fields` order is the placement order measurement 2 compares against.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), list):
        raise ValueError("expectations file must be an object with a 'fields' list")

    values: list[ExpectedValue] = []
    for i, item in enumerate(raw["fields"]):
        if not isinstance(item, dict) or not item.get("value"):
            raise ValueError(f"fields[{i}] must be an object with a non-empty 'value'")
        region = item.get("region")
        if region is not None:
            keys = ("page", "x", "y", "width", "height")
            if not isinstance(region, dict) or any(key not in region for key in keys):
                raise ValueError(f"fields[{i}].region is incomplete")
            page = region["page"]
            numbers = [region[key] for key in keys[1:]]
            if (
                type(page) is not int
                or page < 1
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in numbers
                )
                or region["x"] < 0
                or region["y"] < 0
                or region["width"] <= 0
                or region["height"] <= 0
            ):
                raise ValueError(f"fields[{i}].region has invalid coordinates")
            region = {
                "page": page,
                "x": float(region["x"]),
                "y": float(region["y"]),
                "width": float(region["width"]),
                "height": float(region["height"]),
            }
        values.append(
            ExpectedValue(
                index=i,
                field=str(item.get("field", f"field_{i}")),
                value=str(item["value"]),
                type=str(item.get("type", "")).upper(),
                region=region,
            )
        )
    if not values:
        raise ValueError("expectations file lists no fields")

    decoys = [str(d) for d in raw.get("decoys", []) if str(d)]
    layout = str(raw.get("layout", "unknown"))
    return {"values": values, "decoys": decoys, "layout": layout, "meta": raw.get("meta", {})}


# ── shared helpers ─────────────────────────────────────────────────────────


def align_words(full_text: str, word_bboxes) -> tuple[list[AlignedWord], int]:
    """Pin each WordBbox to its character span in the extracted text.

    Both `extract_text()` and `extract_words()` derive from the same coordinate
    ordered character stream, so walking the word list forward and consuming
    the text with a moving cursor recovers the offsets. Returns
    (aligned, unaligned_count); a word whose text cannot be found ahead of the
    cursor is dropped and counted rather than guessed at, so a caller can see
    how much of the geometry is actually trustworthy.
    """
    aligned: list[AlignedWord] = []
    cursor = 0
    unaligned = 0
    for wb in word_bboxes:
        idx = full_text.find(wb.text, cursor)
        if idx < 0:
            unaligned += 1
            continue
        aligned.append(
            AlignedWord(
                start=idx,
                end=idx + len(wb.text),
                page=wb.page,
                x=wb.x,
                y=wb.y,
                width=wb.width,
                height=wb.height,
            )
        )
        cursor = idx + len(wb.text)
    return aligned, unaligned


def words_for_span(aligned: list[AlignedWord], start: int, end: int) -> list[AlignedWord]:
    """Every aligned word whose character span overlaps [start, end)."""
    return [w for w in aligned if w.start < end and start < w.end]


def detect_columns(word_bboxes) -> dict[str, Any]:
    """Heuristic: does this page's geometry read as one column or several?

    Groups words into rows by vertical centre, then looks for a horizontal gap
    inside a row wide enough to be structural rather than word spacing. Reports
    the evidence (row count, widest gap, how many rows split) alongside the
    verdict so the verdict can be argued with.
    """
    words = [w for w in word_bboxes if w.width > 0 and w.height > 0]
    if not words:
        return {
            "verdict": "unknown",
            "reason": "no word geometry available (plain-text source, or extraction returned no boxes)",
            "rows": 0,
            "wide_gap_rows": 0,
            "max_gap_pt": None,
        }

    heights = sorted(w.height for w in words)
    median_height = heights[len(heights) // 2]
    tolerance = max(median_height * ROW_TOLERANCE_RATIO, 1.0)

    rows: list[list[Any]] = []
    for w in sorted(words, key=lambda w: (w.page, w.y + w.height / 2)):
        centre = w.y + w.height / 2
        if rows and rows[-1][0].page == w.page:
            last_centre = rows[-1][0].y + rows[-1][0].height / 2
            if abs(centre - last_centre) <= tolerance:
                rows[-1].append(w)
                continue
        rows.append([w])

    wide_gap_rows = 0
    max_gap = 0.0
    for row in rows:
        ordered = sorted(row, key=lambda w: w.x)
        row_max = 0.0
        for a, b in zip(ordered, ordered[1:]):
            row_max = max(row_max, b.x - (a.x + a.width))
        max_gap = max(max_gap, row_max)
        if row_max > COLUMN_GAP_PT:
            wide_gap_rows += 1

    verdict = "single_column" if wide_gap_rows == 0 else "multi_column_suspected"
    return {
        "verdict": verdict,
        "reason": (
            f"{wide_gap_rows} of {len(rows)} rows carry an intra-row gap wider than "
            f"{COLUMN_GAP_PT:g}pt (widest gap seen: {max_gap:.1f}pt)"
        ),
        "rows": len(rows),
        "wide_gap_rows": wide_gap_rows,
        "max_gap_pt": round(max_gap, 2),
    }


def approx_substring_distance(needle: str, haystack: str) -> tuple[int, int, int]:
    """Smallest edit distance between `needle` and any substring of `haystack`.

    Sellers' variant of Levenshtein: the first DP row is zeroed so a match may
    start anywhere, and the answer is the minimum of the last row. Returns
    (distance, start, end) of the best-matching substring. Used to score OCR
    character accuracy, where the value is present but misread and a plain
    substring search reports nothing at all.
    """
    n, m = len(needle), len(haystack)
    if n == 0:
        return 0, 0, 0
    if m == 0:
        return n, 0, 0

    prev_d = [0] * (m + 1)
    prev_s = list(range(m + 1))
    for i in range(1, n + 1):
        cur_d = [i] + [0] * m
        cur_s = [0] * (m + 1)
        ch = needle[i - 1]
        for j in range(1, m + 1):
            sub = prev_d[j - 1] + (0 if haystack[j - 1] == ch else 1)
            dele = prev_d[j] + 1
            ins = cur_d[j - 1] + 1
            best = min(sub, dele, ins)
            cur_d[j] = best
            if best == sub:
                cur_s[j] = prev_s[j - 1]
            elif best == dele:
                cur_s[j] = prev_s[j]
            else:
                cur_s[j] = cur_s[j - 1]
        prev_d, prev_s = cur_d, cur_s

    end = min(range(m + 1), key=lambda j: (prev_d[j], j))
    return prev_d[end], prev_s[end], end


# ── measurement 1: extraction survival ─────────────────────────────────────


def measure_extraction(values: list[ExpectedValue], text: str) -> dict[str, Any]:
    """Per expected value: did it survive ingest, and where did it land."""
    rows = []
    claimed: list[tuple[int, int]] = []
    for v in values:
        start, end = _find_unclaimed_exact(text, v.value, claimed)
        method = "exact"
        if start < 0:
            # A value split by a line wrap comes back with different internal
            # whitespace. Retry with runs of whitespace made equivalent before
            # calling it lost -- but say which arm matched, because a
            # whitespace-normalized hit means the PDF broke the value.
            start, end = _find_whitespace_insensitive(text, v.value, claimed)
            method = "whitespace_normalized" if start >= 0 else "none"
        if start >= 0:
            claimed.append((start, end))
        rows.append(
            {
                "index": v.index,
                "field": v.field,
                "value": v.value,
                "type": v.type,
                "found": start >= 0,
                "match": method,
                "start": start if start >= 0 else None,
                "end": end if start >= 0 else None,
            }
        )
    found = sum(1 for r in rows if r["found"])
    return {"total": len(rows), "found": found, "missing": len(rows) - found, "values": rows}


def _range_is_free(start: int, end: int, claimed: list[tuple[int, int]]) -> bool:
    return start < end and all(
        end <= used_start or start >= used_end for used_start, used_end in claimed
    )


def _find_unclaimed_exact(
    text: str,
    value: str,
    claimed: list[tuple[int, int]],
) -> tuple[int, int]:
    start = text.find(value)
    while start >= 0:
        end = start + len(value)
        if _range_is_free(start, end, claimed):
            return start, end
        start = text.find(value, start + 1)
    return -1, -1


def _find_whitespace_insensitive(
    text: str,
    value: str,
    claimed: list[tuple[int, int]] | None = None,
) -> tuple[int, int]:
    """Locate `value` in `text` treating any whitespace run as equivalent.

    Returns (start, end) offsets into the ORIGINAL text, or (-1, -1).
    """
    pattern = r"\s+".join(re.escape(part) for part in value.split())
    if not pattern:
        return -1, -1
    claimed = claimed or []
    for match in re.finditer(pattern, text):
        if _range_is_free(match.start(), match.end(), claimed):
            return match.start(), match.end()
    return -1, -1


# ── measurement 2: extraction order ────────────────────────────────────────


def measure_order(
    extraction: dict[str, Any], columns: dict[str, Any], declared_layout: str
) -> dict[str, Any]:
    """Compare the order values came out in against the order they were placed.

    Reported as the permutation plus its inversion count (Kendall tau
    distance). On a single-column document the two orders agree by
    construction, so the number describes the document rather than the
    extractor -- that case is called out instead of being quoted as a result.
    """
    placed = [r for r in extraction["values"] if r["found"]]
    by_offset = sorted(placed, key=lambda r: r["start"])
    permutation = [r["index"] for r in by_offset]

    inversions = sum(
        1
        for i in range(len(permutation))
        for j in range(i + 1, len(permutation))
        if permutation[i] > permutation[j]
    )
    k = len(permutation)
    max_inversions = k * (k - 1) // 2

    layout = declared_layout if declared_layout != "unknown" else columns["verdict"]
    layout_source = (
        "declared in the expectations file" if declared_layout != "unknown" else "heuristic"
    )

    if k < 2:
        meaningful, why = False, f"only {k} value(s) were found; an order needs at least 2"
    elif layout == "single_column":
        meaningful, why = (
            False,
            "the source reads as a single column, so placement order and extraction order "
            "agree by construction -- this number says nothing about the extractor",
        )
    else:
        meaningful, why = True, f"layout is {layout!r} ({layout_source})"

    return {
        "placed_order": [r["index"] for r in placed],
        "extracted_order": permutation,
        "inversions": inversions,
        "max_inversions": max_inversions,
        "normalized_inversions": (inversions / max_inversions) if max_inversions else None,
        "layout": layout,
        "layout_source": layout_source,
        "columns": columns,
        "meaningful": meaningful,
        "reason": why,
    }


# ── measurement 3: OCR character accuracy ──────────────────────────────────


def _ocr_origin_view(
    text: str,
    meta: dict[str, Any],
) -> tuple[str, list[tuple[int, int, int]]]:
    """Return OCR text and its ranges in the full text."""
    parts = []
    segments = []
    compact_offset = 0
    for item in meta.get("ocr_text_ranges", []):
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(type(value) is int for value in item)
        ):
            start, end = item
            if 0 <= start < end <= len(text):
                if parts:
                    compact_offset += 1
                part = text[start:end]
                parts.append(part)
                segments.append((compact_offset, compact_offset + len(part), start))
                compact_offset += len(part)
    return "\n".join(parts), segments


def _ocr_origin_text(text: str, meta: dict[str, Any]) -> str:
    """Return only text created by OCR."""
    return _ocr_origin_view(text, meta)[0]


def measure_ocr_accuracy(
    values: list[ExpectedValue], text: str, source_type: str, ocr_error: str | None
) -> dict[str, Any]:
    """Per-value edit distance against the expected value. Scans only.

    Skips with a stated reason rather than failing when the source is not a
    scan or when requirements-ocr.txt is not installed -- an absent optional
    extra is a fact about the machine, not a probe failure.
    """
    if ocr_error is not None:
        return {
            "status": "skipped",
            "reason": f"OCR dependencies unavailable: {ocr_error}",
            "values": [],
        }
    if source_type != "pdf_hybrid":
        return {
            "status": "not_applicable",
            "reason": (
                f"source_type is {source_type!r}; character accuracy is only meaningful for a "
                "scan (pdf_hybrid), where the characters were guessed rather than read"
            ),
            "values": [],
        }
    if not text:
        return {"status": "skipped", "reason": "extraction returned no text", "values": []}

    rows = []
    for v in values:
        if len(v.value) * len(text) > MAX_EDIT_DISTANCE_CELLS:
            rows.append(
                {
                    "index": v.index,
                    "field": v.field,
                    "status": "skipped",
                    "reason": "document too long for the approximate-match DP",
                }
            )
            continue
        distance, start, end = approx_substring_distance(v.value, text)
        rows.append(
            {
                "index": v.index,
                "field": v.field,
                "status": "measured",
                "expected": v.value,
                "best_match": text[start:end],
                "start": start,
                "end": end,
                "edit_distance": distance,
                "char_accuracy": round(1.0 - distance / max(len(v.value), 1), 4),
            }
        )

    claimed: list[tuple[int, int]] = []
    ranked = sorted(
        (row for row in rows if row["status"] == "measured"),
        key=lambda row: (-row["char_accuracy"], row["edit_distance"], row["index"]),
    )
    for row in ranked:
        span = row["start"], row["end"]
        if span[0] < span[1] and any(span[0] < end and start < span[1] for start, end in claimed):
            row["status"] = "alignment_conflict"
            row["reason"] = "best OCR range is already used by another expected value"
        elif span[0] < span[1]:
            claimed.append(span)

    measured = [r for r in rows if r["status"] == "measured"]
    mean = round(sum(r["char_accuracy"] for r in measured) / len(measured), 4) if measured else None
    return {"status": "measured", "mean_char_accuracy": mean, "values": rows}


def _measure_source_ocr(
    values: list[ExpectedValue],
    text: str,
    source_type: str,
    ocr_error: str | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Measure OCR and map matches back to the full extracted text."""
    if source_type != "pdf_hybrid":
        return measure_ocr_accuracy(values, text, source_type, ocr_error)

    ocr_text, segments = _ocr_origin_view(text, meta)
    mapped_result = measure_ocr_accuracy(values, ocr_text, source_type, ocr_error)
    for row in mapped_result.get("values", []):
        if row.get("status") != "measured":
            continue
        match = next(
            (
                segment
                for segment in segments
                if segment[0] <= row["start"] < row["end"] <= segment[1]
            ),
            None,
        )
        if match is None:
            row["status"] = "unmapped"
            row["reason"] = "OCR match crosses source ranges"
            continue
        compact_start, _compact_end, source_start = match
        row["start"] = source_start + row["start"] - compact_start
        row["end"] = source_start + row["end"] - compact_start

    observations = meta.get("ocr_observations")
    if not isinstance(observations, list) or not all(
        isinstance(item, str) for item in observations
    ):
        return mapped_result

    observed_text = "\n".join(observations)
    observed_result = measure_ocr_accuracy(values, observed_text, source_type, ocr_error)
    mapped_by_index = {row["index"]: row for row in mapped_result.get("values", [])}
    for row in observed_result.get("values", []):
        mapped = mapped_by_index.get(row["index"], {})
        same_match = (
            mapped.get("status") == "measured"
            and mapped.get("best_match") == row.get("best_match")
            and mapped.get("char_accuracy") == row.get("char_accuracy")
        )
        if same_match:
            row["start"] = mapped["start"]
            row["end"] = mapped["end"]
            row["source_alignment"] = "canonical_ocr_text"
        else:
            row.pop("start", None)
            row.pop("end", None)
            row["source_alignment"] = "observation_only"
    return observed_result


def _measure_render_ocr_text(
    values: list[ExpectedValue],
    text: str,
) -> dict[str, Any]:
    """Find expected values in OCR from the redacted render."""
    exact = measure_extraction(values, text)
    approximate = measure_ocr_accuracy(values, text, "pdf_hybrid", None)
    approximate_by_index = {row["index"]: row for row in approximate.get("values", [])}

    rows = []
    for exact_row in exact["values"]:
        approximate_row = approximate_by_index.get(exact_row["index"], {})
        approximate_hit = (
            not exact_row["found"]
            and approximate_row.get("status") == "measured"
            and approximate_row.get("char_accuracy", 0.0) >= OCR_ALIGNMENT_MIN_ACCURACY
        )
        survives = exact_row["found"] or approximate_hit
        rows.append(
            {
                "index": exact_row["index"],
                "field": exact_row["field"],
                "survives": survives,
                "match": (
                    exact_row["match"]
                    if exact_row["found"]
                    else "ocr_approximate"
                    if approximate_hit
                    else "none"
                ),
                "char_accuracy": (
                    1.0
                    if exact_row["found"]
                    else approximate_row.get("char_accuracy")
                    if approximate_row.get("status") == "measured"
                    else None
                ),
            }
        )

    return {
        "status": "measured",
        "minimum_accuracy": OCR_ALIGNMENT_MIN_ACCURACY,
        "text_chars": len(text),
        "surviving": sum(row["survives"] for row in rows),
        "values": rows,
    }


def _measure_render_ocr(
    values: list[ExpectedValue],
    document: Path,
) -> dict[str, Any]:
    """OCR a redacted PDF without keeping its text."""
    from pii_redactor.ingest.ocr_processor import OCRUnavailableError
    from pii_redactor.ingest.text_extractor import extract

    try:
        text, _words, meta = extract(document, "pdf_hybrid")
    except OCRUnavailableError:
        return {
            "status": "skipped",
            "reason": "OCR dependencies are unavailable",
            "surviving": None,
            "values": [],
        }
    return _measure_render_ocr_text(values, _ocr_origin_text(text, meta))


# ── measurement 4: legacy-11 detection ─────────────────────────────────────


def _value_alignment(
    extracted: dict[str, Any],
    ocr_row: dict[str, Any] | None,
) -> tuple[int, int, str] | None:
    if extracted["found"]:
        return extracted["start"], extracted["end"], extracted.get("match", "exact")
    if (
        ocr_row
        and ocr_row.get("status") == "measured"
        and ocr_row.get("char_accuracy", 0.0) >= OCR_ALIGNMENT_MIN_ACCURACY
        and type(ocr_row.get("start")) is int
        and type(ocr_row.get("end")) is int
    ):
        return ocr_row["start"], ocr_row["end"], "ocr_approximate"
    return None


def _resolve_value_alignments(
    extraction: dict[str, Any],
    ocr: dict[str, Any] | None,
) -> dict[int, tuple[int, int, str] | None]:
    """Give each expected value its own source range."""
    ocr_by_index = {row["index"]: row for row in (ocr or {}).get("values", [])}
    candidates = []
    for extracted in extraction["values"]:
        index = extracted["index"]
        alignment = _value_alignment(extracted, ocr_by_index.get(index))
        if alignment is None:
            continue
        is_approximate = alignment[2] == "ocr_approximate"
        accuracy = ocr_by_index.get(index, {}).get("char_accuracy", 0.0)
        candidates.append((is_approximate, -accuracy, index, alignment))

    resolved: dict[int, tuple[int, int, str] | None] = {
        extracted["index"]: None for extracted in extraction["values"]
    }
    claimed: list[tuple[int, int]] = []
    for _is_approximate, _accuracy, index, alignment in sorted(candidates):
        start, end, _kind = alignment
        if _range_is_free(start, end, claimed):
            resolved[index] = alignment
            claimed.append((start, end))
    return resolved


def measure_privacy_alignment(
    values: list[ExpectedValue],
    extraction: dict[str, Any],
    ocr: dict[str, Any] | None,
) -> dict[str, Any]:
    """Report which values have safe geometry for privacy checks."""
    resolved = _resolve_value_alignments(extraction, ocr)
    rows = []
    for value in values:
        alignment = resolved.get(value.index)
        alignment_kind = alignment[2] if alignment else None
        if alignment_kind is None and value.region is not None:
            alignment_kind = "ground_truth_region"
        rows.append(
            {
                "index": value.index,
                "field": value.field,
                "aligned": alignment_kind is not None,
                "alignment": alignment_kind,
            }
        )
    aligned = sum(row["aligned"] for row in rows)
    return {
        "total": len(rows),
        "aligned": aligned,
        "unaligned": len(rows) - aligned,
        "values": rows,
    }


def measure_detection(
    values: list[ExpectedValue],
    extraction: dict[str, Any],
    entities,
    ocr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per expected value: did detect_all find it, and with the claimed type."""
    rows = []
    alignments = _resolve_value_alignments(extraction, ocr)
    for v in values:
        alignment = alignments.get(v.index)
        if alignment is None:
            rows.append(
                {
                    "index": v.index,
                    "field": v.field,
                    "expected_type": v.type,
                    "status": "not_in_text",
                    "alignment": None,
                    "detected": False,
                    "detected_types": [],
                    "type_match": None,
                    "char_coverage": 0.0,
                }
            )
            continue

        start, end, alignment_kind = alignment
        overlapping = [e for e in entities if e.span[0] < end and start < e.span[1]]
        covered = set()
        for e in overlapping:
            covered.update(range(max(start, e.span[0]), min(end, e.span[1])))
        types = sorted({e.data_type for e in overlapping})

        if not v.type:
            match, status = None, "no_expected_type"
        elif v.type not in LEGACY_11:
            match, status = None, "out_of_scheme"
        else:
            match = v.type in types
            status = "scored_ocr_approximate" if alignment_kind == "ocr_approximate" else "scored"

        rows.append(
            {
                "index": v.index,
                "field": v.field,
                "expected_type": v.type,
                "status": status,
                "alignment": alignment_kind,
                "detected": bool(overlapping),
                "detected_types": types,
                "type_match": match,
                "char_coverage": round(len(covered) / max(end - start, 1), 4),
            }
        )

    scored = [r for r in rows if r["status"].startswith("scored")]
    return {
        "total": len(rows),
        "detected": sum(1 for r in rows if r["detected"]),
        "scored": len(scored),
        "type_matches": sum(1 for r in scored if r["type_match"]),
        "out_of_scheme": sum(1 for r in rows if r["status"] == "out_of_scheme"),
        "values": rows,
    }


# ── measurements 5 + 6: redaction coverage and residual PII ────────────────


def measure_redaction(
    values: list[ExpectedValue],
    extraction: dict[str, Any],
    document: Path,
    source_type: str,
    detect_text: str,
    word_bboxes,
    aligned: list[AlignedWord],
    render_scale: float,
    ocr: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the product's real redaction, then measure pixels and residue.

    Returns (coverage, residual). The entity registry uses the same shared
    detector as the PDF endpoint.
    """
    skip = None
    if source_type not in {"pdf_text", "pdf_hybrid"}:
        skip = f"source_type is {source_type!r}; redaction measurement needs a PDF"
    elif not aligned:
        skip = "no word bboxes could be aligned to the extracted text, so there is no region to measure"

    if skip is None:
        try:
            import numpy as np
            import pypdfium2 as pdfium
        except ModuleNotFoundError as exc:
            # numpy arrives with the ml/ocr extras, not core. probe() promises
            # a skip, never a raise, for a missing optional dependency.
            skip = (
                f"optional dependency {exc.name!r} is not installed; the pixel "
                "measurements need it to rasterize the redacted render"
            )

    if skip:
        blocked = {"status": "skipped", "reason": skip, "values": []}
        return blocked, {
            "status": "skipped",
            "reason": skip,
            "text_arm": None,
            "render_ocr": None,
            "values": [],
        }

    from pii_redactor.detectors.aggregate import detect_all
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_extractor import extract
    from pii_redactor.models import EntityRegistry
    from pii_redactor.redactor import redact_pdf

    entities = detect_all(detect_text)
    fp_count = sum(entity.redact_type == "FP" for entity in entities)
    registry = EntityRegistry(
        entities=entities,
        fp_count=fp_count,
        tb_count=len(entities) - fp_count,
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="aiguard_probe_"))
    redacted = tmp_dir / "redacted.pdf"
    try:
        redact_pdf(str(document), registry, word_bboxes, str(redacted))

        # --- text arm of measurement 6 -------------------------------------
        # Force pdf_text so this reads whatever text layer exists instead of
        # being routed to OCR. A flattened output has none, which is exactly
        # the case that must not be reported as a pass.
        redacted_type = detect_source_type(redacted)
        redacted_text, _rw, _rm = extract(redacted, "pdf_text")
        text_layer_chars = len(redacted_text.strip())
        render_ocr = _measure_render_ocr(values, redacted)
        render_ocr_survivors = {
            row["index"] for row in render_ocr["values"] if row.get("survives") is True
        }

        # --- pixel arm: strictly one page at a time -------------------------
        # Rendering is the memory hazard in this whole harness: a letter page at
        # scale 2 is ~2 MB of greyscale, and holding every page of a long
        # document at once is how a probe run becomes a multi-gigabyte process.
        # So each page is rendered, every value's counters on that page are
        # accumulated, and the array is released before the next page is
        # touched. Only pages that actually carry an expected value are
        # rendered at all.
        alignments = _resolve_value_alignments(extraction, ocr)
        boxes_by_value: dict[int, list[AlignedWord]] = {}
        measurement_alignment: dict[int, str | None] = {}
        for v in values:
            alignment = alignments[v.index]
            if v.region:
                boxes_by_value[v.index] = [
                    AlignedWord(
                        start=0,
                        end=0,
                        page=int(v.region["page"]),
                        x=float(v.region["x"]),
                        y=float(v.region["y"]),
                        width=float(v.region["width"]),
                        height=float(v.region["height"]),
                    )
                ]
                measurement_alignment[v.index] = "ground_truth_region"
            elif alignment:
                boxes_by_value[v.index] = words_for_span(aligned, alignment[0], alignment[1])
                measurement_alignment[v.index] = alignment[2]
            else:
                boxes_by_value[v.index] = []
                measurement_alignment[v.index] = None
        totals = dict.fromkeys(boxes_by_value, 0)
        blacks = dict.fromkeys(boxes_by_value, 0)
        strip_inks = dict.fromkeys(boxes_by_value, 0)

        pages_needed = sorted({w.page for boxes in boxes_by_value.values() for w in boxes})
        doc = pdfium.PdfDocument(str(redacted))
        try:
            for page_num in pages_needed:
                pil = doc[page_num - 1].render(scale=render_scale).to_pil().convert("L")
                arr = np.array(pil)
                del pil
                height, width = arr.shape
                for index, boxes in boxes_by_value.items():
                    for w in boxes:
                        if w.page != page_num:
                            continue
                        x0 = max(0, int(w.x * render_scale))
                        x1 = min(width, int((w.x + w.width) * render_scale))
                        y0 = max(0, int(w.y * render_scale))
                        y1 = min(height, int((w.y + w.height) * render_scale))
                        if x1 <= x0 or y1 <= y0:
                            continue
                        region = arr[y0:y1, x0:x1]
                        totals[index] += region.size
                        blacks[index] += int((region <= INK_BLACK_MAX).sum())

                        strip_top = max(0, int((w.y - INK_STRIP_PT) * render_scale))
                        if y0 > strip_top:
                            strip = arr[strip_top:y0, x0:x1]
                            strip_inks[index] += int(
                                ((strip > INK_BLACK_MAX) & (strip < INK_WHITE_MIN)).sum()
                            )
                del arr
        finally:
            doc.close()

        coverage_rows = []
        residual_rows = []
        for v in values:
            alignment_kind = measurement_alignment[v.index]
            if alignment_kind is None:
                survives_text = v.value in redacted_text
                survives_render = v.index in render_ocr_survivors
                if survives_text or survives_render:
                    verdict = "exposed"
                    reason = (
                        "the value survived in the redacted text layer"
                        if survives_text
                        else "OCR found the value in the redacted render"
                    )
                else:
                    verdict = "unmeasurable"
                    reason = "no reliable source alignment was found for this value"
                coverage_rows.append(
                    {
                        "index": v.index,
                        "field": v.field,
                        "status": "not_in_text",
                        "alignment": None,
                        "words": 0,
                        "black_fraction": None,
                    }
                )
                residual_rows.append(
                    {
                        "index": v.index,
                        "field": v.field,
                        "verdict": verdict,
                        "reason": reason,
                        "alignment": None,
                        "text_arm_survives": survives_text,
                        "render_ocr_survives": survives_render,
                        "black_fraction": None,
                        "ink_above_box_pixels": None,
                    }
                )
                continue

            boxes = boxes_by_value[v.index]
            total, black, strip_ink = totals[v.index], blacks[v.index], strip_inks[v.index]
            fraction = (black / total) if total else None
            fully = fraction is not None and fraction >= COVERAGE_FULL
            coverage_rows.append(
                {
                    "index": v.index,
                    "field": v.field,
                    "status": "measured" if total else "no_pixels",
                    "alignment": alignment_kind,
                    "words": len(boxes),
                    "black_pixels": black,
                    "total_pixels": total,
                    "black_fraction": round(fraction, 4) if fraction is not None else None,
                    "fully_covered": fully,
                }
            )

            survives_text = v.value in redacted_text
            survives_render = v.index in render_ocr_survivors
            if survives_text:
                verdict, reason = "exposed", "the value survived in the redacted text layer"
            elif survives_render:
                verdict, reason = "exposed", "OCR found the value in the redacted render"
            elif fraction is None:
                verdict, reason = (
                    "unmeasurable",
                    "no pixels could be sampled for this value's bboxes",
                )
            elif not fully:
                verdict, reason = (
                    "exposed",
                    f"only {fraction:.1%} of the value's bbox area is opaque black",
                )
            elif strip_ink:
                verdict, reason = (
                    "ink_above_box",
                    f"{strip_ink} pixel(s) of surviving glyph edge in the {INK_STRIP_PT:g}pt "
                    "strip above the box",
                )
            else:
                verdict, reason = (
                    "removed",
                    "bbox fully black and the strip above it is clean",
                )
            residual_rows.append(
                {
                    "index": v.index,
                    "field": v.field,
                    "verdict": verdict,
                    "reason": reason,
                    "alignment": alignment_kind,
                    "text_arm_survives": survives_text,
                    "render_ocr_survives": survives_render,
                    "black_fraction": round(fraction, 4) if fraction is not None else None,
                    "ink_above_box_pixels": strip_ink,
                }
            )

        measured = [r for r in coverage_rows if r["black_fraction"] is not None]
        coverage = {
            "status": "measured",
            "note": (
                "measured on the rendered redacted page using source boxes or "
                "synthetic fixture regions"
            ),
            "render_scale": render_scale,
            "values_measured": len(measured),
            "fully_covered": sum(1 for r in measured if r["fully_covered"]),
            "mean_black_fraction": (
                round(sum(r["black_fraction"] for r in measured) / len(measured), 4)
                if measured
                else None
            ),
            "values": coverage_rows,
        }

        text_arm_vacuous = text_layer_chars == 0
        residual = {
            "status": "measured",
            "text_arm": {
                "redacted_source_type": redacted_type,
                "text_layer_chars": text_layer_chars,
                "values_surviving_in_text": [
                    r["field"] for r in residual_rows if r["text_arm_survives"]
                ],
                "vacuous": text_arm_vacuous,
                "note": (
                    "the redacted output carries no text layer at all, so 'the value is not in "
                    "the extracted text' is true of every string in the universe and proves "
                    "nothing. The verdicts below rest on the rendered pixels."
                    if text_arm_vacuous
                    else "the redacted output has a readable text layer; the text arm carries "
                    "real signal here, but a two-layer Thai PDF can still defeat a substring "
                    "check, so the pixel arm remains the binding evidence."
                ),
            },
            "render_ocr": render_ocr,
            "removed": sum(1 for r in residual_rows if r["verdict"] == "removed"),
            "exposed": sum(
                1 for r in residual_rows if r["verdict"] in ("exposed", "ink_above_box")
            ),
            "unmeasurable": sum(1 for r in residual_rows if r["verdict"] == "unmeasurable"),
            "values": residual_rows,
        }
        return coverage, residual
    finally:
        for leftover in tmp_dir.glob("*"):
            leftover.unlink(missing_ok=True)
        tmp_dir.rmdir()


# ── the probe ──────────────────────────────────────────────────────────────


def probe(
    document: str | Path,
    expectations: dict[str, Any],
    render_scale: float = DEFAULT_RENDER_SCALE,
) -> dict[str, Any]:
    """Run all six measurements over one document. Never raises on a missing
    optional dependency; the affected measurement reports its own skip."""
    from pii_redactor.ingest.file_detector import detect_source_type
    from pii_redactor.ingest.text_cleaner import clean_length_preserving
    from pii_redactor.ingest.text_extractor import extract

    document = Path(document)
    render_scale = min(float(render_scale), MAX_RENDER_SCALE)
    values: list[ExpectedValue] = expectations["values"]

    source_type = detect_source_type(document)
    ocr_error: str | None = None
    try:
        text, word_bboxes, meta = extract(document, source_type)
    except Exception as exc:  # OCRUnavailableError and anything else ingest raises
        if type(exc).__name__ != "OCRUnavailableError":
            raise
        ocr_error = str(exc)
        text, word_bboxes, meta = "", [], {}

    # Same normalisation /api/redact-pdf detects on: 1:1 in character count, so
    # entity spans stay aligned with the offsets measurement 1 found and with
    # the word bboxes the black boxes are drawn from.
    detect_text = clean_length_preserving(text) if text else ""
    aligned, unaligned = align_words(text, word_bboxes)

    extraction = measure_extraction(values, text)
    columns = detect_columns(word_bboxes)
    order = measure_order(extraction, columns, expectations.get("layout", "unknown"))
    ocr = _measure_source_ocr(values, text, source_type, ocr_error, meta)

    if detect_text:
        from pii_redactor.detectors.aggregate import detect_all

        entities = detect_all(detect_text)
    else:
        entities = []
    detection = measure_detection(values, extraction, entities, ocr)
    privacy_alignment = measure_privacy_alignment(values, extraction, ocr)

    coverage, residual = measure_redaction(
        values,
        extraction,
        document,
        source_type,
        detect_text,
        word_bboxes,
        aligned,
        render_scale,
        ocr,
    )

    decoy_hits = [d for d in expectations["decoys"] if d in text]
    control = {
        "checked": len(expectations["decoys"]),
        "false_hits": decoy_hits,
        "note": (
            "decoys are values known NOT to be in the document. A run where every expected "
            "value is found is only informative if the decoys are simultaneously absent -- "
            "otherwise the matcher is agreeing with itself."
            if expectations["decoys"]
            else "no decoys declared; a 100% survival result here has no negative control behind it"
        ),
    }

    return {
        "document": str(document),
        "source_type": source_type,
        "extract_meta": meta,
        "text_chars": len(text),
        "word_bboxes": len(word_bboxes),
        "unaligned_word_bboxes": unaligned,
        "entities_detected": len(entities),
        "extraction": extraction,
        "order": order,
        "ocr": ocr,
        "detection": detection,
        "privacy_alignment": privacy_alignment,
        "coverage": coverage,
        "residual": residual,
        "decoy_control": control,
    }


# ── rendering ──────────────────────────────────────────────────────────────


def render_report(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"document      {result['document']}")
    lines.append(
        f"source_type   {result['source_type']}   text_chars={result['text_chars']} "
        f"word_bboxes={result['word_bboxes']} (unaligned={result['unaligned_word_bboxes']}) "
        f"entities={result['entities_detected']}"
    )

    ex = result["extraction"]
    lines.append("")
    lines.append(f"1. EXTRACTION SURVIVAL      {ex['found']}/{ex['total']} values survived ingest")
    for r in ex["values"]:
        mark = "hit " if r["found"] else "MISS"
        where = f"@{r['start']}" if r["found"] else "-"
        lines.append(f"   {mark} {r['field']:<20} {where:<8} match={r['match']}")

    o = result["order"]
    lines.append("")
    lines.append(
        f"2. EXTRACTION ORDER         inversions={o['inversions']}/{o['max_inversions']}"
        + (f" ({o['normalized_inversions']:.3f})" if o["normalized_inversions"] is not None else "")
    )
    lines.append(f"   placed    {o['placed_order']}")
    lines.append(f"   extracted {o['extracted_order']}")
    lines.append(f"   layout={o['layout']} ({o['layout_source']}); {o['columns']['reason']}")
    if not o["meaningful"]:
        lines.append(f"   NOT MEANINGFUL: {o['reason']}")

    oc = result["ocr"]
    lines.append("")
    if oc["status"] == "measured":
        lines.append(f"3. OCR CHARACTER ACCURACY   mean={oc['mean_char_accuracy']}")
        for r in oc["values"]:
            if r["status"] == "measured":
                lines.append(
                    f"   {r['field']:<20} dist={r['edit_distance']:<4} acc={r['char_accuracy']:.4f}"
                )
            else:
                lines.append(f"   {r['field']:<20} skipped: {r['reason']}")
    else:
        lines.append(f"3. OCR CHARACTER ACCURACY   {oc['status'].upper()}")
        lines.append(f"   {oc['reason']}")

    d = result["detection"]
    lines.append("")
    lines.append(
        f"4. LEGACY-11 DETECTION      detected={d['detected']}/{d['total']}  "
        f"type_match={d['type_matches']}/{d['scored']} scored"
        + (f"  ({d['out_of_scheme']} out of scheme)" if d["out_of_scheme"] else "")
    )
    for r in d["values"]:
        got = ",".join(r["detected_types"]) or "-"
        verdict = {True: "ok", False: "TYPE MISMATCH", None: f"({r['status']})"}[r["type_match"]]
        lines.append(
            f"   {r['field']:<20} want={r['expected_type']:<14} got={got:<20} "
            f"cov={r['char_coverage']:.2f} {verdict}"
        )

    c = result["coverage"]
    lines.append("")
    if c["status"] == "measured":
        lines.append(
            f"5. REDACTION COVERAGE       fully_covered={c['fully_covered']}/{c['values_measured']}  "
            f"mean_black_fraction={c['mean_black_fraction']}"
        )
        lines.append(f"   {c['note']} (render_scale={c['render_scale']})")
        for r in c["values"]:
            if r["black_fraction"] is None:
                lines.append(f"   {r['field']:<20} {r['status']}")
            else:
                lines.append(
                    f"   {r['field']:<20} words={r['words']:<3} black={r['black_fraction']:.4f}"
                )
    else:
        lines.append("5. REDACTION COVERAGE       SKIPPED")
        lines.append(f"   {c['reason']}")

    res = result["residual"]
    lines.append("")
    if res["status"] == "measured":
        ta = res["text_arm"]
        lines.append(
            f"6. RESIDUAL PII             removed={res['removed']} exposed={res['exposed']} "
            f"unmeasurable={res['unmeasurable']}"
        )
        lines.append(
            f"   text arm: redacted output is {ta['redacted_source_type']}, "
            f"{ta['text_layer_chars']} chars of text layer"
            + ("  <-- VACUOUS" if ta["vacuous"] else "")
        )
        lines.append(f"   {ta['note']}")
        render_ocr = res["render_ocr"]
        if render_ocr["status"] == "measured":
            lines.append(
                f"   supporting render OCR: measured, surviving={render_ocr['surviving']}/"
                f"{len(render_ocr['values'])}, min_accuracy="
                f"{render_ocr['minimum_accuracy']}"
            )
        else:
            lines.append(
                f"   supporting render OCR: {render_ocr['status']}; "
                f"{render_ocr.get('reason', 'no reason')}"
            )
        for r in res["values"]:
            lines.append(f"   {r['field']:<20} {r['verdict']:<14} {r['reason']}")
    else:
        lines.append("6. RESIDUAL PII             SKIPPED")
        lines.append(f"   {res['reason']}")

    ctrl = result["decoy_control"]
    lines.append("")
    lines.append(
        f"   negative control: {ctrl['checked']} decoy(s) checked, "
        f"{len(ctrl['false_hits'])} false hit(s)"
        + (f" {ctrl['false_hits']}" if ctrl["false_hits"] else "")
    )
    lines.append(f"   {ctrl['note']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="benchmark.probe_document",
        description="Measure six things about a document's trip through the pipeline.",
    )
    ap.add_argument("document", help="path to the document (.txt or .pdf)")
    ap.add_argument("expectations", help="path to the expectations JSON file")
    ap.add_argument("--json", default=None, help="also write the full result as JSON here")
    ap.add_argument(
        "--render-scale",
        type=float,
        default=DEFAULT_RENDER_SCALE,
        help=f"points -> pixels for the redaction pixel check (capped at {MAX_RENDER_SCALE})",
    )
    args = ap.parse_args(argv)

    doc = Path(args.document)
    if not doc.exists():
        print(f"no such document: {doc}", file=sys.stderr)
        return 2
    try:
        expectations = load_expectations(args.expectations)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"expectations file unusable: {exc}", file=sys.stderr)
        return 2

    result = probe(doc, expectations, render_scale=args.render_scale)
    print(render_report(result))

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
