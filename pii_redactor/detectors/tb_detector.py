"""Text-based (TB) PII detector using PyThaiNLP NER (thainer CRF by default;
WangchanBERTa opt-in via AIGUARD_NER_ENGINE)."""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass

from pythainlp import sent_tokenize
from pythainlp.tag import NER

from pii_redactor.models import Entity

_LOG = logging.getLogger(__name__)


@dataclass
class NERChunkDiagnostics:
    attempted: int = 0
    succeeded: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
        }


# ---------------------------------------------------------------------------
# Label mapping: actual thainer labels -> PDPA data_type (None = skip)
# ---------------------------------------------------------------------------

LABEL_MAP: dict[str, str | None] = {
    "PERSON": "NAME",
    # AI for Thai TNER uses these compact labels on the live API.
    "PER": "NAME",
    "ORGANIZATION": "ORGANIZATION",  # quasi-identifier (employer/hospital)
    "LOCATION": "LOCATION",  # upgraded to ADDRESS by cue (below)
    "DATE": "DATE",  # upgraded to DATE_OF_BIRTH by cue (below)
    "DTM": "DATE",
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
# `เลขที่` is a real address cue on its own ("เลขที่ 26 ซอย...") but it also
# opens compounds meaning "the number of <a thing>" -- เลขที่บัญชี, เลขที่สัญญา,
# เลขที่ใบกำกับภาษี -- which are not addresses. Without the lookahead the
# account-number LABEL was upgraded to ADDRESS and replaced with a fake street
# address; that surrogate landed beside other surrogates, the NER drew one wide
# ADDRESS span across them, and the pre-send guard halted a clean prompt
# (intermittent PreSendValidationError, salt-dependent). Alternation order
# still matters: บ้านเลขที่ must be tried before เลขที่.
_ADDR_CUE_RE = re.compile(
    r"ที่อยู่|บ้านเลขที่|อาศัยอยู่|พักอยู่"
    r"|เลขที่(?!บัญชี|ใบ|สัญญา|เอกสาร|คำสั่ง|กรมธรรม์|พัสดุ|คดี|หนังสือ)"
    r"|ซอย|ถนน|ตำบล|แขวง|อำเภอ|เขต|จังหวัด"
)
_TB_BIRTH_CUE_RE = re.compile(r"เกิด")
_TB_CUE_WINDOW = 30

# thainer CRF has no reliable signal on out-of-distribution (non-Thai) input --
# fed a plain English sentence, it still forces some non-O label onto the
# whole span rather than abstaining. ORGANIZATION is the one honest label with
# no cue gate of its own (unlike LOCATION/DATE, which route through
# _apply_cue_upgrades), so an all-Latin "organization" span is always this
# degenerate guess rather than a real Thai employer/hospital name -- reject it.
_THAI_CHAR_RE = re.compile(r"[฀-๿]")
_ISOLATED_NAME_LINE_RE = re.compile(r"[ก-ฮเ-ไ][ก-ฮะ-์]*(?:[ \t]+[ก-ฮเ-ไ][ก-ฮะ-์]*){1,3}")
# A line holding ONE Thai run is admitted to the retry too, but only through
# `name_context.is_glued_name_run` -- OCR deletes the space inside a name
# ("สมชาย ใจดี" -> "สมชายใจดี") and the shape gate above then rejected the whole
# line. Relaxing the regex to {0,3} instead would admit every single-word Thai
# line in the document, spending the _ISOLATED_NAME_MAX_LINES budget on form
# headers before the retry ever reaches a real name.
_ISOLATED_GLUED_LINE_RE = re.compile(r"[ก-ฮเ-ไ][ก-ฮะ-์]*")
# One or more Thai-letter "words" separated by single spaces/tabs and nothing
# else -- a bare digit run is already excluded (digits aren't in ก-ฮ/ะ-์), and
# so is a segment with a glued non-name prefix like an OCR-corrupted "และ..."
# co-applicant marker ("แถะ...มาลิรักดิ"): the parallel-record bootstrap
# (name_context.detect_parallel_record_names) already owns that shape and
# extracts the bare name from it; a hygiene segment that also grabbed the
# punctuation-glued prefix would out-compete the correct extraction in dedupe.
_NAME_SEGMENT_SHAPE_RE = re.compile(r"^[ก-ฮเ-ไ][ก-ฮะ-์]*(?:[ \t]+[ก-ฮเ-ไ][ก-ฮะ-์]*)*$")
_ISOLATED_NAME_PREFIX_RE = re.compile(r"(?:ชื่อ(?:-นามสกุล)?|ผู้[ก-๛]{1,30})[ \t:：]+")
_ISOLATED_NAME_MAX_CHARS = 80
_ISOLATED_NAME_MAX_LINES = 8
# Document/form compounds the CRF hallucinates as PERSON in header-heavy
# registers. Anchored at span start; each entry is a compound so that real
# given names sharing a prefix (เลขา, ใบเฟิร์น, ประกาศิต, นิคม) survive.
_NAME_CUE_AFTER_BREAK_RE = re.compile(r"(?:[ก-๛]{0,12}ชื่อ|นาย|นางสาว|นาง|ด\.ช\.|ด\.ญ\.)")
_NAME_DOC_COMPOUND_RE = re.compile(
    r"ตารางสอบ|ตารางเรียน|ตารางนัด|รายงานการ|สถานีตำรวจ|ประวัติการ|นิคมอุตสาหกรรม"
    r"|เลขครุภัณฑ์|เลขที่|เลขเอกสาร|ใบสมัคร|ใบคำร้อง|ใบเสร็จ|ใบกำกับ|ใบแจ้ง"
    r"|บันทึกข้อความ|ประกาศรายชื่อ|ประกาศผล|กำหนดการ|ระเบียบวาระ"
    # Form field labels seen gluing to real names in label-first OCR order
    # (M6-P0 mechanism 2, ภ.ง.ด.91 spouse-name exposure): "เดือนปีเกิด" is
    # "month/year of birth", not a person. The regex is used with .match()
    # (anchored at segment start), so the commoner full form spelling
    # "วันเดือนปีเกิด" needs its own alternative -- without it that spelling
    # leaked as a NAME (a measured gold false positive, doc116) even though
    # `name_context.is_glued_name_run` already rejected it via its token stop
    # set. Longer alternative first.
    r"|วันเดือนปีเกิด|เดือนปีเกิด"
)
# Punctuation an OCR line break leaves hanging on a name ("สมชาย ใจดี,"). On a
# tail segment it is TRIMMED, not treated as a reason to drop the segment --
# the strict shape gate below would otherwise discard the name because of a
# comma. Deliberately narrow: only characters that end a clause.
_NAME_SEGMENT_TRIM_CHARS = ",.;:!?)]}\"'"


# A CRF "location" that is really หนังสือราชการ numbering, in two shapes seen
# on the gold negative slice: the span IS a เลขที่<document> field label
# (เลขที่คำสั่ง / เลขที่ใบเสนอราคา ... — same compound list the ADDRESS cue
# already refuses to upgrade on), or the span carries digits with no Thai
# letter RUN and a Buddhist-year component ("จ.44/2569" — a contract number
# whose only Thai is the abbreviation letter). The year requirement is what
# separates it from a bare house number ("214/9"), which the adversarial
# review showed the finetuned engine emits as its own LOCATION span — no
# Thai, digits and a slash, and absolutely PII. A real place with a digit
# ("เชียงใหม่ 50200", "อาคาร 7") keeps its Thai run and survives either way.
_DOC_NUMBER_LABEL_RE = re.compile(r"เลขที่(?:บัญชี|ใบ|สัญญา|เอกสาร|คำสั่ง|กรมธรรม์|พัสดุ|คดี|หนังสือ)")
_THAI_RUN_RE = re.compile(r"[ก-๛]{2,}")
_BUDDHIST_YEAR_RE = re.compile(r"(?<!\d)2[456]\d{2}(?!\d)")
# A "date" right after the Thai industrial-standard designation is the
# standard's number ("มอก. 2540-2555"), not a calendar date. The left
# boundary keeps common words ending in the same letters (ทะเลหมอก) from
# swallowing a real date after them.
_STANDARD_CUE_RE = re.compile(r"(?<![ก-๛])มอก\.?\s*$")
_STANDARD_CUE_LOOKBACK = 10
# No calendar date component has five digits in a row — a run that long
# inside a "date" means the CRF swallowed a serial/reference number into the
# span ("ที่ 27 ISSN 08571724 เผยแพร่เดือนกันยายน 2568", surfaced on the gold
# negative slice once the FP ID_NUMBER stopped out-competing it in dedupe).
_DATE_SERIAL_RE = re.compile(r"\d{5,}")


def _apply_cue_upgrades(text: str, start: int, end: int, data_type: str) -> str | None:
    """Cue-driven label upgrade, or ``None`` when the span is no PII at all."""
    if data_type == "LOCATION":
        entity_text = text[start:end]
        if _DOC_NUMBER_LABEL_RE.match(entity_text):
            return None
        if _BUDDHIST_YEAR_RE.search(entity_text) and not _THAI_RUN_RE.search(entity_text):
            return None
        ctx = text[max(0, start - _TB_CUE_WINDOW) : end]
        if _ADDR_CUE_RE.search(ctx):
            return "ADDRESS"
    elif data_type == "DATE":
        if _STANDARD_CUE_RE.search(text[max(0, start - _STANDARD_CUE_LOOKBACK) : start]):
            return None
        if _DATE_SERIAL_RE.search(text[start:end]):
            return None
        ctx = text[max(0, start - _TB_CUE_WINDOW) : start]
        if _TB_BIRTH_CUE_RE.search(ctx):
            return "DATE_OF_BIRTH"
    return data_type


def _name_hygiene(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Shared NAME span hygiene for every neural engine (CRF and fine-tuned).

    A person's name never spans a line break. On label-first OCR field order
    the CRF can glue a form label to the real name(s) that follow it into one
    span (e.g. "เดือนปีเกิด\n\nกิตติ พรดี\nพิมพ์ใจ แสนดี" -- a
    month/year-of-birth label followed by two real names): unconditionally
    keeping the pre-newline head would mint the label itself as a
    false-positive NAME while discarding both real names. So the span is split
    at newlines into segments -- but the HEAD and the TAIL segments are judged
    by deliberately different rules, because the evidence for them differs:

    - HEAD (the pre-newline part, what the CRF actually started on) keeps the
      original lenient rule: >= 2 characters after rstrip and not a document
      compound. Requiring a strict name shape here drops the real name for a
      trailing comma, a parenthesised role, an age, or Latin script
      ("สมชาย ใจดี," / "สมชาย ใจดี (ผู้ยื่น)" / "John Smith" all became NOTHING)
      -- the sample-PDF regression class, measured on the branch review.
    - TAIL segments carry no such evidence: they are whatever the CRF ran on
      into. They must look like a name (`_NAME_SEGMENT_SHAPE_RE`, after
      trailing clause punctuation is TRIMMED rather than counted against them)
      AND survive the shared non-person rejection
      (`name_context.is_non_person_segment` plus the document-compound regex),
      which is what keeps Thai form labels (ที่อยู่, เลขประจำตัวประชาชน,
      บัญชีรับเงินกู้, ตำแหน่ง) and letter closings (ขอแสดงความนับถือ) from
      becoming NAME entities of their own.

    The one exception: if the line right after the first break opens with a
    name cue (นาย/นาง/ชื่อ/...), the cue pass owns the person outright, and
    even the head would be junk glued to it -- so the WHOLE span is dropped
    instead of segmented.
    """
    from pii_redactor.detectors.name_context import is_non_person_segment

    entity_text = text[start:end]
    if "\n" not in entity_text:
        if _NAME_DOC_COMPOUND_RE.match(entity_text):
            return []
        return [(start, end)]

    _head, tail = entity_text.split("\n", 1)
    if _NAME_CUE_AFTER_BREAK_RE.match(tail.lstrip()):
        return []

    spans: list[tuple[int, int]] = []
    offset = 0
    for index, line in enumerate(entity_text.split("\n")):
        line_start = start + offset
        offset += len(line) + 1
        if index == 0:
            seg = line.rstrip()
            if len(seg) < 2 or _NAME_DOC_COMPOUND_RE.match(seg):
                continue
            spans.append((line_start, line_start + len(seg)))
            continue
        lstripped = line.lstrip()
        pad = len(line) - len(lstripped)
        seg = lstripped.rstrip().rstrip(_NAME_SEGMENT_TRIM_CHARS).rstrip()
        if len(seg) < 2:
            continue
        if _NAME_DOC_COMPOUND_RE.match(seg):
            continue
        if not _NAME_SEGMENT_SHAPE_RE.match(seg):
            continue
        if is_non_person_segment(seg):
            continue
        seg_start = line_start + pad
        spans.append((seg_start, seg_start + len(seg)))
    return spans


_FINETUNED_LABEL_MAP = {
    "PERSON": "NAME",
    "LOCATION": "LOCATION",
    "ORGANIZATION": "ORGANIZATION",
    "DATE": "DATE",
    "STUDENT_ID": "STUDENT_ID",
}
_finetuned_cache: dict[str, object] = {}


def _detect_tb_finetuned(text: str) -> list[Entity]:
    """TB detection under the fine-tuned engine (AIGUARD_NER_ENGINE=finetuned).

    Two deliberate differences from the CRF path, both from the reveal-3
    evidence that the extended cue passes cost precision in registers gold
    does not cover:

    - model spans arrive as character offsets from the adapter (no word/BIO
      reconstruction), with the same hygiene/cue-upgrade layers applied; and
    - the extended name-cue passes are kept only when they OVERLAP a model
      PERSON span (model-as-verifier). The strong passes (titles, explicit
      name labels) stay unconditional — the pre-registered high-precision
      fallback.
    """
    from pii_redactor.detectors.finetuned_engine import FinetunedEngine
    from pii_redactor.detectors.name_context import detect_name_context_passes

    if "engine" not in _finetuned_cache:
        _finetuned_cache["engine"] = FinetunedEngine()
    engine = _finetuned_cache["engine"]

    thresholds = getattr(engine, "thresholds", {}) or {}
    candidates: list[Entity] = []
    model_name_spans: list[tuple[int, int]] = []
    for start, end, label, conf in engine.spans(text):
        data_type = _FINETUNED_LABEL_MAP.get(label)
        if data_type is None or end - start < 2:
            continue
        if conf < thresholds.get(label, 0.0):
            continue
        entity_text = text[start:end]
        if data_type == "ORGANIZATION" and not _THAI_CHAR_RE.search(entity_text):
            continue
        if data_type == "NAME":
            segments = _name_hygiene(text, start, end)
            for seg_start, seg_end in segments:
                model_name_spans.append((seg_start, seg_end))
                seg_data_type = _apply_cue_upgrades(text, seg_start, seg_end, data_type)
                if seg_data_type is None:
                    continue
                candidates.append(
                    Entity(
                        entity_id=str(uuid.uuid4()),
                        redact_type="TB",
                        data_type=seg_data_type,
                        span=(seg_start, seg_end),
                        score=round(min(0.99, max(0.5, conf)), 3),
                        original_text=text[seg_start:seg_end],
                    )
                )
            continue
        data_type = _apply_cue_upgrades(text, start, end, data_type)
        if data_type is None:
            continue
        candidates.append(
            Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="TB",
                data_type=data_type,
                span=(start, end),
                score=round(min(0.99, max(0.5, conf)), 3),
                original_text=text[start:end],
            )
        )

    cue_kept: list[Entity] = []
    for pass_name, e in detect_name_context_passes(text):
        if pass_name == "strong" or any(
            e.span[0] < me and ms < e.span[1] for ms, me in model_name_spans
        ):
            cue_kept.append(e)
    # A verified cue span carries the full name boundary; a model span it
    # contains is the same person clipped (the model said "someone is here",
    # the cue says where the name starts and ends). Drop the contained model
    # span so dedupe cannot prefer it and leak the surname.
    if cue_kept:
        contained = {
            id(c)
            for c in candidates
            if c.data_type == "NAME"
            and any(k.span[0] <= c.span[0] and c.span[1] <= k.span[1] for k in cue_kept)
        }
        candidates = [c for c in candidates if id(c) not in contained]
    return _deduplicate(candidates + cue_kept)


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
        if name == "tner":
            # Not a PyThaiNLP engine: TNER is an HTTP service, so NER(engine=
            # "tner") raised a raw library error and the registered slot did
            # nothing. TnerEngine exposes the same .tag() contract instead.
            from pii_redactor.detectors.tner_client import TnerEngine

            _ner_cache[name] = TnerEngine(api_key=os.environ.get("AIFORTHAI_API_KEY", ""))
        else:
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

# Degenerate-chunk guard (gov-form OCR gap): on sufficiently noisy input the
# CRF sometimes returns a SINGLE span covering nearly the whole chunk instead
# of abstaining, and when that span's data_type is None the entire chunk
# silently yields zero entities -- including any real name the model would
# have tagged correctly in isolation. 80%/3-line are the two shapes this
# degenerate guess takes in the reproduced OCR corpus: either the label maps
# to None (LABEL_MAP.get(label) is None -- true both for a label missing from
# LABEL_MAP entirely, like the reproduced corpus's "LAW", AND for one of the
# labels LABEL_MAP explicitly maps to None, like MONEY/TIME/PERCENT --
# `label not in LABEL_MAP` would miss the second group even though
# _finalize_tb_candidate rejects both identically) or a mapped label has
# swallowed several unrelated form lines into one span (a real NAME/DATE/etc
# never spans that much of a multi-field form).
_DEGENERATE_COVERAGE_RATIO = 0.8
_DEGENERATE_MIN_LINES = 3


def _finalize_tb_candidate(text: str, orig_start: int, orig_end: int, label: str) -> list[Entity]:
    """Apply the normal LABEL_MAP -> hygiene -> cue-upgrade pipeline to one
    decoded BIO span and return the resulting candidate Entities (zero, one,
    or several -- see `_name_hygiene`). Shared by the main per-chunk loop and
    the degenerate-chunk line-by-line fallback so both paths reject/accept
    spans identically.
    """
    data_type = LABEL_MAP.get(label)
    if data_type is None:
        return []
    if (orig_end - orig_start) < 2:
        return []
    entity_text = text[orig_start:orig_end]
    if data_type == "ORGANIZATION" and not _THAI_CHAR_RE.search(entity_text):
        return []
    # NAME hygiene (blind-set precision classes): a person's name never spans
    # a line break. On label-first OCR field order the CRF can glue a form
    # label to the name(s) that follow it into one span, so the span is split
    # into segments (see `_name_hygiene`) rather than just trimmed to the
    # head -- trimming alone would keep the label itself as a false-positive
    # NAME. A segment BEGINNING with a document compound (ตารางสอบ…,
    # เลขครุภัณฑ์…) is a header, not a person. Compounds, never noun prefixes --
    # เลขา, ใบเฟิร์น and ประกาศิต are real names.
    if data_type == "NAME":
        segments = _name_hygiene(text, orig_start, orig_end)
    else:
        segments = [(orig_start, orig_end)]
    entities: list[Entity] = []
    for seg_start, seg_end in segments:
        seg_data_type = _apply_cue_upgrades(text, seg_start, seg_end, data_type)
        if seg_data_type is None:
            continue
        entities.append(
            Entity(
                entity_id=str(uuid.uuid4()),
                redact_type="TB",
                data_type=seg_data_type,
                span=(seg_start, seg_end),
                score=0.85,
                original_text=text[seg_start:seg_end],
            )
        )
    return entities


def _retag_degenerate_chunk(text: str, ner: NER, core_begin: int, core_end: int) -> list[Entity]:
    """Re-tag a degenerate chunk's core one physical line at a time.

    The whole-chunk tagging call that produced the degenerate span is not
    retried -- it is exactly what produced the bad guess. Isolating each line
    removes the noisy neighbours that dragged the CRF into a single bogus
    span, which is what lets it recognize a clean line's PII again (verified
    against the reproduced คร.1 OCR text: the CRF cannot tag a name at all in
    the degenerate whole-chunk context, but tags it correctly once the line
    carrying it is presented alone).
    """
    candidates: list[Entity] = []
    core_text = text[core_begin:core_end]
    offset = 0
    for raw_line in core_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if line.strip():
            line_start = core_begin + offset
            try:
                tagged_line = ner.tag(line)
            except Exception as exc:  # pragma: no cover - defensive, see chunk-level guard above
                _LOG.warning(
                    "NER tagging failed on degenerate-chunk line at char %d (%d chars; %s); "
                    "skipping — PII on this line may be missed",
                    line_start,
                    len(line),
                    type(exc).__name__,
                )
                tagged_line = []
            for ent_text, ls, le, label in _bio_to_spans(tagged_line, line):
                candidates.extend(
                    _finalize_tb_candidate(text, line_start + ls, line_start + le, label)
                )
        offset += len(raw_line)
    return candidates


def _ner_candidates(
    text: str,
    ner: NER,
    sentence_offsets: list[tuple[str, int]],
    margin_sentences: int,
    diagnostics: NERChunkDiagnostics | None = None,
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

        if diagnostics is not None:
            diagnostics.attempted += 1
        try:
            tagged: list[tuple[str, str]] = ner.tag(context_text)
        except Exception as exc:
            # Dropping a whole chunk is recall-negative (violates recall >
            # precision). Never silence it — a repeatedly failing engine must
            # be visible, not quietly eat ~500 chars of PII. Offsets and the
            # exception class are safe integers/names; the message and
            # traceback are NOT logged because they can embed the input text.
            if diagnostics is not None:
                diagnostics.skipped += 1
            _LOG.warning(
                "NER tagging failed on chunk chars %d-%d (%d chars; %s); "
                "skipping — PII in this chunk may be missed",
                core_begin,
                core_end,
                len(context_text),
                type(exc).__name__,
            )
            chunk_first = chunk_last + 1
            continue
        if diagnostics is not None:
            diagnostics.succeeded += 1

        if tagged:
            bio_spans = _bio_to_spans(tagged, context_text)

            # Degenerate-chunk guard: a SINGLE span covering most of the core
            # is either a bogus unmapped label or a mapped label that has
            # swallowed several unrelated lines -- either way it is not a
            # real entity, and consuming it (or letting it fall through to
            # the normal loop below) would drop every real entity the model
            # could have found on this chunk's individual lines.
            if len(bio_spans) == 1:
                _ent_text, sp_ctx_start, sp_ctx_end, sp_label = bio_spans[0]
                sp_start = ctx_begin + sp_ctx_start
                sp_end = ctx_begin + sp_ctx_end
                core_len = core_end - core_begin
                overlap = max(0, min(sp_end, core_end) - max(sp_start, core_begin))
                crosses_lines = text[sp_start:sp_end].count("\n") + 1 >= _DEGENERATE_MIN_LINES
                if (
                    core_len > 0
                    and overlap >= _DEGENERATE_COVERAGE_RATIO * core_len
                    and (LABEL_MAP.get(sp_label) is None or crosses_lines)
                ):
                    _LOG.warning(
                        "Degenerate whole-chunk NER span (label=%s, chunk_chars=%d); "
                        "re-tagging chunk line-by-line",
                        sp_label,
                        core_len,
                    )
                    candidates.extend(_retag_degenerate_chunk(text, ner, core_begin, core_end))
                    chunk_first = chunk_last + 1
                    continue

            for ent_text, ctx_start, ctx_end_pos, label in bio_spans:
                orig_start = ctx_begin + ctx_start
                orig_end = ctx_begin + ctx_end_pos
                if not (core_begin <= orig_start < core_end):
                    continue
                candidates.extend(_finalize_tb_candidate(text, orig_start, orig_end, label))

        chunk_first = chunk_last + 1

    return candidates


def _trim_unoccupied_isolated_name_prefix(
    text: str,
    candidate: Entity,
) -> Entity | None:
    """Remove a field or role before an isolated NAME."""
    candidate_text = text[candidate.span[0] : candidate.span[1]]
    prefix = _ISOLATED_NAME_PREFIX_RE.match(candidate_text)
    if prefix is None:
        return candidate

    # Check the value with the normal name rules, then map it to the source.
    from pii_redactor.detectors.name_context import detect_name_context

    label = "ชื่อ "
    value = candidate_text[prefix.end() :]
    probe = label + value
    validated = [
        entity
        for entity in detect_name_context(probe)
        if entity.data_type == "NAME" and entity.span[0] >= len(label)
    ]
    if not validated:
        return None

    best = max(validated, key=lambda entity: entity.span[1] - entity.span[0])
    start = candidate.span[0] + prefix.end() + best.span[0] - len(label)
    end = candidate.span[0] + prefix.end() + best.span[1] - len(label)
    if not (candidate.span[0] <= start < end <= candidate.span[1]):
        return None
    return Entity(
        entity_id=candidate.entity_id,
        redact_type=candidate.redact_type,
        data_type=candidate.data_type,
        span=(start, end),
        score=candidate.score,
        original_text=text[start:end],
    )


def _isolated_line_name_candidates(
    text: str,
    ner: NER,
    occupied: list[Entity],
    diagnostics: NERChunkDiagnostics | None = None,
) -> tuple[list[Entity], set[str]]:
    """Retry short Thai lines with no entity or only NAME entities."""
    if "\n" not in text and "\r" not in text:
        return [], set()

    from pii_redactor.detectors.name_context import is_glued_name_run

    def _has_name_shape(line: str) -> bool:
        if _ISOLATED_NAME_LINE_RE.fullmatch(line):
            return True
        return bool(_ISOLATED_GLUED_LINE_RE.fullmatch(line)) and is_glued_name_run(line)

    candidates: list[Entity] = []
    superseded_ids: set[str] = set()
    attempted = 0
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        line_end = offset + len(line)
        line_entities = [
            entity
            for entity in occupied
            if not (line_end <= entity.span[0] or offset >= entity.span[1])
        ]
        line_has_non_name = any(entity.data_type != "NAME" for entity in line_entities)
        if (
            attempted < _ISOLATED_NAME_MAX_LINES
            and not line_has_non_name
            and len(line) <= _ISOLATED_NAME_MAX_CHARS
            and _has_name_shape(line)
        ):
            attempted += 1
            line_candidates = [
                entity
                for entity in _ner_candidates(
                    text,
                    ner,
                    [(line, offset)],
                    0,
                    diagnostics=diagnostics,
                )
                if entity.data_type == "NAME"
            ]
            if not line_entities:
                candidates.extend(
                    trimmed
                    for candidate in line_candidates
                    if (trimmed := _trim_unoccupied_isolated_name_prefix(text, candidate))
                    is not None
                )
                offset += len(raw_line)
                continue

            for candidate in line_candidates:
                overlapping = [
                    entity
                    for entity in line_entities
                    if not (
                        candidate.span[1] <= entity.span[0] or candidate.span[0] >= entity.span[1]
                    )
                ]
                preserves_start = overlapping and all(
                    candidate.span[0] == entity.span[0] for entity in overlapping
                )
                extends_right = all(
                    candidate.span[1] >= entity.span[1] for entity in overlapping
                ) and any(candidate.span[1] > entity.span[1] for entity in overlapping)
                if preserves_start and extends_right:
                    candidates.append(candidate)
                    superseded_ids.update(entity.entity_id for entity in overlapping)
        offset += len(raw_line)

    return candidates, superseded_ids


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------


def detect_tb(
    text: str,
    *,
    window_size: int = 1,
    diagnostics: NERChunkDiagnostics | None = None,
) -> list[Entity]:
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
    if name == "finetuned":
        return _detect_tb_finetuned(text)
    if name == "union":
        ners = [_load_ner("thainer"), _load_ner("wangchanberta")]
    else:
        ners = [_get_ner()]

    candidates: list[Entity] = []
    for ner in ners:
        candidates.extend(
            _ner_candidates(
                text,
                ner,
                sentence_offsets,
                window_size,
                diagnostics=diagnostics,
            )
        )

    # Recall booster: title/label-cued names the NER missed or clipped
    # (engine-independent, added once).
    from pii_redactor.detectors.name_context import detect_name_context

    candidates.extend(detect_name_context(text))
    if name == "thainer":
        isolated_names, superseded_ids = _isolated_line_name_candidates(
            text,
            ners[0],
            candidates,
            diagnostics=diagnostics,
        )
        candidates = [entity for entity in candidates if entity.entity_id not in superseded_ids]
        candidates.extend(isolated_names)

    # Deduplication
    return _deduplicate(candidates)
