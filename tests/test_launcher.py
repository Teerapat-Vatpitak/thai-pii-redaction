import launcher


def test_headless_sidecar_flag_disables_browser_open(monkeypatch):
    monkeypatch.setenv("AIGUARD_NO_BROWSER", "1")

    assert launcher._browser_open_enabled() is False


def test_browser_open_remains_enabled_without_headless_flag(monkeypatch):
    monkeypatch.delenv("AIGUARD_NO_BROWSER", raising=False)

    assert launcher._browser_open_enabled() is True
