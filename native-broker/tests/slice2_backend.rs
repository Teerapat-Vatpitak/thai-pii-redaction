use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::Duration;

use aiguard_native_broker_protocol::backend::{BackendTimeouts, ManagedBackend};

fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn backend_test_guard() -> MutexGuard<'static, ()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn python_command(root: &Path, requested: &[String]) -> (PathBuf, Vec<String>) {
    if let Some(value) = std::env::var_os("AIGUARD_TEST_PYTHON") {
        return (PathBuf::from(value), requested.to_vec());
    }
    #[cfg(windows)]
    {
        let configuration = std::fs::read_to_string(root.join(".venv/pyvenv.cfg")).unwrap();
        let executable = configuration
            .lines()
            .find_map(|line| line.strip_prefix("executable = "))
            .map(PathBuf::from)
            .unwrap();
        assert!(executable.is_file());
        let site_packages =
            serde_json::to_string(&root.join(".venv/Lib/site-packages").to_string_lossy()).unwrap();
        let repository = serde_json::to_string(&root.to_string_lossy()).unwrap();
        let setup = format!("import sys;sys.path[:0]=[{site_packages},{repository}];");
        let code = if requested.first().map(String::as_str) == Some("-c") {
            assert_eq!(requested.len(), 2);
            format!("{setup}{}", requested[1])
        } else {
            assert!(!requested.is_empty());
            let arguments = serde_json::to_string(requested).unwrap();
            let script = serde_json::to_string(&requested[0]).unwrap();
            format!(
                "{setup}import runpy;sys.argv={arguments};runpy.run_path({script},run_name='__main__')"
            )
        };
        (executable, vec!["-c".to_owned(), code])
    }
    #[cfg(unix)]
    {
        let candidate = root.join(".venv/bin/python");
        assert!(
            candidate.is_file(),
            "Slice 2 backend tests require the repository Python environment"
        );
        (candidate, requested.to_vec())
    }
}

fn launch_backend(shutdown: Duration) -> ManagedBackend {
    let root = repository_root();
    let requested = vec![
        root.join("launcher.py").to_string_lossy().into_owned(),
        "--native-broker-backend".to_owned(),
    ];
    let (python, arguments) = python_command(&root, &requested);
    ManagedBackend::spawn_synthetic_for_test(
        &python,
        &arguments,
        &root,
        "2.5.0",
        BackendTimeouts {
            startup: Duration::from_secs(20),
            request: Duration::from_secs(2),
            shutdown,
        },
    )
    .unwrap()
}

#[test]
fn inherited_prebound_backend_is_healthy_private_and_gracefully_owned() {
    let _guard = backend_test_guard();
    let mut backend = launch_backend(Duration::from_secs(5));
    let health = backend.health().unwrap();
    assert!(health.status_ok);
    assert!(health.product_compatible);
    assert!(health.data_auth_required);
    assert!(health.control_auth_required);
    let security = backend.security_report();
    assert!(security.listener_prebound);
    assert!(security.listener_exclusive);
    assert!(security.listener_non_inheritable);
    assert!(security.bootstrap_inherited_channel);
    assert!(security.credentials_absent_from_argv);
    assert!(security.credentials_absent_from_environment);
    assert!(security.process_tree_owned);
    let rendered = format!("{backend:?}");
    assert!(!rendered.contains("127.0.0.1"));
    assert!(!rendered.contains("api_key"));
    assert!(!rendered.contains("control_token"));

    let process_id = backend.process_id_for_test();
    assert!(process_id > 0);
    backend.shutdown().unwrap();
    assert!(!backend.is_alive());
}

