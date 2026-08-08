use std::path::{Path, PathBuf};
use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Duration;

use aiguard_native_broker_protocol::admission::{
    decide_admission, BrokerOsContext, OsPeerContext, PackageConsistencyEvidence,
};
use aiguard_native_broker_protocol::bootstrap::BootstrapSecrets;
use aiguard_native_broker_protocol::control::{ControlAction, Slice2ControlPlane};
use aiguard_native_broker_protocol::manifest::ComponentManifest;
use aiguard_native_broker_protocol::transport::{
    ConnectionLimiter, PlatformEndpoint, MAX_ACTIVE_CONNECTIONS,
};
use sha2::{Digest, Sha256};

fn unique_test_root(label: &str) -> PathBuf {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    #[cfg(unix)]
    let base = Path::new("/tmp").to_path_buf();
    #[cfg(windows)]
    let base = std::env::temp_dir();
    base.join(format!(
        "aiguard-slice2-{label}-{}-{nonce}",
        std::process::id()
    ))
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn broker_context() -> BrokerOsContext {
    BrokerOsContext {
        user_boundary: "synthetic-user-a".to_owned(),
        logon_session: "synthetic-session-a".to_owned(),
    }
}

fn peer_context() -> OsPeerContext {
    OsPeerContext {
        user_boundary: "synthetic-user-a".to_owned(),
        logon_session: "synthetic-session-a".to_owned(),
        process_id: 4242,
        credential_verified: true,
        stable_process_reference: true,
    }
}

fn package(role: &str) -> PackageConsistencyEvidence {
    PackageConsistencyEvidence {
        component_id: format!("synthetic-{role}-component"),
        allowed_role: role.to_owned(),
        canonical_path_matches: true,
        build_id_matches: true,
        digest_matches: true,
    }
}

#[test]
fn valid_desktop_extension_and_maintenance_admission_remain_distinct() {
    for role in ["desktop", "extension", "maintenance"] {
        let decision =
            decide_admission(&broker_context(), &peer_context(), &package(role), role).unwrap();
        assert_eq!(decision.claimed_role(), role);
        assert_eq!(decision.admitted_role(), role);
        assert_eq!(
            decision.component_id(),
            format!("synthetic-{role}-component")
        );
        let rendered = format!("{decision:?}");
        assert!(!rendered.contains("synthetic-user-a"));
        assert!(!rendered.contains("synthetic-session-a"));
    }
}

#[test]
fn claimed_role_never_grants_authority_or_changes_the_package_role() {
    let error = decide_admission(
        &broker_context(),
        &peer_context(),
        &package("desktop"),
        "maintenance",
    )
    .unwrap_err();
    assert_eq!(error.code(), "broker_unauthorized");

    let error = decide_admission(
        &broker_context(),
        &peer_context(),
        &package("desktop"),
        "invented-role",
    )
    .unwrap_err();
    assert_eq!(error.code(), "broker_unauthorized");
}

#[test]
fn other_user_unverified_peer_unstable_pid_and_package_mismatch_fail_closed() {
    let mut other_user = peer_context();
    other_user.user_boundary = "synthetic-user-b".to_owned();
    let mut other_session = peer_context();
    other_session.logon_session = "synthetic-session-b".to_owned();
    let mut unverified = peer_context();
    unverified.credential_verified = false;
    let mut unstable = peer_context();
    unstable.stable_process_reference = false;

    for peer in [other_user, other_session, unverified, unstable] {
        assert_eq!(
            decide_admission(&broker_context(), &peer, &package("desktop"), "desktop")
                .unwrap_err()
                .code(),
            "broker_unauthorized"
        );
    }

    for package in [
        PackageConsistencyEvidence {
            canonical_path_matches: false,
            ..package("desktop")
        },
        PackageConsistencyEvidence {
            build_id_matches: false,
            ..package("desktop")
        },
        PackageConsistencyEvidence {
            digest_matches: false,
            ..package("desktop")
        },
    ] {
        assert_eq!(
            decide_admission(&broker_context(), &peer_context(), &package, "desktop")
                .unwrap_err()
                .code(),
            "broker_unauthorized"
        );
    }
}

#[test]
fn bootstrap_secrets_are_distinct_bounded_and_redacted() {
    let secrets = BootstrapSecrets::generate().unwrap();
    let replacement = BootstrapSecrets::generate().unwrap();
    assert_ne!(secrets.api_key(), secrets.control_token());
    assert_ne!(secrets.api_key(), replacement.api_key());
    assert_ne!(secrets.api_key(), replacement.control_token());
    assert_ne!(secrets.control_token(), replacement.api_key());
    assert_ne!(secrets.control_token(), replacement.control_token());
    assert_eq!(secrets.api_key().len(), 64);
    assert_eq!(secrets.control_token().len(), 64);
    assert!(secrets
        .api_key()
        .bytes()
        .all(|byte| byte.is_ascii_hexdigit()));
    assert!(secrets
        .control_token()
        .bytes()
        .all(|byte| byte.is_ascii_hexdigit()));
    let rendered = format!("{secrets:?}");
    assert!(!rendered.contains(secrets.api_key()));
    assert!(!rendered.contains(secrets.control_token()));
}

#[test]
fn health_only_control_plane_rejects_data_and_role_escalation() {
    let desktop = decide_admission(
        &broker_context(),
        &peer_context(),
        &package("desktop"),
        "desktop",
    )
    .unwrap();
    let maintenance = decide_admission(
        &broker_context(),
        &peer_context(),
        &package("maintenance"),
        "maintenance",
    )
    .unwrap();
    let plane = Slice2ControlPlane::new();

    assert_eq!(
        plane.authorize(&desktop, "broker_health").unwrap(),
        ControlAction::Health
    );
    assert_eq!(
        plane
            .authorize(&maintenance, "maintenance_drain_stop")
            .unwrap(),
        ControlAction::DrainStop
    );
    assert_eq!(
        plane
            .authorize(&desktop, "maintenance_drain_stop")
            .unwrap_err()
            .code(),
        "broker_unauthorized"
    );
    assert_eq!(
        plane
            .authorize(&maintenance, "sanitize")
            .unwrap_err()
            .code(),
        "broker_unauthorized"
    );
    for operation in [
        "sanitize",
        "detect",
        "analyze",
        "guard",
        "roundtrip",
        "reidentify",
        "redact_pdf",
        "scope_open",
        "session_dispose",
    ] {
        assert_eq!(
            plane.authorize(&desktop, operation).unwrap_err().code(),
            "operation_failed"
        );
    }
}

#[test]
fn operating_system_endpoint_race_has_one_owner_and_restart_is_clean() {
    let root = unique_test_root("os-owner-race");
    let barrier = Arc::new(Barrier::new(9));
    let mut workers = Vec::new();
    for _ in 0..8 {
        let barrier = Arc::clone(&barrier);
        let root = root.clone();
        workers.push(thread::spawn(move || {
            barrier.wait();
            PlatformEndpoint::create_for_test(&root)
        }));
    }
    barrier.wait();
    let mut owners = Vec::new();
    for worker in workers {
        if let Ok(endpoint) = worker.join().unwrap() {
            owners.push(endpoint);
        }
    }
    assert_eq!(owners.len(), 1);
    let second = PlatformEndpoint::create_for_test(&root);
    assert_eq!(second.err().unwrap().code(), "broker_unavailable");
    drop(owners);
    let restarted = PlatformEndpoint::create_for_test(&root).unwrap();
    drop(restarted);
    #[cfg(unix)]
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn ownership_is_reserved_before_the_native_endpoint_is_published() {
    let root = unique_test_root("reserved-before-publish");
    let reservation = PlatformEndpoint::reserve_for_test(&root).unwrap();
    let publication = PlatformEndpoint::publication_for_test(&root).unwrap();
    assert!(
        aiguard_native_broker_protocol::transport::NativeStream::connect(
            &publication,
            Duration::from_millis(50),
        )
        .is_err()
    );
    assert_eq!(
        PlatformEndpoint::reserve_for_test(&root)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );

    let mut endpoint = reservation.publish().unwrap();
    let client = thread::spawn(move || {
        let mut stream = aiguard_native_broker_protocol::transport::NativeStream::connect(
            &publication,
            Duration::from_secs(2),
        )
        .unwrap();
        stream
            .write_value(
                &serde_json::json!({"synthetic":"published"}),
                4096,
                Duration::from_secs(2),
            )
            .unwrap();
        stream
            .read_frame(4096, Duration::from_secs(2))
            .unwrap()
            .unwrap()
    });
    let mut accepted = endpoint.accept(Duration::from_secs(2)).unwrap().unwrap();
    assert_eq!(
        accepted
            .stream_mut()
            .read_frame(4096, Duration::from_secs(2))
            .unwrap()
            .unwrap(),
        br#"{"synthetic":"published"}"#
    );
    accepted
        .stream_mut()
        .write_value(
            &serde_json::json!({"synthetic":"ack"}),
            4096,
            Duration::from_secs(2),
        )
        .unwrap();
    assert_eq!(client.join().unwrap(), br#"{"synthetic":"ack"}"#);
    drop(accepted);
    drop(endpoint);
    #[cfg(unix)]
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn connection_limit_is_bounded_and_releases_capacity() {
    let limiter = ConnectionLimiter::new(MAX_ACTIVE_CONNECTIONS);
    let mut permits = Vec::new();
    for _ in 0..MAX_ACTIVE_CONNECTIONS {
        permits.push(limiter.try_acquire().unwrap());
    }
    assert_eq!(limiter.try_acquire().unwrap_err().code(), "broker_busy");
    permits.pop();
    assert!(limiter.try_acquire().is_ok());
}

#[test]
fn platform_endpoint_uses_explicit_security_and_cleans_up() {
    let root = unique_test_root("endpoint-security");
    let endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    let security = endpoint.security_report().unwrap();
    assert!(security.os_user_isolated);
    assert!(security.peer_credentials_required);
    assert!(security.single_instance_held);
    assert!(security.remote_clients_rejected);
    #[cfg(unix)]
    {
        assert_eq!(security.runtime_directory_mode, Some(0o700));
        assert_eq!(security.endpoint_mode, Some(0o600));
        assert!(!security.uses_abstract_socket);
    }
    #[cfg(windows)]
    {
        assert!(security.explicit_dacl);
        assert!(security.current_logon_sid_only);
        assert!(security.client_pid_inspection);
    }
    let published = endpoint.publication();
    assert!(!published.contains("127.0.0.1"));
    assert!(!published.contains("api_key"));
    assert!(!published.contains("control"));
    let cleanup_path: Option<PathBuf> = endpoint.filesystem_path().map(PathBuf::from);
    drop(endpoint);
    if let Some(path) = cleanup_path {
        assert!(!path.exists());
    }
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn production_endpoint_constructor_requires_the_canonical_user_namespace() {
    let executable = std::env::current_exe().unwrap().canonicalize().unwrap();
    let install_root = executable.parent().unwrap();
    let canonical = PlatformEndpoint::default_runtime_root(install_root).unwrap();
    let endpoint = PlatformEndpoint::create(&canonical).unwrap();
    assert_eq!(
        endpoint.publication(),
        PlatformEndpoint::publication_for(&canonical).unwrap()
    );
    drop(endpoint);
    let arbitrary = unique_test_root("non-production-root");
    assert_eq!(
        PlatformEndpoint::create(&arbitrary).err().unwrap().code(),
        "broker_unavailable"
    );
    #[cfg(unix)]
    let _ = std::fs::remove_dir_all(canonical);
}

#[cfg(windows)]
#[test]
fn windows_production_namespace_is_single_per_logon_across_install_roots() {
    let first =
        PlatformEndpoint::default_runtime_root(Path::new(r"C:\Synthetic\Install-A")).unwrap();
    let second =
        PlatformEndpoint::default_runtime_root(Path::new(r"D:\Synthetic\Install-B")).unwrap();
    assert_eq!(first, second);
    assert_eq!(
        PlatformEndpoint::publication_for(&first).unwrap(),
        PlatformEndpoint::publication_for(&second).unwrap()
    );
}

#[cfg(unix)]
#[test]
fn unix_production_namespace_is_single_per_user_across_install_roots() {
    let first = PlatformEndpoint::default_runtime_root(Path::new("/synthetic/install-a")).unwrap();
    let second = PlatformEndpoint::default_runtime_root(Path::new("/synthetic/install-b")).unwrap();
    assert_eq!(first, second);
    assert_eq!(
        PlatformEndpoint::publication_for(&first).unwrap(),
        PlatformEndpoint::publication_for(&second).unwrap()
    );
}

#[test]
fn platform_transport_authenticates_kernel_peer_and_roundtrips_strict_frames() {
    let root = unique_test_root("live-transport");
    let mut endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    let publication = endpoint.publication();
    let broker_context = endpoint.broker_context().unwrap();
    let client = thread::spawn(move || {
        let mut stream = aiguard_native_broker_protocol::transport::NativeStream::connect(
            &publication,
            Duration::from_secs(2),
        )
        .unwrap();
        let server = stream.inspect_server().unwrap();
        server.ensure_stable().unwrap();
        assert_eq!(
            server.executable().canonicalize().unwrap(),
            std::env::current_exe().unwrap().canonicalize().unwrap()
        );
        stream
            .write_value(
                &serde_json::json!({"synthetic":"hello"}),
                4096,
                Duration::from_secs(2),
            )
            .unwrap();
        stream
            .read_frame(4096, Duration::from_secs(2))
            .unwrap()
            .unwrap()
    });
    let mut accepted = endpoint.accept(Duration::from_secs(2)).unwrap().unwrap();
    assert_eq!(
        accepted.peer_context().user_boundary,
        broker_context.user_boundary
    );
    assert_eq!(
        accepted.peer_context().logon_session,
        broker_context.logon_session
    );
    accepted.ensure_peer_stable().unwrap();
    assert_eq!(
        accepted.peer_executable().canonicalize().unwrap(),
        std::env::current_exe().unwrap().canonicalize().unwrap()
    );
    let request = accepted
        .stream_mut()
        .read_frame(4096, Duration::from_secs(2))
        .unwrap()
        .unwrap();
    assert_eq!(request, br#"{"synthetic":"hello"}"#);
    accepted
        .stream_mut()
        .write_value(
            &serde_json::json!({"synthetic":"ok"}),
            4096,
            Duration::from_secs(2),
        )
        .unwrap();
    let response = client.join().unwrap();
    assert_eq!(response, br#"{"synthetic":"ok"}"#);
    drop(accepted);
    drop(endpoint);
    #[cfg(unix)]
    std::fs::remove_dir_all(root).unwrap();
}

#[cfg(windows)]
#[test]
fn windows_preaccept_disconnect_resets_the_named_pipe_instance() {
    let root = unique_test_root("preaccept-disconnect");
    let mut endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    let publication = endpoint.publication();
    drop(
        aiguard_native_broker_protocol::transport::NativeStream::connect(
            &publication,
            Duration::from_secs(2),
        )
        .unwrap(),
    );

    let second = thread::spawn(move || {
        let mut stream = aiguard_native_broker_protocol::transport::NativeStream::connect(
            &publication,
            Duration::from_secs(2),
        )
        .unwrap();
        stream
            .write_value(
                &serde_json::json!({"synthetic":"second-client"}),
                4096,
                Duration::from_secs(2),
            )
            .unwrap();
        stream
            .read_frame(4096, Duration::from_secs(2))
            .unwrap()
            .unwrap()
    });
    let mut accepted = endpoint.accept(Duration::from_secs(2)).unwrap().unwrap();
    assert_eq!(
        accepted
            .stream_mut()
            .read_frame(4096, Duration::from_secs(2))
            .unwrap()
            .unwrap(),
        br#"{"synthetic":"second-client"}"#
    );
    accepted
        .stream_mut()
        .write_value(
            &serde_json::json!({"synthetic":"ack"}),
            4096,
            Duration::from_secs(2),
        )
        .unwrap();
    assert_eq!(second.join().unwrap(), br#"{"synthetic":"ack"}"#);
}

#[test]
fn frame_header_and_body_share_one_absolute_read_deadline() {
    let root = unique_test_root("frame-deadline");
    let mut endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    let publication = endpoint.publication();
    let client = thread::spawn(move || {
        let mut stream = aiguard_native_broker_protocol::transport::NativeStream::connect(
            &publication,
            Duration::from_secs(2),
        )
        .unwrap();
        let body = br#"{"synthetic":"bounded"}"#;
        let length = (body.len() as u32).to_be_bytes();
        stream
            .write_raw_for_test(&length[..2], Duration::from_secs(1))
            .unwrap();
        thread::sleep(Duration::from_millis(150));
        stream
            .write_raw_for_test(&length[2..], Duration::from_secs(1))
            .unwrap();
        thread::sleep(Duration::from_millis(250));
        let _ = stream.write_raw_for_test(body, Duration::from_secs(1));
    });
    let mut accepted = endpoint.accept(Duration::from_secs(2)).unwrap().unwrap();
    let started = std::time::Instant::now();
    let error = accepted
        .stream_mut()
        .read_frame(4096, Duration::from_millis(300))
        .unwrap_err();
    assert_eq!(error.code(), "operation_timeout");
    assert!(started.elapsed() < Duration::from_secs(1));
    drop(accepted);
    client.join().unwrap();
    drop(endpoint);
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn partial_frame_disconnect_and_shutdown_timeout_are_bounded() {
    let endpoint = PlatformEndpoint::create_inert_for_test(Duration::from_millis(100)).unwrap();
    assert_eq!(
        endpoint.negotiate_bytes(b"\x00\x00").unwrap_err().code(),
        "request_invalid"
    );
    assert_eq!(
        endpoint
            .negotiate_bytes(b"\x00\x10\x00\x00")
            .unwrap_err()
            .code(),
        "payload_too_large"
    );
    assert_eq!(
        endpoint.disconnect_during_hello().unwrap_err().code(),
        "request_invalid"
    );
}

#[test]
fn component_manifest_binds_path_build_digest_and_role_without_authority_claims() {
    let root = unique_test_root("manifest-valid");
    std::fs::create_dir(&root).unwrap();
    let desktop_bytes = b"fixture\0AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0desktop";
    let broker_bytes = b"fixture\0AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0broker";
    let backend_bytes = b"fixture backend";
    std::fs::write(root.join("desktop-fixture"), desktop_bytes).unwrap();
    std::fs::write(root.join("broker-fixture"), broker_bytes).unwrap();
    std::fs::write(root.join("backend-fixture"), backend_bytes).unwrap();
    let manifest = serde_json::json!({
        "schema_version": 1,
        "product_version": "2.5.0",
        "broker": {
            "component_id": "native-broker",
            "path": "broker-fixture",
            "sha256": sha256_hex(broker_bytes),
            "build_id": "2.5.0"
        },
        "clients": [{
            "component_id": "desktop-shell",
            "role": "desktop",
            "path": "desktop-fixture",
            "sha256": sha256_hex(desktop_bytes),
            "build_id": "2.5.0"
        }],
        "backend": {
            "component_id": "python-backend",
            "path": "backend-fixture",
            "sha256": sha256_hex(backend_bytes),
            "build_id": "2.5.0",
            "arguments": ["--native-broker-backend"]
        }
    });
    let manifest_path = root.join("native-components-v1.json");
    std::fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();

    let loaded = ComponentManifest::load(&manifest_path, "2.5.0").unwrap();
    let evidence = loaded
        .verify_client_executable(&root.join("desktop-fixture"))
        .unwrap();
    assert_eq!(evidence.component_id, "desktop-shell");
    assert_eq!(evidence.allowed_role, "desktop");
    assert!(evidence.canonical_path_matches);
    assert!(evidence.build_id_matches);
    assert!(evidence.digest_matches);
    let backend = loaded.verify_backend().unwrap();
    assert_eq!(backend.component_id(), "python-backend");
    assert_eq!(backend.arguments(), ["--native-broker-backend"]);

    let rendered = format!("{loaded:?} {evidence:?} {backend:?}");
    assert!(!rendered.contains("desktop-fixture"));
    assert!(!rendered.contains(&sha256_hex(desktop_bytes)));
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn component_manifest_rejects_unknown_fields_escape_duplicates_and_mismatch() {
    let root = unique_test_root("manifest-invalid");
    std::fs::create_dir(&root).unwrap();
    let fixture = b"AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0";
    std::fs::write(root.join("broker-fixture"), fixture).unwrap();
    std::fs::write(root.join("client-fixture"), fixture).unwrap();
    std::fs::write(root.join("backend-fixture"), fixture).unwrap();
    let digest = sha256_hex(fixture);
    let base = serde_json::json!({
        "schema_version": 1,
        "product_version": "2.5.0",
        "broker": {
            "component_id": "native-broker",
            "path": "broker-fixture",
            "sha256": digest,
            "build_id": "2.5.0"
        },
        "clients": [{
            "component_id": "desktop-shell",
            "role": "desktop",
            "path": "client-fixture",
            "sha256": sha256_hex(fixture),
            "build_id": "2.5.0"
        }],
        "backend": {
            "component_id": "python-backend",
            "path": "backend-fixture",
            "sha256": sha256_hex(fixture),
            "build_id": "2.5.0",
            "arguments": ["--native-broker-backend"]
        }
    });

    let cases = [
        {
            let mut value = base.clone();
            value
                .as_object_mut()
                .unwrap()
                .insert("unexpected".into(), true.into());
            value
        },
        {
            let mut value = base.clone();
            value["clients"][0]["path"] = "../client-fixture".into();
            value
        },
        {
            let mut value = base.clone();
            let duplicate = value["clients"][0].clone();
            value["clients"].as_array_mut().unwrap().push(duplicate);
            value
        },
        {
            let mut value = base.clone();
            value["product_version"] = "2.5.1".into();
            value
        },
    ];
    for (index, value) in cases.into_iter().enumerate() {
        let path = root.join(format!("invalid-{index}.json"));
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert_eq!(
            ComponentManifest::load(&path, "2.5.0").unwrap_err().code(),
            "broker_unavailable"
        );
    }

    let valid_path = root.join("valid.json");
    std::fs::write(&valid_path, serde_json::to_vec(&base).unwrap()).unwrap();
    let loaded = ComponentManifest::load(&valid_path, "2.5.0").unwrap();
    std::fs::write(root.join("client-fixture"), b"changed").unwrap();
    assert_eq!(
        loaded
            .verify_client_executable(&root.join("client-fixture"))
            .unwrap_err()
            .code(),
        "broker_unauthorized"
    );
    assert_eq!(
        {
            std::fs::write(root.join("backend-fixture"), b"changed").unwrap();
            loaded.verify_backend().unwrap_err().code()
        },
        "broker_unavailable"
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[cfg(unix)]
#[test]
fn component_manifest_rejects_symlinked_ancestor_role_aliases() {
    use std::os::unix::fs::symlink;

    let root = unique_test_root("manifest-role-alias");
    let real_clients = root.join("clients");
    std::fs::create_dir_all(&real_clients).unwrap();
    let fixture = b"AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0";
    std::fs::write(root.join("broker-fixture"), fixture).unwrap();
    std::fs::write(root.join("backend-fixture"), fixture).unwrap();
    std::fs::write(real_clients.join("client-fixture"), fixture).unwrap();
    symlink(&real_clients, root.join("client-alias")).unwrap();
    let manifest = serde_json::json!({
        "schema_version": 1,
        "product_version": "2.5.0",
        "broker": {
            "component_id": "native-broker",
            "path": "broker-fixture",
            "sha256": sha256_hex(fixture),
            "build_id": "2.5.0"
        },
        "clients": [
            {
                "component_id": "desktop-shell",
                "role": "desktop",
                "path": "clients/client-fixture",
                "sha256": sha256_hex(fixture),
                "build_id": "2.5.0"
            },
            {
                "component_id": "maintenance-tool",
                "role": "maintenance",
                "path": "client-alias/client-fixture",
                "sha256": sha256_hex(fixture),
                "build_id": "2.5.0"
            }
        ],
        "backend": {
            "component_id": "python-backend",
            "path": "backend-fixture",
            "sha256": sha256_hex(fixture),
            "build_id": "2.5.0",
            "arguments": ["--native-broker-backend"]
        }
    });
    let path = root.join("native-components-v1.json");
    std::fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    assert_eq!(
        ComponentManifest::load(&path, "2.5.0").unwrap_err().code(),
        "broker_unavailable"
    );
    std::fs::remove_dir_all(root).unwrap();
}

#[cfg(unix)]
#[test]
fn unix_endpoint_rejects_insecure_roots_and_symlink_substitution() {
    use std::os::unix::fs::{symlink, PermissionsExt};

    let insecure = unique_test_root("unix-insecure-root");
    std::fs::create_dir(&insecure).unwrap();
    std::fs::set_permissions(&insecure, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(
        PlatformEndpoint::create_for_test(&insecure)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );
    std::fs::remove_dir_all(&insecure).unwrap();

    let substituted = unique_test_root("unix-symlink");
    std::fs::create_dir(&substituted).unwrap();
    std::fs::set_permissions(&substituted, std::fs::Permissions::from_mode(0o700)).unwrap();
    let target = substituted.join("target");
    std::fs::write(&target, b"synthetic").unwrap();
    symlink(&target, substituted.join("broker.sock")).unwrap();
    assert_eq!(
        PlatformEndpoint::create_for_test(&substituted)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );
    std::fs::remove_dir_all(substituted).unwrap();
}

#[cfg(unix)]
#[test]
fn unix_endpoint_rejects_substituted_insecure_and_hardlinked_lock_files() {
    use std::os::unix::fs::{symlink, PermissionsExt};

    let symlink_root = unique_test_root("unix-lock-symlink");
    std::fs::create_dir(&symlink_root).unwrap();
    std::fs::set_permissions(&symlink_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let target = symlink_root.join("target");
    std::fs::write(&target, b"synthetic").unwrap();
    std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o600)).unwrap();
    symlink(&target, symlink_root.join("broker.lock")).unwrap();
    assert_eq!(
        PlatformEndpoint::reserve_for_test(&symlink_root)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );
    std::fs::remove_dir_all(symlink_root).unwrap();

    let insecure_root = unique_test_root("unix-lock-mode");
    std::fs::create_dir(&insecure_root).unwrap();
    std::fs::set_permissions(&insecure_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let insecure_lock = insecure_root.join("broker.lock");
    std::fs::write(&insecure_lock, b"").unwrap();
    std::fs::set_permissions(&insecure_lock, std::fs::Permissions::from_mode(0o666)).unwrap();
    assert_eq!(
        PlatformEndpoint::reserve_for_test(&insecure_root)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );
    std::fs::remove_dir_all(insecure_root).unwrap();

    let linked_root = unique_test_root("unix-lock-hardlink");
    std::fs::create_dir(&linked_root).unwrap();
    std::fs::set_permissions(&linked_root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let linked_lock = linked_root.join("broker.lock");
    std::fs::write(&linked_lock, b"").unwrap();
    std::fs::set_permissions(&linked_lock, std::fs::Permissions::from_mode(0o600)).unwrap();
    std::fs::hard_link(&linked_lock, linked_root.join("alias.lock")).unwrap();
    assert_eq!(
        PlatformEndpoint::reserve_for_test(&linked_root)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );
    std::fs::remove_dir_all(linked_root).unwrap();
}

#[cfg(unix)]
#[test]
fn unix_live_unexpected_listener_is_never_unlinked_as_stale() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixListener;

    let root = unique_test_root("unix-live-unexpected");
    std::fs::create_dir(&root).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let socket_path = root.join("broker.sock");
    let listener = UnixListener::bind(&socket_path).unwrap();
    std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert_eq!(
        PlatformEndpoint::create_for_test(&root)
            .err()
            .unwrap()
            .code(),
        "broker_unavailable"
    );
    assert!(socket_path.exists());
    listener.set_nonblocking(true).unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(1);
    loop {
        match listener.accept() {
            Ok(_) => break,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                assert!(std::time::Instant::now() < deadline);
                thread::sleep(Duration::from_millis(5));
            }
            Err(error) => panic!("unexpected listener probe failure: {error}"),
        }
    }
    drop(listener);
    std::fs::remove_dir_all(root).unwrap();
}

#[cfg(unix)]
#[test]
fn unix_stale_socket_is_replaced_only_under_lock_and_cleanup_preserves_substitution() {
    use std::os::unix::fs::{symlink, PermissionsExt};
    use std::os::unix::net::UnixListener;

    let root = unique_test_root("unix-stale");
    std::fs::create_dir(&root).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
    let socket_path = root.join("broker.sock");
    let stale = UnixListener::bind(&socket_path).unwrap();
    drop(stale);
    std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert!(socket_path.exists());
    let mut endpoint = PlatformEndpoint::create_for_test(&root).unwrap();
    assert_eq!(
        std::fs::symlink_metadata(&socket_path)
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );

    std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o666)).unwrap();
    assert_eq!(
        endpoint
            .accept(Duration::from_millis(10))
            .unwrap_err()
            .code(),
        "broker_unavailable"
    );
    std::fs::remove_file(&socket_path).unwrap();
    let target = root.join("replacement");
    std::fs::write(&target, b"synthetic").unwrap();
    symlink(&target, &socket_path).unwrap();
    drop(endpoint);
    assert!(std::fs::symlink_metadata(&socket_path)
        .unwrap()
        .file_type()
        .is_symlink());
    std::fs::remove_dir_all(root).unwrap();
}
