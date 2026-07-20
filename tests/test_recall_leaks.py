"""Adversarial regression tests for confirmed recall leaks (roadmap Horizon-1 #1).

Each case documents a real miss verified against the shipped detectors, so the
fix can never silently regress. Recall > precision governs: a leaked national
ID or phone number in a chat paste is the product's worst failure mode.
"""

from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.detectors.fp_detector import detect_fp

# A checksum-valid Thai national ID (mod-11). Standalone detection works today;
# the leak was that gluing it to Thai script hid it from every detector.
VALID_THAI_ID = "1101700230708"


def _types(entities):
    return {e.data_type for e in entities}


def _find(entities, data_type):
    return [e for e in entities if e.data_type == data_type]


# --- Leak 1: Thai-script adjacency defeats \b word boundaries ---------------
# `\b` sits between two word characters when a Thai letter meets a digit, so a
# value glued directly to Thai text (no space) evaded detect_fp and fn_scanner.


def test_thai_id_standalone_is_detected():
    # Sanity: the ID is valid and caught when space-delimited.
    ents = detect_fp(f"เลขบัตร {VALID_THAI_ID} ครับ")
    assert "THAI_ID" in _types(ents)


def test_thai_id_glued_to_thai_script_is_detected():
    text = f"เลขบัตรประชาชน{VALID_THAI_ID}"
    ids = _find(detect_fp(text), "THAI_ID")
    assert ids, "checksum-valid Thai ID glued to Thai script must be detected"
    assert text[ids[0].span[0] : ids[0].span[1]] == VALID_THAI_ID


def test_mobile_phone_glued_to_thai_script_is_detected():
    text = "โทร0812345678"
    phones = _find(detect_fp(text), "PHONE")
    assert phones, "mobile number glued to Thai must be detected"
    assert "0812345678" in text[phones[0].span[0] : phones[0].span[1]]


def test_fn_scanner_catches_glued_13_digits():
    # An invalid-checksum 13-digit run glued to Thai still must be flagged by the
    # FN second pass (it required a \b that adjacent Thai script denies).
    text = "รหัส1234567890123"
    ents = scan_fn(text, existing_entities=[])
    assert any(e.data_type == "THAI_ID" for e in ents)


# --- Leak 2: +66 international phone format ---------------------------------
# A Thai mobile in +66 form carries 9 national digits (leading 0 dropped). The
# old pattern only matched 8, so "+66 81 234 5678" was missed outright and
# "+66812345678" fell through to the STUDENT_ID any-8-to-12-digit catch-all.


def test_plus66_spaced_mobile_is_detected():
    assert "PHONE" in _types(detect_fp("+66 81 234 5678")), "+66 spaced mobile must be detected"


def test_plus66_compact_mobile_is_phone_not_student_id():
    ents = detect_fp("+66812345678")
    assert _find(ents, "PHONE"), "+66 compact mobile must be detected as PHONE"
    assert "STUDENT_ID" not in _types(ents), "+66 number must not be mislabeled STUDENT_ID"


def test_plus66_landline_is_detected():
    # 8 national digits (Bangkok landline, +66 2 xxx xxxx).
    assert "PHONE" in _types(detect_fp("+66 2 123 4567"))


# --- Leak 3: per-page PDF routing -------------------------------------------
# detect_source_type summed characters across the whole document, so a mostly
# scanned PDF with one text page cleared the 50-char threshold and was routed
# as pdf_text -- the scanned pages then contributed no text, no OCR, and no
# warning: an entity_count-0 redaction that looks safe but is not. The fix
# classifies per page: a page that carries an image but (almost) no text is
# image-only and forces the OCR-capable hybrid path; a genuinely blank page,
# having nothing to extract, must not.


