"""Aggregate detected PII across a set of files for a PDPA section 37(4) breach
notification (Track D #2).

Reuses the same `detect_all` / `extract` / `clean` / `assess_reid_risk` /
`scan_section26` every other storefront runs -- this module only aggregates
their output across files, per file and per corpus. No artifact this module
produces may carry a personal-data value, an excerpt, a hash of a value, or
OCR text (a hash of a 13-digit id is brute-forceable, so a hash counts as a
value here too): `to_json_dict()` holds only counts, type/category names, and
version strings. The distinct-value sets used to compute those counts are
plain in-memory `set[str]` and are dropped with the process -- nothing here
writes them to disk.

Not a legal conclusion: the assessment states what was found and how the
subject estimate was derived, never that notification is required.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.tb_detector import _resolve_engine_name
from pii_redactor.ingest.file_detector import detect_source_type
from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.ingest.text_extractor import extract
from pii_redactor.reid_risk import assess_reid_risk
from pii_redactor.report import scan_section26

BREACH_SCHEMA = "aiguard.breach-assessment/1"

# Strong identifiers: the same canonical value under one of these types can
# only ever describe one subject, which is what makes subjects_min/max
# meaningful. NAME is deliberately excluded -- spelling variants and OCR noise
# inflate a name-based count, so it is reported separately (see
# `_NAME_TYPE`) and never contributes to the subject bounds.
_STRONG_TYPES = ("THAI_ID", "PASSPORT", "PHONE", "EMAIL")
_NAME_TYPE = "NAME"

_DISCOVER_SUFFIXES = (".txt", ".pdf")

_SUBJECT_ESTIMATE_METHOD = (
    "subjects_min is the largest distinct-value count among the strong identifier "
    "types found (Thai national ID, passport, phone, email) -- the same value under "
    "one type cannot describe more than one subject. subjects_max is the sum of "
    "those distinct counts, which double-counts a subject who appears under two or "
    "more identifier types; that no such overlap exists is this bound's unverified "
    "assumption. Cross-document and cross-type person linkage is not attempted "
    "in v1 -- both bounds come from counting values, not people."
)

_NAME_WEAK_NOTE = (
    "NAME is a weak identifier: spelling and OCR variants of the same person's name "
    "inflate its distinct count, so it is reported separately and does not "
    "contribute to subjects_min or subjects_max."
)

_NAME_TITLE_RE = re.compile(r"^(?:นางสาว|นาย|นาง|น\.ส\.|ด\.ช\.|ด\.ญ\.|เด็กชาย|เด็กหญิง|คุณ)\s*")


def _short_reason(exc: Exception, path: Path) -> str:
    """`{ExceptionClassName} {message}` with the input file's own path
    scrubbed out of the message.

    `FailedFile.reason` is documented as "basename + short reason, never
    content" -- but several stdlib exceptions embed the FULL operand path in
    their own message (`FileNotFoundError`: "[Errno 2] No such file or
    directory: 'C:\\Users\\...\\missing.txt'"), which can carry a directory
    name the controller did not intend to disclose. Every spelling of `path`
    this process is likely to have produced (as given, resolved, and both
    slash directions) is folded down to the bare basename, which is already
    a value this report shows elsewhere. A space separates the class name
    from the message rather than a colon -- this reason string can reach
    Thai-facing CLI/PDF output, and Thai punctuation uses spaces, not Western
    colons.
    """
    message = str(exc)
    basename = path.name
    spellings = {str(path)}
    try:
        spellings.add(str(path.resolve()))
    except OSError:
        pass
    for spelling in list(spellings):
        spellings.add(spelling.replace("\\", "/"))
        spellings.add(spelling.replace("/", "\\"))
    for spelling in spellings:
        if spelling and spelling != basename:
            message = message.replace(spelling, basename)
    return f"{type(exc).__name__} {message}"


class NoFilesAssessedError(RuntimeError):
    """Nothing could be assessed -- no files found, or every one failed."""


@dataclass
class FailedFile:
    """One file that could not be processed. Never carries file content."""

    basename: str
    reason: str  # "<ExceptionClassName> <short message>"


@dataclass
class FileAssessment:
    """Per-file row: what was found in one document, nothing from its content."""

    basename: str
    source_type: str  # "text" | "pdf_text" | "pdf_hybrid"
    type_counts: dict[str, int]  # data_type -> occurrences
    risk_grade: str  # reid_risk grade for this file's text
    human_review: bool


@dataclass
class BreachAssessment:
    """Corpus-level result of `assess_breach`. `to_json_dict()` is what both
    the CLI's JSON output and the PDF renderer build from, so the two can
    never drift apart."""

    files_total: int
    files_assessed: int
    files_failed: list[FailedFile]
    files_skipped: list[str]  # basenames dropped by the *.txt/*.pdf directory filter
    type_counts: dict[str, dict[str, int]]  # data_type -> {"total": n, "distinct": n}
    subjects_min: int
    subjects_max: int
    subjects_method: str
    no_strong_identifiers: bool  # True when subjects_min/max are 0 because none were found
    name_distinct: int
    name_note: str
    section26_counts: dict[str, int]  # category -> number of files flagged
    risk_max_grade: str
    risk_distribution: dict[str, int]  # grade -> number of files
    environment: dict[str, str]
    assessed_at: str
    file_rows: list[FileAssessment]

    def to_json_dict(self) -> dict:
        """The JSON-serializable shape. No value, excerpt, or hash appears here --
        every field is a count, a type/category name, or a version string."""
        return {
            "schema": BREACH_SCHEMA,
            "assessed_at": self.assessed_at,
            "files": {
                "total": self.files_total,
                "assessed": self.files_assessed,
                "failed": [{"basename": f.basename, "reason": f.reason} for f in self.files_failed],
                "skipped": {
                    "count": len(self.files_skipped),
                    "basenames": list(self.files_skipped),
                },
            },
            "types": self.type_counts,
            "subjects": {
                "min": self.subjects_min,
                "max": self.subjects_max,
                "method": self.subjects_method,
                "no_strong_identifiers": self.no_strong_identifiers,
            },
            "name_weak_identifier": {
                "distinct": self.name_distinct,
                "note": self.name_note,
            },
            "section26": self.section26_counts,
            "risk": {
                "max_grade": self.risk_max_grade,
                "distribution": self.risk_distribution,
            },
            "environment": self.environment,
            "file_rows": [
                {
                    "basename": row.basename,
                    "source_type": row.source_type,
                    "type_counts": row.type_counts,
                    "risk_grade": row.risk_grade,
                    "human_review": row.human_review,
                }
                for row in self.file_rows
            ],
        }


def _read_version() -> str:
    """The product version, or "unknown" when the VERSION file is unreachable.

    Same fallback chain as `receipt.py` (frozen exe's `_MEIPASS`, then the repo
    root next to this file) so a packaged build reports the same version a
    receipt issued from the same build would.
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "VERSION")
    candidates.append(Path(__file__).resolve().parent.parent / "VERSION")
    for candidate in candidates:
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return "unknown"


