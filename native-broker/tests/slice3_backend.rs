use std::collections::HashSet;
use std::ops::Deref;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use std::time::{Duration, Instant};

use aiguard_native_broker_protocol::backend::{
    managed_backend_executor, BackendTimeouts, ManagedBackend,
};
use aiguard_native_broker_protocol::data_plane::{
    BackendCall, BackendCompletion, BackendExecutor, BackendGeneration, DataPlane,
};
use aiguard_native_broker_protocol::BrokerRequest;
use base64::Engine;
use serde_json::json;

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

struct TestBackend {
    inner: Arc<Mutex<ManagedBackend>>,
    working_directory: PathBuf,
}

impl Deref for TestBackend {
    type Target = Arc<Mutex<ManagedBackend>>;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

impl Drop for TestBackend {
    fn drop(&mut self) {
        self.inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .force_terminate();
        let _ = std::fs::remove_dir_all(&self.working_directory);
    }
}

fn backend_working_directory() -> PathBuf {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let path = std::env::temp_dir().join(format!(
        "aiguard-slice3-backend-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::AcqRel)
    ));
    std::fs::create_dir(&path).unwrap();
    path
}

struct TimedExecutor {
    inner: Arc<dyn BackendExecutor>,
    backend_nanos: AtomicU64,
}

impl TimedExecutor {
    fn new(inner: Arc<dyn BackendExecutor>) -> Self {
        Self {
            inner,
            backend_nanos: AtomicU64::new(0),
        }
    }

    fn backend_nanos(&self) -> u64 {
        self.backend_nanos.load(Ordering::Acquire)
    }
}

impl BackendExecutor for TimedExecutor {
    fn generation(&self) -> BackendGeneration {
        self.inner.generation()
    }

    fn execute(
        &self,
        call: &BackendCall,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        let started = Instant::now();
        let completion = self.inner.execute(call, deadline, cancelled);
        let elapsed = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        self.backend_nanos.fetch_add(elapsed, Ordering::AcqRel);
        completion
    }

