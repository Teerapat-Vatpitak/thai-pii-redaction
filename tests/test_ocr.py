"""OCR processing (pii_redactor.ingest.ocr_processor).

Tier 1 (always runs): unit-tests the retry/confidence/human-review control
flow in ocr_page() and the pixel->point rescaling in _run_ocr_once() by
monkeypatching the rendering/preprocessing/engine seams -- no real cv2 or
paddleocr required.

Tier 2 (pytest.importorskip("cv2")): exercises the real preprocessing
functions against synthetic images.
"""
import builtins

import pytest

from pii_redactor.ingest import ocr_processor
from pii_redactor.models import WordBbox

# --- Tier 1: is_available() -------------------------------------------------


def test_is_available_false_when_import_fails(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("cv2", "paddleocr"):
            raise ImportError("mocked missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert ocr_processor.is_available() is False


# --- Tier 1: _run_ocr_once() pixel -> point rescaling -----------------------


class _FakeEngine:
    def predict(self, image):
        # One detected line: a 100x20 pixel box at the page's top-left corner.
        return [
            {
                "rec_texts": ["ทดสอบ"],
                "rec_scores": [0.95],
                "rec_boxes": [[0, 0, 100, 20]],
            }
        ]


def test_run_ocr_once_scales_pixel_to_point_space(monkeypatch):
    monkeypatch.setattr(ocr_processor, "_get_engine", lambda: _FakeEngine())
    words, conf = ocr_processor._run_ocr_once(object(), page_num=1, dpi=300)

    assert len(words) == 1
    word = words[0]
    scale = 72.0 / 300
    assert word.page == 1
    assert word.text == "ทดสอบ"
    assert word.x == pytest.approx(0.0)
    assert word.y == pytest.approx(0.0)
    assert word.width == pytest.approx(100 * scale)
    assert word.height == pytest.approx(20 * scale)
    assert conf == pytest.approx(0.95)


def test_run_ocr_once_empty_result_has_zero_confidence(monkeypatch):
    class _EmptyEngine:
        def predict(self, image):
            return [{"rec_texts": [], "rec_scores": [], "rec_boxes": []}]

    monkeypatch.setattr(ocr_processor, "_get_engine", lambda: _EmptyEngine())
    words, conf = ocr_processor._run_ocr_once(object(), page_num=1, dpi=300)
    assert words == []
    assert conf == 0.0


# --- Tier 1: ocr_page() retry / human_review control flow -------------------


def _patch_render_and_preprocess(monkeypatch):
    monkeypatch.setattr(ocr_processor, "_render_page_to_array", lambda page, dpi: dpi)
    monkeypatch.setattr(ocr_processor, "preprocess_image", lambda img, level=0: img)


def test_ocr_page_succeeds_first_try_no_retry(monkeypatch):
    _patch_render_and_preprocess(monkeypatch)
    calls = []

    def fake_run(image, page_num, dpi):
        calls.append(dpi)
        return [WordBbox(text="abc", page=page_num, x=0, y=0, width=1, height=1)], 0.9

    monkeypatch.setattr(ocr_processor, "_run_ocr_once", fake_run)
    result = ocr_processor.ocr_page(page=object(), page_num=1)

    assert result.attempts == 1
    assert result.human_review is False
    assert result.confidence == pytest.approx(0.9)
    assert calls == [300]


def test_ocr_page_retry_succeeds_on_second_attempt(monkeypatch):
    _patch_render_and_preprocess(monkeypatch)
    confidences = iter([0.4, 0.85])

    def fake_run(image, page_num, dpi):
        return [WordBbox(text="x", page=page_num, x=0, y=0, width=1, height=1)], next(confidences)

    monkeypatch.setattr(ocr_processor, "_run_ocr_once", fake_run)
    result = ocr_processor.ocr_page(page=object(), page_num=1)

    assert result.attempts == 2
    assert result.human_review is False
    assert result.confidence == pytest.approx(0.85)


def test_ocr_page_exhausts_retries_flags_human_review(monkeypatch):
    _patch_render_and_preprocess(monkeypatch)
    monkeypatch.setattr(ocr_processor, "_run_ocr_once", lambda image, page_num, dpi: ([], 0.3))

    result = ocr_processor.ocr_page(page=object(), page_num=1)

    assert result.attempts == 3
    assert result.human_review is True
    assert result.confidence == pytest.approx(0.3)


def test_ocr_page_escalates_dpi_on_retry(monkeypatch):
    _patch_render_and_preprocess(monkeypatch)
    seen_dpis = []

    def fake_run(image, page_num, dpi):
        seen_dpis.append(image)  # "image" is the dpi value, since render returns dpi as-is
        return [], 0.1

    monkeypatch.setattr(ocr_processor, "_run_ocr_once", fake_run)
    ocr_processor.ocr_page(page=object(), page_num=1, dpi=300)

    assert seen_dpis == [300, 400, 500]


def test_ocr_page_escalates_preprocess_level_on_retry(monkeypatch):
    monkeypatch.setattr(ocr_processor, "_render_page_to_array", lambda page, dpi: "img")
    seen_levels = []

    def fake_preprocess(img, level=0):
        seen_levels.append(level)
        return img

    monkeypatch.setattr(ocr_processor, "preprocess_image", fake_preprocess)
    monkeypatch.setattr(ocr_processor, "_run_ocr_once", lambda image, page_num, dpi: ([], 0.1))
    ocr_processor.ocr_page(page=object(), page_num=1)

    assert seen_levels == [0, 1, 2]


def test_ocr_page_word_count_matches_text(monkeypatch):
    _patch_render_and_preprocess(monkeypatch)
    words = [
        WordBbox(text="สวัสดี", page=1, x=0, y=0, width=1, height=1),
        WordBbox(text="ครับ", page=1, x=1, y=0, width=1, height=1),
    ]
    monkeypatch.setattr(ocr_processor, "_run_ocr_once", lambda image, page_num, dpi: (words, 0.9))

    result = ocr_processor.ocr_page(page=object(), page_num=1)

    assert result.text == "สวัสดี ครับ"
    assert result.words == words


# --- Tier 2: real preprocessing functions (requires opencv-python-headless) --
# Each test imports cv2 and numpy itself (rather than at module level) so the
# rest of this file still collects and runs when the optional OCR stack isn't
# installed -- a module-level import of either would break Tier-1 collection.
# numpy ships with opencv, so the cv2 skip and the numpy import go together.


def test_denoise_preserves_shape_and_dtype():
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
    out = ocr_processor._denoise(img)
    assert out.shape == img.shape
    assert out.dtype == np.uint8


def test_sharpen_preserves_shape():
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
    out = ocr_processor._sharpen(img)
    assert out.shape == img.shape


def _install_fake_cv2(monkeypatch, calls):
    """Inject a fake cv2 that records warpAffine (rotation) calls and forces a
    non-trivial skew angle, so any rotation in the preprocessing path is
    observable without the real OpenCV installed."""
    import sys
    import types

    np = pytest.importorskip("numpy")
    fake = types.ModuleType("cv2")
    fake.COLOR_RGB2GRAY = 7
    fake.THRESH_BINARY_INV = 1
    fake.THRESH_OTSU = 8
    fake.INTER_CUBIC = 2
    fake.BORDER_REPLICATE = 1
    fake.cvtColor = lambda img, code: (img[:, :, 0] if img.ndim == 3 else img)
    # thresh image with foreground so np.where(...) yields coords -> deskew proceeds
    fake.threshold = lambda gray, a, b, flags: (0.0, np.ones_like(gray))
    fake.minAreaRect = lambda coords: ((0.0, 0.0), (1.0, 1.0), 5.0)  # 5 deg skew
    fake.getRotationMatrix2D = lambda center, angle, scale: np.eye(2, 3, dtype=float)
    def _warp(img, matrix, size, **kw):
        calls.append("warpAffine")
        return img
    fake.warpAffine = _warp
    fake.fastNlMeansDenoisingColored = lambda img, *a, **k: img
    fake.fastNlMeansDenoising = lambda img, *a, **k: img
    fake.GaussianBlur = lambda img, ksize, sigma: img
    fake.addWeighted = lambda a, wa, b, wb, g: a
    monkeypatch.setitem(sys.modules, "cv2", fake)
    return np


def test_preprocess_does_not_rotate_coordinates(monkeypatch):
    """DET-3: OCR bboxes are consumed by redactor.py against a render of the
    ORIGINAL (unrotated) page, so preprocessing must NOT apply an affine
    rotation -- a rotated image yields boxes in a different coordinate space and
    the black redaction rectangles land off the actual PII."""
    calls: list[str] = []
    np = _install_fake_cv2(monkeypatch, calls)
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    img[10:40, 10:40] = 255
    ocr_processor.preprocess_image(img, level=0)
    assert "warpAffine" not in calls, (
        "preprocessing rotated the image; OCR bbox coordinates will not match "
        "redactor.py's unrotated page render (DET-3)"
    )


def test_preprocess_image_level0_keeps_color_shape():
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
    out = ocr_processor.preprocess_image(img, level=0)
    assert out.shape == img.shape


def test_deskew_removed():
    """DET-3: deskew was removed from the module to keep OCR bbox coordinates in
    the same (unrotated) space redactor.py renders and paints on."""
    assert not hasattr(ocr_processor, "_deskew")


def test_preprocess_image_level1_binarizes_to_grayscale():
    pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    img = np.random.randint(0, 255, (50, 50, 3), dtype=np.uint8)
    out = ocr_processor.preprocess_image(img, level=1)
    assert out.ndim == 2


def test_is_available_true_when_deps_present():
    pytest.importorskip("cv2")
    pytest.importorskip("paddleocr")
    assert ocr_processor.is_available() is True
