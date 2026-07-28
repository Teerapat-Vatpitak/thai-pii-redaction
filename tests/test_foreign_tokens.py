"""Foreign-token detector: bracket tokens the model returned that we never sent.

Alert-only, count-only (VAULT-4: a bracket candidate can contain anything).
Accepted false positives, per spec: bare [ref_1], arr[i_1]. Real negative
controls are shapes that do not parse: [ref], [1], [x_01], arr[i].
"""

import pytest

from pii_redactor.reverse_mapper import count_foreign_tokens
from pii_redactor.stateless import restore_stateless

SENT = ["[ชื่อ_1]", "[โทรศัพท์_1]"]


class TestCountForeignTokens:
    def test_translated_token_is_foreign(self):
        assert count_foreign_tokens("สวัสดี [Name_1] ครับ", SENT) == 1

    def test_sent_tokens_are_not_foreign(self):
        assert count_foreign_tokens("ติดต่อ [ชื่อ_1] ที่ [โทรศัพท์_1]", SENT) == 0

    def test_occurrences_counted_not_distinct(self):
        assert count_foreign_tokens("[Name_1] และ [Name_1] กับ [Email_2]", SENT) == 3

    def test_accepted_false_positives_do_flag(self):
        # recall > precision: suppressing markdown/code context would also hide
        # a translated token embedded in a link -- so these DO count.
        assert count_foreign_tokens("ดูที่ [ref_1] และ arr[i_1]", SENT) == 2

    @pytest.mark.parametrize(
        "text",
        ["[ref]", "[1]", "[x_01]", "arr[i]", "[_1]", "[ชื่อ_๑]", "ไม่มีวงเล็บเลย"],
        ids=[
            "no-ordinal",
            "no-underscore",
            "leading-zero",
            "no-ordinal-code",
            "empty-label",
            "thai-digit-ordinal",
            "plain",
        ],
    )
    def test_non_candidates_do_not_flag(self, text):
        assert count_foreign_tokens(text, SENT) == 0

    def test_inactive_when_mapping_empty(self):
        assert count_foreign_tokens("[Name_1]", []) == 0

    def test_inactive_when_no_sent_pseudonym_is_bracket_shaped(self):
        # surrogate mode: pseudonyms are bare fake values -> detector off
        assert count_foreign_tokens("[Name_1]", ["สมหญิง ดีมาก", "0812345678"]) == 0

    def test_candidate_across_newline_not_matched(self):
        assert count_foreign_tokens("[ชื่อ\n_1]", SENT) == 0


class TestFlagFlow:
    def test_restore_stateless_carries_foreign_tokens_warning(self):
        mapping = {"[ชื่อ_1]": "สมชาย ใจดี"}
        out = restore_stateless("สวัสดี [ชื่อ_1] และ [Name_2]", mapping=mapping)
        assert any(w == "foreign_tokens:1" for w in out.warnings)
        assert out.restored_text == "สวัสดี สมชาย ใจดี และ [Name_2]"

    def test_no_flag_when_clean(self):
        mapping = {"[ชื่อ_1]": "สมชาย ใจดี"}
        out = restore_stateless("สวัสดี [ชื่อ_1]", mapping=mapping)
        assert not any(w.startswith("foreign_tokens:") for w in out.warnings)

    def test_flag_not_filtered_by_session_service_noisy_prefixes(self):
        from pii_redactor.session_service import _NOISY_PREFIXES

        assert not "foreign_tokens:9".startswith(_NOISY_PREFIXES)
