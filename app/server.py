"""FastAPI server for the AI Guard Thai PII redaction pipeline.

Local API backend for the browser extension (extension/). The extension runs
on chatgpt.com / claude.ai and calls these endpoints on localhost.

AI Guard uses TOKEN-mode pseudonymization (e.g. [ชื่อ_1]) so the round-trip
through an external AI is robust and visually explicit. The token -> original
map is owned by `pii_redactor.session_service.SessionService` in backend
memory. Contract-v1 responses still expose direct or reconstructable mapping
fields to local clients; removing those fields is a separate v2 contract gate.
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import logging
import os
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

from fastapi import FastAPI, File, Header, Query, Request, UploadFile
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pii_redactor.ai_client import (
    DEFAULT_SYSTEM_PROMPT,
    ProviderCallError,
    complete_provider_call,
    get_provider_factories,
)
from pii_redactor.audit import write_process_log
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.guard.injection import scan_injection, to_wire
from pii_redactor.ingest.file_detector import detect_source_type
from pii_redactor.ingest.ocr_processor import OCRUnavailableError
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


class _PublicHTTPError(FastAPIHTTPException):
    """An endpoint-authored error whose detail is safe for the current wire."""


# Keep the existing call sites compact while separating trusted endpoint errors
# from FastAPI exceptions raised by fallible downstream code.
HTTPException = _PublicHTTPError


def _contain_public_errors(func):
    """Sever failed endpoint frames before a fixed public exception escapes."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        failure = None
        try:
            return func(*args, **kwargs)
        except _PublicHTTPError as error:
            if type(error) is _PublicHTTPError:
                failure = (error.status_code, error.detail, error.headers)
            else:
                failure = (500, "Internal processing failed", None)
            discard_exception_graph(error)
        except FastAPIHTTPException as error:
            failure = (500, "Internal processing failed", None)
            discard_exception_graph(error)
        except Exception as error:
            failure = (500, "Internal processing failed", None)
            discard_exception_graph(error)

        args = ()
        kwargs = {}
        status_code, detail, headers = failure
        failure = None
        raise FastAPIHTTPException(
            status_code=status_code,
            detail=detail,
            headers=headers,
        )

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
)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request: Request, error: RequestValidationError):
    """Return a fixed 422 without echoing invalid body/query values."""
    discard_exception_graph(error)
    try:
        object.__setattr__(error, "body", None)
        object.__setattr__(error, "_errors", [])
        BaseException.__setattr__(error, "args", ())
    except BaseException:
        pass
    _request = None
    error = None
    return JSONResponse(status_code=422, content={"detail": "Invalid request"})


_LEGACY_V1_API_KEY_POST_PATHS = frozenset(
    {"/api/sanitize", "/api/reidentify", "/api/analyze", "/api/guard"}
)


@app.middleware("http")
async def authenticate_legacy_v1_endpoints(request: Request, call_next):
    """Gate the legacy local v1 POST set before parsing request bodies."""
    path = request.url.path.rstrip("/") or "/"
    if request.method == "POST" and path in _LEGACY_V1_API_KEY_POST_PATHS:
        if not _legacy_v1_api_key_ok(request.headers.get("X-AIGuard-Key")):
            # Deliberately generic: neither the supplied key nor request
            # content crosses into the response or application logs.
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-p]{32}|moz-extension://[0-9a-fA-F-]+|tauri://localhost|https?://tauri\.localhost)$",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
_DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1"]


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
async def contain_framework_errors(request: Request, call_next):
    """Contain pre-response-start failures, including JSON rendering."""
    try:
        return await call_next(request)
    except Exception as error:
        discard_exception_graph(error)
        request = None
        call_next = None
        error = None
        return JSONResponse(status_code=500, content={"detail": "Internal processing failed"})


# ── boot token (Horizon-1 #2) ──────────────────────────────────────────
# Random shared secret read once at import from the AIGUARD_TOKEN env var.
# Enforced ONLY on the control plane (`POST /api/shutdown`,
# `DELETE /api/session/{id}`) and ONLY when set — when it is None the grace
# path keeps the pre-token behavior byte-for-byte (X-AIGuard-Local for
# shutdown, open delete-session). launcher.py / Tauri generate a value and
# pass it in via the env; the value is never logged. Tests monkeypatch this
# module global directly, so the checks below read it dynamically at call time.
_BOOT_TOKEN: str | None = os.environ.get("AIGUARD_TOKEN") or None

