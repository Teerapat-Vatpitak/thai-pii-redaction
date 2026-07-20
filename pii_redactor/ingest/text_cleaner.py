"""Text cleaning and normalization — 4-stage pipeline.

Stages 4/5/6 of the original 7 (broken-word recovery, OCR-error flagging,
broken-sentence review) were removed after the v2 audit verified the kill-list
claim against the running code:

- stage 4 tokenized every input through PyThaiNLP and rejoined it, loading the
  entire Thai word set into memory, yet changed nothing on real Thai text (0/4
  representative samples) while being free to concatenate tokens the tokenizer
  had split;
- stage 5 flagged every word containing B or Z as an "OCR substitution
  candidate" ("Bob", "Building", "ZIP", "AB1234567" all matched);
- stage 6's interactive review branch was unreachable — no caller anywhere
  passes interactive=True, so it always took the auto-skip path.

Nothing consumed any of their outputs (only hasattr assertions in tests), so
the work was computed and discarded on every request.
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass
class CleanResult:
    text: str  # the cleaned text
    post_clean_warnings: list[str]  # any encoding issues found post-clean


# ---------------------------------------------------------------------------
# Stage 3 constants
# ---------------------------------------------------------------------------

THAI_DIGIT_MAP = {
    "๐": "0",
    "๑": "1",
    "๒": "2",
    "๓": "3",
    "๔": "4",
    "๕": "5",
    "๖": "6",
    "๗": "7",
    "๘": "8",
    "๙": "9",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def clean(
    text: str,
    *,
    interactive: bool = False,
    review_timeout_s: float = 30.0,
) -> CleanResult:
    """
    Run the text cleaning pipeline: whitespace, Unicode NFC, Thai character
    standardization, and a post-clean encoding check.

    Args:
        text: raw text to clean
        interactive: accepted and ignored — kept so existing callers and the CLI
                     flag keep working now that the interactive review stage is
                     gone (it was never reachable; no caller set it).
        review_timeout_s: accepted and ignored, same reason.

    Returns:
        CleanResult with cleaned text and any post-clean encoding warnings
    """
    del interactive, review_timeout_s  # retained for call-site compatibility

    # ------------------------------------------------------------------
    # Stage 1: Whitespace normalization
    # ------------------------------------------------------------------
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = text.strip()

    # ------------------------------------------------------------------
    # Stage 2: Unicode normalization
    # ------------------------------------------------------------------
    text = unicodedata.normalize("NFC", text)

    # ------------------------------------------------------------------
    # Stage 3: Character standardization (Thai shape variants)
    # ------------------------------------------------------------------
    for thai, ascii_ch in THAI_DIGIT_MAP.items():
        text = text.replace(thai, ascii_ch)

    # Remove zero-width chars: zero-width space (U+200B), ZWJ (U+200C),
    # ZWNJ (U+200D), BOM / zero-width no-break space (U+FEFF)
    text = re.sub(r"[​‌‍﻿]", "", text)

    # ------------------------------------------------------------------
    # Stage 4: Post-clean encoding check
    # ------------------------------------------------------------------
    post_warnings: list[str] = []
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as e:
        post_warnings.append(f"Post-clean encoding issue: {e}")
        text = text.encode("utf-8", errors="replace").decode("utf-8")

    return CleanResult(text=text, post_clean_warnings=post_warnings)
