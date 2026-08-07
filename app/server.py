"""FastAPI server for the AI Guard Thai PII redaction pipeline.

Local API backend for the browser extension (extension/). The extension runs
on chatgpt.com / claude.ai and calls these endpoints on localhost.

AI Guard uses session-namespaced TOKEN-mode pseudonymization so the round-trip
through an external AI is robust and visually explicit. The token -> original
map is owned by `pii_redactor.session_service.SessionService` in backend
memory. HTTP contract v2 returns only strict, data-minimized projections.
"""

from __future__ import annotations

import atexit
import base64
import glob
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.access_logging import install_uvicorn_access_log_filter
from app.http_v2 import (
    CONTRACT_HEADER,
    CONTRACT_VERSION,
    ERROR_SPECS,
    RECOMMENDATION_TEMPLATES,
    AnalyzeReportResponse,
    AnalyzeResponse,
    AuditLogResponse,
    ContractError,
    DeleteSessionResponse,
    DetectResponse,
    GuardResponse,
    HealthResponse,
    RedactPdfResponse,
    ReidentifyRequest,
    ReidentifyResponse,
    RoundtripRequest,
    RoundtripResponse,
    SanitizeRequest,
    SanitizeResponse,
    ShutdownResponse,
    TextRequest,
    error_response,
    finite_nonnegative,
    validated_payload,
)
from app.session_control_auth import (
    make_session_disposal_authorization,
    verify_session_disposal_authorization,
)
from pii_redactor.ai_client import (
    DEFAULT_SYSTEM_PROMPT,
    ProviderCallError,
    complete_provider_with_retry_policy,
    get_provider_factories,
)
from pii_redactor.audit import write_process_log
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.ner_failure import NERFailureError, ner_failure_metadata
from pii_redactor.guard.injection import scan_injection
from pii_redactor.ingest.file_detector import detect_source_type
from pii_redactor.ingest.ocr_processor import OCRUnavailableError
from pii_redactor.ingest.quality_validator import OCR_CONFIDENCE_THRESHOLD
from pii_redactor.ingest.text_cleaner import clean, clean_length_preserving
from pii_redactor.ingest.text_extractor import extract
from pii_redactor.leak_guard import (
    OutboundPolicyError,
    enforce_outbound_policy,
    normalize_outbound_leak_types,
    scan_outbound_leaks,
    scan_residual_signals,
)
from pii_redactor.models import EntityRegistry
from pii_redactor.redactor import redact_pdf as redact_pdf_file
from pii_redactor.report import analyze_text, scan_section26
from pii_redactor.report_pdf import render_pdpa_report
from pii_redactor.safe_errors import discard_exception_graph
from pii_redactor.stateless import (
    StatelessLeakError,
    restore_stateless,
    sanitize_stateless,
)


def _contain_public_errors(func):
    """Sever failed endpoint frames before one fixed v2 error escapes."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        failure: tuple[str, int, str | None] = ("internal_error", 0, None)
        try:
            return func(*args, **kwargs)
        except ContractError as error:
            code = getattr(error, "code", "internal_error")
            count = getattr(error, "count", 0)
            ner_category = getattr(error, "ner_category", None)
            if code in ERROR_SPECS and type(count) is int and count >= 0:
                failure = (code, count, ner_category)
            discard_exception_graph(error)
        except NERFailureError as error:
            code, category, count = ner_failure_metadata(error)
            failure = (code, count, category)
            discard_exception_graph(error)
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            discard_exception_graph(error)

        args = ()
        kwargs = {}
        code, count, ner_category = failure
        failure = None
        raise ContractError(
            code,
            count=count,
            ner_category=ner_category,
        ) from None

    return wrapped


def _read_version() -> str:
    """Read the product version from the single-source `VERSION` file at repo
    root (Horizon-1 #5 — one file, everything else derives from it).

    Checked in order:
    1. Next to a PyInstaller-frozen executable (`sys._MEIPASS`) -- `VERSION` is
       bundled via `--add-data` in `scripts/build_sidecar.py`.
    2. Next to this source file, two levels up (`app/server.py` -> repo root)
       -- the dev / from-source / core-only-install path.

    Falls back to a hardcoded string if VERSION can't be found anywhere (e.g.
    an old frozen exe built before VERSION was added to PyInstaller datas).
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "VERSION")
    candidates.append(Path(__file__).resolve().parent.parent / "VERSION")

    for candidate in candidates:
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    # Last-resort fallback, outside the single-source system by design:
    # bump this literal at release time (scripts/bump_version.py does not).
    return "2.5.0"


__version__ = _read_version()

app = FastAPI(
    title="AI Guard API",
    description="Thai PII detection, anonymization, and redaction",
    version=__version__,
    redirect_slashes=False,
)
app.state.session_disposal_enabled = True


@app.exception_handler(ContractError)
async def contract_error_handler(_request: Request, error: ContractError):
    """Render only the closed error row selected by an endpoint."""
    code = getattr(error, "code", "internal_error")
    count = getattr(error, "count", 0)
    ner_category = getattr(error, "ner_category", None)
    if code not in ERROR_SPECS or type(count) is not int or count < 0:
        code, count, ner_category = "internal_error", 0, None
    discard_exception_graph(error)
    _request = None
    error = None
    return error_response(code, count=count, ner_category=ner_category)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request: Request, error: RequestValidationError):
    """Return a count-only schema error without echoing rejected values."""
    try:
        count = len(error.errors())
    except Exception as metadata_error:
        discard_exception_graph(metadata_error)
        count = 0
    discard_exception_graph(error)
    try:
        object.__setattr__(error, "body", None)
        object.__setattr__(error, "_errors", [])
        BaseException.__setattr__(error, "args", ())
    except BaseException:
        pass
    _request = None
    error = None
    return error_response("request_schema_invalid", count=count)


@app.exception_handler(StarletteHTTPException)
async def framework_http_error(_request: Request, error: StarletteHTTPException):
    """Translate route and method failures without returning framework detail."""
    code = (
        "route_not_found"
        if error.status_code == 404
        else "method_not_allowed"
        if error.status_code == 405
        else "invalid_request"
        if error.status_code == 400
        else "internal_error"
    )
    discard_exception_graph(error)
    _request = None
    error = None
    return error_response(code)


_DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
_ALLOWED_BROWSER_ORIGIN = re.compile(
    r"^(?:chrome-extension://[a-p]{32}|moz-extension://[0-9a-fA-F-]+|"
    r"tauri://localhost|https?://tauri\.localhost)$"
)
_CORS_METHODS = "GET, POST"
_CORS_HEADERS = "Content-Type, X-AIGuard-Contract-Version"


class _StrictCORSMiddleware:
    """Handle only the fixed v2 browser transport surface."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        install_uvicorn_access_log_filter()
        header_values: dict[str, list[str]] = {}
        for key, value in scope.get("headers", []):
            header_values.setdefault(key.decode("latin-1").lower(), []).append(
                value.decode("latin-1")
            )
        origins = header_values.get("origin", [])
        origin = origins[0] if len(origins) == 1 else None
        allowed_origin = bool(origin and _ALLOWED_BROWSER_ORIGIN.fullmatch(origin))
        path = (scope.get("path") or "/").rstrip("/") or "/"
        is_health_path = path == "/api/health"
        is_control_path = path == "/api/shutdown" or path.startswith("/api/session/")
        if origins and is_control_path and scope["method"] == "OPTIONS":
            await Response(status_code=400)(scope, receive, send)
            return
        requested_methods = header_values.get("access-control-request-method", [])
        requested_method = requested_methods[0] if len(requested_methods) == 1 else None
        if scope["method"] == "OPTIONS" and origin and requested_method:
            requested_header_rows = header_values.get("access-control-request-headers", [])
            requested_headers = {
                item.strip().lower()
                for item in (
                    requested_header_rows[0] if len(requested_header_rows) == 1 else ""
                ).split(",")
                if item.strip()
            }
            allowed = (
                allowed_origin
                and requested_method in {"GET", "POST"}
                and len(requested_header_rows) <= 1
                and requested_headers <= {"content-type", "x-aiguard-contract-version"}
            )
            response_headers = (
                {
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": _CORS_METHODS,
                    "Access-Control-Allow-Headers": _CORS_HEADERS,
                    "Access-Control-Expose-Headers": CONTRACT_HEADER,
                    "Vary": "Origin",
                }
                if allowed
                else {}
            )
            response = Response(
                status_code=200 if allowed else 400,
                headers=response_headers,
            )
            await response(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                if is_health_path:
                    response_headers = [
                        (key, value)
                        for key, value in response_headers
                        if key.lower() != b"cache-control"
                    ]
                    response_headers.append((b"cache-control", b"no-store"))
                if allowed_origin and not is_control_path and origin is not None:
                    response_headers.extend(
                        [
                            (b"access-control-allow-origin", origin.encode("latin-1")),
                            (
                                b"access-control-expose-headers",
                                CONTRACT_HEADER.encode("latin-1"),
                            ),
                            (b"vary", b"Origin"),
                        ]
                    )
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_cors)


def _parse_csv_env(value: str | None) -> list[str]:
    """Split a comma-separated env value into stripped, non-empty items."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# Hosted deployments sit behind a reverse proxy whose public hostname must be
# accepted (a Host of e.g. team08.aiforthai.in.th would otherwise 400). The
# default stays the exact localhost pair so a from-source backend + extension
# keeps working byte-for-byte when the env var is unset.
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_parse_csv_env(os.environ.get("AIGUARD_ALLOWED_HOSTS")) or _DEFAULT_ALLOWED_HOSTS,
)


@app.middleware("http")
async def enforce_http_v2(request: Request, call_next):
    """Assert contract/auth before parsing and contain every API response."""
    path = request.url.path.rstrip("/") or "/"
    is_api = path == "/api" or path.startswith("/api/")
    if not is_api:
        return await call_next(request)

    is_health = request.method == "GET" and path == "/api/health"
    if not is_health:
        assertions = request.headers.getlist(CONTRACT_HEADER)
        if assertions != [str(CONTRACT_VERSION)]:
            return error_response("contract_version_required")

    data_paths = {
        "/api/detect",
        "/api/analyze",
        "/api/guard",
        "/api/sanitize",
        "/api/reidentify",
        "/api/roundtrip",
        "/api/analyze-report",
        "/api/redact-pdf",
        "/api/audit-log",
    }
    is_session_control = bool(
        app.state.session_disposal_enabled and path.startswith("/api/session/")
    )
    is_control = path == "/api/shutdown" or is_session_control
    if is_control and request.headers.getlist("origin"):
        return error_response("control_forbidden")
    if path in data_paths and not _api_key_ok(request.headers.get("X-AIGuard-Key")):
        return error_response("authentication_required")
    if is_session_control:
        session_id = path.removeprefix("/api/session/")
        authorizations = request.headers.getlist("X-AIGuard-Token")
        verified = (
            verify_session_disposal_authorization(
                _BOOT_TOKEN,
                session_id,
                authorizations[0],
                now=_authorization_now(),
            )
            if len(authorizations) == 1
            else None
        )
        if verified is None:
            return error_response("control_forbidden")
        request.state.session_disposal_authorization = verified
    elif path == "/api/shutdown" and not _boot_token_ok(request.headers.get("X-AIGuard-Token")):
        return error_response("control_forbidden")

    query_items = list(request.query_params.multi_items())
    if path == "/api/audit-log":
        seen_query_keys: set[str] = set()
        rejected_count = 0
        for key, value in query_items:
            valid_value = (
                bool(re.fullmatch(r"[1-9][0-9]*", value))
                if key == "limit"
                else bool(re.fullmatch(r"(?:0|[1-9][0-9]*)", value))
                if key == "offset"
                else False
            )
            if key in seen_query_keys or not valid_value:
                rejected_count += 1
            seen_query_keys.add(key)
        if rejected_count:
            return error_response("request_schema_invalid", count=rejected_count)
    elif query_items:
        return error_response("request_schema_invalid", count=len(query_items))

    if request.method in {"GET", "DELETE"} or path == "/api/shutdown":
        try:
            body = await request.body()
        except Exception as error:
            discard_exception_graph(error)
            return error_response("invalid_request")
        if body:
            body = b""
            return error_response("invalid_request")

    try:
        response = await call_next(request)
    except BaseException as error:
        if not isinstance(error, Exception):
            raise
        discard_exception_graph(error)
        request = None
        call_next = None
        error = None
        return error_response("internal_error")

    if response.status_code >= 400 and response.headers.get(CONTRACT_HEADER) != str(
        CONTRACT_VERSION
    ):
        status_code = response.status_code
        response = None
        code = (
            "invalid_request"
            if status_code == 400
            else "route_not_found"
            if status_code == 404
            else "method_not_allowed"
            if status_code == 405
            else "internal_error"
        )
        return error_response(code)
    response.headers[CONTRACT_HEADER] = str(CONTRACT_VERSION)
    return response


