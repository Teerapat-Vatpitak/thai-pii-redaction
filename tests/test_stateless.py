"""Stateless-core and transient-mapping contract tests."""

from dataclasses import asdict

import pytest

from pii_redactor.scan_common import canonical_value
from pii_redactor.stateless import (
    StatelessLeakError,
    StatelessSanitizeResult,
    restore_stateless,
    sanitize_stateless,
)

TEXT = "ผมชื่อ นายวิทยา สมบูรณ์ โทร 081-234-5678"
# Two names so the person checked below does NOT hold the ordinal a fresh
# vault would hand a lone name -- see the prior_mapping tests further down.
TEXT_TWO_NAMES = "ผมชื่อ นายวิทยา สมบูรณ์ และเพื่อนชื่อ นางสาวมาลี ดีใจ โทร 081-234-5678"


def test_returns_mapping_to_the_caller():
    out = sanitize_stateless(TEXT, mode="token", salt="s")
    assert isinstance(out, StatelessSanitizeResult)
    assert out.mapping, "mapping must be returned, not retained"
    for pseudonym, original in out.mapping.items():
        assert pseudonym in out.sanitized_text
        assert original in TEXT


def test_no_original_pii_survives_in_the_output():
    out = sanitize_stateless(TEXT, mode="token", salt="s")
    assert "081-234-5678" not in out.sanitized_text
    assert "วิทยา" not in out.sanitized_text


def test_repeated_token_calls_use_distinct_generation_namespaces(monkeypatch):
    """Independent token calls must not mint the same token identity."""
    import pii_redactor.session_vault as vault_mod

    namespaces = iter(("a" * 25, "f" * 25))
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: next(namespaces))
    a = sanitize_stateless(TEXT, mode="token", salt="s")
    b = sanitize_stateless(TEXT, mode="token", salt="s")
    assert a.sanitized_text != b.sanitized_text
    assert set(a.mapping.values()) == set(b.mapping.values())
    assert set(a.mapping).isdisjoint(b.mapping)


def test_a_call_leaves_no_trace_for_the_next_call():
    """Isolation -- distinct from reproducibility above.

    Calling with identical text twice (the test above) would pass even if a
    vault were retained across calls: call 2 would just reuse call 1's tokens
    and produce an identical result either way. To actually detect retained
    state, call 2 must use different text naming a different person: a lone
    name with no shared history must still get ordinal 1, and call 1's
    original must not surface anywhere in call 2's mapping.
    """
    first = sanitize_stateless(TEXT, mode="token", salt="s")

    second = sanitize_stateless("ผมชื่อ นายสมชาย ใจเย็น", mode="token", salt="s")

    assert list(second.mapping.values()) == ["นายสมชาย ใจเย็น"]
    assert next(iter(second.mapping)).endswith("_1]")
    assert not set(first.mapping.values()) & set(second.mapping.values())


def test_prior_mapping_keeps_tokens_stable_across_turns():
    """Multi-turn consistency without server state: the caller passes the map back.

    Turn 1 names two people, so the person checked here holds `[ชื่อ_2]`, not
    the `[ชื่อ_1]` a fresh vault would mint for a lone name in turn 2 -- a
    single-name turn-1 fixture would make this pass even if prior_mapping
    were silently dropped, since the fresh-vault ordinal and the stable
    token would coincide.
    """
    name = "นายวิทยา สมบูรณ์"
    first = sanitize_stateless(TEXT_TWO_NAMES, mode="token", salt="s")
    token = next(p for p, original in first.mapping.items() if original == name)

    second = sanitize_stateless(
        f"แจ้ง {name} อีกครั้ง", mode="token", salt="s", prior_mapping=first.mapping
    )
    assert second.mapping.get(token) == name, (
        "the same person must reuse the same token across turns"
    )
    assert token in second.sanitized_text