# Optional authentication for the four legacy v1 POST endpoints in the main
# local server. This is not the unconfirmed official hosted public surface.
# Like the control-plane boot token above, it is read once when the service
# starts and never logged. Keeping the unset path open preserves the existing
# localhost extension/desktop workflow.
_API_KEY: str | None = os.environ.get("AIGUARD_API_KEY") or None
_LOGGER = logging.getLogger(__name__)


def _warn_if_api_key_unset() -> None:
    """Make an unauthenticated deployment visible without logging user data."""
    if _API_KEY is None:
        _LOGGER.warning(
            "AIGUARD_API_KEY is not configured; legacy v1 API endpoints are unauthenticated"
        )


_warn_if_api_key_unset()


def _token_required() -> bool:
    return _BOOT_TOKEN is not None


def _boot_token_ok(supplied: str | None) -> bool:
    """True when the supplied X-AIGuard-Token authorizes the request.

    When no boot token is configured, always True (grace path — the caller
    falls back to its legacy check). When one is configured, requires an exact
    constant-time match of the supplied header.
    """
    if _BOOT_TOKEN is None:
        return True
    if not supplied:
        return False
    return secrets.compare_digest(supplied, _BOOT_TOKEN)


def _legacy_v1_api_key_ok(supplied: str | None) -> bool:
    """Authorize a legacy local v1 endpoint when AIGUARD_API_KEY is set."""
    if _API_KEY is None:
        return True
    if not supplied:
        return False
    return secrets.compare_digest(supplied, _API_KEY)


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
        raise HTTPException(status_code=404, detail="Not Found")
    page = _demo_page_path()
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
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


@app.post("/api/shutdown")
@_contain_public_errors
def shutdown(
    x_aiguard_local: Annotated[str | None, Header()] = None,
    x_aiguard_token: Annotated[str | None, Header()] = None,
):
    if _BOOT_TOKEN is not None:
        # Token configured: require it. X-AIGuard-Local alone no longer suffices.
        if not _boot_token_ok(x_aiguard_token):
            raise HTTPException(status_code=403, detail="Invalid or missing token")
    elif not x_aiguard_local:
        # Grace path (no token): legacy local-header check, unchanged.
        raise HTTPException(status_code=403, detail="Local shutdown only")
    _schedule_exit()
    return {"status": "shutting_down"}


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
    ModeMismatchError,
    OutboundLeakError,
    SanitizeOutcome,
    SessionExpiredError,
    SessionService,
)

SERVICE = SessionService(cap=_SESSION_CAP, ttl_s=_SESSION_TTL_S, now_fn=lambda: _now())


def _residual_detail(values: object) -> dict[str, object]:
    return {
        "error": "residual_pii",
        "types": normalize_outbound_leak_types(values),
    }


# ── request models ─────────────────────────────────────────────────────
class SanitizeRequest(BaseModel):
    text: str
    mode: str | None = None  # "token" (default) | "surrogate"; None inherits session mode
    session_id: str | None = None  # reuse an existing session for multi-turn consistency


class ReidentifyRequest(BaseModel):
    session_id: str
    text: str


class AnalyzeRequest(BaseModel):
    text: str


class DetectRequest(BaseModel):
    text: str


class RoundtripRequest(BaseModel):
    text: str
    mode: str = "token"  # "token" | "surrogate"
    provider: str = "fake"  # any key of pii_redactor.ai_client.PROVIDER_FACTORIES


class GuardRequest(BaseModel):
    text: str


# ── endpoints ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "contract_version": 1,
        "capabilities": {"token_required": _token_required()},
    }


_AUDIT_MAX_FILES = 50
_AUDIT_MAX_RECORDS = 5000


@app.get("/api/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    log_dir = _get_audit_log_dir()
    paths = glob.glob(f"{log_dir}/audit_*.jsonl")
    paths.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0.0, reverse=True)
    records = []
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
                    safe = {"type": r.get("type"), "timestamp": r.get("timestamp")}
                    if r.get("type") == "process":
                        safe.update(
                            step=r.get("step"),
                            entity_count=r.get("entity_count"),
                            validation_result=r.get("validation_result"),
                            latency_ms=r.get("latency_ms"),
                            flags=r.get("flags", []),
                        )
                    elif r.get("type") == "security":
                        safe.update(
                            layer=r.get("layer"),
                            pii_scan_result=r.get("pii_scan_result"),
                            retry_count=r.get("retry_count"),
                            error_type=r.get("error_type"),
                            rollback_occurred=r.get("rollback_occurred"),
                        )
                    records.append(safe)
        except OSError:
            continue
        if len(records) >= _AUDIT_MAX_RECORDS:
            break
    records.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
    total = len(records)
    return {
        "status": "ok",
        "total_count": total,
        "limit": limit,
        "offset": offset,
        "logs": records[offset : offset + limit],
    }


