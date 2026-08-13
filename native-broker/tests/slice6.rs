use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

use aiguard_native_broker_protocol::admission::{
    decide_admission, BrokerOsContext, OsPeerContext, PackageConsistencyEvidence,
};
use aiguard_native_broker_protocol::backend::{BackendTimeouts, ManagedBackend};
use aiguard_native_broker_protocol::broker::{BrokerExit, BrokerRuntime, BrokerRuntimeConfig};
use aiguard_native_broker_protocol::control::{ControlAction, Slice2ControlPlane};
use aiguard_native_broker_protocol::data_plane::{
    BackendCall, BackendCompletion, BackendExecutor, BackendFailure, BackendGeneration,
    BackendReply, DataPlane,
};
use aiguard_native_broker_protocol::desktop_client::{DesktopBrokerClient, DesktopScopeKind};
use aiguard_native_broker_protocol::extension_client::{ExtensionBrokerClient, ExtensionScopeKind};
use aiguard_native_broker_protocol::lifecycle::{
    begin_component_replacement, component_replacement_active, drain_existing_broker_for_test,
    finish_component_replacement, DrainOutcome,
};
use aiguard_native_broker_protocol::manifest::ComponentManifest;
use aiguard_native_broker_protocol::transport::PlatformEndpoint;
use aiguard_native_broker_protocol::{negotiate_hello, BrokerRequest, ProtocolError};
use serde_json::json;
use sha2::{Digest, Sha256};

const PRODUCT_VERSION: &str = env!("CARGO_PKG_VERSION");
const DESKTOP_LIVE_FIXTURE: &str = "slice6_desktop_live_scope_fixture";
const EXTENSION_LIVE_FIXTURE: &str = "slice6_extension_live_scope_fixture";
const MANAGER_DRAIN_FIXTURE: &str = "slice6_manager_drain_fixture";
const BROKER_RUNTIME_FIXTURE: &str = "slice6_broker_runtime_fixture";
const MANAGER_DRAIN_SECONDS: u64 = 45;
const MANAGER_DRAIN_TIMEOUT: Duration = Duration::from_secs(MANAGER_DRAIN_SECONDS);
// Leave bounded startup and process-exit margin outside the drain operation.
const MANAGER_EXIT_TIMEOUT: Duration = Duration::from_secs(MANAGER_DRAIN_SECONDS + 10);
// Client fixtures outlive the manager so scheduler delay cannot win the race.
const LIVE_FIXTURE_SIGNAL_TIMEOUT: Duration = Duration::from_secs(MANAGER_DRAIN_SECONDS + 10 + 20);

fn slice6_guard() -> MutexGuard<'static, ()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn unique_root(label: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    #[cfg(unix)]
    let root = PathBuf::from("/tmp").join(format!(
        "ag6-{:x}-{:x}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    #[cfg(not(unix))]
    let root = std::env::temp_dir().join(format!(
        "aiguard-slice6-{label}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    std::fs::create_dir(&root).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        assert!(root.join("broker.sock").as_os_str().len() < 100);
    }
    let _ = label;
    root
}

fn executable_name(name: &str) -> String {
    #[cfg(windows)]
    {
        format!("{name}.exe")
    }
    #[cfg(not(windows))]
    {
        name.to_owned()
    }
}

fn digest(path: &Path) -> String {
    format!("{:x}", Sha256::digest(std::fs::read(path).unwrap()))
}

fn make_executable(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755)).unwrap();
    }
    #[cfg(not(unix))]
    let _ = path;
}

fn set_fixture_owner(path: &Path) {
    #[cfg(windows)]
    assert!(
        aiguard_native_broker_protocol::manifest::windows_set_owner_to_current_user_for_test(path)
    );
    #[cfg(not(windows))]
    let _ = path;
}

struct FullPackage {
    root: PathBuf,
    manifest_path: PathBuf,
    components: BTreeMap<&'static str, PathBuf>,
}

