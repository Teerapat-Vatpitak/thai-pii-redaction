"""Blind held-out evaluation set: locked storage, aggregate-only scoring.

Track A rule one: tuning happens on the gold set; the blind set exists to
measure whether that tuning generalizes. Its corpus must therefore never enter
a development context — including the AI coding agents that grep and read this
repository. The mechanisms here exist for that one purpose:

- The corpus is committed only as an authenticated, obfuscated blob
  (``data/<version>.enc``). The keystream construction (HMAC-SHA256 in counter
  mode plus a separate authentication MAC) is **blinding against accidental
  reading and grep, not security against an adversary** — anyone with the key
  file can decrypt, and that is fine; the threat model is self-deception, not
  attackers.
- The key lives OUTSIDE the repository and is supplied explicitly via the
  ``AIGUARD_BLIND_KEY_FILE`` environment variable. There is no default
  discovery path, so routine tooling cannot stumble into the plaintext.
- ``data/<version>.lock.json`` pins the plaintext and ciphertext hashes plus
  aggregate composition counts. Scoring refuses a corpus whose hash does not
  match the lock.
- Scoring output is AGGREGATE ONLY: counts and metrics, never document text,
  entity values, or per-document diffs. Error paths raise :class:`BlindError`
  with generic messages for the same reason.
- Every scoring run — the protocol calls one a "reveal" — appends a
  hash-chained entry to ``data/blind-scores.jsonl`` (committed), so how often
  the holdout was consulted is itself auditable. The lock carries a reveal
  budget; runs beyond it are recorded with ``over_budget: true``.

The full protocol, including authoring, pre-freeze QA, family definitions, and
rotation rules, is docs/decisions/2026-07-28-blind-set-protocol.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .gold import SLICE_LAYERS, parse_gold
from .scorer import _prf, _score_group, score
from .types import Sample

BLIND_VERSION = "blind-v1"
DATA_DIR = Path(__file__).with_name("data")
LOG_NAME = "blind-scores.jsonl"
MAGIC = "AIGUARD-BLIND"
FORMAT = 1

# Predeclared metric families (see the protocol ADR). Declared here, before the
# first blind reveal, so pooling cannot be invented after seeing results.
STRUCTURED_TYPES = (
    "THAI_ID",
    "CREDIT_CARD",
    "BANK_ACCOUNT",
    "PHONE",
    "EMAIL",
    "PASSPORT",
    "VEHICLE_PLATE",
    "STUDENT_ID",
)
CONTEXTUAL_TYPES = ("NAME", "ADDRESS", "DATE_OF_BIRTH")
ALLOWED_TYPES = set(STRUCTURED_TYPES) | set(CONTEXTUAL_TYPES)

# Per-type counts below this are reported but labeled descriptive: a single
# entity flips recall by more than a benchmark-worthy delta.
DESCRIPTIVE_N = 50

_MARKUP = re.compile(r"\[\[([A-Z_]+)\|(.*?)\]\]")


class BlindError(RuntimeError):
    """Raised on any blind-protocol failure.

    Messages must stay generic: no document text, no entity values, no
    plaintext fragments — a traceback is an output channel too.
    """


# ---------------------------------------------------------------------------
# key handling and cipher (blinding, not security — see module docstring)
# ---------------------------------------------------------------------------


def generate_key(key_path: Path) -> None:
    key_path = Path(key_path)
    if key_path.exists():
        raise BlindError(f"refusing to overwrite existing key file: {key_path}")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(secrets.token_hex(32), encoding="ascii")


def load_master(key_path: str | Path) -> bytes:
    try:
        text = Path(key_path).read_text(encoding="ascii").strip()
        master = bytes.fromhex(text)
    except FileNotFoundError:
        raise BlindError(f"blind key file not found: {key_path}") from None
    except ValueError:
        raise BlindError("blind key file is not valid hex") from None
    if len(master) < 32:
        raise BlindError("blind key must be at least 32 bytes of hex")
    return master


def _subkeys(master: bytes) -> tuple[bytes, bytes]:
    enc = hmac.new(master, b"aiguard-blind-enc", hashlib.sha256).digest()
    auth = hmac.new(master, b"aiguard-blind-auth", hashlib.sha256).digest()
    return enc, auth


def _keystream(enc_key: bytes, version: str, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    prefix = version.encode("utf-8") + b"\x00" + nonce
    while len(out) < length:
        block = hmac.new(enc_key, prefix + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: bytes, master: bytes, version: str = BLIND_VERSION) -> bytes:
    enc_key, auth_key = _subkeys(master)
    nonce = secrets.token_bytes(16)
    stream = _keystream(enc_key, version, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    header = json.dumps(
        {"magic": MAGIC, "format": FORMAT, "version": version, "nonce": nonce.hex()},
        sort_keys=True,
    ).encode("ascii")
    mac = hmac.new(auth_key, header + b"\n" + ciphertext, hashlib.sha256).hexdigest()
    return header + b"\n" + base64.b64encode(ciphertext) + b"\n" + mac.encode("ascii") + b"\n"


def decrypt(blob: bytes, master: bytes) -> tuple[str, bytes]:
    enc_key, auth_key = _subkeys(master)
    try:
        header_b, body_b, mac_b = blob.split(b"\n")[:3]
        header = json.loads(header_b)
        ciphertext = base64.b64decode(body_b, validate=True)
    except Exception:
        raise BlindError("blind blob is malformed") from None
    if header.get("magic") != MAGIC or header.get("format") != FORMAT:
        raise BlindError("blind blob has an unknown header")
    expected = hmac.new(auth_key, header_b + b"\n" + ciphertext, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac_b.decode("ascii", "replace")):
        raise BlindError("blind blob failed authentication (wrong key or tampered file)")
    version = header["version"]
    nonce = bytes.fromhex(header["nonce"])
    stream = _keystream(enc_key, version, nonce, len(ciphertext))
    return version, bytes(a ^ b for a, b in zip(ciphertext, stream))


# ---------------------------------------------------------------------------
# freeze: validate a draft, then write blob + lock
# ---------------------------------------------------------------------------

TYPE_MINIMUMS = {
    "NAME": 70,
    "ADDRESS": 60,
    "PHONE": 45,
    "EMAIL": 35,
    "THAI_ID": 35,
    "BANK_ACCOUNT": 35,
    "DATE_OF_BIRTH": 35,
    "CREDIT_CARD": 25,
    "PASSPORT": 25,
    "VEHICLE_PLATE": 25,
    "STUDENT_ID": 25,
}

_LONG_FORM_ZONES = (450, 550)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _thai_id_ok(digits: str) -> bool:
    if len(digits) != 13:
        return False
    check = (11 - sum(int(digits[i]) * (13 - i) for i in range(12)) % 11) % 10
    return check == int(digits[12])


def validate_draft(records: list[dict], type_minimums: dict | None = None) -> list[tuple[str, str]]:
    """Return (doc_id, error-kind) pairs. NEVER include values in the pairs."""
    minimums = TYPE_MINIMUMS if type_minimums is None else type_minimums
    errors: list[tuple[str, str]] = []
    ids: set[str] = set()
    type_counts: Counter = Counter()
    seen_values: dict[tuple[str, str], str] = {}

    for r in records:
        doc_id = str(r.get("doc_id", "?"))
        slice_ = r.get("slice")
        annotated = r.get("annotated", "")
        if doc_id in ids:
            errors.append((doc_id, "duplicate-doc-id"))
        ids.add(doc_id)
        if slice_ not in SLICE_LAYERS:
            errors.append((doc_id, "unknown-slice"))
            continue
        if r.get("layer") != SLICE_LAYERS[slice_]:
            errors.append((doc_id, "layer-mismatch"))

        marks = list(_MARKUP.finditer(annotated))
        stripped = _MARKUP.sub(lambda m: m.group(2), annotated)
        if "[[" in stripped or "]]" in stripped:
            errors.append((doc_id, "unbalanced-markup"))

        if slice_ == "negative":
            if marks:
                errors.append((doc_id, "negative-has-markup"))
            if re.search(r"\d{13}", stripped):
                errors.append((doc_id, "negative-contains-13-digit-run"))
            continue

        if not marks:
            errors.append((doc_id, "positive-doc-without-entities"))

        sample = parse_gold(doc_id, slice_, annotated)
        starts = [g.start for g in sample.spans]
        if slice_ == "long_form":
            lo, hi = _LONG_FORM_ZONES
            if len(stripped) <= 500:
                errors.append((doc_id, "long-form-too-short"))
            if not (
                any(s < lo for s in starts)
                and any(lo <= s <= hi for s in starts)
                and any(s > hi for s in starts)
            ):
                errors.append((doc_id, "long-form-missing-boundary-zone-entity"))

        for g, m in zip(sample.spans, marks):
            etype, value = m.group(1), m.group(2)
            if etype not in ALLOWED_TYPES:
                errors.append((doc_id, f"unknown-type-{etype}"))
                continue
            type_counts[etype] += 1
            digits = re.sub(r"\D", "", value)
            if etype == "THAI_ID" and not _thai_id_ok(digits):
                errors.append((doc_id, "thai-id-bad-checksum"))
            if etype == "CREDIT_CARD" and not (13 <= len(digits) <= 16 and _luhn_ok(digits)):
                errors.append((doc_id, "credit-card-bad-checksum"))
            key = (etype, value)
            if key in seen_values and seen_values[key] != doc_id:
                errors.append((doc_id, "value-reused-across-docs"))
            seen_values[key] = doc_id

    for etype, minimum in minimums.items():
        if type_counts[etype] < minimum:
            errors.append(("<corpus>", f"type-below-minimum-{etype}"))
    return errors


def freeze(
    draft_path: str | Path,
    key_path: str | Path,
    data_dir: Path = DATA_DIR,
    version: str = BLIND_VERSION,
    type_minimums: dict | None = None,
    reveal_budget: int = 6,
    force: bool = False,
) -> dict:
    """Validate the plaintext draft, then write ``<version>.enc`` + lock."""
    draft_path = Path(draft_path)
    if Path(data_dir).resolve() in draft_path.resolve().parents:
        raise BlindError("draft plaintext must live outside the repository data dir")
    raw = draft_path.read_bytes()
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    errors = validate_draft(records, type_minimums=type_minimums)
    if errors:
        listing = ", ".join(f"{d}:{k}" for d, k in errors[:40])
        raise BlindError(f"draft failed validation ({len(errors)} errors): {listing}")

    lock_path = Path(data_dir) / f"{version}.lock.json"
    enc_path = Path(data_dir) / f"{version}.enc"
    if (lock_path.exists() or enc_path.exists()) and not force:
        raise BlindError(f"{version} is already frozen; freezing again requires force=True")

    master = load_master(key_path)
    blob = encrypt(raw, master, version)
    slice_counts = Counter(r["slice"] for r in records)
    type_counts: Counter = Counter()
    for r in records:
        for m in _MARKUP.finditer(r["annotated"]):
            type_counts[m.group(1)] += 1
    lock = {
        "version": version,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "plaintext_sha256": hashlib.sha256(raw).hexdigest(),
        "ciphertext_sha256": hashlib.sha256(blob).hexdigest(),
        "documents": len(records),
        "slice_counts": dict(sorted(slice_counts.items())),
        "type_counts": dict(sorted(type_counts.items())),
        "reveal_budget": reveal_budget,
        "protocol": "docs/decisions/2026-07-28-blind-set-protocol.md",
    }
    enc_path.write_bytes(blob)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return lock


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def load_lock(data_dir: Path = DATA_DIR, version: str = BLIND_VERSION) -> dict:
    lock_path = Path(data_dir) / f"{version}.lock.json"
    try:
        return json.loads(lock_path.read_text(encoding="ascii"))
    except FileNotFoundError:
        raise BlindError(f"no lock file for {version}; the blind set is not frozen yet") from None


def load_blind(
    key_file: str | Path, data_dir: Path = DATA_DIR, version: str = BLIND_VERSION
) -> tuple[list[Sample], dict]:
    lock = load_lock(data_dir, version)
    blob = (Path(data_dir) / f"{version}.enc").read_bytes()
    if hashlib.sha256(blob).hexdigest() != lock["ciphertext_sha256"]:
        raise BlindError("ciphertext does not match the lock file")
    header_version, plaintext = decrypt(blob, load_master(key_file))
    if header_version != version:
        raise BlindError("blob version does not match the requested version")
    if hashlib.sha256(plaintext).hexdigest() != lock["plaintext_sha256"]:
        raise BlindError("decrypted corpus does not match the lock file")
    try:
        records = [
            json.loads(line) for line in plaintext.decode("utf-8").splitlines() if line.strip()
        ]
        samples = [parse_gold(r["doc_id"], r["slice"], r["annotated"]) for r in records]
    except Exception:
        raise BlindError("blind corpus failed to parse") from None
    return samples, lock


# ---------------------------------------------------------------------------
# scoring run ("reveal") with hash-chained audit log
# ---------------------------------------------------------------------------


def code_digest() -> str:
    """One digest over the benchmark package sources bound into each log entry.

    A score is only comparable to another score if the evaluator was the same;
    this makes a silent scorer change visible in the audit log.
    """
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        h.update(path.name.encode())
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def git_state() -> dict:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return {"head": head, "dirty": dirty}
    except Exception:
        return {"head": None, "dirty": None}


def _entry_hash(entry: dict) -> str:
    payload = json.dumps(
        {k: v for k, v in entry.items() if k != "entry_sha256"},
        sort_keys=True,
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def read_log(log_path: Path) -> list[dict]:
    if not Path(log_path).exists():
        return []
    return [
        json.loads(line)
        for line in Path(log_path).read_text(encoding="ascii").splitlines()
        if line.strip()
    ]


def verify_log(log_path: Path) -> int:
    entries = read_log(log_path)
    prev = None
    for i, entry in enumerate(entries):
        if entry.get("prev_sha256") != prev:
            raise BlindError(f"blind score log chain broken at entry {i}")
        if _entry_hash(entry) != entry.get("entry_sha256"):
            raise BlindError(f"blind score log entry {i} does not match its hash")
        prev = entry["entry_sha256"]
    return len(entries)


def _bootstrap_f2_ci(
    samples: list[Sample],
    predictions: list[list[tuple[int, int, str]]],
    iters: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap over DOCUMENTS for overall entity-level F2.

    Documents are the resampling unit because entities inside one document are
    correlated; resampling entities would overstate precision.
    """
    import random

    per_doc: list[tuple[int, int, int]] = []
    for s, p in zip(samples, predictions):
        by_type, overall = _score_group([s], [p])
        if overall.get("gold_entities") == 0:
            tp = fn = 0
            fp = overall["false_positives"]
        else:
            tp, fp, fn = overall["tp"], overall["fp"], overall["fn"]
        per_doc.append((tp, fp, fn))
    rng = random.Random(seed)
    n = len(per_doc)
    f2s = []
    for _ in range(iters):
        tp = fp = fn = 0
        for _ in range(n):
            a, b, c = per_doc[rng.randrange(n)]
            tp += a
            fp += b
            fn += c
        f2s.append(_prf(tp, fp, fn)["f2"])
    f2s.sort()
    return f2s[int(0.025 * iters)], f2s[int(0.975 * iters)]


