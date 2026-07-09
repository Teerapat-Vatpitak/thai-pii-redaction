"""FastAPI server for the AI Guard Thai PII redaction pipeline.

Local API backend for the browser extension (extension/). The extension runs
on chatgpt.com / claude.ai and calls these endpoints on localhost.

AI Guard uses TOKEN-mode pseudonymization (e.g. [ชื่อ_1]) so the round-trip
through an external AI is robust and visually explicit. The token -> original
map lives in an in-memory session store keyed by session_id. It is never
written to disk and never sent over the network — consistent with the
"vault never leaves the device" invariant for a local deployment.
"""
from __future__ import annotations

import base64
import glob
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from pii_redactor.audit import write_process_log
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.anonymizer.fp_generator import generate_fp
from pii_redactor.anonymizer.tb_generator import generate_tb
from pii_redactor.ingest.file_detector import detect_source_type
from pii_redactor.ingest.ocr_processor import OCRUnavailableError
from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.ingest.text_extractor import extract
from pii_redactor.redactor import redact_pdf as redact_pdf_file
from pii_redactor.models import EntityRegistry
from pii_redactor.report import generate_report, scan_section26
from pii_redactor.reid_risk import assess_reid_risk

app = FastAPI(
    title="AI Guard API",
    description="Thai PII Redaction Pipeline — PSU FTC 2026",
    version="2.2.0",
)

# CORS — the browser extension (content script on chatgpt.com / claude.ai)
# calls this backend cross-origin. No cookies are used, so a wildcard origin
# without credentials is safe for this localhost-only prototype.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


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
def shutdown():
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


# ── in-memory session store (token -> original maps) ───────────────────
# Bounded; oldest sessions evicted. In-memory only; never persisted.
_SESSIONS: dict[str, dict] = {}
_SESSION_CAP = 200


def _store_session(token_map: dict[str, str]) -> str:
    sid = str(uuid.uuid4())
    if len(_SESSIONS) >= _SESSION_CAP:
        oldest = min(_SESSIONS, key=lambda k: _SESSIONS[k]["created"])
        _SESSIONS.pop(oldest, None)
    _SESSIONS[sid] = {"token_map": token_map, "created": time.monotonic()}
    return sid


# ── token labels ───────────────────────────────────────────────────────
_TOKEN_LABEL = {
    "NAME": "ชื่อ", "SURNAME": "นามสกุล", "THAI_ID": "บัตรประชาชน",
    "PHONE": "โทรศัพท์", "EMAIL": "อีเมล", "ADDRESS": "ที่อยู่",
    "BANK_ACCOUNT": "บัญชีธนาคาร", "CREDIT_CARD": "บัตรเครดิต",
    "DATE_OF_BIRTH": "วันเกิด", "PASSPORT": "พาสปอร์ต",
    "STUDENT_ID": "รหัสนักศึกษา", "VEHICLE_PLATE": "ทะเบียนรถ", "IBAN": "ไอแบน",
}


def _dedupe_spans(entities: list) -> list:
    """Sort by start; drop entities overlapping an already-kept one.
    Prefers earlier start, then longer span."""
    ents = sorted(entities, key=lambda e: (e.span[0], -(e.span[1] - e.span[0])))
    kept = []
    last_end = -1
    for e in ents:
        s, en = e.span
        if s >= last_end:
            kept.append(e)
            last_end = en
    return kept


def _make_surrogate(entity, text: str, salt: str, used: set) -> str:
    """Generate a realistic, valid-format fake value for an entity.

    Unique within this document so re-identification is unambiguous: avoids
    duplicating another pseudonym or coinciding with text already present.
    """
    fake = ""
    for attempt in range(8):
        s = salt if attempt == 0 else f"{salt}:{attempt}"
        if entity.redact_type == "FP":
            fake = generate_fp(entity.data_type, entity.original_text, salt=s)
        else:
            ctx = text[: entity.span[0]] + "___" + text[entity.span[1] :]
            fake = generate_tb(entity.data_type, ctx, salt=s, original=entity.original_text)
        if fake and fake not in used and fake != entity.original_text and fake not in text:
            return fake
    return f"{fake}#{len(used) + 1}"  # last-resort disambiguation


