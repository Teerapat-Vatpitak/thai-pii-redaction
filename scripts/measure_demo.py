#!/usr/bin/env python3
r"""Booth-demo latency measurement against an ALREADY-RUNNING AI Guard backend.

Does NOT start a backend. Launch the desktop app (or `./run.ps1`) first, then
run this script to time the endpoints the live demo will hit:

    GET  /api/health
    POST /api/sanitize        (mode="token")
    POST /api/sanitize        (mode="surrogate")
    POST /api/reidentify      (using the token-mode session_id)
    POST /api/redact-pdf      (multipart pdf_file)

Windows console is cp1252 by default; set PYTHONUTF8=1 before running so the
Thai sample text round-trips correctly:

    $env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts\measure_demo.py

Exits non-zero (and prints a clear message) if the health check fails.
This script assumes AI Guard is already up, it never spawns one.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_TEXT_PATH = REPO_ROOT / "tests" / "fixtures" / "demo_sample_th.txt"
SAMPLE_PDF_PATH = REPO_ROOT / "examples" / "sample_document.pdf"

COMBINED_WARN_MS = 2000  # sanitize + reidentify combined budget


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def _timed(label: str, fn):
    start = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"{label:<32} {elapsed_ms:8.1f} ms")
    return result, elapsed_ms


def main() -> None:
    if not SAMPLE_TEXT_PATH.exists():
        _fail(f"missing sample text fixture: {SAMPLE_TEXT_PATH}")
    if not SAMPLE_PDF_PATH.exists():
        _fail(f"missing demo PDF: {SAMPLE_PDF_PATH}")

    sample_text = SAMPLE_TEXT_PATH.read_text(encoding="utf-8")

    print(f"== AI Guard booth-demo latency measurement ({BASE_URL}) ==\n")

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # ── health ──────────────────────────────────────────────────────
        try:
            health_resp, health_ms = _timed("GET  /api/health", lambda: client.get("/api/health"))
        except httpx.HTTPError as e:
            _fail(
                "could not reach the backend at 127.0.0.1:8000 - launch the "
                f"desktop app or ./run.ps1 first ({e})"
            )
            return  # unreachable, keeps type checkers happy

        if health_resp.status_code != 200 or health_resp.json().get("status") != "ok":
            _fail(
                f"/api/health did not return status ok (HTTP {health_resp.status_code}: "
                f"{health_resp.text})"
            )

        # ── sanitize: token mode ────────────────────────────────────────
        sanitize_token_resp, sanitize_token_ms = _timed(
            "POST /api/sanitize (token)",
            lambda: client.post("/api/sanitize", json={"text": sample_text, "mode": "token"}),
        )
        if sanitize_token_resp.status_code != 200:
            _fail(
                f"/api/sanitize (token) returned HTTP {sanitize_token_resp.status_code}: {sanitize_token_resp.text}"
            )
        sanitize_token = sanitize_token_resp.json()
        session_id = sanitize_token["session_id"]
        entity_count = len(sanitize_token["entities"])

        # ── sanitize: surrogate mode (same text, separate session) ─────
        sanitize_surrogate_resp, sanitize_surrogate_ms = _timed(
            "POST /api/sanitize (surrogate)",
            lambda: client.post("/api/sanitize", json={"text": sample_text, "mode": "surrogate"}),
        )
        if sanitize_surrogate_resp.status_code != 200:
            _fail(
                f"/api/sanitize (surrogate) returned HTTP {sanitize_surrogate_resp.status_code}: {sanitize_surrogate_resp.text}"
            )

        # ── reidentify: round-trip the token-mode session ───────────────
        sanitized_text = sanitize_token["sanitized_text"]
        reidentify_resp, reidentify_ms = _timed(
            "POST /api/reidentify",
            lambda: client.post(
                "/api/reidentify",
                json={"session_id": session_id, "text": sanitized_text},
            ),
        )
        if reidentify_resp.status_code != 200:
            _fail(
                f"/api/reidentify returned HTTP {reidentify_resp.status_code}: {reidentify_resp.text}"
            )
        reidentify = reidentify_resp.json()

        # ── redact-pdf ───────────────────────────────────────────────────
        def _redact_pdf():
            with open(SAMPLE_PDF_PATH, "rb") as f:
                files = {"pdf_file": (SAMPLE_PDF_PATH.name, f, "application/pdf")}
                return client.post("/api/redact-pdf", files=files)

        redact_resp, redact_ms = _timed("POST /api/redact-pdf", _redact_pdf)
        if redact_resp.status_code != 200:
            _fail(f"/api/redact-pdf returned HTTP {redact_resp.status_code}: {redact_resp.text}")
        redact = redact_resp.json()

    # ── summary ───────────────────────────────────────────────────────────
    print()
    print(f"entities detected (token mode):    {entity_count}")
    print(f"leftover tokens after reidentify:  {len(reidentify['leftover_tokens'])}")
    print(f"redact-pdf entity_count:           {redact['entity_count']}")
    print(f"redact-pdf source_type:            {redact['source_type']}")

    combined_ms = sanitize_token_ms + reidentify_ms
    print()
    print(f"sanitize(token) + reidentify combined: {combined_ms:8.1f} ms", end="")
    if combined_ms > COMBINED_WARN_MS:
        print(f"  ** exceeds {COMBINED_WARN_MS} ms budget **")
    else:
        print("  (within budget)")

    if reidentify["leftover_tokens"]:
        print(
            f"WARNING: {len(reidentify['leftover_tokens'])} token(s) were not restored: "
            f"{reidentify['leftover_tokens']}"
        )


if __name__ == "__main__":
    main()
