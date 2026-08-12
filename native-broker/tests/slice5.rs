use std::ffi::OsString;
use std::io::Cursor;

use aiguard_native_broker_protocol::extension_client::ExtensionClientError;
use aiguard_native_broker_protocol::extension_client::ExtensionScopeKind;
use aiguard_native_broker_protocol::manifest::NativeHostPolicy;
use aiguard_native_broker_protocol::native_messaging::{
    process_native_messages, validate_chrome_launch, BrowserProcessEvidence, ExtensionBroker,
    NativeMessagingSession, NATIVE_MESSAGE_MAX_BYTES,
};
use serde_json::{json, Value};

const ORIGIN: &str = "chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/";

#[derive(Default)]
struct FakeBroker {
    calls: Vec<(String, String, Option<String>)>,
    scope_index: usize,
    disconnected: bool,
    oversized_restore: bool,
}

impl ExtensionBroker for FakeBroker {
    fn health(&mut self) -> Result<(), ExtensionClientError> {
        self.calls.push(("health".into(), String::new(), None));
        Ok(())
    }

    fn open_scope(
        &mut self,
        scope_kind: ExtensionScopeKind,
    ) -> Result<String, ExtensionClientError> {
        self.scope_index += 1;
        let scope = format!("scope-{}", self.scope_index);
        self.calls.push((
            "scope_open".into(),
            scope_kind.as_protocol_value().into(),
            None,
        ));
        Ok(scope)
    }

    fn close_scope(&mut self, scope_id: &str) -> Result<(), ExtensionClientError> {
        self.calls
            .push(("scope_close".into(), scope_id.into(), None));
        Ok(())
    }

    fn sanitize(
        &mut self,
        scope_id: &str,
        _text: &str,
        mode: &str,
        session_id: Option<&str>,
    ) -> Result<Value, ExtensionClientError> {
        self.calls.push((
            format!("sanitize:{mode}"),
            scope_id.into(),
            session_id.map(str::to_owned),
        ));
        let suffix = scope_id.strip_prefix("scope-").unwrap();
        Ok(json!({
            "detected_entity_count": 1,
            "entity_type_counts": {"NAME": 1},
            "guard_findings": [],
            "highlights": [{"data_type": "NAME", "end": 8, "redact_type": "TB", "start": 0}],
            "replacement_count": 1,
            "safety": {"residual_count": 0, "status": "pass"},
            "sanitized_text": format!("[NAME_{suffix}]"),
            "section26_categories": [],
            "session_id": session_id.unwrap_or(&format!("session-{suffix}")),
            "warnings": []
        }))
    }

    fn reidentify(
        &mut self,
        scope_id: &str,
        session_id: &str,
        text: &str,
    ) -> Result<Value, ExtensionClientError> {
        self.calls.push((
            "reidentify".into(),
            scope_id.into(),
            Some(session_id.into()),
        ));
        Ok(json!({
            "leftover_count": 0,
            "replaced_count": 1,
            "restored_text": if self.oversized_restore {
                "x".repeat(NATIVE_MESSAGE_MAX_BYTES as usize)
            } else {
                format!("restored:{text}")
            },
            "warnings": []
        }))
    }

    fn disconnect(&mut self) {
        self.disconnected = true;
    }
}

fn policy(origin: &str) -> NativeHostPolicy {
    NativeHostPolicy::for_test(
        "th.ac.psu.aiguard.native_host",
        origin,
        "synthetic_test_only",
    )
}

fn browser(name: &str) -> BrowserProcessEvidence {
    BrowserProcessEvidence::for_test(name, true, true)
}

fn frame(value: &Value) -> Vec<u8> {
    let body = serde_json::to_vec(value).unwrap();
    let mut framed = Vec::with_capacity(4 + body.len());
    framed.extend_from_slice(&(body.len() as u32).to_ne_bytes());
    framed.extend_from_slice(&body);
    framed
}

fn decode_frames(mut bytes: &[u8]) -> Vec<Value> {
    let mut values = Vec::new();
    while !bytes.is_empty() {
        let length = u32::from_ne_bytes(bytes[..4].try_into().unwrap()) as usize;
        values.push(serde_json::from_slice(&bytes[4..4 + length]).unwrap());
        bytes = &bytes[4 + length..];
    }
    values
}

fn request(operation: &str, request_id: &str, context_id: Option<&str>, payload: Value) -> Value {
    let mut value = json!({
        "native_protocol_version": 1,
        "operation": operation,
        "payload": payload,
        "request_id": request_id
    });
    if let Some(context_id) = context_id {
        value["context_id"] = Value::String(context_id.into());
    }
    value
}

