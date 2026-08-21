"""Tests for Step 3: pseudonymization (fp_generator, tb_generator, anonymizer)."""

import time
import uuid

import pytest

from pii_redactor.anonymizer.anonymizer import anonymize
from pii_redactor.anonymizer.fp_generator import generate_fp
from pii_redactor.anonymizer.tb_generator import generate_tb
from pii_redactor.models import Entity, EntityRegistry, PseudonymizedDocument, VaultRecord
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


def _seed(vault: SessionVault, entity: Entity, pseudonym: str) -> None:
    """Pin an entity's pseudonym so the test does not depend on a random draw."""
    vault.write(
        VaultRecord(
            entity_id=entity.entity_id,
            original=entity.original_text,
            pseudonym=pseudonym,
            type=entity.redact_type,
            data_type=entity.data_type,
            span=entity.span,
            timestamp=time.monotonic(),
        )
    )


def test_consistency_scan_does_not_corrupt_an_already_written_pseudonym():
    """A pseudonym may contain another entity's original value verbatim.

    The fake pools are small and the NER splits names, so "ไทย" can be its own
    LOCATION entity while also sitting inside the NAME entity's fake surname.
    The consistency scan must not reach into a pseudonym it already wrote.
    """
    text = "ผู้ป่วยชื่อ สมหญิง รักไทย มาตรวจ"
    name_start = text.index("สมหญิง")
    name = _make_entity("NAME", text, name_start, name_start + len("สมหญิง"), redact_type="TB")
    loc_start = text.index("รักไทย") + len("รัก")
    loc = _make_entity("LOCATION", text, loc_start, loc_start + len("ไทย"), redact_type="TB")

    vault = SessionVault()
    _seed(vault, name, "อนุชา รักไทย")  # contains the LOCATION entity's original
    _seed(vault, loc, "เขตลาดกระบัง")

    registry = EntityRegistry(entities=[name, loc], fp_count=0, tb_count=2)
    result = anonymize(text, registry, vault, salt=SALT)

    assert "อนุชา รักไทย" in result.text


def test_consistency_scan_handles_a_self_overlapping_original():
    """An original can occur at overlapping offsets: "กก" sits at two offsets
    inside "กกก". Scheduling both splices one over the other, so a match must
    consume its own characters the way str.replace does."""
    text = "กก กกก"
    entity = _make_entity("NAME", text, 0, 2, redact_type="TB")
    vault = SessionVault()
    _seed(vault, entity, "สมชาย")

    registry = EntityRegistry(entities=[entity], fp_count=0, tb_count=1)
    result = anonymize(text, registry, vault, salt=SALT)

    assert result.text == "สมชาย สมชายก"


