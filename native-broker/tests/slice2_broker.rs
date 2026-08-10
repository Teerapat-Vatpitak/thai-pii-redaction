use std::path::{Path, PathBuf};
use std::sync::atomic::Ordering;
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::thread;
use std::time::Duration;

use aiguard_native_broker_protocol::backend::{BackendTimeouts, ManagedBackend};
use aiguard_native_broker_protocol::broker::{BrokerExit, BrokerRuntime, BrokerRuntimeConfig};
use aiguard_native_broker_protocol::control_client::{
    spawn_sealed_broker_process_for_test, BrokerControlClient,
};
use aiguard_native_broker_protocol::manifest::ComponentManifest;
use aiguard_native_broker_protocol::transport::{
    NativeStream, PlatformEndpoint, MAX_ACTIVE_CONNECTIONS,
};
use aiguard_native_broker_protocol::ProtocolError;
use base64::Engine;
use sha2::{Digest, Sha256};

fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn broker_test_guard() -> MutexGuard<'static, ()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn backend_python_command(root: &Path, requested: &[String]) -> (PathBuf, Vec<String>) {
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
        let site_packages =
            serde_json::to_string(&root.join(".venv/Lib/site-packages").to_string_lossy()).unwrap();
        let repository = serde_json::to_string(&root.to_string_lossy()).unwrap();
        let arguments = serde_json::to_string(requested).unwrap();
        let script = serde_json::to_string(&requested[0]).unwrap();
        let code = format!(
            "import sys,runpy;sys.path[:0]=[{site_packages},{repository}];sys.argv={arguments};runpy.run_path({script},run_name='__main__')"
        );
        (executable, vec!["-c".to_owned(), code])
    }
    #[cfg(unix)]
    {
        let candidate = root.join(".venv/bin/python");
        assert!(candidate.is_file());
        (candidate, requested.to_vec())
    }
}

fn unique(label: &str) -> String {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    format!("aiguard-{label}-{}-{nonce}", std::process::id())
}

fn test_temp_root(label: &str) -> PathBuf {
    #[cfg(unix)]
    let base = Path::new("/tmp").to_path_buf();
    #[cfg(windows)]
    let base = std::env::temp_dir();
    base.join(unique(label))
}

fn digest_file(path: &Path) -> String {
    format!("{:x}", Sha256::digest(std::fs::read(path).unwrap()))
}

fn remove_tree_after_process_exit(path: &Path) {
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    loop {
        match std::fs::remove_dir_all(path) {
            Ok(()) => return,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return,
            Err(error)
                if error.kind() == std::io::ErrorKind::PermissionDenied
                    && std::time::Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(20));
            }
            Err(error) => panic!("fixture process did not release its package: {error}"),
        }
    }
}

struct ManifestFixture {
    manifest: Option<ComponentManifest>,
    paths: Vec<PathBuf>,
}

impl ManifestFixture {
    fn create(role: &str) -> Self {
        let executable = std::env::current_exe().unwrap().canonicalize().unwrap();
        let directory = executable.parent().unwrap();
        let token = unique("manifest");
        let broker_name = format!("{token}-broker-fixture");
        let backend_name = format!("{token}-backend-fixture");
        let manifest_name = format!("{token}.json");
        let broker_path = directory.join(&broker_name);
        let backend_path = directory.join(&backend_name);
        let manifest_path = directory.join(&manifest_name);
        let marker = b"AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0";
        std::fs::write(&broker_path, marker).unwrap();
        std::fs::write(&backend_path, b"synthetic backend component").unwrap();
        let manifest = serde_json::json!({
            "schema_version": 1,
            "product_version": "2.5.0",
            "broker": {
                "component_id": "native-broker",
                "path": broker_name,
                "sha256": digest_file(&broker_path),
                "build_id": "2.5.0"
            },
            "clients": [{
                "component_id": format!("{role}-fixture"),
                "role": role,
                "path": executable.file_name().unwrap().to_string_lossy(),
                "sha256": digest_file(&executable),
                "build_id": "2.5.0"
            }],
            "backend": {
                "component_id": "python-backend",
                "path": backend_name,
                "sha256": digest_file(&backend_path),
                "build_id": "2.5.0",
                "arguments": ["--native-broker-backend"]
            }
        });
        std::fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        let loaded = ComponentManifest::load(&manifest_path, "2.5.0").unwrap();
        loaded.verify_client_executable(&executable).unwrap();
        Self {
            manifest: Some(loaded),
            paths: vec![manifest_path, broker_path, backend_path],
        }
    }
}

impl Drop for ManifestFixture {
    fn drop(&mut self) {
        for path in &self.paths {
            let _ = std::fs::remove_file(path);
        }
    }
}

fn launch_backend() -> ManagedBackend {
    let root = repository_root();
    let requested = vec![
        root.join("launcher.py").to_string_lossy().into_owned(),
        "--native-broker-backend".to_owned(),
    ];
    let (python, arguments) = backend_python_command(&root, &requested);
    ManagedBackend::spawn_synthetic_for_test(
        &python,
        &arguments,
        &root,
        "2.5.0",
        BackendTimeouts {
            startup: Duration::from_secs(20),
            request: Duration::from_secs(2),
            shutdown: Duration::from_secs(5),
        },
    )
    .unwrap()
}

fn runtime_config() -> BrokerRuntimeConfig {
    BrokerRuntimeConfig {
        accept_poll: Duration::from_millis(20),
        hello_timeout: Duration::from_secs(5),
        request_timeout: Duration::from_secs(5),
        idle_timeout: Duration::from_secs(2),
        drain_timeout: Duration::from_secs(6),
    }
}

fn connect(publication: &str) -> NativeStream {
    NativeStream::connect(publication, Duration::from_secs(5)).unwrap()
}

fn send(stream: &mut NativeStream, value: serde_json::Value) -> serde_json::Value {
    send_with_limit(stream, value, 1_048_576, Duration::from_secs(5))
}

