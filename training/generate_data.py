"""Synthetic training-data generator for the fine-tuned NER engine (Track A #5).

Emits JSONL records {"text": ..., "spans": [[start, end, LABEL], ...]} in the
model label space PERSON / LOCATION / ORGANIZATION / DATE / STUDENT_ID.
Structured identifiers (Thai ID, phones, cards, ...) are deliberately absent:
the regex/checksum FP layer owns them, and training the model on them would
add a second, hallucination-capable owner (adversarial-review decision).

Design rules, from the same review:
- NEVER sources gold or blind content. Values come from training/lexicons.json,
  whose build asserted disjointness from gold's annotated values and from the
  product's surrogate pools; `check_contamination()` re-asserts it here.
- Boundary semantics follow docs/annotation-guidelines.md (titles and cue
  labels OUTSIDE the span), NOT benchmark/corpus.py's title-inside values.
- The dev split is generator-disjoint: held-out value shard AND held-out
  template subset, so checkpoint selection never sees training recombinations.
- O-only documents in hallucination-prone registers (headers, agendas, form
  labels) are first-class citizens, and documents where the CURRENT detector
  hallucinates entities are upweighted (hard negatives).
- Counterfactual pairs: the same frame carrying a real name vs a header
  phrase, and a student id vs a reference number.

Run: PYTHONUTF8=1 python training/generate_data.py --seed 20260728 --out training/data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEXICONS = Path(__file__).with_name("lexicons.json")
_MARKUP = re.compile(r"\[\[([A-Z_]+)\|(.*?)\]\]")

TRAIN_DOCS_PER_FAMILY = 550
DEV_DOCS_PER_FAMILY = 60
REHEARSAL_TRAIN = 2000
REHEARSAL_DEV = 200
HARD_NEGATIVE_UPWEIGHT = 3
DEV_VALUE_SHARD = 10  # every 10th lexicon value is dev-only


def _load_lexicons() -> dict:
    return json.loads(LEXICONS.read_text(encoding="utf-8"))


def _shard(values: list[str], dev: bool) -> list[str]:
    return [v for i, v in enumerate(values) if (i % DEV_VALUE_SHARD == 0) == dev]


class Gen:
    def __init__(self, lex: dict, rng: random.Random, dev: bool):
        self.rng = rng
        self.dev = dev
        self.first = _shard(lex["first_names"], dev)
        self.last = _shard(lex["surnames"], dev)
        self.latin = _shard(lex["latin_names"], dev)
        self.orgs = _shard(lex["org_names"], dev)
        self.streets = _shard(lex["streets"], dev)
        self.subdistricts = _shard(lex["subdistricts"], dev)
        self.districts = _shard(lex["districts"], dev)
        self.provinces = lex["provinces"]  # 77 real provinces, shared
        self.buildings = _shard(lex["building_names"], dev)
        self.dates = _shard(lex["date_phrases"], dev)
        self.sid_formats = lex["student_id_formats"]
        self.sid_contexts = _shard(lex["student_contexts"], dev)
        self.headers = _shard(lex["header_phrases"], dev)
        self.form_labels = _shard(lex["form_labels"], dev)
        self.refs = lex["reference_numbers"]
        self.fillers = _shard(lex["prose_fillers"], dev)

    def pick(self, pool: list[str]) -> str:
        return self.rng.choice(pool)

    def person(self) -> str:
        return f"{self.pick(self.first)} {self.pick(self.last)}"

    def student_id(self) -> str:
        return "".join(
            str(self.rng.randint(0, 9)) if ch == "#" else ch for ch in self.pick(self.sid_formats)
        )

    def ref_number(self) -> str:
        return "".join(
            str(self.rng.randint(0, 9)) if ch == "#" else ch for ch in self.pick(self.refs)
        )

    def date(self) -> str:
        return self.pick(self.dates)


def _assemble(parts: list[tuple[str, str | None]]) -> dict:
    """parts = [(text, label-or-None), ...] -> record with char spans."""
    text = ""
    spans = []
    for frag, label in parts:
        if label:
            spans.append([len(text), len(text) + len(frag), label])
        text += frag
    return {"text": text, "spans": spans}


# ── document families (each is one template-space; dev uses its own subset) ──


def fam_form(g: Gen) -> dict:
    person, date, org = g.person(), g.date(), g.pick(g.orgs)
    sub, dist, prov = g.pick(g.subdistricts), g.pick(g.districts), g.pick(g.provinces)
    title = g.rng.choice(["นาย", "นาง", "นางสาว", ""])
    return _assemble(
        [
            (g.pick(g.headers) + "\n", None),
            (g.pick(g.form_labels) + " " + title, None),
            (person, "PERSON"),
            ("\nวันที่ ", None),
            (date, "DATE"),
            ("\nสังกัด ", None),
            (org, "ORGANIZATION"),
            (f"\nที่อยู่ เลขที่ {g.rng.randint(1, 299)} หมู่ {g.rng.randint(1, 12)} ตำบล", None),
            (sub, "LOCATION"),
            (" อำเภอ", None),
            (dist, "LOCATION"),
            (" จังหวัด", None),
            (prov, "LOCATION"),
            ("\n" + g.pick(g.fillers), None),
        ]
    )


def fam_prose(g: Gen) -> dict:
    p1, p2 = g.person(), g.person()
    return _assemble(
        [
            (g.pick(g.fillers) + " ", None),
            ("ผู้เกี่ยวข้องได้แก่ ", None),
            (p1, "PERSON"),
            (" และ ", None),
            (p2, "PERSON"),
            (" นัดหมายเมื่อ ", None),
            (g.date(), "DATE"),
            (" ณ ", None),
            (g.pick(g.orgs), "ORGANIZATION"),
            (" " + g.pick(g.fillers), None),
        ]
    )


def fam_roster(g: Gen) -> dict:
    parts: list[tuple[str, str | None]] = [("รายชื่อผู้เข้าร่วม\n", None)]
    for i in range(g.rng.randint(2, 5)):
        parts.append((f"{i + 1}. ", None))
        parts.append((g.person(), "PERSON"))
        parts.append((" รหัส ", None))
        parts.append((g.student_id(), "STUDENT_ID"))
        parts.append(("\n", None))
    return _assemble(parts)


def fam_chat(g: Gen) -> dict:
    return _assemble(
        [
            (g.rng.choice(["ฝากบอก", "เดี๋ยวส่งให้", "ประสานงานกับ", "เอกสารของ"]), None),
            (g.person(), "PERSON"),
            (g.rng.choice([" ด้วยนะ ", " ครับ ", " ค่ะ เรื่องนัด "]), None),
            (g.date(), "DATE"),
            (" " + g.pick(g.fillers), None),
        ]
    )


def fam_student_context(g: Gen) -> dict:
    tpl = g.pick(g.sid_contexts)
    sid = g.student_id()
    before, _, after = tpl.partition("{SID}")
    return _assemble([(before, None), (sid, "STUDENT_ID"), (after, None)])


def fam_o_only(g: Gen) -> dict:
    parts: list[tuple[str, str | None]] = []
    for _ in range(g.rng.randint(3, 6)):
        kind = g.rng.random()
        if kind < 0.4:
            parts.append((g.pick(g.headers) + "\n", None))
        elif kind < 0.6:
            parts.append((g.pick(g.form_labels) + " ........\n", None))
        elif kind < 0.8:
            parts.append((g.ref_number() + "\n", None))
        else:
            parts.append((g.pick(g.fillers) + "\n", None))
    return _assemble(parts)


def fam_counterfactual(g: Gen) -> list[dict]:
    """Same frame, entity vs non-entity filler — emitted as a pair."""
    frame_head = g.pick(g.form_labels) + " "
    tail = "\n" + g.pick(g.fillers)
    person = g.person()
    header = g.pick(g.headers)
    pair1 = _assemble([(frame_head, None), (person, "PERSON"), (tail, None)])
    pair2 = _assemble([(frame_head, None), (header, None), (tail, None)])
    sid_frame = g.rng.choice(["อ้างถึงรหัส ", "ตรวจสอบรหัส ", "แจ้งผลของ "])
    pair3 = _assemble([(sid_frame, None), (g.student_id(), "STUDENT_ID"), (tail, None)])
    pair4 = _assemble(
        [(sid_frame.replace("รหัส ", "เลขที่เอกสาร "), None), (g.ref_number(), None), (tail, None)]
    )
    return [pair1, pair2, pair3, pair4]


FAMILIES = {
    "form": fam_form,
    "prose": fam_prose,
    "roster": fam_roster,
    "chat": fam_chat,
    "student": fam_student_context,
    "o_only": fam_o_only,
}


def generate(seed: int, dev: bool, per_family: int) -> list[dict]:
    lex = _load_lexicons()
    rng = random.Random(seed + (1 if dev else 0))
    g = Gen(lex, rng, dev)
    docs: list[dict] = []
    for name, fn in FAMILIES.items():
        for _ in range(per_family):
            rec = fn(g)
            rec["family"] = name
            docs.append(rec)
    for _ in range(per_family // 2):
        for rec in fam_counterfactual(g):
            rec["family"] = "counterfactual"
            docs.append(rec)
    rng.shuffle(docs)
    return docs


def upweight_hard_negatives(docs: list[dict]) -> list[dict]:
    """Duplicate O-only docs the CURRENT detector hallucinates entities on."""
    from pii_redactor.detectors.tb_detector import detect_tb

    out = list(docs)
    for rec in docs:
        if rec["family"] not in ("o_only", "counterfactual") or rec["spans"]:
            continue
        if detect_tb(rec["text"]):
            out.extend([rec] * (HARD_NEGATIVE_UPWEIGHT - 1))
    return out


def load_rehearsal(n_train: int, n_dev: int, seed: int) -> tuple[list[dict], list[dict]]:
    """ThaiNER-2.0 rehearsal so the model does not forget LOC/ORG/DATE."""
    from datasets import load_dataset

    ds = load_dataset("pythainlp/thainer-corpus-v2", split="train")
    names = ds.features["ner"].feature.names
    keep = {"PERSON", "LOCATION", "ORGANIZATION", "DATE"}
    rng = random.Random(seed)
    idxs = list(range(len(ds)))
    rng.shuffle(idxs)
    out: list[dict] = []
    for i in idxs[: n_train + n_dev]:
        row = ds[i]
        text = ""
        spans = []
        cur_label, cur_start = None, 0
        for word, tag_id in zip(row["words"], row["ner"]):
            tag = names[tag_id]
            prefix, _, etype = tag.partition("-")
            etype = etype.upper() if etype else ""
            if prefix == "B" and etype in keep:
                if cur_label:
                    spans.append([cur_start, len(text), cur_label])
                cur_label, cur_start = etype, len(text)
            elif prefix == "I" and etype == cur_label:
                pass
            else:
                if cur_label:
                    spans.append([cur_start, len(text), cur_label])
                cur_label = None
            text += word
        if cur_label:
            spans.append([cur_start, len(text), cur_label])
        if text.strip():
            out.append({"text": text, "spans": spans, "family": "rehearsal"})
    return out[:n_train], out[n_train : n_train + n_dev]


def check_contamination(docs: list[dict]) -> None:
    gold_values = set()
    for line in (
        (ROOT / "benchmark" / "data" / "gold.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        if line.strip():
            for m in _MARKUP.finditer(json.loads(line)["annotated"]):
                gold_values.add(m.group(2))
    hits = 0
    for rec in docs:
        for s, e, _ in rec["spans"]:
            if rec["text"][s:e] in gold_values:
                hits += 1
    if hits:
        raise SystemExit(f"CONTAMINATION: {hits} training spans equal gold annotated values")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--out", default=str(Path(__file__).with_name("data")))
    ap.add_argument("--skip-rehearsal", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train = generate(args.seed, dev=False, per_family=TRAIN_DOCS_PER_FAMILY)
    dev = generate(args.seed, dev=True, per_family=DEV_DOCS_PER_FAMILY)
    train = upweight_hard_negatives(train)
    if not args.skip_rehearsal:
        r_train, r_dev = load_rehearsal(REHEARSAL_TRAIN, REHEARSAL_DEV, args.seed)
        train += r_train
        dev += r_dev
    check_contamination(train + dev)

    rng = random.Random(args.seed)
    rng.shuffle(train)
    manifest = {}
    for name, docs in (("train", train), ("dev", dev)):
        path = out / f"{name}.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for rec in docs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        manifest[name] = {
            "docs": len(docs),
            "entities": sum(len(d["spans"]) for d in docs),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest["seed"] = args.seed
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
