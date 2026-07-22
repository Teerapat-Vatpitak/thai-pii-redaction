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

// ---- port-owner identity (DESK-2 / DESK-5) --------------------------------
//
// Anything can bind 127.0.0.1:8000 before we start; attaching blindly would
// hand every hotkey clipboard grab and UI request to the squatter. The
// strongest identity available without changing the wire protocol is the
// image name of the process that owns the listening socket. Honest limit:
// same-user malware that names its binary aiguard.exe still passes — at that
// point the machine is already lost. All parsers are pure functions so tests
// pin them without a live backend (same pattern as `taskkill_args`).

/// Parse `netstat -ano -p tcp` output: the PID of the LISTENING socket bound
/// to the given local port (exact port match — `:18000` must not match 8000).
fn port_owner_pid_from_netstat(output: &str, port: u16) -> Option<u32> {
    let needle = format!(":{port}");
    for line in output.lines() {
        let cols: Vec<&str> = line.split_whitespace().collect();
        if cols.len() < 5 || cols[0] != "TCP" {
            continue;
        }
        if cols[1].ends_with(&needle) && cols[3] == "LISTENING" {
            return cols[4].parse().ok();
        }
    }
    None
}

/// Parse `tasklist /FI "PID eq N" /FO CSV /NH`: the quoted image name in the
/// first field, or None on the "INFO: No tasks" miss line.
fn image_name_from_tasklist_csv(csv: &str) -> Option<String> {
    let line = csv.lines().next()?.trim();
    let first = line.split("\",\"").next()?;
    let name = first.trim_start_matches('"').trim_end_matches('"').trim();
    if name.is_empty() || !line.starts_with('"') {
        return None;
    }
    Some(name.to_string())
}

/// Parse `lsof -nP -iTCP:<port> -sTCP:LISTEN`: the COMMAND column of the
/// first process row (macOS/Linux path).
fn image_name_from_lsof(output: &str) -> Option<String> {
    for line in output.lines().skip(1) {
        let cols: Vec<&str> = line.split_whitespace().collect();
        if cols.len() >= 2 && cols[1].chars().all(|c| c.is_ascii_digit()) {
            return Some(cols[0].to_string());
        }
    }
    None
}

/// Exact image-name match only: "aiguard-fake.exe" is not our binary.
fn is_aiguard_image(name: &str) -> bool {
    let n = name.to_ascii_lowercase();
    n == "aiguard.exe" || n == "aiguard"
}

#[derive(Debug, PartialEq, Eq)]
enum AttachDecision {
    /// Dev escape hatch (AIGUARD_ALLOW_ATTACH=1): legacy attach, no identity
    /// check — the from-source `uvicorn` backend runs under python.exe.
    AttachLegacy,
    /// Our own binary owns the port. The single-instance plugin excludes a
    /// live second shell, so this is an orphan from a crashed shell whose
    /// token died with it (DESK-5): reap the tree and spawn fresh.
    KillOrphanAndSpawn,
    /// Unknown or foreign owner: never attach, never send it a byte.
    RefuseUntrusted,
}

fn attach_decision(owner_image: Option<&str>, allow_attach: bool) -> AttachDecision {
    if allow_attach {
        return AttachDecision::AttachLegacy;
    }
    match owner_image {
        Some(name) if is_aiguard_image(name) => AttachDecision::KillOrphanAndSpawn,
        _ => AttachDecision::RefuseUntrusted,
    }
}

/// Resolve the image name of the process listening on 127.0.0.1:<port>.
#[cfg(windows)]
fn port_owner_image(port: u16) -> (Option<u32>, Option<String>) {
    let netstat = std::process::Command::new("netstat")
        .args(["-ano", "-p", "tcp"])
        .output();
    let Ok(out) = netstat else { return (None, None) };
    let pid = port_owner_pid_from_netstat(&String::from_utf8_lossy(&out.stdout), port);
    let Some(pid) = pid else { return (None, None) };
    let tasklist = std::process::Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
        .output();
    let name = tasklist
        .ok()
        .and_then(|o| image_name_from_tasklist_csv(&String::from_utf8_lossy(&o.stdout)));
    (Some(pid), name)
}