#[test]
fn launch_requires_exact_origin_service_worker_and_browser_process_context() {
    let exact = policy(ORIGIN);
    let windows_args = [OsString::from(ORIGIN), OsString::from("--parent-window=0")];
    let unix_args = [OsString::from(ORIGIN)];
    assert!(validate_chrome_launch(&windows_args, &exact, &browser("chrome.exe"), true).is_ok());
    assert!(validate_chrome_launch(&unix_args, &exact, &browser("google-chrome"), false).is_ok());

    for args in [
        vec![],
        vec![OsString::from(
            "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
        )],
        vec![OsString::from(ORIGIN), OsString::from("--parent-window=7")],
    ] {
        assert!(validate_chrome_launch(&args, &exact, &browser("chrome.exe"), true).is_err());
    }
    assert!(validate_chrome_launch(
        &unix_args,
        &policy("chrome-extension://*/"),
        &browser("google-chrome"),
        false
    )
    .is_err());
    assert!(validate_chrome_launch(&unix_args, &exact, &browser("powershell.exe"), false).is_err());
    assert!(validate_chrome_launch(
        &unix_args,
        &exact,
        &BrowserProcessEvidence::for_test("google-chrome", false, true),
        false,
    )
    .is_err());
}

#[test]
fn native_framing_rejects_partial_zero_invalid_and_oversized_messages_without_stdout() {
    let cases = [
        vec![1],
        0_u32.to_ne_bytes().to_vec(),
        ((NATIVE_MESSAGE_MAX_BYTES + 1) as u32)
            .to_ne_bytes()
            .to_vec(),
        {
            let mut value = 5_u32.to_ne_bytes().to_vec();
            value.extend_from_slice(b"{}");
            value
        },
        {
            let mut value = 2_u32.to_ne_bytes().to_vec();
            value.extend_from_slice(&[0xff, 0xfe]);
            value
        },
    ];
    for bytes in cases {
        let mut session = NativeMessagingSession::new(FakeBroker::default(), "2.5.0").unwrap();
        let mut stdout = Vec::new();
        assert!(process_native_messages(Cursor::new(bytes), &mut stdout, &mut session).is_err());
        assert!(stdout.is_empty());
    }
}

#[test]
fn malformed_unknown_duplicate_and_incompatible_requests_are_terminal_and_value_free() {
    let bodies = [
        br#"{"#.to_vec(),
        br#"{"native_protocol_version":1,"operation":"health","payload":{},"request_id":"id-1","unknown":1}"#.to_vec(),
        br#"{"native_protocol_version":1,"operation":"health","operation":"sanitize","payload":{},"request_id":"id-1"}"#.to_vec(),
        br#"{"native_protocol_version":2,"operation":"health","payload":{},"request_id":"id-1"}"#.to_vec(),
        br#"{"native_protocol_version":1,"operation":"pdf","payload":{"text":"pii-sentinel"},"request_id":"id-1"}"#.to_vec(),
    ];
    for body in bodies {
        let mut input = (body.len() as u32).to_ne_bytes().to_vec();
        input.extend_from_slice(&body);
        let mut session = NativeMessagingSession::new(FakeBroker::default(), "2.5.0").unwrap();
        let mut stdout = Vec::new();
        assert!(process_native_messages(Cursor::new(input), &mut stdout, &mut session).is_err());
        assert!(!String::from_utf8_lossy(&stdout).contains("pii-sentinel"));
    }
}