# CORS is outermost so a valid preflight does no contract, auth, body, or
# service work. Disallowed preflights receive no permissive CORS headers.
app.add_middleware(_StrictCORSMiddleware)


# ── boot token (Horizon-1 #2) ──────────────────────────────────────────
# Random shared secret read once at import from the AIGUARD_TOKEN env var.
# Shutdown accepts the secret directly when configured. Session disposal always
# requires a short-lived target-bound authorization derived from it; an unset
# secret therefore leaves no disposal grace path. Packaged launchers keep the
# secret in the native/backend trust domain. The value is never logged. Tests
# monkeypatch this module global directly, so checks read it dynamically.
_BOOT_TOKEN: str | None = os.environ.get("AIGUARD_TOKEN") or None

# Optional v2 data-plane authentication. It is distinct from the control token,
# read once at process start, and never logged or reflected.
_API_KEY: str | None = os.environ.get("AIGUARD_API_KEY") or None
_LOGGER = logging.getLogger(__name__)


def _warn_if_api_key_unset() -> None:
    """Make an unauthenticated deployment visible without logging user data."""
    if _API_KEY is None:
        _LOGGER.warning(
            "AIGUARD_API_KEY is not configured; local v2 data-plane routes are unauthenticated"
        )


_warn_if_api_key_unset()


def _token_required() -> bool:
    return _BOOT_TOKEN is not None


def _boot_token_ok(supplied: str | None) -> bool:
    """True when the supplied X-AIGuard-Token authorizes the request.

    When no boot token is configured, source-development control routes remain
    open. When one is configured, an exact constant-time header match is
    required.
    """
    if _BOOT_TOKEN is None:
        return True
    if not supplied:
        return False
    try:
        return secrets.compare_digest(supplied, _BOOT_TOKEN)
    except TypeError:
        return False


def _authorization_now() -> float:
    return time.time()


def _make_session_disposal_authorization(
    control_secret: str,
    session_id: str,
    *,
    now: float | None = None,
    lifetime_s: float = 30.0,
    nonce: bytes | None = None,
) -> str:
    """Trusted helper for the existing target-bound control-plane route."""
    return make_session_disposal_authorization(
        control_secret,
        session_id,
        now=_authorization_now() if now is None else now,
        lifetime_s=lifetime_s,
        nonce=nonce,
    )


def _api_key_ok(supplied: str | None) -> bool:
    """Authorize a v2 data-plane route when AIGUARD_API_KEY is set."""
    if _API_KEY is None:
        return True
    if not supplied:
        return False
    try:
        return secrets.compare_digest(supplied, _API_KEY)
    except TypeError:
        return False


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


