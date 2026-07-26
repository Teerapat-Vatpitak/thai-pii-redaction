"""LLM-as-detector: ask a chat model for PII, then locate what it returns.

The comparison this supports is "how much accuracy does sending the text to a
large hosted model actually buy", so the setup is deliberately generous to the
model: it is given the exact type vocabulary the gold set uses, told what each
type means, and asked only for the VALUES. Character offsets are computed here
by locating each returned value in the original text, because making a model
count UTF-8 offsets measures its arithmetic, not its extraction.

Values are claimed longest-first and never overlap -- the same rule
`reverse_mapper` and `leak_guard` use, so a short value that happens to sit
inside a longer one cannot double-count.
"""

from __future__ import annotations

import json
import re

# Exactly the gold set's vocabulary. Anything else the model invents is dropped
# before scoring, and the drop is counted so the run can report it.
GOLD_TYPES = (
    "NAME",
    "ADDRESS",
    "PHONE",
    "EMAIL",
    "THAI_ID",
    "BANK_ACCOUNT",
    "CREDIT_CARD",
    "PASSPORT",
    "VEHICLE_PLATE",
    "STUDENT_ID",
    "DATE_OF_BIRTH",
)

SYSTEM_PROMPT = """คุณคือระบบตรวจจับข้อมูลส่วนบุคคล (PII) ในข้อความภาษาไทย

หน้าที่ของคุณคือหาข้อมูลส่วนบุคคลทุกชิ้นในข้อความที่ได้รับ แล้วตอบกลับเป็น JSON array เท่านั้น

ชนิดข้อมูลที่ต้องหา ใช้ชื่อชนิดตามนี้เป๊ะ ห้ามคิดชื่อใหม่
- NAME ชื่อบุคคล รวมคำนำหน้าถ้ามี เช่น นาย นาง นางสาว ด.ช. ด.ญ.
- ADDRESS ที่อยู่ ตั้งแต่บ้านเลขที่หรือเลขที่ ไปจนจบรหัสไปรษณีย์ นับเป็นชิ้นเดียว
- PHONE เบอร์โทรศัพท์ ทั้งมือถือและบ้าน
- EMAIL อีเมล
- THAI_ID เลขประจำตัวประชาชน 13 หลัก มีหรือไม่มีขีดคั่นก็ได้
- BANK_ACCOUNT เลขที่บัญชีธนาคาร
- CREDIT_CARD เลขบัตรเครดิต 16 หลัก
- PASSPORT เลขหนังสือเดินทาง
- VEHICLE_PLATE ทะเบียนรถ
- STUDENT_ID รหัสนักศึกษา รหัสนักเรียน หรือรหัสประจำตัวผู้เรียน
- DATE_OF_BIRTH วันเดือนปีเกิดเท่านั้น วันที่อื่นเช่นวันประชุมหรือวันออกเอกสารไม่ต้องเอา

กฎการตอบ
1. ตอบเป็น JSON array อย่างเดียว ห้ามมีคำอธิบาย ห้ามมี markdown code fence
2. แต่ละสมาชิกคือ {"type": "<ชนิด>", "value": "<ข้อความที่ตัดมาจากต้นฉบับตรงตัวอักษรเป๊ะ>"}
3. value ต้องคัดลอกจากข้อความต้นฉบับตรงทุกตัวอักษร ห้ามแก้ไข ห้ามเว้นวรรคเพิ่ม ห้ามตัดต่อ
4. ถ้าข้อมูลชิ้นเดิมปรากฏหลายครั้ง ใส่ครั้งเดียวพอ
5. ถ้าไม่พบข้อมูลส่วนบุคคลเลย ตอบ []
6. เลขที่หนังสือราชการ เลขที่ใบเสร็จ รหัสสินค้า รหัสวิชา เลขมาตรากฎหมาย ราคา และ
   หมายเลขสายด่วนสาธารณะ ไม่ใช่ข้อมูลส่วนบุคคล ห้ามใส่"""

USER_TEMPLATE = "ข้อความที่ต้องตรวจ\n---\n{text}\n---\nตอบเป็น JSON array"

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
# Reasoning models on the ThaiLLM gateway put a <think> block in `content`
# itself, ahead of the answer. It has to go before the bracket search, or a
# stray bracket inside the reasoning is parsed as the answer.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


_OBJECT = re.compile(r"\{[^{}]*\}")


def _load_rows(text: str) -> list:
    """Pull the row objects out of whatever shape the model actually emitted.

    Asked for a JSON array, models answer with an array, a single bare object
    (OpenThaiGPT does this when there is exactly one hit), or a run of objects
    with no array around them. All three are the same answer, so all three parse
    -- otherwise the score would measure output formatting, not detection.
    """
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    lo, hi = text.find("["), text.rfind("]")
    if lo >= 0 and hi > lo:
        try:
            data = json.loads(text[lo : hi + 1])
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(data, list):
                return data

    rows = []
    for m in _OBJECT.finditer(text):
        try:
            row = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


