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
from pii_redactor.leak_guard import scan_outbound_leaks, scan_residual_signals
from pii_redactor.session_vault import SessionVault, VaultTimeoutError
from pii_redactor.stateless import (
    StatelessLeakError,
    StatelessProcessingError,
    restore_stateless,
    sanitize_into_vault,
    sanitize_stateless,
)

SYNTHETIC_VAULT_ORIGINAL = "synthetic-vault-original@example.invalid"


def _product_traceback_locals(error):
    frames = []
    traceback = error.__traceback__
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module.startswith(("pii_redactor.", "app.")):
            frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return frames


def _contains_identity(value, target, seen=None):
    """Inspect only built-in containers; never call product object protocols."""
    if value is target:
        return True
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return False
    seen.add(identity)
    if isinstance(value, dict):
        return any(
            _contains_identity(item, target, seen) for pair in value.items() for item in pair
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_identity(item, target, seen) for item in value)
    return False


def _assert_retained_error_is_safe(error, *, forbidden_text=(), forbidden_objects=()):
    assert error.__cause__ is None
    assert error.__context__ is None
    frames = _product_traceback_locals(error)
    assert frames
    rendered = repr(frames)
    for value in forbidden_text:
        assert value not in rendered
        assert value not in repr(vars(error))
    for target in forbidden_objects:
        assert not any(_contains_identity(frame, target) for frame in frames)
        assert not _contains_identity(vars(error), target)


