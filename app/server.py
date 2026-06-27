"""FastAPI server for the AI Guard Thai PII redaction pipeline.

Web API behind the vanilla-JS frontend in app/static/.

AI Guard uses TOKEN-mode pseudonymization (e.g. [ชื่อ_1]) so the round-trip
through an external AI is robust and visually explicit. The token -> original
map lives in an in-memory session store keyed by session_id. It is never
written to disk and never sent over the network — consistent with the
"vault never leaves the device" invariant for a local deployment.
"""
from __future__ import annotations

import io
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.detectors.fn_scanner import scan_fn
from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.report import generate_report, scan_section26
from pii_redactor.reid_risk import assess_reid_risk

app = FastAPI(
    title="AI Guard API",
    description="Thai PII Redaction Pipeline — PSU FTC 2026",
    version="2.0.0",
)

_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/index.html")


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


def _tokenize(text: str) -> dict:
    """Detect PII, assign consistent tokens, build sanitized text.

    Returns a dict with original_text, sanitized_text, entities[], token_map,
    entity_type_counts, section26[].
    """
    fp = detect_fp(text)
    tb = detect_tb(text)
    fn = scan_fn(text, fp + tb)
    entities = _dedupe_spans(fp + tb + fn)

    # assign tokens: same original value -> same token (consistency)
    token_map: dict[str, str] = {}       # token -> original
    by_original: dict[tuple, str] = {}    # (data_type, original) -> token
    counters: dict[str, int] = {}
    out_entities = []

    for e in entities:
        key = (e.data_type, e.original_text)
        if key in by_original:
            token = by_original[key]
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


class ReidentifyRequest(BaseModel):
    session_id: str
    text: str


class AnalyzeRequest(BaseModel):
    text: str


# ── endpoints ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/api/sanitize")
def sanitize(request: SanitizeRequest):
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    clean_text = clean(request.text).text
    try:
        result = _tokenize(clean_text)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=str(e))

    sid = _store_session(result["token_map"])
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


@app.post("/api/redact-pdf")
async def redact_pdf(pdf_file: Annotated[UploadFile, File()]):
    """Analyze a PDF for PII. Returns detected field types for the redaction view.

    Note: actual bbox-level PDF redaction (black boxes) is handled in
    pii_redactor/redactor.py; this endpoint returns the analysis used to
    drive the redaction preview.
    """
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")

    contents = await pdf_file.read()
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=io.BytesIO(contents), filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

    text = clean(text).text
    fp = detect_fp(text)
    tb = detect_tb(text)
    entities = fp + tb

    # unique field types, in order of first appearance
    seen = set()
    fields = []
    for e in entities:
        if e.data_type not in seen:
            seen.add(e.data_type)
            fields.append({"data_type": e.data_type, "redact_type": e.redact_type})

    return {
        "filename": pdf_file.filename,
        "entity_count": len(entities),
        "fields": fields,
        "section26": scan_section26(text),
    }
