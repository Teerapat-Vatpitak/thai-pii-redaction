"""Hosted HTTP adapter with an explicit public route allowlist."""

from __future__ import annotations

import os


def _require_setting(name: str) -> None:
    if not os.environ.get(name, "").strip():
        raise RuntimeError(f"{name} must be configured for the hosted adapter")


_require_setting("AIGUARD_API_KEY")
_provider_policy = [
    item.strip() for item in os.environ.get("AIGUARD_PROVIDERS", "").split(",") if item.strip()
]
if not _provider_policy:
    raise RuntimeError("AIGUARD_PROVIDERS must select at least one hosted provider")

from app.server import app  # noqa: E402

_HOSTED_PATHS = frozenset(
    {
        "/api/health",
        "/api/detect",
        "/api/analyze",
        "/api/guard",
        "/api/sanitize",
        "/api/reidentify",
        "/api/roundtrip",
    }
)

app.router.routes[:] = [
    route for route in app.router.routes if getattr(route, "path", None) in _HOSTED_PATHS
]
app.state.session_disposal_enabled = False