def test_prior_mapping_reuses_the_token_rather_than_minting_a_second_one():
    """Stronger than the test above, which a mere echo of prior_mapping passes.

    A re-admitted pair must satisfy the anonymizer's reuse lookup, otherwise
    the same person is issued a fresh token every turn and the caller-held
    mapping grows a second entry pointing at them. Turn 1 again uses the
    two-name fixture (see above) so this person's token is the non-default
    `[ชื่อ_2]`, not the ordinal a fresh vault would hand out on its own.
    """
    name = "นายวิทยา สมบูรณ์"
    first = sanitize_stateless(TEXT_TWO_NAMES, mode="token", salt="s")
    token = next(p for p, original in first.mapping.items() if original == name)

    second = sanitize_stateless(
        f"แจ้ง {name} อีกครั้ง", mode="token", salt="s", prior_mapping=first.mapping
    )
    assert token in second.sanitized_text
    assert [p for p, original in second.mapping.items() if original == name] == [token]


def test_prior_mapping_keeps_one_namespace_for_new_tokens(monkeypatch):
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import token_namespace_from_candidate

    namespaces = iter(("a" * 25, "f" * 25))
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: next(namespaces))
    first = sanitize_stateless("โทร 081-234-5678", mode="token", salt="s")
    first_token = next(iter(first.mapping))
    assert token_namespace_from_candidate(first_token) == "a" * 25

    second = sanitize_stateless(
        "โทร 081-234-5678 อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping=first.mapping,
    )

    assert first_token in second.mapping
    assert {token_namespace_from_candidate(pseudonym) for pseudonym in second.mapping} == {"a" * 25}


def test_prior_mapping_keeps_namespace_when_next_turn_contains_only_new_pii(monkeypatch):
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import token_namespace_from_candidate

    namespaces = iter(("a" * 25, "f" * 25))
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: next(namespaces))
    first = sanitize_stateless("โทร 081-234-5678", mode="token", salt="s")

    second = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping=first.mapping,
    )

    assert {token_namespace_from_candidate(pseudonym) for pseudonym in second.mapping} == {"a" * 25}


def test_prior_mapping_continues_same_type_ordinal_for_new_value():
    first = sanitize_stateless("อีเมล a@b.co", mode="token", salt="s")

    second = sanitize_stateless(
        "อีเมล c@d.co",
        mode="token",
        salt="s",
        prior_mapping=first.mapping,
    )

    new_token = next(
        pseudonym for pseudonym, original in second.mapping.items() if original == "c@d.co"
    )
    assert new_token.endswith("_2]")


def test_ambiguous_prior_namespaces_do_not_select_either_chain(monkeypatch):
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import (
        generate_token,
        token_namespace_from_candidate,
    )

    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: "a" * 25)
    prior_mapping = {
        generate_token("PHONE", 1, namespace="e" * 25, nonce="n" * 20): "081-234-5678",
        generate_token("EMAIL", 1, namespace="f" * 25, nonce="m" * 20): "a@b.co",
    }

    result = sanitize_stateless(
        "อีเมล c@d.co",
        mode="token",
        salt="s",
        prior_mapping=prior_mapping,
    )

    new_token = next(
        pseudonym for pseudonym, original in result.mapping.items() if original == "c@d.co"
    )
    assert token_namespace_from_candidate(new_token) == "a" * 25
    assert new_token.endswith("_2]")


def test_prior_mapping_reuses_valid_namespaced_token(monkeypatch):
    import pii_redactor.session_vault as vault_mod

    namespaces = iter(("a" * 25, "f" * 25))
    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: next(namespaces))
    first = sanitize_stateless("อีเมล a@b.co", mode="token", salt="s")
    first_token = next(iter(first.mapping))

    second = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping=first.mapping,
    )

    assert list(second.mapping) == [first_token]
    assert first_token in second.sanitized_text


def test_caller_token_shape_cannot_launder_residual_pii():
    malicious_token = "[อีเมล_1101700230708abc_1]"

    result = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping={malicious_token: "a@b.co"},
    )

    assert malicious_token not in result.sanitized_text
    assert "a@b.co" not in result.sanitized_text
    replacement = next(
        pseudonym
        for pseudonym, original in result.mapping.items()
        if original == "a@b.co" and pseudonym != malicious_token
    )
    assert replacement in result.sanitized_text


