"""OCR processing for pdf_hybrid pages (Step 1).

Optional dependency (requirements-ocr.txt): paddleocr, paddlepaddle,
opencv-python-headless. Never imported at module load time -- only inside
functions -- so importing this module is always safe even when the OCR
stack isn't installed. Callers must check is_available() (or catch
OCRUnavailableError) before relying on OCR extraction.
"""
from __future__ import annotations

from dataclasses import dataclass

from pii_redactor.ingest.quality_validator import OCR_CONFIDENCE_THRESHOLD
from pii_redactor.models import WordBbox

MAX_OCR_RETRIES = 3
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

        _engine = PaddleOCR(lang="th", use_textline_orientation=True)
    return _engine


@dataclass
class OCRPageResult:
    words: list[WordBbox]
    text: str
    confidence: float  # mean word-confidence for the page, 0.0 if no words found
    attempts: int  # 1..MAX_OCR_RETRIES
    human_review: bool  # True if confidence stayed below threshold after the final attempt


def _render_page_to_array(page, dpi: int):
    """Render a fitz.Page to an RGB numpy array at the given DPI."""
    import numpy as np

    pix = page.get_pixmap(dpi=dpi)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return arr[:, :, :3] if pix.n == 4 else arr


def _deskew(image):
    """Estimate and correct page skew via minAreaRect on the thresholded foreground."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if coords.shape[0] == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.1:
        return image
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


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

    level 0 (first attempt): deskew + denoise + sharpen.
    level >= 1 (retries): adds stronger binarization to help low-quality scans.
    """
    import cv2

    image = _deskew(image)
    image = _denoise(image)
    image = _sharpen(image)
    if level >= 1:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
        image = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
        )
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


def ocr_page(
    page, page_num: int, *, dpi: int = 300, max_retries: int = MAX_OCR_RETRIES
) -> OCRPageResult:
    """OCR a single PDF page with a retry loop.

    Retries up to max_retries times, escalating DPI and preprocessing strength
    each attempt while confidence stays below OCR_CONFIDENCE_THRESHOLD, stopping
    early once the threshold is met. human_review is set when confidence is
    still below threshold after the final attempt (design doc: "Retry >= 3 ->
    flag human review").
    """
    cur_dpi = dpi
    words: list[WordBbox] = []
    conf = 0.0
    attempts = 0
    for attempt in range(1, max_retries + 1):
        attempts = attempt
        arr = _render_page_to_array(page, cur_dpi)
        arr = preprocess_image(arr, level=attempt - 1)
        words, conf = _run_ocr_once(arr, page_num, cur_dpi)
        if conf >= OCR_CONFIDENCE_THRESHOLD:
            break
        cur_dpi = min(cur_dpi + _DPI_ESCALATION_STEP, _DPI_CAP)
    text = " ".join(w.text for w in words)
    return OCRPageResult(
        words=words,
        text=text,
        confidence=conf,
        attempts=attempts,
        human_review=conf < OCR_CONFIDENCE_THRESHOLD,
    )
