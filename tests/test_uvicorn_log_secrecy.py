"""Real Uvicorn access-log secrecy for bearer-like session control values."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.access_logging import UvicornAccessLogFilter
from app.session_control_auth import make_session_disposal_authorization

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_CONTRACT_HEADERS = {"X-AIGuard-Contract-Version": "2"}


def _unused_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {**_CONTRACT_HEADERS, **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url + path,
        data=payload,
        headers=request_headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_access_filter_suppresses_unrecognized_uvicorn_record_shape():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        "%s %s",
        ("DELETE", "/api/session/synthetic-session-authority"),
        None,
    )

    allowed = UvicornAccessLogFilter().filter(record)
    record.msg = ""
    record.args = ()

    assert allowed is False


@pytest.mark.parametrize("startup", ["launcher", "cli"])
def test_real_uvicorn_redacts_disposal_route_and_keeps_safe_access_logs(
    tmp_path,
    startup,
):
    port = _unused_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    control_secret = "synthetic-log-control-secret"
    synthetic_pii = "โทร 0812345678"
    query_authority = "synthetic-query-authority"
    repository_root = Path(__file__).resolve().parents[1]
    child_code = (
        "import sys, uvicorn; "
        "from app.server import app; "
        "from launcher import _uvicorn_log_config; "
        "uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), "
        "log_level='info', log_config=_uvicorn_log_config())"
    )
    if startup == "launcher":
        command = [sys.executable, "-c", child_code, str(port)]
    else:
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ]
    environment = os.environ.copy()
    environment.update(
        {
            "AIGUARD_TOKEN": control_secret,
            "AIGUARD_NO_BROWSER": "1",
            "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join(
                filter(
                    None,
                    (str(repository_root), environment.get("PYTHONPATH")),
                )
            ),
        }
    )
    environment.pop("AIGUARD_API_KEY", None)
    process = subprocess.Popen(
        command,
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    captured = ""
    session_id = ""
    authorization = ""
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                _request(base_url, "/api/health")
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline or process.poll() is not None:
                    pytest.fail("bounded Uvicorn instance did not become ready")
                time.sleep(0.05)

        _, created = _request(
            base_url,
            "/api/sanitize",
            method="POST",
            body={"text": synthetic_pii},
        )
        session_id = created["session_id"]
        authorization = make_session_disposal_authorization(
            control_secret,
            session_id,
            now=time.time(),
            nonce=b"l" * 16,
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            _request(
                base_url,
                f"/api/session/{session_id}?authority={query_authority}",
                method="DELETE",
                headers={"X-AIGuard-Token": "synthetic-invalid-authorization"},
            )
        assert rejected.value.code == 403
        status, deleted = _request(
            base_url,
            f"/api/session/{session_id}",
            method="DELETE",
            headers={"X-AIGuard-Token": authorization},
        )
        assert status == 200
        assert deleted == {"deleted": True}
        _request(
            base_url,
            "/api/shutdown",
            method="POST",
            headers={"X-AIGuard-Token": control_secret},
        )
        stdout, stderr = process.communicate(timeout=10)
        captured = stdout + stderr
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=5)
                captured += stdout + stderr
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                captured += stdout + stderr

    session_id_exposed = bool(session_id and session_id in captured)
    authorization_exposed = bool(authorization and authorization in captured)
    control_secret_exposed = control_secret in captured
    pii_exposed = synthetic_pii in captured
    query_authority_exposed = query_authority in captured
    safe_health_logged = "GET /api/health" in captured
    redacted_delete_logged = "DELETE /api/session/[redacted]" in captured
    captured = ""
    session_id = ""
    authorization = ""
    control_secret = ""
    synthetic_pii = ""
    query_authority = ""

    assert process.returncode == 0
    assert session_id_exposed is False
    assert authorization_exposed is False
    assert control_secret_exposed is False
    assert pii_exposed is False
    assert query_authority_exposed is False
    assert safe_health_logged is True
    assert redacted_delete_logged is True