    fn teardown(&self) {
        self.inner.teardown();
    }
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

fn launch_backend() -> TestBackend {
    let root = repository_root();
    let working_directory = backend_working_directory();
    let requested = vec![
        root.join("launcher.py").to_string_lossy().into_owned(),
        "--native-broker-backend".to_owned(),
    ];
    let (python, arguments) = python_command(&root, &requested);
    let inner = Arc::new(Mutex::new(
        ManagedBackend::spawn_synthetic_for_test(
            &python,
            &arguments,
            &working_directory,
            "2.5.0",
            BackendTimeouts {
                startup: Duration::from_secs(20),
                request: Duration::from_secs(2),
                shutdown: Duration::from_secs(5),
            },
        )
        .unwrap(),
    ));
    TestBackend {
        inner,
        working_directory,
    }
}

fn launch_blocking_backend(ready: &Path) -> Arc<Mutex<ManagedBackend>> {
    let root = repository_root();
    let requested = vec![
        root.join("native-broker/tests/fixtures/blocking_private_backend.py")
            .to_string_lossy()
            .into_owned(),
        ready.to_string_lossy().into_owned(),
    ];
    let (python, arguments) = python_command(&root, &requested);
    Arc::new(Mutex::new(
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
        .unwrap(),
    ))
}

fn request(
    operation: &str,
    request_id: &str,
    scope_id: Option<&str>,
    payload: serde_json::Value,
    deadline_ms: u64,
) -> BrokerRequest {
    let local_detection_phases = match operation {
        "detect" | "analyze" | "analyze_report" | "reidentify" => Some(1),
        "sanitize" => Some(2),
        "roundtrip" => Some(6),
        "redact_pdf" => None,
        _ => Some(0),
    };
    BrokerRequest {
        protocol_version: 1,
        request_id: request_id.to_owned(),
        operation: operation.to_owned(),
        scope_id: scope_id.map(str::to_owned),
        payload,
        deadline_ms: Some(deadline_ms),
        local_detection_phases,
        local_intermediate_text_chars: local_detection_phases
            .filter(|phases| *phases > 0)
            .map(|_| 200_000),
        remote_tner_max_calls: 0,
        remote_tner_text_chars: None,
        replay: "never".to_owned(),
        uncertain_completion: "none".to_owned(),
    }
}

#[test]
fn cancelled_submitted_stateless_real_backend_is_killed_before_permit_reuse() {
    let _guard = backend_test_guard();
    let root = std::env::temp_dir().join(format!(
        "aiguard-slice3-blocked-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&root).unwrap();
    let ready = root.join("ready");
    let backend = launch_blocking_backend(&ready);
    let executor = managed_backend_executor(&backend).unwrap();
    let plane = DataPlane::new(executor).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = connection
        .dispatch(
            &request(
                "scope_open",
                "blocked-open",
                None,
                json!({"scope_kind": "desktop_ui"}),
                5_000,
            ),
            &|| false,
        )
        .unwrap()["scope_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let cancelled = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&cancelled);
    let worker = std::thread::spawn(move || {
        connection.dispatch(
            &request(
                "detect",
                "blocked-detect",
                Some(&scope),
                json!({"text": "synthetic blocked input"}),
                30_000,
            ),
            &|| observed.load(Ordering::Acquire),
        )
    });
    let deadline = Instant::now() + Duration::from_secs(10);
    while !ready.is_file() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(ready.is_file());
    assert_eq!(plane.stats().in_flight, 1);
    cancelled.store(true, Ordering::Release);
    let error = worker.join().unwrap().unwrap_err();
    assert_eq!(error.code(), "operation_timeout");
    assert!(plane.stats().backend_invalidated);
    assert_eq!(plane.stats().in_flight, 0);
    assert!(!backend.lock().unwrap().is_alive());
    drop(backend);
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn managed_private_http_v2_executes_stateless_and_session_lifecycle() {
    let _guard = backend_test_guard();
    let backend = launch_backend();
    let executor = Arc::new(TimedExecutor::new(
        managed_backend_executor(&backend).unwrap(),
    ));
    let plane = DataPlane::new(executor.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = connection
        .dispatch(
            &request(
                "scope_open",
                "slice3-open",
                None,
                json!({"scope_kind": "desktop_ui"}),
                5_000,
            ),
            &|| false,
        )
        .unwrap()["scope_id"]
        .as_str()
        .unwrap()
        .to_owned();

    let detected = connection
        .dispatch(
            &request(
                "detect",
                "slice3-detect",
                Some(&scope),
                json!({"text": "synthetic plain input"}),
                30_000,
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(detected["detected_entity_count"], 0);

    let sanitized = connection
        .dispatch(
            &request(
                "sanitize",
                "slice3-sanitize",
                Some(&scope),
                json!({"text": "synthetic plain input", "mode": "token"}),
                30_000,
            ),
            &|| false,
        )
        .unwrap();
    let session = sanitized["session_id"].as_str().unwrap().to_owned();
    assert!(session.starts_with("session-"));
    assert!(!format!("{plane:?}").contains(&session));

    let restored = connection
        .dispatch(
            &request(
                "reidentify",
                "slice3-reidentify",
                Some(&scope),
                json!({"session_id": session.as_str(), "text": "synthetic plain input"}),
                30_000,
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(restored["replaced_count"], 0);

    let audit = connection
        .dispatch(
            &request("audit_log", "slice3-audit", Some(&scope), json!({}), 30_000),
            &|| false,
        )
        .unwrap();
    assert_eq!(audit["limit"], 100);
    assert_eq!(audit["offset"], 0);

    let roundtrip = connection
        .dispatch(
            &request(
                "roundtrip",
                "slice3-roundtrip",
                Some(&scope),
                json!({
                    "text": "synthetic plain input",
                    "mode": "token",
                    "provider": "fake"
                }),
                120_000,
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(roundtrip["provider_used"], "fake");

    let sample_pdf = std::fs::read(repository_root().join("examples/sample_document.pdf")).unwrap();
    let pdf_b64 = base64::engine::general_purpose::STANDARD.encode(sample_pdf);
    let redacted = connection
        .dispatch(
            &request(
                "redact_pdf",
                "slice3-redact-pdf",
                Some(&scope),
                json!({"pdf_b64": pdf_b64.clone()}),
                120_000,
            ),
            &|| false,
        )
        .unwrap();
    assert!(matches!(
        redacted["source_type"].as_str(),
        Some("pdf_text") | Some("pdf_hybrid")
    ));

    let disposed = connection
        .dispatch(
            &request(
                "session_dispose",
                "slice3-dispose",
                Some(&scope),
                json!({"session_id": session}),
                30_000,
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(disposed, json!({"disposed": true}));

    let baseline_resources = resource_count();
    let baseline_rss = rss_bytes();
    let backend_before = executor.backend_nanos();
    let mut detect_nanos = 0_u128;
    let mut session_nanos = 0_u128;
    let mut roundtrip_nanos = 0_u128;
    let mut pdf_nanos = 0_u128;
    for index in 0..24 {
        let call = request(
            "detect",
            &format!("slice3-cycle-detect-{index}"),
            Some(&scope),
            json!({"text": "synthetic plain input"}),
            30_000,
        );
        let started = Instant::now();
        let detected = connection.dispatch(&call, &|| false).unwrap();
        detect_nanos += started.elapsed().as_nanos();
        assert_eq!(detected["detected_entity_count"], 0);
    }
    for index in 0..24 {
        let sanitize_call = request(
            "sanitize",
            &format!("slice3-cycle-sanitize-{index}"),
            Some(&scope),
            json!({"text": "synthetic plain input", "mode": "token"}),
            30_000,
        );
        let started = Instant::now();
        let sanitized = connection.dispatch(&sanitize_call, &|| false).unwrap();
        let handle = sanitized["session_id"].as_str().unwrap().to_owned();
        let masked = sanitized["sanitized_text"].as_str().unwrap().to_owned();
        let reidentify_call = request(
            "reidentify",
            &format!("slice3-cycle-reidentify-{index}"),
            Some(&scope),
            json!({"session_id": handle.as_str(), "text": masked}),
            30_000,
        );
        let restored = connection.dispatch(&reidentify_call, &|| false).unwrap();
        assert_eq!(restored["leftover_count"], 0);
        let dispose_call = request(
            "session_dispose",
            &format!("slice3-cycle-dispose-{index}"),
            Some(&scope),
            json!({"session_id": handle}),
            30_000,
        );
        let disposed = connection.dispatch(&dispose_call, &|| false).unwrap();
        session_nanos += started.elapsed().as_nanos();
        assert_eq!(disposed["disposed"], true);
    }
    for index in 0..8 {
        let call = request(
            "roundtrip",
            &format!("slice3-cycle-roundtrip-{index}"),
            Some(&scope),
            json!({
                "text": "synthetic plain input",
                "mode": "token",
                "provider": "fake"
            }),
            120_000,
        );
        let started = Instant::now();
        let result = connection.dispatch(&call, &|| false).unwrap();
        roundtrip_nanos += started.elapsed().as_nanos();
        assert_eq!(result["provider_used"], "fake");
    }
    for index in 0..3 {
        let call = request(
            "redact_pdf",
            &format!("slice3-cycle-pdf-{index}"),
            Some(&scope),
            json!({"pdf_b64": pdf_b64.clone()}),
            120_000,
        );
        let started = Instant::now();
        let result = connection.dispatch(&call, &|| false).unwrap();
        pdf_nanos += started.elapsed().as_nanos();
        assert!(matches!(
            result["source_type"].as_str(),
            Some("pdf_text") | Some("pdf_hybrid")
        ));
    }
    let forwarding_nanos = detect_nanos + session_nanos + roundtrip_nanos + pdf_nanos;
    let backend_nanos = u128::from(executor.backend_nanos().saturating_sub(backend_before));
    let overhead_nanos = forwarding_nanos.saturating_sub(backend_nanos);
    let final_resources = resource_count();
    let final_rss = rss_bytes();
    assert!(forwarding_nanos < Duration::from_secs(120).as_nanos());
    assert!(final_resources <= baseline_resources + 2);
    assert!(final_rss <= baseline_rss + 64 * 1024 * 1024);
    assert_eq!(plane.stats().desktop_sessions, 0);
    eprintln!(
        "slice3-resource detect24_ms={} session24_ms={} roundtrip8_ms={} pdf3_ms={} forwarding_overhead_us={} resource_delta={} rss_delta_bytes={}",
        detect_nanos / 1_000_000,
        session_nanos / 1_000_000,
        roundtrip_nanos / 1_000_000,
        pdf_nanos / 1_000_000,
        overhead_nanos / 1_000,
        final_resources.saturating_sub(baseline_resources),
        final_rss.saturating_sub(baseline_rss),
    );
    connection.close().unwrap();
    backend.lock().unwrap().shutdown().unwrap();
}

#[test]
fn repeated_forced_teardown_and_restart_rotates_generation_without_resource_growth() {
    let _guard = backend_test_guard();
    let warmup = launch_backend();
    warmup.lock().unwrap().force_terminate();
    drop(warmup);
    let baseline_resources = resource_count();
    let baseline_rss = rss_bytes();
    let mut generations = HashSet::new();

    for _ in 0..3 {
        let backend = launch_backend();
        let executor = managed_backend_executor(&backend).unwrap();
        assert!(generations.insert(executor.generation()));
        backend.lock().unwrap().force_terminate();
        drop(executor);
        drop(backend);
    }

    let final_resources = resource_count();
    let final_rss = rss_bytes();
    assert!(final_resources <= baseline_resources + 1);
    assert!(final_rss <= baseline_rss + 64 * 1024 * 1024);
}

#[cfg(windows)]
fn resource_count() -> u64 {
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, GetProcessHandleCount};

    let mut count = 0_u32;
    assert_ne!(
        unsafe { GetProcessHandleCount(GetCurrentProcess(), &mut count) },
        0
    );
    u64::from(count)
}

#[cfg(unix)]
fn resource_count() -> u64 {
    #[cfg(target_os = "linux")]
    let directory = "/proc/self/fd";
    #[cfg(target_os = "macos")]
    let directory = "/dev/fd";
    u64::try_from(std::fs::read_dir(directory).unwrap().count()).unwrap()
}

#[cfg(windows)]
fn rss_bytes() -> u64 {
    use windows_sys::Win32::System::ProcessStatus::{
        GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::GetCurrentProcess;

    let mut counters = PROCESS_MEMORY_COUNTERS {
        cb: std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
        ..PROCESS_MEMORY_COUNTERS::default()
    };
    assert_ne!(
        unsafe { GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, counters.cb) },
        0
    );
    counters.WorkingSetSize as u64
}

#[cfg(target_os = "linux")]
fn rss_bytes() -> u64 {
    let status = std::fs::read_to_string("/proc/self/status").unwrap();
    let kibibytes = status
        .lines()
        .find_map(|line| line.strip_prefix("VmRSS:"))
        .and_then(|value| value.split_ascii_whitespace().next())
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap();
    kibibytes * 1024
}

#[cfg(target_os = "macos")]
fn rss_bytes() -> u64 {
    let mut usage = unsafe { std::mem::zeroed::<libc::rusage>() };
    assert_eq!(unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut usage) }, 0);
    usage.ru_maxrss as u64
}