fn send_with_limit(
    stream: &mut NativeStream,
    value: serde_json::Value,
    max_frame_bytes: u64,
    timeout: Duration,
) -> serde_json::Value {
    stream
        .write_value(&value, max_frame_bytes, timeout)
        .unwrap();
    let response = stream
        .read_frame(max_frame_bytes, timeout)
        .unwrap()
        .unwrap();
    serde_json::from_slice(&response).unwrap()
}

fn hello(stream: &mut NativeStream, role: &str, versions: serde_json::Value) -> serde_json::Value {
    send(
        stream,
        serde_json::json!({
            "claimed_role": role,
            "client_product_version": "2.5.0",
            "request_id": format!("hello-{role}"),
            "supported_protocol_versions": versions,
        }),
    )
}

fn create_live_session(stream: &mut NativeStream, label: &str) -> (String, String) {
    assert_eq!(
        hello(stream, "desktop", serde_json::json!([1]))["role"],
        "desktop"
    );
    let opened = send(
        stream,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "scope_open",
            "payload": {"scope_kind": "desktop_ui"},
            "request_id": format!("{label}-scope"),
        }),
    );
    let scope = opened["result"]["scope_id"].as_str().unwrap().to_owned();
    let sanitized = send(
        stream,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "sanitize",
            "payload": {"mode": "token", "text": "synthetic runtime cleanup"},
            "request_id": format!("{label}-sanitize"),
            "scope_id": scope,
        }),
    );
    let session = sanitized["result"]["session_id"]
        .as_str()
        .unwrap()
        .to_owned();
    (scope, session)
}

fn wait_for_desktop_sessions(
    plane: &aiguard_native_broker_protocol::data_plane::DataPlane,
    expected: usize,
) {
    let deadline = std::time::Instant::now() + Duration::from_secs(6);
    while plane.stats().desktop_sessions != expected && std::time::Instant::now() < deadline {
        thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(plane.stats().desktop_sessions, expected);
}

#[test]
fn live_sessions_are_cleaned_on_eof_malformed_frame_and_broker_shutdown() {
    let _guard = broker_test_guard();
    let mut fixture = ManifestFixture::create("desktop");
    let endpoint_root = test_temp_root("stateful-runtime-cleanup");
    let endpoint = PlatformEndpoint::create_for_test(&endpoint_root).unwrap();
    let publication = endpoint.publication();
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        fixture.manifest.take().unwrap(),
        launch_backend(),
        "2.5.0",
        runtime_config(),
    )
    .unwrap();
    let plane = runtime.data_plane_for_test();
    let stop = runtime.stop_signal_for_test();
    let server = thread::spawn(move || runtime.run().unwrap());

    let mut eof = connect(&publication);
    let _ = create_live_session(&mut eof, "eof");
    wait_for_desktop_sessions(&plane, 1);
    drop(eof);
    wait_for_desktop_sessions(&plane, 0);
    assert!(!plane.stats().backend_invalidated);

    let mut malformed = connect(&publication);
    let _ = create_live_session(&mut malformed, "malformed");
    wait_for_desktop_sessions(&plane, 1);
    malformed
        .write_raw_for_test(&[0, 0, 0, 1, b'{'], Duration::from_secs(2))
        .unwrap();
    let failure = malformed
        .read_frame(1_048_576, Duration::from_secs(2))
        .unwrap()
        .unwrap();
    let failure: serde_json::Value = serde_json::from_slice(&failure).unwrap();
    assert_eq!(failure["error"]["code"], "request_invalid");
    drop(malformed);
    wait_for_desktop_sessions(&plane, 0);
    assert!(!plane.stats().backend_invalidated);

    let mut shutdown = connect(&publication);
    let _ = create_live_session(&mut shutdown, "shutdown");
    wait_for_desktop_sessions(&plane, 1);
    stop.store(true, Ordering::Release);
    assert_eq!(server.join().unwrap(), BrokerExit::Idle);
    wait_for_desktop_sessions(&plane, 0);
    assert!(!plane.stats().backend_invalidated);
    drop(shutdown);
    #[cfg(unix)]
    std::fs::remove_dir_all(endpoint_root).unwrap();
}

