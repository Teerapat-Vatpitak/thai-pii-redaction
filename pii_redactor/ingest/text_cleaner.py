"""Text cleaning and normalization — 7-stage pipeline."""
import re
import unicodedata
from dataclasses import dataclass


@dataclass
class CleanResult:
    text: str                               # the cleaned text
    skipped_sentence_review: bool           # True if user didn't confirm sentence fixes
    ocr_error_flags: list[str]              # list of suspicious OCR substitution candidates (flagged, not fixed)
    broken_sentence_candidates: list[str]   # sentences that may be split wrongly (for user review)
    post_clean_warnings: list[str]          # any encoding issues found post-clean


# ---------------------------------------------------------------------------
# Stage 3 constants
# ---------------------------------------------------------------------------

THAI_DIGIT_MAP = {
    '๐': '0', '๑': '1', '๒': '2', '๓': '3', '๔': '4',
    '๕': '5', '๖': '6', '๗': '7', '๘': '8', '๙': '9',
}

# ---------------------------------------------------------------------------
# Stage 4: Broken word recovery helpers
# ---------------------------------------------------------------------------

_THAI_WORD_SET = None


def _get_thai_word_set():
    global _THAI_WORD_SET
    if _THAI_WORD_SET is None:
        from pythainlp.corpus import thai_words
        _THAI_WORD_SET = set(thai_words())
    return _THAI_WORD_SET


def _is_pure_thai(token: str) -> bool:
    return token.isalpha() and all('฀' <= c <= '๿' for c in token)


def _merge_split_words(text: str) -> str:
    from pythainlp import word_tokenize
    word_set = _get_thai_word_set()
    tokens = word_tokenize(text, engine='newmm')
    merged = []
    i = 0
    while i < len(tokens):
        if (i + 1 < len(tokens)
                and _is_pure_thai(tokens[i])
                and _is_pure_thai(tokens[i + 1])
                and tokens[i] + tokens[i + 1] in word_set):
            merged.append(tokens[i] + tokens[i + 1])
            i += 2
        else:
            merged.append(tokens[i])
            i += 1
    return ''.join(merged)


# ---------------------------------------------------------------------------
# Stage 5: OCR error patterns
# ---------------------------------------------------------------------------

OCR_PATTERNS = [
    (r'\b\w*Z\w*\b', 'Z-for-2 substitution candidate'),
    (r'\b[A-Z][a-z]*O[a-z]*\b', 'O-for-0 substitution candidate'),
    (r'\b\w*B\w*\b', 'B-for-8 substitution candidate'),
]

# ---------------------------------------------------------------------------
# Stage 6: Broken sentence detection
# ---------------------------------------------------------------------------

def _find_broken_sentences(text: str) -> list[str]:
    lines = text.split('\n')
    candidates = []
    for i in range(len(lines) - 1):
        line = lines[i].strip()
        next_line = lines[i + 1].strip()
        if not line or not next_line:
            continue
        ends_mid = not re.search(r'[.!?।।ฯ๚๛]$', line)
        starts_continuation = re.match(r'^[a-z฀-๿]', next_line)
        if ends_mid and starts_continuation:
            candidates.append(f"Line {i + 1}: '{line[:50]}...' → '{next_line[:30]}'")
    return candidates


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
    Run 7-stage text cleaning pipeline.

    Args:
        text: raw text to clean
        interactive: if True and broken sentences found, pause for user input (CLI mode)
                     if False (default/web mode), skip user review, log as skipped
        review_timeout_s: seconds to wait for user input before auto-skipping

    Returns:
        CleanResult with cleaned text and metadata
    """

    # ------------------------------------------------------------------
    # Stage 1: Whitespace normalization
    # ------------------------------------------------------------------
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    text = text.strip()

    # ------------------------------------------------------------------
    # Stage 2: Unicode normalization
    # ------------------------------------------------------------------
    text = unicodedata.normalize('NFC', text)

    # ------------------------------------------------------------------
    # Stage 3: Character standardization (Thai shape variants)
    # ------------------------------------------------------------------
    for thai, ascii_ch in THAI_DIGIT_MAP.items():
        text = text.replace(thai, ascii_ch)

    # Remove zero-width chars: zero-width space (U+200B), ZWJ (U+200C),
    # ZWNJ (U+200D), BOM / zero-width no-break space (U+FEFF)
    text = re.sub(r'[​‌‍﻿]', '', text)

    # ------------------------------------------------------------------
    # Stage 4: Broken word recovery
    # ------------------------------------------------------------------
    text = _merge_split_words(text)

    # ------------------------------------------------------------------
    # Stage 5: OCR error detection (flag only, do NOT auto-fix)
    # ------------------------------------------------------------------
    ocr_flags: list[str] = []
    for pattern, label in OCR_PATTERNS:
        matches = re.findall(pattern, text)
        for m in matches:
            ocr_flags.append(f"{label}: '{m}'")

    # ------------------------------------------------------------------
    # Stage 6: Broken sentence detection (interactive if enabled)
    # ------------------------------------------------------------------
    broken_candidates = _find_broken_sentences(text)
    skipped = False

    if broken_candidates:
        if interactive:
            print(
                f"\n[Text Cleaner] Found {len(broken_candidates)} possible broken sentences:"
            )
            for c in broken_candidates:
                print(f"  {c}")
            print(
                f"\nConfirm these are real issues? [y/N] "
                f"(auto-skip in {review_timeout_s}s): ",
                end='',
                flush=True,
            )
            try:
                import msvcrt
                import time

                start = time.monotonic()
                response = ''
                while time.monotonic() - start < review_timeout_s:
                    if msvcrt.kbhit():
                        ch = msvcrt.getwche()
                        if ch in ('\r', '\n'):
                            break
                        response += ch
                if response.strip().lower() == 'y':
                    # User confirmed -- we still don't auto-fix
                    pass
                else:
                    skipped = True
            except ImportError:
                # Non-Windows fallback
                skipped = True
        else:
            skipped = True  # web mode: always skip

    # ------------------------------------------------------------------
    # Stage 7: Post-clean encoding check
    # ------------------------------------------------------------------
    post_warnings: list[str] = []
    try:
        text.encode('utf-8')
    except UnicodeEncodeError as e:
        post_warnings.append(f"Post-clean encoding issue: {e}")
        text = text.encode('utf-8', errors='replace').decode('utf-8')

    return CleanResult(
        text=text,
        skipped_sentence_review=skipped,
        ocr_error_flags=ocr_flags,
        broken_sentence_candidates=broken_candidates,
        post_clean_warnings=post_warnings,
    )
