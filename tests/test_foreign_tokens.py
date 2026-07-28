"""Foreign-token detector: bracket tokens the model returned that we never sent.

Alert-only, count-only (VAULT-4: a bracket candidate can contain anything).
Accepted false positives, per spec: bare [ref_1], arr[i_1]. Real negative
controls are shapes that do not parse: [ref], [1], [x_01], arr[i].
"""

import re

import pytest

from pii_redactor.reverse_mapper import count_foreign_tokens
from pii_redactor.stateless import restore_stateless

_BRACKET_TOKEN = re.compile(r"\[[^\[\]\r\n]{1,64}\]")

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


class TestSessionReidentifyForeignTokens:
    """The blocklist filter at the reidentify site (session_service.py
    _restore_locked) must let foreign_tokens through to /api/reidentify's
    warnings[] -- this is the extension-facing surface. If that filter were
    ever flipped from blocklist to allowlist, every FlagFlow test above
    (which exercises restore_stateless directly) would stay green while this
    warning silently stopped reaching the caller.
    """

    @pytest.fixture()
    def client(self):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from app.server import app

        return TestClient(app, base_url="http://localhost")

    def test_foreign_token_warning_survives_session_reidentify(self, client):
        sanitize_resp = client.post(
            "/api/sanitize",
            json={"text": "ผมชื่อ นายสมชาย ใจดี โทร 081-234-5678", "mode": "token"},
        )
        assert sanitize_resp.status_code == 200
        sanitize_out = sanitize_resp.json()
        session_id = sanitize_out["session_id"]

        real_tokens = _BRACKET_TOKEN.findall(sanitize_out["sanitized_text"])
        assert real_tokens, "sanitize did not mint any bracket token to test against"
        real_token = real_tokens[0]

        reply_text = f"{real_token} และ [Name_99]"
        reidentify_resp = client.post(
            "/api/reidentify",
            json={"session_id": session_id, "text": reply_text},
        )
        assert reidentify_resp.status_code == 200
        reidentify_out = reidentify_resp.json()

        warnings = reidentify_out["warnings"]
        assert sum(1 for w in warnings if re.fullmatch(r"foreign_tokens:1", w)) == 1
        assert real_token not in reidentify_out["restored_text"]