#[cfg(windows)]
#[test]
fn windows_prebound_listener_rejects_reuse_address_takeover() {
    let _guard = backend_test_guard();
    use windows_sys::Win32::Networking::WinSock::{
        bind, closesocket, setsockopt, WSASocketW, AF_INET, INVALID_SOCKET, IN_ADDR, IPPROTO_TCP,
        SOCKADDR, SOCKADDR_IN, SOCKET_ERROR, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR,
        WSA_FLAG_NO_HANDLE_INHERIT,
    };

    let mut backend = launch_backend(Duration::from_secs(5));
    let address = backend.address_for_test();
    // SAFETY: arguments create one bounded adversarial IPv4 TCP socket.
    let socket = unsafe {
        WSASocketW(
            AF_INET as i32,
            SOCK_STREAM,
            IPPROTO_TCP,
            std::ptr::null(),
            0,
            WSA_FLAG_NO_HANDLE_INHERIT,
        )
    };
    assert_ne!(socket, INVALID_SOCKET);
    let reuse = 1_i32;
    // SAFETY: reuse is a live i32 option value for this socket.
    assert_ne!(
        unsafe {
            setsockopt(
                socket,
                SOL_SOCKET,
                SO_REUSEADDR,
                (&reuse as *const i32).cast(),
                std::mem::size_of::<i32>() as i32,
            )
        },
        SOCKET_ERROR
    );
    let competing = SOCKADDR_IN {
        sin_family: AF_INET,
        sin_port: address.port().to_be(),
        sin_addr: IN_ADDR {
            S_un: windows_sys::Win32::Networking::WinSock::IN_ADDR_0 {
                S_addr: u32::from_ne_bytes([127, 0, 0, 1]),
            },
        },
        sin_zero: [0; 8],
    };
    // SAFETY: competing is a complete loopback sockaddr for the live socket.
    assert_eq!(
        unsafe {
            bind(
                socket,
                (&competing as *const SOCKADDR_IN).cast::<SOCKADDR>(),
                std::mem::size_of::<SOCKADDR_IN>() as i32,
            )
        },
        SOCKET_ERROR
    );
    unsafe { closesocket(socket) };
    backend.shutdown().unwrap();
}

#[cfg(unix)]
#[test]
fn unix_prebound_listener_rejects_reuse_address_takeover() {
    let _guard = backend_test_guard();
    let mut backend = launch_backend(Duration::from_secs(5));
    let address = backend.address_for_test();
    // SAFETY: arguments create one bounded adversarial IPv4 TCP socket.
    let socket = unsafe { libc::socket(libc::AF_INET, libc::SOCK_STREAM, libc::IPPROTO_TCP) };
    assert!(socket >= 0);
    let reuse = 1_i32;
    // SAFETY: reuse is a live i32 option value for this socket.
    assert_eq!(
        unsafe {
            libc::setsockopt(
                socket,
                libc::SOL_SOCKET,
                libc::SO_REUSEADDR,
                (&reuse as *const i32).cast(),
                std::mem::size_of::<i32>() as libc::socklen_t,
            )
        },
        0
    );
    let competing = libc::sockaddr_in {
        #[cfg(target_os = "macos")]
        sin_len: std::mem::size_of::<libc::sockaddr_in>() as u8,
        sin_family: libc::AF_INET as libc::sa_family_t,
        sin_port: address.port().to_be(),
        sin_addr: libc::in_addr {
            s_addr: u32::from_ne_bytes([127, 0, 0, 1]),
        },
        sin_zero: [0; 8],
    };
    // SAFETY: competing is a complete loopback sockaddr for the live socket.
    assert_eq!(
        unsafe {
            libc::bind(
                socket,
                (&competing as *const libc::sockaddr_in).cast(),
                std::mem::size_of::<libc::sockaddr_in>() as libc::socklen_t,
            )
        },
        -1
    );
    unsafe { libc::close(socket) };
    backend.shutdown().unwrap();
}

#[test]
fn incompatible_or_unhealthy_backend_fails_closed_and_is_reaped() {
    let _guard = backend_test_guard();
    let root = repository_root();
    let requested_launcher = vec![
        root.join("launcher.py").to_string_lossy().into_owned(),
        "--native-broker-backend".to_owned(),
    ];
    let (python, launcher_arguments) = python_command(&root, &requested_launcher);
    let incompatible = ManagedBackend::spawn_synthetic_for_test(
        &python,
        &launcher_arguments,
        &root,
        "2.5.1",
        BackendTimeouts {
            startup: Duration::from_secs(5),
            request: Duration::from_millis(250),
            shutdown: Duration::from_secs(1),
        },
    )
    .unwrap_err();
    assert_eq!(incompatible.code(), "broker_unavailable");

    let requested_unhealthy = vec!["-c".to_owned(), "import time; time.sleep(30)".to_owned()];
    let (unhealthy_python, unhealthy_arguments) = python_command(&root, &requested_unhealthy);
    let unhealthy = ManagedBackend::spawn_synthetic_for_test(
        &unhealthy_python,
        &unhealthy_arguments,
        &root,
        "2.5.0",
        BackendTimeouts {
            startup: Duration::from_millis(300),
            request: Duration::from_millis(100),
            shutdown: Duration::from_millis(100),
        },
    )
    .unwrap_err();
    assert_eq!(unhealthy.code(), "broker_unavailable");
}

