"""Locate which files, among a set the controller already holds, mention a
data subject -- for a PDPA มาตรา 30 access request (Track D #3).

This module LOCATES; it never reproduces document content. The controller
answering the request serves it from the located files themselves. Retention
is in-memory for the duration of one run only (owner decision, 2026-08-01):
the subject identifiers the controller supplies, every value this module
detects while matching them, and all intermediate state live in local
variables and die with the process -- nothing here writes to disk, and no
subject identifier VALUE (never mind a hash of one -- see breach.py's own
rationale, a hash of a 13-digit id is brute-forceable) reaches `to_json_dict()`,
an exception message, or a dataclass repr. `DsarResult` therefore carries only
identifier TYPE counts, never the identifiers themselves -- every dataclass
below is absent-by-construction rather than filtered late (no field holds a
raw value, so there is nothing for its ordinary auto-generated repr to leak).

Reuses the same `extract` / `clean` / `detect_all` / `assess_reid_risk` every
other storefront runs, and the same `discover_files` / `short_reason` /
`canonical_value` helpers `breach.py` uses (now shared via `scan_common.py`)
-- this module only classifies subject-file lines and matches canonical
values across files.

Not a legal conclusion: the result never claims the DSAR is satisfied. Not a
document exporter: unmatched files are never listed, and a matched file's
own content is never quoted or excerpted.
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
from pii_redactor.scan_common import canonical_value, discover_files, short_reason

DSAR_SCHEMA = "aiguard.dsar-locate/1"

# Subject-file line classification, in this exact priority order (a line
# tried against later rules only if the earlier ones don't fire):
#   13 digits                -> THAI_ID
#   [A-Z]{2}\d{7}             -> PASSPORT (Thai-format, no cue needed)
#   contains "@"              -> EMAIL
#   digit / "+66" phone shape -> PHONE
#   anything else             -> NAME (the catch-all; a full name has no
#                                shape test, so nothing is "unclassifiable"
#                                except a blank line)
_PASSPORT_LINE_RE = re.compile(r"^[A-Z]{2}\d{7}$")
_PHONE_DOMESTIC_RE = re.compile(r"^0\d{8,9}$")
_PHONE_INTL_RE = re.compile(r"^\+66\d{8,9}$")

# An explicit "+66" country-code marker (the plus sign itself, not just the
# bare digits "66") somewhere in a detected entity's raw text -- see
# `_entity_matches_any_subject_value`'s PHONE guard below.
_PLUS_66_MARKER_RE = re.compile(r"\+\s*66")

_METHOD_STATEMENT = (
    "A file matches the subject only on exact canonical equality between a detected "
    "entity's value and one of the identifiers supplied in the subject file -- same "
    "normalization breach.py uses (spaced/hyphenated Thai id forms, mixed-case "
    "emails, +66/domestic phone forms, and a name with its title stripped all "
    "collapse to one canonical value). Matching is value-based only: the detector's "
    "own type label for that entity is never consulted, only the canonical value of "
    "what it detected against the subject identifier's own canonical form -- a phone "
    "number the detector happens to label BANK_ACCOUNT in one document, or a name it "
    "labels ORGANIZATION in another, still matches, because the label is the "
    "detector's contextual guess, not a property of the value. One deliberate "
    "exception guards against a false match: a phone number's international-to-"
    "domestic fold (+66 -> 0) only applies when the detected text still carries "
    "an explicit +66 marker, so an unrelated bare digit run that merely starts "
    "with 66 (e.g. a bank account) is never folded into a false phone match. No "
    "fuzzy or partial matching is attempted."
)

_OCR_LIMITATION_NOTE = (
    "Exact-match-only means an OCR misread of a scanned page's identifier will not "
    "match the subject file even when a human reader would recognize it as the same "
    "value -- this is a known Track A limitation, not a claim that a document does "
    "not concern the subject."
)

_THIRD_PARTY_NOTE = (
    "third_party_possible is set on a matched file whose overall PII inventory "
    "contains a type or a count beyond what matched the subject's own identifiers -- "
    "that extra personal data may belong to someone else. It is a warning to review "
    "and redact before serving a copy, not a conclusion that a third party is present. "
    "This flag is heuristic: it also fires on the subject's own data under a type they "
    "did not list in the subject file, and on the detector's own false positives (e.g. "
    'a stray NAME hit on a label like "national id number"), so a true value here is '
    "not proof of a third party either -- review the file's own PII inventory before "
    "acting on it."
)

_NAME_WEAK_MATCH_NOTE = (
    "weak_only is set on a matched file whose ONLY matched identifier type is NAME. "
    "NAME is a weak identifier -- the same rule breach.py already applies when bounding "
    "its subjects_min/max estimate -- because spelling and OCR variants of a name "
    "inflate it and a common Thai name can belong to someone other than the requester. "
    "A weak_only match is evidence that a person with this name appears in the file, "
    "not proof that the requester does; it needs human confirmation before the file is "
    "treated as concerning the subject."
)

_SCOPE_NOTE = (
    "This tool locates matching files; it does not reproduce, copy, or excerpt their "
    "content, and it does not by itself constitute a completed response to the "
    "access request. Unmatched files are counted but never listed, and are out of "
    "scope for this request."
)


class NoSubjectIdentifiersError(ValueError):
    """The subject file was empty, or every line was blank."""


class NoFilesAssessedError(RuntimeError):
    """Nothing could be assessed -- no files found, or every one failed.

    Mirrors `breach.assess_breach`'s own error of the same name: a result
    that silently covers zero documents is worse than a clear failure."""


@dataclass
class FailedFile:
    """One file that could not be processed. Never carries file content."""

    basename: str
    reason: str  # "<ExceptionClassName> <short message>"


@dataclass
class MatchedFile:
    """One file where the subject was found. Nothing here is a value -- type
    names, counts, a grade, and three flags."""

    basename: str
    source_type: str  # "text" | "pdf_text" | "pdf_hybrid"
    matched_identifier_counts: dict[
        str, int
    ]  # identifier type -> occurrences that matched the subject
    type_counts: dict[str, int]  # this file's full PII inventory: data_type -> occurrences
    risk_grade: str
    human_review: bool
    third_party_possible: bool
    weak_only: bool  # True iff the ONLY matched identifier type is NAME -- see
    # _NAME_WEAK_MATCH_NOTE: a name-only match needs human confirmation, unlike
    # a checksum-backed id/passport/phone/email match.


@dataclass
class DsarResult:
    """Corpus-level result of `locate_subject`. `to_json_dict()` is what both
    the CLI's JSON output and the PDF renderer build from, so the two can
    never drift apart. `subject_counts` holds identifier TYPES and how many of
    each were supplied -- never the identifier values themselves."""

    subject_counts: dict[str, int]  # identifier type -> count supplied
    files_total: int
    files_assessed: int
    files_failed: list[FailedFile]
    files_skipped: list[str]  # basenames dropped by the *.txt/*.pdf directory filter
    matched_files: list[MatchedFile]
    environment: dict[str, str]
    assessed_at: str

    def to_json_dict(self) -> dict:
        """The JSON-serializable shape. No subject identifier value, document
        excerpt, or hash appears here -- every field is a count, a type name,
        a basename, a grade, a flag, or a fixed method statement."""
        return {
            "schema": DSAR_SCHEMA,
            "assessed_at": self.assessed_at,
            "subject": {"types": self.subject_counts},
            "files": {
                "total": self.files_total,
                "assessed": self.files_assessed,
                "matched": len(self.matched_files),
                "failed": [{"basename": f.basename, "reason": f.reason} for f in self.files_failed],
                "skipped": {
                    "count": len(self.files_skipped),
                    "basenames": list(self.files_skipped),
                },
            },
            "matched_files": [
                {
                    "basename": row.basename,
                    "source_type": row.source_type,
                    "matched_identifier_counts": row.matched_identifier_counts,
                    "type_counts": row.type_counts,
                    "risk_grade": row.risk_grade,
                    "human_review": row.human_review,
                    "third_party_possible": row.third_party_possible,
                    "weak_only": row.weak_only,
                }
                for row in self.matched_files
            ],
            "method": {
                "match": _METHOD_STATEMENT,
                "ocr_limitation": _OCR_LIMITATION_NOTE,
                "third_party": _THIRD_PARTY_NOTE,
                "name_weak_match": _NAME_WEAK_MATCH_NOTE,
                "scope": _SCOPE_NOTE,
            },
            "environment": self.environment,
        }


def _read_version() -> str:
    """The product version, or "unknown" when the VERSION file is unreachable.

    Same fallback chain as `breach.py`/`receipt.py` (frozen exe's `_MEIPASS`,
    then the repo root next to this file) so a packaged build reports the
    same version a breach assessment or receipt issued from the same build
    would.
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


