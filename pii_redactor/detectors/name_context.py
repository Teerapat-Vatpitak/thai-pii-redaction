"""Context-based Thai name detection (recall booster for the CRF NER).

The thainer CRF NER misses some names and clips others (e.g. a leading title
"นาย" shifts the span so the surname leaks). Thai names are reliably introduced
by a small set of high-precision cues — titles (นาย/นาง/นางสาว/…) and explicit
name labels (ผมชื่อ…, ลงชื่อ). This pass works on word TOKENS (not raw regex)
so it does not fire on substrings like "นายก" or "คุณภาพ", and captures the
following 1–2 name tokens.

Emitted entities are TB/NAME with a slightly higher score than the CRF, so when
they overlap a partial CRF hit the longer, complete name wins de-duplication.
Recall > precision: a few extra cues are preferred over missed names.
"""
from __future__ import annotations

import re
import uuid

from pythainlp.tokenize import word_tokenize

from pii_redactor.models import Entity

# Titles that, as standalone tokens, almost always precede a person name.
_TITLES = {
    "นาย", "นาง", "นางสาว", "น.ส.", "ด.ช.", "ด.ญ.", "เด็กชาย", "เด็กหญิง",
}
# "ชื่อ" is only a name cue right after a first-person pronoun.
_PRONOUNS = {"ผม", "ดิฉัน", "ฉัน", "หนู", "กระผม", "ข้าพเจ้า"}
# Compound self-introductions newmm may keep as one token.
_INTRO_COMPOUND = {"ผมชื่อ", "ดิฉันชื่อ", "ฉันชื่อ", "หนูชื่อ", "ลงชื่อ"}

_THAI_WORD = re.compile(r"^[ก-๛]{2,}$")
# Thai-script tokens that are not names even right after a cue.
_NOT_NAME = {
    "ชื่อ", "นามสกุล", "คือ", "ครับ", "ค่ะ", "คะ", "นะ", "และ", "ที่", "ของ", "จาก",
    "อยู่", "เป็น", "อายุ", "มา", "ไป", "ได้", "เบอร์", "อีเมล", "โทร",
}


def _is_name_token(tok: str) -> bool:
    return bool(_THAI_WORD.match(tok)) and tok not in _NOT_NAME and tok not in _TITLES


def detect_name_context(text: str) -> list[Entity]:
    """Detect names introduced by a title or an explicit name label."""
    if not text or not text.strip():
        return []

    tokens = word_tokenize(text, keep_whitespace=True)
    # map tokens to character offsets
    spans: list[tuple[str, int, int]] = []
    pos = 0
    for t in tokens:
        i = text.find(t, pos)
        if i == -1:
            i = pos
        spans.append((t, i, i + len(t)))
        pos = i + len(t)

    n = len(spans)
    ents: list[Entity] = []
    for idx, (tok, _s, _e) in enumerate(spans):
        is_title = tok in _TITLES
        is_cue = is_title or tok in _INTRO_COMPOUND
        if not is_cue and tok == "ชื่อ":
            # cue only if the previous non-space token is a first-person pronoun
            j = idx - 1
            while j >= 0 and spans[j][0].strip() == "":
                j -= 1
            is_cue = j >= 0 and spans[j][0] in _PRONOUNS
        if not is_cue:
            continue

        # collect the name: first-name + optional surname (2 space-separated
        # groups). A single space joins the two groups; a second space ends it.
        # Thai first names often tokenize into several tokens, so count groups
        # (space gaps), not tokens.
        collected: list[tuple[int, int]] = []
        j = idx + 1
        space_seen = False
        while j < n:
            ttok, ts, te = spans[j]
            if ttok.strip() == "":  # whitespace
                if not collected:  # leading space before the name
                    j += 1
                    continue
                if space_seen:  # second gap -> first+surname already captured
                    break
                space_seen = True
                j += 1
                continue
            if _is_name_token(ttok):
                collected.append((ts, te))
                j += 1
            else:
                break

        if collected:
            # for a title cue, include the title in the span so this fuller
            # entity wins de-duplication against a CRF hit that clipped the
            # surname (e.g. CRF "นายสมชาย" vs here "นายสมชาย ใจดี").
            start = spans[idx][1] if is_title else collected[0][0]
            end = collected[-1][1]
            if end - start >= 2:  # span chokepoint
                ents.append(
                    Entity(
                        entity_id=str(uuid.uuid4()),
                        redact_type="TB",
                        data_type="NAME",
                        span=(start, end),
                        score=0.9,
                        original_text=text[start:end],
                    )
                )
    return ents
