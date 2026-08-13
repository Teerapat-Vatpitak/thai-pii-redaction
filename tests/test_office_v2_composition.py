import json
import ssl
import subprocess
from types import SimpleNamespace
from urllib.request import ProxyHandler

import pytest

from scripts import office_v2_composition as composition

CONTRACT_HEADERS = {"X-AIGuard-Contract-Version": "2"}


def _health(*, control=True, api_key=False):
    return {
        "status": "ok",
        "version": composition.PRODUCT_VERSION,
        "contract_version": 2,
        "capabilities": {
            "control_token_required": control,
            "api_key_required": api_key,
        },
    }


def test_packaged_health_accepts_control_plane_protection_without_api_key():
    projected = composition.assert_packaged_health(_health())

    assert projected["capabilities"] == {
        "control_token_required": True,
        "api_key_required": False,
    }


@pytest.mark.parametrize(
    "body",
    [
        _health(control=False),
        _health(api_key=True),
        {**_health(), "token": "must-not-cross"},
        {
            **_health(),
            "capabilities": {
                **_health()["capabilities"],
                "control_token": "must-not-cross",
            },
        },
    ],
)
def test_packaged_health_rejects_wrong_or_secret_bearing_capabilities(body):
    with pytest.raises(composition.CompositionError, match="packaged health mismatch"):
        composition.assert_packaged_health(body)


def test_packaged_health_rejects_version_drift():
    body = {**_health(), "version": "9.9.9"}

    with pytest.raises(composition.CompositionError, match="packaged health mismatch"):
        composition.assert_packaged_health(body)


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, '{"status":"ready"}', composition.CertificateState.READY),
        (
            3,
            '{"status":"pending","reason":"certificate-files-missing"}',
            composition.CertificateState.PENDING,
        ),
        (
            3,
            '{"status":"pending","reason":"not-trusted-or-invalid"}',
            composition.CertificateState.PENDING,
        ),
        (
            1,
            '{"status":"error","reason":"verification-error"}',
            composition.CertificateState.ERROR,
        ),
    ],
)
def test_certificate_probe_protocol_is_bounded(returncode, stdout, expected):
    result = composition.parse_certificate_probe(returncode, stdout)

    assert result.state is expected
    assert set(result.as_dict()) <= {"status", "reason"}
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "must-not-cross" not in serialized


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (0, "{}"),
        (0, '{"status":"pending"}'),
        (3, '{"status":"ready"}'),
        (1, '{"status":"error","reason":"unexpected-detail"}'),
        (2, "not-json"),
    ],
)
def test_certificate_probe_rejects_ambiguous_or_unbounded_output(returncode, stdout):
    with pytest.raises(composition.CompositionError, match="certificate probe failed"):
        composition.parse_certificate_probe(returncode, stdout)


def test_v2_composition_exercises_health_sanitize_and_reidentify():
    calls = []
    source = "ผู้ติดต่อทดสอบ โทร 081-234-5678"
    prefix = "ผู้ติดต่อทดสอบ โทร "
    masked = f"{prefix}[PHONE_1_nsabcdefghijklmnopqrst]"

    def request_json(method, url, *, payload=None, ssl_context=None):
        calls.append((method, url, payload, ssl_context))
        if url.endswith("/api/health"):
            return 200, CONTRACT_HEADERS, _health()
        if url.endswith("/api/sanitize"):
            assert payload == {"text": source, "mode": "token"}
            return (
                200,
                CONTRACT_HEADERS,
                {
                    "session_id": "synthetic-session",
                    "sanitized_text": masked,
                    "detected_entity_count": 1,
                    "replacement_count": 1,
                    "entity_type_counts": {"PHONE": 1},
                    "highlights": [
                        {
                            "start": len(prefix),
                            "end": len(masked),
                            "data_type": "PHONE",
                            "redact_type": "FP",
                        }
                    ],
                    "section26_categories": [],
                    "guard_findings": [],
                    "warnings": [],
                    "safety": {"status": "pass", "residual_count": 0},
                },
            )
        assert url.endswith("/api/reidentify")
        assert payload == {
            "session_id": "synthetic-session",
            "text": masked,
        }
        return (
            200,
            CONTRACT_HEADERS,
            {
                "restored_text": source,
                "replaced_count": 1,
                "leftover_count": 0,
                "warnings": [],
            },
        )

    evidence = composition.exercise_v2_api(
        "https://localhost:3000",
        source_text=source,
        request_json=request_json,
        ssl_context=object(),
    )

    assert evidence == composition.ApiEvidence(
        detected_entity_count=1,
        replacement_count=1,
        restored_count=1,
    )
    assert [call[0] for call in calls] == ["GET", "POST", "POST"]
    assert [call[1].rsplit("/", 1)[-1] for call in calls] == [
        "health",
        "sanitize",
        "reidentify",
    ]
    assert all(call[3] is not None for call in calls)


