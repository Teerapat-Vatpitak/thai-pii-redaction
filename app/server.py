"""FastAPI server for the AI Guard Thai PII redaction pipeline."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pii_redactor.pipeline import run_pipeline
from pii_redactor.ai_client import FakeLLMProvider, OllamaProvider
from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.ingest.text_cleaner import clean

app = FastAPI(
    title="AI Guard API",
    description="Thai PII Redaction Pipeline — PSU FTC 2026",
    version="1.0.0",
)

_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/static/index.html")


class SanitizeRequest(BaseModel):
    text: str
    provider: str = "fake"  # "fake" | "ollama"


class ReidentifyRequest(BaseModel):
    text: str
    provider: str = "fake"


class AnalyzeRequest(BaseModel):
    text: str


def _get_provider(provider_name: str):
    if provider_name == "fake":
        return FakeLLMProvider()
    elif provider_name == "ollama":
        return OllamaProvider()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/sanitize")
def sanitize(request: SanitizeRequest):
    provider = _get_provider(request.provider)
    try:
        result = run_pipeline(text=request.text, provider=provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "session_id": result.session_id,
        "pseudonymized_text": result.pseudonymized_text,
        "entity_count": len(result.entity_registry.entities),
    }


@app.post("/api/reidentify")
def reidentify(request: ReidentifyRequest):
    """Run full pipeline and return restored text (FakeLLM round-trip demo)."""
    provider = _get_provider(request.provider)
    try:
        result = run_pipeline(text=request.text, provider=provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "restored_text": result.reverse_result.text,
        "flags": result.reverse_result.flags,
    }


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    clean_result = clean(request.text)
    text = clean_result.text

    fp_entities = detect_fp(text)
    tb_entities = detect_tb(text)

    total = len(fp_entities) + len(tb_entities)
    if total == 0:
        risk = "Low"
    elif total <= 5:
        risk = "Medium"
    else:
        risk = "High"

    type_counts: dict[str, int] = {}
    for e in fp_entities + tb_entities:
        type_counts[e.data_type] = type_counts.get(e.data_type, 0) + 1

    return {
        "entity_count": total,
        "fp_count": len(fp_entities),
        "tb_count": len(tb_entities),
        "risk_level": risk,
        "entity_types": type_counts,
    }


@app.post("/api/redact-pdf")
async def redact_pdf(pdf_file: Annotated[UploadFile, File()]):
    """Analyze a PDF for PII. Returns analysis report, not a redacted file.

    Note: For the contest demo, this endpoint returns an analysis report only.
    Actual bbox-level PDF redaction (black boxes) requires file I/O and is
    handled separately in pii_redactor/redactor.py.
    """
    if not pdf_file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")

    contents = await pdf_file.read()

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=io.BytesIO(contents), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

    fp_entities = detect_fp(text)
    tb_entities = detect_tb(text)
    total = len(fp_entities) + len(tb_entities)

    return {
        "entity_count": total,
        "message": f"Redaction analysis complete. {total} entities found.",
    }
