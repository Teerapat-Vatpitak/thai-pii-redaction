"""Slice 4 Desktop trust-boundary and legacy-path regressions."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAURI = ROOT / "desktop" / "src-tauri"
FRONTEND = ROOT / "desktop" / "src"
PROTOCOL = json.loads((ROOT / "native-broker" / "protocol-v1.json").read_text("utf-8"))

EXPECTED_DESKTOP_OPERATIONS = {
    "analyze",
    "analyze_report",
    "audit_log",
    "broker_health",
    "detect",
    "guard",
    "redact_pdf",
    "reidentify",
    "roundtrip",
    "sanitize",
    "scope_close",
    "scope_open",
    "session_dispose",
}

EXPECTED_WEBVIEW_COMMANDS = {
    "desktop_analyze",
    "desktop_analyze_report",
    "desktop_audit_log",
    "desktop_copy_masked",
    "desktop_health",
    "desktop_redact_pdf",
    "desktop_reidentify",
    "desktop_sanitize",
    "desktop_scope_reset",
    "desktop_scope_rotate",
    "desktop_session_dispose",
    "quit_app",
    "update_check",
    "update_install",
}

EXPECTED_WEBVIEW_BROKER_OPERATIONS = {
    "analyze",
    "analyze_report",
    "audit_log",
    "broker_health",
    "redact_pdf",
    "reidentify",
    "sanitize",
    "scope_close",
    "session_dispose",
}


def _production_sources() -> str:
    paths = sorted((TAURI / "src").glob("*.rs")) + sorted(FRONTEND.glob("*.js"))
    paths.append(FRONTEND / "index.html")
    paths.append(TAURI / "tauri.conf.json")
    paths.append(TAURI / "Cargo.toml")
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def test_protocol_desktop_role_matrix_is_complete_and_unchanged():
    assert set(PROTOCOL["roles"]["desktop"]) == EXPECTED_DESKTOP_OPERATIONS
    assert set(PROTOCOL["scope_kinds"]["desktop"]) == {
        "desktop_hotkey",
        "desktop_ui",
    }
    assert "desktop-v2" not in PROTOCOL["roles"]
    assert "admin" not in PROTOCOL["roles"]
    assert "debug" not in PROTOCOL["roles"]


def test_webview_command_allowlist_is_exact_and_has_no_generic_escape_hatch():
    lib = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    match = re.search(
        r"const WEBVIEW_COMMAND_ALLOWLIST: &\[&str\] = &\[(?P<body>.*?)\];",
        lib,
        flags=re.DOTALL,
    )
    assert match, "Rust must publish one reviewable command allowlist"
    commands = set(re.findall(r'"([a-z0-9_]+)"', match.group("body")))
    assert commands == EXPECTED_WEBVIEW_COMMANDS
    assert not any(
        token in command
        for command in commands
        for token in ("raw", "arbitrary", "http", "url", "shell", "filesystem", "send")
    )

    handler_bodies = re.findall(
        r"tauri::generate_handler!\[(?P<body>.*?)\]",
        lib,
        flags=re.DOTALL,
    )
    assert len(handler_bodies) == 2, "default and smoke handlers must stay reviewable"
    registered = [
        {member.rsplit("::", 1)[-1] for member in re.findall(r"(?:[a-z0-9_]+::)*[a-z0-9_]+", body)}
        for body in handler_bodies
    ]
    smoke_only = {
        "desktop_package_smoke_ready",
        "desktop_package_smoke_finish",
        "desktop_package_smoke_fail",
    }
    assert EXPECTED_WEBVIEW_COMMANDS in registered
    assert EXPECTED_WEBVIEW_COMMANDS | smoke_only in registered
    assert ".invoke_handler(desktop_invoke_handler!())" in lib


def test_webview_broker_command_map_is_conformant_with_desktop_role():
    lib = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    match = re.search(
        r"const WEBVIEW_BROKER_COMMANDS: &\[\(&str, &str\)\] = &\[(?P<body>.*?)\];",
        lib,
        flags=re.DOTALL,
    )
    assert match
    pairs = re.findall(r'\("([a-z0-9_]+)", "([a-z0-9_]+)"\)', match.group("body"))
    assert len(pairs) == len(set(pairs))
    assert {command for command, _ in pairs} == EXPECTED_WEBVIEW_COMMANDS - {
        "quit_app",
        "update_check",
        "update_install",
    }
    assert {operation for _, operation in pairs} == EXPECTED_WEBVIEW_BROKER_OPERATIONS
    assert {"detect", "guard", "roundtrip"}.isdisjoint(operation for _, operation in pairs)


def test_production_desktop_has_no_direct_backend_or_provider_authority():
    sources = _production_sources().lower()
    forbidden = (
        "http://127.0.0.1",
        "http://localhost",
        "localhost:8000",
        "x-aiguard-key",
        "aiguard_api_key",
        "aiguard_token",
        "reqwest",
        "netstat",
        "lsof",
        "taskkill",
        "allow_attach",
        "provider retries",
        "openai_api_key",
        "anthropic_api_key",
        "gemini_api_key",
    )
    for marker in forbidden:
        assert marker not in sources


def test_installed_broker_configuration_is_fixed_without_removing_core_capabilities():
    policy = (ROOT / "native-broker" / "src" / "installed_product.rs").read_text(encoding="utf-8")
    desktop_client = (ROOT / "native-broker" / "src" / "desktop_client.rs").read_text(
        encoding="utf-8"
    )
    broker = (ROOT / "native-broker" / "src" / "broker.rs").read_text(encoding="utf-8")
    control_client = (ROOT / "native-broker" / "src" / "control_client.rs").read_text(
        encoding="utf-8"
    )
    backend = (ROOT / "native-broker" / "src" / "backend.rs").read_text(encoding="utf-8")
    process = (ROOT / "native-broker" / "src" / "process.rs").read_text(encoding="utf-8")
    data_plane = (ROOT / "native-broker" / "src" / "data_plane.rs").read_text(encoding="utf-8")

    assert 'pub(crate) const NER_ENGINE: &str = "thainer";' in policy
    assert 'pub(crate) const PROVIDER_POLICY: &str = "fake";' in policy
    for name in (
        "AIFORTHAI_API_KEY",
        "AIGUARD_FINETUNED_MODEL_DIR",
        "AIGUARD_NER_ENGINE",
        "AIGUARD_PROVIDERS",
        "ANTHROPIC_API_KEY",
        "TOKENMIND_ALLOW_HTTP",
        "TOKENMIND_API_KEY",
        "TOKENMIND_BASE_URL",
    ):
        assert f'"{name}"' in policy
    assert "validate_requested_configuration()?;" in desktop_client
    assert "validate_requested_configuration()?;" in broker
    assert "remote_tner" not in desktop_client
    assert "remote_tner_enabled" not in broker
    assert "configure_child_command(command);" in control_client
    assert "configure_child_command(&mut command);" in backend
    assert "installed_product::child_environment()" in process
    assert "installed_product::child_environment()" in backend
    assert "validate_desktop_provider_request" in data_plane
    assert "vars_os" not in policy
    assert "vars_os" not in process
    assert "vars_os" not in backend

    core_provider = (ROOT / "pii_redactor" / "ai_client.py").read_text(encoding="utf-8")
    core_detector = (ROOT / "pii_redactor" / "detectors" / "tb_detector.py").read_text(
        encoding="utf-8"
    )
    for provider in ("pathumma", "tokenmind", "claude", "ollama", "fake"):
        assert f'"{provider}"' in core_provider
    assert 'if name == "tner":' in core_detector


def test_legacy_sidecar_owner_is_removed_and_shell_plugin_is_not_linked():
    assert not (TAURI / "src" / "sidecar.rs").exists()
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    lib = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    assert "tauri-plugin-shell" not in cargo
    assert "tauri_plugin_shell" not in lib
    assert "mod sidecar" not in lib


def test_frontend_uses_typed_native_invoke_and_never_fetches():
    api = (FRONTEND / "api.js").read_text(encoding="utf-8")
    assert "fetch(" not in api
    assert "FormData" not in api
    assert "X-AIGuard-Contract-Version" not in api
    assert "window.__TAURI__?.core?.invoke" in api
    for command in EXPECTED_WEBVIEW_COMMANDS - {
        "quit_app",
        "update_check",
        "update_install",
    }:
        assert f'"{command}"' in api


def test_frontend_policy_copies_are_pinned_to_protocol_v1():
    api = (FRONTEND / "api.js").read_text(encoding="utf-8")
    errors = (FRONTEND / "errors.js").read_text(encoding="utf-8")
    limit = re.search(r"MAX_PDF_RAW_BYTES_V1 = ([0-9_]+);", api)
    assert limit
    assert int(limit.group(1).replace("_", "")) == PROTOCOL["framing"]["max_pdf_raw_bytes"]
    safe_messages = re.search(
        r"const SAFE_MESSAGES = new Map\(\[(?P<body>.*?)\]\);",
        errors,
        flags=re.DOTALL,
    )
    assert safe_messages
    codes = set(re.findall(r'^\s*\["([a-z_]+)"', safe_messages.group("body"), re.MULTILINE))
    assert codes == set(PROTOCOL["errors"])


def test_csp_has_no_localhost_networking_and_capabilities_remain_minimal():
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    csp = config["app"]["security"]["csp"].lower()
    assert "127.0.0.1" not in csp
    assert "http://localhost" not in csp
    connect_src = csp.split("connect-src ", 1)[1].split(";", 1)[0].split()
    assert connect_src == ["'self'", "ipc:", "http://ipc.localhost"]
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<script src="theme-bootstrap.js"></script>' in html
    assert "<script>" not in html
    capability = json.loads((TAURI / "capabilities" / "default.json").read_text(encoding="utf-8"))
    permissions = capability["permissions"]
    assert permissions == ["core:event:allow-listen"]
    rendered_capability = json.dumps(capability).lower()
    for forbidden in ("updater:", "filesystem", "shell", "http", "url", "allow-unlisten"):
        assert forbidden not in rendered_capability


def test_navigation_and_packaged_smoke_paths_stay_exact_and_feature_gated():
    lib = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    assert 'url.scheme() == "tauri" && url.host_str() == Some("localhost")' in lib
    assert 'url.scheme() == "http" && url.host_str() == Some("tauri.localhost")' in lib
    assert "#[cfg(windows)]" in lib
    assert "#[cfg(not(windows))]" in lib
    assert "url.port().is_none()" in lib
    assert "url.username().is_empty()" in lib
    assert "url.password().is_none()" in lib
    assert ".on_page_load(" in lib
    assert "PageLoadEvent::Started" in lib
    assert "ProcessFailedEventHandler" in lib
    assert "connect_web_process_terminated" in lib
    assert "on_web_content_process_terminate" in lib
    assert "broker::close_window(webview.app_handle(), webview.label())" in lib
    assert '#[cfg(feature = "package-smoke")]' in lib
    assert "default =" not in cargo
    assert "package-smoke = []" in cargo


def test_native_components_replace_python_as_desktop_runtime_authority():
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["bundle"]["externalBin"] == [
        "binaries/aiguard",
        "binaries/aiguard-native-broker",
        "binaries/aiguard-chrome-native-host",
        "binaries/aiguard-native-host-manager",
    ]
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    assert 'aiguard-native-broker-protocol = { path = "../../native-broker" }' in cargo


def test_ui_copy_has_no_endpoint_or_internal_identifier_disclosure():
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            FRONTEND / "index.html",
            FRONTEND / "app.js",
            FRONTEND / "screen-settings.js",
        ]
    ).lower()
    for marker in (
        "localhost",
        "127.0.0.1",
        "backend port",
        "socket",
        "named pipe",
        "session_id",
        "api key",
        "boot key",
    ):
        assert marker not in rendered


def test_slice5_and_slice6_are_not_started_by_desktop_migration():
    assert not (ROOT / "desktop" / "src" / "chrome-native").exists()
    assert not (ROOT / "desktop" / "src" / "extension-broker").exists()