#[test]
fn authenticated_desktop_health_and_slice3_data_are_live_while_global_stop_stays_disabled() {
    let _guard = broker_test_guard();
    let mut fixture = ManifestFixture::create("desktop");
    let endpoint_root = test_temp_root("desktop-runtime");
    let endpoint = PlatformEndpoint::create_for_test(&endpoint_root).unwrap();
    let publication = endpoint.publication();
    assert!(!publication.contains("127.0.0.1"));
    assert!(!publication.contains("api_key"));
    assert!(!publication.contains("control"));
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        fixture.manifest.take().unwrap(),
        launch_backend(),
        "2.5.0",
        runtime_config(),
    )
    .unwrap();

    let mut pipelined = connect(&publication);
    pipelined
        .write_value(
            &serde_json::json!({
                "claimed_role": "desktop",
                "client_product_version": "2.5.0",
                "request_id": "pipelined-hello",
                "supported_protocol_versions": [1],
            }),
            1_048_576,
            Duration::from_secs(2),
        )
        .unwrap();
    pipelined
        .write_value(
            &serde_json::json!({
                "broker_protocol_version": 1,
                "operation": "broker_health",
                "payload": {},
                "request_id": "pipelined-health",
            }),
            1_048_576,
            Duration::from_secs(2),
        )
        .unwrap();
    let server = thread::spawn(move || runtime.run().unwrap());

    // Keep the server end live long enough to prove a terminal response is
    // retained until a delayed authenticated peer can consume it.
    thread::sleep(Duration::from_millis(500));
    let rejected = pipelined
        .read_frame(1_048_576, Duration::from_secs(2))
        .unwrap()
        .unwrap();
    let rejected: serde_json::Value = serde_json::from_slice(&rejected).unwrap();
    assert_eq!(rejected["error"]["code"], "request_invalid");
    drop(pipelined);

    let mut wrong_role = connect(&publication);
    let rejected = hello(&mut wrong_role, "maintenance", serde_json::json!([1]));
    assert_eq!(rejected["error"]["code"], "broker_unauthorized");
    drop(wrong_role);

    let mut incompatible = connect(&publication);
    let rejected = hello(&mut incompatible, "desktop", serde_json::json!([2]));
    assert_eq!(rejected["error"]["code"], "broker_incompatible");
    drop(incompatible);

    let mut client = connect(&publication);
    let negotiated = hello(&mut client, "desktop", serde_json::json!([1]));
    assert_eq!(negotiated["role"], "desktop");
    assert_eq!(negotiated["broker_protocol_version"], 1);
    let health = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": "desktop-health",
        }),
    );
    assert_eq!(health["result"], serde_json::json!({"status": "ok"}));

    let opened = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "scope_open",
            "payload": {"scope_kind": "desktop_ui"},
            "request_id": "desktop-scope-open",
        }),
    );
    let scope = opened["result"]["scope_id"].as_str().unwrap();
    let data = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "detect",
            "payload": {"text": "synthetic transport fixture"},
            "request_id": "desktop-data",
            "scope_id": scope,
        }),
    );
    assert_eq!(data["result"]["detected_entity_count"], 0);

    let sanitized = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "sanitize",
            "payload": {"mode": "token", "text": "synthetic transport fixture"},
            "request_id": "desktop-sanitize",
            "scope_id": scope,
        }),
    );
    let session = sanitized["result"]["session_id"].as_str().unwrap();
    assert!(session.starts_with("session-"));
    let reidentified = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "reidentify",
            "payload": {
                "session_id": session,
                "text": sanitized["result"]["sanitized_text"],
            },
            "request_id": "desktop-reidentify",
            "scope_id": scope,
        }),
    );
    assert_eq!(reidentified["result"]["leftover_count"], 0);

    let roundtrip = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "roundtrip",
            "payload": {
                "mode": "token",
                "provider": "fake",
                "text": "synthetic transport fixture",
            },
            "request_id": "desktop-roundtrip",
            "scope_id": scope,
        }),
    );
    assert_eq!(roundtrip["result"]["provider_used"], "fake");

    let sample_pdf = std::fs::read(repository_root().join("examples/sample_document.pdf")).unwrap();
    let pdf_started = std::time::Instant::now();
    let redacted = send_with_limit(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "redact_pdf",
            "payload": {
                "pdf_b64": base64::engine::general_purpose::STANDARD.encode(sample_pdf),
            },
            "request_id": "desktop-redact-pdf",
            "scope_id": scope,
        }),
        aiguard_native_broker_protocol::max_frame_bytes(),
        Duration::from_secs(60),
    );
    assert!(matches!(
        redacted["result"]["source_type"].as_str(),
        Some("pdf_text") | Some("pdf_hybrid")
    ));
    eprintln!(
        "native-runtime-pdf response_bytes={} roundtrip_ms={}",
        serde_json::to_vec(&redacted).unwrap().len(),
        pdf_started.elapsed().as_millis()
    );
    let disposed = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "session_dispose",
            "payload": {"session_id": session},
            "request_id": "desktop-session-dispose",
            "scope_id": scope,
        }),
    );
    assert_eq!(disposed["result"], serde_json::json!({"disposed": true}));

    let global_stop = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "maintenance_drain_stop",
            "payload": {},
            "request_id": "desktop-stop-denied",
        }),
    );
    assert_eq!(global_stop["error"]["code"], "broker_unauthorized");
    drop(client);
    assert_eq!(server.join().unwrap(), BrokerExit::Idle);
    #[cfg(unix)]
    std::fs::remove_dir_all(endpoint_root).unwrap();
}

#[test]
fn transient_backend_lock_busy_keeps_the_health_connection_live() {
    let _guard = broker_test_guard();
    let mut fixture = ManifestFixture::create("desktop");
    let endpoint_root = test_temp_root("health-lock-busy");
    let endpoint = PlatformEndpoint::create_for_test(&endpoint_root).unwrap();
    let publication = endpoint.publication();
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        fixture.manifest.take().unwrap(),
        launch_backend(),
        "2.5.0",
        runtime_config(),
    )
    .unwrap();
    let backend = runtime.backend_handle_for_test();
    let backend_guard = backend.lock().unwrap();
    let server = thread::spawn(move || runtime.run().unwrap());

    let mut client = connect(&publication);
    hello(&mut client, "desktop", serde_json::json!([1]));
    let busy = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": "health-lock-busy",
        }),
    );
    assert_eq!(busy["error"]["code"], "broker_busy");

    drop(backend_guard);
    let recovered = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": "health-lock-recovered",
        }),
    );
    assert_eq!(recovered["result"]["status"], "ok");
    drop(client);
    assert_eq!(server.join().unwrap(), BrokerExit::Idle);
    #[cfg(unix)]
    std::fs::remove_dir_all(endpoint_root).unwrap();
}

