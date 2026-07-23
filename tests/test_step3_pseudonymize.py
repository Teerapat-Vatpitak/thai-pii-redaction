"""Tests for Step 3: pseudonymization (fp_generator, tb_generator, anonymizer)."""

import uuid

import pytest

from pii_redactor.anonymizer.anonymizer import anonymize
from pii_redactor.anonymizer.fp_generator import generate_fp
from pii_redactor.anonymizer.tb_generator import generate_tb
from pii_redactor.models import Entity, EntityRegistry, PseudonymizedDocument
from pii_redactor.session_vault import SessionVault

SALT = "test-salt-abc123"


# ---------------------------------------------------------------------------
# fp_generator tests
# ---------------------------------------------------------------------------


def test_generate_fp_thai_id():
    from pii_redactor.detectors.thai_id import is_valid_thai_id

    result = generate_fp("THAI_ID", "1101200012345", salt=SALT)
    assert len(result.replace("-", "").replace(" ", "")) == 13
    assert is_valid_thai_id(result.replace("-", "").replace(" ", ""))


def test_generate_fp_deterministic():
    r1 = generate_fp("EMAIL", "real@example.com", salt=SALT)
    r2 = generate_fp("EMAIL", "real@example.com", salt=SALT)
    assert r1 == r2


def test_generate_fp_different_originals():
    r1 = generate_fp("EMAIL", "alice@example.com", salt=SALT)
    r2 = generate_fp("EMAIL", "bob@example.com", salt=SALT)
    assert r1 != r2


def test_generate_fp_different_salts():
    r1 = generate_fp("EMAIL", "same@example.com", salt="salt1")
    r2 = generate_fp("EMAIL", "same@example.com", salt="salt2")
    assert r1 != r2


def test_generate_fp_phone():
    result = generate_fp("PHONE", "081-234-5678", salt=SALT)
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_fp_credit_card_luhn():
    from pii_redactor.detectors.fp_detector import _luhn_check

    result = generate_fp("CREDIT_CARD", "4532015112830366", salt=SALT)
    digits = result.replace("-", "").replace(" ", "")
    assert len(digits) == 16
    assert _luhn_check(digits)


# ---------------------------------------------------------------------------
# tb_generator tests
# ---------------------------------------------------------------------------


def test_generate_tb_name():
    result = generate_tb("NAME", "นาย ___ ทำงาน", salt=SALT, original="สมชาย")
    assert isinstance(result, str)
    assert len(result) > 0
    assert "___" not in result


def test_generate_tb_full_name_preserves_two_part_shape():
    result = generate_tb(
        "NAME",
        "ผมชื่อ ___ ขอลาป่วย",
        salt=SALT,
        original="นายสมชาย ใจดี",
    )
    assert len(result.split()) == 2


def test_generate_tb_deterministic():
    r1 = generate_tb("NAME", "context ___", salt=SALT, original="สมชาย")
    r2 = generate_tb("NAME", "context ___", salt=SALT, original="สมชาย")
    assert r1 == r2


def test_generate_tb_address():
    result = generate_tb("ADDRESS", "อยู่ที่ ___", salt=SALT, original="123 ถนนสุขุมวิท")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# anonymizer tests
# ---------------------------------------------------------------------------


def _make_entity(
    data_type: str,
    text: str,
    start: int,
    end: int,
    redact_type: str = "FP",
) -> Entity:
    return Entity(
        entity_id=str(uuid.uuid4()),
        redact_type=redact_type,
        data_type=data_type,
        span=(start, end),
        score=1.0,
        original_text=text[start:end],
    )


def test_anonymize_replaces_email():
    text = "contact wittaya.s@company.co.th for details"
    email_start = text.index("wittaya")
    email_end = text.index(" for")
    entity = _make_entity("EMAIL", text, email_start, email_end)
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "wittaya.s@company.co.th" not in result.text
    assert isinstance(result.text, str)