UNTYPED = "PII"


def parse_items(raw: str, *, strict: bool = True) -> tuple[list[tuple[str, str]], list[str]]:
    """Return ([(type, value)], [type names outside the gold vocabulary]).

    Tolerant by design: a model that wraps its JSON in a fence or pads it with a
    sentence should not be scored as if it found nothing, since that would
    measure output formatting rather than detection.

    `strict=True` keeps only the gold vocabulary, which is the type-aware view.
    `strict=False` keeps every row and labels the whole lot `UNTYPED`, which is
    the type-agnostic view: it answers "did the model find this PII at all",
    separately from "did it call it by the right name". Pathumma needs the
    distinction badly -- it answers with the Thai field label as the type
    (`{"type": "ที่อยู่ปัจจุบัน"}`), inventing over 150 type names, so the
    strict view scores its instruction-following, not its detection.
    """
    text = _THINK.sub("", raw or "")
    # An unclosed <think> means the answer never arrived (the token budget ran
    # out mid-reasoning). Dropping the tail yields no detections, which is the
    # honest reading -- and the run reports it as an empty response.
    text = _UNCLOSED_THINK.sub("", text)
    text = _FENCE.sub("", text.strip())
    data = _load_rows(text)

    items: list[tuple[str, str]] = []
    rejected: list[str] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        etype = str(row.get("type", "")).strip().upper()
        value = row.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        if etype not in GOLD_TYPES:
            rejected.append(etype)
            if not strict:
                items.append((UNTYPED, value))
            continue
        items.append((UNTYPED if not strict else etype, value))
    return items, rejected


def locate(text: str, items: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    """Map returned values onto character spans, longest-first, non-overlapping."""
    claimed = [False] * len(text)
    spans: list[tuple[int, int, str]] = []
    # Longest first so "45/12 หมู่ 3 ..." claims its range before a bare "45/12"
    # inside it can, mirroring reverse_mapper's rule.
    for etype, value in sorted(items, key=lambda it: len(it[1]), reverse=True):
        start = 0
        while True:
            i = text.find(value, start)
            if i < 0:
                break
            j = i + len(value)
            if not any(claimed[i:j]):
                for k in range(i, j):
                    claimed[k] = True
                spans.append((i, j, etype))
            start = i + 1
    spans.sort()
    return spans


def parse_values(raw: str) -> list[tuple[str, str]]:
    """The (type, value) pairs a provider returned, with no response body kept.

    Every row with a usable string value is kept here, whatever its type --
    including ones outside the gold vocabulary. score_values needs both the
    gold-vocabulary view and the "did it find anything at all" view, and both
    have to come from this same list, so the vocabulary split happens there,
    not here.
    """
    text = _THINK.sub("", raw or "")
    text = _UNCLOSED_THINK.sub("", text)
    text = _FENCE.sub("", text.strip())
    data = _load_rows(text)

    values: list[tuple[str, str]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        etype = str(row.get("type", "")).strip().upper()
        value = row.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        values.append((etype, value))
    return values


def score_values(text: str, values: list[tuple[str, str]]) -> dict:
    """Everything score_raw does after parsing. Re-scorable from a cache entry
    holding only the parsed (type, value) pairs -- no network call, and no
    response body kept around to re-score from."""
    rejected = [etype for etype, _ in values if etype not in GOLD_TYPES]
    typed = [(etype, value) for etype, value in values if etype in GOLD_TYPES]
    untyped = [(UNTYPED, value) for _, value in values]
    typed_spans = locate(text, typed)
    untyped_spans = locate(text, untyped)
    return {
        "spans": typed_spans,
        "untyped_spans": untyped_spans,
        "meta": {
            "returned": len(untyped),
            "kept_typed": len(typed),
            "located": len(typed_spans),
            # A value the model invented or paraphrased cannot be found in the
            # source. Counting it separately keeps "the model hallucinated"
            # apart from "the model missed something".
            "unlocatable": len(untyped) - len(untyped_spans),
            "rejected_types": rejected,
            "empty_response": not values,
        },
    }


def score_raw(text: str, raw: str) -> dict:
    """Derive both views from one stored response. No network, so re-scoring a
    cached run after a parser or scorer change costs nothing."""
    return score_values(text, parse_values(raw))


def detect_with_llm(text: str, call) -> tuple[str, dict]:
    """Run one document through a caller. Returns (raw response, scored views)."""
    raw = call(SYSTEM_PROMPT, USER_TEMPLATE.format(text=text))
    return raw, score_raw(text, raw)