def test_certificate_snapshot_detects_any_mutation_without_exporting_material():
    before = {
        "ca.crt": ("digest-a", 1),
        "localhost.crt": ("digest-b", 2),
        "localhost.key": ("digest-c", 3),
    }

    composition.assert_certificate_snapshot_unchanged(before, dict(before))
    with pytest.raises(composition.CompositionError, match="certificate files changed"):
        composition.assert_certificate_snapshot_unchanged(
            before,
            {**before, "localhost.key": ("changed", 4)},
        )


def test_certificate_probe_ignores_ambient_custom_directory(monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"status":"ready"}')

    monkeypatch.setenv("AIGUARD_OFFICE_CERT_DIR", "ambient-directory")
    monkeypatch.setattr(composition.subprocess, "run", run)

    result = composition.probe_existing_certificates()

    assert result.state is composition.CertificateState.READY
    assert "AIGUARD_OFFICE_CERT_DIR" not in captured["env"]
    assert captured["cwd"] == composition.OFFICE_ROOT


def test_packaged_environment_forces_offline_local_profile():
    environment = composition._packaged_environment(
        {
            "AIGUARD_NER_ENGINE": "tner",
            "AIFORTHAI_API_KEY": "must-not-cross",
            "AIGUARD_API_KEY": "must-not-cross",
            "AIGUARD_PROVIDERS": "pathumma",
            "ANTHROPIC_API_KEY": "must-not-cross",
            "TOKENMIND_API_KEY": "must-not-cross",
            "TOKENMIND_BASE_URL": "https://example.invalid/v1",
            "AIGUARD_TOKEN": "must-not-cross",
            "PYTHAINLP_ALLOW_UNSAFE_PICKLE": "must-not-cross",
            "PYTHAINLP_DATA": "must-not-cross",
            "PYTHAINLP_DATA_DIR": "must-not-cross",
            "PYTHAINLP_OFFLINE": "0",
            "PYTHAINLP_READ_MODE": "must-not-cross",
            "PYTHAINLP_READ_ONLY": "must-not-cross",
            "SAFE_UNRELATED": "kept",
        }
    )

    assert environment["AIGUARD_NER_ENGINE"] == "thainer"
    assert environment["PYTHAINLP_OFFLINE"] == "1"
    assert environment["AIGUARD_NO_BROWSER"] == "1"
    assert environment["AIGUARD_AUDIT_STDOUT"] == "1"
    assert environment["SAFE_UNRELATED"] == "kept"
    assert "must-not-cross" not in environment.values()
    assert (
        not {
            "PYTHAINLP_ALLOW_UNSAFE_PICKLE",
            "PYTHAINLP_DATA",
            "PYTHAINLP_DATA_DIR",
            "PYTHAINLP_READ_MODE",
            "PYTHAINLP_READ_ONLY",
        }
        & environment.keys()
    )