def _detector_version() -> str:
    try:
        from importlib.metadata import version

        return f"pythainlp {version('pythainlp')}"
    except Exception:
        return "unknown"


def _environment() -> dict:
    return {
        "product_version": _read_version(),
        "ner_engine": _resolve_engine_name(),
        "detector_version": _detector_version(),
    }


def _canonical_value(data_type: str, value: str) -> str:
    """Fold formatting differences that would otherwise inflate a distinct count.

    Only strong types get bespoke normalization (per the spec: spaced/hyphenated
    Thai id forms and mixed-case emails are the same value). NAME is normalized
    by stripping a leading title and collapsing whitespace -- still a WEAK
    identifier, so this only keeps its own distinct count honest, never feeds
    subjects_min/max. Every other type gets a generic whitespace/case fold so
    its distinct count is not inflated by incidental formatting.
    """
    if data_type == "THAI_ID":
        return re.sub(r"\D", "", value)
    if data_type == "PASSPORT":
        return re.sub(r"[\s-]", "", value).upper()
    if data_type == "PHONE":
        digits = re.sub(r"\D", "", value)
        # +66 drops the domestic leading 0 (fp_detector's _RE_PHONE_INTL
        # comment): a 9-digit mobile number becomes 66 + 9 digits (11 total),
        # an 8-digit landline becomes 66 + 8 digits (10 total). Both fold back
        # to the domestic form so "+66 81 234 5678" and "081-234-5678" --
        # or "+66 2 123 4567" and "02-123-4567" -- collapse to one value
        # instead of counting the same subject twice.
        if digits.startswith("66") and len(digits) in (10, 11):
            digits = "0" + digits[2:]
        return digits
    if data_type == "EMAIL":
        return value.strip().casefold()
    if data_type == _NAME_TYPE:
        stripped = _NAME_TITLE_RE.sub("", value.strip())
        return re.sub(r"\s+", " ", stripped).strip().casefold()
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _max_risk_grade(distribution: dict[str, int]) -> str:
    """The worst grade present. `distribution` is never empty when this is
    called -- every successfully assessed file contributes exactly one grade,
    and zero successes raises before this point."""
    rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    return max(distribution, key=lambda grade: rank.get(grade, -1))


