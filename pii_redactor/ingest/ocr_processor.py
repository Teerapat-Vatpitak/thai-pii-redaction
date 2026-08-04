"""OCR processing for pdf_hybrid pages (Step 1).

Optional dependency (requirements-ocr.txt): paddleocr, paddlepaddle,
OpenCV (provided by the PaddleOCR/PaddleX dependency set). Never imported at
module load time -- only inside functions -- so importing this module is
always safe even when the OCR stack isn't installed. Callers must check
is_available() (or catch
OCRUnavailableError) before relying on OCR extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.ingest.quality_validator import OCR_CONFIDENCE_THRESHOLD
from pii_redactor.ingest.text_cleaner import clean_length_preserving
from pii_redactor.models import WordBbox

MAX_OCR_RETRIES = 3
MIN_OCR_ATTEMPTS = 2
OCR_EARLY_STOP_THRESHOLD = 0.9
_DPI_ESCALATION_STEP = 100
_DPI_CAP = 600


class OCRUnavailableError(RuntimeError):
    """pdf_hybrid extraction was requested but the OCR stack isn't installed."""


def _prime_torch_if_present() -> None:
    """Windows DLL-load-order workaround.

    If torch is installed (the optional sentence-transformers Section-26
    detector pulls it in), it must be imported before paddleocr/paddle in
    this process -- paddleocr's own dependency chain (via albumentations)
    imports torch too, and if paddle's native libraries load first, torch's
    later import fails with "OSError: ... Error loading ...torch\\lib\\shm.dll".
    Importing torch here first (best-effort, a no-op if it isn't installed)
    avoids the crash regardless of which optional feature a process uses first.
    """
    try:
        import torch  # noqa: F401
    except Exception:
        pass


def is_available() -> bool:
    """Whether the optional OCR dependencies (requirements-ocr.txt) are importable."""
    _prime_torch_if_present()
    try:
        import cv2  # noqa: F401
        import paddleocr  # noqa: F401
    except Exception:
        return False
    return True


_engine = None


def _get_engine():
    """Lazy singleton PaddleOCR engine (Thai language model)."""
    global _engine
    if _engine is None:
        _prime_torch_if_present()
        from paddleocr import PaddleOCR

        # Redaction uses the original page coordinates.
        _engine = PaddleOCR(
            lang="th",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
        )
    return _engine


@dataclass
class OCRPageResult:
    words: list[WordBbox]
    text: str
    confidence: float  # lowest confidence among kept text
    attempts: int  # 1..MAX_OCR_RETRIES
    human_review: bool  # true when kept text has low confidence
    warnings: list[str] = field(default_factory=list)  # e.g. engine-fault retries


def _render_page_to_array(page, dpi: int):
    """Render a pypdfium2 PdfPage to an RGB numpy array at the given DPI."""
    import numpy as np

    scale = dpi / 72.0
    pil_image = page.render(scale=scale).to_pil().convert("RGB")
    return np.asarray(pil_image)


def _denoise(image):
    """Remove scan noise while preserving character edges."""
    import cv2

    if image.ndim == 3:
        return cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)
    return cv2.fastNlMeansDenoising(image, None, 10, 7, 21)


def _sharpen(image):
    """Unsharp-mask sharpening to increase character legibility."""
    import cv2

    blurred = cv2.GaussianBlur(image, (0, 0), 3)
    return cv2.addWeighted(image, 1.5, blurred, -0.5, 0)


def preprocess_image(image, *, level: int = 0):
    """Preprocess a rendered page image before OCR.

    level 0 (first attempt): denoise + sharpen.
    level >= 1 (retries): adds stronger binarization to help low-quality scans.

    NOTE: no deskew here (DET-3). Rotating the page for OCR put the detected
    bboxes in a rotated coordinate space, but redactor.py paints its black
    boxes on a render of the ORIGINAL (unrotated) page -- so on any skewed scan
    the redaction rectangles landed off the actual PII, leaving it visible. The
    old angle logic was also written for OpenCV < 4.5's convention and could
    over-rotate a near-straight page by ~90 deg under the pinned cv2 >= 4.9.
    PaddleOCR's own text detector tolerates moderate skew; keeping the image
    unrotated guarantees bbox coordinates match the redaction render.
    """
    import cv2

    image = _denoise(image)
    image = _sharpen(image)
    if level >= 1:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        image = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
        )
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    return image


def _run_ocr_once(image, page_num: int, dpi: int) -> tuple[list[WordBbox], float]:
    """Run PaddleOCR on a preprocessed page image.

    Rescales detected boxes from pixel space (at the given DPI) back to PDF
    point space (72 DPI) so they line up with fitz's page coordinate system --
    the same contract redactor.py already relies on for text-layer bboxes.

    PaddleOCR's predict() returns one OCRResult (dict-like) per input image,
    with parallel "rec_texts" / "rec_scores" / "rec_boxes" fields -- rec_boxes
    is an (N, 4) array of axis-aligned [x0, y0, x1, y1] pixel-space boxes, one
    per recognized line.
    """
    engine = _get_engine()
    scale = 72.0 / dpi
    result = engine.predict(image)
    words: list[WordBbox] = []
    confs: list[float] = []
    if result:
        page_result = result[0]
        texts = page_result["rec_texts"]
        scores = page_result["rec_scores"]
        boxes = page_result["rec_boxes"]
        for text, conf, box in zip(texts, scores, boxes):
            x0, y0, x1, y1 = (float(v) for v in box)
            words.append(
                WordBbox(
                    text=text,
                    page=page_num,
                    x=x0 * scale,
                    y=y0 * scale,
                    width=(x1 - x0) * scale,
                    height=(y1 - y0) * scale,
                )
            )
            confs.append(float(conf))
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    return words, mean_conf


