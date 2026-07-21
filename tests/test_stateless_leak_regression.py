"""Regression pins for PII that survives the platform entry point.

Observed on 21 Jul 2026 by running `sanitize_stateless` on a five-line Thai
government letter: the house number, the soi, the sub-district, the postal
code, an untitled personal name and a hospital number all survived into the
sanitized text -- and the call reported `warnings == []`, i.e. "clean".

That entry point is the one the NECTEC platform calls, where the caller is a
stranger, so every gap here is a live PII disclosure rather than a quality
issue. These tests are written from the observed behaviour BEFORE any fix, so
they fail for the reason the product actually fails rather than the reason a
proposed fix expects it to.

The last two tests pin the guard itself rather than the detectors: a residual
leak must never be reported as clean, and a caller-supplied mapping must not
be able to switch the guard off.
"""

import pytest

from pii_redactor import stateless as stateless_module
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.session_vault import SessionVault
from pii_redactor.stateless import StatelessLeakError, sanitize_stateless

# A plain Thai government letter. Nothing exotic -- this is the shape of the
# documents a regulator or an agency clerk pastes in first.
LETTER = """เรียน ผู้อำนวยการกองคลัง
ข้าพเจ้า วิชัย ประสงค์ดี ขอยื่นคำร้อง
ที่อยู่ 99 ซอยลาดพร้าว 71 แขวงวังทองหลาง กรุงเทพมหานคร 10310
โทร 081-234-5678 เลขประจำตัวประชาชน 1 1017 00230 70 8
ผู้ป่วย HN 6801234 เข้ารับการรักษา"""

# Every substring above that identifies the person. Kept as one list so the
# "never reported as clean" test below covers exactly what the individual
# tests cover, with no drift between them.
IDENTIFYING = [
    "99 ซอยลาดพร้าว 71",
    "แขวงวังทองหลาง",
    "10310",
    "วิชัย ประสงค์ดี",
    "6801234",
]


@pytest.fixture
def sanitized():
    return sanitize_stateless(LETTER, mode="token", salt="s")


def test_house_number_and_soi_do_not_survive(sanitized):
    """The street line is the most identifying part of a Thai address.

    Only the province is masked today: `กรุงเทพมหานคร` becomes a token while
    `99 ซอยลาดพร้าว 71` is left verbatim. Masking the province and keeping the
    house number inverts the intent -- the province is the least identifying
    component in the line.
    """
    assert "99 ซอยลาดพร้าว 71" not in sanitized.sanitized_text


def test_sub_district_and_postal_code_do_not_survive(sanitized):
    """A sub-district plus a postal code narrows a person to a few streets.

    `แขวง`/`ตำบล` names and the five-digit postal code have no detector at
    all, so they pass through untouched even though the address cue words are
    right next to them.
    """
    assert "แขวงวังทองหลาง" not in sanitized.sanitized_text
    assert "10310" not in sanitized.sanitized_text


def test_a_name_without_a_title_does_not_survive(sanitized):
    """Names carry a title in forms, but not in the body of a letter.

    `ข้าพเจ้า วิชัย ประสงค์ดี` has an introducing cue and still survives,
    because the cue list keys on นาย/นาง/นางสาว and the CRF misses the bare
    name. This is the single most likely thing a judge or a clerk types.
    """
    assert "วิชัย ประสงค์ดี" not in sanitized.sanitized_text


def test_a_hospital_number_does_not_survive(sanitized):
    """HN is the primary identifier inside a Thai health record.

    The numeric detectors floor at eight digits, so a seven-digit HN sitting
    directly after its own `HN` cue is not detected -- in a document class
    that is Section 26 sensitive data by definition.
    """
    assert "6801234" not in sanitized.sanitized_text


def test_residual_pii_is_never_reported_as_clean(sanitized):
    """The guard-level contract, independent of any one detector.

    Detectors will always miss something; that is survivable. Reporting a
    miss as clean is not, because the caller has no other signal -- an empty
    `warnings` list is the platform's only "safe to send" indicator. So
    whatever survives, the result must not claim to be clean.
    """
    residual = [value for value in IDENTIFYING if value in sanitized.sanitized_text]
    assert not residual or sanitized.warnings, (
        f"identifying data survived but the call reported no warnings: {residual}"
    )


def test_a_caller_supplied_pseudonym_cannot_silence_the_leak_guard():
    """A stranger's mapping must not be able to switch the guard off.

    `scan_outbound_leaks` excuses any detector hit whose text is a known
    pseudonym. On the platform path those pseudonyms come from the caller via
    `prior_mapping`, so a caller who declares a real national ID to be "their
    pseudonym" removes it from the guard's findings. Verified directly: the
    same text is reported as a THAI_ID leak against an empty vault and as
    clean against a seeded one.
    """
    real_id = "1101700230708"
    leaked = f"ข้อความที่ยังมีเลขบัตร {real_id} หลงเหลืออยู่"

    honest = SessionVault()
    assert scan_outbound_leaks(leaked, honest), "fixture broken: the guard must see this leak"

    attacker = SessionVault()
    attacker.seed(real_id, "ชื่อปลอมอะไรก็ได้")
    assert scan_outbound_leaks(leaked, attacker), (
        "a caller-declared pseudonym that is itself real PII must not be excused"
    )


def test_a_residual_name_blocks_the_send_instead_of_warning(monkeypatch):
    """A leaked NAME must stop the call, not annotate it.

    On the platform path the response goes straight to a model, so a warning
    string nobody parses is the same as no protection at all. FP-grade leaks
    already raise; TB-grade ones (NAME, ADDRESS -- exactly what the detectors
    miss most often) only appended `possible_tb_leak:` and shipped the text.

    The guard is stubbed rather than reproduced through the detectors on
    purpose: this pins the POLICY (a known residual leak blocks) independently
    of which inputs happen to defeat detection on any given day.
    """
    leaked_name = detect_tb("นายสมชาย ใจดี ทำงานที่นี่")
    assert leaked_name, "fixture broken: the NER must see a name here"
    monkeypatch.setattr(
        stateless_module, "scan_outbound_leaks", lambda text, vault: list(leaked_name)
    )

    with pytest.raises(StatelessLeakError) as excinfo:
        sanitize_stateless("ทดสอบข้อความ", mode="token", salt="s")
    assert excinfo.value.leak_types, "the error must name what leaked, machine-readably"


def test_an_orphan_digit_run_is_reported_even_though_no_detector_claims_it():
    """The independent check: a second opinion that is not the first one again.

    `leak_guard` calls the same `detect_fp`/`detect_tb` that produced the
    output, so anything detection missed on the way in is missed again on the
    way out -- three layers on the diagram, one layer in practice. A long bare
    digit run is the cheapest signal that does NOT depend on those detectors:
    the numeric detectors are cue-gated or floored at eight digits, so a
    six-or-seven-digit identifier with an unfamiliar label passes them all.

    Reported, not blocked: unlabelled numbers are also amounts and quantities,
    so this is a flag for a human, not a halt.
    """
    out = sanitize_stateless("ผู้ป่วยหมายเลข 6801234 เข้ารับการรักษา", mode="token", salt="s")
    if "6801234" in out.sanitized_text:
        assert any("orphan_digits" in w for w in out.warnings), (
            f"an unmasked 7-digit run went out unreported: {out.warnings}"
        )