#[test]
fn shutdown_timeout_forces_the_backend_process_tree_closed() {
    let _guard = backend_test_guard();
    let mut backend = launch_backend(Duration::from_nanos(1));
    let started = std::time::Instant::now();
    let error = backend.shutdown().unwrap_err();
    assert!(started.elapsed() < Duration::from_secs(3));
    assert_eq!(error.code(), "operation_timeout");
    assert!(!backend.is_alive());
    assert_eq!(backend.health().unwrap_err().code(), "broker_unavailable");
}

#[cfg(target_os = "linux")]
#[test]
fn unrelated_inheritable_descriptor_does_not_reach_the_backend() {
    let _guard = backend_test_guard();
    use std::os::fd::AsRawFd;

    let marker_path = std::env::temp_dir().join(format!(
        "aiguard-slice2-inheritance-{}-{}.marker",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let marker = std::fs::File::create(&marker_path).unwrap();
    // SAFETY: this deliberately creates an adversarial inheritable descriptor
    // in the broker process so the launch boundary must seal it before exec.
    let flags = unsafe { libc::fcntl(marker.as_raw_fd(), libc::F_GETFD) };
    assert!(flags >= 0);
    assert_eq!(
        unsafe { libc::fcntl(marker.as_raw_fd(), libc::F_SETFD, flags & !libc::FD_CLOEXEC) },
        0
    );

    let mut backend = launch_backend(Duration::from_secs(5));
    let marker_path = marker_path.canonicalize().unwrap();
    let descriptors = std::fs::read_dir(format!("/proc/{}/fd", backend.process_id_for_test()))
        .unwrap()
        .filter_map(Result::ok)
        .filter_map(|entry| std::fs::read_link(entry.path()).ok())
        .filter_map(|path| path.canonicalize().ok())
        .collect::<Vec<_>>();
    assert!(!descriptors.contains(&marker_path));
    backend.shutdown().unwrap();
    drop(marker);
    std::fs::remove_file(marker_path).unwrap();
}

#[cfg(unix)]
#[test]
fn unix_backend_launch_closes_an_unrelated_inheritable_pipe_writer() {
    let _guard = backend_test_guard();
    let mut descriptors = [0_i32; 2];
    // SAFETY: descriptors provides both outputs required by pipe.
    assert_eq!(unsafe { libc::pipe(descriptors.as_mut_ptr()) }, 0);
    let reader = descriptors[0];
    let writer = descriptors[1];
    // SAFETY: both descriptors were returned by pipe and remain live.
    let writer_flags = unsafe { libc::fcntl(writer, libc::F_GETFD) };
    assert!(writer_flags >= 0);
    assert_eq!(
        unsafe { libc::fcntl(writer, libc::F_SETFD, writer_flags & !libc::FD_CLOEXEC) },
        0
    );
    let reader_flags = unsafe { libc::fcntl(reader, libc::F_GETFL) };
    assert!(reader_flags >= 0);
    assert_eq!(
        unsafe { libc::fcntl(reader, libc::F_SETFL, reader_flags | libc::O_NONBLOCK) },
        0
    );

    let mut backend = launch_backend(Duration::from_secs(5));
    unsafe { libc::close(writer) };
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    let mut reached_eof = false;
    while std::time::Instant::now() < deadline {
        let mut byte = 0_u8;
        // SAFETY: reader is live and byte provides one writable byte.
        let result = unsafe { libc::read(reader, (&mut byte as *mut u8).cast(), 1) };
        if result == 0 {
            reached_eof = true;
            break;
        }
        assert_eq!(result, -1);
        assert_eq!(
            std::io::Error::last_os_error().kind(),
            std::io::ErrorKind::WouldBlock
        );
        std::thread::sleep(Duration::from_millis(10));
    }
    unsafe { libc::close(reader) };
    backend.shutdown().unwrap();
    assert!(reached_eof, "backend inherited an unrelated pipe writer");
}

#[cfg(windows)]
#[test]
fn windows_backend_launch_closes_an_unrelated_inheritable_pipe_writer() {
    let _guard = backend_test_guard();
    use windows_sys::Win32::Foundation::{CloseHandle, SetHandleInformation, HANDLE_FLAG_INHERIT};
    use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
    use windows_sys::Win32::Storage::FileSystem::ReadFile;
    use windows_sys::Win32::System::Pipes::CreatePipe;

    let inheritable = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(),
        bInheritHandle: 1,
    };
    let mut reader = std::ptr::null_mut();
    let mut writer = std::ptr::null_mut();
    // SAFETY: both outputs and the attributes structure are initialized.
    assert_ne!(
        unsafe { CreatePipe(&mut reader, &mut writer, &inheritable, 0) },
        0
    );
    assert_ne!(
        unsafe { SetHandleInformation(reader, HANDLE_FLAG_INHERIT, 0) },
        0
    );
    let mut backend = launch_backend(Duration::from_secs(5));
    unsafe { CloseHandle(writer) };

    let reader_value = reader as usize;
    let (sender, receiver) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        let reader = reader_value as windows_sys::Win32::Foundation::HANDLE;
        let mut byte = 0_u8;
        let mut read = 0_u32;
        // A closed pipe reports either zero bytes or ERROR_BROKEN_PIPE.
        let _ = unsafe {
            ReadFile(
                reader,
                (&mut byte as *mut u8).cast(),
                1,
                &mut read,
                std::ptr::null_mut(),
            )
        };
        unsafe { CloseHandle(reader) };
        let _ = sender.send(());
    });
    let leaked = receiver.recv_timeout(Duration::from_secs(2)).is_err();
    backend.shutdown().unwrap();
    if leaked {
        receiver.recv_timeout(Duration::from_secs(2)).unwrap();
    }
    worker.join().unwrap();
    assert!(!leaked, "backend inherited an unrelated pipe writer");
}