@app.post("/api/sanitize")
@_contain_public_errors
def sanitize(request: SanitizeRequest):
    start = time.time()
    operation_id = str(uuid.uuid4())
    _validate_text_input(request.text)
    if request.mode is not None and request.mode not in ("token", "surrogate"):
        raise HTTPException(
            status_code=400,
            detail="Invalid mode: expected 'token' or 'surrogate'",
        )
    mode = request.mode
    clean_text = clean(request.text).text

    def finalize(out: SanitizeOutcome) -> JSONResponse:
        guard_findings = to_wire(scan_injection(request.text))
        payload = {
            "session_id": out.session_id,
            "original_text": out.original_text,
            "sanitized_text": out.sanitized_text,
            "entities": out.entities,
            "entity_type_counts": out.entity_type_counts,
            "section26": out.section26,
            "warnings": out.warnings,
            "guard": guard_findings,
        }
        # Constructing the response renders JSON immediately. The transaction
        # is still unpublished if encoding rejects any value.
        response = JSONResponse(content=payload)
        write_process_log(
            session_id=operation_id,
            step="api_sanitize",
            entity_count=len(out.entities),
            # The process record is written before the one-assignment publish.
            # "prepared" stays truthful even if the write itself then fails.
            validation_result="prepared",
            flags=list(out.warnings),
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        return response

    residual_failure = None
    try:
        result = SERVICE.sanitize_transaction(
            clean_text,
            mode=mode,
            session_id=request.session_id,
            finalize=finalize,
        )
    except SessionExpiredError:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    except ModeMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OutboundLeakError, OutboundPolicyError) as e:
        residual_failure = normalize_outbound_leak_types(e.leak_types)
        discard_exception_graph(e)

    if residual_failure is not None:
        safe_types = residual_failure
        write_process_log(
            session_id=operation_id,
            step="api_sanitize",
            entity_count=0,
            validation_result="blocked",
            flags=[f"leak_type:{t}" for t in safe_types],
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        request = None
        clean_text = ""
        finalize = None
        mode = None
        raise HTTPException(
            status_code=422,
            detail={"error": "residual_pii", "types": safe_types},
        )
    return result


@app.post("/api/reidentify")
@_contain_public_errors
def reidentify(request: ReidentifyRequest):
    """Restore original PII via the core reverse mapper + output validation."""
    start = time.time()
    operation_id = str(uuid.uuid4())
    _validate_text_input(request.text)
    try:
        out = SERVICE.restore(request.session_id, request.text)
    except SessionExpiredError:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    write_process_log(
        session_id=operation_id,
        step="api_reidentify",
        entity_count=out.replaced_count,
        validation_result="warn" if (out.leftover_tokens or out.warnings) else "pass",
        # VAULT-4: never log the pseudonym itself. The signed AI for Thai
        # proposal states the audit log holds only event type, counts and time,
        # and /api/audit-log echoes `flags` verbatim to any local caller.
        flags=([f"leftover_count:{len(out.leftover_tokens)}"] if out.leftover_tokens else []),
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "restored_text": out.restored_text,
        "replaced": out.replaced,
        "replaced_count": out.replaced_count,
        "leftover_tokens": out.leftover_tokens,
        "warnings": out.warnings,
    }


@app.delete("/api/session/{session_id}")
@_contain_public_errors
def delete_session(
    session_id: str,
    x_aiguard_token: Annotated[str | None, Header()] = None,
):
    # Control-plane endpoint: gated by the boot token when one is configured;
    # open (grace path) when it is not.
    if not _boot_token_ok(x_aiguard_token):
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    return {"deleted": SERVICE.drop(session_id)}


@app.post("/api/analyze")
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
    return result


@app.post("/api/analyze-report")
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
    return {
        "report_pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),
        "overall_score": analysis["overall_score"],
        "overall_grade": analysis["overall_grade"],
    }


@app.post("/api/detect")
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
    out = [
        {
            "start": e.span[0],
            "end": e.span[1],
            "data_type": e.data_type,
            "redact_type": e.redact_type,
        }
        for e in entities
    ]
    counts: dict[str, int] = {}
    for e in out:
        counts[e["data_type"]] = counts.get(e["data_type"], 0) + 1
    return {"entities": out, "entity_type_counts": counts}


# Hosted deployments narrow the provider surface (e.g. AIGUARD_PROVIDERS=
# "tokenmind") so ollama/claude/fake cannot appear on a public service by
# accident. Unset keeps the full registry — the local extension/desktop
# behavior, byte-for-byte. An unknown name fails the boot loudly (the
# registry's allowlist contract), never silently drops.
_PROVIDER_FACTORIES = get_provider_factories(
    allowed=_parse_csv_env(os.environ.get("AIGUARD_PROVIDERS")) or None
)


@app.post("/api/roundtrip")
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
        raise HTTPException(status_code=400, detail="Invalid mode: expected 'token' or 'surrogate'")
    factory = _PROVIDER_FACTORIES.get(request.provider)
    if factory is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: expected one of {sorted(_PROVIDER_FACTORIES)}",
        )
    provider_unavailable = False
    try:
        provider = factory()
    except Exception as error:
        discard_exception_graph(error)
        provider_unavailable = True
    if provider_unavailable:
        request = None
        factory = None
        raise HTTPException(status_code=503, detail="AI provider unavailable")

    clean_text = clean(request.text).text
    sanitize_failure = None
    try:
        masked = sanitize_stateless(clean_text, mode=request.mode, salt=uuid.uuid4().hex)
    except (OutboundPolicyError, StatelessLeakError) as error:
        sanitize_failure = normalize_outbound_leak_types(error.leak_types)
        discard_exception_graph(error)
    if sanitize_failure is not None:
        detail = _residual_detail(sanitize_failure)
        provider = None
        factory = None
        request = None
        clean_text = ""
        masked = None
        error = None
        raise HTTPException(status_code=422, detail=detail)

    rescan_failure = None
    try:
        enforce_outbound_policy(
            masked.sanitized_text,
            guard_context=masked.guard_context,
            scan_leaks=scan_outbound_leaks,
            scan_residual=scan_residual_signals,
        )
    except OutboundPolicyError as error:
        rescan_failure = normalize_outbound_leak_types(error.leak_types)
        discard_exception_graph(error)
    if rescan_failure is not None:
        detail = _residual_detail(rescan_failure)
        provider = None
        factory = None
        request = None
        clean_text = ""
        masked = None
        error = None
        raise HTTPException(status_code=422, detail=detail)

    provider_error_detail = None
    try:
        ai_text = complete_provider_call(
            provider,
            DEFAULT_SYSTEM_PROMPT,
            masked.sanitized_text,
        )
    except ProviderCallError as error:
        if error.category == "malformed":
            provider_error_detail = f"AI provider error: malformed response ({error.error_type})"
        elif error.category == "non_text":
            provider_error_detail = "AI provider error: malformed response (non-text)"
        else:
            provider_error_detail = f"AI provider error: {error.error_type}"
        discard_exception_graph(error)
    if provider_error_detail is not None:
        # The traceback is inspectable until FastAPI renders this exception.
        # Clear all locals that can reach credentials, input, or the transient
        # mapping before raising the fixed wire-safe error.
        provider = None
        factory = None
        request = None
        clean_text = ""
        masked = None
        ai_text = ""
        raise HTTPException(status_code=502, detail=provider_error_detail)
    restore_error_type = None
    try:
        restored = restore_stateless(ai_text, mapping=masked.mapping)
    except Exception as error:
        restore_error_type = type(error).__name__
        discard_exception_graph(error)
    if restore_error_type is not None:
        # A defect on OUR side after a successful provider call is a 500, not a
        # 502 -- and its message is not for the wire. Type name only.
        provider = None
        factory = None
        request = None
        clean_text = ""
        masked = None
        ai_text = ""
        restored = None
        raise HTTPException(
            status_code=500,
            detail=f"restore failed ({restore_error_type})",
        )

    guard_findings = to_wire(scan_injection(request.text))

    write_process_log(
        session_id=str(uuid.uuid4()),
        step="api_roundtrip",
        entity_count=len(masked.entities),
        validation_result="warn" if (masked.warnings or restored.warnings) else "pass",
        flags=[f"provider:{request.provider}"]
        + (
            [f"leftover_count:{len(restored.leftover_pseudonyms)}"]
            if restored.leftover_pseudonyms
            else []
        ),
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "sanitized_text": masked.sanitized_text,
        "ai_response_masked": ai_text,
        "restored_text": restored.restored_text,
        "entities": masked.entities,
        "entity_type_counts": masked.entity_type_counts,
        "provider_used": request.provider,
        "warnings": masked.warnings + restored.warnings,
        "guard": guard_findings,
    }