def _raise_sensitive_failure(text, prior_mapping, vault):
    cause = ValueError(f"nested:{text}")
    error = RuntimeError(f"boundary:{text}")
    error.payload = {
        "text": text,
        "prior_mapping": prior_mapping,
        "vault": vault,
    }
    raise error from cause


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

    A successful outbound sanitize result cannot contain a known residual.
    Residuals are errors, not warning-only results that a caller can ignore.
    """
    residual = [value for value in IDENTIFYING if value in sanitized.sanitized_text]
    assert not residual


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


def test_an_orphan_digit_run_blocks_even_when_no_detector_claims_it(monkeypatch):
    """The independent check: a second opinion that is not the first one again.

    `leak_guard` calls the same `detect_fp`/`detect_tb` that produced the
    output, so anything detection missed on the way in is missed again on the
    way out -- three layers on the diagram, one layer in practice. A long bare
    digit run is the cheapest signal that does NOT depend on those detectors:
    the numeric detectors are cue-gated or floored at eight digits, so a
    six-or-seven-digit identifier with an unfamiliar label passes them all.

    The outbound policy is fail closed. Inspection endpoints may still report
    detector findings, but a sanitize result cannot carry this signal as a
    warning that callers can ignore.
    """
    monkeypatch.setattr(
        stateless_module,
        "scan_residual_signals",
        lambda _text, _vault: ["orphan_digits:7"],
    )

    with pytest.raises(StatelessLeakError) as excinfo:
        sanitize_stateless("ผู้ป่วยหมายเลข 6801234 เข้ารับการรักษา", mode="token", salt="s")

    assert excinfo.value.leak_types == ["ORPHAN_DIGITS"]
    assert "6801234" not in str(excinfo.value)


def test_stateless_residual_error_graph_drops_input_and_prior_mapping(monkeypatch):
    residual = "เอกสารหมายเลข 6801234"
    monkeypatch.setattr(
        stateless_module,
        "scan_residual_signals",
        lambda _text, _vault: ["orphan_digits:7"],
    )

    with pytest.raises(StatelessLeakError) as excinfo:
        sanitize_stateless(
            residual,
            mode="token",
            salt="s",
            prior_mapping={"[EMAIL_9]": SYNTHETIC_VAULT_ORIGINAL},
        )

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    frame_locals = _product_traceback_locals(excinfo.value)
    assert frame_locals
    assert residual not in repr(frame_locals)
    assert SYNTHETIC_VAULT_ORIGINAL not in repr(frame_locals)


def test_caller_seed_cannot_silence_detector_independent_digit_guard():
    """A caller-declared numeric pseudonym is not trusted outbound material."""
    vault = SessionVault()
    vault.seed("6801234", "เจ้าของข้อมูลสังเคราะห์")

    assert scan_residual_signals("เอกสารอ้างอิง 6801234", vault)


def test_caller_seed_cannot_silence_text_residual_guard():
    """A caller-declared realistic name is not proof that the output is safe."""
    seeded_name = "นายสมชาย ใจดี"
    vault = SessionVault()
    vault.seed(seeded_name, "เจ้าของข้อมูลสังเคราะห์")

    assert scan_outbound_leaks(f"ผู้ยื่นคำร้อง {seeded_name}", vault)


def test_missing_replacement_record_blocks_instead_of_returning_empty_token(monkeypatch):
    """A silent vault-write defect must not produce an incomplete projection."""
    monkeypatch.setattr(SessionVault, "write", lambda *_args, **_kwargs: None)

    with pytest.raises(StatelessLeakError) as excinfo:
        sanitize_stateless("โทร 081-234-5678", mode="token", salt="s")

    assert excinfo.value.leak_types == ["MISSING_REPLACEMENT_RECORD"]
    assert excinfo.value.policy_categories == ["replacement_integrity"]
    assert excinfo.value.category_count == 1
    assert "081-234-5678" not in str(excinfo.value)


def test_direct_sanitize_unexpected_error_graph_is_contained(monkeypatch):
    raw_text = "privacy-boundary.person@example.com"
    prior_mapping = {"[EMAIL_9]": SYNTHETIC_VAULT_ORIGINAL}
    vault = SessionVault()

    def fail_detection(_text):
        _raise_sensitive_failure(raw_text, prior_mapping, vault)

    monkeypatch.setattr(stateless_module, "detect_all", fail_detection)

    with pytest.raises(StatelessProcessingError) as excinfo:
        sanitize_into_vault(raw_text, vault, mode="token", salt="secret-salt")

    assert excinfo.value.code == "stateless_sanitize_failed"
    assert str(excinfo.value) == "stateless sanitize failed"
    _assert_retained_error_is_safe(
        excinfo.value,
        forbidden_text=(raw_text, SYNTHETIC_VAULT_ORIGINAL, "secret-salt"),
        forbidden_objects=(vault, prior_mapping),
    )


def test_direct_sanitize_preserves_safe_leak_metadata_without_the_inner_graph(
    monkeypatch,
):
    raw_text = "privacy-boundary.person@example.com"
    vault = SessionVault()

    def fail_policy(*_args, **_kwargs):
        error = stateless_module.OutboundPolicyError(
            ["THAI_ID", "THAI_ID"],
            policy_categories=["structured", "detector_independent"],
        )
        error.payload = raw_text
        raise error from RuntimeError(raw_text)

    monkeypatch.setattr(stateless_module, "enforce_outbound_policy", fail_policy)

    with pytest.raises(StatelessLeakError) as excinfo:
        sanitize_into_vault(raw_text, vault, mode="token", salt="secret-salt")

    assert excinfo.value.leak_types == ["THAI_ID"]
    assert excinfo.value.policy_categories == ["detector_independent", "structured"]
    assert excinfo.value.category_count == 2
    _assert_retained_error_is_safe(
        excinfo.value,
        forbidden_text=(raw_text, "secret-salt"),
        forbidden_objects=(vault,),
    )


def test_direct_sanitize_translates_timeout_to_a_fresh_fixed_error(monkeypatch):
    raw_text = "privacy-boundary.person@example.com"
    vault = SessionVault()

    def fail_detection(_text):
        raise VaultTimeoutError(raw_text) from RuntimeError(raw_text)

    monkeypatch.setattr(stateless_module, "detect_all", fail_detection)

    with pytest.raises(VaultTimeoutError) as excinfo:
        sanitize_into_vault(raw_text, vault, mode="token", salt="secret-salt")

    assert str(excinfo.value) == "Session vault idle timeout"
    _assert_retained_error_is_safe(
        excinfo.value,
        forbidden_text=(raw_text, "secret-salt"),
        forbidden_objects=(vault,),
    )


@pytest.mark.parametrize("boundary", ["seed", "export", "section26", "result"])
def test_stateless_tail_failures_clear_vault_and_contain_error_graph(
    monkeypatch,
    boundary,
):
    raw_text = "privacy-boundary.person@example.com"
    prior_mapping = {"[EMAIL_9]": SYNTHETIC_VAULT_ORIGINAL}
    vault = SessionVault()
    monkeypatch.setattr(stateless_module, "SessionVault", lambda: vault)

    def fail(*_args, **_kwargs):
        _raise_sensitive_failure(raw_text, prior_mapping, vault)

    if boundary == "seed":
        monkeypatch.setattr(vault, "seed", fail)
    elif boundary == "export":
        monkeypatch.setattr(vault, "export_mapping", fail)
    elif boundary == "section26":
        monkeypatch.setattr(stateless_module, "scan_section26", fail)
    else:
        monkeypatch.setattr(stateless_module, "StatelessSanitizeResult", fail)

    with pytest.raises(StatelessProcessingError) as excinfo:
        sanitize_stateless(
            raw_text,
            mode="token",
            salt="secret-salt",
            prior_mapping=prior_mapping,
        )

    assert excinfo.value.code == "stateless_sanitize_failed"
    assert str(excinfo.value) == "stateless sanitize failed"
    assert vault._table == {}
    assert vault._reverse == {}
    _assert_retained_error_is_safe(
        excinfo.value,
        forbidden_text=(raw_text, SYNTHETIC_VAULT_ORIGINAL, "secret-salt"),
        forbidden_objects=(vault, prior_mapping),
    )


def test_natural_empty_restore_clears_vault_and_returns_a_safe_value_error(
    monkeypatch,
):
    original = SYNTHETIC_VAULT_ORIGINAL
    mapping = {"[EMAIL_1]": original}
    vault = SessionVault()
    monkeypatch.setattr(stateless_module, "SessionVault", lambda: vault)

    with pytest.raises(ValueError) as excinfo:
        restore_stateless("", mapping=mapping)

    assert str(excinfo.value) == "restore text must not be empty"
    assert vault._table == {}
    assert vault._reverse == {}
    _assert_retained_error_is_safe(
        excinfo.value,
        forbidden_text=(original,),
        forbidden_objects=(vault, mapping),
    )


@pytest.mark.parametrize("boundary", ["seed", "reverse", "result"])
def test_restore_tail_failures_clear_vault_and_contain_error_graph(
    monkeypatch,
    boundary,
):
    raw_text = "คำตอบ [EMAIL_1]"
    mapping = {"[EMAIL_1]": SYNTHETIC_VAULT_ORIGINAL}
    vault = SessionVault()
    monkeypatch.setattr(stateless_module, "SessionVault", lambda: vault)

    def fail(*_args, **_kwargs):
        _raise_sensitive_failure(raw_text, mapping, vault)

    if boundary == "seed":
        monkeypatch.setattr(vault, "seed", fail)
    elif boundary == "reverse":
        monkeypatch.setattr(stateless_module, "reverse_map", fail)
    else:
        monkeypatch.setattr(stateless_module, "StatelessRestoreResult", fail)

    with pytest.raises(StatelessProcessingError) as excinfo:
        restore_stateless(raw_text, mapping=mapping)

    assert excinfo.value.code == "stateless_restore_failed"
    assert str(excinfo.value) == "stateless restore failed"
    assert vault._table == {}
    assert vault._reverse == {}
    _assert_retained_error_is_safe(
        excinfo.value,
        forbidden_text=(raw_text, SYNTHETIC_VAULT_ORIGINAL),
        forbidden_objects=(vault, mapping),
    )
