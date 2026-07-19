use std::sync::Mutex;
use tauri::{AppHandle, Manager};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Default)]
pub struct HotkeyState {
    pub last_session: Mutex<Option<String>>,
}

const BASE: &str = "http://127.0.0.1:8000";

// Clipboard-based hotkeys are fails-closed: if a Mask does not clearly succeed,
// we must NOT leave raw PII sitting in the clipboard where the user pastes it
// into an external AI believing it was masked (DESK-1). On any failure we
// overwrite the clipboard with this marker so the failure is impossible to miss
// and no unmasked PII can be pasted by accident.
const MASK_FAILED_MARKER: &str =
    "[AI Guard] ปกปิดไม่สำเร็จ ยังไม่ได้ปกปิดข้อความ ตรวจสอบว่าโปรแกรมหลังบ้านทำงานอยู่แล้วลองใหม่";

#[derive(Debug, PartialEq)]
enum MaskOutcome {
    Masked { session_id: String, masked: String },
    Failed(String),
}

#[derive(Debug, PartialEq)]
enum RestoreOutcome {
    Restored(String),
    Failed(String),
}

/// Classify a /api/sanitize response. A non-2xx status (backend down, 422
/// residual-leak refusal, ...) or a 2xx body missing the expected fields is a
/// failure, never a silent no-op — that was the DESK-1 leak.
fn interpret_sanitize(status: u16, body: Option<&serde_json::Value>) -> MaskOutcome {
    if !(200..300).contains(&status) {
        return MaskOutcome::Failed(format!("backend returned status {status}"));
    }
    match body.and_then(|v| {
        match (v["session_id"].as_str(), v["sanitized_text"].as_str()) {
            // A blank sanitized_text is not a usable mask; treat it as failure
            // so the fails-closed path does not silently blank the clipboard.
            (Some(sid), Some(m)) if !m.is_empty() => Some((sid.to_string(), m.to_string())),
            _ => None,
        }
    }) {
        Some((session_id, masked)) => MaskOutcome::Masked { session_id, masked },
        None => MaskOutcome::Failed("malformed sanitize response".into()),
    }
}

/// Classify a /api/reidentify response with the same status/shape discipline.
fn interpret_reidentify(status: u16, body: Option<&serde_json::Value>) -> RestoreOutcome {
    if !(200..300).contains(&status) {
        return RestoreOutcome::Failed(format!("backend returned status {status}"));
    }
    match body.and_then(|v| v["restored_text"].as_str().map(|s| s.to_string())) {
        Some(t) => RestoreOutcome::Restored(t),
        None => RestoreOutcome::Failed("malformed reidentify response".into()),
    }
}

async fn mask(app: AppHandle) {
    let text = match app.clipboard().read_text() {
        Ok(t) if !t.trim().is_empty() => t,
        _ => return,
    };
    let client = reqwest::Client::new();
    let outcome = match client
        .post(format!("{BASE}/api/sanitize"))
        .json(&serde_json::json!({ "text": text, "mode": "token" }))
        .send()
        .await
    {
        Ok(r) => {
            let status = r.status().as_u16();
            let body = r.json::<serde_json::Value>().await.ok();
            interpret_sanitize(status, body.as_ref())
        }
        Err(e) => MaskOutcome::Failed(format!("network error: {e}")),
    };
    match outcome {
        MaskOutcome::Masked { session_id, masked } => {
            *app.state::<HotkeyState>().last_session.lock().unwrap() = Some(session_id);
            let _ = app.clipboard().write_text(masked);
        }
        MaskOutcome::Failed(reason) => {
            log::error!("mask hotkey failed: {reason}");
            let _ = app.clipboard().write_text(MASK_FAILED_MARKER.to_string());
        }
    }
}

