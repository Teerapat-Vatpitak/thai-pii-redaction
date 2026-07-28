"""One provider registry, consumed by every surface (spec: no copied lists)."""

import re
from pathlib import Path

import pytest

from pii_redactor.ai_client import PROVIDER_FACTORIES, get_provider_factories

EXPECTED = {"fake", "pathumma", "tokenmind", "ollama", "claude"}


class TestCanonicalRegistry:
    def test_tokenmind_is_registered_by_name(self):
        # Asserted by NAME, not set-equality: equality alone passes when the
        # provider is forgotten everywhere at once (the likeliest mistake).
        assert "tokenmind" in PROVIDER_FACTORIES

    def test_full_registry(self):
        assert set(PROVIDER_FACTORIES) == EXPECTED

    def test_registry_is_immutable(self):
        with pytest.raises(TypeError):
            PROVIDER_FACTORIES["evil"] = object  # type: ignore[index]

    def test_filter_returns_subset(self):
        assert set(get_provider_factories(allowed=["fake", "tokenmind"])) == {
            "fake",
            "tokenmind",
        }

    def test_filter_fails_loud_on_unknown_name(self):
        with pytest.raises(ValueError, match="typo_provider"):
            get_provider_factories(allowed=["fake", "typo_provider"])


class TestSurfaceRegistries:
    def test_worker_surface_has_tokenmind(self):
        from app.worker import handler

        assert "tokenmind" in handler._PROVIDER_FACTORIES
        assert set(handler._PROVIDER_FACTORIES) == EXPECTED

    def test_server_surface_has_tokenmind(self):
        pytest.importorskip("fastapi")
        from app import server

        assert "tokenmind" in server._PROVIDER_FACTORIES
        assert set(server._PROVIDER_FACTORIES) == EXPECTED


class TestPlaygroundDropdown:
    def _options(self):
        html = (Path(__file__).parent.parent / "demo" / "playground.html").read_text(
            encoding="utf-8"
        )
        select = re.search(r'<select id="provider">(.*?)</select>', html, re.DOTALL)
        assert select, "provider dropdown missing"
        return re.findall(r'<option value="([^"]+)"', select.group(1))

    def test_playground_offers_tokenmind(self):
        assert "tokenmind" in self._options()

    def test_playground_options_match_registry(self):
        assert set(self._options()) == EXPECTED