impl FullPackage {
    fn create(label: &str) -> Self {
        let root = unique_root(label);
        let source = std::env::current_exe().unwrap().canonicalize().unwrap();
        let names = BTreeMap::from([
            ("desktop", executable_name("desktop")),
            ("broker", executable_name("aiguard-native-broker")),
            ("adapter", executable_name("aiguard-chrome-native-host")),
            ("manager", executable_name("aiguard-native-host-manager")),
            ("backend", executable_name("aiguard")),
        ]);
        let mut components = BTreeMap::new();
        for (key, name) in &names {
            let destination = root.join(name);
            std::fs::copy(&source, &destination).unwrap();
            set_fixture_owner(&destination);
            make_executable(&destination);
            components.insert(*key, destination);
        }
        let manifest = serde_json::json!({
            "schema_version": 1,
            "product_version": PRODUCT_VERSION,
            "broker": {
                "component_id": "native-broker",
                "path": names["broker"],
                "sha256": digest(&components["broker"]),
                "build_id": PRODUCT_VERSION
            },
            "clients": [
                {
                    "component_id": "desktop",
                    "role": "desktop",
                    "path": names["desktop"],
                    "sha256": digest(&components["desktop"]),
                    "build_id": PRODUCT_VERSION
                },
                {
                    "component_id": "chrome-native-host",
                    "role": "extension",
                    "path": names["adapter"],
                    "sha256": digest(&components["adapter"]),
                    "build_id": PRODUCT_VERSION
                },
                {
                    "component_id": "native-host-manager",
                    "role": "maintenance",
                    "path": names["manager"],
                    "sha256": digest(&components["manager"]),
                    "build_id": PRODUCT_VERSION
                }
            ],
            "backend": {
                "component_id": "python-backend",
                "path": names["backend"],
                "sha256": digest(&components["backend"]),
                "build_id": PRODUCT_VERSION,
                "arguments": ["--native-broker-backend"]
            },
            "native_host": {
                "name": "th.ac.psu.aiguard.native_host",
                "allowed_origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/",
                "identity_classification": "synthetic_test_only"
            }
        });
        let manifest_path = root.join("native-components-v1.json");
        std::fs::write(
            &manifest_path,
            serde_json::to_vec_pretty(&manifest).unwrap(),
        )
        .unwrap();
        set_fixture_owner(&manifest_path);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&manifest_path, std::fs::Permissions::from_mode(0o644))
                .unwrap();
        }
        Self {
            root,
            manifest_path,
            components,
        }
    }

    fn manifest_value(&self) -> serde_json::Value {
        serde_json::from_slice(&std::fs::read(&self.manifest_path).unwrap()).unwrap()
    }

    fn write_manifest(&self, value: &serde_json::Value) {
        std::fs::write(
            &self.manifest_path,
            serde_json::to_vec_pretty(value).unwrap(),
        )
        .unwrap();
        set_fixture_owner(&self.manifest_path);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&self.manifest_path, std::fs::Permissions::from_mode(0o644))
                .unwrap();
        }
    }
}

impl Drop for FullPackage {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
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
        PRODUCT_VERSION,
        BackendTimeouts {
            startup: Duration::from_secs(30),
            request: Duration::from_secs(10),
            shutdown: Duration::from_secs(8),
        },
    )
    .unwrap()
}

fn runtime_config() -> BrokerRuntimeConfig {
    BrokerRuntimeConfig {
        accept_poll: Duration::from_millis(20),
        hello_timeout: Duration::from_secs(5),
        request_timeout: Duration::from_secs(10),
        idle_timeout: Duration::from_secs(30),
        drain_timeout: Duration::from_secs(20),
    }
}

fn spawn_runtime_fixture(
    package: &FullPackage,
    endpoint_root: &Path,
    state_root: &Path,
    generation: &str,
) -> Child {
    Command::new(&package.components["broker"])
        .args(fixture_arguments(BROKER_RUNTIME_FIXTURE))
        .env("AIGUARD_SLICE6_MANIFEST", &package.manifest_path)
        .env("AIGUARD_SLICE6_ENDPOINT", endpoint_root)
        .env("AIGUARD_SLICE6_STATE", state_root)
        .env("AIGUARD_SLICE6_BROKER_GENERATION", generation)
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .unwrap()
}

fn fixture_arguments(name: &str) -> [&str; 4] {
    ["--ignored", "--exact", name, "--nocapture"]
}

fn spawn_client_fixture(
    executable: &Path,
    fixture: &str,
    package: &FullPackage,
    endpoint_root: &Path,
    state_root: &Path,
) -> Child {
    Command::new(executable)
        .args(fixture_arguments(fixture))
        .env("AIGUARD_SLICE6_MANIFEST", &package.manifest_path)
        .env("AIGUARD_SLICE6_ENDPOINT", endpoint_root)
        .env("AIGUARD_SLICE6_STATE", state_root)
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .unwrap()
}

