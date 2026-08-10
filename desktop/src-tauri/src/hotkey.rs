use serde::Deserialize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::{AppHandle, Manager};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[derive(Default)]
pub struct HotkeyState {
    last_session: Mutex<Option<String>>,
}

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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Safety {
    status: String,
    residual_count: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SanitizeResult {
    session_id: String,
    sanitized_text: String,
    detected_entity_count: u64,
    replacement_count: u64,
    entity_type_counts: serde_json::Value,
    highlights: serde_json::Value,
    section26_categories: serde_json::Value,
    guard_findings: serde_json::Value,
    warnings: Vec<serde_json::Value>,
    safety: Safety,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReidentifyResult {
    restored_text: String,
    replaced_count: u64,
    leftover_count: u64,
    warnings: Vec<serde_json::Value>,
}

fn validated_mask(result: serde_json::Value) -> Option<(String, String)> {
    let parsed: SanitizeResult = serde_json::from_value(result).ok()?;
    let _validated_shape = (
        parsed.detected_entity_count,
        parsed.replacement_count,
        &parsed.entity_type_counts,
        &parsed.highlights,
        &parsed.section26_categories,
        &parsed.guard_findings,
    );
    if parsed.session_id.is_empty()
        || parsed.sanitized_text.is_empty()
        || parsed.safety.status != "pass"
        || parsed.safety.residual_count != 0
        || !parsed.warnings.is_empty()
    {
        return None;
    }
    Some((parsed.session_id, parsed.sanitized_text))
}

fn validated_restore(result: serde_json::Value) -> Option<String> {
    let parsed: ReidentifyResult = serde_json::from_value(result).ok()?;
    let _validated_count = parsed.replaced_count;
    if parsed.leftover_count != 0 || !parsed.warnings.is_empty() {
        return None;
    }
    Some(parsed.restored_text)
}

fn clear_session_slot(slot: &Mutex<Option<String>>) {
    match slot.lock() {
        Ok(mut session) => *session = None,
        Err(poisoned) => {
            *poisoned.into_inner() = None;
            slot.clear_poison();
        }
    }
}

pub(crate) fn invalidate_session(app: &AppHandle) {
    if let Some(state) = app.try_state::<HotkeyState>() {
        clear_session_slot(&state.last_session);
    }
}

fn retain_session(slot: &Mutex<Option<String>>, session: String) -> bool {
    let Ok(mut slot) = slot.lock() else {
        return false;
    };
    *slot = Some(session);
    true
}

fn clear_hotkey_authority(app: &AppHandle) {
    invalidate_session(app);
    crate::broker::reset_hotkey_scope(app);
}

fn mask(app: AppHandle) {
    let Some(_busy_guard) = HotkeyBusyGuard::acquire() else {
        return;
    };
    let text = match app.clipboard().read_text() {
        Ok(text) if !text.trim().is_empty() => text,
        _ => return,
    };
    let prior = app
        .state::<HotkeyState>()
        .last_session
        .lock()
        .ok()
        .and_then(|session| session.clone());
    match crate::broker::hotkey_sanitize(&app, &text, prior.as_deref(), |result| {
        let Some((session, masked)) = validated_mask(result) else {
            return false;
        };
        if !retain_session(&app.state::<HotkeyState>().last_session, session) {
            return false;
        }
        if app.clipboard().write_text(masked).is_err() {
            invalidate_session(&app);
            return false;
        }
        true
    }) {
        Ok(()) => {}
        Err(error) => {
            if error.session_invalidated() {
                clear_hotkey_authority(&app);
            }
            log::error!("mask hotkey failed: {}", error.code());
        }
    }
}

fn restore(app: AppHandle) {
    let Some(_busy_guard) = HotkeyBusyGuard::acquire() else {
        return;
    };
    let text = match app.clipboard().read_text() {
        Ok(text) if !text.trim().is_empty() => text,
        _ => return,
    };
    let Some(session) = app
        .state::<HotkeyState>()
        .last_session
        .lock()
        .ok()
        .and_then(|session| session.clone())
    else {
        return;
    };
    match crate::broker::hotkey_reidentify(&app, &session, &text, |result| {
        let Some(restored) = validated_restore(result) else {
            return false;
        };
        if app.clipboard().write_text(restored).is_err() {
            return false;
        }
        true
    }) {
        Ok(()) => {}
        Err(error) => {
            if error.session_invalidated() {
                clear_hotkey_authority(&app);
            }
            log::error!("restore hotkey failed: {}", error.code());
        }
    }
}

pub fn setup(app: &tauri::App) -> tauri::Result<()> {
    app.manage(HotkeyState::default());
    let mask_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
    let restore_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyR);
    app.global_shortcut()
        .on_shortcut(mask_shortcut, move |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                let app = app.clone();
                tauri::async_runtime::spawn_blocking(move || mask(app));
            }
        })
        .unwrap_or_else(|_| log::error!("mask hotkey registration failed: operation_failed"));
    app.global_shortcut()
        .on_shortcut(restore_shortcut, move |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                let app = app.clone();
                tauri::async_runtime::spawn_blocking(move || restore(app));
            }
        })
        .unwrap_or_else(|_| log::error!("restore hotkey registration failed: operation_failed"));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_or_unsafe_results_never_reach_clipboard_values() {
        assert!(validated_mask(serde_json::json!({})).is_none());
        assert!(validated_mask(serde_json::json!({
            "session_id": "session-handle",
            "sanitized_text": "[PHONE_1]",
            "detected_entity_count": 1,
            "replacement_count": 1,
            "entity_type_counts": {"PHONE": 1},
            "highlights": [],
            "section26_categories": [],
            "guard_findings": [],
            "warnings": [],
            "safety": {"status": "pass", "residual_count": 1}
        }))
        .is_none());
        assert!(validated_restore(serde_json::json!({
            "restored_text": "synthetic",
            "replaced_count": 1,
            "leftover_count": 1,
            "warnings": []
        }))
        .is_none());
    }

    #[test]
    fn validated_results_are_the_only_publishable_values() {
        assert_eq!(
            validated_mask(serde_json::json!({
                "session_id": "session-handle",
                "sanitized_text": "[PHONE_1]",
                "detected_entity_count": 1,
                "replacement_count": 1,
                "entity_type_counts": {"PHONE": 1},
                "highlights": [{"start": 0, "end": 9, "data_type": "PHONE", "redact_type": "FP"}],
                "section26_categories": [],
                "guard_findings": [],
                "warnings": [],
                "safety": {"status": "pass", "residual_count": 0}
            })),
            Some(("session-handle".to_owned(), "[PHONE_1]".to_owned()))
        );
        assert_eq!(
            validated_restore(serde_json::json!({
                "restored_text": "synthetic",
                "replaced_count": 1,
                "leftover_count": 0,
                "warnings": []
            })),
            Some("synthetic".to_owned())
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
    fn session_authority_must_be_retained_before_clipboard_publication() {
        let slot = std::sync::Arc::new(Mutex::new(None));
        assert!(retain_session(&slot, "session-ok".to_owned()));
        assert_eq!(slot.lock().unwrap().as_deref(), Some("session-ok"));

        let poisoned = std::sync::Arc::clone(&slot);
        let _ = std::panic::catch_unwind(move || {
            let _guard = poisoned.lock().unwrap();
            panic!("synthetic session-state panic");
        });

        assert!(!retain_session(&slot, "session-unsafe".to_owned()));

        clear_session_slot(&slot);
        assert!(slot.lock().unwrap().is_none());
    }
}
