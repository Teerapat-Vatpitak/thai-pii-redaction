"""Semantic detector for PDPA Section 26 sensitive data.

Flags free-form sensitive content (health, religion, etc.) that the keyword
scan in report.py misses — e.g. "ป่วยเป็นเบาหวาน" has no keyword like "โรค".
It compares each sentence's embedding against per-category prototype phrases
(MiniLM, multilingual) and flags those above a similarity threshold.

Non-generative: it only flags spans that exist in the input, so there is no
hallucination risk. Optional — requires sentence-transformers
(requirements-ml.txt). Callers degrade gracefully (empty list) when the model
or its dependency is unavailable, so the base product runs without it.
"""
from __future__ import annotations

_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Prototype phrases per PDPA Section 26 category (Thai). A handful each is
# enough for sentence-level semantic matching.
_PROTOTYPES: dict[str, list[str]] = {
    "HEALTH": [
        "ฉันป่วยเป็นโรคประจำตัว",
        "กำลังรักษาตัวอยู่ที่โรงพยาบาล",
        "ผลตรวจสุขภาพผิดปกติ",
        "เป็นเบาหวาน ความดัน หรือมะเร็ง",
    ],
    "RELIGION": [
        "ฉันนับถือศาสนา",
        "ไปทำบุญที่วัดเป็นประจำ",
        "ไปโบสถ์ทุกวันอาทิตย์",
        "ละหมาดวันละห้าเวลา",
    ],
    "RACE_ETHNICITY": [
        "ฉันเป็นคนเชื้อชาติอื่น",
        "ชาติพันธุ์ของฉัน",
        "เป็นชนกลุ่มน้อย",
    ],
    "POLITICAL_OPINION": [
        "ฉันสนับสนุนพรรคการเมืองนี้",
        "อุดมการณ์ทางการเมืองของฉัน",
        "ไปร่วมชุมนุมทางการเมือง",
    ],
    "SEXUAL_BEHAVIOR": [
        "รสนิยมทางเพศของฉัน",
        "ฉันเป็นเพศทางเลือก",
    ],
    "CRIMINAL_RECORD": [
        "ฉันเคยติดคุก",
        "มีประวัติอาชญากรรม",
        "เคยถูกดำเนินคดีอาญา",
    ],
    "DISABILITY": [
        "ฉันเป็นผู้พิการ",
        "มีความทุพพลภาพ",
        "พิการทางสายตา",
    ],
    "LABOR_UNION": [
        "ฉันเป็นสมาชิกสหภาพแรงงาน",
    ],
}

_model = None
_proto_emb: dict | None = None


def is_available() -> bool:
    """True if the embedding dependency is importable."""
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def _load():
    global _model, _proto_emb
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
        _proto_emb = {
            cat: _model.encode(
                phrases, convert_to_numpy=True, normalize_embeddings=True
            )
            for cat, phrases in _PROTOTYPES.items()
        }
    return _model, _proto_emb


def detect_sensitive(text: str, *, threshold: float = 0.55) -> list[dict]:
    """Flag sentences semantically close to a Section 26 category.

    Returns one entry per flagged sentence:
    ``{category, text, start, end, score}``. Returns an empty list when the
    text is empty or the embedding dependency is unavailable.
    """
    if not text or not text.strip() or not is_available():
        return []

    import numpy as np
    from pythainlp import sent_tokenize

    model, proto = _load()
    sentences = sent_tokenize(text, engine="crfcut")

    hits: list[dict] = []
    pos = 0
    for sent in sentences:
        idx = text.find(sent, pos)
        if idx == -1:
            idx = pos
        pos = idx + len(sent)
        if not sent.strip():
            continue

        emb = model.encode(sent, convert_to_numpy=True, normalize_embeddings=True)
        best_cat, best_score = None, 0.0
        for cat, pe in proto.items():
            score = float(np.max(pe @ emb))  # cosine on normalized vectors
            if score > best_score:
                best_cat, best_score = cat, score

        if best_cat is not None and best_score >= threshold:
            hits.append(
                {
                    "category": best_cat,
                    "text": sent,
                    "start": idx,
                    "end": idx + len(sent),
                    "score": round(best_score, 3),
                }
            )
    return hits