def _structured_keys(text: str) -> set[tuple[str, str]]:
    """Return structured matches for one OCR line."""
    clean_text = clean_length_preserving(text)
    entities = detect_fp(clean_text)
    entities.extend(scan_fn(clean_text, entities))
    return {(entity.data_type, entity.original_text.casefold().strip()) for entity in entities}


def _same_word_area(first: WordBbox, second: WordBbox) -> bool:
    if first.page != second.page:
        return False
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first.width) * max(0.0, first.height)
    second_area = max(0.0, second.width) * max(0.0, second.height)
    smaller_area = min(first_area, second_area)
    return bool(smaller_area and intersection / smaller_area >= 0.3)


def _word_key(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def _merge_retry_words(
    primary_words: list[WordBbox],
    primary_confidence: float,
    attempts: list[tuple[list[WordBbox], float]],
) -> tuple[list[WordBbox], float]:
    """Add text found in new page areas on later tries."""
    merged = list(primary_words)
    used_confidences = [primary_confidence]
    seen_structured = set().union(*(_structured_keys(word.text) for word in merged))

    for words, confidence in sorted(attempts, key=lambda item: item[1], reverse=True):
        if words is primary_words:
            continue
        for word in words:
            overlaps = [
                index for index, current in enumerate(merged) if _same_word_area(word, current)
            ]
            word_key = _word_key(word.text)
            if any(_word_key(merged[index].text) == word_key for index in overlaps):
                continue

            keys = _structured_keys(word.text)
            if keys - seen_structured:
                merged.append(word)
                seen_structured.update(keys)
                used_confidences.append(confidence)
                continue
            if not overlaps:
                merged.append(word)
                used_confidences.append(confidence)
                continue

            contained = [
                index
                for index in overlaps
                if _word_key(merged[index].text) and _word_key(merged[index].text) in word_key
            ]
            # Replacing is only safe when the longer read still carries every
            # structured value the reads it evicts carried. A retry that adds
            # one digit to a national id contains the old key as a SUBSTRING
            # while matching no pattern itself, so without this check a 0.55
            # attempt could delete the 0.90 attempt's valid THAI_ID and leave
            # nothing for detection — and nothing for redaction — to find.
            if contained and keys >= set().union(
                *(_structured_keys(merged[index].text) for index in contained)
            ):
                for index in sorted(contained, reverse=True):
                    merged.pop(index)
                merged.append(word)
                used_confidences.append(confidence)

    merged.sort(key=lambda word: (word.page, word.y, word.x))
    return merged, min(used_confidences)


def ocr_page(
    page, page_num: int, *, dpi: int = 300, max_retries: int = MAX_OCR_RETRIES
) -> OCRPageResult:
    """OCR a page, then join useful text from its retries."""
    cur_dpi = dpi
    best_conf = -1.0
    attempt_results: list[tuple[list[WordBbox], float]] = []
    attempts = 0
    warnings: list[str] = []
    for attempt in range(1, max_retries + 1):
        attempts = attempt
        arr = _render_page_to_array(page, cur_dpi)
        arr = preprocess_image(arr, level=attempt - 1)
        try:
            words, conf = _run_ocr_once(arr, page_num, cur_dpi)
        except RuntimeError as exc:
            if type(exc) is not RuntimeError:
                raise
            # PaddlePaddle's pybind layer translates transient native faults
            # to BARE builtins.RuntimeError ("Unknown exception",
            # enforce-class errors like PreconditionNotMet). Retry the failed
            # attempt once, visibly: the warning is recorded on the page
            # result and surfaced through extract() meta warnings, so
            # evidence shows every retry. A second failure propagates
            # unchanged, and RuntimeError SUBCLASSES (PdfiumError,
            # OCRUnavailableError) never retry.
            warnings.append(
                f"page {page_num}: OCR attempt {attempt} raised RuntimeError; retried once"
            )
            words, conf = _run_ocr_once(arr, page_num, cur_dpi)
        attempt_results.append((words, conf))
        if conf > best_conf:
            best_conf = conf
        minimum = min(MIN_OCR_ATTEMPTS, max_retries)
        if attempt >= minimum and best_conf >= OCR_EARLY_STOP_THRESHOLD:
            break
        cur_dpi = min(cur_dpi + _DPI_ESCALATION_STEP, _DPI_CAP)
    primary_words, primary_conf = max(attempt_results, key=lambda item: item[1])
    merged_words, retained_conf = _merge_retry_words(
        primary_words,
        primary_conf,
        attempt_results,
    )
    text = "\n".join(word.text for word in merged_words)
    return OCRPageResult(
        words=merged_words,
        text=text,
        confidence=max(retained_conf, 0.0),
        attempts=attempts,
        human_review=retained_conf < OCR_CONFIDENCE_THRESHOLD,
        warnings=warnings,
    )