fn wait_for_file(path: &Path, timeout: Duration) {
    let deadline = Instant::now() + timeout;
    while !path.is_file() {
        assert!(
            Instant::now() < deadline,
            "fixture signal was not published"
        );
        thread::sleep(Duration::from_millis(20));
    }
}

fn wait_for_child(child: &mut Child, timeout: Duration) -> std::process::ExitStatus {
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            return status;
        }
        if Instant::now() >= deadline {
            child.kill().unwrap();
            let _ = child.wait();
            panic!("Slice 6 fixture did not exit within its bounded deadline");
        }
        thread::sleep(Duration::from_millis(20));
    }
}

fn state_path(name: &str) -> PathBuf {
    PathBuf::from(std::env::var_os("AIGUARD_SLICE6_STATE").unwrap()).join(name)
}

fn fixture_configuration() -> (PathBuf, PathBuf) {
    (
        PathBuf::from(std::env::var_os("AIGUARD_SLICE6_MANIFEST").unwrap()),
        PathBuf::from(std::env::var_os("AIGUARD_SLICE6_ENDPOINT").unwrap()),
    )
}

fn wait_for_fixture_signal(name: &str) {
    wait_for_file(&state_path(name), LIVE_FIXTURE_SIGNAL_TIMEOUT);
}

#[test]
fn installed_native_manifest_requires_one_complete_exact_component_set() {
    let package = FullPackage::create("complete-set");
    let manifest = ComponentManifest::load(&package.manifest_path, PRODUCT_VERSION).unwrap();
    assert!(manifest.verified_broker_executable().is_ok());
    assert!(manifest.verify_backend().is_ok());
    for role in ["desktop", "extension", "maintenance"] {
        assert!(manifest.verified_client_executable_for_role(role).is_ok());
    }

    let mut unexpected = package.manifest_value();
    unexpected["clients"][2]["component_id"] = "unexpected-maintenance".into();
    package.write_manifest(&unexpected);
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));
}

#[test]
fn installed_native_manifest_rejects_a_mixed_or_modified_set_at_load() {
    let package = FullPackage::create("mixed-set");
    std::fs::write(&package.components["adapter"], b"modified adapter fixture").unwrap();
    make_executable(&package.components["adapter"]);
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("stale-manifest");
    std::fs::write(
        &package.components["manager"],
        b"replacement manager fixture",
    )
    .unwrap();
    make_executable(&package.components["manager"]);
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("missing-component");
    std::fs::remove_file(&package.components["backend"]).unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("substituted-path");
    let mut substituted = package.manifest_value();
    substituted["clients"][0]["path"] = executable_name("relocated-desktop").into();
    package.write_manifest(&substituted);
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));
}

#[test]
fn installed_native_manifest_rejects_hard_link_substitution() {
    let package = FullPackage::create("hard-link");
    std::fs::remove_file(&package.components["adapter"]).unwrap();
    std::fs::hard_link(
        &package.components["desktop"],
        &package.components["adapter"],
    )
    .unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));
}

#[cfg(unix)]
#[test]
fn installed_native_manifest_rejects_wrong_component_or_manifest_modes() {
    use std::os::unix::fs::PermissionsExt;

    let package = FullPackage::create("wrong-mode");
    std::fs::set_permissions(
        &package.components["adapter"],
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("writable-mode");
    std::fs::set_permissions(
        &package.components["manager"],
        std::fs::Permissions::from_mode(0o777),
    )
    .unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("private-executable-mode");
    std::fs::set_permissions(
        &package.components["broker"],
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("setuid-executable-mode");
    std::fs::set_permissions(
        &package.components["desktop"],
        std::fs::Permissions::from_mode(0o4755),
    )
    .unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));

    let package = FullPackage::create("private-manifest-mode");
    std::fs::set_permissions(
        &package.manifest_path,
        std::fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    assert_fixed(ComponentManifest::load(
        &package.manifest_path,
        PRODUCT_VERSION,
    ));
}

fn assert_fixed<T>(result: Result<T, ProtocolError>) {
    let error = result.err().expect("fixture must fail closed");
    assert_eq!(error.code(), "broker_unavailable");
    assert_eq!(
        format!("{error:?}"),
        "ProtocolError { code: \"broker_unavailable\", .. }"
    );
}

fn hello(product_version: &str, versions: serde_json::Value) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "claimed_role": "desktop",
        "client_product_version": product_version,
        "request_id": "slice6-hello",
        "supported_protocol_versions": versions
    }))
    .unwrap()
}