def _tokenize(text: str, mode: str = "token") -> dict:
    """Detect PII, assign consistent pseudonyms, build sanitized text.

    mode="token"     -> bracket tokens like [ชื่อ_1] (explicit, robust)
    mode="surrogate" -> realistic valid-format fake data (reads naturally to the AI)

    Returns a dict with original_text, sanitized_text, entities[], token_map,
    entity_type_counts, section26[]. token_map maps pseudonym -> original.
    """
    fp = detect_fp(text)
    tb = detect_tb(text)
    fn = scan_fn(text, fp + tb)
    entities = _dedupe_spans(fp + tb + fn)

    salt = uuid.uuid4().hex
    # assign pseudonyms: same original value -> same pseudonym (consistency)
    token_map: dict[str, str] = {}       # pseudonym -> original
    by_original: dict[tuple, str] = {}    # (data_type, original) -> pseudonym
    counters: dict[str, int] = {}
    out_entities = []

    for e in entities:
        key = (e.data_type, e.original_text)
        if key in by_original:
            token = by_original[key]
        elif mode == "surrogate":
            token = _make_surrogate(e, text, salt, set(token_map))
            by_original[key] = token
            token_map[token] = e.original_text
        else:
            counters[e.data_type] = counters.get(e.data_type, 0) + 1
            label = _TOKEN_LABEL.get(e.data_type, e.data_type)
            token = f"[{label}_{counters[e.data_type]}]"
            by_original[key] = token
            token_map[token] = e.original_text
        out_entities.append({
            "start": e.span[0], "end": e.span[1],
            "data_type": e.data_type, "redact_type": e.redact_type,
            "token": token,
        })

    # build sanitized text (tail-first replacement preserves offsets)
    sanitized = text
    for e in sorted(out_entities, key=lambda x: x["start"], reverse=True):
        sanitized = sanitized[:e["start"]] + e["token"] + sanitized[e["end"]:]

    type_counts: dict[str, int] = {}
    for e in out_entities:
        type_counts[e["data_type"]] = type_counts.get(e["data_type"], 0) + 1

    return {
        "original_text": text,
        "sanitized_text": sanitized,
        "entities": out_entities,
        "token_map": token_map,
        "entity_type_counts": type_counts,
        "section26": scan_section26(text),
    }


# ── request models ─────────────────────────────────────────────────────
class SanitizeRequest(BaseModel):
    text: str
    mode: str = "token"  # "token" -> [ชื่อ_1] ; "surrogate" -> realistic fake data


class ReidentifyRequest(BaseModel):
    session_id: str
    text: str


class AnalyzeRequest(BaseModel):
    text: str


# ── endpoints ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.2.0"}


