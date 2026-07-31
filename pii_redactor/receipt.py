"""Create one PDPA section 39 receipt for each run.

Verification runs the same input again and compares digests. The receipt keeps
counts, types, hashes, and offsets, but never document values. ``entity_id`` and
``score`` stay out of the digest so a new run can match. ``purpose`` and
``controller`` are user text and may contain personal data.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.tb_detector import _resolve_engine_name
from pii_redactor.ingest.file_detector import detect_source_type
from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.ingest.text_extractor import extract
from pii_redactor.models import Entity

RECEIPT_SCHEMA = "aiguard.processing-receipt/1"

# Every field `verify` needs to do its job. A receipt missing one of these is
# rejected rather than partially checked -- "verified" has to mean all of it.
_REQUIRED_PATHS = (
    ("source", "sha256"),
    ("source", "bytes"),
    ("source", "source_type"),
    ("result", "digest"),
    ("result", "entity_count"),
    ("result", "fp_count"),
    ("result", "tb_count"),
    ("result", "type_counts"),
    ("environment", "product_version"),
    ("environment", "ner_engine"),
    ("environment", "detector_version"),
)

_ENVIRONMENT_KEYS = ("product_version", "ner_engine", "detector_version")


class SourceChangedError(RuntimeError):
    """The input file changed while the receipt was being issued."""


@dataclass
class ProcessedSource:
    """What one run of the pipeline saw. The unit `verify` recomputes."""

    text: str
    entities: list[Entity]
    source_type: str


@dataclass
class VerifyResult:
    ok: bool
    outcome: str  # match | source_mismatch | result_mismatch |
    # unsupported_schema | malformed_receipt
    differences: list[str] = field(default_factory=list)
    recomputed: dict = field(default_factory=dict)


def _read_version() -> str:
    """The product version, or "unknown" when the VERSION file is unreachable.

    Deliberately does NOT carry a fallback literal the way `app/server.py` does.
    A third hardcoded copy of the version would be one more thing for
    `scripts/check_version.py` to police, and a receipt that guesses its own
    version is worse than one that admits it does not know: the guess would be
    silently wrong on exactly the frozen builds where it matters.
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


def process_for_receipt(path: str | Path) -> ProcessedSource:
    """Ingest, clean and detect — the single path both issuing and verifying run.

    Shared on purpose rather than duplicated: if issuing and verifying could
    drift apart, a receipt would start failing against its own document and the
    verifier would be measuring itself.
    """
    source_type = detect_source_type(path)
    raw_text, _bboxes, _meta = extract(path, source_type)
    text = clean(raw_text).text
    return ProcessedSource(text=text, entities=detect_all(text), source_type=source_type)


def result_digest(entities: list[Entity]) -> str:
    """A digest over what detection found — spans and types, nothing else.

    Sorted before hashing so detector ordering, which is an implementation
    detail, cannot change the digest. See the module docstring for what is
    excluded and why.
    """
    rows = sorted([e.span[0], e.span[1], e.data_type, e.redact_type] for e in entities)
    # The schema string is in the preimage so a future schema that hashes
    # different material can never collide with a v1 digest.
    preimage = RECEIPT_SCHEMA + "\n" + json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def _source_fingerprint(path: Path) -> tuple[str, int]:
    """Hash and size from ONE pass over the bytes.

    Together rather than separately so the two can never describe different
    reads of a file that is changing underneath us.
    """
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _detector_version() -> str:
    """The PyThaiNLP release that produced the detection result.

    `requirements.txt` carries a loose `>=` floor, so two machines reporting
    the same `product_version` can be running different CRF models. Without
    this field a genuine version difference surfaces as a `result_mismatch`
    with an EMPTY list of differences -- the likeliest explanation would be
    the one thing the receipt could not see.
    """
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


def _claims(processed: ProcessedSource, sha256: str, size: int) -> dict:
    """The factual half of a receipt — everything `verify` recomputes.

    Built in one place and used by BOTH `build_receipt` and `verify_receipt`,
    which is the point. The first version of this module compared only the two
    digests, so `entity_count`, the per-type counts, the file size and the
    source type rode along unverified: a receipt could be edited to claim zero
    entities found and still verify clean, while the verifier had the real
    numbers in hand and discarded them. Anything that goes in here from now on
    is checked by construction rather than by someone remembering to add a
    comparison.
    """
    type_counts: dict[str, int] = {}
    for entity in processed.entities:
        type_counts[entity.data_type] = type_counts.get(entity.data_type, 0) + 1
    return {
        "source": {
            "sha256": sha256,
            "bytes": size,
            "source_type": processed.source_type,
        },
        "result": {
            "digest": result_digest(processed.entities),
            "entity_count": len(processed.entities),
            "fp_count": sum(1 for e in processed.entities if e.redact_type == "FP"),
            "tb_count": sum(1 for e in processed.entities if e.redact_type != "FP"),
            "type_counts": dict(sorted(type_counts.items())),
        },
    }