#[test]
fn compatibility_uses_only_explicit_protocol_intersection() {
    for client_version in ["2.4.9-fixture", PRODUCT_VERSION, "9.0.0-fixture"] {
        let negotiated = negotiate_hello(
            &hello(client_version, serde_json::json!([1])),
            "desktop",
            PRODUCT_VERSION,
        )
        .unwrap();
        assert_eq!(negotiated.state.protocol_version(), 1);
        assert_eq!(
            negotiated.response["broker_product_version"],
            PRODUCT_VERSION
        );
    }

    let incompatible = negotiate_hello(
        &hello("9.0.0-fixture", serde_json::json!([2, 3])),
        "desktop",
        PRODUCT_VERSION,
    )
    .unwrap_err();
    assert_eq!(incompatible.code(), "broker_incompatible");
    assert_eq!(incompatible.request_id(), Some("slice6-hello"));

    for malformed in [
        serde_json::json!([]),
        serde_json::json!([1, 1]),
        serde_json::json!(["1"]),
    ] {
        let error = negotiate_hello(
            &hello(PRODUCT_VERSION, malformed),
            "desktop",
            PRODUCT_VERSION,
        )
        .unwrap_err();
        assert_eq!(error.code(), "request_invalid");
    }
}

fn admitted(role: &str) -> aiguard_native_broker_protocol::admission::AdmissionDecision {
    decide_admission(
        &BrokerOsContext {
            user_boundary: "synthetic-user".to_owned(),
            logon_session: "synthetic-logon".to_owned(),
        },
        &OsPeerContext {
            user_boundary: "synthetic-user".to_owned(),
            logon_session: "synthetic-logon".to_owned(),
            process_id: 7,
            credential_verified: true,
            stable_process_reference: true,
        },
        &PackageConsistencyEvidence {
            component_id: format!("{role}-component"),
            allowed_role: role.to_owned(),
            canonical_path_matches: true,
            build_id_matches: true,
            digest_matches: true,
        },
        role,
    )
    .unwrap()
}

struct DrainCancellationBackend {
    blocked_operation: &'static str,
    entered: AtomicBool,
    calls: Mutex<Vec<String>>,
    teardowns: AtomicUsize,
}

impl DrainCancellationBackend {
    fn new(blocked_operation: &'static str) -> Arc<Self> {
        Arc::new(Self {
            blocked_operation,
            entered: AtomicBool::new(false),
            calls: Mutex::new(Vec::new()),
            teardowns: AtomicUsize::new(0),
        })
    }
}

impl BackendExecutor for DrainCancellationBackend {
    fn generation(&self) -> BackendGeneration {
        BackendGeneration::for_test(86)
    }

    fn execute(
        &self,
        call: &BackendCall,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        self.calls.lock().unwrap().push(call.operation().to_owned());
        if call.operation() == self.blocked_operation {
            self.entered.store(true, Ordering::Release);
            while !cancelled() && Instant::now() < deadline {
                thread::yield_now();
            }
            return BackendCompletion::Unknown(BackendFailure::Cancelled);
        }
        if cancelled() {
            return BackendCompletion::NotSubmitted(BackendFailure::Cancelled);
        }
        match call.operation() {
            "sanitize" => BackendCompletion::Confirmed(BackendReply::for_test(
                200,
                Some("2"),
                Some("application/json"),
                json!({
                    "detected_entity_count": 0,
                    "entity_type_counts": {},
                    "guard_findings": [],
                    "highlights": [],
                    "replacement_count": 0,
                    "safety": {"residual_count": 0, "status": "pass"},
                    "sanitized_text": "synthetic-safe-output",
                    "section26_categories": [],
                    "session_id": "00000000-0000-4000-8000-000000000086",
                    "warnings": []
                }),
            )),
            "session_dispose" => BackendCompletion::Confirmed(BackendReply::for_test(
                200,
                Some("2"),
                Some("application/json"),
                json!({"deleted": true}),
            )),
            operation => panic!("unexpected Slice 6 backend operation: {operation}"),
        }
    }

