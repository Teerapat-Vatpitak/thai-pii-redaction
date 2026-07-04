/// Build the Windows `taskkill` arguments to force-kill a process tree by PID.
/// PyInstaller onefile spawns a child; `/T` kills the whole tree, `/F` forces it.
pub fn taskkill_args(pid: u32) -> Vec<String> {
    vec![
        "/PID".to_string(),
        pid.to_string(),
        "/T".to_string(),
        "/F".to_string(),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn taskkill_args_builds_tree_force_kill() {
        assert_eq!(
            taskkill_args(1234),
            vec!["/PID", "1234", "/T", "/F"]
        );
    }
}

use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Holds the running sidecar child so it can be killed on exit.
#[derive(Default)]
pub struct SidecarState {
    pub child: Mutex<Option<CommandChild>>,
    pub pid: Mutex<Option<u32>>,
}

/// Spawn the `aiguard` sidecar and stream its output to the Rust log.
pub fn spawn(app: &AppHandle) -> Result<(), String> {
    let (mut rx, child) = app
        .shell()
        .sidecar("aiguard")
        .map_err(|e| format!("create sidecar: {e}"))?
        .spawn()
        .map_err(|e| format!("spawn sidecar: {e}"))?;

    let pid = child.pid();
    let state = app.state::<SidecarState>();
    *state.child.lock().unwrap() = Some(child);
    *state.pid.lock().unwrap() = Some(pid);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    log::info!("[aiguard] {}", String::from_utf8_lossy(&bytes).trim_end());
                }
                CommandEvent::Stderr(bytes) => {
                    log::warn!("[aiguard] {}", String::from_utf8_lossy(&bytes).trim_end());
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!("[aiguard] terminated: {:?}", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Kill the sidecar process tree. Best-effort: kill the child handle, then
/// `taskkill /T /F` on the stored PID to also reap the PyInstaller child.
pub fn kill(app: &AppHandle) {
    let state = app.state::<SidecarState>();
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
    if let Some(pid) = state.pid.lock().unwrap().take() {
        let _ = std::process::Command::new("taskkill")
            .args(taskkill_args(pid))
            .output();
    }
}

/// Hook to call from the Tauri `run` closure on every runtime event.
pub fn on_run_event(app: &AppHandle, event: &RunEvent) {
    if let RunEvent::ExitRequested { .. } = event {
        kill(app);
    }
}