#[test]
fn broker_process_death_does_not_leave_the_backend_alive() {
    let _guard = backend_test_guard();
    let root = repository_root();
    let pid_file = std::env::temp_dir().join(format!(
        "aiguard-slice2-orphan-{}-{}.pid",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--ignored",
            "--exact",
            "broker_parent_crash_fixture",
            "--nocapture",
        ])
        .current_dir(root)
        .env("AIGUARD_SLICE2_PID_FILE", &pid_file)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(91));
    let process_id: u32 = std::fs::read_to_string(&pid_file)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    while process_alive(process_id) && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(!process_alive(process_id));
    std::fs::remove_file(pid_file).unwrap();
}

#[test]
fn broker_death_during_bootstrap_preparation_reaps_the_backend() {
    let _guard = backend_test_guard();
    let root = repository_root();
    let pid_file = std::env::temp_dir().join(format!(
        "aiguard-slice2-early-orphan-{}-{}.pid",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let mut fixture = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--ignored",
            "--exact",
            "broker_early_parent_death_fixture",
            "--nocapture",
        ])
        .current_dir(root)
        .env("AIGUARD_SLICE2_EARLY_PID_FILE", &pid_file)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .unwrap();
    let ready_deadline = std::time::Instant::now() + Duration::from_secs(10);
    while !pid_file.is_file() && std::time::Instant::now() < ready_deadline {
        assert!(fixture.try_wait().unwrap().is_none());
        std::thread::sleep(Duration::from_millis(25));
    }
    if !pid_file.is_file() {
        let _ = fixture.kill();
        let _ = fixture.wait();
        panic!("backend preparation fixture did not publish its process id");
    }
    let published = std::fs::read_to_string(&pid_file).unwrap();
    let process_id: u32 = published
        .trim()
        .parse()
        .unwrap_or_else(|_| panic!("fixed bootstrap stage: {published}"));
    fixture.kill().unwrap();
    fixture.wait().unwrap();

    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    while process_alive(process_id) && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(!process_alive(process_id));
    std::fs::remove_file(pid_file).unwrap();
}

