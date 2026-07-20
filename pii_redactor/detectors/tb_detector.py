"""Text-based (TB) PII detector using PyThaiNLP NER (thainer CRF by default;
WangchanBERTa opt-in via AIGUARD_NER_ENGINE)."""

from __future__ import annotations

import logging
import os
import re
import uuid

from pythainlp import sent_tokenize
from pythainlp.tag import NER

from pii_redactor.models import Entity

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label mapping: actual thainer labels -> PDPA data_type (None = skip)
# ---------------------------------------------------------------------------

LABEL_MAP: dict[str, str | None] = {
    "PERSON": "NAME",
    "ORGANIZATION": "ORGANIZATION",  # quasi-identifier (employer/hospital)
    "LOCATION": "LOCATION",  # upgraded to ADDRESS by cue (below)
    "DATE": "DATE",  # upgraded to DATE_OF_BIRTH by cue (below)
    "TIME": None,
    "MONEY": None,
    "PERCENT": None,
    "FACILITY": None,
    "PRODUCT": None,
    # Aliases from brief (kept for safety)
    "ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
}

# Cue-based upgrades (same cue-window mechanism as fp_detector's
# _disambiguate_bank_phone; regexes copied rather than imported to avoid a
# circular import, same precedent as _deduplicate below).
# The ADDRESS check includes the span ITSELF because address cues (เขต/ตำบล/
# ซอย/ถนน) usually sit inside the address text; the DOB check looks only at
# the preceding context.
_ADDR_CUE_RE = re.compile(r"ที่อยู่|บ้านเลขที่|อาศัยอยู่|พักอยู่|เลขที่|ซอย|ถนน|ตำบล|แขวง|อำเภอ|เขต|จังหวัด")
_TB_BIRTH_CUE_RE = re.compile(r"เกิด")
_TB_CUE_WINDOW = 30

# thainer CRF has no reliable signal on out-of-distribution (non-Thai) input --
# fed a plain English sentence, it still forces some non-O label onto the
# whole span rather than abstaining. ORGANIZATION is the one honest label with
# no cue gate of its own (unlike LOCATION/DATE, which route through
# _apply_cue_upgrades), so an all-Latin "organization" span is always this
# degenerate guess rather than a real Thai employer/hospital name -- reject it.
_THAI_CHAR_RE = re.compile(r"[฀-๿]")


def _apply_cue_upgrades(text: str, start: int, end: int, data_type: str) -> str:
    if data_type == "LOCATION":
        ctx = text[max(0, start - _TB_CUE_WINDOW) : end]
        if _ADDR_CUE_RE.search(ctx):
            return "ADDRESS"
    elif data_type == "DATE":
        ctx = text[max(0, start - _TB_CUE_WINDOW) : start]
        if _TB_BIRTH_CUE_RE.search(ctx):
            return "DATE_OF_BIRTH"
    return data_type


class NEREngineUnavailableError(RuntimeError):
    """AIGUARD_NER_ENGINE is set to an engine whose dependency isn't installed."""


# Curated allow-list: only engines verified to emit the same (word, "B-"/"I-"/
# "O"-tag) shape that _bio_to_spans() below decodes. Do NOT add thai-nner or
# tltk here without first verifying their .tag() output shape -- they are
# known to differ (nested entities / different tuple layout).
_ENGINE_CONFIG: dict[str, dict[str, str | None]] = {
    "thainer": {"ner_engine": "thainer", "requires": None},
    "wangchanberta": {"ner_engine": "thainer-v2", "requires": "transformers"},
    # AI for Thai platform TNER. Opt-in only: the proposal claims detection
    # runs offline in-container, which stays true precisely because this is
    # never the default. Needs AIFORTHAI_API_KEY; absent credentials raise
    # rather than fall back, so nobody believes they have recall they do not.
    "tner": {"ner_engine": "tner", "requires": "env:AIFORTHAI_API_KEY"},
}

# Lazy NER cache, keyed by AIGUARD_NER_ENGINE value (first use per engine loads
# the model). A dict rather than a single slot so `union` can hold both engines.
_ner_cache: dict[str, NER] = {}


def _load_ner(name: str) -> NER:
    """Return the NER engine for a single engine name (thainer / wangchanberta),
    loading and caching it on first use. Raises ValueError for an unknown name
    and NEREngineUnavailableError if the engine's dependency is missing."""
    if name not in _ENGINE_CONFIG:
        raise ValueError(
            f"Unknown AIGUARD_NER_ENGINE={name!r}; supported: {sorted(_ENGINE_CONFIG)} (or 'union')"
        )
    if name not in _ner_cache:
        config = _ENGINE_CONFIG[name]
        requires = config["requires"]
        if requires is not None:
            if requires.startswith("env:"):
                env_var = requires[len("env:") :]
                if not env_var:
                    raise NEREngineUnavailableError(
                        f"AIGUARD_NER_ENGINE={name!r} has a malformed requirement "
                        f"{requires!r} (env: prefix with no variable name)"
                    )
                if not os.environ.get(env_var):
                    raise NEREngineUnavailableError(
                        f"AIGUARD_NER_ENGINE={name!r} requires the {env_var} "
                        f"environment variable to be set."
                    )
            else:
                try:
                    __import__(requires)
                except ImportError:
                    raise NEREngineUnavailableError(
                        f"AIGUARD_NER_ENGINE={name!r} requires {requires!r}. "
                        f"Run: pip install -r requirements-ml.txt"
                    ) from None
        _ner_cache[name] = NER(engine=config["ner_engine"])
    return _ner_cache[name]


