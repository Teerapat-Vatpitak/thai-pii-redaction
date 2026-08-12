// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Some(code) = desktop_lib::native_host_lifecycle_exit_code() {
        std::process::exit(code);
    }
    if let Some(code) = desktop_lib::stable_appimage_reexec_exit_code() {
        std::process::exit(code);
    }
    desktop_lib::run()
}
