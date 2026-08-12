mod broker;
mod hotkey;
mod native_host_lifecycle;
#[cfg(feature = "package-smoke")]
mod package_smoke;
mod tray;
mod updater;

use tauri::Manager;

#[cfg(not(feature = "package-smoke"))]
macro_rules! desktop_invoke_handler {
    () => {
        tauri::generate_handler![
            quit_app,
            broker::desktop_health,
            broker::desktop_analyze,
            broker::desktop_sanitize,
            broker::desktop_reidentify,
            broker::desktop_analyze_report,
            broker::desktop_redact_pdf,
            broker::desktop_audit_log,
            broker::desktop_copy_masked,
            broker::desktop_session_dispose,
            broker::desktop_scope_reset,
            broker::desktop_scope_rotate,
            updater::update_check,
            updater::update_install
        ]
    };
}

#[cfg(feature = "package-smoke")]
macro_rules! desktop_invoke_handler {
    () => {
        tauri::generate_handler![
            quit_app,
            broker::desktop_health,
            broker::desktop_analyze,
            broker::desktop_sanitize,
            broker::desktop_reidentify,
            broker::desktop_analyze_report,
            broker::desktop_redact_pdf,
            broker::desktop_audit_log,
            broker::desktop_copy_masked,
            broker::desktop_session_dispose,
            broker::desktop_scope_reset,
            broker::desktop_scope_rotate,
            updater::update_check,
            updater::update_install,
            package_smoke::desktop_package_smoke_ready,
            package_smoke::desktop_package_smoke_finish,
            package_smoke::desktop_package_smoke_fail
        ]
    };
}

fn webview_load_replaces_content(
    seen: &std::sync::Mutex<std::collections::BTreeSet<String>>,
    label: &str,
) -> bool {
    match seen.lock() {
        Ok(mut seen) => !seen.insert(label.to_owned()),
        Err(_) => true,
    }
}

#[cfg(windows)]
fn register_webview_process_cleanup(window: &tauri::WebviewWindow) -> tauri::Result<()> {
    let registration_app = window.app_handle().clone();
    let registration_label = window.label().to_owned();
    window.with_webview(move |platform| {
        use webview2_com::ProcessFailedEventHandler;

        let event_app = registration_app.clone();
        let event_label = registration_label.clone();
        let registration = (|| -> webview2_com::Result<()> {
            let controller = platform.controller();
            let webview = unsafe { controller.CoreWebView2()? };
            let handler = ProcessFailedEventHandler::create(Box::new(move |_sender, _args| {
                broker::close_window(&event_app, &event_label);
                Ok(())
            }));
            let mut token = 0_i64;
            unsafe { webview.add_ProcessFailed(&handler, &mut token)? };
            Ok(())
        })();
        if registration.is_err() {
            broker::shutdown(&registration_app);
            registration_app.exit(1);
        }
    })
}

#[cfg(target_os = "linux")]
fn register_webview_process_cleanup(window: &tauri::WebviewWindow) -> tauri::Result<()> {
    let event_app = window.app_handle().clone();
    let event_label = window.label().to_owned();
    window.with_webview(move |platform| {
        use webkit2gtk::WebViewExt;

        platform
            .inner()
            .connect_web_process_terminated(move |_webview, _reason| {
                #[cfg(feature = "package-smoke")]
                package_smoke::desktop_package_smoke_runtime_fail(
                    package_smoke::PackageSmokeFailure::WebviewProcess,
                );
                broker::close_window(&event_app, &event_label);
            });
    })
}

#[cfg(not(any(windows, target_os = "linux")))]
fn register_webview_process_cleanup(_window: &tauri::WebviewWindow) -> tauri::Result<()> {
    Ok(())
}

fn navigation_is_allowed(url: &tauri::Url) -> bool {
    let exact_authority =
        url.port().is_none() && url.username().is_empty() && url.password().is_none();
    #[cfg(windows)]
    let configured_origin = url.scheme() == "http" && url.host_str() == Some("tauri.localhost");
    #[cfg(not(windows))]
    let configured_origin = url.scheme() == "tauri" && url.host_str() == Some("localhost");
    exact_authority && configured_origin
}

pub const WEBVIEW_COMMAND_ALLOWLIST: &[&str] = &[
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
];

pub const WEBVIEW_BROKER_COMMANDS: &[(&str, &str)] = &[
    ("desktop_analyze", "analyze"),
    ("desktop_analyze_report", "analyze_report"),
    ("desktop_audit_log", "audit_log"),
    ("desktop_copy_masked", "reidentify"),
    ("desktop_health", "broker_health"),
    ("desktop_redact_pdf", "redact_pdf"),
    ("desktop_reidentify", "reidentify"),
    ("desktop_sanitize", "sanitize"),
    ("desktop_scope_reset", "scope_close"),
    ("desktop_scope_rotate", "scope_close"),
    ("desktop_session_dispose", "session_dispose"),
];

pub fn native_host_lifecycle_exit_code() -> Option<i32> {
    native_host_lifecycle::requested_action(std::env::args_os()).map(|action| {
        if native_host_lifecycle::run(action).is_ok() {
            0
        } else {
            75
        }
    })
}

