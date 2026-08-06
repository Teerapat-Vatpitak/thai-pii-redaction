use serde::Deserialize;
use std::collections::{BTreeMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Manager};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Default)]
pub struct HotkeyState {
    pub last_session: Mutex<Option<String>>,
}

const BASE: &str = "http://127.0.0.1:8000";
const CONTRACT_HEADER: &str = "X-AIGuard-Contract-Version";
const CONTRACT_VERSION: &str = "2";
static HOTKEY_BUSY: AtomicBool = AtomicBool::new(false);

struct HotkeyBusyGuard;

impl HotkeyBusyGuard {
    fn acquire() -> Option<Self> {
        HOTKEY_BUSY
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .ok()
            .map(|_| Self)
    }
}

impl Drop for HotkeyBusyGuard {
    fn drop(&mut self) {
        HOTKEY_BUSY.store(false, Ordering::Release);
    }
}

#[derive(Debug, PartialEq)]
enum MaskOutcome {
    Masked { session_id: String, masked: String },
    RetryFresh,
    Failed(String),
}

#[derive(Debug, PartialEq)]
enum RestoreOutcome {
    Restored(String),
    Failed(String),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HealthCapabilities {
    control_token_required: bool,
    api_key_required: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HealthResponse {
    status: String,
    version: String,
    contract_version: u8,
    capabilities: HealthCapabilities,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Safety {
    status: String,
    residual_count: usize,
}

#[derive(Deserialize)]
#[serde(rename_all = "UPPERCASE")]
enum RedactType {
    Fp,
    Tb,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Highlight {
    start: usize,
    end: usize,
    data_type: String,
    redact_type: RedactType,
}

#[derive(Clone, Copy, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd)]
enum Section26Category {
    #[serde(rename = "RACE_ETHNICITY")]
    RaceEthnicity,
    #[serde(rename = "POLITICAL_OPINION")]
    PoliticalOpinion,
    #[serde(rename = "RELIGION")]
    Religion,
    #[serde(rename = "HEALTH")]
    Health,
    #[serde(rename = "SEXUAL_BEHAVIOR")]
    SexualBehavior,
    #[serde(rename = "CRIMINAL_RECORD")]
    CriminalRecord,
    #[serde(rename = "DISABILITY")]
    Disability,
    #[serde(rename = "LABOR_UNION")]
    LaborUnion,
}

#[derive(Clone, Deserialize, Eq, Hash, PartialEq)]
enum GuardCategory {
    #[serde(rename = "instruction_override")]
    InstructionOverride,
    #[serde(rename = "role_hijack")]
    RoleHijack,
    #[serde(rename = "exfiltration")]
    Exfiltration,
    #[serde(rename = "hidden_chars")]
    HiddenChars,
    #[serde(rename = "suspicious_payload")]
    SuspiciousPayload,
}

#[derive(Clone, Deserialize, Eq, Hash, PartialEq)]
enum GuardSeverity {
    #[serde(rename = "low")]
    Low,
    #[serde(rename = "medium")]
    Medium,
    #[serde(rename = "high")]
    High,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GuardFinding {
    category: GuardCategory,
    severity: GuardSeverity,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SanitizeResponse {
    session_id: String,
    sanitized_text: String,
    detected_entity_count: usize,
    replacement_count: usize,
    entity_type_counts: BTreeMap<String, usize>,
    highlights: Vec<Highlight>,
    section26_categories: Vec<Section26Category>,
    guard_findings: Vec<GuardFinding>,
    warnings: Vec<serde_json::Value>,
    safety: Safety,
}

#[derive(Clone, Deserialize, Eq, Hash, PartialEq)]
enum RestoreWarningCode {
    #[serde(rename = "generated_pii")]
    GeneratedPii,
    #[serde(rename = "foreign_replacement")]
    ForeignReplacement,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RestoreWarning {
    code: RestoreWarningCode,
    count: usize,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReidentifyResponse {
    restored_text: String,
    replaced_count: usize,
    leftover_count: usize,
    warnings: Vec<RestoreWarning>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ErrorEnvelope {
    error: ErrorDetail,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ErrorDetail {
    code: String,
    category: String,
    count: usize,
    retryable: bool,
    status: u16,
}

fn exact_contract_header(values: &[&str]) -> bool {
    values.len() == 1 && values[0] == CONTRACT_VERSION
}

fn error_spec(code: &str) -> Option<(u16, &'static str, bool)> {
    match code {
        "contract_version_required" => Some((426, "contract", false)),
        "invalid_request" => Some((400, "request", false)),
        "request_schema_invalid" => Some((422, "request", false)),
        "authentication_required" => Some((401, "authentication", false)),
        "control_forbidden" => Some((403, "authentication", false)),
        "route_not_found" => Some((404, "request", false)),
        "session_unavailable" => Some((404, "session", false)),
        "method_not_allowed" => Some((405, "request", false)),
        "rate_limited" => Some((429, "service", true)),
        "payload_too_large" => Some((413, "request", false)),
        "residual_pii" => Some((422, "privacy", false)),
        "document_invalid" => Some((422, "document", false)),
        "provider_unavailable" => Some((502, "upstream", true)),
        "provider_rejected" => Some((502, "upstream", false)),
        "provider_response_invalid" => Some((502, "upstream", false)),
        "ner_incomplete" => Some((502, "upstream", false)),
        "provider_configuration" => Some((503, "configuration", false)),
        "dependency_unavailable" => Some((503, "dependency", false)),
        "ocr_unavailable" => Some((503, "dependency", false)),
        "service_unavailable" => Some((503, "service", true)),
        "restore_failed" => Some((500, "internal", false)),
        "internal_error" => Some((500, "internal", false)),
        _ => None,
    }
}

fn validate_error(
    response_status: u16,
    contract_headers: &[&str],
    body: Option<&serde_json::Value>,
) -> Option<String> {
    if !exact_contract_header(contract_headers) {
        return None;
    }
    let parsed = serde_json::from_value::<ErrorEnvelope>(body?.clone()).ok()?;
    let detail = parsed.error;
    let counted = matches!(
        detail.code.as_str(),
        "request_schema_invalid" | "residual_pii" | "ner_incomplete" | "ner_unavailable"
    );
    if (!counted && detail.count != 0) || detail.status != response_status {
        return None;
    }
    if detail.code == "ner_unavailable" {
        let valid = detail.status == 503
            && match (detail.category.as_str(), detail.retryable) {
                ("configuration" | "dependency", false) => true,
                ("network" | "upstream", true) => true,
                _ => false,
            };
        return valid.then_some(detail.code);
    }
    let (status, category, retryable) = error_spec(&detail.code)?;
    (detail.status == status && detail.category == category && detail.retryable == retryable)
        .then_some(detail.code)
}

fn is_data_type(value: &str) -> bool {
    let mut chars = value.chars();
    matches!(chars.next(), Some('A'..='Z'))
        && chars.all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
}

fn unique<T: Eq + std::hash::Hash + Clone>(values: &[T]) -> bool {
    let mut seen = HashSet::with_capacity(values.len());
    values.iter().all(|value| seen.insert(value.clone()))
}

fn interpret_health(
    status: u16,
    contract_headers: &[&str],
    body: Option<&serde_json::Value>,
) -> bool {
    if status != 200 || !exact_contract_header(contract_headers) {
        return false;
    }
    let Some(body) = body else { return false };
    let Ok(parsed) = serde_json::from_value::<HealthResponse>(body.clone()) else {
        return false;
    };
    let _control_plane_is_protected = parsed.capabilities.control_token_required;
    parsed.status == "ok"
        && !parsed.version.trim().is_empty()
        && parsed.contract_version == 2
        && !parsed.capabilities.api_key_required
}

/// Classify a /api/sanitize response. A non-2xx status (backend down, 422
/// residual-leak refusal, ...) or a 2xx body missing the expected fields is a
/// failure, never a silent no-op — that was the DESK-1 leak.
fn interpret_sanitize(
    status: u16,
    contract_headers: &[&str],
    body: Option<&serde_json::Value>,
) -> MaskOutcome {
    if !exact_contract_header(contract_headers) {
        return MaskOutcome::Failed("sanitize rejected".into());
    }
    if status != 200 {
        return match validate_error(status, contract_headers, body) {
            Some(code)
                if (status == 404 && code == "session_unavailable")
                    || (status == 400 && code == "invalid_request") =>
            {
                MaskOutcome::RetryFresh
            }
            Some(code) => MaskOutcome::Failed(format!("sanitize rejected: {code}")),
            None => MaskOutcome::Failed("invalid HTTP v2 error response".into()),
        };
    }
    let Some(body) = body else {
        return MaskOutcome::Failed("sanitize rejected".into());
    };
    let Ok(parsed) = serde_json::from_value::<SanitizeResponse>(body.clone()) else {
        return MaskOutcome::Failed("sanitize rejected".into());
    };
    if parsed.session_id.trim().is_empty()
        || parsed.sanitized_text.is_empty()
        || parsed.safety.status != "pass"
        || parsed.safety.residual_count != 0
        || !parsed.warnings.is_empty()
        || parsed.replacement_count != parsed.highlights.len()
        || parsed.replacement_count < parsed.detected_entity_count
        || parsed.detected_entity_count
            != parsed
                .entity_type_counts
                .values()
                .try_fold(0usize, |total, count| total.checked_add(*count))
                .unwrap_or(usize::MAX)
        || parsed
            .entity_type_counts
            .iter()
            .any(|(data_type, count)| !is_data_type(data_type) || *count == 0)
        || !unique(&parsed.section26_categories)
        || !parsed
            .section26_categories
            .windows(2)
            .all(|pair| pair[0] < pair[1])
    {
        return MaskOutcome::Failed("sanitize rejected".into());
    }

    let text_len = parsed.sanitized_text.chars().count();
    let mut prior_end = 0usize;
    for highlight in &parsed.highlights {
        if !is_data_type(&highlight.data_type)
            || highlight.start >= highlight.end
            || highlight.start < prior_end
            || highlight.end > text_len
        {
            return MaskOutcome::Failed("sanitize rejected".into());
        }
        prior_end = highlight.end;
        match highlight.redact_type {
            RedactType::Fp | RedactType::Tb => {}
        }
    }

    let mut guard_seen = HashSet::with_capacity(parsed.guard_findings.len());
    if !parsed
        .guard_findings
        .iter()
        .all(|finding| guard_seen.insert((finding.category.clone(), finding.severity.clone())))
    {
        return MaskOutcome::Failed("sanitize rejected".into());
    }

    MaskOutcome::Masked {
        session_id: parsed.session_id,
        masked: parsed.sanitized_text,
    }
}

/// Classify a /api/reidentify response with the same status/shape discipline.
fn interpret_reidentify(
    status: u16,
    contract_headers: &[&str],
    body: Option<&serde_json::Value>,
) -> RestoreOutcome {
    if !exact_contract_header(contract_headers) {
        return RestoreOutcome::Failed("restore rejected".into());
    }
    if status != 200 {
        return match validate_error(status, contract_headers, body) {
            Some(code) => RestoreOutcome::Failed(format!("restore rejected: {code}")),
            None => RestoreOutcome::Failed("invalid HTTP v2 error response".into()),
        };
    }
    let Some(body) = body else {
        return RestoreOutcome::Failed("restore rejected".into());
    };
    let Ok(parsed) = serde_json::from_value::<ReidentifyResponse>(body.clone()) else {
        return RestoreOutcome::Failed("restore rejected".into());
    };
    let warnings_valid = parsed.warnings.iter().all(|warning| warning.count > 0)
        && unique(
            &parsed
                .warnings
                .iter()
                .map(|warning| warning.code.clone())
                .collect::<Vec<_>>(),
        );
    if !warnings_valid || !parsed.warnings.is_empty() || parsed.leftover_count != 0 {
        return RestoreOutcome::Failed("restore rejected".into());
    }
    if parsed.replaced_count == usize::MAX {
        return RestoreOutcome::Failed("restore rejected".into());
    }
    RestoreOutcome::Restored(parsed.restored_text)
}

fn response_contract_headers(headers: &reqwest::header::HeaderMap) -> Vec<String> {
    headers
        .get_all(CONTRACT_HEADER)
        .iter()
        .map(|value| value.to_str().unwrap_or("").to_owned())
        .collect()
}

async fn health_ready(client: &reqwest::Client) -> bool {
    let Ok(response) = client.get(format!("{BASE}/api/health")).send().await else {
        return false;
    };
    let status = response.status().as_u16();
    let headers = response_contract_headers(response.headers());
    let body = response.json::<serde_json::Value>().await.ok();
    let header_refs = headers.iter().map(String::as_str).collect::<Vec<_>>();
    interpret_health(status, &header_refs, body.as_ref())
}

fn apply_mask_write<F>(outcome: MaskOutcome, mut write: F) -> Result<String, String>
where
    F: FnMut(String) -> Result<(), String>,
{
    match outcome {
        MaskOutcome::Masked { session_id, masked } => {
            write(masked)?;
            Ok(session_id)
        }
        MaskOutcome::RetryFresh => Err("session retry required".into()),
        MaskOutcome::Failed(reason) => Err(reason),
    }
}

fn apply_restore_write<F>(outcome: RestoreOutcome, mut write: F) -> Result<(), String>
where
    F: FnMut(String) -> Result<(), String>,
{
    match outcome {
        RestoreOutcome::Restored(text) => {
            write(text)?;
            Ok(())
        }
        RestoreOutcome::Failed(reason) => Err(reason),
    }
}

fn sanitize_payload(text: &str, session_id: Option<&str>) -> serde_json::Value {
    let mut payload = serde_json::json!({ "text": text, "mode": "token" });
    if let Some(session_id) = session_id {
        payload["session_id"] = serde_json::Value::String(session_id.to_owned());
    }
    payload
}

async fn request_sanitize(
    client: &reqwest::Client,
    text: &str,
    session_id: Option<&str>,
) -> MaskOutcome {
    match client
        .post(format!("{BASE}/api/sanitize"))
        .header(CONTRACT_HEADER, CONTRACT_VERSION)
        .json(&sanitize_payload(text, session_id))
        .send()
        .await
    {
        Ok(response) => {
            let status = response.status().as_u16();
            let headers = response_contract_headers(response.headers());
            let body = response.json::<serde_json::Value>().await.ok();
            let header_refs = headers.iter().map(String::as_str).collect::<Vec<_>>();
            interpret_sanitize(status, &header_refs, body.as_ref())
        }
        Err(_) => MaskOutcome::Failed("network rejected".into()),
    }
}

async fn mask(app: AppHandle) {
    let Some(_busy_guard) = HotkeyBusyGuard::acquire() else {
        return;
    };
    let text = match app.clipboard().read_text() {
        Ok(t) if !t.trim().is_empty() => t,
        _ => return,
    };
    let client = reqwest::Client::new();
    let prior_session = app
        .state::<HotkeyState>()
        .last_session
        .lock()
        .unwrap()
        .clone();
    let outcome = if !health_ready(&client).await {
        MaskOutcome::Failed("health rejected".into())
    } else {
        let first = request_sanitize(&client, &text, prior_session.as_deref()).await;
        if prior_session.is_some() && matches!(first, MaskOutcome::RetryFresh) {
            request_sanitize(&client, &text, None).await
        } else {
            first
        }
    };
    match apply_mask_write(outcome, |masked| {
        app.clipboard()
            .write_text(masked)
            .map_err(|_| "clipboard write failed".into())
    }) {
        Ok(session_id) => {
            *app.state::<HotkeyState>().last_session.lock().unwrap() = Some(session_id);
        }
        Err(reason) => {
            log::error!("mask hotkey failed: {reason}");
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
    }
}

async fn restore(app: AppHandle) {
    let Some(_busy_guard) = HotkeyBusyGuard::acquire() else {
        return;
    };
    let sid = app
        .state::<HotkeyState>()
        .last_session
        .lock()
        .unwrap()
        .clone();
    let sid = match sid {
        Some(s) => s,
        None => return,
    };
    let text = match app.clipboard().read_text() {
        Ok(t) => t,
        _ => return,
    };
    let client = reqwest::Client::new();
    let outcome = if !health_ready(&client).await {
        RestoreOutcome::Failed("health rejected".into())
    } else {
        match client
            .post(format!("{BASE}/api/reidentify"))
            .header(CONTRACT_HEADER, CONTRACT_VERSION)
            .json(&serde_json::json!({ "session_id": sid, "text": text }))
            .send()
            .await
        {
            Ok(r) => {
                let status = r.status().as_u16();
                let headers = response_contract_headers(r.headers());
                let body = r.json::<serde_json::Value>().await.ok();
                let header_refs = headers.iter().map(String::as_str).collect::<Vec<_>>();
                interpret_reidentify(status, &header_refs, body.as_ref())
            }
            Err(_) => RestoreOutcome::Failed("network rejected".into()),
        }
    };
    if let Err(reason) = apply_restore_write(outcome, |text| {
        app.clipboard()
            .write_text(text)
            .map_err(|_| "clipboard write failed".into())
    }) {
        log::error!("restore hotkey failed: {reason}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const TOKEN: &str = "[ชื่อ_aaaaaaaaaaaaaaaaaaaaaaaaa_nnnnnnnnnnnnnnnnnnnn_1]";

    #[test]
    fn sanitize_ok_yields_masked() {
        let body = json!({
            "session_id": "S1",
            "sanitized_text": TOKEN,
            "detected_entity_count": 1,
            "replacement_count": 1,
            "entity_type_counts": {"NAME": 1},
            "highlights": [{
                "start": 0,
                "end": TOKEN.chars().count(),
                "data_type": "NAME",
                "redact_type": "TB"
            }],
            "section26_categories": [],
            "guard_findings": [],
            "warnings": [],
            "safety": {"status": "pass", "residual_count": 0}
        });
        assert_eq!(
            interpret_sanitize(200, &["2"], Some(&body)),
            MaskOutcome::Masked {
                session_id: "S1".into(),
                masked: TOKEN.into()
            }
        );
    }

    #[test]
    fn sanitize_non_2xx_is_failure_not_silent() {
        // 422 = backend refused because it detected a residual leak. The old
        // code never checked status and just fell through silently (DESK-1).
        let body = json!({
            "error": {
                "code": "residual_pii",
                "category": "privacy",
                "count": 1,
                "retryable": false,
                "status": 422
            }
        });
        assert_eq!(
            interpret_sanitize(422, &["2"], Some(&body)),
            MaskOutcome::Failed("sanitize rejected: residual_pii".into())
        );
        assert!(matches!(
            interpret_sanitize(500, &["2"], None),
            MaskOutcome::Failed(_)
        ));
    }

    #[test]
    fn sanitize_retries_fresh_only_for_exact_stale_session_errors() {
        let expired = json!({
            "error": {
                "code": "session_unavailable",
                "category": "session",
                "count": 0,
                "retryable": false,
                "status": 404
            }
        });
        assert_eq!(
            interpret_sanitize(404, &["2"], Some(&expired)),
            MaskOutcome::RetryFresh
        );

        let mode_mismatch = json!({
            "error": {
                "code": "invalid_request",
                "category": "request",
                "count": 0,
                "retryable": false,
                "status": 400
            }
        });
        assert_eq!(
            interpret_sanitize(400, &["2"], Some(&mode_mismatch)),
            MaskOutcome::RetryFresh
        );

        let malformed = json!({
            "error": {
                "code": "session_unavailable",
                "category": "internal",
                "count": 0,
                "retryable": false,
                "status": 404
            }
        });
        assert!(matches!(
            interpret_sanitize(404, &["2"], Some(&malformed)),
            MaskOutcome::Failed(_)
        ));
    }

    #[test]
    fn sanitize_payload_reuses_only_an_explicit_session() {
        assert_eq!(
            sanitize_payload("synthetic", Some("session-1")),
            json!({"text": "synthetic", "mode": "token", "session_id": "session-1"})
        );
        assert_eq!(
            sanitize_payload("synthetic", None),
            json!({"text": "synthetic", "mode": "token"})
        );
    }

    #[test]
    fn hotkey_operations_are_serialized() {
        let first = HotkeyBusyGuard::acquire().expect("first operation acquires guard");
        assert!(HotkeyBusyGuard::acquire().is_none());
        drop(first);
        assert!(HotkeyBusyGuard::acquire().is_some());
    }

    #[test]
    fn non_2xx_requires_an_exact_safe_error_envelope() {
        let base = json!({
            "error": {
                "code": "session_unavailable",
                "category": "session",
                "count": 0,
                "retryable": false,
                "status": 404
            }
        });
        assert_eq!(
            interpret_reidentify(404, &["2"], Some(&base)),
            RestoreOutcome::Failed("restore rejected: session_unavailable".into())
        );

        let mut raw_detail = base.clone();
        raw_detail["error"]["detail"] = json!("SYNTHETIC-PRIVATE-MARKER");
        assert_eq!(
            interpret_reidentify(404, &["2"], Some(&raw_detail)),
            RestoreOutcome::Failed("invalid HTTP v2 error response".into())
        );

        let mut wrong_category = base.clone();
        wrong_category["error"]["category"] = json!("internal");
        assert_eq!(
            interpret_reidentify(404, &["2"], Some(&wrong_category)),
            RestoreOutcome::Failed("invalid HTTP v2 error response".into())
        );

        let mut wrong_status = base;
        wrong_status["error"]["status"] = json!(500);
        assert_eq!(
            interpret_reidentify(404, &["2"], Some(&wrong_status)),
            RestoreOutcome::Failed("invalid HTTP v2 error response".into())
        );
    }

    #[test]
    fn sanitize_2xx_missing_fields_is_failure() {
        let body = json!({"session_id": "S1"}); // no sanitized_text
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&body)),
            MaskOutcome::Failed(_)
        ));
    }

    #[test]
    fn sanitize_2xx_empty_masked_text_is_failure() {
        // An empty sanitized_text must not be treated as a successful mask; the
        // fails-closed path would otherwise blank the clipboard silently.
        let body = json!({
            "session_id": "S1",
            "sanitized_text": "",
            "detected_entity_count": 0,
            "replacement_count": 0,
            "entity_type_counts": {},
            "highlights": [],
            "section26_categories": [],
            "guard_findings": [],
            "warnings": [],
            "safety": {"status": "pass", "residual_count": 0}
        });
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&body)),
            MaskOutcome::Failed(_)
        ));
    }

    #[test]
    fn reidentify_ok_yields_restored() {
        let body = json!({
            "restored_text": "สมชาย",
            "replaced_count": 1,
            "leftover_count": 0,
            "warnings": []
        });
        assert_eq!(
            interpret_reidentify(200, &["2"], Some(&body)),
            RestoreOutcome::Restored("สมชาย".into())
        );
    }

    #[test]
    fn reidentify_non_2xx_is_failure() {
        assert!(matches!(
            interpret_reidentify(404, &["2"], None),
            RestoreOutcome::Failed(_)
        ));
    }

    #[test]
    fn reidentify_2xx_missing_field_is_failure() {
        let body = json!({});
        assert!(matches!(
            interpret_reidentify(200, &["2"], Some(&body)),
            RestoreOutcome::Failed(_)
        ));
    }

    #[test]
    fn health_requires_exact_v2_contract_and_capabilities() {
        let body = json!({
            "status": "ok",
            "version": "2.5.0",
            "contract_version": 2,
            "capabilities": {
                "control_token_required": true,
                "api_key_required": false
            }
        });
        assert!(interpret_health(200, &["2"], Some(&body)));
        assert!(!interpret_health(200, &[], Some(&body)));
        assert!(!interpret_health(200, &["2", "2"], Some(&body)));
        assert!(!interpret_health(200, &["1"], Some(&body)));
        assert!(!interpret_health(
            200,
            &["2"],
            Some(&json!({
                "status": "ok",
                "version": "2.5.0",
                "contract_version": 1,
                "capabilities": {
                    "control_token_required": true,
                    "api_key_required": false
                }
            }))
        ));
        assert!(!interpret_health(
            200,
            &["2"],
            Some(&json!({
                "status": "ok",
                "version": "2.5.0",
                "contract_version": 2,
                "capabilities": {
                    "control_token_required": false,
                    "api_key_required": true
                }
            }))
        ));
    }

    #[test]
    fn sanitize_rejects_extra_mapping_fields_and_unsafe_safety() {
        let base = json!({
            "session_id": "S1",
            "sanitized_text": TOKEN,
            "detected_entity_count": 1,
            "replacement_count": 1,
            "entity_type_counts": {"NAME": 1},
            "highlights": [{
                "start": 0,
                "end": TOKEN.chars().count(),
                "data_type": "NAME",
                "redact_type": "TB"
            }],
            "section26_categories": [],
            "guard_findings": [],
            "warnings": [],
            "safety": {"status": "pass", "residual_count": 0}
        });
        let mut extra = base.clone();
        extra["original_text"] = json!("synthetic-source");
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&extra)),
            MaskOutcome::Failed(_)
        ));

        let mut unsafe_body = base;
        unsafe_body["safety"] = json!({"status": "pass", "residual_count": 1});
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&unsafe_body)),
            MaskOutcome::Failed(_)
        ));
    }

    #[test]
    fn sanitize_rejects_malformed_counts_offsets_and_headers() {
        let body = json!({
            "session_id": "S1",
            "sanitized_text": format!("😀{TOKEN}"),
            "detected_entity_count": 1,
            "replacement_count": 1,
            "entity_type_counts": {"NAME": 1},
            "highlights": [{
                "start": 1,
                "end": 1 + TOKEN.chars().count(),
                "data_type": "NAME",
                "redact_type": "TB"
            }],
            "section26_categories": [],
            "guard_findings": [],
            "warnings": [],
            "safety": {"status": "pass", "residual_count": 0}
        });
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&body)),
            MaskOutcome::Masked { .. }
        ));
        assert!(matches!(
            interpret_sanitize(200, &[], Some(&body)),
            MaskOutcome::Failed(_)
        ));
        assert!(matches!(
            interpret_sanitize(200, &["2", "2"], Some(&body)),
            MaskOutcome::Failed(_)
        ));

        let mut bad_count = body.clone();
        bad_count["replacement_count"] = json!(2);
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&bad_count)),
            MaskOutcome::Failed(_)
        ));

        let mut missing_replacement = body.clone();
        missing_replacement["detected_entity_count"] = json!(2);
        missing_replacement["entity_type_counts"] = json!({"NAME": 2});
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&missing_replacement)),
            MaskOutcome::Failed(_)
        ));

        let mut bad_offset = body.clone();
        bad_offset["highlights"][0]["end"] = json!(99);
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&bad_offset)),
            MaskOutcome::Failed(_)
        ));

        let mut bad_order = body;
        bad_order["section26_categories"] = json!(["HEALTH", "RACE_ETHNICITY"]);
        assert!(matches!(
            interpret_sanitize(200, &["2"], Some(&bad_order)),
            MaskOutcome::Failed(_)
        ));
    }

    #[test]
    fn partial_or_warned_restore_never_reaches_clipboard_outcome() {
        let partial = json!({
            "restored_text": "preview-only",
            "replaced_count": 1,
            "leftover_count": 1,
            "warnings": []
        });
        assert!(matches!(
            interpret_reidentify(200, &["2"], Some(&partial)),
            RestoreOutcome::Failed(_)
        ));

        let warned = json!({
            "restored_text": "preview-only",
            "replaced_count": 1,
            "leftover_count": 0,
            "warnings": [{"code": "generated_pii", "count": 1}]
        });
        assert!(matches!(
            interpret_reidentify(200, &["2"], Some(&warned)),
            RestoreOutcome::Failed(_)
        ));

        let mut extra = warned;
        extra["replaced"] = json!([]);
        assert!(matches!(
            interpret_reidentify(200, &["2"], Some(&extra)),
            RestoreOutcome::Failed(_)
        ));
    }

    #[test]
    fn rejected_results_never_call_clipboard_writer() {
        let mut writes = Vec::new();
        assert!(
            apply_mask_write(MaskOutcome::Failed("blocked".into()), |value| {
                writes.push(value);
                Ok(())
            })
            .is_err()
        );
        assert!(
            apply_restore_write(RestoreOutcome::Failed("blocked".into()), |value| {
                writes.push(value);
                Ok(())
            })
            .is_err()
        );
        assert!(writes.is_empty());
    }

    #[test]
    fn validated_results_call_clipboard_writer_once() {
        let mut writes = Vec::new();
        let session_id = apply_mask_write(
            MaskOutcome::Masked {
                session_id: "S1".into(),
                masked: TOKEN.into(),
            },
            |value| {
                writes.push(value);
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(session_id, "S1");
        assert_eq!(writes, vec![TOKEN]);

        writes.clear();
        apply_restore_write(RestoreOutcome::Restored("synthetic".into()), |value| {
            writes.push(value);
            Ok(())
        })
        .unwrap();
        assert_eq!(writes, vec!["synthetic"]);
    }

    #[test]
    fn clipboard_write_failures_are_propagated() {
        assert_eq!(
            apply_mask_write(
                MaskOutcome::Masked {
                    session_id: "S1".into(),
                    masked: TOKEN.into(),
                },
                |_value| Err("clipboard write failed".into()),
            ),
            Err("clipboard write failed".into())
        );
        assert_eq!(
            apply_restore_write(RestoreOutcome::Restored("synthetic".into()), |_value| Err(
                "clipboard write failed".into()
            ),),
            Err("clipboard write failed".into())
        );
    }
}

pub fn setup(app: &tauri::App) -> tauri::Result<()> {
    app.manage(HotkeyState::default());
    let mask_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
    let restore_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyR);
    let mask_id = mask_sc.clone();
    app.global_shortcut()
        .on_shortcut(mask_sc, move |app, sc, event| {
            if event.state() == ShortcutState::Pressed {
                let app = app.clone();
                let is_mask = sc == &mask_id;
                tauri::async_runtime::spawn(async move {
                    if is_mask {
                        mask(app).await
                    } else {
                        restore(app).await
                    }
                });
            }
        })
        .unwrap_or_else(|e| log::error!("hotkey register failed: {e}"));
    app.global_shortcut()
        .on_shortcut(restore_sc, move |app, _sc, event| {
            if event.state() == ShortcutState::Pressed {
                let app = app.clone();
                tauri::async_runtime::spawn(async move { restore(app).await });
            }
        })
        .unwrap_or_else(|e| log::error!("hotkey register failed: {e}"));
    Ok(())
}