#[test]
fn maintenance_can_health_and_stop_but_cannot_request_data() {
    let _guard = broker_test_guard();
    let mut fixture = ManifestFixture::create("maintenance");
    let endpoint_root = test_temp_root("maintenance-runtime");
    let endpoint = PlatformEndpoint::create_for_test(&endpoint_root).unwrap();
    let publication = endpoint.publication();
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        fixture.manifest.take().unwrap(),
        launch_backend(),
        "2.5.0",
        runtime_config(),
    )
    .unwrap();
    let server = thread::spawn(move || runtime.run().unwrap());
    let mut client = connect(&publication);
    assert_eq!(
        hello(&mut client, "maintenance", serde_json::json!([1]))["role"],
        "maintenance"
    );
    let health = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": "maintenance-health",
        }),
    );
    assert_eq!(health["result"]["status"], "ok");
    let data = send(
        &mut client,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "detect",
            "payload": {"text": "synthetic transport fixture"},
            "request_id": "maintenance-data-denied",
            "scope_id": "synthetic-scope",
        }),
    );
    assert_eq!(data["error"]["code"], "broker_unauthorized");
    drop(client);

    let mut control = connect(&publication);
    hello(&mut control, "maintenance", serde_json::json!([1]));
    let stopped = send(
        &mut control,
        serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "maintenance_drain_stop",
            "payload": {},
            "request_id": "maintenance-stop",
        }),
    );
    assert_eq!(stopped["result"], serde_json::json!({"accepted": true}));
    drop(control);
    assert_eq!(server.join().unwrap(), BrokerExit::Maintenance);
    #[cfg(unix)]
    std::fs::remove_dir_all(endpoint_root).unwrap();
}

#[test]
fn backend_crash_after_runtime_construction_closes_endpoint_and_returns_fixed_exit() {
    let _guard = broker_test_guard();
    let mut fixture = ManifestFixture::create("desktop");
    let endpoint_root = test_temp_root("crashed-runtime");
    let endpoint = PlatformEndpoint::create_for_test(&endpoint_root).unwrap();
    let publication = endpoint.publication();
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        fixture.manifest.take().unwrap(),
        launch_backend(),
        "2.5.0",
        runtime_config(),
    )
    .unwrap();
    runtime.force_backend_terminate_for_test();
    assert_eq!(runtime.run().unwrap(), BrokerExit::BackendFailed);
    assert!(NativeStream::connect(&publication, Duration::from_millis(50)).is_err());
    #[cfg(unix)]
    std::fs::remove_dir_all(endpoint_root).unwrap();
}

#[cfg(unix)]
#[test]
fn unix_broker_launch_closes_an_unrelated_inheritable_pipe_writer() {
    let mut descriptors = [0_i32; 2];
    // SAFETY: descriptors provides both outputs required by pipe.
    assert_eq!(unsafe { libc::pipe(descriptors.as_mut_ptr()) }, 0);
    let reader = descriptors[0];
    let writer = descriptors[1];
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

    let executable = std::env::current_exe().unwrap();
    let arguments = [
        "--ignored".to_owned(),
        "--exact".to_owned(),
        "sealed_broker_process_fixture".to_owned(),
        "--nocapture".to_owned(),
    ];
    let mut child =
        spawn_sealed_broker_process_for_test(&executable, &arguments, executable.parent().unwrap())
            .unwrap();
    unsafe { libc::close(writer) };
    thread::sleep(Duration::from_millis(100));
    assert!(child.try_wait().unwrap().is_none());
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    let mut reached_eof = false;
    while std::time::Instant::now() < deadline {
        let mut byte = 0_u8;
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
        thread::sleep(Duration::from_millis(10));
    }
    unsafe { libc::close(reader) };
    child.kill().unwrap();
    child.wait().unwrap();
    assert!(reached_eof, "broker inherited an unrelated pipe writer");
}