#[test]
#[ignore]
fn broker_parent_crash_fixture() {
    let Some(pid_file) = std::env::var_os("AIGUARD_SLICE2_PID_FILE") else {
        return;
    };
    let backend = launch_backend(Duration::from_secs(5));
    std::fs::write(pid_file, backend.process_id_for_test().to_string()).unwrap();
    std::mem::forget(backend);
    std::process::exit(91);
}

#[test]
#[ignore]
fn broker_early_parent_death_fixture() {
    let Some(_pid_file) = std::env::var_os("AIGUARD_SLICE2_EARLY_PID_FILE") else {
        return;
    };
    let root = repository_root();
    #[cfg(not(target_os = "macos"))]
    let source = r#"
import os
import time
from native_broker_backend import main

def prepare():
    with open(os.environ["AIGUARD_SLICE2_EARLY_PID_FILE"], "w", encoding="ascii") as handle:
        handle.write(str(os.getpid()))
    time.sleep(30)

raise SystemExit(main(prepare))
"#;
    #[cfg(target_os = "macos")]
    let source = r#"
import os
import socket
import sys
import threading
import time
from native_broker_backend import (
    _read_unix_bootstrap,
    _validate_listener,
    _watch_broker_channel_and_exit,
)

def mark(stage):
    with open(os.environ["AIGUARD_SLICE2_EARLY_PID_FILE"], "w", encoding="ascii") as handle:
        handle.write(stage)

try:
    credentials, listener, broker_channel = _read_unix_bootstrap()
except BaseException:
    mark("read-failed")
    time.sleep(30)
    raise

sys.stdin.close()
threading.Thread(
    target=_watch_broker_channel_and_exit,
    args=(broker_channel,),
    daemon=True,
).start()
try:
    _validate_listener(listener)
except BaseException:
    try:
        address = listener.getsockname()
    except BaseException:
        mark("validate-name-inspection-failed")
        time.sleep(30)
        raise
    try:
        accepting = listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
    except BaseException:
        mark("validate-listening-inspection-failed")
        time.sleep(30)
        raise
    try:
        listener.set_inheritable(False)
        inheritable = listener.get_inheritable()
    except BaseException:
        mark("validate-inheritance-inspection-failed")
        time.sleep(30)
        raise
    if listener.family != socket.AF_INET:
        mark("validate-family-failed")
    elif listener.type & socket.SOCK_STREAM != socket.SOCK_STREAM:
        mark("validate-type-failed")
    elif not isinstance(address, tuple) or len(address) < 2 or address[0] != "127.0.0.1":
        mark("validate-address-failed")
    elif type(address[1]) is not int or not 1 <= address[1] <= 65535:
        mark("validate-port-failed")
    elif accepting != 1:
        mark("validate-listening-failed")
    elif inheritable:
        mark("validate-inheritance-failed")
    else:
        mark("validate-unknown-failed")
    time.sleep(30)
    raise

mark(str(os.getpid()))
time.sleep(30)
"#;
    let requested = vec!["-c".to_owned(), source.to_owned()];
    let (python, arguments) = python_command(&root, &requested);
    let _ = ManagedBackend::spawn_synthetic_for_test(
        &python,
        &arguments,
        &root,
        "2.5.0",
        BackendTimeouts {
            startup: Duration::from_secs(60),
            request: Duration::from_secs(1),
            shutdown: Duration::from_secs(1),
        },
    );
}

#[cfg(windows)]
fn process_alive(process_id: u32) -> bool {
    use windows_sys::Win32::Foundation::{CloseHandle, WAIT_TIMEOUT};
    use windows_sys::Win32::System::Threading::{
        OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE,
    };
    // SAFETY: process_id is synthetic test process state and the handle is closed below.
    let handle = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, process_id) };
    if handle.is_null() {
        return false;
    }
    let alive = unsafe { WaitForSingleObject(handle, 0) } == WAIT_TIMEOUT;
    unsafe { CloseHandle(handle) };
    alive
}

#[cfg(unix)]
fn process_alive(process_id: u32) -> bool {
    // SAFETY: signal zero performs no mutation and checks this positive PID.
    unsafe { libc::kill(process_id as libc::pid_t, 0) == 0 }
}