@pytest.mark.parametrize(
    "malicious_token",
    [
        f"[อีเมล_extra_{'f' * 25}_{'n' * 20}_1]",
        f"[อีเมล_[extra]_{'f' * 25}_{'n' * 20}_1]",
        f"[อีเมล\n_{'f' * 25}_{'n' * 20}_1]",
    ],
)
def test_malformed_token_seed_is_not_reused_or_allowed_to_select_namespace(
    monkeypatch,
    malicious_token,
):
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import token_namespace_from_candidate

    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: "a" * 25)

    result = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping={malicious_token: "a@b.co"},
    )

    replacement = next(
        pseudonym
        for pseudonym, original in result.mapping.items()
        if original == "a@b.co" and pseudonym != malicious_token
    )
    assert malicious_token not in result.sanitized_text
    assert replacement in result.sanitized_text
    assert token_namespace_from_candidate(replacement) == "a" * 25


def test_residual_bearing_token_seed_cannot_select_namespace(monkeypatch):
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import token_namespace_from_candidate

    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: "a" * 25)
    malicious_token = f"[อีเมล_{'f' * 25}_{'n' * 20}_1101700207031]"

    result = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping={malicious_token: "a@b.co"},
    )

    replacement = next(
        pseudonym
        for pseudonym, original in result.mapping.items()
        if original == "a@b.co" and pseudonym != malicious_token
    )
    assert malicious_token not in result.sanitized_text
    assert token_namespace_from_candidate(replacement) == "a" * 25


def test_wrong_label_token_seed_cannot_select_namespace(monkeypatch):
    import pii_redactor.session_vault as vault_mod
    from pii_redactor.anonymizer.token_generator import (
        generate_token,
        token_namespace_from_candidate,
    )

    monkeypatch.setattr(vault_mod, "new_token_namespace", lambda: "a" * 25)
    wrong_label = generate_token(
        "PHONE",
        1,
        namespace="f" * 25,
        nonce="n" * 20,
    )

    result = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping={wrong_label: "a@b.co"},
    )

    replacement = next(
        pseudonym
        for pseudonym, original in result.mapping.items()
        if original == "a@b.co" and pseudonym != wrong_label
    )
    assert wrong_label not in result.sanitized_text
    assert token_namespace_from_candidate(replacement) == "a" * 25


def test_valid_same_type_seed_is_reused_after_wrong_label_seed_for_same_original():
    from pii_redactor.anonymizer.token_generator import generate_token

    wrong_label = generate_token(
        "PHONE",
        1,
        namespace="f" * 25,
        nonce="n" * 20,
    )
    valid = generate_token(
        "EMAIL",
        1,
        namespace="a" * 25,
        nonce="m" * 20,
    )

    result = sanitize_stateless(
        "อีเมล a@b.co",
        mode="token",
        salt="s",
        prior_mapping={
            wrong_label: "a@b.co",
            valid: "a@b.co",
        },
    )

    assert valid in result.sanitized_text
    assert wrong_label not in result.sanitized_text
    assert [
        pseudonym for pseudonym, original in result.mapping.items() if original == "a@b.co"
    ] == [wrong_label, valid]