def _discover_files(
    paths: Sequence[str | Path], *, recursive: bool
) -> tuple[list[Path], list[str]]:
    """Resolve `paths` to a deterministic, de-duplicated list of files, plus the
    basenames a directory scan chose not to look at.

    A directory is scanned for *.txt/*.pdf (non-recursive unless `recursive`);
    every other file the scan finds there is reported back as skipped rather
    than dropped silently -- a breach report must not claim it covered a
    folder when it only opened a subset of what was in it. A path that is not
    a directory is taken as-is, even if it does not exist or carries a
    different extension -- the caller named it explicitly, and letting it
    reach `assess_breach`'s per-file try/except turns a bad path into a
    failed-file row instead of a silent skip (this rule does not apply to
    directory contents, which is exactly what "skipped" now surfaces).
    """
    found: list[Path] = []
    skipped: list[str] = []
    seen: set[Path] = set()
    seen_skipped: set[Path] = set()

    def _resolved(candidate: Path) -> Path:
        try:
            return candidate.resolve()
        except OSError:
            return candidate

    def _add(candidate: Path) -> None:
        key = _resolved(candidate)
        if key not in seen:
            seen.add(key)
            found.append(candidate)

    def _add_skipped(candidate: Path) -> None:
        key = _resolved(candidate)
        if key not in seen_skipped:
            seen_skipped.add(key)
            skipped.append(candidate.name)

    for raw in paths:
        candidate_path = Path(raw)
        if candidate_path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(candidate_path.glob(pattern)):
                if not child.is_file():
                    continue
                if child.suffix.lower() in _DISCOVER_SUFFIXES:
                    _add(child)
                else:
                    _add_skipped(child)
        else:
            _add(candidate_path)

    return found, skipped


def assess_breach(
    paths: Sequence[str | Path],
    *,
    recursive: bool = False,
    assessed_at: str | None = None,
) -> BreachAssessment:
    """Assess a set of leaked/affected files for a PDPA section 37(4) notification.

    Each file runs the product's own pipeline (`extract` -> `clean` ->
    `detect_all`), then contributes to per-file and corpus-level PII counts, a
    `scan_section26` flag, and a `reid_risk` grade. A file that fails to
    process is recorded as a `FailedFile` (basename + exception class/short
    reason -- never its content) and the assessment continues; if every file
    fails, or none were found, raises `NoFilesAssessedError` rather than
    returning an assessment that silently covers zero documents.

    Raises:
        NoFilesAssessedError: no file could be assessed.
    """
    files, skipped_names = _discover_files(paths, recursive=recursive)
    files_total = len(files) + len(skipped_names)

    total_counts: dict[str, int] = {}
    distinct_sets: dict[str, set[str]] = {}
    section26_counts: dict[str, int] = {}
    risk_distribution: dict[str, int] = {}
    file_rows: list[FileAssessment] = []
    failed: list[FailedFile] = []

    for path in files:
        try:
            source_type = detect_source_type(path)
            raw_text, _bboxes, meta = extract(path, source_type)
            text = clean(raw_text).text
            entities = detect_all(text)
        except Exception as exc:
            failed.append(FailedFile(basename=path.name, reason=_short_reason(exc, path)))
            continue

        per_file_counts: dict[str, int] = {}
        for entity in entities:
            per_file_counts[entity.data_type] = per_file_counts.get(entity.data_type, 0) + 1
            total_counts[entity.data_type] = total_counts.get(entity.data_type, 0) + 1
            distinct_sets.setdefault(entity.data_type, set()).add(
                _canonical_value(entity.data_type, entity.original_text)
            )

        for hit in scan_section26(text):
            section26_counts[hit["category"]] = section26_counts.get(hit["category"], 0) + 1

        reid = assess_reid_risk(text)
        risk_distribution[reid.grade] = risk_distribution.get(reid.grade, 0) + 1

        file_rows.append(
            FileAssessment(
                basename=path.name,
                source_type=source_type,
                type_counts=dict(sorted(per_file_counts.items())),
                risk_grade=reid.grade,
                human_review=bool(meta.get("human_review", False)),
            )
        )

    files_assessed = len(file_rows)
    if files_assessed == 0:
        raise NoFilesAssessedError(
            f"No files could be assessed: {files_total} discovered, "
            f"{len(skipped_names)} skipped, {len(failed)} failed"
        )

    strong_distinct = {
        data_type: len(distinct_sets[data_type])
        for data_type in _STRONG_TYPES
        if data_type in distinct_sets
    }
    subjects_min = max(strong_distinct.values(), default=0)
    subjects_max = sum(strong_distinct.values())

    type_counts = {
        data_type: {
            "total": total_counts[data_type],
            "distinct": len(distinct_sets.get(data_type, set())),
        }
        for data_type in sorted(total_counts)
    }

    return BreachAssessment(
        files_total=files_total,
        files_assessed=files_assessed,
        files_failed=failed,
        files_skipped=skipped_names,
        type_counts=type_counts,
        subjects_min=subjects_min,
        subjects_max=subjects_max,
        subjects_method=_SUBJECT_ESTIMATE_METHOD,
        no_strong_identifiers=subjects_max == 0,
        name_distinct=len(distinct_sets.get(_NAME_TYPE, set())),
        name_note=_NAME_WEAK_NOTE,
        section26_counts=dict(sorted(section26_counts.items())),
        risk_max_grade=_max_risk_grade(risk_distribution),
        risk_distribution=dict(sorted(risk_distribution.items())),
        environment=_environment(),
        assessed_at=assessed_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        file_rows=file_rows,
    )