@app.post("/api/guard")
@_contain_public_errors
def guard(request: GuardRequest):
    """Dependency-light prompt-injection warning scan; blocks nothing.

    See pii_redactor/guard/injection.py: explicit rules plus bounded
    normalization/intent features in Thai and English; not airtight.
    """
    _validate_text_input(request.text)
    findings = to_wire(scan_injection(request.text))
    return {"guard": findings, "flagged": bool(findings)}


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
        raise HTTPException(status_code=400, detail="Empty text")
    if len(text) > _MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"text exceeds limit of {_MAX_TEXT_CHARS} characters",
        )


def _check_pdf_work_caps(pdf_path: Path) -> None:
    """Reject page-count / page-size bombs before any render or OCR work.

    Raises HTTPException 413 on a cap violation, 422 if the file cannot even
    be opened (with a fixed category — never the parser's exception text).
    """
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception:
        raise HTTPException(status_code=422, detail="Could not read PDF (unreadable file)")
    try:
        n_pages = len(pdf)
        if n_pages > _MAX_PDF_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF has {n_pages} pages (limit {_MAX_PDF_PAGES})",
            )
        for i in range(n_pages):
            page = pdf.get_page(i)
            try:
                width, height = page.get_size()
            finally:
                page.close()
            if width > _MAX_PDF_PAGE_POINTS or height > _MAX_PDF_PAGE_POINTS:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"PDF page {i + 1} exceeds {_MAX_PDF_PAGE_POINTS:g}pt in width or height"
                    ),
                )
    finally:
        pdf.close()