def _classify_subject_line(line: str) -> str | None:
    """Classify one subject-file line by shape. Returns `None` only for a
    blank line -- every non-blank line classifies as at least NAME, the
    catch-all with no shape test of its own."""
    stripped = line.strip()
    if not stripped:
        return None

    compact = re.sub(r"[\s-]", "", stripped)
    if compact.isdigit() and len(compact) == 13:
        return "THAI_ID"
    if _PASSPORT_LINE_RE.fullmatch(stripped):
        return "PASSPORT"
    if "@" in stripped:
        return "EMAIL"
    if _PHONE_DOMESTIC_RE.fullmatch(compact) or _PHONE_INTL_RE.fullmatch(compact):
        return "PHONE"
    return "NAME"


def _read_subject_identifiers(subject_file: str | Path) -> list[tuple[str, str]]:
    """Read and classify every non-blank line of `subject_file`.

    Returns a list of (data_type, canonical_value) pairs, kept only in local
    memory by every caller -- this function does not log, cache, or persist
    a single value it reads.

    Raises:
        NoSubjectIdentifiersError: the file has no classifiable (non-blank)
            line. The message names the subject-file path, never a line's
            content.
    """
    path = Path(subject_file)
    raw_lines = path.read_text(encoding="utf-8").splitlines()

    identifiers: list[tuple[str, str]] = []
    for line in raw_lines:
        data_type = _classify_subject_line(line)
        if data_type is None:
            continue
        identifiers.append((data_type, canonical_value(data_type, line.strip())))

    if not identifiers:
        raise NoSubjectIdentifiersError(
            f"Subject file has no identifiable line (expected one Thai national id, "
            f"passport, phone, email, or name per line): {path}"
        )
    return identifiers