def test_anonymize_vault_stores_mapping():
    text = "email: test@example.com here"
    start = text.index("test@")
    end = text.index(" here")
    entity = _make_entity("EMAIL", text, start, end)
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    record = vault.get_by_entity_id(entity.entity_id)
    assert record is not None
    assert record.original == "test@example.com"


def test_anonymize_empty_registry():
    text = "no PII here"
    registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert result.text == text


def test_anonymize_consistency():
    text = "call 081-234-5678 or 081-234-5678"
    e1 = _make_entity("PHONE", text, 5, 17)
    e2 = _make_entity("PHONE", text, 21, 33)
    registry = EntityRegistry(entities=[e1, e2], fp_count=2, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "081-234-5678" not in result.text


def test_anonymize_returns_pseudonymized_document():
    text = "contact test@example.com"
    start = text.index("test@")
    entity = _make_entity("EMAIL", text, start, len(text))
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert isinstance(result, PseudonymizedDocument)
    assert result.session_id == vault.session_id


# ---------------------------------------------------------------------------
# collision-safe pseudonym tests (roadmap Horizon-1 #4)
# ---------------------------------------------------------------------------


def test_generate_tb_attempt_rerolls_seed():
    """attempt > 0 must vary the seed so a collision can be re-rolled;
    attempt=0 must keep the historical deterministic value."""
    base = generate_tb("NAME", "context ___", salt=SALT, original="สมชาย")
    assert generate_tb("NAME", "context ___", salt=SALT, original="สมชาย", attempt=0) == base
    rerolls = {
        generate_tb("NAME", "context ___", salt=SALT, original="สมชาย", attempt=n)
        for n in range(1, 6)
    }
    assert rerolls - {base}, "re-roll attempts never produced a different pseudonym"
    # deterministic per attempt
    assert generate_tb(
        "NAME", "context ___", salt=SALT, original="สมชาย", attempt=3
    ) == generate_tb("NAME", "context ___", salt=SALT, original="สมชาย", attempt=3)


def test_generate_fp_attempt_rerolls_seed():
    base = generate_fp("PHONE", "081-234-5678", salt=SALT)
    assert generate_fp("PHONE", "081-234-5678", salt=SALT, attempt=0) == base
    rerolls = {generate_fp("PHONE", "081-234-5678", salt=SALT, attempt=n) for n in range(1, 6)}
    assert rerolls - {base}


def test_anonymize_rerolls_on_pseudonym_collision(monkeypatch):
    """Two DIFFERENT people whose generated fake names collide must not share
    a pseudonym (the vault reverse index would restore the wrong person)."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    def fake_generate_tb(data_type, context, *, salt, original, attempt=0):
        if attempt == 0:
            return "ชนกัน"  # everyone collides on the first attempt
        return f"คนละคน{attempt}-{original}"

    monkeypatch.setattr(anon_mod, "generate_tb", fake_generate_tb)

    text = "ผู้ร้องคือ สมชาย ใจดี และผู้ถูกร้องคือ วิชัย ทองแท้"
    e1 = _make_entity(
        "NAME", text, text.index("สมชาย"), text.index("สมชาย") + len("สมชาย ใจดี"), redact_type="TB"
    )
    e2 = _make_entity(
        "NAME", text, text.index("วิชัย"), text.index("วิชัย") + len("วิชัย ทองแท้"), redact_type="TB"
    )
    registry = EntityRegistry(entities=[e1, e2], fp_count=0, tb_count=2)
    vault = SessionVault()
    anonymize(text, registry, vault, salt=SALT)

    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p1 != p2
    # both people must be independently recoverable through the reverse index
    assert vault.get_by_pseudonym(p1).original == "สมชาย ใจดี"
    assert vault.get_by_pseudonym(p2).original == "วิชัย ทองแท้"


def test_anonymize_suffix_fallback_when_generator_exhausted(monkeypatch):
    """If every re-roll still collides, a unique suffix is the last resort —
    never a silent overwrite."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    def stubborn_generate_tb(data_type, context, *, salt, original, attempt=0):
        return "ชนกัน"

    monkeypatch.setattr(anon_mod, "generate_tb", stubborn_generate_tb)

    text = "ผู้ร้องคือ สมชาย ใจดี และผู้ถูกร้องคือ วิชัย ทองแท้"
    e1 = _make_entity(
        "NAME", text, text.index("สมชาย"), text.index("สมชาย") + len("สมชาย ใจดี"), redact_type="TB"
    )
    e2 = _make_entity(
        "NAME", text, text.index("วิชัย"), text.index("วิชัย") + len("วิชัย ทองแท้"), redact_type="TB"
    )
    registry = EntityRegistry(entities=[e1, e2], fp_count=0, tb_count=2)
    vault = SessionVault()
    anonymize(text, registry, vault, salt=SALT)

    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p1 != p2
    assert vault.get_by_pseudonym(p1).original != vault.get_by_pseudonym(p2).original


def test_anonymize_fp_collision_rerolls_never_suffixes(monkeypatch):
    """FP pseudonyms must stay format-valid: a '#N' suffix would leave the
    valid FP-looking base embedded in the output (detect_fp re-flags it).
    Collisions re-roll instead."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    def fake_generate_fp(data_type, original, *, salt, attempt=0):
        if attempt == 0:
            return "099-999-9999"  # everyone collides on attempt 0
        return f"099-999-{9000 + attempt}"  # unique per attempt

    monkeypatch.setattr(anon_mod, "generate_fp", fake_generate_fp)

    text = "call 081-234-5678 or 086-111-2233"
    e1 = _make_entity("PHONE", text, 5, 17)
    e2 = _make_entity("PHONE", text, 21, 33)
    registry = EntityRegistry(entities=[e1, e2], fp_count=2, tb_count=0)
    vault = SessionVault()
    anonymize(text, registry, vault, salt=SALT)

    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p1 != p2
    assert "#" not in p1 and "#" not in p2


def test_anonymize_fp_exhausted_raises_instead_of_suffix(monkeypatch):
    """If an FP generator somehow cannot produce a unique value, fail loudly —
    a suffixed FP value is either misleading or re-flagged as a leak."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    def stubborn_generate_fp(data_type, original, *, salt, attempt=0):
        return "099-999-9999"

    monkeypatch.setattr(anon_mod, "generate_fp", stubborn_generate_fp)

    text = "call 081-234-5678 or 086-111-2233"
    e1 = _make_entity("PHONE", text, 5, 17)
    e2 = _make_entity("PHONE", text, 21, 33)
    registry = EntityRegistry(entities=[e1, e2], fp_count=2, tb_count=0)
    vault = SessionVault()
    with pytest.raises(ValueError):
        anonymize(text, registry, vault, salt=SALT)


def test_anonymize_suffix_never_embeds_another_persons_real_value(monkeypatch):
    """The '#N' last resort must not wrap a base that equals another entity's
    REAL value — 'สมชาย ใจดี#2' would ship the real name to the AI."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    def evil_generate_tb(data_type, context, *, salt, original, attempt=0):
        return "สมชาย ใจดี"  # always collides with person A's real name

    monkeypatch.setattr(anon_mod, "generate_tb", evil_generate_tb)

    text = "ผู้ร้องคือ สมชาย ใจดี และผู้ถูกร้องคือ วิชัย ทองแท้"
    e1 = _make_entity(
        "NAME", text, text.index("สมชาย"), text.index("สมชาย") + len("สมชาย ใจดี"), redact_type="TB"
    )
    e2 = _make_entity(
        "NAME", text, text.index("วิชัย"), text.index("วิชัย") + len("วิชัย ทองแท้"), redact_type="TB"
    )
    registry = EntityRegistry(entities=[e1, e2], fp_count=0, tb_count=2)
    vault = SessionVault()
    with pytest.raises(ValueError):
        anonymize(text, registry, vault, salt=SALT)


def test_anonymize_same_original_still_shares_pseudonym():
    """Consistency must survive the uniqueness check: the SAME original
    appearing as two entities keeps one shared pseudonym (no re-roll)."""
    text = "call 081-234-5678 or 081-234-5678"
    e1 = _make_entity("PHONE", text, 5, 17)
    e2 = _make_entity("PHONE", text, 21, 33)
    registry = EntityRegistry(entities=[e1, e2], fp_count=2, tb_count=0)
    vault = SessionVault()
    anonymize(text, registry, vault, salt=SALT)
    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p1 == p2


def test_anonymize_avoids_pseudonym_equal_to_other_original(monkeypatch):
    """A generated fake must not equal ANOTHER person's real value — reverse
    mapping would then plant person A's data where person B's real value stood."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    def unlucky_generate_tb(data_type, context, *, salt, original, attempt=0):
        if original == "วิชัย ทองแท้" and attempt == 0:
            return "สมชาย ใจดี"  # fake for B happens to equal A's real name
        return f"ปลอม{attempt}-{original}"

    monkeypatch.setattr(anon_mod, "generate_tb", unlucky_generate_tb)

    text = "ผู้ร้องคือ สมชาย ใจดี และผู้ถูกร้องคือ วิชัย ทองแท้"
    e1 = _make_entity(
        "NAME", text, text.index("สมชาย"), text.index("สมชาย") + len("สมชาย ใจดี"), redact_type="TB"
    )
    e2 = _make_entity(
        "NAME", text, text.index("วิชัย"), text.index("วิชัย") + len("วิชัย ทองแท้"), redact_type="TB"
    )
    registry = EntityRegistry(entities=[e1, e2], fp_count=0, tb_count=2)
    vault = SessionVault()
    anonymize(text, registry, vault, salt=SALT)

    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p2 != "สมชาย ใจดี"


def test_anonymize_fn_scanner_entities_get_realistic_fake_values():
    """Regression: fn_scanner-detected THAI_ID/EMAIL must route through
    generate_fp (realistic fake value), not tb_generator's literal
    "[REDACTED_x]" fallback -- fn_scanner now tags them redact_type="FP"."""
    from pii_redactor.detectors.fn_scanner import scan_fn

    text = "id 1234567890123 email foo@bar.com"
    entities = scan_fn(text, [])
    assert {e.data_type for e in entities} == {"THAI_ID", "EMAIL"}
    assert all(e.redact_type == "FP" for e in entities)

    registry = EntityRegistry(
        entities=entities,
        fp_count=len(entities),
        tb_count=0,
    )
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "[REDACTED_THAI_ID]" not in result.text
    assert "[REDACTED_EMAIL]" not in result.text
    assert "1234567890123" not in result.text
    assert "foo@bar.com" not in result.text


# ---------------------------------------------------------------------------
# token_generator tests
# ---------------------------------------------------------------------------


def test_generate_token_known_type():
    from pii_redactor.anonymizer.token_generator import generate_token

    assert generate_token("NAME", 1) == "[ชื่อ_1]"
    assert generate_token("PHONE", 3) == "[โทรศัพท์_3]"


def test_generate_token_unknown_type_falls_back_to_type_name():
    from pii_redactor.anonymizer.token_generator import generate_token

    assert generate_token("MYSTERY", 2) == "[MYSTERY_2]"


def test_token_label_map_matches_v2_contract():
    from pii_redactor.anonymizer.token_generator import TOKEN_LABEL

    assert TOKEN_LABEL["THAI_ID"] == "บัตรประชาชน"
    assert TOKEN_LABEL["BANK_ACCOUNT"] == "บัญชีธนาคาร"
    assert len(TOKEN_LABEL) == 19
    assert TOKEN_LABEL["ORGANIZATION"] == "องค์กร"
    assert TOKEN_LABEL["ID_NUMBER"] == "รหัสอ้างอิง"
    # Added with the Thai address/health detectors: a postal code and a
    # hospital number are neither ADDRESS nor a generic reference number, and
    # the label map is what the caller sees, so it has to name them honestly.
    assert TOKEN_LABEL["POSTAL_CODE"] == "รหัสไปรษณีย์"
    assert TOKEN_LABEL["MEDICAL_ID"] == "เลขเวชระเบียน"


# ---------------------------------------------------------------------------
# anonymize(mode="token") tests
# ---------------------------------------------------------------------------


def test_anonymize_token_mode_brackets_and_counters():
    text = "email a@b.co and c@d.co and a@b.co"
    e1 = _make_entity("EMAIL", text, 6, 12)  # a@b.co
    e2 = _make_entity("EMAIL", text, 17, 23)  # c@d.co
    e3 = _make_entity("EMAIL", text, 28, 34)  # a@b.co again
    registry = EntityRegistry(entities=[e1, e2, e3], fp_count=3, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT, mode="token")
    assert "[อีเมล_1]" in result.text and "[อีเมล_2]" in result.text
    assert "a@b.co" not in result.text and "c@d.co" not in result.text
    # same original -> same token
    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p3 = vault.get_by_entity_id(e3.entity_id).pseudonym
    assert p1 == p3
    # distinct originals -> distinct ordinals
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p2 != p1


def test_anonymize_token_mode_ordinal_continues_across_calls():
    """Second call on the SAME vault (multi-turn) must not reuse ordinal 1."""
    vault = SessionVault()
    t1 = "email a@b.co"
    e1 = _make_entity("EMAIL", t1, 6, 12)
    anonymize(
        t1, EntityRegistry(entities=[e1], fp_count=1, tb_count=0), vault, salt=SALT, mode="token"
    )
    t2 = "email x@y.co"
    e2 = _make_entity("EMAIL", t2, 6, 12)
    r2 = anonymize(
        t2, EntityRegistry(entities=[e2], fp_count=1, tb_count=0), vault, salt=SALT, mode="token"
    )
    assert "[อีเมล_2]" in r2.text


def test_anonymize_token_mode_same_original_across_calls_reuses_token():
    vault = SessionVault()
    t1 = "email a@b.co"
    e1 = _make_entity("EMAIL", t1, 6, 12)
    r1 = anonymize(
        t1, EntityRegistry(entities=[e1], fp_count=1, tb_count=0), vault, salt=SALT, mode="token"
    )
    t2 = "again a@b.co"
    e2 = _make_entity("EMAIL", t2, 6, 12)
    r2 = anonymize(
        t2, EntityRegistry(entities=[e2], fp_count=1, tb_count=0), vault, salt=SALT, mode="token"
    )
    assert "[อีเมล_1]" in r1.text and "[อีเมล_1]" in r2.text


def test_anonymize_default_mode_is_surrogate():
    text = "email a@b.co now"
    e1 = _make_entity("EMAIL", text, 6, 12)
    registry = EntityRegistry(entities=[e1], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "[" not in result.text  # no bracket tokens in surrogate mode
    assert "a@b.co" not in result.text


def test_generate_tb_new_types():
    loc = generate_tb("LOCATION", "ไปเที่ยว ___", salt=SALT, original="เชียงใหม่")
    assert loc and not loc[0].isdigit()  # a place name, no house number
    org = generate_tb("ORGANIZATION", "ทำงานที่ ___", salt=SALT, original="ธนาคารกสิกรไทย")
    assert org and "[REDACTED" not in org
    date = generate_tb("DATE", "ประชุมวันที่ ___", salt=SALT, original="12 มกราคม 2560")
    assert "/" in date and "[REDACTED" not in date


def test_generate_fp_new_types():
    idnum = generate_fp("ID_NUMBER", "1234567890", salt=SALT)
    assert len(idnum) == 10 and idnum.isdigit()
    date = generate_fp("DATE", "12/05/2560", salt=SALT)
    assert "/" in date or "-" in date
