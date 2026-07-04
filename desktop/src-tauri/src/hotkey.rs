use std::sync::Mutex;
use tauri::{AppHandle, Manager};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Default)]
pub struct HotkeyState {
    pub last_session: Mutex<Option<String>>,
}

const BASE: &str = "http://127.0.0.1:8000";

async fn mask(app: AppHandle) {
    let text = match app.clipboard().read_text() {
        Ok(t) if !t.trim().is_empty() => t,
        _ => return,
    };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{BASE}/api/sanitize"))
        .json(&serde_json::json!({ "text": text, "mode": "token" }))
        .send()
        .await;
    if let Ok(r) = resp {
        if let Ok(v) = r.json::<serde_json::Value>().await {
            if let (Some(sid), Some(masked)) =
                (v["session_id"].as_str(), v["sanitized_text"].as_str())
            {
                *app.state::<HotkeyState>().last_session.lock().unwrap() = Some(sid.to_string());
                let _ = app.clipboard().write_text(masked.to_string());
            }
        }
    }
}

async fn restore(app: AppHandle) {
    let sid = app.state::<HotkeyState>().last_session.lock().unwrap().clone();
    let sid = match sid { Some(s) => s, None => return };
    let text = match app.clipboard().read_text() { Ok(t) => t, _ => return };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{BASE}/api/reidentify"))
        .json(&serde_json::json!({ "session_id": sid, "text": text }))
        .send()
        .await;
    if let Ok(r) = resp {
        if let Ok(v) = r.json::<serde_json::Value>().await {
            if let Some(restored) = v["restored_text"].as_str() {
                let _ = app.clipboard().write_text(restored.to_string());
            }
        }
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
