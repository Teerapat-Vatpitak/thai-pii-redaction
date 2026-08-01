"""Shared file-discovery and value-canonicalization helpers for the
corpus-scanning storefronts (`breach.py`, `dsar.py`).

Extracted verbatim from `pii_redactor/breach.py` (Track D #2) when the second
caller (`dsar.py`, Track D #3) needed the identical behavior. `breach.py`
imports these under its old private names so its own tests (which import
`_canonical_value` directly) keep working unmodified. The extraction itself
was a pure move, but `path_spellings` was extended afterward (adding the
backslash-doubled and `repr()`-stripped spellings a real `OSError` message
embeds), which changed `short_reason`'s scrubbing behavior for both callers --
see `docs/decisions/2026-08-01-dsar-helper.md`'s "A fix that came out of this
work" section.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

_DISCOVER_SUFFIXES = (".txt", ".pdf")

_NAME_TYPE = "NAME"

_NAME_TITLE_RE = re.compile(r"^(?:นางสาว|นาย|นาง|น\.ส\.|ด\.ช\.|ด\.ญ\.|เด็กชาย|เด็กหญิง|คุณ)\s*")


def path_spellings(path: Path) -> set[str]:
    """Every string spelling of `path` a caught exception's own message might
    embed -- as given, resolved, both slash directions, AND the repr-escaped
    forms CPython's `OSError.__str__` actually produces.

    `OSError.__str__` formats its filename with `%R` (Python's own `repr()`),
    which backslash-escapes a Windows path -- a real `FileNotFoundError` from
    e.g. `Path.read_bytes()` on a missing file embeds the path as
    `'C:\\\\Users\\\\...\\\\missing.txt'` (doubled backslashes), which none of
    the plain single-backslash/forward-slash spellings match as a substring.
    Shared by `short_reason` (per-file scrub) and `ai_guard._scrub_known_paths`
    (corpus-level scrub) so this escaping only has to be handled once.
    """
    spellings = {str(path)}
    try:
        spellings.add(str(path.resolve()))
    except OSError:
        pass
    for spelling in list(spellings):
        spellings.add(spelling.replace("\\", "/"))
        spellings.add(spelling.replace("/", "\\"))
    for spelling in list(spellings):
        spellings.add(spelling.replace("\\", "\\\\"))
        spellings.add(repr(spelling)[1:-1])
    return spellings


def short_reason(exc: Exception, path: Path) -> str:
    """`{ExceptionClassName} {message}` with the input file's own path
    scrubbed out of the message.

    A failed-file row is documented as "basename + short reason, never
    content" -- but several stdlib exceptions embed the FULL operand path in
    their own message (`FileNotFoundError`: "[Errno 2] No such file or
    directory: 'C:\\\\Users\\\\...\\\\missing.txt'" -- note the DOUBLED
    backslashes: `OSError.__str__` formats the filename via `repr()`), which
    can carry a directory name the controller did not intend to disclose.
    Every spelling of `path` this process is likely to have produced --
    see `path_spellings` -- is folded down to the bare basename, which is
    already a value this report shows elsewhere. A space separates the class
    name from the message rather than a colon -- this reason string can reach
    Thai-facing CLI/PDF output, and Thai punctuation uses spaces, not Western
    colons.
    """
    message = str(exc)
    basename = path.name
    for spelling in path_spellings(path):
        if spelling and spelling != basename:
            message = message.replace(spelling, basename)
    return f"{type(exc).__name__} {message}"


def discover_files(paths: Sequence[str | Path], *, recursive: bool) -> tuple[list[Path], list[str]]:
    """Resolve `paths` to a deterministic, de-duplicated list of files, plus the
    basenames a directory scan chose not to look at.

    A directory is scanned for *.txt/*.pdf (non-recursive unless `recursive`);
    every other file the scan finds there is reported back as skipped rather
    than dropped silently -- a report must not claim it covered a folder when
    it only opened a subset of what was in it. A path that is not a directory
    is taken as-is, even if it does not exist or carries a different
    extension -- the caller named it explicitly, and letting it reach the
    caller's own per-file try/except turns a bad path into a failed-file row
    instead of a silent skip (this rule does not apply to directory contents,
    which is exactly what "skipped" now surfaces).
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


def canonical_value(data_type: str, value: str) -> str:
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