#[cfg(not(windows))]
fn port_owner_image(port: u16) -> (Option<u32>, Option<String>) {
    let lsof = std::process::Command::new("lsof")
        .args(["-nP", &format!("-iTCP:{port}"), "-sTCP:LISTEN"])
        .output();
    let Ok(out) = lsof else { return (None, None) };
    let text = String::from_utf8_lossy(&out.stdout);
    let name = image_name_from_lsof(&text);
    let pid = text
        .lines()
        .skip(1)
        .filter_map(|l| l.split_whitespace().nth(1))
        .find_map(|p| p.parse().ok());
    (pid, name)
}

/// Raised (as an Err string prefix) when an untrusted process owns the port.
/// lib.rs matches on it to fail closed instead of merely logging.
pub const UNTRUSTED_PORT_OWNER: &str = "untrusted-port-owner";

/// Spawn the `aiguard` sidecar and stream its output to the Rust log.
pub fn spawn(app: &AppHandle) -> Result<(), String> {
    // Something already listening? Decide what it is before trusting it
    // (DESK-2): our own orphan gets reaped and replaced (DESK-5); anything
    // else is refused outright — the app must not run against it.
    if std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8000".parse().expect("valid socket addr"),
        Duration::from_millis(300),
    )
    .is_ok()
    {
        let allow_attach = std::env::var("AIGUARD_ALLOW_ATTACH").is_ok_and(|v| v == "1");
        let (owner_pid, owner_image) = port_owner_image(8000);
        match attach_decision(owner_image.as_deref(), allow_attach) {
            AttachDecision::AttachLegacy => {
                log::info!(
                    "backend already listening on 127.0.0.1:8000; attaching (AIGUARD_ALLOW_ATTACH=1)"
                );
                return Ok(());
            }
            AttachDecision::KillOrphanAndSpawn => {
                let pid = owner_pid.expect("aiguard owner implies a pid");
                log::warn!(
                    "orphan aiguard backend (pid {pid}) owns 127.0.0.1:8000 — reaping and respawning"
                );
                force_kill_tree(pid);
                // Wait for the socket to actually free before binding anew.
                for _ in 0..30 {
                    if std::net::TcpStream::connect_timeout(
                        &"127.0.0.1:8000".parse().expect("valid socket addr"),
                        Duration::from_millis(100),
                    )
                    .is_err()
                    {
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
            AttachDecision::RefuseUntrusted => {
                return Err(format!(
                    "{UNTRUSTED_PORT_OWNER}: 127.0.0.1:8000 is owned by {} (pid {:?}), not an aiguard backend — refusing to attach",
                    owner_image.as_deref().unwrap_or("an unidentifiable process"),
                    owner_pid,
                ));
            }
        }
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

/// The raw HTTP request kill() writes to ask the backend to exit. Kept as a
/// pure function so tests can pin the exact bytes (header order matters to
/// nobody, but presence does: X-AIGuard-Local always, X-AIGuard-Token only
/// when we spawned the sidecar ourselves).
fn shutdown_request(token: Option<&str>) -> String {
    // Keep X-AIGuard-Local for backward compat with a backend that predates
    // the token (grace path); add X-AIGuard-Token when we have one.
    let mut req =
        String::from("POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nX-AIGuard-Local: 1\r\n");
    if let Some(tok) = token {
        req.push_str("X-AIGuard-Token: ");
        req.push_str(tok);
        req.push_str("\r\n");
    }
    req.push_str("Content-Length: 0\r\nConnection: close\r\n\r\n");
    req
}

/// Best-effort graceful stop: bounded connect + write of the shutdown request.
fn send_shutdown(addr: std::net::SocketAddr, token: Option<&str>) {
    use std::io::Write;
    // Bounded: a bare connect()/write() to a filtered or half-open loopback
    // socket could otherwise block the exit path (this runs on the main thread
    // from ExitRequested). The force-kill below stays the real guarantee.
    if let Ok(mut stream) = std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(500))
    {
        let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
        let _ = stream.write_all(shutdown_request(token).as_bytes());
    }
}

/// Kill sequence, parameterized by backend address so tests can point it at a
/// mock listener: (1) ask the backend to exit, (2) kill the child handle,
/// (3) force-kill the stored PID's process tree (the real guarantee).
pub(crate) fn kill_with(state: &SidecarState, addr: std::net::SocketAddr) {
    // Snapshot the token (a uuid v4 hex string — safe to place verbatim in a
    // header) so the shutdown request can authenticate when the backend
    // enforces the boot token. `None` (attached to a pre-existing backend) ->
    // legacy header only.
    let token = state.token.lock().unwrap().clone();
    send_shutdown(addr, token.as_deref());
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

/// Kill the sidecar process tree. Best-effort: graceful shutdown request, then
/// kill the child handle, then force-kill the stored PID's tree to also reap
/// the PyInstaller child.
pub fn kill(app: &AppHandle) {
    // Best-effort graceful stop: ask the backend to exit itself. The taskkill
    // tree-kill below stays the guarantee (a POST can't reliably reap the
    // PyInstaller child process).
    let state = app.state::<SidecarState>();
    kill_with(&state, "127.0.0.1:8000".parse().expect("valid socket addr"));
}

/// Hook to call from the Tauri `run` closure on every runtime event.
pub fn on_run_event(app: &AppHandle, event: &RunEvent) {
    if let RunEvent::ExitRequested { .. } = event {
        kill(app);
    }
}

#[cfg(test)]
mod port_owner_tests {
    use super::*;

    const NETSTAT: &str = "\
  Proto  Local Address          Foreign Address        State           PID\r\n\
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1100\r\n\
  TCP    127.0.0.1:18000        0.0.0.0:0              LISTENING       7777\r\n\
  TCP    127.0.0.1:8000         127.0.0.1:52011        ESTABLISHED     4321\r\n\
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       4321\r\n\
  TCP    [::1]:8000             [::]:0                 LISTENING       4321\r\n";

    #[test]
    fn netstat_parser_finds_the_listening_pid_on_the_exact_port() {
        assert_eq!(port_owner_pid_from_netstat(NETSTAT, 8000), Some(4321));
    }

    #[test]
    fn netstat_parser_ignores_other_ports_and_non_listening_rows() {
        // :18000 must not substring-match :8000, ESTABLISHED rows don't count.
        assert_eq!(port_owner_pid_from_netstat(NETSTAT, 9000), None);
        let established_only =
            "  TCP    127.0.0.1:8000    127.0.0.1:5201    ESTABLISHED    4321\r\n";
        assert_eq!(port_owner_pid_from_netstat(established_only, 8000), None);
    }

    #[test]
    fn tasklist_csv_parser_extracts_the_image_name() {
        let csv = "\"aiguard.exe\",\"4321\",\"Console\",\"1\",\"120,564 K\"\r\n";
        assert_eq!(
            image_name_from_tasklist_csv(csv),
            Some("aiguard.exe".to_string())
        );
        assert_eq!(image_name_from_tasklist_csv("INFO: No tasks are running.\r\n"), None);
        assert_eq!(image_name_from_tasklist_csv(""), None);
    }

    #[test]
    fn lsof_parser_extracts_the_command_name() {
        let out = "\
COMMAND   PID  USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME\n\
aiguard  4321 teera    3u  IPv4 0x1234      0t0    TCP 127.0.0.1:8000 (LISTEN)\n";
        assert_eq!(image_name_from_lsof(out), Some("aiguard".to_string()));
        assert_eq!(image_name_from_lsof("COMMAND PID USER\n"), None);
        assert_eq!(image_name_from_lsof(""), None);
    }

    #[test]
    fn aiguard_image_names_match_exactly_not_by_substring() {
        assert!(is_aiguard_image("aiguard.exe"));
        assert!(is_aiguard_image("AIGUARD.EXE"));
        assert!(is_aiguard_image("aiguard"));
        assert!(!is_aiguard_image("python.exe"));
        assert!(!is_aiguard_image("aiguard-fake.exe"));
        assert!(!is_aiguard_image("not-aiguard.exe"));
    }

    #[test]
    fn attach_decision_is_fail_closed() {
        // Explicit dev escape hatch: legacy attach no matter who owns the port.
        assert_eq!(
            attach_decision(Some("python.exe"), true),
            AttachDecision::AttachLegacy
        );
        // Our own binary on the port = orphan from a dead shell (the
        // single-instance plugin excludes a live second shell): reap + respawn.
        assert_eq!(
            attach_decision(Some("aiguard.exe"), false),
            AttachDecision::KillOrphanAndSpawn
        );
        // Anyone else — or nobody identifiable — never receives our traffic.
        assert_eq!(
            attach_decision(Some("python.exe"), false),
            AttachDecision::RefuseUntrusted
        );
        assert_eq!(attach_decision(None, false), AttachDecision::RefuseUntrusted);
    }
}

#[cfg(test)]
mod shutdown_request_tests {
    use super::*;

    #[test]
    fn request_without_token_has_legacy_header_only() {
        let req = shutdown_request(None);
        assert!(req.starts_with("POST /api/shutdown HTTP/1.1\r\n"));
        assert!(req.contains("X-AIGuard-Local: 1\r\n"));
        assert!(!req.contains("X-AIGuard-Token"));
        assert!(req.ends_with("Content-Length: 0\r\nConnection: close\r\n\r\n"));
    }

    #[test]
    fn request_with_token_carries_both_headers() {
        let req = shutdown_request(Some("cafe1234"));
        assert!(req.contains("X-AIGuard-Local: 1\r\n"));
        assert!(req.contains("X-AIGuard-Token: cafe1234\r\n"));
    }

    #[test]
    fn kill_sequence_sends_authenticated_shutdown_to_the_given_addr() {
        use std::io::Read;
        use std::sync::mpsc;

        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind mock backend");
        let addr = listener.local_addr().expect("mock addr");
        let (tx, rx) = mpsc::channel::<String>();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = String::new();
                let _ = stream.read_to_string(&mut buf);
                let _ = tx.send(buf);
            }
        });

        let state = SidecarState::default();
        *state.token.lock().unwrap() = Some("tok123".to_string());
        kill_with(&state, addr);

        let received = rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .expect("mock backend never received the shutdown request");
        assert!(received.contains("POST /api/shutdown"));
        assert!(received.contains("X-AIGuard-Token: tok123"));
        assert!(received.contains("X-AIGuard-Local: 1"));
    }
}

#[cfg(all(test, windows))]
mod kill_tree_tests {
    use super::*;

    #[test]
    fn kill_with_force_kills_the_stored_pid_tree() {
        // Victim: cmd spawns ping as a child -> a real 2-process tree. ping -n 60
        // keeps it alive far longer than the test needs.
        let mut victim = std::process::Command::new("cmd")
            .args(["/C", "ping -n 60 127.0.0.1 > NUL"])
            .spawn()
            .expect("spawn victim tree");
        let pid = victim.id();

        // Unreachable addr: connect_timeout fails fast, proving the kill path
        // does not depend on a live backend.
        let state = SidecarState::default();
        *state.pid.lock().unwrap() = Some(pid);
        kill_with(&state, "127.0.0.1:1".parse().expect("valid socket addr"));

        // The tree must die promptly; poll try_wait up to ~5s.
        let mut dead = false;
        for _ in 0..50 {
            if victim.try_wait().expect("try_wait").is_some() {
                dead = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        assert!(dead, "victim process tree survived kill_with/taskkill");
    }
}