def test_sidecar_build_uses_the_same_sanitized_pythainlp_profile(monkeypatch):
    calls = []
    monkeypatch.setenv("PYTHAINLP_DATA", "must-not-cross")
    monkeypatch.setenv("PYTHAINLP_DATA_DIR", "must-not-cross")
    monkeypatch.setenv("PYTHAINLP_READ_ONLY", "must-not-cross")
    monkeypatch.setenv("SAFE_UNRELATED", "kept")
    monkeypatch.setattr(
        composition.subprocess,
        "check_call",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    monkeypatch.setattr(composition, "find_sidecar", lambda: "synthetic-sidecar")

    composition._run_builds(build_sidecar=True, build_office=True)

    build_environment = calls[1][1]["env"]
    assert build_environment["PYTHAINLP_OFFLINE"] == "1"
    assert build_environment["SAFE_UNRELATED"] == "kept"
    assert "must-not-cross" not in build_environment.values()


def test_loopback_opener_disables_ambient_proxies(monkeypatch):
    def fail_if_system_proxies_are_loaded():
        raise AssertionError("ambient proxies were consulted")

    monkeypatch.setattr(
        composition.urllib.request,
        "getproxies",
        fail_if_system_proxies_are_loaded,
    )
    opener = composition._direct_opener()
    proxy_handlers = [handler for handler in opener.handlers if isinstance(handler, ProxyHandler)]

    # An explicit empty ProxyHandler suppresses build_opener's default ambient
    # proxy handler. It has no protocol methods, so it is not retained.
    assert proxy_handlers == []


def test_supervisor_command_waits_for_hidden_process_tree():
    command = composition._supervisor_command(
        "C:\\Program Files\\Synthetic Tool\\tool.exe",
        ("run", "value-with-'quote"),
        composition.Path("C:\\synthetic-working-directory"),
    )

    assert command[:5] == [
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
    ]
    script = command[5]
    assert script.startswith("Start-Process ")
    assert "-WindowStyle Hidden" in script
    assert "-Wait" in script
    assert "Wait-Process" not in script
    assert "value-with-''quote" in script


def test_supervisor_suppresses_output_and_uses_hidden_console(monkeypatch):
    captured = {}
    sentinel = object()

    def popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(composition.subprocess, "Popen", popen)

    result = composition._start_supervised(
        "synthetic-program",
        arguments=("run",),
        working_directory=composition.Path("synthetic-directory"),
        environment={"SAFE": "1"},
    )

    assert result is sentinel
    assert "-WindowStyle Hidden" in captured["command"][-1]
    assert "-Wait" in captured["command"][-1]
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert captured["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert captured["env"] == {"SAFE": "1"}


def test_kill_tree_reaps_windows_descendants_after_wrapper_exit(monkeypatch):
    taskkill_calls = []
    wait_calls = []
    process = SimpleNamespace(
        pid=1234,
        poll=lambda: 1,
        wait=lambda *, timeout: wait_calls.append(timeout),
        kill=lambda: pytest.fail("Windows cleanup must use taskkill /T"),
    )
    monkeypatch.setattr(composition.os, "name", "nt")
    monkeypatch.setattr(
        composition,
        "taskkill_tree",
        lambda pid: taskkill_calls.append(pid),
    )

    composition._kill_tree(process)

    assert taskkill_calls == [1234]
    assert wait_calls == [15]


@pytest.mark.parametrize("failure_stage", ["api", "certificate", "proxy"])
def test_run_composition_failure_paths_reap_started_processes(
    monkeypatch,
    failure_stage,
):
    sidecar = SimpleNamespace(pid=1001)
    proxy = SimpleNamespace(pid=1002)
    killed = []
    checked_ports = []
    evidence = composition.ApiEvidence(1, 1, 1)

    monkeypatch.setattr(composition.sys, "platform", "win32")
    monkeypatch.setattr(composition, "_run_builds", lambda **_kwargs: None)
    monkeypatch.setattr(composition, "_start_sidecar", lambda: sidecar)
    monkeypatch.setattr(composition, "_start_office_proxy", lambda: proxy)
    monkeypatch.setattr(composition, "_backend_health_ready", lambda: True)
    monkeypatch.setattr(composition, "_office_page_ready", lambda _context: True)
    monkeypatch.setattr(composition, "_office_ssl_context", lambda _directory: object())
    monkeypatch.setattr(
        composition,
        "_wait_for",
        lambda predicate, _timeout: predicate(),
    )

    def port_is_free(port):
        checked_ports.append(port)
        return True

    monkeypatch.setattr(composition, "_port_is_free", port_is_free)
    monkeypatch.setattr(
        composition,
        "_kill_tree",
        lambda process: killed.append(process.pid),
    )
    monkeypatch.setattr(
        composition,
        "certificate_directory",
        lambda: composition.Path("unused-certificate-directory"),
    )
    snapshot = {"ca.crt": ("digest", 1)}
    monkeypatch.setattr(composition, "certificate_snapshot", lambda _path: snapshot)

    def certificate_probe():
        if failure_stage == "certificate":
            raise composition.CompositionError("certificate verification failed")
        return composition.CertificateProbe(composition.CertificateState.READY)

    monkeypatch.setattr(
        composition,
        "probe_existing_certificates",
        certificate_probe,
    )

    def exercise(base_url, **_kwargs):
        if failure_stage == "api" and base_url == composition.BACKEND_BASE:
            raise composition.CompositionError("HTTP v2 composition mismatch")
        if failure_stage == "proxy" and base_url == composition.OFFICE_BASE:
            raise composition.CompositionError("HTTP v2 composition mismatch")
        return evidence

    monkeypatch.setattr(composition, "exercise_v2_api", exercise)

    with pytest.raises(composition.CompositionError):
        composition.run_composition(
            build_sidecar=False,
            build_office=False,
            require_https=True,
        )

    if failure_stage == "proxy":
        assert killed == [proxy.pid, sidecar.pid]
        assert checked_ports.count(3000) == 2
    else:
        assert killed == [sidecar.pid]
        assert 3000 not in checked_ports
    assert checked_ports.count(8000) == 2


def test_cleanup_attempts_every_tree_when_one_kill_fails(monkeypatch):
    sidecar = SimpleNamespace(pid=2001)
    proxy = SimpleNamespace(pid=2002)
    killed = []

    def kill_tree(process):
        killed.append(process.pid)
        if process is proxy:
            raise OSError("private-path-must-not-cross")

    monkeypatch.setattr(composition, "_kill_tree", kill_tree)
    monkeypatch.setattr(composition, "_wait_for", lambda _predicate, _timeout: True)

    with pytest.raises(
        composition.CompositionError,
        match="composition process cleanup failed",
    ):
        composition._cleanup_composition(
            sidecar=sidecar,
            proxy=proxy,
            cert_dir=None,
            certificate_before=None,
        )

    assert killed == [proxy.pid, sidecar.pid]


@pytest.mark.parametrize(
    "error",
    [
        OSError("C:\\private\\must-not-cross"),
        ssl.SSLError("certificate-must-not-cross"),
        subprocess.SubprocessError("popen-must-not-cross"),
    ],
)
def test_main_bounds_unexpected_runtime_failures(monkeypatch, capsys, error):
    def fail(**_kwargs):
        raise error

    monkeypatch.setattr(composition, "run_composition", fail)

    result = composition.main(["--skip-sidecar-build", "--skip-office-build", "--require-https"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "FAIL: composition runtime failed\n"
    assert "must-not-cross" not in captured.err