    fn teardown(&self) {
        self.teardowns.fetch_add(1, Ordering::AcqRel);
    }
}

fn data_request(
    operation: &str,
    scope_id: Option<&str>,
    payload: serde_json::Value,
) -> BrokerRequest {
    let uncertainty = match operation {
        "scope_open" => "connection_state",
        "detect" => "external_tner_possible",
        "sanitize" => "possible_session_publication_or_known_session_mutation",
        "reidentify" => "known_session_mutation",
        _ => "none",
    };
    BrokerRequest {
        protocol_version: 1,
        request_id: format!("slice6-{operation}"),
        operation: operation.to_owned(),
        scope_id: scope_id.map(str::to_owned),
        payload,
        deadline_ms: Some(30_000),
        local_detection_phases: Some(match operation {
            "scope_open" => 0,
            "sanitize" => 2,
            _ => 1,
        }),
        local_intermediate_text_chars: (operation != "scope_open").then_some(200_000),
        remote_tner_max_calls: 0,
        remote_tner_text_chars: None,
        replay: "never".to_owned(),
        uncertain_completion: uncertainty.to_owned(),
    }
}

#[test]
fn maintenance_is_least_authority_and_storefronts_cannot_drain() {
    let plane = Slice2ControlPlane::new();
    let maintenance = admitted("maintenance");
    assert_eq!(
        plane.authorize(&maintenance, "broker_health").unwrap(),
        ControlAction::Health
    );
    assert_eq!(
        plane
            .authorize(&maintenance, "maintenance_drain_stop")
            .unwrap(),
        ControlAction::DrainStop
    );
    for operation in [
        "scope_open",
        "sanitize",
        "reidentify",
        "session_dispose",
        "roundtrip",
        "detect",
        "redact_pdf",
    ] {
        assert_eq!(
            plane.authorize(&maintenance, operation).unwrap_err().code(),
            "broker_unauthorized"
        );
    }
    for role in ["desktop", "extension"] {
        assert_eq!(
            plane
                .authorize(&admitted(role), "maintenance_drain_stop")
                .unwrap_err()
                .code(),
            "broker_unauthorized"
        );
    }
}

#[test]
fn maintenance_drain_cancels_detect_sanitize_and_restore_without_replay() {
    for blocked_operation in ["detect", "sanitize", "reidentify"] {
        let backend = DrainCancellationBackend::new(blocked_operation);
        let plane = DataPlane::new(backend.clone()).unwrap();
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = connection
            .dispatch(
                &data_request("scope_open", None, json!({"scope_kind": "desktop_ui"})),
                &|| false,
            )
            .unwrap()["scope_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let old_session = if blocked_operation == "reidentify" {
            Some(
                connection
                    .dispatch(
                        &data_request(
                            "sanitize",
                            Some(&scope),
                            json!({"mode": "token", "text": "synthetic setup"}),
                        ),
                        &|| false,
                    )
                    .unwrap()["session_id"]
                    .as_str()
                    .unwrap()
                    .to_owned(),
            )
        } else {
            None
        };
        let payload = match blocked_operation {
            "detect" => json!({"text": "synthetic in-flight detect"}),
            "sanitize" => json!({"mode": "token", "text": "synthetic in-flight sanitize"}),
            "reidentify" => json!({
                "session_id": old_session.as_deref().unwrap(),
                "text": "synthetic-safe-output"
            }),
            _ => unreachable!(),
        };
        let cancelled = Arc::new(AtomicBool::new(false));
        let observed = Arc::clone(&cancelled);
        let request = data_request(blocked_operation, Some(&scope), payload);
        let worker = thread::spawn(move || {
            connection.dispatch(&request, &|| observed.load(Ordering::Acquire))
        });
        let deadline = Instant::now() + Duration::from_secs(5);
        while !backend.entered.load(Ordering::Acquire) {
            assert!(
                Instant::now() < deadline,
                "in-flight operation did not enter backend"
            );
            thread::yield_now();
        }

        // BrokerRuntime supplies this same cancellation signal as soon as the
        // authenticated maintenance drain is accepted.
        cancelled.store(true, Ordering::Release);
        let error = worker.join().unwrap().unwrap_err();
        assert!(matches!(
            error.code(),
            "operation_failed" | "operation_timeout"
        ));
        assert_eq!(
            backend
                .calls
                .lock()
                .unwrap()
                .iter()
                .filter(|operation| operation.as_str() == blocked_operation)
                .count(),
            1,
            "{blocked_operation} was replayed"
        );
        assert_eq!(backend.teardowns.load(Ordering::Acquire), 1);
        assert!(plane.stats().backend_invalidated);
        assert_eq!(plane.stats().in_flight, 0);
        assert_eq!(plane.stats().desktop_sessions, 0);
    }
}