#[cfg(windows)]
#[test]
fn windows_broker_launch_closes_an_unrelated_inheritable_pipe_writer() {
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
    assert_ne!(
        unsafe { CreatePipe(&mut reader, &mut writer, &inheritable, 0) },
        0
    );
    assert_ne!(
        unsafe { SetHandleInformation(reader, HANDLE_FLAG_INHERIT, 0) },
        0
    );

    let executable = std::env::current_exe().unwrap();
    let arguments = [
        "--ignored".to_owned(),
        "--exact".to_owned(),
        "sealed_broker_process_fixture".to_owned(),
        "--nocapture".to_owned(),
    ];
    let mut child =
        spawn_sealed_broker_process_for_test(&executable, &arguments, executable.parent().unwrap())
            .unwrap();
    unsafe { CloseHandle(writer) };
    thread::sleep(Duration::from_millis(100));
    assert!(child.try_wait().unwrap().is_none());

    let reader_value = reader as usize;
    let (sender, receiver) = std::sync::mpsc::channel();
    let worker = thread::spawn(move || {
        let reader = reader_value as windows_sys::Win32::Foundation::HANDLE;
        let mut byte = 0_u8;
        let mut read = 0_u32;
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
    child.kill().unwrap();
    child.wait().unwrap();
    if leaked {
        receiver.recv_timeout(Duration::from_secs(2)).unwrap();
    }
    worker.join().unwrap();
    assert!(!leaked, "broker inherited an unrelated pipe writer");
}

#[test]
#[ignore]
fn sealed_broker_process_fixture() {
    thread::sleep(Duration::from_secs(10));
}

#[test]
fn control_client_binds_kernel_server_identity_to_the_expected_package_broker() {
    let _guard = broker_test_guard();
    let executable = std::env::current_exe().unwrap().canonicalize().unwrap();
    let package_root = test_temp_root("control-client-package");
    let endpoint_root = test_temp_root("control-client-runtime");
    std::fs::create_dir(&package_root).unwrap();
    let suffix = executable
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy()))
        .unwrap_or_default();
    let broker_path = package_root.join(format!("broker-fixture{suffix}"));
    let alternate_broker_path = package_root.join(format!("alternate-broker-fixture{suffix}"));
    let client_path = package_root.join(format!("desktop-fixture{suffix}"));
    let backend_path = package_root.join("backend-fixture.bin");
    for target in [&broker_path, &alternate_broker_path, &client_path] {
        std::fs::copy(&executable, target).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(target, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
    }
    std::fs::write(&backend_path, b"synthetic backend component").unwrap();
    let manifest_path = package_root.join("native-components-v1.json");
    let mismatched_manifest_path = package_root.join("mismatched-components-v1.json");
    write_control_client_manifest(&manifest_path, &broker_path, &client_path, &backend_path);
    write_control_client_manifest(
        &mismatched_manifest_path,
        &alternate_broker_path,
        &client_path,
        &backend_path,
    );
    let ready_path = package_root.join("broker.ready");
    let mut broker = std::process::Command::new(&broker_path)
        .args([
            "--ignored",
            "--exact",
            "control_client_broker_fixture",
            "--nocapture",
        ])
        .env("AIGUARD_SLICE2_MANIFEST", &manifest_path)
        .env("AIGUARD_SLICE2_ENDPOINT_ROOT", &endpoint_root)
        .env("AIGUARD_SLICE2_READY", &ready_path)
        .env("AIGUARD_SLICE2_HELLO_DELAY_MS", "500")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let ready_deadline = std::time::Instant::now() + Duration::from_secs(20);
    while !ready_path.is_file() && std::time::Instant::now() < ready_deadline {
        assert!(broker.try_wait().unwrap().is_none());
        thread::sleep(Duration::from_millis(10));
    }
    assert!(ready_path.is_file());

    let started = std::time::Instant::now();
    let admitted =
        run_control_client_fixture(&client_path, &manifest_path, &endpoint_root, false, true);
    assert!(admitted.status.success());
    assert_no_sensitive_output(&admitted);
    assert!(started.elapsed() >= Duration::from_millis(350));
    assert!(started.elapsed() < Duration::from_secs(10));
    let rejected = run_control_client_fixture(
        &client_path,
        &mismatched_manifest_path,
        &endpoint_root,
        true,
        false,
    );
    assert!(rejected.status.success());
    assert_no_sensitive_output(&rejected);

    let broker_output = broker.wait_with_output().unwrap();
    assert!(broker_output.status.success());
    assert_no_sensitive_output(&broker_output);
    #[cfg(unix)]
    let _ = std::fs::remove_dir_all(&endpoint_root);
    remove_tree_after_process_exit(&package_root);
}

#[test]
fn on_demand_bootstrap_and_simultaneous_clients_converge_on_one_broker() {
    let _guard = broker_test_guard();
    let executable = std::env::current_exe().unwrap().canonicalize().unwrap();
    let package_root = test_temp_root("on-demand-package");
    let endpoint_root = test_temp_root("on-demand-runtime");
    let owners_root = package_root.join("owners");
    let done_root = package_root.join("done");
    let connected_root = package_root.join("connected");
    let holders_root = package_root.join("holders");
    let release_path = package_root.join("release");
    let expand_path = package_root.join("expand");
    let keeper_ready_path = package_root.join("keeper-ready");
    let overflow_result_path = package_root.join("overflow-result");
    std::fs::create_dir_all(&owners_root).unwrap();
    std::fs::create_dir_all(&done_root).unwrap();
    std::fs::create_dir_all(&connected_root).unwrap();
    std::fs::create_dir_all(&holders_root).unwrap();
    let suffix = executable
        .extension()
        .map(|value| format!(".{}", value.to_string_lossy()))
        .unwrap_or_default();
    let broker_path = package_root.join(format!("broker-fixture{suffix}"));
    let client_path = package_root.join(format!("desktop-fixture{suffix}"));
    let backend_path = package_root.join("backend-fixture.bin");
    for target in [&broker_path, &client_path] {
        std::fs::copy(&executable, target).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(target, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
    }
    std::fs::write(&backend_path, b"synthetic backend component").unwrap();
    let manifest_path = package_root.join("native-components-v1.json");
    write_control_client_manifest(&manifest_path, &broker_path, &client_path, &backend_path);

    let mut clients = Vec::new();
    for _ in 0..4 {
        clients.push(
            std::process::Command::new(&client_path)
                .args([
                    "--ignored",
                    "--exact",
                    "control_client_client_fixture",
                    "--nocapture",
                ])
                .env("AIGUARD_SLICE2_MANIFEST", &manifest_path)
                .env("AIGUARD_SLICE2_ENDPOINT_ROOT", &endpoint_root)
                .env("AIGUARD_SLICE2_EXPECT_DENIED", "false")
                .env("AIGUARD_SLICE2_START_IF_ABSENT", "true")
                .env("AIGUARD_SLICE2_LAUNCH_BROKER", &broker_path)
                .env("AIGUARD_SLICE2_OWNERS_ROOT", &owners_root)
                .env("AIGUARD_SLICE2_DONE_ROOT", &done_root)
                .env("AIGUARD_SLICE2_CONNECTED_ROOT", &connected_root)
                .env("AIGUARD_SLICE2_IDLE_MS", "5000")
                .env("AIGUARD_SLICE2_SKIP_HEALTH", "true")
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
                .unwrap(),
        );
    }
    let connected_deadline = std::time::Instant::now() + Duration::from_secs(30);
    while std::fs::read_dir(&connected_root).unwrap().count() != 4
        && std::time::Instant::now() < connected_deadline
    {
        thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(std::fs::read_dir(&connected_root).unwrap().count(), 4);

    let mut saturation = std::process::Command::new(&client_path)
        .args([
            "--ignored",
            "--exact",
            "control_client_client_fixture",
            "--nocapture",
        ])
        .env("AIGUARD_SLICE2_MANIFEST", &manifest_path)
        .env("AIGUARD_SLICE2_ENDPOINT_ROOT", &endpoint_root)
        .env("AIGUARD_SLICE2_EXPECT_DENIED", "false")
        .env("AIGUARD_SLICE2_START_IF_ABSENT", "false")
        .env("AIGUARD_SLICE2_SKIP_HEALTH", "true")
        .env("AIGUARD_SLICE2_HOLDERS_ROOT", &holders_root)
        .env("AIGUARD_SLICE2_RELEASE_PATH", &release_path)
        .env("AIGUARD_SLICE2_EXPAND_PATH", &expand_path)
        .env("AIGUARD_SLICE2_KEEPER_READY_PATH", &keeper_ready_path)
        .env(
            "AIGUARD_SLICE2_HOLD_COUNT",
            MAX_ACTIVE_CONNECTIONS.to_string(),
        )
        .env("AIGUARD_SLICE2_RESULT_PATH", &overflow_result_path)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let keeper_deadline = std::time::Instant::now() + Duration::from_secs(15);
    while !keeper_ready_path.is_file() && std::time::Instant::now() < keeper_deadline {
        assert!(saturation.try_wait().unwrap().is_none());
        thread::sleep(Duration::from_millis(20));
    }
    assert!(keeper_ready_path.is_file());
    for mut client in clients {
        assert!(client.wait().unwrap().success(), "client fixture failed");
    }
    std::fs::write(&expand_path, b"expand").unwrap();
    let saturation_deadline = std::time::Instant::now() + Duration::from_secs(15);
    while (!overflow_result_path.is_file()
        || std::fs::read_dir(&holders_root).unwrap().count() != 1)
        && std::time::Instant::now() < saturation_deadline
    {
        if saturation.try_wait().unwrap().is_some() {
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    std::fs::write(&release_path, b"release").unwrap();
    let capacity_result = std::fs::read_to_string(&overflow_result_path).unwrap_or_default();
    let saturation_output = saturation.wait_with_output().unwrap();
    assert_no_sensitive_output(&saturation_output);
    assert!(
        saturation_output.status.success(),
        "capacity fixture failed"
    );
    assert_eq!(capacity_result, "broker_busy");

    let deadline = std::time::Instant::now() + Duration::from_secs(15);
    while std::fs::read_dir(&done_root).unwrap().count() != 1
        && std::time::Instant::now() < deadline
    {
        thread::sleep(Duration::from_millis(20));
    }
    assert_eq!(std::fs::read_dir(&owners_root).unwrap().count(), 1);
    assert_eq!(std::fs::read_dir(&done_root).unwrap().count(), 1);
    #[cfg(unix)]
    let _ = std::fs::remove_dir_all(&endpoint_root);
    remove_tree_after_process_exit(&package_root);
}

#[test]
fn expired_on_demand_deadline_never_launches_a_late_broker() {
    use std::sync::atomic::{AtomicBool, Ordering};

    let _guard = broker_test_guard();
    let fixture = ManifestFixture::create("desktop");
    let endpoint_root = test_temp_root("expired-start-runtime");
    let launched = AtomicBool::new(false);
    let error = BrokerControlClient::connect_or_start_with_launcher_for_test(
        &endpoint_root,
        &fixture.paths[0],
        "desktop",
        "2.5.0",
        Duration::from_nanos(1),
        || {
            launched.store(true, Ordering::Release);
            Ok(())
        },
    )
    .unwrap_err();
    assert_eq!(error.code(), "broker_unavailable");
    assert!(!launched.load(Ordering::Acquire));
}

fn write_control_client_manifest(path: &Path, broker: &Path, client: &Path, backend: &Path) {
    let manifest = serde_json::json!({
        "schema_version": 1,
        "product_version": "2.5.0",
        "broker": {
            "component_id": "native-broker",
            "path": broker.file_name().unwrap().to_string_lossy(),
            "sha256": digest_file(broker),
            "build_id": "2.5.0"
        },
        "clients": [{
            "component_id": "desktop-fixture",
            "role": "desktop",
            "path": client.file_name().unwrap().to_string_lossy(),
            "sha256": digest_file(client),
            "build_id": "2.5.0"
        }],
        "backend": {
            "component_id": "python-backend",
            "path": backend.file_name().unwrap().to_string_lossy(),
            "sha256": digest_file(backend),
            "build_id": "2.5.0",
            "arguments": ["--native-broker-backend"]
        }
    });
    std::fs::write(path, serde_json::to_vec(&manifest).unwrap()).unwrap();
}

fn run_control_client_fixture(
    executable: &Path,
    manifest: &Path,
    endpoint_root: &Path,
    expect_denied: bool,
    start_if_absent: bool,
) -> std::process::Output {
    std::process::Command::new(executable)
        .args([
            "--ignored",
            "--exact",
            "control_client_client_fixture",
            "--nocapture",
        ])
        .env("AIGUARD_SLICE2_MANIFEST", manifest)
        .env("AIGUARD_SLICE2_ENDPOINT_ROOT", endpoint_root)
        .env("AIGUARD_SLICE2_EXPECT_DENIED", expect_denied.to_string())
        .env(
            "AIGUARD_SLICE2_START_IF_ABSENT",
            start_if_absent.to_string(),
        )
        .output()
        .unwrap()
}

fn assert_no_sensitive_output(output: &std::process::Output) {
    for bytes in [&output.stdout, &output.stderr] {
        let rendered = String::from_utf8_lossy(bytes);
        for forbidden in [
            "synthetic-api-key",
            "synthetic-control-token",
            "Authorization: Bearer",
            "127.0.0.1:",
            "Traceback",
        ] {
            assert!(!rendered.contains(forbidden));
        }
    }
}

#[test]
#[ignore]
fn control_client_broker_fixture() {
    let Some(manifest_path) = std::env::var_os("AIGUARD_SLICE2_MANIFEST") else {
        return;
    };
    let endpoint_root = PathBuf::from(std::env::var_os("AIGUARD_SLICE2_ENDPOINT_ROOT").unwrap());
    let manifest = ComponentManifest::load(Path::new(&manifest_path), "2.5.0").unwrap();
    manifest
        .verify_broker_executable(&std::env::current_exe().unwrap())
        .unwrap();
    let reservation = match PlatformEndpoint::reserve_for_test(&endpoint_root) {
        Ok(reservation) => reservation,
        Err(error) if error.code() == "broker_unavailable" => return,
        Err(error) => panic!("unexpected reservation failure: {error}"),
    };
    if let Some(root) = std::env::var_os("AIGUARD_SLICE2_OWNERS_ROOT") {
        std::fs::write(
            PathBuf::from(root).join(std::process::id().to_string()),
            b"owner",
        )
        .unwrap();
    }
    let backend = launch_backend();
    let endpoint = reservation.publish().unwrap();
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        manifest,
        backend,
        "2.5.0",
        BrokerRuntimeConfig {
            idle_timeout: std::env::var("AIGUARD_SLICE2_IDLE_MS")
                .ok()
                .and_then(|value| value.parse().ok())
                .map(Duration::from_millis)
                .unwrap_or(Duration::from_secs(2)),
            hello_timeout: Duration::from_secs(5),
            request_timeout: Duration::from_secs(5),
            drain_timeout: Duration::from_secs(5),
            ..runtime_config()
        },
    )
    .unwrap();
    if let Some(ready_path) = std::env::var_os("AIGUARD_SLICE2_READY") {
        std::fs::write(ready_path, b"ready").unwrap();
    }
    if let Ok(delay) = std::env::var("AIGUARD_SLICE2_HELLO_DELAY_MS") {
        thread::sleep(Duration::from_millis(delay.parse().unwrap()));
    }
    assert_eq!(runtime.run().unwrap(), BrokerExit::Idle);
    if let Some(root) = std::env::var_os("AIGUARD_SLICE2_DONE_ROOT") {
        std::fs::write(
            PathBuf::from(root).join(std::process::id().to_string()),
            b"done",
        )
        .unwrap();
    }
}

#[test]
#[ignore]
fn control_client_client_fixture() {
    let Some(manifest_path) = std::env::var_os("AIGUARD_SLICE2_MANIFEST") else {
        return;
    };
    let endpoint_root = PathBuf::from(std::env::var_os("AIGUARD_SLICE2_ENDPOINT_ROOT").unwrap());
    let expected_denial =
        std::env::var("AIGUARD_SLICE2_EXPECT_DENIED").unwrap_or_default() == "true";
    let expected_error = std::env::var("AIGUARD_SLICE2_EXPECT_ERROR").ok();
    let start_if_absent =
        std::env::var("AIGUARD_SLICE2_START_IF_ABSENT").unwrap_or_default() == "true";
    let result = if start_if_absent {
        if let Some(broker_path) = std::env::var_os("AIGUARD_SLICE2_LAUNCH_BROKER") {
            let broker_path = PathBuf::from(broker_path);
            let manifest_path = PathBuf::from(&manifest_path);
            let launch_manifest_path = manifest_path.clone();
            let launch_root = endpoint_root.clone();
            BrokerControlClient::connect_or_start_with_launcher_for_test(
                &endpoint_root,
                &manifest_path,
                "desktop",
                "2.5.0",
                Duration::from_secs(30),
                move || {
                    let mut command = std::process::Command::new(&broker_path);
                    command
                        .args([
                            "--ignored",
                            "--exact",
                            "control_client_broker_fixture",
                            "--nocapture",
                        ])
                        .env("AIGUARD_SLICE2_MANIFEST", &launch_manifest_path)
                        .env("AIGUARD_SLICE2_ENDPOINT_ROOT", &launch_root)
                        .stdout(std::process::Stdio::null())
                        .stderr(std::process::Stdio::null());
                    for name in [
                        "AIGUARD_SLICE2_OWNERS_ROOT",
                        "AIGUARD_SLICE2_DONE_ROOT",
                        "AIGUARD_SLICE2_IDLE_MS",
                    ] {
                        if let Some(value) = std::env::var_os(name) {
                            command.env(name, value);
                        }
                    }
                    let mut child = command
                        .spawn()
                        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
                    thread::spawn(move || {
                        let _ = child.wait();
                    });
                    Ok(())
                },
            )
        } else {
            BrokerControlClient::connect_or_start_for_test(
                &endpoint_root,
                Path::new(&manifest_path),
                "desktop",
                "2.5.0",
                Duration::from_secs(15),
            )
        }
    } else {
        BrokerControlClient::connect_existing_for_test(
            &endpoint_root,
            Path::new(&manifest_path),
            "desktop",
            "2.5.0",
            Duration::from_secs(5),
        )
    };
    if let Some(expected_error) = expected_error {
        let code = result.unwrap_err().code().to_owned();
        if let Some(path) = std::env::var_os("AIGUARD_SLICE2_RESULT_PATH") {
            std::fs::write(path, &code).unwrap();
        }
        assert_eq!(code, expected_error);
    } else if expected_denial {
        assert_eq!(result.unwrap_err().code(), "broker_unauthorized");
    } else {
        let mut client = match result {
            Ok(client) => client,
            Err(error) => {
                if let Some(path) = std::env::var_os("AIGUARD_SLICE2_RESULT_PATH") {
                    std::fs::write(path, format!("initial-{}", error.code())).unwrap();
                    return;
                }
                panic!("control client fixture failed with fixed code");
            }
        };
        if std::env::var("AIGUARD_SLICE2_SKIP_HEALTH").unwrap_or_default() != "true" {
            client.health().unwrap();
        }
        if let Some(root) = std::env::var_os("AIGUARD_SLICE2_CONNECTED_ROOT") {
            std::fs::write(
                PathBuf::from(root).join(std::process::id().to_string()),
                b"connected",
            )
            .unwrap();
        }
        if let Some(root) = std::env::var_os("AIGUARD_SLICE2_HOLDERS_ROOT") {
            let hold_count = std::env::var("AIGUARD_SLICE2_HOLD_COUNT")
                .ok()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(1);
            let release = PathBuf::from(std::env::var_os("AIGUARD_SLICE2_RELEASE_PATH").unwrap());
            if hold_count > 1 {
                if let Some(expand) = std::env::var_os("AIGUARD_SLICE2_EXPAND_PATH") {
                    if let Some(ready) = std::env::var_os("AIGUARD_SLICE2_KEEPER_READY_PATH") {
                        std::fs::write(ready, b"ready").unwrap();
                    }
                    let expand = PathBuf::from(expand);
                    let expand_deadline = std::time::Instant::now() + Duration::from_secs(30);
                    while !expand.is_file() && std::time::Instant::now() < expand_deadline {
                        if let Err(error) = client.health() {
                            std::fs::write(
                                PathBuf::from(
                                    std::env::var_os("AIGUARD_SLICE2_RESULT_PATH").unwrap(),
                                ),
                                format!("keepalive-{}", error.code()),
                            )
                            .unwrap();
                            return;
                        }
                        thread::sleep(Duration::from_millis(250));
                    }
                    assert!(expand.is_file());
                }
                if let Err(error) = client.health() {
                    std::fs::write(
                        PathBuf::from(std::env::var_os("AIGUARD_SLICE2_RESULT_PATH").unwrap()),
                        format!("refresh-{}", error.code()),
                    )
                    .unwrap();
                    return;
                }
                let publication = PlatformEndpoint::publication_for_test(&endpoint_root).unwrap();
                let mut workers = Vec::with_capacity(hold_count - 1);
                for index in 1..hold_count {
                    let worker_publication = publication.clone();
                    workers.push(thread::spawn(move || {
                        let mut stream =
                            NativeStream::connect(&worker_publication, Duration::from_secs(5))?;
                        stream.write_value(
                            &serde_json::json!({
                                "claimed_role": "desktop",
                                "client_product_version": "2.5.0",
                                "request_id": format!("capacity-hello-{index}"),
                                "supported_protocol_versions": [1],
                            }),
                            1_048_576,
                            Duration::from_secs(5),
                        )?;
                        let raw = stream
                            .read_frame(1_048_576, Duration::from_secs(5))?
                            .ok_or_else(|| ProtocolError::new("broker_unavailable", None))?;
                        let response: serde_json::Value = serde_json::from_slice(&raw)
                            .map_err(|_| ProtocolError::new("request_invalid", None))?;
                        if response["role"] != "desktop" || response["broker_protocol_version"] != 1
                        {
                            return Err(ProtocolError::new("broker_unavailable", None));
                        }
                        Ok(stream)
                    }));
                }
                let mut held_streams = Vec::with_capacity(hold_count - 1);
                for worker in workers {
                    let result = worker
                        .join()
                        .unwrap_or_else(|_| Err(ProtocolError::new("broker_unavailable", None)));
                    match result {
                        Ok(next) => held_streams.push(next),
                        Err(error) => {
                            std::fs::write(
                                PathBuf::from(
                                    std::env::var_os("AIGUARD_SLICE2_RESULT_PATH").unwrap(),
                                ),
                                format!("setup-{}-{}", error.code(), held_streams.len() + 1),
                            )
                            .unwrap();
                            return;
                        }
                    }
                }
                let capacity_root = endpoint_root.clone();
                let capacity_manifest = PathBuf::from(&manifest_path);
                let capacity = thread::spawn(move || {
                    match BrokerControlClient::connect_existing_for_test(
                        &capacity_root,
                        &capacity_manifest,
                        "desktop",
                        "2.5.0",
                        Duration::from_secs(5),
                    ) {
                        Err(error) => error.code().to_owned(),
                        Ok(extra) => {
                            drop(extra);
                            "unexpected-admission".to_owned()
                        }
                    }
                });
                let mut keepalive_error = None;
                while !capacity.is_finished() {
                    match client.health() {
                        Ok(()) => {}
                        Err(error) if error.code() == "broker_busy" => {}
                        Err(error) => {
                            keepalive_error = Some(error.code().to_owned());
                            break;
                        }
                    }
                    thread::sleep(Duration::from_millis(100));
                }
                let code = capacity
                    .join()
                    .unwrap_or_else(|_| "capacity-worker-failed".to_owned());
                if let Some(code) = keepalive_error {
                    std::fs::write(
                        PathBuf::from(std::env::var_os("AIGUARD_SLICE2_RESULT_PATH").unwrap()),
                        format!("capacity-keepalive-{code}"),
                    )
                    .unwrap();
                    return;
                }
                let health_deadline = std::time::Instant::now() + Duration::from_secs(5);
                loop {
                    match client.health() {
                        Ok(()) => break,
                        Err(error)
                            if error.code() == "broker_busy"
                                && std::time::Instant::now() < health_deadline =>
                        {
                            thread::sleep(Duration::from_millis(20));
                        }
                        Err(error) => {
                            std::fs::write(
                                PathBuf::from(
                                    std::env::var_os("AIGUARD_SLICE2_RESULT_PATH").unwrap(),
                                ),
                                format!("post-capacity-{}", error.code()),
                            )
                            .unwrap();
                            return;
                        }
                    }
                }
                std::fs::write(
                    PathBuf::from(std::env::var_os("AIGUARD_SLICE2_RESULT_PATH").unwrap()),
                    &code,
                )
                .unwrap();
                std::fs::write(
                    PathBuf::from(root).join(std::process::id().to_string()),
                    b"holding",
                )
                .unwrap();
                let deadline = std::time::Instant::now() + Duration::from_secs(30);
                while !release.is_file() && std::time::Instant::now() < deadline {
                    thread::sleep(Duration::from_millis(5));
                }
                assert!(release.is_file());
                drop(held_streams);
                drop(client);
                return;
            }
            std::fs::write(
                PathBuf::from(root).join(std::process::id().to_string()),
                b"holding",
            )
            .unwrap();
            let deadline = std::time::Instant::now() + Duration::from_secs(60);
            while !release.is_file() && std::time::Instant::now() < deadline {
                thread::sleep(Duration::from_millis(10));
            }
            assert!(release.is_file());
        }
    }
}