#[test]
fn one_connection_keeps_tab_and_panel_scopes_and_broker_sessions_internal() {
    let messages = [
        request("health", "r1", None, json!({})),
        request(
            "scope_open",
            "r2",
            Some("tab-a"),
            json!({"scope_kind": "tab"}),
        ),
        request(
            "scope_open",
            "r3",
            Some("panel-a"),
            json!({"scope_kind": "panel"}),
        ),
        request(
            "sanitize",
            "r4",
            Some("tab-a"),
            json!({"mode": "token", "text": "synthetic-a"}),
        ),
        request(
            "sanitize",
            "r5",
            Some("panel-a"),
            json!({"mode": "surrogate", "text": "synthetic-b"}),
        ),
        request(
            "sanitize",
            "r6",
            Some("tab-a"),
            json!({"mode": "token", "text": "synthetic-c"}),
        ),
        request(
            "reidentify",
            "r7",
            Some("tab-a"),
            json!({"text": "masked-a"}),
        ),
        request(
            "reidentify",
            "r8",
            Some("panel-a"),
            json!({"text": "masked-b"}),
        ),
        request("scope_close", "r9", Some("tab-a"), json!({})),
        request(
            "reidentify",
            "r10",
            Some("panel-a"),
            json!({"text": "masked-c"}),
        ),
    ];
    let input = messages.iter().flat_map(frame).collect::<Vec<_>>();
    let mut session = NativeMessagingSession::new(FakeBroker::default(), "2.5.0").unwrap();
    let mut stdout = Vec::new();
    process_native_messages(Cursor::new(input), &mut stdout, &mut session).unwrap();
    let responses = decode_frames(&stdout);
    assert_eq!(responses.len(), messages.len());
    assert!(responses.iter().all(|response| response["ok"] == true));
    assert!(responses
        .iter()
        .all(|response| response.get("scope_id").is_none()));
    assert!(responses
        .iter()
        .all(|response| response.to_string().find("session-").is_none()));
    assert_eq!(responses[6]["result"]["restored_text"], "restored:masked-a");
    assert_eq!(responses[7]["result"]["restored_text"], "restored:masked-b");
    assert_eq!(responses[9]["result"]["restored_text"], "restored:masked-c");

    let calls = &session.broker_for_test().calls;
    assert_eq!(calls[5].2.as_deref(), Some("session-1"));
    assert_eq!(calls[8], ("scope_close".into(), "scope-1".into(), None));
}

#[test]
fn duplicate_request_id_and_cross_context_restore_fail_closed() {
    let messages = [
        request(
            "scope_open",
            "same",
            Some("tab-a"),
            json!({"scope_kind": "tab"}),
        ),
        request(
            "scope_open",
            "same",
            Some("tab-b"),
            json!({"scope_kind": "tab"}),
        ),
    ];
    let input = messages.iter().flat_map(frame).collect::<Vec<_>>();
    let mut session = NativeMessagingSession::new(FakeBroker::default(), "2.5.0").unwrap();
    let mut stdout = Vec::new();
    assert!(process_native_messages(Cursor::new(input), &mut stdout, &mut session).is_err());
    assert_eq!(decode_frames(&stdout).len(), 1);

    let messages = [
        request(
            "scope_open",
            "a1",
            Some("tab-a"),
            json!({"scope_kind": "tab"}),
        ),
        request(
            "scope_open",
            "b1",
            Some("tab-b"),
            json!({"scope_kind": "tab"}),
        ),
        request(
            "sanitize",
            "a2",
            Some("tab-a"),
            json!({"mode": "token", "text": "synthetic"}),
        ),
        request(
            "reidentify",
            "b2",
            Some("tab-b"),
            json!({"text": "[NAME_1]"}),
        ),
    ];
    let input = messages.iter().flat_map(frame).collect::<Vec<_>>();
    let mut session = NativeMessagingSession::new(FakeBroker::default(), "2.5.0").unwrap();
    let mut stdout = Vec::new();
    process_native_messages(Cursor::new(input), &mut stdout, &mut session).unwrap();
    let responses = decode_frames(&stdout);
    assert_eq!(responses[3]["ok"], false);
    assert_eq!(responses[3]["error"]["code"], "session_unavailable");
    assert!(!responses[3].to_string().contains("[NAME_1]"));
}

#[test]
fn host_response_above_chromes_limit_is_replaced_and_disconnects_every_scope() {
    let messages = [
        request(
            "scope_open",
            "r1",
            Some("tab-a"),
            json!({"scope_kind": "tab"}),
        ),
        request(
            "sanitize",
            "r2",
            Some("tab-a"),
            json!({"mode": "token", "text": "synthetic"}),
        ),
        request("reidentify", "r3", Some("tab-a"), json!({"text": "masked"})),
    ];
    let input = messages.iter().flat_map(frame).collect::<Vec<_>>();
    let broker = FakeBroker {
        oversized_restore: true,
        ..FakeBroker::default()
    };
    let mut session = NativeMessagingSession::new(broker, "2.5.0").unwrap();
    let mut stdout = Vec::new();
    assert!(process_native_messages(Cursor::new(input), &mut stdout, &mut session).is_err());
    let responses = decode_frames(&stdout);
    assert_eq!(responses.len(), 3);
    assert_eq!(responses[2]["error"]["code"], "payload_too_large");
    assert!(session.broker_for_test().disconnected);
    assert!(stdout.len() < NATIVE_MESSAGE_MAX_BYTES as usize);
}
