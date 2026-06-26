"""Text-based (TB) PII detector using PyThaiNLP NER (thainer CRF)."""
from __future__ import annotations

import uuid

from pythainlp import sent_tokenize
from pythainlp.tag import NER

from pii_redactor.models import Entity

# ---------------------------------------------------------------------------
# Label mapping: actual thainer labels -> PDPA data_type (None = skip)
# ---------------------------------------------------------------------------

LABEL_MAP: dict[str, str | None] = {
    "PERSON": "NAME",
    "ORGANIZATION": None,   # Not PII; skip
    "LOCATION": "ADDRESS",
    "DATE": "DATE_OF_BIRTH",
    "TIME": None,
    "MONEY": None,
    "PERCENT": None,
    "FACILITY": None,
    "PRODUCT": None,
    # Aliases from brief (kept for safety)
    "ORG": None,
    "GPE": "ADDRESS",
    "LOC": "ADDRESS",
}

# Lazy-initialized NER instance (first import triggers model load)
_ner: NER | None = None


def _get_ner() -> NER:
    global _ner
    if _ner is None:
        _ner = NER(engine="thainer")
    return _ner


# ---------------------------------------------------------------------------
# BIO tag decoding
# ---------------------------------------------------------------------------

def _bio_to_spans(tokens: list[tuple[str, str]], text: str) -> list[tuple[str, int, int, str]]:
    """
    Convert BIO-tagged token list to entity spans with character offsets.

    Returns list of (entity_text, start, end, label).
    """
    spans: list[tuple[str, int, int, str]] = []
    current_label: str | None = None
    current_start: int | None = None
    current_chars: list[str] = []
    pos = 0

    for word, tag in tokens:
        idx = text.find(word, pos)
        if idx == -1:
            continue

        if tag.startswith("B-"):
            # Save previous entity
            if current_label and current_chars:
                ent_text = "".join(current_chars)
                spans.append((ent_text, current_start, current_start + len(ent_text), current_label))
            current_label = tag[2:]
            current_start = idx
            current_chars = [word]
        elif tag.startswith("I-") and current_label == tag[2:]:
            current_chars.append(word)
        else:
            # O tag or label mismatch — close current entity
            if current_label and current_chars:
                ent_text = "".join(current_chars)
                spans.append((ent_text, current_start, current_start + len(ent_text), current_label))
            current_label = None
            current_start = None
            current_chars = []

        pos = idx + len(word)

    # Flush last entity
    if current_label and current_chars:
        ent_text = "".join(current_chars)
        spans.append((ent_text, current_start, current_start + len(ent_text), current_label))

    return spans


# ---------------------------------------------------------------------------
# Deduplication (copied from fp_detector to avoid circular import)
# ---------------------------------------------------------------------------

def _deduplicate(entities: list[Entity]) -> list[Entity]:
    """Remove overlapping spans; prefer higher score, then first occurrence."""
    sorted_ents = sorted(entities, key=lambda e: (e.span[0], -e.score))
    kept: list[Entity] = []
    for ent in sorted_ents:
        if (ent.span[1] - ent.span[0]) < 2:
            continue
        overlaps = any(
            not (ent.span[1] <= k.span[0] or ent.span[0] >= k.span[1])
            for k in kept
        )
        if not overlaps:
            kept.append(ent)
    return sorted(kept, key=lambda e: e.span[0])


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

def detect_tb(text: str, *, window_size: int = 3) -> list[Entity]:
    """
    Detect text-based PII entities using PyThaiNLP NER (thainer CRF).

    Args:
        text: cleaned text to scan
        window_size: number of sentences before/after context (default +-3)

    Returns list of Entity objects (redact_type="TB").
    Sorted by span start (ascending).
    No overlapping spans.
    Span chokepoint: reject span < 2 chars.
    """
    if not text or not text.strip():
        return []

    ner = _get_ner()

    # Step 1: Sentence tokenization with cumulative offsets
    raw_sentences = sent_tokenize(text, engine="crfcut")
    if not raw_sentences:
        return []

    # Build (sentence_text, start_offset) pairs by walking through text
    sentence_offsets: list[tuple[str, int]] = []
    pos = 0
    for sent in raw_sentences:
        idx = text.find(sent, pos)
        if idx == -1:
            idx = pos
        sentence_offsets.append((sent, idx))
        pos = idx + len(sent)

    candidates: list[Entity] = []

    # Step 3: Sliding window NER
    for i, (sent_text, sent_offset) in enumerate(sentence_offsets):
        window_start = max(0, i - window_size)
        window_end = min(len(sentence_offsets), i + window_size + 1)
        context_sents = sentence_offsets[window_start:window_end]

        # Build context string and track offset of current sentence within context
        context_text = "".join(s for s, _ in context_sents)
        context_sent_start = sum(len(s) for s, _ in context_sents[: i - window_start])
        context_sent_end = context_sent_start + len(sent_text)

        # Step 4: Run NER on context window (tag=None returns BIO tuple list)
        try:
            tagged: list[tuple[str, str]] = ner.tag(context_text)
        except Exception:
            continue

        if not tagged:
            continue

        # Step 5: Decode BIO tags to spans within context
        raw_spans = _bio_to_spans(tagged, context_text)

        for ent_text, ctx_start, ctx_end, label in raw_spans:
            # Only keep entities whose span falls within current sentence bounds
            if ctx_start < context_sent_start or ctx_end > context_sent_end:
                continue

            data_type = LABEL_MAP.get(label)
            if data_type is None:
                continue

            # Map context offsets to original text offsets
            orig_start = sent_offset + (ctx_start - context_sent_start)
            orig_end = sent_offset + (ctx_end - context_sent_start)

            # Step 6: Span chokepoint — reject spans < 2 chars
            if (orig_end - orig_start) < 2:
                continue

            candidates.append(Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="TB",
                data_type=data_type,
                span=(orig_start, orig_end),
                score=0.85,
                original_text=text[orig_start:orig_end],
            ))

    # Step 7: Deduplication
    return _deduplicate(candidates)