@app.post("/api/redact-pdf")
@_contain_public_errors
def redact_pdf(pdf_file: Annotated[UploadFile, File()]):
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
        raise HTTPException(status_code=400, detail="Only PDF files supported")

    # Sync endpoint on purpose (API-1): the heavy OCR/NER/render work must run
    # in FastAPI's threadpool, not on the event loop. pdf_file.file is the
    # underlying SpooledTemporaryFile, readable without await.
    chunks: list[bytes] = []
    size = 0
    while chunk := pdf_file.file.read(64 * 1024):
        size += len(chunk)
        if size > _MAX_PDF_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF exceeds size limit of {_MAX_PDF_BYTES} bytes",
            )
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
        except OCRUnavailableError as e:
            # our own static message (install requirements-ocr.txt) — safe
            raise HTTPException(status_code=503, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            # Category + exception TYPE only. The message of an arbitrary
            # parser error can quote file content, and this detail is public
            # (no-PII-in-errors rule).
            raise HTTPException(
                status_code=422,
                detail=f"Could not read PDF ({type(e).__name__})",
            )

        detect_text = clean_length_preserving(raw_text)
        entities = detect_all(detect_text)
        fp_count = sum(entity.redact_type == "FP" for entity in entities)
        registry = EntityRegistry(
            entities=entities,
            fp_count=fp_count,
            tb_count=len(entities) - fp_count,
        )

        redact_pdf_file(str(in_path), registry, word_bboxes, str(out_path))

        # unique field types, in order of first appearance
        seen = set()
        fields = []
        for e in entities:
            if e.data_type not in seen:
                seen.add(e.data_type)
                fields.append({"data_type": e.data_type, "redact_type": e.redact_type})

        human_review = bool(extract_meta.get("human_review", False))
        ocr_warnings = extract_meta.get("warnings", [])
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
        return {
            "filename": pdf_file.filename,
            "source_type": source_type,
            "ocr_confidence": extract_meta.get("ocr_confidence"),
            "human_review": human_review,
            "ocr_warnings": ocr_warnings,
            "entity_count": len(entities),
            "fields": fields,
            "section26": scan_section26(raw_text),
            "redacted_pdf_b64": base64.b64encode(out_path.read_bytes()).decode("ascii"),
            "before_png_b64": _first_page_png(str(in_path)),
            "after_png_b64": _first_page_png(str(out_path)),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
