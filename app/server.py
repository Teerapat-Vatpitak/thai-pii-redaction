"""FastAPI server for the AI Guard Thai PII redaction pipeline.

Local API backend for the browser extension (extension/). The extension runs
on chatgpt.com / claude.ai and calls these endpoints on localhost.

AI Guard uses TOKEN-mode pseudonymization (e.g. [ชื่อ_1]) so the round-trip
through an external AI is robust and visually explicit. The token -> original
map lives in `pii_redactor.session_service.SessionService` (in-memory, keyed
by session_id). It is never written to disk and never sent over the network
— consistent with the "vault never leaves the device" invariant for a local
deployment.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pii_redactor.ai_client import (
    DEFAULT_SYSTEM_PROMPT,
    ClaudeProvider,
    FakeLLMProvider,
    OllamaProvider,
    PathummaProvider,
)
from pii_redactor.audit import write_process_log
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.ingest.file_detector import detect_source_type
from pii_redactor.ingest.ocr_processor import OCRUnavailableError
from pii_redactor.ingest.text_cleaner import clean, clean_length_preserving
from pii_redactor.ingest.text_extractor import extract
from pii_redactor.models import EntityRegistry
from pii_redactor.redactor import redact_pdf as redact_pdf_file
from pii_redactor.report import generate_report, scan_section26
from pii_redactor.stateless import (
    StatelessLeakError,
    restore_stateless,
    sanitize_stateless,
)


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
    return "2.3.0"


__version__ = _read_version()

app = FastAPI(
    title="AI Guard API",
    description="Thai PII Redaction Pipeline — PSU FTC 2026",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome-extension://[a-p]{32}|moz-extension://[0-9a-fA-F-]+|tauri://localhost|https?://tauri\.localhost)$",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1"],
)


# ── boot token (Horizon-1 #2) ──────────────────────────────────────────
# Random shared secret read once at import from the AIGUARD_TOKEN env var.
# Enforced ONLY on the control plane (`POST /api/shutdown`,
# `DELETE /api/session/{id}`) and ONLY when set — when it is None the grace
# path keeps the pre-token behavior byte-for-byte (X-AIGuard-Local for
# shutdown, open delete-session). launcher.py / Tauri generate a value and
# pass it in via the env; the value is never logged. Tests monkeypatch this
# module global directly, so the checks below read it dynamically at call time.
_BOOT_TOKEN: str | None = os.environ.get("AIGUARD_TOKEN") or None


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


def _get_audit_log_dir() -> str:
    """Audit log directory. Frozen exe -> %APPDATA%/AI Guard/logs; source -> ./logs."""
    if getattr(sys, "frozen", False):
        log_dir = Path.home() / "AppData" / "Roaming" / "AI Guard" / "logs"
    else:
        log_dir = Path.cwd() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir)


_SESSION_CAP = 200
_SESSION_TTL_S = 1800


def _now() -> float:
    return time.monotonic()


# The single core brain. now_fn is late-bound through the module global so
# tests that monkeypatch app.server._now keep working.
from pii_redactor.session_service import (
    ModeMismatchError,
    OutboundLeakError,
    SessionExpiredError,
    SessionService,
)

SERVICE = SessionService(cap=_SESSION_CAP, ttl_s=_SESSION_TTL_S, now_fn=lambda: _now())


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
    provider: str = "fake"  # "fake" | "pathumma" | "ollama" | "claude"


# ── endpoints ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
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
def sanitize(request: SanitizeRequest):
    start = time.time()
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    if request.mode is not None and request.mode not in ("token", "surrogate"):
        raise HTTPException(
            status_code=400,
            detail="Invalid mode: expected 'token' or 'surrogate'",
        )
    mode = request.mode
    clean_text = clean(request.text).text
    try:
        out = SERVICE.sanitize(clean_text, mode=mode, session_id=request.session_id)
    except SessionExpiredError:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    except ModeMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OutboundLeakError as e:
        write_process_log(
            session_id="blocked",
            step="api_sanitize",
            entity_count=0,
            validation_result="blocked",
            flags=[f"leak_type:{t}" for t in e.leak_types],
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        raise HTTPException(
            status_code=422,
            detail={"error": "pii_leak_risk", "types": e.leak_types},
        )

    write_process_log(
        session_id=out.session_id,
        step="api_sanitize",
        entity_count=len(out.entities),
        validation_result="warn" if out.warnings else "pass",
        flags=list(out.warnings),
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "session_id": out.session_id,
        "original_text": out.original_text,
        "sanitized_text": out.sanitized_text,
        "entities": out.entities,
        "entity_type_counts": out.entity_type_counts,
        "section26": out.section26,
        "warnings": out.warnings,
    }


@app.post("/api/reidentify")
def reidentify(request: ReidentifyRequest):
    """Restore original PII via the core reverse mapper + output validation."""
    start = time.time()
    try:
        out = SERVICE.restore(request.session_id, request.text)
    except SessionExpiredError:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    write_process_log(
        session_id=request.session_id,
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
def delete_session(
    session_id: str,
    x_aiguard_token: Annotated[str | None, Header()] = None,
):
    # Control-plane endpoint: gated by the boot token when one is configured;
    # open (grace path) when it is not.
    if not _boot_token_ok(x_aiguard_token):
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    return {"deleted": SERVICE.drop(session_id)}


def _risk_label(score: float) -> str:
    return (
        "Very Low Risk"
        if score <= 20
        else "Low Risk"
        if score <= 40
        else "Medium Risk"
        if score <= 60
        else "High Risk"
        if score <= 80
        else "Very High Risk"
    )


def _analyze_text(text: str) -> dict:
    """Assemble the full PDPA analysis for already-cleaned text.

    Shared by /api/analyze (JSON) and /api/analyze-report (PDF) so the two
    can never drift. Returns the exact response dict /api/analyze serves.
    """
    report = generate_report(text)
    reid = report.reid_risk

    fp = detect_fp(text)
    tb = detect_tb(text)

    # entity breakdown per data_type
    breakdown_map: dict[str, dict] = {}
    for e in fp + tb:
        key = e.data_type
        if key not in breakdown_map:
            breakdown_map[key] = {"data_type": key, "redact_type": e.redact_type, "count": 0}
        breakdown_map[key]["count"] += 1
    breakdown = sorted(breakdown_map.values(), key=lambda x: -x["count"])

    section26 = scan_section26(text)
    # Semantic pass: flag free-form sensitive content the keywords miss.
    # No-op (empty) when sentence-transformers is not installed.
    try:
        from pii_redactor.sensitive_detector import detect_sensitive

        have = {s["category"] for s in section26}
        for hit in detect_sensitive(text):
            if hit["category"] not in have:
                section26 = section26 + [{**hit, "source": "semantic"}]
                have.add(hit["category"])
    except Exception:  # pragma: no cover - defensive; model issues never block analyze
        pass

    # structured recommendations with severity levels
    recs = []
    if report.direct_pii_count > 0:
        recs.append(
            {
                "level": "high",
                "title": f"Remove or pseudonymize {report.direct_pii_count} direct PII entities",
                "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
            }
        )
    if section26:
        cats = ", ".join(s["category"] for s in section26)
        recs.append(
            {
                "level": "high",
                "title": f"Section 26 sensitive data found ({cats})",
                "desc": "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
            }
        )
    if reid.high_risk_combo:
        recs.append(
            {
                "level": "medium",
                "title": "Remove quasi-identifier combinations to reduce re-identification risk",
                "desc": "การรวม gender + district + age สามารถระบุตัวบุคคลได้แม้ไม่มี PII โดยตรง",
            }
        )
    if report.overall_score >= 60:
        recs.append(
            {
                "level": "info",
                "title": "Consider data minimization",
                "desc": "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
            }
        )
    if not recs:
        recs.append(
            {
                "level": "info",
                "title": "No significant PDPA risk detected",
                "desc": "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
            }
        )

    return {
        "overall_score": report.overall_score,
        "overall_grade": report.overall_grade,
        "risk_label": _risk_label(report.overall_score),
        "direct_pii_count": report.direct_pii_count,
        "fp_count": report.fp_count,
        "tb_count": report.tb_count,
        "section26": section26,
        "reid": {
            "score": reid.score,
            "grade": reid.grade,
            "qi_found": reid.qi_found,
            "high_risk_combo": reid.high_risk_combo,
        },
        "breakdown": breakdown,
        "recommendations": recs,
    }


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    start = time.time()
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    text = clean(request.text).text
    result = _analyze_text(text)
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


@app.post("/api/detect")
def detect(request: DetectRequest):
    """Detection only — no session, no vault, no persistence.

    Exists for the demo playground's live-highlight loop: /api/sanitize mints a
    session per call, which a keystroke-frequency caller would flood. Offsets
    must stay aligned with the caller's text, so this uses
    clean_length_preserving (same contract as the redact-pdf path), never
    clean().
    """
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
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


_PROVIDER_FACTORIES = {
    "fake": FakeLLMProvider,
    "pathumma": PathummaProvider,
    "ollama": OllamaProvider,
    "claude": ClaudeProvider,
}


@app.post("/api/roundtrip")
def roundtrip(request: RoundtripRequest):
    """mask -> LLM -> restore in one request, on the stateless core.

    The mapping lives only inside this request; nothing is stored server-side
    (the platform contract). `fake` is the identity provider so the demo can
    always run offline.
    """
    start = time.time()
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    if request.mode not in ("token", "surrogate"):
        raise HTTPException(status_code=400, detail="Invalid mode: expected 'token' or 'surrogate'")
    factory = _PROVIDER_FACTORIES.get(request.provider)
    if factory is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: expected one of {sorted(_PROVIDER_FACTORIES)}",
        )
    try:
        provider = factory()
    except ValueError as e:
        # provider knows its own missing-credential story (e.g. AIFORTHAI_API_KEY)
        raise HTTPException(status_code=503, detail=str(e))

    clean_text = clean(request.text).text
    try:
        masked = sanitize_stateless(clean_text, mode=request.mode, salt=uuid.uuid4().hex)
    except StatelessLeakError as e:
        raise HTTPException(
            status_code=422, detail={"error": "pii_leak_risk", "types": e.leak_types}
        )

    try:
        ai_text = provider.complete(DEFAULT_SYSTEM_PROMPT, masked.sanitized_text)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"AI provider error: {type(e).__name__}")
    except (IndexError, KeyError, TypeError, ValueError) as e:
        # A 200 with a malformed/unexpected body (e.g. missing "content") lands
        # here via the providers' resp.json()[...] — still a provider failure,
        # still a 502. Only the exception class name crosses the boundary.
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error: malformed response ({type(e).__name__})",
        )

    restored = restore_stateless(ai_text, mapping=masked.mapping)

    write_process_log(
        session_id="roundtrip",
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
    }


def _first_page_png(pdf_path: str) -> str:
    """Render page 1 of a PDF to a base64 PNG (for before/after previews)."""
    from pii_redactor.pdf_render import render_page_png

    png = render_page_png(pdf_path, page_index=0)
    return base64.b64encode(png).decode("ascii")


# Upload cap for /api/redact-pdf; enforced while streaming so an oversize
# body is rejected before it is fully buffered in memory.
_MAX_PDF_BYTES = 50 * 1024 * 1024


@app.post("/api/redact-pdf")
async def redact_pdf(pdf_file: Annotated[UploadFile, File()]):
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

    chunks: list[bytes] = []
    size = 0
    while chunk := await pdf_file.read(64 * 1024):
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
        try:
            source_type = detect_source_type(in_path)
            raw_text, word_bboxes, extract_meta = extract(in_path, source_type)
        except OCRUnavailableError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

        detect_text = clean_length_preserving(raw_text)
        fp = detect_fp(detect_text)
        tb = detect_tb(detect_text)
        entities = fp + tb
        registry = EntityRegistry(entities=entities, fp_count=len(fp), tb_count=len(tb))

        redact_pdf_file(str(in_path), registry, word_bboxes, str(out_path))

        # unique field types, in order of first appearance
        seen = set()
        fields = []
        for e in entities:
            if e.data_type not in seen:
                seen.add(e.data_type)
                fields.append({"data_type": e.data_type, "redact_type": e.redact_type})

        write_process_log(
            session_id=str(uuid.uuid4()),
            step="api_redact_pdf",
            entity_count=len(entities),
            validation_result="pass",
            flags=[f"source_type:{source_type}"],
            latency_ms=(time.time() - start) * 1000,
            output_dir=_get_audit_log_dir(),
        )
        return {
            "filename": pdf_file.filename,
            "source_type": source_type,
            "ocr_confidence": extract_meta.get("ocr_confidence"),
            "human_review": extract_meta.get("human_review", False),
            "ocr_warnings": extract_meta.get("warnings", []),
            "entity_count": len(entities),
            "fields": fields,
            "section26": scan_section26(raw_text),
            "redacted_pdf_b64": base64.b64encode(out_path.read_bytes()).decode("ascii"),
            "before_png_b64": _first_page_png(str(in_path)),
            "after_png_b64": _first_page_png(str(out_path)),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
