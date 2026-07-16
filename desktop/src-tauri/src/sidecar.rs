/// Build the Windows `taskkill` arguments to force-kill a process tree by PID.
/// PyInstaller onefile spawns a child; `/T` kills the whole tree, `/F` forces it.
#[cfg(windows)]
pub fn taskkill_args(pid: u32) -> Vec<String> {
    vec![
        "/PID".to_string(),
        pid.to_string(),
        "/T".to_string(),
        "/F".to_string(),
    ]
}

#[cfg(all(test, windows))]
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
use std::time::Duration;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Holds the running sidecar child so it can be killed on exit.
#[derive(Default)]
pub struct SidecarState {
    pub child: Mutex<Option<CommandChild>>,
    pub pid: Mutex<Option<u32>>,
    /// Boot token generated for the sidecar we spawned, if any. `None` when we
    /// attached to a backend already listening (dev mode / no token), so
    /// `kill()` falls back to the legacy `X-AIGuard-Local` header only.
    pub token: Mutex<Option<String>>,
}

/// Spawn the `aiguard` sidecar and stream its output to the Rust log.
pub fn spawn(app: &AppHandle) -> Result<(), String> {
    // Don't spawn a second backend if one is already listening (defends the
    // "no second backend" invariant even if single-instance ever fails to
    // short-circuit the second process).
    if std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8000".parse().expect("valid socket addr"),
        Duration::from_millis(300),
    )
    .is_ok()
    {
        log::info!("backend already listening on 127.0.0.1:8000; skipping sidecar spawn");
        return Ok(());
    }

    // Random per-boot shared secret. Passed to the sidecar via its env so the
    // backend enforces the control plane (/api/shutdown, delete-session), and
    // stored in state so kill() can authenticate its shutdown request. Never
    // logged.
    let token = uuid::Uuid::new_v4().simple().to_string();

    let (mut rx, child) = app
        .shell()
        .sidecar("aiguard")
        .map_err(|e| format!("create sidecar: {e}"))?
        .env("AIGUARD_TOKEN", &token)
        .spawn()
        .map_err(|e| format!("spawn sidecar: {e}"))?;

    let pid = child.pid();
    let state = app.state::<SidecarState>();
    *state.child.lock().unwrap() = Some(child);
    *state.pid.lock().unwrap() = Some(pid);
    *state.token.lock().unwrap() = Some(token);

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

/// Force-kill the sidecar's process tree by PID (best-effort, platform-specific).
#[cfg(windows)]
fn force_kill_tree(pid: u32) {
    let _ = std::process::Command::new("taskkill")
        .args(taskkill_args(pid))
        .output();
}

#[cfg(not(windows))]
fn force_kill_tree(pid: u32) {
    // No portable process-tree kill; SIGKILL the pid. child.kill() above already
    // handled the directly-spawned process; this reaps the PyInstaller onefile
    // child on macOS/Linux.
    let _ = std::process::Command::new("kill")
        .arg("-9")
        .arg(pid.to_string())
        .output();
}

/// Kill the sidecar process tree. Best-effort: kill the child handle, then
/// force-kill the stored PID's tree to also reap the PyInstaller child.
pub fn kill(app: &AppHandle) {
    // Best-effort graceful stop: ask the backend to exit itself. The taskkill
    // tree-kill below stays the guarantee (a POST can't reliably reap the
    // PyInstaller child process).
    use std::io::Write;
    let state = app.state::<SidecarState>();
    // Snapshot the token (a uuid v4 hex string — safe to place verbatim in a
    // header) so the shutdown request can authenticate when the backend
    // enforces the boot token. `None` (attached to a pre-existing backend) ->
    // legacy header only.
    let token = state.token.lock().unwrap().clone();
    // Bounded: a bare connect()/write() to a filtered or half-open loopback
    // socket could otherwise block the exit path (this runs on the main thread
    // from ExitRequested). The force-kill below stays the real guarantee.
    if let Ok(mut stream) = std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8000".parse().expect("valid socket addr"),
        Duration::from_millis(500),
    ) {
        let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
        // Keep X-AIGuard-Local for backward compat with a backend that predates
        // the token (grace path); add X-AIGuard-Token when we have one.
        let mut req =
            String::from("POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nX-AIGuard-Local: 1\r\n");
        if let Some(tok) = &token {
            req.push_str("X-AIGuard-Token: ");
            req.push_str(tok);
            req.push_str("\r\n");
        }
        req.push_str("Content-Length: 0\r\nConnection: close\r\n\r\n");
        let _ = stream.write_all(req.as_bytes());
    }
    // Take the values out of their mutexes into locals first: this drops each
    // MutexGuard temporary at the `let` statement rather than holding a borrow
    // of `state` across the `if let` block (which trips E0597 on drop order).
    let child = state.child.lock().unwrap().take();
    if let Some(child) = child {
        let _ = child.kill();
    }
    let pid = state.pid.lock().unwrap().take();
    if let Some(pid) = pid {
        force_kill_tree(pid);
    }
}

/// Hook to call from the Tauri `run` closure on every runtime event.
pub fn on_run_event(app: &AppHandle, event: &RunEvent) {
    if let RunEvent::ExitRequested { .. } = event {
        kill(app);
    }
}