#[test]
fn upgrade_drains_live_desktop_and_extension_scopes_without_reviving_sessions() {
    let _guard = slice6_guard();
    let package = FullPackage::create("live-upgrade");
    let endpoint_root = unique_root("live-upgrade-endpoint");
    let state_root = unique_root("live-upgrade-state");
    let mut old_runtime = spawn_runtime_fixture(&package, &endpoint_root, &state_root, "old");
    wait_for_file(
        &state_root.join("old-broker-ready"),
        Duration::from_secs(45),
    );

    let mut desktop = spawn_client_fixture(
        &package.components["desktop"],
        DESKTOP_LIVE_FIXTURE,
        &package,
        &endpoint_root,
        &state_root,
    );
    let mut extension = spawn_client_fixture(
        &package.components["adapter"],
        EXTENSION_LIVE_FIXTURE,
        &package,
        &endpoint_root,
        &state_root,
    );
    wait_for_file(&state_root.join("desktop-ready"), Duration::from_secs(60));
    wait_for_file(&state_root.join("extension-ready"), Duration::from_secs(60));

    let mut manager = spawn_client_fixture(
        &package.components["manager"],
        MANAGER_DRAIN_FIXTURE,
        &package,
        &endpoint_root,
        &state_root,
    );
    assert!(wait_for_child(&mut manager, MANAGER_EXIT_TIMEOUT).success());
    assert!(wait_for_child(&mut old_runtime, MANAGER_EXIT_TIMEOUT).success());
    assert!(state_root.join("old-broker-maintenance").is_file());
    assert!(component_replacement_active(&package.root).unwrap());

    std::fs::write(state_root.join("old-runtime-stopped"), b"continue").unwrap();
    wait_for_file(
        &state_root.join("desktop-old-invalidated"),
        Duration::from_secs(15),
    );
    wait_for_file(
        &state_root.join("extension-old-invalidated"),
        Duration::from_secs(15),
    );

    finish_component_replacement(&package.root).unwrap();
    let mut new_runtime = spawn_runtime_fixture(&package, &endpoint_root, &state_root, "new");
    wait_for_file(
        &state_root.join("new-broker-ready"),
        Duration::from_secs(45),
    );
    std::fs::write(state_root.join("replacement-ready"), b"continue").unwrap();
    assert!(wait_for_child(&mut desktop, Duration::from_secs(60)).success());
    assert!(wait_for_child(&mut extension, Duration::from_secs(60)).success());
    assert!(state_root.join("desktop-passed").is_file());
    assert!(state_root.join("extension-passed").is_file());
    std::fs::write(state_root.join("new-broker-stop"), b"stop").unwrap();
    assert!(wait_for_child(&mut new_runtime, Duration::from_secs(40)).success());
    assert!(state_root.join("new-broker-idle").is_file());

    #[cfg(unix)]
    PlatformEndpoint::cleanup_runtime_root_for_test(&endpoint_root).unwrap();
    #[cfg(windows)]
    std::fs::remove_dir(endpoint_root).unwrap();
    std::fs::remove_dir_all(state_root).unwrap();
}