async fn restore(app: AppHandle) {
    let sid = app.state::<HotkeyState>().last_session.lock().unwrap().clone();
    let sid = match sid { Some(s) => s, None => return };
    let text = match app.clipboard().read_text() { Ok(t) => t, _ => return };
    let client = reqwest::Client::new();
    let outcome = match client
        .post(format!("{BASE}/api/reidentify"))
        .json(&serde_json::json!({ "session_id": sid, "text": text }))
        .send()
        .await
    {
        Ok(r) => {
            let status = r.status().as_u16();
            let body = r.json::<serde_json::Value>().await.ok();
            interpret_reidentify(status, body.as_ref())
        }
        Err(e) => RestoreOutcome::Failed(format!("network error: {e}")),
    };
    match outcome {
        // Restore failure is not a leak (tokens simply remain), so leave the
        // clipboard untouched and log — overwriting would destroy the user's
        // copied AI reply.
        RestoreOutcome::Restored(t) => {
            let _ = app.clipboard().write_text(t);
        }
        RestoreOutcome::Failed(reason) => {
            log::error!("restore hotkey failed: {reason}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn sanitize_ok_yields_masked() {
        let body = json!({"session_id": "S1", "sanitized_text": "[ชื่อ_1]"});
        assert_eq!(
            interpret_sanitize(200, Some(&body)),
            MaskOutcome::Masked { session_id: "S1".into(), masked: "[ชื่อ_1]".into() }
        );
    }

    #[test]
    fn sanitize_non_2xx_is_failure_not_silent() {
        // 422 = backend refused because it detected a residual leak. The old
        // code never checked status and just fell through silently (DESK-1).
        let body = json!({"error": "pii_leak_risk"});
        assert!(matches!(interpret_sanitize(422, Some(&body)), MaskOutcome::Failed(_)));
        assert!(matches!(interpret_sanitize(500, None), MaskOutcome::Failed(_)));
    }

    #[test]
    fn sanitize_2xx_missing_fields_is_failure() {
        let body = json!({"session_id": "S1"}); // no sanitized_text
        assert!(matches!(interpret_sanitize(200, Some(&body)), MaskOutcome::Failed(_)));
    }

    #[test]
    fn sanitize_2xx_empty_masked_text_is_failure() {
        // An empty sanitized_text must not be treated as a successful mask; the
        // fails-closed path would otherwise blank the clipboard silently.
        let body = json!({"session_id": "S1", "sanitized_text": ""});
        assert!(matches!(interpret_sanitize(200, Some(&body)), MaskOutcome::Failed(_)));
    }

    #[test]
    fn reidentify_ok_yields_restored() {
        let body = json!({"restored_text": "สมชาย"});
        assert_eq!(
            interpret_reidentify(200, Some(&body)),
            RestoreOutcome::Restored("สมชาย".into())
        );
    }

    #[test]
    fn reidentify_non_2xx_is_failure() {
        assert!(matches!(interpret_reidentify(404, None), RestoreOutcome::Failed(_)));
    }

    #[test]
    fn reidentify_2xx_missing_field_is_failure() {
        let body = json!({});
        assert!(matches!(interpret_reidentify(200, Some(&body)), RestoreOutcome::Failed(_)));
    }
}

pub fn setup(app: &tauri::App) -> tauri::Result<()> {
    app.manage(HotkeyState::default());
    let mask_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
    let restore_sc = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyR);
    let mask_id = mask_sc.clone();
    app.global_shortcut().on_shortcut(mask_sc, move |app, sc, event| {
        if event.state() == ShortcutState::Pressed {
            let app = app.clone();
            let is_mask = sc == &mask_id;
            tauri::async_runtime::spawn(async move {
                if is_mask { mask(app).await } else { restore(app).await }
            });
        }
    }).unwrap_or_else(|e| log::error!("hotkey register failed: {e}"));
    app.global_shortcut().on_shortcut(restore_sc, move |app, _sc, event| {
        if event.state() == ShortcutState::Pressed {
            let app = app.clone();
            tauri::async_runtime::spawn(async move { restore(app).await });
        }
    }).unwrap_or_else(|e| log::error!("hotkey register failed: {e}"));
    Ok(())
}
