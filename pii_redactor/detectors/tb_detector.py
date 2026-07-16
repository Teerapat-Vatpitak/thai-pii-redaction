"""Text-based (TB) PII detector using PyThaiNLP NER (thainer CRF by default;
WangchanBERTa opt-in via AIGUARD_NER_ENGINE)."""
from __future__ import annotations

import os
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


class NEREngineUnavailableError(RuntimeError):
    """AIGUARD_NER_ENGINE is set to an engine whose dependency isn't installed."""


# Curated allow-list: only engines verified to emit the same (word, "B-"/"I-"/
# "O"-tag) shape that _bio_to_spans() below decodes. Do NOT add thai-nner or
# tltk here without first verifying their .tag() output shape -- they are
# known to differ (nested entities / different tuple layout).
_ENGINE_CONFIG: dict[str, dict[str, str | None]] = {
    "thainer": {"ner_engine": "thainer", "requires": None},
    "wangchanberta": {"ner_engine": "thainer-v2", "requires": "transformers"},
}

# Lazy NER cache, keyed by AIGUARD_NER_ENGINE value (first use per engine loads
# the model). A dict rather than a single slot so `union` can hold both engines.
_ner_cache: dict[str, "NER"] = {}


def _load_ner(name: str) -> NER:
    """Return the NER engine for a single engine name (thainer / wangchanberta),
    loading and caching it on first use. Raises ValueError for an unknown name
    and NEREngineUnavailableError if the engine's dependency is missing."""
    if name not in _ENGINE_CONFIG:
        raise ValueError(
            f"Unknown AIGUARD_NER_ENGINE={name!r}; "
            f"supported: {sorted(_ENGINE_CONFIG)} (or 'union')"
        )
    if name not in _ner_cache:
        config = _ENGINE_CONFIG[name]
        requires = config["requires"]
        if requires is not None:
            try:
                __import__(requires)
            except ImportError:
                raise NEREngineUnavailableError(
                    f"AIGUARD_NER_ENGINE={name!r} requires {requires!r}. "
                    f"Run: pip install -r requirements-ml.txt"
                ) from None
        _ner_cache[name] = NER(engine=config["ner_engine"])
    return _ner_cache[name]


def _get_ner() -> NER:
    """Select the single engine named by AIGUARD_NER_ENGINE (default thainer)."""
    name = os.environ.get("AIGUARD_NER_ENGINE", "thainer")
    return _load_ner(name)


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
# Sliding-window NER (single engine)
# ---------------------------------------------------------------------------

def _ner_candidates(
    text: str, ner: NER, sentence_offsets: list[tuple[str, int]], window_size: int
) -> list[Entity]:
    """Run one NER engine over the sliding-sentence windows and return TB
    Entity candidates mapped to original-text offsets (pre-dedup)."""
    candidates: list[Entity] = []
    for i, (sent_text, sent_offset) in enumerate(sentence_offsets):
        window_start = max(0, i - window_size)
        window_end = min(len(sentence_offsets), i + window_size + 1)
        context_sents = sentence_offsets[window_start:window_end]

        context_text = "".join(s for s, _ in context_sents)
        context_sent_start = sum(len(s) for s, _ in context_sents[: i - window_start])
        context_sent_end = context_sent_start + len(sent_text)

        try:
            tagged: list[tuple[str, str]] = ner.tag(context_text)
        except Exception:
            continue
        if not tagged:
            continue

        raw_spans = _bio_to_spans(tagged, context_text)
        for ent_text, ctx_start, ctx_end, label in raw_spans:
            if ctx_start < context_sent_start or ctx_end > context_sent_end:
                continue
            data_type = LABEL_MAP.get(label)
            if data_type is None:
                continue
            orig_start = sent_offset + (ctx_start - context_sent_start)
            orig_end = sent_offset + (ctx_end - context_sent_start)
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
    return candidates


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

    # Step 1: Sentence tokenization with cumulative offsets
    raw_sentences = sent_tokenize(text, engine="crfcut")
    if not raw_sentences:
        return []

    sentence_offsets: list[tuple[str, int]] = []
    pos = 0
    for sent in raw_sentences:
        idx = text.find(sent, pos)
        if idx == -1:
            idx = pos
        sentence_offsets.append((sent, idx))
        pos = idx + len(sent)

    # Engine selection: union runs both, everything else is a single engine.
    name = os.environ.get("AIGUARD_NER_ENGINE", "thainer")
    if name == "union":
        ners = [_load_ner("thainer"), _load_ner("wangchanberta")]
    else:
        ners = [_get_ner()]

    candidates: list[Entity] = []
    for ner in ners:
        candidates.extend(_ner_candidates(text, ner, sentence_offsets, window_size))

    # Recall booster: title/label-cued names the NER missed or clipped
    # (engine-independent, added once).
    from pii_redactor.detectors.name_context import detect_name_context
    candidates.extend(detect_name_context(text))

    # Deduplication
    return _deduplicate(candidates)