def test_consistency_scan_does_not_rescan_the_document_per_entity(monkeypatch):
    """The scan re-derived every pseudonym range from scratch for each entity,
    so a long paste re-scanned the whole document once per entity and masking
    grew with entities x length. Nothing changes between those calls unless the
    scan itself rewrote the text."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    phones = [f"08{i % 9 + 1}-{100 + i:03d}-{1000 + i:04d}" for i in range(40)]
    text = "\n".join(f"ผู้ติดต่อรายที่ {i} หมายเลขโทรศัพท์ {phone}" for i, phone in enumerate(phones))
    entities = [
        _make_entity("PHONE", text, text.index(phone), text.index(phone) + len(phone))
        for phone in phones
    ]
    registry = EntityRegistry(entities=entities, fp_count=len(entities), tb_count=0)

    scanned = []
    real_ranges = anon_mod.pseudonym_ranges

    def counting_ranges(scan_text, pseudonyms):
        scanned.append(len(scan_text))
        return real_ranges(scan_text, pseudonyms)

    monkeypatch.setattr(anon_mod, "pseudonym_ranges", counting_ranges)
    result = anonymize(text, registry, SessionVault(), salt=SALT, mode="token")

    assert all(phone not in result.text for phone in phones)
    assert len(scanned) <= 3, (
        f"{len(scanned)} whole-document passes ({sum(scanned)} chars) for "
        f"{len(entities)} entities — the scan still re-derives every pseudonym "
        f"range once per entity"
    )


def test_reuse_check_folds_the_document_once(monkeypatch):
    """Reusing a prior pseudonym asks whether the candidate already occurs in
    the source, and that check folded the WHOLE document once per entity. A
    long paste that repeats one value folded it hundreds of times."""
    import pii_redactor.anonymizer.anonymizer as anon_mod

    phone = "081-234-5678"
    text = "\n".join(f"ผู้ติดต่อรายที่ {i} หมายเลขโทรศัพท์ {phone}" for i in range(40))
    entities = [
        _make_entity("PHONE", text, start, start + len(phone))
        for start in anon_mod._find_all(text, phone)
    ]
    registry = EntityRegistry(entities=entities, fp_count=len(entities), tb_count=0)

    folded = []
    real_compact = anon_mod._compact_identity

    def counting_compact(value):
        folded.append(len(value))
        return real_compact(value)

    monkeypatch.setattr(anon_mod, "_compact_identity", counting_compact)
    result = anonymize(text, registry, SessionVault(), salt=SALT, mode="token")

    assert phone not in result.text
    assert sum(folded) <= 3 * len(text), (
        f"folded {sum(folded)} chars for a {len(text)}-char text with "
        f"{len(entities)} entities — the whole document is still folded per entity"
    )


def test_consistency_scan_still_replaces_an_untagged_repeat():
    """The scan's actual job: a value the detector tagged once but that occurs
    twice must be replaced at both occurrences, not just the tagged span."""
    text = "โทร 081-234-5678 หรือ 081-234-5678"
    start = text.index("081")
    entity = _make_entity("PHONE", text, start, start + len("081-234-5678"))
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)

    result = anonymize(text, registry, SessionVault(), salt=SALT)

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
        suffix = "หนึ่ง" if original == "สมชาย ใจดี" else "สอง"
        return f"คนละคน{attempt}-{suffix}"

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
        suffix = "หนึ่ง" if original == "สมชาย ใจดี" else "สอง"
        return f"ปลอม{attempt}-{suffix}"

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

    namespace = "a" * 25
    nonce = "n" * 20
    assert generate_token("NAME", 1, namespace=namespace, nonce=nonce) == (
        f"[ชื่อ_{namespace}_{nonce}_1]"
    )
    assert generate_token("PHONE", 3, namespace=namespace, nonce=nonce) == (
        f"[โทรศัพท์_{namespace}_{nonce}_3]"
    )


def test_generate_token_unknown_type_falls_back_to_type_name():
    from pii_redactor.anonymizer.token_generator import generate_token

    namespace = "a" * 25
    nonce = "n" * 20
    assert generate_token("MYSTERY", 2, namespace=namespace, nonce=nonce) == (
        f"[MYSTERY_{namespace}_{nonce}_2]"
    )


@pytest.mark.parametrize(
    ("namespace", "nonce", "ordinal"),
    [
        ("too-short", "n" * 20, 1),
        ("a" * 24 + "g", "n" * 20, 1),
        ("A" * 25, "n" * 20, 1),
        ("a" * 25, "too-short", 1),
        ("a" * 25, "n" * 19 + "0", 1),
        ("a" * 25, "n" * 20, 0),
        ("a" * 25, "n" * 20, -1),
    ],
)
def test_generate_token_rejects_non_product_identity(namespace, nonce, ordinal):
    from pii_redactor.anonymizer.token_generator import generate_token

    with pytest.raises(ValueError, match="invalid token"):
        generate_token("NAME", ordinal, namespace=namespace, nonce=nonce)


@pytest.mark.parametrize(
    "candidate",
    [
        f"[อีเมล_extra_{'a' * 25}_{'n' * 20}_1]",
        f"[อีเมล_[extra]_{'a' * 25}_{'n' * 20}_1]",
        f"[อีเมล\n_{'a' * 25}_{'n' * 20}_1]",
        f"[อีเมล_{'a' * 25}_1]",
        f"[ชื่อ_{'a' * 25}_{'n' * 20}_1]",
    ],
)
def test_token_shape_requires_exact_label_namespace_nonce_and_ordinal(candidate):
    from pii_redactor.anonymizer.token_generator import is_token_for_data_type

    assert not is_token_for_data_type(candidate, "EMAIL")


def test_legacy_token_shape_is_readable_only_when_explicitly_allowed():
    from pii_redactor.anonymizer.token_generator import (
        is_token_for_data_type,
        token_ordinal_from_candidate,
    )

    assert not is_token_for_data_type("[อีเมล_1]", "EMAIL")
    assert is_token_for_data_type("[อีเมล_1]", "EMAIL", allow_legacy=True)
    oversized = f"[อีเมล_{'9' * 5000}]"
    assert not is_token_for_data_type(oversized, "EMAIL", allow_legacy=True)
    assert token_ordinal_from_candidate(oversized, "EMAIL", allow_legacy=True) is None


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
    namespace = vault.token_namespace
    assert "a@b.co" not in result.text and "c@d.co" not in result.text
    # same original -> same token
    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p3 = vault.get_by_entity_id(e3.entity_id).pseudonym
    assert p1 == p3
    # distinct originals -> distinct ordinals
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p1.startswith(f"[อีเมล_{namespace}_") and p1.endswith("_1]")
    assert p2.startswith(f"[อีเมล_{namespace}_") and p2.endswith("_2]")
    assert p1 in result.text and p2 in result.text
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
    token = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert token.startswith(f"[อีเมล_{vault.token_namespace}_")
    assert token.endswith("_2]")
    assert token in r2.text


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
    token = vault.get_by_entity_id(e1.entity_id).pseudonym
    assert token.endswith("_1]")
    assert token in r1.text and token in r2.text


def test_token_mode_same_ordinal_is_namespaced_per_vault(monkeypatch):
    import pii_redactor.anonymizer.anonymizer as anonymizer_mod
    import pii_redactor.session_vault as vault_mod

    namespaces = iter(("a" * 25, "f" * 25))
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: next(namespaces))
    monkeypatch.setattr(anonymizer_mod, "new_token_nonce", lambda: "n" * 20)
    first_vault = SessionVault()
    second_vault = SessionVault()
    text = "email a@b.co"
    entity = _make_entity("EMAIL", text, 6, 12)
    registry = EntityRegistry(entities=[entity], fp_count=1, tb_count=0)

    first = anonymize(text, registry, first_vault, salt=SALT, mode="token")
    second = anonymize(text, registry, second_vault, salt=SALT, mode="token")

    assert first.text == f"email [อีเมล_{'a' * 25}_{'n' * 20}_1]"
    assert second.text == f"email [อีเมล_{'f' * 25}_{'n' * 20}_1]"
    assert first.text != second.text


def test_token_mode_retries_when_nonce_identity_already_occurs_in_source(monkeypatch):
    import pii_redactor.anonymizer.anonymizer as anonymizer_mod
    from pii_redactor.anonymizer.token_generator import generate_token

    namespace = "a" * 25
    nonces = iter(("n" * 20, "m" * 20))
    monkeypatch.setattr(anonymizer_mod, "new_token_nonce", lambda: next(nonces))
    collision = generate_token("EMAIL", 1, namespace=namespace, nonce="n" * 20)
    text = f"email a@b.co keep {collision}"
    entity = _make_entity("EMAIL", text, 6, 12)
    vault = SessionVault(token_namespace=namespace)

    result = anonymize(
        text,
        EntityRegistry(entities=[entity], fp_count=1, tb_count=0),
        vault,
        salt=SALT,
        mode="token",
    )

    minted = vault.get_by_entity_id(entity.entity_id).pseudonym
    assert minted == generate_token("EMAIL", 1, namespace=namespace, nonce="m" * 20)
    assert minted in result.text
    assert collision in result.text


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