#[test]
#[ignore]
fn slice6_broker_runtime_fixture() {
    let Some(_) = std::env::var_os("AIGUARD_SLICE6_MANIFEST") else {
        return;
    };
    let (manifest_path, endpoint_root) = fixture_configuration();
    let generation = std::env::var("AIGUARD_SLICE6_BROKER_GENERATION").unwrap();
    assert!(matches!(generation.as_str(), "old" | "new"));
    let manifest = ComponentManifest::load(&manifest_path, PRODUCT_VERSION).unwrap();
    manifest
        .verify_broker_executable(&std::env::current_exe().unwrap())
        .unwrap();
    let reservation = PlatformEndpoint::reserve_for_test(&endpoint_root).unwrap();
    let endpoint = reservation.publish().unwrap();
    let runtime = BrokerRuntime::from_parts_for_test(
        endpoint,
        manifest,
        launch_backend(),
        PRODUCT_VERSION,
        runtime_config(),
    )
    .unwrap();
    let stop = runtime.stop_signal_for_test();
    if generation == "new" {
        let stop = Arc::clone(&stop);
        thread::spawn(move || {
            wait_for_fixture_signal("new-broker-stop");
            stop.store(true, Ordering::Release);
        });
    }
    std::fs::write(state_path(&format!("{generation}-broker-ready")), b"ready").unwrap();
    let exit = runtime.run().unwrap();
    let expected = if generation == "old" {
        BrokerExit::Maintenance
    } else {
        BrokerExit::Idle
    };
    assert_eq!(exit, expected);
    let exit_name = match exit {
        BrokerExit::Maintenance => "maintenance",
        BrokerExit::Idle => "idle",
        BrokerExit::BackendFailed => "backend-failed",
        BrokerExit::ForcedShutdown => "forced-shutdown",
    };
    std::fs::write(
        state_path(&format!("{generation}-broker-{exit_name}")),
        b"stopped",
    )
    .unwrap();
}

#[test]
#[ignore]
fn slice6_manager_drain_fixture() {
    let Some(_) = std::env::var_os("AIGUARD_SLICE6_MANIFEST") else {
        return;
    };
    let (manifest_path, endpoint_root) = fixture_configuration();
    let install_root = manifest_path.parent().unwrap();
    begin_component_replacement(install_root).unwrap();
    assert!(matches!(
        drain_existing_broker_for_test(
            &endpoint_root,
            &manifest_path,
            PRODUCT_VERSION,
            MANAGER_DRAIN_TIMEOUT,
        )
        .unwrap(),
        DrainOutcome::Stopped | DrainOutcome::AlreadyStopped
    ));
}

#[test]
#[ignore]
fn slice6_desktop_live_scope_fixture() {
    let Some(_) = std::env::var_os("AIGUARD_SLICE6_MANIFEST") else {
        return;
    };
    let (manifest_path, endpoint_root) = fixture_configuration();
    let mut client = DesktopBrokerClient::connect_or_start_for_test(
        &endpoint_root,
        &manifest_path,
        PRODUCT_VERSION,
        Duration::from_secs(15),
    )
    .unwrap();
    let ui_a = client.open_scope(DesktopScopeKind::Ui).unwrap();
    let ui_b = client.open_scope(DesktopScopeKind::Ui).unwrap();
    let hotkey = client.open_scope(DesktopScopeKind::Hotkey).unwrap();
    let first = client
        .sanitize(&ui_a, "ผู้ใช้ทดสอบ โทร 000-000-0000", "token", None)
        .unwrap();
    let old_session = first["session_id"].as_str().unwrap().to_owned();
    let old_masked = first["sanitized_text"].as_str().unwrap().to_owned();
    client
        .sanitize(&ui_b, "บัญชีทดสอบ B โทร 000-000-0001", "surrogate", None)
        .unwrap();
    client
        .sanitize(&hotkey, "บัญชีทดสอบ C โทร 000-000-0002", "token", None)
        .unwrap();
    std::fs::write(state_path("desktop-ready"), b"ready").unwrap();

    wait_for_fixture_signal("old-runtime-stopped");
    let error = client
        .reidentify(&ui_a, &old_session, &old_masked)
        .unwrap_err();
    assert!(error.connection_invalidated());
    assert!(error.session_invalidated());
    assert!(matches!(
        error.code(),
        "broker_unavailable" | "operation_failed" | "session_unavailable"
    ));
    std::fs::write(state_path("desktop-old-invalidated"), b"invalidated").unwrap();

    wait_for_fixture_signal("replacement-ready");
    let mut replacement = DesktopBrokerClient::connect_or_start_for_test(
        &endpoint_root,
        &manifest_path,
        PRODUCT_VERSION,
        Duration::from_secs(15),
    )
    .unwrap();
    let fresh_scope = replacement.open_scope(DesktopScopeKind::Ui).unwrap();
    let stale = replacement
        .reidentify(&fresh_scope, &old_session, &old_masked)
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
    replacement.close_scope(&fresh_scope).unwrap();
    std::fs::write(state_path("desktop-passed"), b"passed").unwrap();
}