def test_prior_mapping_reuses_the_surrogate_across_turns():
    """Forces a real pin, not a vacuous one.

    The surrogate generator's random draw is a pure function of its seed
    inputs (data type, salt, original, and attempt); the TB name cue/shape also
    comes from the supplied context. `tb_generator._seeded_rng` takes no
    vault/call-order input (see tb_generator.py:171-179). So whenever turn 1's
    value came from attempt=0, a from-scratch regeneration in turn 2
    reproduces it exactly, with or without prior_mapping -- a test built on
    an attempt=0 fixture would pass either way.

    To make prior_mapping load-bearing, turn 1's surrogate must NOT come from
    attempt=0. `bait` is the attempt=0 draw for `name` under salt "s" and
    TEXT (verified by running _generate_pseudonym directly); seeding it in
    the vault under an unrelated decoy original makes
    _generate_unique_pseudonym's owner check reject attempt 0.  Attempt 1
    ("วิทยา") is rejected too, but for a different reason: it is a literal
    substring of "นายวิทยา" already present in TEXT, so the source-text
    check rejects it. The real surrogate only settles at attempt 2. A fresh
    regeneration with no decoy in the vault has nothing to collide with, so
    it lands back on the plain attempt=0 value -- a different string, which
    is exactly what `assert surrogate != bait` below would also catch if the
    fixture's premise ever stopped holding.
    """
    name = "นายวิทยา สมบูรณ์"
    bait = "อนุชา"
    decoy_original = "คนอื่น ไม่เกี่ยว"

    first = sanitize_stateless(
        TEXT, mode="surrogate", salt="s", prior_mapping={bait: decoy_original}
    )
    surrogate = next(p for p, original in first.mapping.items() if original == name)
    assert surrogate != bait, "fixture must force a reroll -- otherwise this test is vacuous"

    second = sanitize_stateless(
        f"แจ้ง {name} อีกครั้ง", mode="surrogate", salt="s", prior_mapping=first.mapping
    )
    assert surrogate in second.sanitized_text
    assert [p for p, original in second.mapping.items() if original == name] == [surrogate]


@pytest.mark.parametrize("mode", ["token", "surrogate"])
def test_numeric_prior_mapping_is_regenerated_instead_of_promoted(mode):
    """A caller-supplied residual-looking value cannot become trusted by reuse."""
    prior = {"6801234": "12345678"}
    out = sanitize_stateless(
        "รหัสอ้างอิง 12345678",
        mode=mode,
        salt="s",
        prior_mapping=prior,
    )

    assert "6801234" not in out.sanitized_text
    assert "6801234" not in out.guard_context.trusted_pseudonyms()


@pytest.mark.parametrize("mode", ["token", "surrogate"])
@pytest.mark.parametrize(
    "candidate",
    [
        "1101700230708",
        "081-234-5678",
        "other.person@example.invalid",
        "นายทดสอบ บุคคลตัวอย่าง",
    ],
)
def test_cross_type_prior_mapping_cannot_promote_detected_pii(mode, candidate):
    original = "test.user@example.com"
    out = sanitize_stateless(
        original,
        mode=mode,
        salt="s",
        prior_mapping={candidate: original},
    )

    assert candidate not in out.sanitized_text
    assert candidate not in out.guard_context.trusted_pseudonyms()


@pytest.mark.parametrize("mode", ["token", "surrogate"])
def test_reused_numeric_mapping_cannot_authorize_an_untouched_duplicate(mode):
    """Trusting one replacement must not excuse the same digits elsewhere."""
    with pytest.raises(StatelessLeakError) as excinfo:
        sanitize_stateless(
            "รหัสอ้างอิง 12345678 และค่าที่เหลือ 6801234",
            mode=mode,
            salt="s",
            prior_mapping={"6801234": "12345678"},
        )

    assert excinfo.value.leak_types == ["ORPHAN_DIGITS"]


@pytest.mark.parametrize("mode", ["token", "surrogate"])
@pytest.mark.parametrize(
    "pseudonym",
    [
        "1101700230708",
        "[MASK-1101700230708]",
    ],
)
def test_prior_mapping_cannot_reuse_identity_or_embedded_original(mode, pseudonym):
    """A caller mapping cannot turn the original into trusted output."""
    original = "1101700230708"

    out = sanitize_stateless(
        original,
        mode=mode,
        salt="s",
        prior_mapping={pseudonym: original},
    )

    assert original not in out.sanitized_text
    assert all(entity["token"] for entity in out.entities)


@pytest.mark.parametrize("mode", ["token", "surrogate"])
@pytest.mark.parametrize(
    ("data_type", "pseudonym", "original"),
    [
        ("THAI_ID", "1101700230708", "1-1017-00230-70-8"),
        ("PHONE", "0812345678", "081-234-5678"),
        ("EMAIL", "synthetic@example.com", "Synthetic@Example.com"),
    ],
)
def test_prior_mapping_cannot_reuse_canonical_original_variant(
    mode,
    data_type,
    pseudonym,
    original,
):
    """Formatting and case changes do not make an original a pseudonym."""
    out = sanitize_stateless(
        original,
        mode=mode,
        salt="s",
        prior_mapping={pseudonym: original},
    )

    canonical_original = canonical_value(data_type, original)
    canonical_output = canonical_value(data_type, out.sanitized_text)
    assert canonical_original not in canonical_output
    assert all(entity["token"] for entity in out.entities)