def _make_pdf(tmp_path, name, pages):
    """Build a PDF. `pages` is a list of ("text", str) | ("image",) | ("blank",)."""
    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    path = tmp_path / name
    c = canvas.Canvas(str(path), pagesize=A4)
    for spec in pages:
        if spec[0] == "text":
            c.setFont("Helvetica", 12)
            c.drawString(72, 720, spec[1])
        elif spec[0] == "image":
            img = Image.new("RGB", (400, 300), (128, 128, 128))
            c.drawImage(ImageReader(img), 72, 400, width=400, height=300)
        # "blank": draw nothing
        c.showPage()
    c.save()
    return str(path)


def test_mixed_pdf_with_scanned_page_is_hybrid(tmp_path):
    from pii_redactor.ingest.file_detector import detect_source_type

    path = _make_pdf(
        tmp_path,
        "mixed.pdf",
        [
            ("text", "This is a full page of real selectable text content here."),
            ("image",),
        ],
    )
    assert detect_source_type(path) == "pdf_hybrid", (
        "a scanned page alongside a text page must not be silently dropped"
    )


def test_fully_scanned_pdf_is_hybrid(tmp_path):
    from pii_redactor.ingest.file_detector import detect_source_type

    path = _make_pdf(tmp_path, "scan.pdf", [("image",)])
    assert detect_source_type(path) == "pdf_hybrid"


def test_text_pdf_with_blank_page_is_not_forced_to_ocr(tmp_path):
    from pii_redactor.ingest.file_detector import detect_source_type

    path = _make_pdf(
        tmp_path,
        "textblank.pdf",
        [
            ("text", "This is a full page of real selectable text content here."),
            ("blank",),
        ],
    )
    assert detect_source_type(path) == "pdf_text", (
        "a blank divider page has nothing to OCR and must stay pdf_text"
    )


# --- Leak 4: PASSPORT / VEHICLE_PLATE glued to Thai script -------------------
# Same \b-vs-Thai-adjacency class as Leak 1, now for the alphanumeric PASSPORT
# patterns (which still used \b) and the VEHICLE_PLATE mid-word guard (which
# rejected any plate preceded by a Thai char). Surfaced by the gold `messy`
# slice at recall 0.000 on both CRF and WangchanBERTa (docs .../gold-v2-design).


def test_passport_standalone_is_detected():
    # Sanity: a space-delimited passport is caught today.
    assert "PASSPORT" in _types(detect_fp("หนังสือเดินทาง AB1234567 ออกให้"))


def test_passport_glued_to_thai_script_is_detected():
    text = "หนังสือเดินทางเลขที่AB1234567ออกโดยกรมการกงสุล"
    ps = _find(detect_fp(text), "PASSPORT")
    assert ps, "passport glued to Thai script must be detected"
    assert "AB1234567" in text[ps[0].span[0] : ps[0].span[1]]


def test_vehicle_plate_glued_after_cue_is_detected():
    text = "ทะเบียนรถขก 4471จอดในลานจอด"
    plates = _find(detect_fp(text), "VEHICLE_PLATE")
    assert plates, "plate glued to a Thai cue word (ทะเบียนรถ) must be detected"
    assert "4471" in text[plates[0].span[0] : plates[0].span[1]]


def test_thai_glued_plate_without_cue_stays_rejected():
    # Precision guard: a consonant+number run glued mid-Thai with NO ทะเบียน
    # cue stays rejected -- the mid-word guard is relaxed only on a plate cue.
    assert "VEHICLE_PLATE" not in _types(detect_fp("ผมมีรถกก 1234"))


def test_soi_number_is_not_a_vehicle_plate():
    # "ซอย 4" is Thai for "Soi 4" (a lane in an address), not a plate, but
    # ซ-อ-ย are all consonants followed by a number, so the loose plate regex
    # matched it. A locality stopword must suppress it while real plates stay.
    for text in (
        "88 หมู่บ้านสวนหลวง ซอย 4 ตำบลหนองปรือ",
        "55/1 ถนนสุขุมวิท ซอย 24 คลองตัน",
    ):
        assert "VEHICLE_PLATE" not in _types(detect_fp(text)), text
    # The real cued plate is unaffected.
    assert "VEHICLE_PLATE" in _types(detect_fp("ทะเบียนรถขก 4471 จอด"))
