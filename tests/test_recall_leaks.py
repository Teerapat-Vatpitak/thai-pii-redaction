"""Adversarial regression tests for confirmed recall leaks (roadmap Horizon-1 #1).

Each case documents a real miss verified against the shipped detectors, so the
fix can never silently regress. Recall > precision governs: a leaked national
ID or phone number in a chat paste is the product's worst failure mode.
"""
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.fn_scanner import scan_fn


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
    assert text[ids[0].span[0]:ids[0].span[1]] == VALID_THAI_ID


def test_mobile_phone_glued_to_thai_script_is_detected():
    text = "โทร0812345678"
    phones = _find(detect_fp(text), "PHONE")
    assert phones, "mobile number glued to Thai must be detected"
    assert "0812345678" in text[phones[0].span[0]:phones[0].span[1]]


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
    assert "PHONE" in _types(detect_fp("+66 81 234 5678")), \
        "+66 spaced mobile must be detected"


def test_plus66_compact_mobile_is_phone_not_student_id():
    ents = detect_fp("+66812345678")
    assert _find(ents, "PHONE"), "+66 compact mobile must be detected as PHONE"
    assert "STUDENT_ID" not in _types(ents), "+66 number must not be mislabeled STUDENT_ID"


def test_plus66_landline_is_detected():
    # 8 national digits (Bangkok landline, +66 2 xxx xxxx).
    assert "PHONE" in _types(detect_fp("+66 2 123 4567"))