@pytest.mark.parametrize("mode", ["token", "surrogate"])
def test_empty_seed_is_not_used_as_a_replacement(mode):
    """An empty caller key cannot delete an entity into an unrestorable result."""
    original = "1101700230708"

    out = sanitize_stateless(
        original,
        mode=mode,
        salt="s",
        prior_mapping={"": original},
    )

    assert out.sanitized_text
    assert original not in out.sanitized_text
    assert all(entity["token"] for entity in out.entities)
    restored = restore_stateless(out.sanitized_text, mapping=out.mapping)
    assert restored.restored_text == original


def test_provider_guard_context_is_internal_original_free_and_repr_hidden():
    out = sanitize_stateless(TEXT, mode="token", salt="s")
    context = out.guard_context

    assert "guard_context" not in asdict(out)
    assert set(context.trusted_pseudonyms()) == {entity["token"] for entity in out.entities}
    assert all(token not in repr(context) for token in out.mapping)
    assert all(original not in repr(context) for original in out.mapping.values())


def test_a_prior_mapping_token_owned_by_someone_else_is_not_handed_out_again():
    """A replayed mapping must never make one token mean two different people.

    Repointing is impossible to express inside a single prior_mapping (dict
    keys are unique), so the reachable risk is the opposite one: a token the
    caller claims belongs to A must not be issued to B. B gets a fresh token
    and A's entry is left intact — pinned here because a restore driven by
    this mapping would otherwise name the wrong person.
    """
    out = sanitize_stateless(TEXT, mode="token", salt="s", prior_mapping={"[ชื่อ_1]": "คนอื่น ไม่เกี่ยว"})
    assert out.mapping["[ชื่อ_1]"] == "คนอื่น ไม่เกี่ยว"
    assert "[ชื่อ_1]" not in out.sanitized_text
    assert len(set(out.mapping.values())) == len(out.mapping), "one token, one person"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        sanitize_stateless(TEXT, mode="nonsense", salt="s")


def test_restore_closes_the_round_trip_without_server_state():
    """The in-process/legacy worker-v1 primitive closes a stateless roundtrip.

    Hosted roundtrip consumes this transient mapping internally; the accepted
    HTTP v2 wire does not export it. This direct helper accepts a caller-held
    mapping for legacy compatibility and retains no process-global vault or
    mapping afterwards.
    """
    out = sanitize_stateless(TEXT, mode="token", salt="s")
    assert out.sanitized_text != TEXT

    back = restore_stateless(out.sanitized_text, mapping=out.mapping)

    assert back.restored_text == TEXT
    assert back.replaced_count == len(out.mapping)
    assert not back.leftover_pseudonyms


def test_restore_flags_a_duplicate_of_a_known_original_outside_restored_span():
    original = "081-234-5678"
    out = sanitize_stateless(f"เบอร์ {original}", mode="token", salt="s")

    back = restore_stateless(
        f"{out.sanitized_text} สำรอง {original}",
        mapping=out.mapping,
        mode="token",
    )

    assert back.restored_text.count(original) == 2
    assert back.generated_pii_count >= 1


def test_restore_reports_pseudonyms_it_could_not_account_for():
    """A model reply may drop or mangle a token; the caller has to learn that.

    Silence here would let a half-restored answer look complete, which is the
    same failure class as reporting a residual leak as clean on the way out.
    """
    out = sanitize_stateless(TEXT, mode="token", salt="s")
    reply_missing_a_token = "ตอบกลับโดยไม่มี token ใด ๆ เลย"

    back = restore_stateless(reply_missing_a_token, mapping=out.mapping)

    assert back.replaced_count == 0
    assert back.warnings, "a reply that used none of the tokens must not look complete"
