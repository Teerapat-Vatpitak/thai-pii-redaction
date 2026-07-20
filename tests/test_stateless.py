"""The platform contract: sanitize holds nothing between calls."""

import pytest

from pii_redactor.stateless import StatelessSanitizeResult, sanitize_stateless

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


def test_repeated_calls_with_the_same_input_are_reproducible():
    """Two calls with the same salt must not need shared state to agree."""
    a = sanitize_stateless(TEXT, mode="token", salt="s")
    b = sanitize_stateless(TEXT, mode="token", salt="s")
    assert a.sanitized_text == b.sanitized_text
    assert a.mapping == b.mapping


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

    assert second.mapping == {"[ชื่อ_1]": "นายสมชาย ใจเย็น"}
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


def test_prior_mapping_reuses_the_surrogate_across_turns():
    name = "นายวิทยา สมบูรณ์"
    first = sanitize_stateless(TEXT, mode="surrogate", salt="s")
    surrogate = next(p for p, original in first.mapping.items() if original == name)

    second = sanitize_stateless(
        f"แจ้ง {name} อีกครั้ง", mode="surrogate", salt="s", prior_mapping=first.mapping
    )
    assert surrogate in second.sanitized_text
    assert [p for p, original in second.mapping.items() if original == name] == [surrogate]


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