@app.get("/api/audit-log")
def get_audit_log(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Paginated, PII-free audit trail (newest first).

    Reads the JSONL files written by pii_redactor.audit.write_process_log /
    write_security_log, filtering to a safe field set that never echoes
    request text or vault content.
    """
    log_dir = _get_audit_log_dir()
    records = []
    for path in glob.glob(f"{log_dir}/audit_*.jsonl"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    safe = {"type": r.get("type"), "session_id": r.get("session_id"), "timestamp": r.get("timestamp")}
                    if r.get("type") == "process":
                        safe.update(step=r.get("step"), entity_count=r.get("entity_count"),
                                    validation_result=r.get("validation_result"),
                                    latency_ms=r.get("latency_ms"), flags=r.get("flags", []))
                    elif r.get("type") == "security":
                        safe.update(layer=r.get("layer"), pii_scan_result=r.get("pii_scan_result"),
                                    retry_count=r.get("retry_count"), error_type=r.get("error_type"),
                                    rollback_occurred=r.get("rollback_occurred"))
                    records.append(safe)
        except OSError:
            continue
    records.sort(key=lambda r: r.get("timestamp") or 0, reverse=True)
    total = len(records)
    return {"status": "ok", "total_count": total, "limit": limit, "offset": offset,
            "logs": records[offset:offset + limit]}


@app.post("/api/sanitize")
def sanitize(request: SanitizeRequest):
    start = time.time()
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    mode = request.mode if request.mode in ("token", "surrogate") else "token"
    clean_text = clean(request.text).text
    try:
        result = _tokenize(clean_text, mode)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(e))

    sid = _store_session(result["token_map"])
    write_process_log(
        session_id=sid,
        step="api_sanitize",
        entity_count=len(result["entities"]),
        validation_result="pass",
        flags=[],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "session_id": sid,
        "original_text": result["original_text"],
        "sanitized_text": result["sanitized_text"],
        "entities": result["entities"],
        "entity_type_counts": result["entity_type_counts"],
        "section26": result["section26"],
    }


@app.post("/api/reidentify")
def reidentify(request: ReidentifyRequest):
    """Restore original PII by replacing tokens using the stored session map."""
    start = time.time()
    session = _SESSIONS.get(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    token_map: dict[str, str] = session["token_map"]
    restored = request.text
    replaced = []
    # longest token first to avoid partial overlaps
    for token in sorted(token_map, key=len, reverse=True):
        if token in restored:
            restored = restored.replace(token, token_map[token])
            replaced.append({"token": token, "original": token_map[token]})

    leftover = [t for t in token_map if t in restored]  # tokens not restored

    write_process_log(
        session_id=request.session_id,
        step="api_reidentify",
        entity_count=len(replaced),
        validation_result="warn" if leftover else "pass",
        flags=[f"leftover:{t}" for t in leftover],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "restored_text": restored,
        "replaced": replaced,
        "replaced_count": len(replaced),
        "leftover_tokens": leftover,
    }


def _risk_label(score: float) -> str:
    return (
        "Very Low Risk" if score <= 20 else
        "Low Risk" if score <= 40 else
        "Medium Risk" if score <= 60 else
        "High Risk" if score <= 80 else
        "Very High Risk"
    )


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    start = time.time()
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    text = clean(request.text).text

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
        recs.append({
            "level": "high",
            "title": f"Remove or pseudonymize {report.direct_pii_count} direct PII entities",
            "desc": "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
        })
    if section26:
        cats = ", ".join(s["category"] for s in section26)
        recs.append({
            "level": "high",
            "title": f"Section 26 sensitive data found ({cats})",
            "desc": "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
        })
    if reid.high_risk_combo:
        recs.append({
            "level": "medium",
            "title": "Remove quasi-identifier combinations to reduce re-identification risk",
            "desc": "การรวม gender + district + age สามารถระบุตัวบุคคลได้แม้ไม่มี PII โดยตรง",
        })
    if report.overall_score >= 60:
        recs.append({
            "level": "info",
            "title": "Consider data minimization",
            "desc": "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
        })
    if not recs:
        recs.append({
            "level": "info",
            "title": "No significant PDPA risk detected",
            "desc": "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
        })

    write_process_log(
        session_id=str(uuid.uuid4()),
        step="api_analyze",
        entity_count=report.direct_pii_count,
        validation_result="pass",
        flags=[],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
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


def _first_page_png(pdf_path: str) -> str:
    """Render page 1 of a PDF to a base64 PNG (for before/after previews)."""
    from pii_redactor.pdf_render import render_page_png

    png = render_page_png(pdf_path, page_index=0)
    return base64.b64encode(png).decode("ascii")


@app.post("/api/redact-pdf")
async def redact_pdf(pdf_file: Annotated[UploadFile, File()]):
    """Redact PII in a text-layer or scanned PDF and return the redacted file + previews.

    Detection runs on the RAW extracted text (not cleaned) so entity text
    aligns with the word bboxes used to draw the black boxes — the text
    cleaner would shift char offsets. Scanned/image PDFs are routed through
    OCR (pii_redactor.ingest.ocr_processor) page by page; if the OCR
    dependencies (requirements-ocr.txt) aren't installed, this returns 503.
    """
    start = time.time()
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")

    contents = await pdf_file.read()
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

        fp = detect_fp(raw_text)
        tb = detect_tb(raw_text)
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