def _entity_matches_any_subject_value(
    subject_type: str, subject_values: set[str], entity_text: str
) -> bool:
    """Whether `entity_text` (a detected entity's raw text, ANY detector
    label) is a legitimate spelling of one of the subject's `subject_type`
    identifiers -- the label-independent half of F1's fix.

    For every type except PHONE this is exactly `canonical_value`'s own
    normalization: no rewrite beyond folding formatting (spaces, hyphens,
    case), so an accidental cross-type collision would require the two
    values to already be identical once formatting is stripped.

    PHONE needs an extra guard. `canonical_value("PHONE", ...)` folds an
    11/10-digit run starting "66" down to the domestic "0..." form, because
    "+66 81 234 5678" and "081-234-5678" are the same legitimate spelling of
    one Thai mobile number. But that fold does not require the source text
    to have actually carried a "+" country-code marker -- it fires on bare
    digits alone. A 10/11-digit Thai bank account number that happens to
    start with "66" (no relation to any phone number) would then canonicalize
    to the same domestic form purely by digit coincidence, producing a false
    positive this tool must not make (a DSAR artifact is legal evidence).
    So: a plain domestic-looking match (raw digits equal a subject's already-
    domestic canonical phone) is accepted directly, and the international
    fold is applied ONLY when the entity's own raw text still carries an
    explicit "+66" marker -- bare "66812345678" with no "+" is left
    unmatched, `+66 81 234 5678` (any spacing/labeling) still matches.
    """
    if subject_type == "PHONE":
        digits = re.sub(r"\D", "", entity_text)
        if digits in subject_values:
            return True
        if _PLUS_66_MARKER_RE.search(entity_text):
            return canonical_value("PHONE", entity_text) in subject_values
        return False
    return canonical_value(subject_type, entity_text) in subject_values