def _resolve_engine_name() -> str:
    """The engine named by AIGUARD_NER_ENGINE, defaulting to the offline CRF.

    The default is load-bearing: the AI for Thai proposal claims detection runs
    offline in-container, which is only true while every network-backed engine
    stays opt-in.
    """
    return os.environ.get("AIGUARD_NER_ENGINE", "thainer")


def _get_ner() -> NER:
    """Select the single engine named by AIGUARD_NER_ENGINE (default thainer)."""
    return _load_ner(_resolve_engine_name())


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
                spans.append(
                    (ent_text, current_start, current_start + len(ent_text), current_label)
                )
            current_label = tag[2:]
            current_start = idx
            current_chars = [word]
        elif tag.startswith("I-") and current_label == tag[2:]:
            current_chars.append(word)
        else:
            # O tag or label mismatch — close current entity
            if current_label and current_chars:
                ent_text = "".join(current_chars)
                spans.append(
                    (ent_text, current_start, current_start + len(ent_text), current_label)
                )
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
        overlaps = any(not (ent.span[1] <= k.span[0] or ent.span[0] >= k.span[1]) for k in kept)
        if not overlaps:
            kept.append(ent)
    return sorted(kept, key=lambda e: e.span[0])


# ---------------------------------------------------------------------------
# Stride-chunk NER (single engine)
# ---------------------------------------------------------------------------

_CHUNK_CORE_CHARS = 500


def _ner_candidates(
    text: str, ner: NER, sentence_offsets: list[tuple[str, int]], margin_sentences: int
) -> list[Entity]:
    """Run one NER engine over stride chunks and return TB Entity candidates
    mapped to original-text offsets (pre-dedup).

    Chunks are runs of consecutive sentences whose combined length is capped
    at ~_CHUNK_CORE_CHARS (always at least one sentence), padded with
    `margin_sentences` sentences of context on each side. The tagged string is
    ALWAYS a slice of the original text (a join of sentence strings would drop
    the gaps between sentences and corrupt every offset after the first gap).
    Only spans that START inside the chunk core are kept, so margins never
    duplicate entities across neighbouring chunks. Each sentence is tagged
    ~1+2*margin/chunk_len times instead of the old sliding window's ~7x.
    """
    n = len(sentence_offsets)
    candidates: list[Entity] = []

    def _sent_start(i: int) -> int:
        return sentence_offsets[i][1]

    def _sent_end(i: int) -> int:
        s, off = sentence_offsets[i]
        return off + len(s)

    chunk_first = 0
    while chunk_first < n:
        # grow the core until the char cap (always >= 1 sentence)
        chunk_last = chunk_first
        while (
            chunk_last + 1 < n
            and _sent_end(chunk_last + 1) - _sent_start(chunk_first) <= _CHUNK_CORE_CHARS
        ):
            chunk_last += 1

        core_begin = _sent_start(chunk_first)
        core_end = _sent_end(chunk_last)
        ctx_begin = _sent_start(max(0, chunk_first - margin_sentences))
        ctx_end = _sent_end(min(n - 1, chunk_last + margin_sentences))
        context_text = text[ctx_begin:ctx_end]

        try:
            tagged: list[tuple[str, str]] = ner.tag(context_text)
        except Exception:
            # Dropping a whole chunk is recall-negative (violates recall >
            # precision). Never silence it — a repeatedly failing engine must
            # be visible, not quietly eat ~500 chars of PII.
            _LOG.warning(
                "NER tagging failed on chunk chars %d-%d (%d chars); skipping "
                "— PII in this chunk may be missed",
                core_begin,
                core_end,
                len(context_text),
                exc_info=True,
            )
            chunk_first = chunk_last + 1
            continue

        if tagged:
            for ent_text, ctx_start, ctx_end_pos, label in _bio_to_spans(tagged, context_text):
                orig_start = ctx_begin + ctx_start
                orig_end = ctx_begin + ctx_end_pos
                if not (core_begin <= orig_start < core_end):
                    continue
                data_type = LABEL_MAP.get(label)
                if data_type is None:
                    continue
                if (orig_end - orig_start) < 2:
                    continue
                entity_text = text[orig_start:orig_end]
                if data_type == "ORGANIZATION" and not _THAI_CHAR_RE.search(entity_text):
                    continue
                data_type = _apply_cue_upgrades(text, orig_start, orig_end, data_type)
                candidates.append(
                    Entity(
                        entity_id=str(uuid.uuid4()),
                        redact_type="TB",
                        data_type=data_type,
                        span=(orig_start, orig_end),
                        score=0.85,
                        original_text=text[orig_start:orig_end],
                    )
                )

        chunk_first = chunk_last + 1

    return candidates


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------


def detect_tb(text: str, *, window_size: int = 1) -> list[Entity]:
    """
    Detect text-based PII entities using PyThaiNLP NER (thainer CRF).

    Args:
        text: cleaned text to scan
        window_size: sentences of margin context on each side of a chunk
            (default 1; raise to 2 if benchmark recall regresses)

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
    name = _resolve_engine_name()
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