def _demo_page_path() -> Path:
    """Resolve demo/playground.html next to the repo root or the frozen exe."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "demo" / "playground.html"
    return Path(__file__).resolve().parent.parent / "demo" / "playground.html"


@app.get("/demo", include_in_schema=False)
def demo_page():
    """Demo playground — off unless AIGUARD_DEMO=1 (backend stays API-only).

    Read dynamically (not at import) so one process can flip it in tests and
    the packaged exe's default stays "off" without a rebuild.
    """
    if os.environ.get("AIGUARD_DEMO") != "1":
        raise FastAPIHTTPException(status_code=404, detail="Not Found")
    page = _demo_page_path()
    if not page.is_file():
        raise FastAPIHTTPException(status_code=404, detail="Not Found")
    return FileResponse(page, media_type="text/html")


def _schedule_exit() -> None:
    """Exit the process shortly after the HTTP response is flushed.

    Localhost-only control path used by the desktop shell (Tauri) to stop the
    bundled sidecar gracefully. A short delay lets the 200 response reach the
    caller before the interpreter exits.
    """

    def _die() -> None:
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()


@app.post("/api/shutdown", response_model=ShutdownResponse)
@_contain_public_errors
def shutdown():
    SERVICE.close()
    _schedule_exit()
    return validated_payload(
        ShutdownResponse,
        {"status": "shutting_down"},
    )


def _check_audit_dir_writable() -> None:
    """Fail at boot, not with a 500 on first use, when audit logs cannot be written.

    pii_redactor/audit.py has no try/except around its file writes on purpose
    (a silently lost audit trail is worse than a crash), so on a hosted
    deployment a bad mount/permission would otherwise surface as a 500 the
    first time a judge presses the button. Skipped in stdout audit mode
    (AIGUARD_AUDIT_STDOUT=1), which never touches the filesystem.
    """
    if os.environ.get("AIGUARD_AUDIT_STDOUT") == "1":
        return
    log_dir = Path(_get_audit_log_dir())
    probe = log_dir / f".write_probe_{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise RuntimeError(
            f"audit log directory {log_dir} is not writable ({type(e).__name__}); "
            "fix the mount/permissions or set AIGUARD_AUDIT_STDOUT=1"
        ) from e


def _get_audit_log_dir() -> str:
    """Audit log directory. Frozen exe -> %APPDATA%/AI Guard/logs; source -> ./logs."""
    if getattr(sys, "frozen", False):
        log_dir = Path.home() / "AppData" / "Roaming" / "AI Guard" / "logs"
    else:
        log_dir = Path.cwd() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir)


_check_audit_dir_writable()


_SESSION_CAP = 200
_SESSION_TTL_S = 1800


def _now() -> float:
    return time.monotonic()


# The single core brain. now_fn is late-bound through the module global so
# tests that monkeypatch app.server._now keep working.
from pii_redactor.session_service import (
    DisposalAuthorizationError,
    ModeMismatchError,
    OutboundLeakError,
    SanitizeOutcome,
    SessionExpiredError,
    SessionService,
)


def _new_session_expiry_timer(
    delay: float,
    callback,
) -> threading.Timer:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    return timer


SERVICE = SessionService(
    cap=_SESSION_CAP,
    ttl_s=_SESSION_TTL_S,
    now_fn=lambda: _now(),
    timer_factory=_new_session_expiry_timer,
)
atexit.register(SERVICE.close)


_SECTION26_CATEGORIES = (
    "RACE_ETHNICITY",
    "POLITICAL_OPINION",
    "RELIGION",
    "HEALTH",
    "SEXUAL_BEHAVIOR",
    "CRIMINAL_RECORD",
    "DISABILITY",
    "LABOR_UNION",
)
_GUARD_CATEGORIES = {
    "instruction_override",
    "role_hijack",
    "exfiltration",
    "hidden_chars",
    "suspicious_payload",
}
_GUARD_SEVERITIES = {"low", "medium", "high"}
_AUDIT_STEPS = {
    "api_sanitize",
    "api_reidentify",
    "api_analyze",
    "api_analyze_report",
    "api_roundtrip",
    "api_redact_pdf",
}
_AUDIT_RESULTS = {"prepared", "blocked", "pass", "warn"}
_AUDIT_LAYERS = {"layer1", "layer2", "layer3", "outbound", "provider", "restore"}
_AUDIT_SCAN_RESULTS = {"clean", "unexpected_pii", "blocked", "error"}


def _render(model, payload: object) -> JSONResponse:
    """Validate and render while a sanitize transaction is still detached."""
    return JSONResponse(content=validated_payload(model, payload))


def _section26_categories(findings: object) -> list[str]:
    if not isinstance(findings, list):
        return []
    observed: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        category = finding.get("category")
        if category in _SECTION26_CATEGORIES:
            observed.add(category)
    return [category for category in _SECTION26_CATEGORIES if category in observed]


def _guard_findings(text: str) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for finding in scan_injection(text):
        category = getattr(finding, "category", None)
        severity = getattr(finding, "severity", None)
        pair = (category, severity)
        if category in _GUARD_CATEGORIES and severity in _GUARD_SEVERITIES and pair not in seen:
            projected.append({"category": category, "severity": severity})
            seen.add(pair)
    return projected


def _restore_warnings(out) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    generated_count = getattr(out, "generated_pii_count", 0)
    foreign_count = getattr(out, "foreign_replacement_count", 0)
    if type(generated_count) is int and generated_count > 0:
        warnings.append({"code": "generated_pii", "count": generated_count})
    if type(foreign_count) is int and foreign_count > 0:
        warnings.append({"code": "foreign_replacement", "count": foreign_count})
    return warnings


def _analyze_projection(result: dict) -> dict[str, object]:
    section26_categories = _section26_categories(result.get("section26"))
    reid = result.get("reid") if isinstance(result.get("reid"), dict) else {}
    direct_count = result.get("direct_pii_count")
    score = result.get("overall_score")
    recommendations: list[dict[str, str]] = []
    if type(direct_count) is int and direct_count > 0:
        recommendations.append(dict(RECOMMENDATION_TEMPLATES["direct"]))
    if section26_categories:
        recommendations.append(dict(RECOMMENDATION_TEMPLATES["section26"]))
    if reid.get("high_risk_combo") is True:
        recommendations.append(dict(RECOMMENDATION_TEMPLATES["reidentification"]))
    if type(score) in {int, float} and not isinstance(score, bool) and score >= 60:
        recommendations.append(dict(RECOMMENDATION_TEMPLATES["minimization"]))
    if not recommendations:
        recommendations.append(dict(RECOMMENDATION_TEMPLATES["clear"]))
    return {
        "overall_score": float(result["overall_score"]),
        "overall_grade": result["overall_grade"],
        "risk_label": result["risk_label"],
        "direct_pii_count": result["direct_pii_count"],
        "fp_count": result["fp_count"],
        "tb_count": result["tb_count"],
        "section26_categories": section26_categories,
        "reidentification": {
            "score": float(reid["score"]),
            "grade": reid["grade"],
            "quasi_identifier_categories": list(reid["qi_found"]),
            "high_risk_combination": reid["high_risk_combo"],
        },
        "breakdown": [
            {
                "data_type": item["data_type"],
                "redact_type": item["redact_type"],
                "count": item["count"],
            }
            for item in result["breakdown"]
        ],
        "recommendations": recommendations,
    }


def _audit_flags(values: object) -> list[dict[str, object]]:
    if not isinstance(values, list):
        return []
    counts: dict[str, int] = {}
    order: list[str] = []

    def add(code: str, count: int) -> None:
        if code not in counts:
            counts[code] = 0
            order.append(code)
        counts[code] += count

    for value in values:
        if type(value) is not str:
            continue
        if value.startswith("provider:"):
            add("provider_call", 0)
        elif value.startswith("leftover_count:"):
            try:
                count = int(value.removeprefix("leftover_count:"))
            except ValueError:
                continue
            if count >= 0:
                add("leftover_replacement", count)
        elif value.startswith("leak_type:"):
            add("residual_block", 1)
        elif value == "ocr_review_required":
            add("ocr_review_required", 0)
        elif value == "source_type:pdf_text":
            add("source_pdf_text", 0)
        elif value == "source_type:pdf_hybrid":
            add("source_pdf_hybrid", 0)
    return [{"code": code, "count": counts[code]} for code in order]


def _project_audit_record(record: object) -> dict[str, object] | None:
    if not isinstance(record, dict):
        return None
    timestamp = finite_nonnegative(record.get("timestamp"))
    if timestamp is None:
        return None
    if record.get("type") == "process":
        step = record.get("step")
        result = record.get("validation_result")
        entity_count = record.get("entity_count")
        latency_ms = finite_nonnegative(record.get("latency_ms"))
        if (
            type(step) is not str
            or step not in _AUDIT_STEPS
            or type(result) is not str
            or result not in _AUDIT_RESULTS
            or type(entity_count) is not int
            or entity_count < 0
            or latency_ms is None
        ):
            return None
        return {
            "type": "process",
            "timestamp": timestamp,
            "step": step,
            "entity_count": entity_count,
            "validation_result": result,
            "latency_ms": latency_ms,
            "flags": _audit_flags(record.get("flags")),
        }
    if record.get("type") == "security":
        layer = record.get("layer")
        scan_result = record.get("pii_scan_result")
        retry_count = record.get("retry_count")
        error_type = record.get("error_type")
        rollback = record.get("rollback_occurred")
        if (
            type(layer) is not str
            or layer not in _AUDIT_LAYERS
            or type(scan_result) is not str
            or scan_result not in _AUDIT_SCAN_RESULTS
            or type(retry_count) is not int
            or retry_count < 0
            or (
                error_type is not None
                and (type(error_type) is not str or error_type not in ERROR_SPECS)
            )
            or type(rollback) is not bool
        ):
            return None
        return {
            "type": "security",
            "timestamp": timestamp,
            "layer": layer,
            "pii_scan_result": scan_result,
            "retry_count": retry_count,
            "error_type": error_type,
            "rollback_occurred": rollback,
        }
    return None


# Keep the route-specific names stable for direct Python callers and tests
# while using one exact `{text}` schema.
AnalyzeRequest = TextRequest
DetectRequest = TextRequest
GuardRequest = TextRequest


# ── endpoints ──────────────────────────────────────────────────────────
@app.get("/api/health", response_model=HealthResponse)
def health():
    return validated_payload(
        HealthResponse,
        {
            "status": "ok",
            "version": __version__,
            "contract_version": CONTRACT_VERSION,
            "capabilities": {
                "control_token_required": _token_required(),
                "api_key_required": _API_KEY is not None,
            },
        },
    )


_AUDIT_MAX_FILES = 50
_AUDIT_MAX_RECORDS = 5000


@app.get("/api/audit-log", response_model=AuditLogResponse)
def get_audit_log(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    log_dir = _get_audit_log_dir()
    paths = glob.glob(f"{log_dir}/audit_*.jsonl")
    paths.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0.0, reverse=True)
    records: list[dict[str, object]] = []
    for path in paths[:_AUDIT_MAX_FILES]:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    safe = _project_audit_record(r)
                    if safe is not None:
                        records.append(safe)
        except OSError:
            continue
        if len(records) >= _AUDIT_MAX_RECORDS:
            break
    records.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
    total = len(records)
    return validated_payload(
        AuditLogResponse,
        {
            "status": "ok",
            "total_count": total,
            "limit": limit,
            "offset": offset,
            "logs": records[offset : offset + limit],
        },
    )


@app.post("/api/sanitize", response_model=SanitizeResponse)
@_contain_public_errors
def sanitize(request: SanitizeRequest):
    start = time.time()
    operation_id = str(uuid.uuid4())
    _validate_text_input(request.text)
    if request.mode is not None and request.mode not in ("token", "surrogate"):
        raise ContractError("invalid_request")
    mode = request.mode
    source_text = request.text
    detection_text = clean_length_preserving(source_text)

    def finalize(out: SanitizeOutcome) -> JSONResponse:
        highlights = [
            {
                "start": item.start,
                "end": item.end,
                "data_type": item.data_type,
                "redact_type": item.redact_type,
            }
            for item in out.replacement_highlights
        ]
        payload = {
            "session_id": out.session_id,
            "sanitized_text": out.sanitized_text,
            "detected_entity_count": len(out.entities),
            "replacement_count": len(highlights),
            "entity_type_counts": out.entity_type_counts,
            "highlights": highlights,
            "section26_categories": _section26_categories(out.section26),
            "guard_findings": _guard_findings(request.text),
            "warnings": [],
            "safety": {"status": "pass", "residual_count": 0},
        }
        # Validation and JSON rendering happen before the one-assignment
        # publication in SessionService.
        response = _render(SanitizeResponse, payload)
        write_process_log(
            session_id=operation_id,
            step="api_sanitize",
            entity_count=len(out.entities),
            # The process record is written before the one-assignment publish.
            # "prepared" stays truthful even if the write itself then fails.
            validation_result="prepared",
            flags=[],
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        return response

    residual_count = 0
    residual_types: list[str] = []
    try:
        result = SERVICE.sanitize_transaction(
            source_text,
            mode=mode,
            session_id=request.session_id,
            detection_text=detection_text,
            finalize=finalize,
        )
    except SessionExpiredError:
        raise ContractError("session_unavailable") from None
    except ModeMismatchError as error:
        discard_exception_graph(error)
        raise ContractError("invalid_request") from None
    except (OutboundLeakError, OutboundPolicyError) as error:
        residual_types = normalize_outbound_leak_types(error.leak_types)
        residual_count = getattr(error, "policy_category_count", 0)
        if type(residual_count) is not int or residual_count <= 0:
            residual_count = max(1, len(residual_types))
        discard_exception_graph(error)

    if residual_count:
        write_process_log(
            session_id=operation_id,
            step="api_sanitize",
            entity_count=0,
            validation_result="blocked",
            flags=[f"leak_type:{item}" for item in residual_types],
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        request = None
        source_text = ""
        detection_text = ""
        finalize = None
        mode = None
        residual_types = []
        raise ContractError("residual_pii", count=residual_count)
    return result


@app.post("/api/reidentify", response_model=ReidentifyResponse)
@_contain_public_errors
def reidentify(request: ReidentifyRequest):
    """Restore original PII via the core reverse mapper + output validation."""
    start = time.time()
    operation_id = str(uuid.uuid4())
    _validate_text_input(request.text)
    restore_failed = False
    try:
        out = SERVICE.restore(request.session_id, request.text)
    except SessionExpiredError:
        raise ContractError("session_unavailable") from None
    except Exception as error:
        restore_failed = True
        discard_exception_graph(error)
    if restore_failed:
        request = None
        out = None
        raise ContractError("restore_failed")

    leftover_count = len(out.leftover_tokens)
    warnings = _restore_warnings(out)

    write_process_log(
        session_id=operation_id,
        step="api_reidentify",
        entity_count=out.replaced_count,
        validation_result="warn" if (leftover_count or warnings) else "pass",
        # VAULT-4: never log the pseudonym itself. The signed AI for Thai
        # proposal states the audit log holds only event type, counts and time,
        # and /api/audit-log echoes `flags` verbatim to any local caller.
        flags=([f"leftover_count:{leftover_count}"] if leftover_count else []),
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return _render(
        ReidentifyResponse,
        {
            "restored_text": out.restored_text,
            "replaced_count": out.replaced_count,
            "leftover_count": leftover_count,
            "warnings": warnings,
        },
    )


@app.delete("/api/session/{session_id}", response_model=DeleteSessionResponse)
@_contain_public_errors
def delete_session(
    request: Request,
    session_id: str,
):
    if not session_id:
        raise ContractError("invalid_request")
    authorization = getattr(
        request.state,
        "session_disposal_authorization",
        None,
    )
    if authorization is None:
        raise ContractError("control_forbidden")
    try:
        deleted = SERVICE.dispose_authenticated(
            session_id,
            authorization_fingerprint=authorization.fingerprint,
            authorization_expires_at_ms=authorization.expires_at_ms,
            authorization_now_ms_fn=lambda: _authorization_now() * 1000,
        )
    except DisposalAuthorizationError as error:
        discard_exception_graph(error)
        raise ContractError("control_forbidden") from None
    except SessionExpiredError as error:
        discard_exception_graph(error)
        raise ContractError("session_unavailable") from None
    return validated_payload(
        DeleteSessionResponse,
        {"deleted": deleted},
    )


@app.post("/api/analyze", response_model=AnalyzeResponse)
@_contain_public_errors
def analyze(request: AnalyzeRequest):
    start = time.time()
    _validate_text_input(request.text)
    text = clean(request.text).text
    result = analyze_text(text)
    write_process_log(
        session_id=str(uuid.uuid4()),
        step="api_analyze",
        entity_count=result["direct_pii_count"],
        validation_result="pass",
        flags=[],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return validated_payload(AnalyzeResponse, _analyze_projection(result))


@app.post("/api/analyze-report", response_model=AnalyzeReportResponse)
@_contain_public_errors
def analyze_report(request: AnalyzeRequest):
    """PDPA risk report as a downloadable PDF — the compliance artifact.

    Same assembly as /api/analyze (via report.analyze_text), rendered by
    pii_redactor/report_pdf.py which draws whitelist fields only; the source
    text itself never reaches the canvas. The sha256 prefix ties a report to
    its source without embedding any of it.
    """
    start = time.time()
    _validate_text_input(request.text)
    text = clean(request.text).text
    analysis = analyze_text(text)
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    pdf_bytes = render_pdpa_report(analysis, version=__version__, source_sha256_12=source_hash)
    write_process_log(
        session_id=str(uuid.uuid4()),
        step="api_analyze_report",
        entity_count=analysis["direct_pii_count"],
        validation_result="pass",
        flags=[],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return validated_payload(
        AnalyzeReportResponse,
        {
            "report_pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
            "overall_score": float(analysis["overall_score"]),
            "overall_grade": analysis["overall_grade"],
        },
    )


@app.post("/api/detect", response_model=DetectResponse)
@_contain_public_errors
def detect(request: DetectRequest):
    """Detection only — no session, no vault, no persistence.

    Exists for the demo playground's live-highlight loop: /api/sanitize mints a
    session per call, which a keystroke-frequency caller would flood. Offsets
    must stay aligned with the caller's text, so this uses
    clean_length_preserving (same contract as the redact-pdf path), never
    clean().
    """
    _validate_text_input(request.text)
    entities = detect_all(clean_length_preserving(request.text))
    highlights = [
        {
            "start": e.span[0],
            "end": e.span[1],
            "data_type": e.data_type,
            "redact_type": e.redact_type,
        }
        for e in entities
    ]
    counts: dict[str, int] = {}
    for e in highlights:
        counts[e["data_type"]] = counts.get(e["data_type"], 0) + 1
    previous_end = 0
    for item in highlights:
        if (
            item["start"] < previous_end
            or item["end"] > len(request.text)
            or item["end"] <= item["start"]
        ):
            raise ContractError("internal_error")
        previous_end = item["end"]
    return validated_payload(
        DetectResponse,
        {
            "detected_entity_count": len(highlights),
            "entity_type_counts": counts,
            "highlights": highlights,
        },
    )


# Hosted deployments narrow the provider surface (e.g. AIGUARD_PROVIDERS=
# "tokenmind") so ollama/claude/fake cannot appear on a public service by
# accident. Unset keeps the full registry — the local extension/desktop
# behavior, byte-for-byte. An unknown name fails the boot loudly (the
# registry's allowlist contract), never silently drops.
_PROVIDER_FACTORIES = get_provider_factories(
    allowed=_parse_csv_env(os.environ.get("AIGUARD_PROVIDERS")) or None
)


@app.post("/api/roundtrip", response_model=RoundtripResponse)
@_contain_public_errors
def roundtrip(request: RoundtripRequest):
    """mask -> LLM -> restore in one request, on the stateless core.

    This endpoint consumes the mapping inside the request, does not serialize
    it, and creates no SessionService entry. Platform logging and persistence
    acceptance remain separate. In the default local provider registry, `fake`
    is the offline identity provider used by the demo.
    """
    start = time.time()
    _validate_text_input(request.text)
    if request.mode not in ("token", "surrogate"):
        raise ContractError("invalid_request")
    factory = _PROVIDER_FACTORIES.get(request.provider)
    if factory is None:
        raise ContractError("invalid_request")
    provider_unavailable = False
    try:
        provider = factory()
    except Exception as error:
        discard_exception_graph(error)
        provider_unavailable = True
    if provider_unavailable:
        request = None
        factory = None
        raise ContractError("provider_configuration")

    source_text = request.text
    detection_text = clean_length_preserving(source_text)
    sanitize_failure = 0
    try:
        masked = sanitize_stateless(
            source_text,
            mode=request.mode,
            salt=uuid.uuid4().hex,
            detection_text=detection_text,
        )
    except (OutboundPolicyError, StatelessLeakError) as error:
        sanitize_failure = getattr(error, "policy_category_count", 0)
        if type(sanitize_failure) is not int or sanitize_failure <= 0:
            sanitize_failure = max(
                1,
                len(normalize_outbound_leak_types(error.leak_types)),
            )
        discard_exception_graph(error)
    if sanitize_failure:
        provider = None
        factory = None
        request = None
        source_text = ""
        detection_text = ""
        masked = None
        raise ContractError("residual_pii", count=sanitize_failure)

    def validate_provider_attempt(_attempt: int) -> None:
        enforce_outbound_policy(
            masked.sanitized_text,
            guard_context=masked.guard_context,
            scan_leaks=scan_outbound_leaks,
            scan_residual=scan_residual_signals,
        )

    rescan_failure = 0
    provider_error_code = None
    try:
        ai_text, _provider_latency, _provider_attempts = complete_provider_with_retry_policy(
            provider,
            DEFAULT_SYSTEM_PROMPT,
            masked.sanitized_text,
            before_attempt=validate_provider_attempt,
        )
    except OutboundPolicyError as error:
        rescan_failure = getattr(error, "policy_category_count", 0)
        if type(rescan_failure) is not int or rescan_failure <= 0:
            rescan_failure = max(
                1,
                len(normalize_outbound_leak_types(error.leak_types)),
            )
        discard_exception_graph(error)
    except ProviderCallError as error:
        category = error.category if type(error.category) is str else "failed"
        status_code = error.status_code if type(error.status_code) is int else None
        if category in {"malformed", "non_text"}:
            provider_error_code = "provider_response_invalid"
        elif category == "http_status" and status_code is not None:
            if status_code == 429 or status_code >= 500:
                provider_error_code = "provider_unavailable"
            else:
                provider_error_code = "provider_rejected"
        else:
            provider_error_code = "provider_unavailable"
        discard_exception_graph(error)
    validate_provider_attempt = None
    if rescan_failure:
        provider = None
        factory = None
        request = None
        source_text = ""
        detection_text = ""
        masked = None
        ai_text = ""
        raise ContractError("residual_pii", count=rescan_failure)
    if provider_error_code is None:
        invalid_provider_text = not ai_text.strip()
        if not invalid_provider_text:
            try:
                ai_text.encode("utf-8")
            except UnicodeEncodeError as error:
                discard_exception_graph(error)
                invalid_provider_text = True
        if invalid_provider_text:
            provider_error_code = "provider_response_invalid"
    if provider_error_code is not None:
        # The traceback is inspectable until FastAPI renders this exception.
        # Clear all locals that can reach credentials, input, or the transient
        # mapping before raising the fixed wire-safe error.
        provider = None
        factory = None
        request = None
        source_text = ""
        detection_text = ""
        masked = None
        ai_text = ""
        raise ContractError(provider_error_code)
    restore_failed = False
    try:
        restored = restore_stateless(
            ai_text,
            mapping=masked.mapping,
            mode=request.mode,
        )
    except Exception as error:
        restore_failed = True
        discard_exception_graph(error)
    if restore_failed:
        provider = None
        factory = None
        request = None
        source_text = ""
        detection_text = ""
        masked = None
        ai_text = ""
        restored = None
        raise ContractError("restore_failed")

    warnings = _restore_warnings(restored)
    leftover_count = len(restored.leftover_pseudonyms)
    restoration_status = "unsafe" if warnings else "incomplete" if leftover_count else "complete"
    write_process_log(
        session_id=str(uuid.uuid4()),
        step="api_roundtrip",
        entity_count=len(masked.entities),
        validation_result="warn" if (warnings or leftover_count) else "pass",
        flags=[f"provider:{request.provider}"]
        + ([f"leftover_count:{leftover_count}"] if leftover_count else []),
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    payload = {
        "sanitized_text": masked.sanitized_text,
        "ai_response_masked": ai_text,
        "restored_text": restored.restored_text,
        "detected_entity_count": len(masked.entities),
        "entity_type_counts": masked.entity_type_counts,
        "provider_used": request.provider,
        "section26_categories": _section26_categories(masked.section26),
        "guard_findings": _guard_findings(request.text),
        "warnings": warnings,
        "safety": {"status": "pass", "residual_count": 0},
        "restoration": {
            "status": restoration_status,
            "replaced_count": restored.replaced_count,
            "leftover_count": leftover_count,
        },
    }
    masked.mapping.clear()
    return _render(RoundtripResponse, payload)


@app.post("/api/guard", response_model=GuardResponse)
@_contain_public_errors
def guard(request: GuardRequest):
    """Dependency-light prompt-injection warning scan; blocks nothing.

    See pii_redactor/guard/injection.py: explicit rules plus bounded
    normalization/intent features in Thai and English; not airtight.
    """
    _validate_text_input(request.text)
    findings = _guard_findings(request.text)
    return validated_payload(
        GuardResponse,
        {"guard_findings": findings, "flagged": bool(findings)},
    )


def _first_page_png(pdf_path: str) -> str:
    """Render page 1 of a PDF to a base64 PNG (for before/after previews)."""
    from pii_redactor.pdf_render import render_page_png

    png = render_page_png(pdf_path, page_index=0)
    return base64.b64encode(png).decode("ascii")


# Upload cap for /api/redact-pdf; enforced while streaming so an oversize
# body is rejected before it is fully buffered in memory.
_MAX_PDF_BYTES = 50 * 1024 * 1024

# Work caps for a public deployment: byte size alone does not bound OCR work
# (a small file can carry hundreds of pages, or one page with an enormous
# MediaBox that renders to a gigapixel bitmap). Read at import; hosted
# deployments tune via env, tests monkeypatch the module globals.
_MAX_PDF_PAGES = int(os.environ.get("AIGUARD_PDF_MAX_PAGES", "100"))
_MAX_PDF_PAGE_POINTS = float(os.environ.get("AIGUARD_PDF_MAX_PAGE_POINTS", "5000"))

# Same idea for the text endpoints: NER/masking work scales with input length
# and nothing bounded it before. The default is far above any legitimate chat
# or document paste; hosted deployments tighten it via env.
_MAX_TEXT_CHARS = int(os.environ.get("AIGUARD_MAX_TEXT_CHARS", "200000"))


def _validate_text_input(text: str) -> None:
    """400 on empty, 413 past the work cap — shared by every text endpoint."""
    if not text or not text.strip():
        raise ContractError("invalid_request")
    if len(text) > _MAX_TEXT_CHARS:
        raise ContractError("payload_too_large")


def _check_pdf_work_caps(pdf_path: Path) -> None:
    """Reject page-count / page-size bombs before any render or OCR work.

    Raises a fixed v2 error on a cap violation or unreadable document.
    be opened (with a fixed category — never the parser's exception text).
    """
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception as error:
        discard_exception_graph(error)
        raise ContractError("document_invalid") from None
    try:
        n_pages = len(pdf)
        if n_pages > _MAX_PDF_PAGES:
            raise ContractError("payload_too_large")
        for i in range(n_pages):
            page = pdf.get_page(i)
            try:
                width, height = page.get_size()
            finally:
                page.close()
            if width > _MAX_PDF_PAGE_POINTS or height > _MAX_PDF_PAGE_POINTS:
                raise ContractError("payload_too_large")
    finally:
        pdf.close()


async def _strict_pdf_upload(
    request: Request,
    pdf_file: Annotated[UploadFile, File()],
) -> UploadFile:
    """Reject missing, repeated, or additional multipart fields."""
    try:
        form = await request.form()
    except Exception as error:
        discard_exception_graph(error)
        raise ContractError("request_schema_invalid", count=1) from None
    items = list(form.multi_items())
    invalid_count = sum(key != "pdf_file" for key, _value in items)
    pdf_count = sum(key == "pdf_file" for key, _value in items)
    if pdf_count != 1:
        invalid_count += abs(pdf_count - 1)
    form = None
    items = []
    if invalid_count:
        raise ContractError("request_schema_invalid", count=invalid_count)
    return pdf_file


@app.post("/api/redact-pdf", response_model=RedactPdfResponse)
@_contain_public_errors
def redact_pdf(pdf_file: Annotated[UploadFile, Depends(_strict_pdf_upload)]):
    """Redact PII in a text-layer or scanned PDF and return the redacted file + previews.

    Detection runs on a length-preserving normalisation of the raw extracted
    text (clean_length_preserving — Thai-to-Arabic digit substitution only),
    not the full clean(), so entity text still aligns with the word bboxes
    used to draw the black boxes: clean()'s whitespace collapsing, NFC and
    zero-width stripping all shift char offsets, which would misalign the
    boxes. The digit substitution is 1:1 in character count, so it's safe here
    — without it a Thai-numeral phone number (e.g. ๐๘๑-๒๓๔-๕๖๗๘) is never
    detected and never blacked out. Scanned/image PDFs are routed through
    OCR (pii_redactor.ingest.ocr_processor) page by page; if the OCR
    dependencies (requirements-ocr.txt) aren't installed, this returns 503.
    """
    start = time.time()
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise ContractError("document_invalid")

    # Sync endpoint on purpose (API-1): the heavy OCR/NER/render work must run
    # in FastAPI's threadpool, not on the event loop. pdf_file.file is the
    # underlying SpooledTemporaryFile, readable without await.
    chunks: list[bytes] = []
    size = 0
    while chunk := pdf_file.file.read(64 * 1024):
        size += len(chunk)
        if size > _MAX_PDF_BYTES:
            raise ContractError("payload_too_large")
        chunks.append(chunk)
    contents = b"".join(chunks)
    tmp_dir = Path(tempfile.mkdtemp(prefix="aiguard_redact_"))
    in_path = tmp_dir / "input.pdf"
    out_path = tmp_dir / "redacted.pdf"
    try:
        in_path.write_bytes(contents)
        _check_pdf_work_caps(in_path)
        try:
            source_type = detect_source_type(in_path)
            raw_text, word_bboxes, extract_meta = extract(in_path, source_type)
        except OCRUnavailableError as error:
            discard_exception_graph(error)
            raise ContractError("ocr_unavailable") from None
        except ContractError:
            raise
        except Exception as error:
            discard_exception_graph(error)
            raise ContractError("document_invalid") from None

        detect_text = clean_length_preserving(raw_text)
        entities = detect_all(detect_text)
        fp_count = sum(entity.redact_type == "FP" for entity in entities)
        registry = EntityRegistry(
            entities=entities,
            fp_count=fp_count,
            tb_count=len(entities) - fp_count,
        )

        redact_pdf_file(str(in_path), registry, word_bboxes, str(out_path))

        counts: dict[str, int] = {}
        for entity in entities:
            counts[entity.data_type] = counts.get(entity.data_type, 0) + 1

        # Unique type/class pairs in first-detection order.
        seen: set[tuple[str, str]] = set()
        fields: list[dict[str, str]] = []
        for e in entities:
            pair = (e.data_type, e.redact_type)
            if pair not in seen:
                seen.add(pair)
                fields.append({"data_type": e.data_type, "redact_type": e.redact_type})

        human_review = bool(extract_meta.get("human_review", False))
        ocr_warnings = extract_meta.get("warnings", [])
        pages_ocred = extract_meta.get("pages_ocred", [])
        ocr_affected_pages = (
            len({page for page in pages_ocred if type(page) is int and page > 0})
            if isinstance(pages_ocred, list)
            else 0
        )
        human_review_pages = extract_meta.get("human_review_pages", [])
        review_affected_pages = (
            len({page for page in human_review_pages if type(page) is int and page > 0})
            if isinstance(human_review_pages, list)
            else 0
        )
        confidence = finite_nonnegative(extract_meta.get("ocr_confidence"))
        if confidence is not None and confidence > 1:
            confidence = None
        warnings: list[dict[str, object]] = []
        if confidence is not None and confidence < OCR_CONFIDENCE_THRESHOLD:
            warnings.append(
                {
                    "code": "ocr_low_confidence",
                    "count": max(1, ocr_affected_pages),
                }
            )
        if human_review:
            warnings.append(
                {
                    "code": "human_review_required",
                    "count": max(1, review_affected_pages),
                }
            )
        audit_flags = [f"source_type:{source_type}"]
        if human_review:
            audit_flags.append("ocr_review_required")
        write_process_log(
            session_id=str(uuid.uuid4()),
            step="api_redact_pdf",
            entity_count=len(entities),
            validation_result="warn" if (human_review or ocr_warnings) else "pass",
            flags=audit_flags,
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        return validated_payload(
            RedactPdfResponse,
            {
                "source_type": source_type,
                "ocr_confidence": confidence,
                "human_review": human_review,
                "warnings": warnings,
                "detected_entity_count": len(entities),
                "entity_type_counts": counts,
                "fields": fields,
                "section26_categories": _section26_categories(scan_section26(raw_text)),
                "redacted_pdf_b64": base64.b64encode(out_path.read_bytes()).decode("ascii"),
                "after_png_b64": _first_page_png(str(out_path)),
            },
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
