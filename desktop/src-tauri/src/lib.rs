mod hotkey;
mod sidecar;
mod tray;
mod updater;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(sidecar::SidecarState::default())
        .invoke_handler(tauri::generate_handler![
            quit_app,
            updater::update_check,
            updater::update_install
        ])
        .setup(|app| {
            if let Err(e) = sidecar::spawn(&app.handle()) {
                log::error!("failed to start sidecar: {e}");
                // DESK-2: an untrusted process owns the backend port. Running
                // on would point every UI fetch and hotkey clipboard grab at
                // it, so the only safe move is to not run at all.
                if e.starts_with(sidecar::UNTRUSTED_PORT_OWNER) {
                    notify_untrusted_port();
                    app.handle().exit(1);
                }
            }
            tray::setup(app)?;
            hotkey::setup(app)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| sidecar::on_run_event(app, &event));
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    sidecar::kill(&app);
    app.exit(0);
}

/// Best-effort native alert before the fail-closed exit — the app is about to
/// quit, so the log alone would leave the user staring at nothing.
#[cfg(windows)]
fn notify_untrusted_port() {
    let _ = std::process::Command::new("powershell")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Add-Type -AssemblyName PresentationFramework; \
             [System.Windows.MessageBox]::Show(\
             'มีโปรแกรมอื่นที่ไม่รู้จักใช้พอร์ต 8000 อยู่ AI Guard จะไม่เริ่มทำงานเพื่อป้องกันข้อมูลรั่ว \
ปิดโปรแกรมที่ใช้พอร์ตนั้นแล้วเปิด AI Guard ใหม่','AI Guard')",
        ])
        .status();
}

#[cfg(not(windows))]
fn notify_untrusted_port() {}