def locate_subject(
    paths: Sequence[str | Path],
    subject_file: str | Path,
    *,
    recursive: bool = False,
) -> DsarResult:
    """Locate which of `paths` mention the subject named in `subject_file`.

    `subject_file` holds one identifier per line (Thai national id, passport,
    phone, email, or full name), classified by shape. Each document runs the
    product's own pipeline (`extract` -> `clean` -> `detect_all`); a detected
    entity matches the subject when its raw text, canonicalized under a
    subject identifier's own type rules, equals that subject identifier's
    canonical value -- value-based only, the detector's own label for that
    entity is never consulted (exact match, no fuzzy matching -- see
    `_METHOD_STATEMENT`). A matched file whose ONLY matched identifier type is
    NAME is flagged `weak_only` (see `_NAME_WEAK_MATCH_NOTE`). A file that
    fails to process is recorded as a `FailedFile` (basename + exception
    class/short reason -- never its content) and the run continues. Unmatched
    files are counted but never listed as rows.

    Raises:
        NoSubjectIdentifiersError: the subject file has no classifiable line.
        NoFilesAssessedError: no document could be assessed (none found, or
            every one failed to process).
    """
    subject_identifiers = _read_subject_identifiers(subject_file)

    subject_counts: dict[str, int] = {}
    subject_lookup: dict[str, set[str]] = {}
    for data_type, value in subject_identifiers:
        subject_counts[data_type] = subject_counts.get(data_type, 0) + 1
        subject_lookup.setdefault(data_type, set()).add(value)

    files, skipped_names = discover_files(paths, recursive=recursive)
    files_total = len(files) + len(skipped_names)

    matched_files: list[MatchedFile] = []
    failed: list[FailedFile] = []

    for path in files:
        try:
            source_type = detect_source_type(path)
            raw_text, _bboxes, meta = extract(path, source_type)
            text = clean(raw_text).text
            entities = detect_all(text)
        except Exception as exc:
            failed.append(FailedFile(basename=path.name, reason=short_reason(exc, path)))
            continue

        type_counts: dict[str, int] = {}
        matched_identifier_counts: dict[str, int] = {}
        for entity in entities:
            type_counts[entity.data_type] = type_counts.get(entity.data_type, 0) + 1
            # Value-based, not label-based (F1): the detector's own data_type
            # for this entity is never consulted here. Every subject identifier
            # TYPE gets a turn at checking this entity's raw text against that
            # type's own subject values, because the detector's label is a
            # contextual guess (the same value can be tagged BANK_ACCOUNT in
            # one document and PHONE in another) and is not a property of the
            # value itself -- see _METHOD_STATEMENT. The comparison itself is
            # delegated to `_entity_matches_any_subject_value`, which for PHONE
            # additionally guards against a bare "66"-prefixed digit run
            # (e.g. an unrelated bank account) being folded into a false
            # match with a +66 phone spelling it never actually carried.
            for subject_type, subject_values in subject_lookup.items():
                if _entity_matches_any_subject_value(
                    subject_type, subject_values, entity.original_text
                ):
                    matched_identifier_counts[subject_type] = (
                        matched_identifier_counts.get(subject_type, 0) + 1
                    )

        if not matched_identifier_counts:
            continue

        third_party_possible = sum(type_counts.values()) > sum(matched_identifier_counts.values())
        # weak_only (F2): true only when NAME is the ONLY identifier type that
        # matched -- a checksum-backed id/passport/phone/email match on the
        # same file makes it False even if a NAME also happened to match.
        weak_only = set(matched_identifier_counts) == {"NAME"}
        reid = assess_reid_risk(text)

        matched_files.append(
            MatchedFile(
                basename=path.name,
                source_type=source_type,
                matched_identifier_counts=dict(sorted(matched_identifier_counts.items())),
                type_counts=dict(sorted(type_counts.items())),
                risk_grade=reid.grade,
                human_review=bool(meta.get("human_review", False)),
                third_party_possible=third_party_possible,
                weak_only=weak_only,
            )
        )

    # files_assessed counts every file the pipeline actually ran on --
    # matched or not -- mirroring breach.py's own definition (assessed !=
    # matched, the same way breach's assessed != "flagged for section 26").
    files_assessed = files_total - len(skipped_names) - len(failed)
    if files_assessed == 0:
        raise NoFilesAssessedError(
            f"No files could be assessed: {files_total} discovered, "
            f"{len(skipped_names)} skipped, {len(failed)} failed"
        )

    return DsarResult(
        subject_counts=dict(sorted(subject_counts.items())),
        files_total=files_total,
        files_assessed=files_assessed,
        files_failed=failed,
        files_skipped=skipped_names,
        matched_files=matched_files,
        environment=_environment(),
        assessed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