#[test]
#[ignore]
fn slice6_extension_live_scope_fixture() {
    let Some(_) = std::env::var_os("AIGUARD_SLICE6_MANIFEST") else {
        return;
    };
    let (manifest_path, endpoint_root) = fixture_configuration();
    let mut client = ExtensionBrokerClient::connect_or_start_for_test(
        &endpoint_root,
        &manifest_path,
        PRODUCT_VERSION,
        Duration::from_secs(15),
    )
    .unwrap();
    let tab_a = client.open_scope(ExtensionScopeKind::Tab).unwrap();
    let tab_b = client.open_scope(ExtensionScopeKind::Tab).unwrap();
    let panel = client.open_scope(ExtensionScopeKind::Panel).unwrap();
    let first = client
        .sanitize(&tab_a, "แท็บทดสอบ โทร 000-000-0010", "token", None)
        .unwrap();
    let old_session = first["session_id"].as_str().unwrap().to_owned();
    let old_masked = first["sanitized_text"].as_str().unwrap().to_owned();
    client
        .sanitize(&tab_b, "แท็บทดสอบ B โทร 000-000-0011", "surrogate", None)
        .unwrap();
    client
        .sanitize(&panel, "แผงทดสอบ โทร 000-000-0012", "token", None)
        .unwrap();
    std::fs::write(state_path("extension-ready"), b"ready").unwrap();

    wait_for_fixture_signal("old-runtime-stopped");
    let error = client
        .reidentify(&tab_a, &old_session, &old_masked)
        .unwrap_err();
    assert!(error.connection_invalidated());
    assert!(error.session_invalidated());
    assert!(matches!(
        error.code(),
        "broker_unavailable" | "operation_failed" | "session_unavailable"
    ));
    std::fs::write(state_path("extension-old-invalidated"), b"invalidated").unwrap();

    wait_for_fixture_signal("replacement-ready");
    let mut replacement = ExtensionBrokerClient::connect_or_start_for_test(
        &endpoint_root,
        &manifest_path,
        PRODUCT_VERSION,
        Duration::from_secs(15),
    )
    .unwrap();
    let fresh_scope = replacement.open_scope(ExtensionScopeKind::Panel).unwrap();
    let stale = replacement
        .reidentify(&fresh_scope, &old_session, &old_masked)
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
    replacement.close_scope(&fresh_scope).unwrap();
    std::fs::write(state_path("extension-passed"), b"passed").unwrap();
}

#[test]
fn replacement_barrier_is_fixed_idempotent_and_corruption_fails_closed() {
    let root = unique_root("replacement-barrier");
    assert!(!component_replacement_active(&root).unwrap());
    begin_component_replacement(&root).unwrap();
    begin_component_replacement(&root).unwrap();
    assert!(component_replacement_active(&root).unwrap());
    finish_component_replacement(&root).unwrap();
    assert!(!component_replacement_active(&root).unwrap());

    let marker = root.join(".aiguard-component-maintenance-v1");
    std::fs::write(&marker, b"unexpected state").unwrap();
    assert!(component_replacement_active(&root).is_err());
    assert!(finish_component_replacement(&root).is_err());
    assert_eq!(std::fs::read(&marker).unwrap(), b"unexpected state");
    std::fs::remove_file(marker).unwrap();
    std::fs::remove_dir(root).unwrap();
}

#[cfg(unix)]
#[test]
fn uninstall_cleanup_removes_only_an_owned_inactive_runtime_root() {
    let root = unique_root("runtime-cleanup");
    let endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    drop(endpoint);
    assert!(root.join("broker.lock").is_file());
    PlatformEndpoint::cleanup_runtime_root_for_test(&root).unwrap();
    assert!(!root.exists());

    let root = unique_root("runtime-preserve-unrelated");
    let endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    drop(endpoint);
    std::fs::write(root.join("unrelated"), b"preserve").unwrap();
    assert!(PlatformEndpoint::cleanup_runtime_root_for_test(&root).is_err());
    assert_eq!(std::fs::read(root.join("unrelated")).unwrap(), b"preserve");
    std::fs::remove_file(root.join("unrelated")).unwrap();
    PlatformEndpoint::cleanup_runtime_root_for_test(&root).unwrap();
}
