mod sidecar;

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
        .manage(sidecar::SidecarState::default())
        .invoke_handler(tauri::generate_handler![quit_app])
        .setup(|app| {
            if let Err(e) = sidecar::spawn(&app.handle()) {
                log::error!("failed to start sidecar: {e}");
            }
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
