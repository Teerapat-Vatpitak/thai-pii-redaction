"""Processing receipt for PDPA มาตรา 39 — one slip per run, verified by rerunning.

Section 39 asks a data controller to keep a record of its processing
activities. The obvious reading is a cumulative register (a RoPA) that grows
over time, and this project cannot honestly keep one: the vault is in memory,
the hosted path is stateless by contract, and nothing about a document survives
the request that carried it. A register would mean starting to retain exactly
what the product promises not to retain.

So the record here is a **per-run slip**. Each run of AI Guard over a document
can emit one receipt, the operator keeps it beside their own file, and the
receipt says what was processed, how much of it, by which version of the system,
and when. It records the processing; it does not record the person.

Authenticity comes from **recomputation, not signature**. A signature would
prove who issued a receipt and prove nothing about whether it describes reality
— and it needs a key to keep, which is one more secret than a local-first tool
should ask for. Instead the receipt carries two digests: one over the source
bytes, one over the detection result. Hand `verify` the receipt and the original
file and it runs the same pipeline again; if the file is the same file and the
system still sees the same thing in it, the digests match. That is the same
position `docs/decisions/2026-07-29-store-distribution-and-signing.md` takes on
the installer — trust is earned by being checkable, not by a certificate.

Two things are deliberately outside the result digest:

- `entity_id` is a fresh UUID4 per run, so including it would make every
  receipt unverifiable by construction.
- `score` is a detector's internal confidence. A PyThaiNLP patch release could
  move a float without moving a single span, and a receipt that fails
  verification over that would train its reader to ignore failures. What the
  receipt attests to is which spans of what type were treated as personal
  data — the thing that decides what gets masked.

Nothing here reads an entity's text. A receipt carries counts, types, offsets'
digest and hashes; never a value.
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
    ("result", "digest"),
    ("environment", "product_version"),
    ("environment", "ner_engine"),
)

_ENVIRONMENT_KEYS = ("product_version", "ner_engine")


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


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    """
    path = Path(path)
    processed = process_for_receipt(path)

    type_counts: dict[str, int] = {}
    for entity in processed.entities:
        type_counts[entity.data_type] = type_counts.get(entity.data_type, 0) + 1

    activity: dict = {"operation": operation}
    if purpose:
        activity["purpose"] = purpose
    if controller:
        activity["controller"] = controller

    return {
        "schema": RECEIPT_SCHEMA,
        "issued_at": issued_at or _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "activity": activity,
        "source": {
            "sha256": _source_sha256(path),
            "bytes": path.stat().st_size,
            "source_type": processed.source_type,
        },
        "result": {
            "digest": result_digest(processed.entities),
            "entity_count": len(processed.entities),
            "fp_count": sum(1 for e in processed.entities if e.redact_type == "FP"),
            "tb_count": sum(1 for e in processed.entities if e.redact_type != "FP"),
            "type_counts": dict(sorted(type_counts.items())),
        },
        "environment": {
            "product_version": _read_version(),
            "ner_engine": _resolve_engine_name(),
        },
    }


def _missing_fields(receipt: dict) -> list[str]:
    missing = []
    for section, key in _REQUIRED_PATHS:
        value = receipt.get(section)
        if not isinstance(value, dict) or key not in value:
            missing.append(f"{section}.{key}")
    return missing


def verify_receipt(receipt: dict, path: str | Path) -> VerifyResult:
    """Re-run `path` and report whether it still produces this receipt.

    The two digests are kept apart so the answer distinguishes "this is not the
    document the receipt was issued for" from "same document, the system now
    sees something different in it". Collapsing them into one pass/fail would
    make a version upgrade look like a swapped file.

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
    actual_sha = _source_sha256(path)
    environment = {
        "product_version": _read_version(),
        "ner_engine": _resolve_engine_name(),
    }
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

    processed = process_for_receipt(path)
    actual_digest = result_digest(processed.entities)
    recomputed = {
        "source_sha256": actual_sha,
        "result_digest": actual_digest,
        "entity_count": len(processed.entities),
    }
    if actual_digest != receipt["result"]["digest"]:
        return VerifyResult(
            ok=False,
            outcome="result_mismatch",
            differences=[
                f"result digest: receipt {receipt['result']['digest']}, now {actual_digest}"
            ]
            + env_differences,
            recomputed=recomputed,
        )
    return VerifyResult(
        ok=True, outcome="match", differences=env_differences, recomputed=recomputed
    )