def _macro(by_type: dict, types: tuple[str, ...], metric: str) -> float | None:
    vals = [by_type[t][metric] for t in types if t in by_type]
    return sum(vals) / len(vals) if vals else None


def run_blind(
    engine: str = "crf",
    key_file: str | Path | None = None,
    reason: str = "",
    data_dir: Path = DATA_DIR,
    log_path: Path | None = None,
    bootstrap_iters: int = 1000,
) -> dict:
    if not key_file:
        raise BlindError(
            "set AIGUARD_BLIND_KEY_FILE to the key file path (kept outside the repository)"
        )
    if not reason.strip():
        raise BlindError("a blind run must state --reason (it is recorded in the audit log)")

    from .runner import predict_samples

    samples, lock = load_blind(key_file, data_dir=data_dir)
    predictions = predict_samples(samples, engine)
    report = score(samples, predictions)

    ci_lo, ci_hi = _bootstrap_f2_ci(samples, predictions, iters=bootstrap_iters)
    negative = report["by_slice"].get("negative")
    result = {
        "version": lock["version"],
        "engine": engine,
        "documents": report["corpus"]["samples"],
        "entities": report["corpus"]["entities"],
        "overall": report["overall"],
        "overall_f2_ci95": [round(ci_lo, 4), round(ci_hi, 4)],
        "families": {
            "structured_macro_f2": _macro(report["by_type"], STRUCTURED_TYPES, "f2"),
            "structured_macro_recall": _macro(report["by_type"], STRUCTURED_TYPES, "recall"),
            "contextual_macro_f2": _macro(report["by_type"], CONTEXTUAL_TYPES, "f2"),
            "contextual_macro_recall": _macro(report["by_type"], CONTEXTUAL_TYPES, "recall"),
        },
        "by_type": {
            t: {**m, "n": report["corpus"]["by_type"].get(t, 0)}
            for t, m in sorted(report["by_type"].items())
        },
        "negative": negative,
    }

    log_path = Path(log_path) if log_path else Path(data_dir) / LOG_NAME
    prior = read_log(log_path)
    prior_reveals = sum(1 for e in prior if e.get("version") == lock["version"])
    over_budget = prior_reveals + 1 > int(lock.get("reveal_budget", 0))
    entry = {
        "schema": 1,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": lock["version"],
        "reveal_index": prior_reveals + 1,
        "reveal_budget": lock.get("reveal_budget"),
        "over_budget": over_budget,
        "reason": reason.strip(),
        "engine": engine,
        "corpus_sha256": lock["plaintext_sha256"],
        "ciphertext_sha256": lock["ciphertext_sha256"],
        "bench_code_sha256": code_digest(),
        "git": git_state(),
        "metrics": {
            "overall": report["overall"],
            "overall_f2_ci95": result["overall_f2_ci95"],
            "families": result["families"],
            "by_type": result["by_type"],
            "negative": negative,
        },
        "prev_sha256": prior[-1]["entry_sha256"] if prior else None,
    }
    entry["entry_sha256"] = _entry_hash(entry)
    with Path(log_path).open("a", encoding="ascii") as f:
        f.write(json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n")

    result["reveal_index"] = entry["reveal_index"]
    result["over_budget"] = over_budget
    return result


def render_blind_table(result: dict) -> str:
    lines = []
    o = result["overall"]
    lines.append(
        f"BLIND {result['version']} engine={result['engine']} "
        f"docs={result['documents']} entities={result['entities']} "
        f"reveal {result['reveal_index']}" + (" OVER BUDGET" if result.get("over_budget") else "")
    )
    lines.append(
        f"overall  R={o['recall']:.3f} P={o['precision']:.3f} F2={o['f2']:.3f} "
        f"(95% CI {result['overall_f2_ci95'][0]:.3f}-{result['overall_f2_ci95'][1]:.3f}) "
        f"cov_R={o['coverage_recall']:.3f} exact={o['exact_recall']:.3f}"
    )
    fam = result["families"]
    if fam["structured_macro_f2"] is not None:
        lines.append(
            f"families structured_macro_F2={fam['structured_macro_f2']:.3f} "
            f"contextual_macro_F2={fam['contextual_macro_f2']:.3f}"
        )
    for t, m in result["by_type"].items():
        note = f"  (descriptive n<{DESCRIPTIVE_N})" if m["n"] < DESCRIPTIVE_N else ""
        lines.append(
            f"  {t:<14} n={m['n']:<4} R={m['recall']:.3f} P={m['precision']:.3f} "
            f"F2={m['f2']:.3f}{note}"
        )
    neg = result.get("negative")
    if neg:
        lines.append(
            f"negative  docs={neg['documents']} false_positives={neg['false_positives']} "
            f"clean_doc_rate={neg['clean_doc_rate']:.3f}"
        )
    lines.append("aggregate-only output; per-document diffs are never shown for the blind set")
    return "\n".join(lines)