def build_receipt(
    path: str | Path,
    *,
    purpose: str | None = None,
    controller: str | None = None,
    operation: str = "detect",
    issued_at: str | None = None,
) -> dict:
    """Run the pipeline over `path` and return the receipt describing that run.

    `purpose` and `controller` are Section 39 fields only the operator can
    answer, so they appear only when supplied. Inventing a plausible default
    for either would put a claim in a compliance document that nobody made.
    Note that both are free text the operator typed: they are the one part of
    a receipt that is not derived from the document, and nothing here inspects
    them.

    Raises:
        SourceChangedError: the file's bytes changed while it was being read.
    """
    path = Path(path)
    # Fingerprinted on both sides of the pipeline. Detection takes real time on
    # a large document, and a file rewritten in that window would otherwise
    # produce a receipt whose hash describes the new bytes and whose findings
    # describe the old ones -- internally inconsistent, unverifiable forever,
    # and diagnosed later as `result_mismatch`, which would be a lie about what
    # went wrong.
    before, _ = _source_fingerprint(path)
    processed = process_for_receipt(path)
    after, size = _source_fingerprint(path)
    if before != after:
        raise SourceChangedError(
            f"{path} changed while the receipt was being issued; nothing can be "
            f"attested about a file that moved under the reader"
        )

    activity: dict = {"operation": operation}
    if purpose:
        activity["purpose"] = purpose
    if controller:
        activity["controller"] = controller

    return {
        "schema": RECEIPT_SCHEMA,
        "issued_at": issued_at or _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "activity": activity,
        **_claims(processed, after, size),
        "environment": _environment(),
    }


def _missing_fields(receipt: dict) -> list[str]:
    missing = []
    for section, key in _REQUIRED_PATHS:
        value = receipt.get(section)
        if not isinstance(value, dict) or key not in value:
            missing.append(f"{section}.{key}")
    return missing


def _diff_claims(receipt: dict, actual: dict) -> list[str]:
    """Every field of the recomputation that the receipt disagrees with."""
    differences = []
    for section, fields in actual.items():
        for key, value in fields.items():
            claimed = receipt[section].get(key)
            if claimed != value:
                differences.append(f"{section}.{key}: receipt {claimed!r}, now {value!r}")
    return differences


def verify_receipt(receipt: dict, path: str | Path) -> VerifyResult:
    """Re-run `path` and report whether it still produces this receipt.

    EVERY factual field is compared, not just the two digests. That distinction
    is the whole difference between a receipt and a decorated guess: the digest
    covers which spans of what type were found, but what a person reads off the
    page is "7 entities, 3 of them names" — and until this compared the counts
    too, those numbers could be edited to anything at all and the tool would
    still print that the document and the result matched. `_claims()` is the
    single source for both sides so a field cannot be added on one side only.

    The source hash is checked first and on its own, so the answer distinguishes
    "this is not the document the receipt was issued for" from "same document,
    the system now sees something different in it". Collapsing them would make a
    version upgrade look like a swapped file.

    A mismatch is reported with whatever changed in the environment alongside
    it, because that is almost always the explanation. An environment
    difference that did NOT change the result is reported too, on the other
    side of the ledger: reproducing across versions is a stronger result than
    reproducing on the same one.
    """
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return VerifyResult(
            ok=False,
            outcome="unsupported_schema",
            differences=[f"schema {receipt.get('schema')!r}, this build reads {RECEIPT_SCHEMA!r}"],
        )
    missing = _missing_fields(receipt)
    if missing:
        return VerifyResult(
            ok=False,
            outcome="malformed_receipt",
            differences=[f"missing field {name}" for name in missing],
        )

    path = Path(path)
    actual_sha, actual_size = _source_fingerprint(path)
    environment = _environment()
    env_differences = [
        f"{key}: receipt {receipt['environment'][key]!r}, now {environment[key]!r}"
        for key in _ENVIRONMENT_KEYS
        if receipt["environment"][key] != environment[key]
    ]

    if actual_sha != receipt["source"]["sha256"]:
        # Stop here. Recomputing a result for a document the receipt never
        # described would produce a second mismatch that says nothing.
        return VerifyResult(
            ok=False,
            outcome="source_mismatch",
            differences=[f"source sha256: receipt {receipt['source']['sha256']}, file {actual_sha}"]
            + env_differences,
            recomputed={"source_sha256": actual_sha},
        )

    try:
        processed = process_for_receipt(path)
    except Exception as e:
        # The bytes are right but the pipeline cannot read them again. The
        # ordinary cause is a renamed file -- `detect_source_type` routes on the
        # extension, so a PDF copied to `.txt` fails to decode. Reported as its
        # own outcome, because letting this surface as a raw error made a
        # correct file look like a broken tool.
        return VerifyResult(
            ok=False,
            outcome="recompute_failed",
            differences=[
                f"the file's bytes match the receipt but it could not be processed "
                f"again as {receipt['source']['source_type']!r}: {e}"
            ]
            + env_differences,
            recomputed={"source_sha256": actual_sha, "source_bytes": actual_size},
        )

    actual = _claims(processed, actual_sha, actual_size)
    recomputed = {**actual["source"], **actual["result"]}
    claim_differences = _diff_claims(receipt, actual)
    if claim_differences:
        return VerifyResult(
            ok=False,
            outcome="result_mismatch",
            differences=claim_differences + env_differences,
            recomputed=recomputed,
        )
    return VerifyResult(
        ok=True, outcome="match", differences=env_differences, recomputed=recomputed
    )
