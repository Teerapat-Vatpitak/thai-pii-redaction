#!/usr/bin/env python3
"""Run repeatable functional acceptance checks without recording raw PII.

Core checks exercise a running HTTP service. Live AI for Thai calls are opt-in
because they consume an external credential/quota:

    python scripts/run_acceptance.py
    python scripts/run_acceptance.py --live-pathumma --live-tner

Start the backend with ``AIGUARD_DEMO=1`` before running. Evidence contains
only statuses, counts, type names, timings, and output digests; never request
text, provider bodies, mappings, or credentials.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SYNTHETIC_TEXT = "ผมชื่อ นายสมชาย ใจดี โทร 081-234-5678"
SYNTHETIC_NAME = "นายสมชาย ใจดี"
SYNTHETIC_PHONE = "081-234-5678"
TNER_TEXT = "สมชาย ใจดี ทำงานที่บริษัท เอไอ การ์ด จำกัด ในกรุงเทพมหานคร วันที่ 22 กรกฎาคม 2569"
MARKER = "[AIGUARD_MARKER_7F3A]"


@dataclass
class CheckResult:
    check_id: str
    status: str
    elapsed_ms: int
    details: dict[str, object] = field(default_factory=dict)


class BlockedError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _checked(check_id: str, fn: Callable[[], dict[str, object]]) -> CheckResult:
    started = time.monotonic()
    try:
        details = fn()
        status = "pass"
    except BlockedError as exc:
        details = {"reason": exc.reason}
        status = "blocked"
    except Exception as exc:
        # Exception messages may contain upstream bodies or payload fragments.
        details = {"error_type": type(exc).__name__}
        status = "fail"
    return CheckResult(
        check_id=check_id,
        status=status,
        elapsed_ms=round((time.monotonic() - started) * 1000),
        details=details,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _request_json(client, method: str, path: str, **kwargs) -> tuple[int, dict]:
    response = client.request(method, path, **kwargs)
    try:
        body = response.json()
    except Exception as exc:
        raise AssertionError("response was not JSON") from exc
    _require(isinstance(body, dict), "response body must be an object")
    return response.status_code, body


def core_checks(client, root: Path = ROOT) -> list[CheckResult]:
    def health() -> dict[str, object]:
        status, body = _request_json(client, "GET", "/api/health")
        _require(status == 200 and body.get("status") == "ok", "health failed")
        return {
            "version": str(body.get("version", "")),
            "contract_version": body.get("contract_version"),
        }

    def playground() -> dict[str, object]:
        response = client.get("/demo")
        _require(response.status_code == 200, "demo is not enabled")
        _require("AI Guard" in response.text, "demo page is unexpected")
        _require(
            "ข้อมูลจริงไม่เคยออกจากเครื่องฝั่งผู้ใช้" not in response.text,
            "demo contains the invalid hosted privacy claim",
        )
        return {"http_status": response.status_code}

    def fake_roundtrip() -> dict[str, object]:
        status, body = _request_json(
            client,
            "POST",
            "/api/roundtrip",
            json={"text": SYNTHETIC_TEXT, "mode": "token", "provider": "fake"},
        )
        _require(status == 200, "fake roundtrip failed")
        sanitized = str(body.get("sanitized_text", ""))
        outbound = str(body.get("ai_response_masked", ""))
        _require(SYNTHETIC_NAME not in sanitized, "name remained in sanitized text")
        _require(SYNTHETIC_PHONE not in sanitized, "phone remained in sanitized text")
        _require(SYNTHETIC_NAME not in outbound, "name reached fake provider")
        _require(SYNTHETIC_PHONE not in outbound, "phone reached fake provider")
        _require(body.get("restored_text") == SYNTHETIC_TEXT, "restore was not exact")
        return {
            "entity_count": len(body.get("entities", [])),
            "entity_types": sorted(body.get("entity_type_counts", {})),
            "warning_count": len(body.get("warnings", [])),
        }

    def report() -> dict[str, object]:
        status, body = _request_json(
            client,
            "POST",
            "/api/analyze-report",
            json={"text": SYNTHETIC_TEXT},
        )
        _require(status == 200, "report failed")
        report_bytes = base64.b64decode(body.get("report_pdf_b64", ""), validate=True)
        _require(report_bytes.startswith(b"%PDF"), "report is not a PDF")
        return {
            "grade": str(body.get("overall_grade", "")),
            "pdf_sha256_12": hashlib.sha256(report_bytes).hexdigest()[:12],
        }

    def redact_pdf() -> dict[str, object]:
        source = root / "examples" / "sample_document.pdf"
        _require(source.is_file(), "sample PDF is missing")
        status, body = _request_json(
            client,
            "POST",
            "/api/redact-pdf",
            files={"pdf_file": (source.name, source.read_bytes(), "application/pdf")},
        )
        _require(status == 200, "PDF redaction failed")
        redacted = base64.b64decode(body.get("redacted_pdf_b64", ""), validate=True)
        before = base64.b64decode(body.get("before_png_b64", ""), validate=True)
        after = base64.b64decode(body.get("after_png_b64", ""), validate=True)
        _require(redacted.startswith(b"%PDF"), "redacted output is not a PDF")
        _require(
            before.startswith(b"\x89PNG") and after.startswith(b"\x89PNG"),
            "preview failed",
        )
        with pdfplumber.open(io.BytesIO(redacted)) as document:
            extracted = "".join(page.extract_text() or "" for page in document.pages)
        _require(not extracted.strip(), "redacted PDF retained a text layer")
        return {
            "entity_count": int(body.get("entity_count", 0)),
            "source_type": str(body.get("source_type", "")),
            "redacted_sha256_12": hashlib.sha256(redacted).hexdigest()[:12],
        }

    return [
        _checked("api.health", health),
        _checked("playground.enabled", playground),
        _checked("roundtrip.fake", fake_roundtrip),
        _checked("report.pdf", report),
        _checked("redaction.pdf", redact_pdf),
    ]


def pathumma_checks(client) -> list[CheckResult]:
    def completion() -> dict[str, object]:
        if not os.environ.get("AIFORTHAI_API_KEY"):
            raise BlockedError("AIFORTHAI_API_KEY is not set")
        from pii_redactor.ai_client import PathummaProvider

        system = "ตอบกลับด้วยข้อความของผู้ใช้ตามตัวอักษรทุกตัว ห้ามเพิ่ม ลบ หรือแก้ไข โดยเฉพาะข้อความในวงเล็บเหลี่ยม"
        user = "ยืนยันการทดสอบ " + MARKER
        response = PathummaProvider().complete(system, user, timeout=60.0)
        _require(bool(response.strip()), "provider returned an empty completion")
        return {
            # This is an observation, not a gate: a generative response may
            # legitimately omit an entity. The protected-roundtrip check below
            # is the safety gate and warns about unused pseudonyms.
            "marker_preserved": MARKER in response,
            "exact_echo": response.strip() == user,
            "response_length": len(response),
        }

    def protected_roundtrip() -> dict[str, object]:
        if not os.environ.get("AIFORTHAI_API_KEY"):
            raise BlockedError("AIFORTHAI_API_KEY is not set")
        status, body = _request_json(
            client,
            "POST",
            "/api/roundtrip",
            json={"text": SYNTHETIC_TEXT, "mode": "token", "provider": "pathumma"},
        )
        _require(status == 200, "Pathumma roundtrip failed")
        sanitized = str(body.get("sanitized_text", ""))
        outbound_response = str(body.get("ai_response_masked", ""))
        restored = str(body.get("restored_text", ""))
        for raw in (SYNTHETIC_NAME, SYNTHETIC_PHONE):
            _require(raw not in sanitized, "raw PII remained before provider call")
            _require(raw not in outbound_response, "raw PII appeared in provider response")
        sent_tokens = set(re.findall(r"\[[^\]\r\n]+_\d+\]", sanitized))
        returned_tokens = {token for token in sent_tokens if token in outbound_response}
        _require(
            not any(token in restored for token in returned_tokens),
            "a returned pseudonym was not restored",
        )
        return {
            "provider": str(body.get("provider_used", "")),
            "entity_count": len(body.get("entities", [])),
            "returned_token_count": len(returned_tokens),
            "warning_count": len(body.get("warnings", [])),
        }

    return [
        _checked("pathumma.completion", completion),
        _checked("pathumma.protected_roundtrip", protected_roundtrip),
    ]


def tner_checks() -> list[CheckResult]:
    def live_tagging() -> dict[str, object]:
        key = os.environ.get("AIFORTHAI_API_KEY", "")
        if not key:
            raise BlockedError("AIFORTHAI_API_KEY is not set")
        from pii_redactor.detectors.tner_client import TnerEngine

        tagged = TnerEngine(api_key=key).tag(TNER_TEXT)
        labels = sorted({label for _, label in tagged})
        _require(any(label.startswith("B-") for label in labels), "TNER returned no entities")
        return {
            "token_count": len(tagged),
            "labels": labels,
            "entity_tag_count": sum(label not in {"O", " "} for _, label in tagged),
        }

    def pipeline_mapping() -> dict[str, object]:
        if not os.environ.get("AIFORTHAI_API_KEY"):
            raise BlockedError("AIFORTHAI_API_KEY is not set")
        from pii_redactor.detectors import tb_detector

        previous = os.environ.get("AIGUARD_NER_ENGINE")
        tb_detector._ner_cache.pop("tner", None)
        os.environ["AIGUARD_NER_ENGINE"] = "tner"
        try:
            entities = tb_detector.detect_tb(TNER_TEXT)
        finally:
            tb_detector._ner_cache.pop("tner", None)
            if previous is None:
                os.environ.pop("AIGUARD_NER_ENGINE", None)
            else:
                os.environ["AIGUARD_NER_ENGINE"] = previous
        types = sorted({entity.data_type for entity in entities})
        _require("NAME" in types, "PER did not map to NAME")
        _require("LOCATION" in types, "LOC did not map to LOCATION")
        _require("DATE" in types, "DTM did not map to DATE")
        return {"entity_count": len(entities), "entity_types": types}

    return [
        _checked("tner.live_tagging", live_tagging),
        _checked("tner.pipeline_mapping", pipeline_mapping),
    ]


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _write_evidence(path: Path, base_url: str, results: list[CheckResult]) -> None:
    status_counts = {
        status: sum(result.status == status for result in results)
        for status in ("pass", "fail", "blocked")
    }
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        "git_commit": _git_commit(ROOT),
        "base_url": base_url,
        "summary": status_counts,
        "checks": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--live-pathumma", action="store_true")
    parser.add_argument("--live-tner", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "artifacts"
        / "acceptance"
        / f"acceptance-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    args = parser.parse_args()

    headers = {}
    if os.environ.get("AIGUARD_API_KEY"):
        headers["X-API-Key"] = os.environ["AIGUARD_API_KEY"]
    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers=headers,
        timeout=args.timeout,
    ) as client:
        results = core_checks(client)
        if args.live_pathumma:
            results.extend(pathumma_checks(client))
        if args.live_tner:
            results.extend(tner_checks())

    output = args.output.resolve()
    _write_evidence(output, args.base_url, results)
    for result in results:
        print(f"{result.status.upper():7} {result.check_id} ({result.elapsed_ms} ms)")
    print(f"evidence: {output}")

    if any(result.status == "fail" for result in results):
        return 1
    if any(result.status == "blocked" for result in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