pub fn stable_appimage_reexec_exit_code() -> Option<i32> {
    native_host_lifecycle::stable_appimage_reexec_exit_code()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(feature = "package-smoke")]
    if package_smoke::requested() {
        std::panic::set_hook(Box::new(|_| {
            package_smoke::desktop_package_smoke_bootstrap_fail(
                package_smoke::PackageSmokeFailure::AppRuntime,
            );
        }));
    }
    let seen_page_loads = std::sync::Arc::new(std::sync::Mutex::new(std::collections::BTreeSet::<
        String,
    >::new()));
    let page_load_tracker = std::sync::Arc::clone(&seen_page_loads);
    let builder = tauri::Builder::default()
        .on_page_load(move |webview, payload| {
            if matches!(payload.event(), tauri::webview::PageLoadEvent::Started)
                && webview_load_replaces_content(&page_load_tracker, webview.label())
            {
                broker::close_window(webview.app_handle(), webview.label());
            }
            #[cfg(feature = "package-smoke")]
            if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished)
                && webview.label() == "main"
                && package_smoke::requested()
                && webview.eval(package_smoke::BOOTSTRAP_SCRIPT).is_err()
            {
                let app = webview.app_handle().clone();
                tauri::async_runtime::spawn(async move {
                    package_smoke::desktop_package_smoke_fail(
                        app,
                        package_smoke::PackageSmokeFailure::BootstrapEval,
                    )
                    .await;
                });
            }
        })
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(
            tauri::plugin::Builder::<_, ()>::new("navigation-guard")
                .on_navigation(|_webview, url| navigation_is_allowed(url))
                .build(),
        )
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(broker::DesktopBrokerState::default())
        .invoke_handler(desktop_invoke_handler!())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            let _ = native_host_lifecycle::run(native_host_lifecycle::Action::Repair);
            #[cfg(feature = "package-smoke")]
            if package_smoke::requested()
                && package_smoke::desktop_package_smoke_native_start().is_err()
            {
                return Err("package smoke unavailable".into());
            }
            let windows = app.webview_windows();
            if windows.is_empty() {
                return Err("desktop webview unavailable".into());
            }
            for window in windows.values() {
                register_webview_process_cleanup(window)?;
            }
            broker::start_keepalive(app.handle());
            tray::setup(app)?;
            hotkey::setup(app)?;
            Ok(())
        });
    #[cfg(target_os = "macos")]
    let builder = builder.on_web_content_process_terminate(|webview| {
        broker::close_window(webview.app_handle(), webview.label());
    });
    let application = match builder.build(tauri::generate_context!()) {
        Ok(application) => application,
        Err(error) => {
            #[cfg(all(feature = "package-smoke", target_os = "linux"))]
            if package_smoke::requested() {
                package_smoke::desktop_package_smoke_bootstrap_fail(
                    package_smoke::PackageSmokeFailure::AppBuild,
                );
                std::process::exit(75);
            }
            panic!("error while building tauri application: {error}");
        }
    };
    application.run(|app, event| {
        if let tauri::RunEvent::WindowEvent {
            ref label,
            ref event,
            ..
        } = event
        {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                broker::close_window(app, label);
            }
        }
        if matches!(event, tauri::RunEvent::Exit) {
            #[cfg(feature = "package-smoke")]
            package_smoke::desktop_package_smoke_runtime_fail(
                package_smoke::PackageSmokeFailure::AppExit,
            );
            broker::shutdown(app);
        }
    });
}

#[tauri::command]
async fn quit_app(app: tauri::AppHandle) {
    let cleanup_app = app.clone();
    let _ = tauri::async_runtime::spawn_blocking(move || broker::shutdown(&cleanup_app)).await;
    app.exit(0);
}

#[cfg(test)]
mod tests {
    use super::{navigation_is_allowed, webview_load_replaces_content};

    #[test]
    fn every_page_load_after_the_initial_load_requires_scope_cleanup() {
        let seen = std::sync::Mutex::new(std::collections::BTreeSet::new());
        assert!(!webview_load_replaces_content(&seen, "main"));
        assert!(webview_load_replaces_content(&seen, "main"));
        assert!(!webview_load_replaces_content(&seen, "second"));
        assert!(webview_load_replaces_content(&seen, "second"));
    }

    #[test]
    fn navigation_is_limited_to_exact_internal_origins() {
        #[cfg(windows)]
        let allowed = ["http://tauri.localhost/"];
        #[cfg(not(windows))]
        let allowed = ["tauri://localhost/"];
        for allowed in allowed {
            assert!(navigation_is_allowed(&tauri::Url::parse(allowed).unwrap()));
        }
        for blocked in [
            "tauri://external.invalid/",
            "tauri://localhost:4444/",
            "tauri://user@localhost/",
            "https://external.invalid/",
            "https://tauri.localhost:4444/",
            "https://user@tauri.localhost/",
            "https://tauri.localhost.evil.invalid/",
            "file:///tmp/forbidden",
        ] {
            assert!(!navigation_is_allowed(&tauri::Url::parse(blocked).unwrap()));
        }
        #[cfg(windows)]
        for blocked in ["tauri://localhost/", "https://tauri.localhost/"] {
            assert!(!navigation_is_allowed(&tauri::Url::parse(blocked).unwrap()));
        }
        #[cfg(not(windows))]
        for blocked in ["http://tauri.localhost/", "https://tauri.localhost/"] {
            assert!(!navigation_is_allowed(&tauri::Url::parse(blocked).unwrap()));
        }
    }
}
