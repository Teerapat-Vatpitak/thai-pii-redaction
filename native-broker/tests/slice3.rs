use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Barrier, Mutex};
use std::time::{Duration, Instant};

use aiguard_native_broker_protocol::data_plane::{
    BackendCall, BackendCompletion, BackendExecutor, BackendFailure, BackendGeneration,
    BackendReply, DataPlane, OperationKind, MAX_IN_FLIGHT_OPERATIONS, MAX_IN_FLIGHT_PER_ROLE,
    MAX_SCOPES_PER_CONNECTION, MAX_SESSIONS_PER_CONNECTION, MAX_SESSIONS_PER_ROLE,
};
use aiguard_native_broker_protocol::{
    canonical_json_bytes, negotiate_hello, validate_request, BrokerRequest, ConnectionState,
};
use serde_json::{json, Value};

const BACKEND_SESSION_A: &str = "00000000-0000-4000-8000-000000000001";
const BACKEND_SESSION_B: &str = "00000000-0000-4000-8000-000000000002";
const _: () = assert!(MAX_SESSIONS_PER_ROLE >= MAX_SESSIONS_PER_CONNECTION);
const _: () = assert!(MAX_SESSIONS_PER_ROLE < 200);

#[derive(Clone, Debug, Eq, PartialEq)]
struct CallRecord {
    operation: String,
    backend_session: bool,
    document_bytes: Option<usize>,
}

struct ScriptedBackend {
    generation: BackendGeneration,
    completions: Mutex<VecDeque<BackendCompletion>>,
    calls: Mutex<Vec<CallRecord>>,
    teardown_count: AtomicUsize,
    entered: Option<Arc<Barrier>>,
    release: Option<Arc<Barrier>>,
}

impl ScriptedBackend {
    fn new(completions: impl IntoIterator<Item = BackendCompletion>) -> Arc<Self> {
        Arc::new(Self {
            generation: BackendGeneration::for_test(1),
            completions: Mutex::new(completions.into_iter().collect()),
            calls: Mutex::new(Vec::new()),
            teardown_count: AtomicUsize::new(0),
            entered: None,
            release: None,
        })
    }

    fn with_generation(
        generation: u64,
        completions: impl IntoIterator<Item = BackendCompletion>,
    ) -> Arc<Self> {
        Arc::new(Self {
            generation: BackendGeneration::for_test(generation),
            completions: Mutex::new(completions.into_iter().collect()),
            calls: Mutex::new(Vec::new()),
            teardown_count: AtomicUsize::new(0),
            entered: None,
            release: None,
        })
    }

    fn concurrent(
        completions: impl IntoIterator<Item = BackendCompletion>,
        entered: Arc<Barrier>,
        release: Arc<Barrier>,
    ) -> Arc<Self> {
        Arc::new(Self {
            generation: BackendGeneration::for_test(1),
            completions: Mutex::new(completions.into_iter().collect()),
            calls: Mutex::new(Vec::new()),
            teardown_count: AtomicUsize::new(0),
            entered: Some(entered),
            release: Some(release),
        })
    }

    fn calls(&self) -> Vec<CallRecord> {
        self.calls.lock().unwrap().clone()
    }

    fn teardowns(&self) -> usize {
        self.teardown_count.load(Ordering::Acquire)
    }
}

impl BackendExecutor for ScriptedBackend {
    fn generation(&self) -> BackendGeneration {
        self.generation
    }

    fn execute(
        &self,
        call: &BackendCall,
        _deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        if cancelled() {
            return BackendCompletion::NotSubmitted(BackendFailure::Cancelled);
        }
        self.calls.lock().unwrap().push(CallRecord {
            operation: call.operation().to_owned(),
            backend_session: call.backend_session_id_for_test().is_some(),
            document_bytes: call.document_len_for_test(),
        });
        if let Some(barrier) = &self.entered {
            barrier.wait();
        }
        if let Some(barrier) = &self.release {
            barrier.wait();
        }
        self.completions
            .lock()
            .unwrap()
            .pop_front()
            .expect("scripted completion")
    }

    fn teardown(&self) {
        self.teardown_count.fetch_add(1, Ordering::AcqRel);
    }
}

struct PublicationRaceBackend {
    entered: Arc<Barrier>,
    release: Arc<Barrier>,
    teardown_count: AtomicUsize,
}

struct CancelBeforePublishBackend {
    cancelled: Arc<AtomicBool>,
    calls: AtomicUsize,
    teardown_count: AtomicUsize,
}

struct OversizedThenCancelBackend {
    cancelled: Arc<AtomicBool>,
    teardown_count: AtomicUsize,
}

struct BoundedConcurrencyBackend {
    entered: Arc<Barrier>,
    release: Arc<Barrier>,
    calls: AtomicUsize,
    active: AtomicUsize,
    maximum_active: AtomicUsize,
}

impl BackendExecutor for BoundedConcurrencyBackend {
    fn generation(&self) -> BackendGeneration {
        BackendGeneration::for_test(79)
    }

    fn execute(
        &self,
        call: &BackendCall,
        _deadline: Instant,
        _cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        if call.operation() == "session_dispose" {
            return disposal_success();
        }
        let index = self.calls.fetch_add(1, Ordering::AcqRel);
        let active = self.active.fetch_add(1, Ordering::AcqRel) + 1;
        self.maximum_active.fetch_max(active, Ordering::AcqRel);
        self.entered.wait();
        self.release.wait();
        self.active.fetch_sub(1, Ordering::AcqRel);
        if call.operation() == "sanitize" {
            sanitize_success(&format!("00000000-0000-4000-8003-{index:012x}"))
        } else {
            guard_success()
        }
    }

    fn teardown(&self) {}
}

impl BackendExecutor for CancelBeforePublishBackend {
    fn generation(&self) -> BackendGeneration {
        BackendGeneration::for_test(78)
    }

    fn execute(
        &self,
        call: &BackendCall,
        _deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        self.calls.fetch_add(1, Ordering::AcqRel);
        if call.operation() == "sanitize" {
            self.cancelled.store(true, Ordering::Release);
            sanitize_success(BACKEND_SESSION_A)
        } else if cancelled() {
            BackendCompletion::NotSubmitted(BackendFailure::Cancelled)
        } else {
            disposal_success()
        }
    }

    fn teardown(&self) {
        self.teardown_count.fetch_add(1, Ordering::AcqRel);
    }
}

impl BackendExecutor for OversizedThenCancelBackend {
    fn generation(&self) -> BackendGeneration {
        BackendGeneration::for_test(80)
    }

    fn execute(
        &self,
        _call: &BackendCall,
        _deadline: Instant,
        _cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        self.cancelled.store(true, Ordering::Release);
        BackendCompletion::ConfirmedTooLarge
    }

    fn teardown(&self) {
        self.teardown_count.fetch_add(1, Ordering::AcqRel);
    }
}

impl BackendExecutor for PublicationRaceBackend {
    fn generation(&self) -> BackendGeneration {
        BackendGeneration::for_test(77)
    }

    fn execute(
        &self,
        call: &BackendCall,
        _deadline: Instant,
        _cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion {
        match call.operation() {
            "sanitize" => {
                self.entered.wait();
                self.release.wait();
                sanitize_success(BACKEND_SESSION_A)
            }
            "roundtrip" => BackendCompletion::Unknown(BackendFailure::Transport),
            _ => panic!("unexpected race operation"),
        }
    }

    fn teardown(&self) {
        self.teardown_count.fetch_add(1, Ordering::AcqRel);
    }
}

fn confirmed(status: u16, body: Value) -> BackendCompletion {
    BackendCompletion::Confirmed(BackendReply::for_test(
        status,
        Some("2"),
        Some("application/json"),
        body,
    ))
}

fn sanitize_success(backend_session_id: &str) -> BackendCompletion {
    confirmed(
        200,
        json!({
            "detected_entity_count": 0,
            "entity_type_counts": {},
            "guard_findings": [],
            "highlights": [],
            "replacement_count": 0,
            "safety": {"residual_count": 0, "status": "pass"},
            "sanitized_text": "synthetic-safe-output",
            "section26_categories": [],
            "session_id": backend_session_id,
            "warnings": []
        }),
    )
}

fn reidentify_success() -> BackendCompletion {
    confirmed(
        200,
        json!({
            "leftover_count": 0,
            "replaced_count": 1,
            "restored_text": "synthetic-restored-output",
            "warnings": []
        }),
    )
}

fn detect_success() -> BackendCompletion {
    confirmed(
        200,
        json!({
            "detected_entity_count": 0,
            "entity_type_counts": {},
            "highlights": []
        }),
    )
}

fn guard_success() -> BackendCompletion {
    confirmed(200, json!({"flagged": false, "guard_findings": []}))
}

fn disposal_success() -> BackendCompletion {
    confirmed(200, json!({"deleted": true}))
}

fn session_unavailable() -> BackendCompletion {
    confirmed(
        404,
        json!({
            "error": {
                "category": "session",
                "code": "session_unavailable",
                "count": 0,
                "retryable": false,
                "status": 404
            }
        }),
    )
}

fn residual_failure() -> BackendCompletion {
    confirmed(
        422,
        json!({
            "error": {
                "category": "privacy",
                "code": "residual_pii",
                "count": 1,
                "retryable": false,
                "status": 422
            }
        }),
    )
}

fn restore_failure() -> BackendCompletion {
    confirmed(
        500,
        json!({
            "error": {
                "category": "internal",
                "code": "restore_failed",
                "count": 0,
                "retryable": false,
                "status": 500
            }
        }),
    )
}

fn request(
    operation: &str,
    scope_id: Option<&str>,
    payload: Value,
    uncertain_completion: &str,
) -> BrokerRequest {
    BrokerRequest {
        protocol_version: 1,
        request_id: format!("request-{operation}"),
        operation: operation.to_owned(),
        scope_id: scope_id.map(str::to_owned),
        payload,
        deadline_ms: Some(60_000),
        local_detection_phases: Some(0),
        local_intermediate_text_chars: None,
        remote_tner_max_calls: 0,
        remote_tner_text_chars: None,
        replay: "never".to_owned(),
        uncertain_completion: uncertain_completion.to_owned(),
    }
}

fn open_scope(
    connection: &mut aiguard_native_broker_protocol::data_plane::DataConnection,
) -> String {
    let result = connection
        .dispatch(
            &request(
                "scope_open",
                None,
                json!({"scope_kind": "desktop_ui"}),
                "connection_state",
            ),
            &|| false,
        )
        .unwrap();
    result["scope_id"].as_str().unwrap().to_owned()
}

fn create_session(
    connection: &mut aiguard_native_broker_protocol::data_plane::DataConnection,
    scope_id: &str,
) -> String {
    let result = connection
        .dispatch(
            &request(
                "sanitize",
                Some(scope_id),
                json!({"mode": "token", "text": "synthetic-input"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
        .unwrap();
    result["session_id"].as_str().unwrap().to_owned()
}

#[test]
fn operation_classification_pins_backend_state_semantics() {
    use OperationKind::*;
    let cases = [
        ("broker_health", json!({}), Control),
        (
            "scope_open",
            json!({"scope_kind": "desktop_ui"}),
            ConnectionState,
        ),
        ("scope_close", json!({}), TerminalScope),
        (
            "session_dispose",
            json!({"session_id": "session-a"}),
            TerminalSession,
        ),
        ("detect", json!({"text": "x"}), Stateless),
        ("analyze", json!({"text": "x"}), Stateless),
        ("guard", json!({"text": "x"}), Stateless),
        ("sanitize", json!({"text": "x"}), SessionCreate),
        (
            "sanitize",
            json!({"session_id": "session-a", "text": "x"}),
            SessionMutation,
        ),
        (
            "reidentify",
            json!({"session_id": "session-a", "text": "x"}),
            SessionMutation,
        ),
        (
            "roundtrip",
            json!({"mode": "token", "provider": "fake", "text": "x"}),
            TransientMapping,
        ),
        ("analyze_report", json!({"text": "x"}), Stateless),
        ("redact_pdf", json!({"pdf_b64": "WA=="}), Stateless),
        ("audit_log", json!({}), Stateless),
        ("maintenance_drain_stop", json!({}), GlobalControl),
    ];
    for (operation, payload, expected) in cases {
        assert_eq!(
            aiguard_native_broker_protocol::data_plane::operation_kind(operation, &payload),
            Some(expected),
            "{operation}"
        );
    }
}

#[test]
fn valid_stateless_operation_forwards_once_and_returns_exact_projection() {
    let backend = ScriptedBackend::new([detect_success()]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let result = connection
        .dispatch(
            &request(
                "detect",
                Some(&scope),
                json!({"text": "synthetic-input"}),
                "external_tner_possible",
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(
        result,
        json!({"detected_entity_count": 0, "entity_type_counts": {}, "highlights": []})
    );
    assert_eq!(backend.calls().len(), 1);
    assert_eq!(backend.teardowns(), 0);
}

#[test]
fn session_creation_and_same_owner_continuation_use_only_broker_handles() {
    let backend = ScriptedBackend::new([
        sanitize_success(BACKEND_SESSION_A),
        reidentify_success(),
        disposal_success(),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let handle = create_session(&mut connection, &scope);
    assert_ne!(handle, BACKEND_SESSION_A);
    let restored = connection
        .dispatch(
            &request(
                "reidentify",
                Some(&scope),
                json!({"session_id": handle, "text": "synthetic-masked-input"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(restored["replaced_count"], 1);
    assert_eq!(backend.calls().len(), 2);
    assert!(backend.calls()[1].backend_session);
}

#[test]
fn cross_connection_cross_scope_guessed_and_stale_handles_fail_closed() {
    let backend = ScriptedBackend::new([sanitize_success(BACKEND_SESSION_A), disposal_success()]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut owner = plane.open_connection("desktop").unwrap();
    let mut other = plane.open_connection("desktop").unwrap();
    let owner_scope = open_scope(&mut owner);
    let other_owner_scope = open_scope(&mut owner);
    let other_connection_scope = open_scope(&mut other);
    let handle = create_session(&mut owner, &owner_scope);

    {
        let error = other
            .dispatch(
                &request(
                    "reidentify",
                    Some(&other_connection_scope),
                    json!({"session_id": handle.as_str(), "text": "synthetic"}),
                    "known_session_mutation",
                ),
                &|| false,
            )
            .unwrap_err();
        assert_eq!(error.code(), "session_unavailable");
    }
    for (scope, session) in [
        (other_owner_scope.as_str(), handle.as_str()),
        (owner_scope.as_str(), "guessed-session"),
    ] {
        let error = owner
            .dispatch(
                &request(
                    "reidentify",
                    Some(scope),
                    json!({"session_id": session, "text": "synthetic"}),
                    "known_session_mutation",
                ),
                &|| false,
            )
            .unwrap_err();
        assert_eq!(error.code(), "session_unavailable");
    }

    owner
        .dispatch(
            &request(
                "session_dispose",
                Some(&owner_scope),
                json!({"session_id": handle}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap();
    let stale = owner
        .dispatch(
            &request(
                "reidentify",
                Some(&owner_scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
    assert_eq!(backend.calls().len(), 2);
}

#[test]
fn scope_close_invalidates_first_and_disposes_every_owned_session() {
    let backend = ScriptedBackend::new([
        sanitize_success(BACKEND_SESSION_A),
        sanitize_success(BACKEND_SESSION_B),
        disposal_success(),
        disposal_success(),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let first = create_session(&mut connection, &scope);
    let second = create_session(&mut connection, &scope);
    let closed = connection
        .dispatch(
            &request("scope_close", Some(&scope), json!({}), "owned_sessions"),
            &|| false,
        )
        .unwrap();
    assert_eq!(closed, json!({"closed": true}));
    for handle in [first, second] {
        let error = connection
            .dispatch(
                &request(
                    "reidentify",
                    Some(&scope),
                    json!({"session_id": handle, "text": "synthetic"}),
                    "known_session_mutation",
                ),
                &|| false,
            )
            .unwrap_err();
        assert!(matches!(
            error.code(),
            "broker_unauthorized" | "session_unavailable"
        ));
    }
    assert_eq!(
        backend
            .calls()
            .iter()
            .filter(|call| call.operation == "session_dispose")
            .count(),
        2
    );
}

#[test]
fn graceful_connection_close_disposes_and_reconnect_inherits_no_authority() {
    let backend = ScriptedBackend::new([sanitize_success(BACKEND_SESSION_A), disposal_success()]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut first = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut first);
    let handle = create_session(&mut first, &scope);
    first.close().unwrap();

    let mut reconnect = plane.open_connection("desktop").unwrap();
    let reconnect_scope = open_scope(&mut reconnect);
    let error = reconnect
        .dispatch(
            &request(
                "reidentify",
                Some(&reconnect_scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(error.code(), "session_unavailable");
    assert_eq!(backend.teardowns(), 0);
}

#[test]
fn definitely_not_submitted_and_confirmed_failure_are_not_collapsed_into_unknown() {
    let backend = ScriptedBackend::new([
        BackendCompletion::NotSubmitted(BackendFailure::Transport),
        residual_failure(),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);

    let unsubmitted = connection
        .dispatch(
            &request(
                "sanitize",
                Some(&scope),
                json!({"text": "synthetic"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(unsubmitted.code(), "operation_failed");
    assert_eq!(backend.teardowns(), 0);

    let rejected = connection
        .dispatch(
            &request(
                "sanitize",
                Some(&scope),
                json!({"text": "synthetic"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(rejected.code(), "residual_pii");
    assert_eq!(backend.teardowns(), 0);
}

#[test]
fn lost_new_session_response_forces_teardown_without_replay() {
    let backend = ScriptedBackend::new([BackendCompletion::Unknown(BackendFailure::Transport)]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let error = connection
        .dispatch(
            &request(
                "sanitize",
                Some(&scope),
                json!({"text": "synthetic"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(error.code(), "operation_failed");
    assert_eq!(backend.calls().len(), 1);
    assert_eq!(backend.teardowns(), 1);
    assert!(plane.stats().backend_invalidated);
}

#[test]
fn unknown_existing_session_mutation_requires_confirmed_disposal() {
    let backend = ScriptedBackend::new([
        sanitize_success(BACKEND_SESSION_A),
        BackendCompletion::Unknown(BackendFailure::Transport),
        disposal_success(),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let handle = create_session(&mut connection, &scope);
    let error = connection
        .dispatch(
            &request(
                "sanitize",
                Some(&scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(error.code(), "operation_failed");
    assert_eq!(backend.teardowns(), 0);
    assert_eq!(backend.calls().last().unwrap().operation, "session_dispose");
    let stale = connection
        .dispatch(
            &request(
                "reidentify",
                Some(&scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
}

#[test]
fn confirmed_restore_failure_still_invalidates_the_mutated_session() {
    let backend = ScriptedBackend::new([
        sanitize_success(BACKEND_SESSION_A),
        restore_failure(),
        disposal_success(),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let handle = create_session(&mut connection, &scope);

    let error = connection
        .dispatch(
            &request(
                "reidentify",
                Some(&scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();

    assert_eq!(error.code(), "restore_failed");
    assert_eq!(backend.teardowns(), 0);
    assert_eq!(backend.calls().last().unwrap().operation, "session_dispose");
    let stale = connection
        .dispatch(
            &request(
                "reidentify",
                Some(&scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
}

#[test]
fn unconfirmed_disposal_timeout_or_backend_crash_forces_global_invalidation() {
    for failure in [
        BackendFailure::Transport,
        BackendFailure::Timeout,
        BackendFailure::BackendDied,
    ] {
        let backend = ScriptedBackend::new([
            sanitize_success(BACKEND_SESSION_A),
            BackendCompletion::Unknown(failure),
        ]);
        let plane = DataPlane::new(backend.clone()).unwrap();
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        let handle = create_session(&mut connection, &scope);
        let error = connection
            .dispatch(
                &request(
                    "session_dispose",
                    Some(&scope),
                    json!({"session_id": handle}),
                    "known_session_mutation",
                ),
                &|| false,
            )
            .unwrap_err();
        assert!(matches!(
            error.code(),
            "operation_failed" | "operation_timeout"
        ));
        assert_eq!(backend.teardowns(), 1);
        assert!(plane.stats().backend_invalidated);
    }
}

#[test]
fn concurrent_generation_invalidation_never_fabricates_disposal_confirmation() {
    let backend = ScriptedBackend::new([
        sanitize_success(BACKEND_SESSION_A),
        sanitize_success(BACKEND_SESSION_B),
        BackendCompletion::Unknown(BackendFailure::Transport),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut invalidator = plane.open_connection("desktop").unwrap();
    let invalidator_scope = open_scope(&mut invalidator);
    let invalidator_handle = create_session(&mut invalidator, &invalidator_scope);
    let mut disposer = plane.open_connection("desktop").unwrap();
    let disposer_scope = open_scope(&mut disposer);
    let disposer_handle = create_session(&mut disposer, &disposer_scope);

    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let paused = Arc::new(AtomicBool::new(false));
    let worker_entered = Arc::clone(&entered);
    let worker_release = Arc::clone(&release);
    let worker_paused = Arc::clone(&paused);
    let worker = std::thread::spawn(move || {
        disposer.dispatch(
            &request(
                "session_dispose",
                Some(&disposer_scope),
                json!({"session_id": disposer_handle}),
                "known_session_mutation",
            ),
            &|| {
                if !worker_paused.swap(true, Ordering::AcqRel) {
                    worker_entered.wait();
                    worker_release.wait();
                }
                false
            },
        )
    });

    entered.wait();
    let invalidation = invalidator
        .dispatch(
            &request(
                "detect",
                Some(&invalidator_scope),
                json!({"text": "synthetic"}),
                "external_tner_possible",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(invalidation.code(), "operation_failed");
    release.wait();

    let disposal = worker.join().unwrap().unwrap_err();
    assert_eq!(disposal.code(), "broker_unavailable");
    assert_eq!(backend.teardowns(), 1);
    assert_eq!(
        backend
            .calls()
            .iter()
            .filter(|call| call.operation == "session_dispose")
            .count(),
        0
    );

    let stale = invalidator
        .dispatch(
            &request(
                "reidentify",
                Some(&invalidator_scope),
                json!({"session_id": invalidator_handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
    assert_eq!(plane.stats().desktop_sessions, 0);
}

#[test]
fn terminal_cleanup_failure_preserves_timeout_and_cancellation_precedence() {
    for operation in ["session_dispose", "scope_close"] {
        let backend = ScriptedBackend::new([
            sanitize_success(BACKEND_SESSION_A),
            BackendCompletion::Unknown(BackendFailure::Transport),
        ]);
        let plane = DataPlane::new(backend.clone()).unwrap();
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        let handle = create_session(&mut connection, &scope);
        let polls = AtomicUsize::new(0);
        let payload = if operation == "session_dispose" {
            json!({"session_id": handle})
        } else {
            json!({})
        };

        let error = connection
            .dispatch(
                &request(operation, Some(&scope), payload, "known_session_mutation"),
                &|| polls.fetch_add(1, Ordering::AcqRel) >= 2,
            )
            .unwrap_err();

        assert_eq!(error.code(), "operation_timeout", "{operation}");
        assert_eq!(backend.teardowns(), 1, "{operation}");
        assert_eq!(
            backend
                .calls()
                .iter()
                .filter(|call| call.operation == "session_dispose")
                .count(),
            1,
            "{operation}"
        );
        assert_eq!(plane.stats().desktop_sessions, 0, "{operation}");
        assert!(plane.stats().backend_invalidated, "{operation}");
    }
}

#[test]
fn stateless_transport_uncertainty_terminates_unaccounted_backend_work() {
    let backend = ScriptedBackend::new([BackendCompletion::Unknown(BackendFailure::Transport)]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let error = connection
        .dispatch(
            &request(
                "detect",
                Some(&scope),
                json!({"text": "synthetic"}),
                "external_tner_possible",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(error.code(), "operation_failed");
    assert_eq!(backend.calls().len(), 1);
    assert_eq!(backend.teardowns(), 1);
    assert!(plane.stats().backend_invalidated);
}

#[test]
fn unknown_roundtrip_cleanup_and_backend_death_always_tear_down() {
    for failure in [BackendFailure::Transport, BackendFailure::BackendDied] {
        let backend = ScriptedBackend::new([BackendCompletion::Unknown(failure)]);
        let plane = DataPlane::new(backend.clone()).unwrap();
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        let error = connection
            .dispatch(
                &request(
                    "roundtrip",
                    Some(&scope),
                    json!({"mode": "token", "provider": "fake", "text": "synthetic"}),
                    "transient_mapping_and_provider",
                ),
                &|| false,
            )
            .unwrap_err();
        assert_eq!(error.code(), "operation_failed");
        assert_eq!(backend.calls().len(), 1);
        assert_eq!(backend.teardowns(), 1);
    }
}

#[test]
fn deadline_and_cancellation_preserve_submission_certainty_and_no_replay() {
    let backend = ScriptedBackend::new([BackendCompletion::Unknown(BackendFailure::Timeout)]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let mut timed = request(
        "sanitize",
        Some(&scope),
        json!({"text": "synthetic"}),
        "possible_session_publication_or_known_session_mutation",
    );
    timed.deadline_ms = Some(1);
    let error = connection.dispatch(&timed, &|| false).unwrap_err();
    assert_eq!(error.code(), "operation_timeout");
    assert_eq!(backend.calls().len(), 1);
    assert_eq!(backend.teardowns(), 1);

    let before_submit_backend = ScriptedBackend::new([]);
    let before_submit_plane = DataPlane::new(before_submit_backend.clone()).unwrap();
    let mut before_submit = before_submit_plane.open_connection("desktop").unwrap();
    let before_scope = open_scope(&mut before_submit);
    let cancelled = before_submit
        .dispatch(
            &request(
                "guard",
                Some(&before_scope),
                json!({"text": "synthetic"}),
                "none",
            ),
            &|| true,
        )
        .unwrap_err();
    assert_eq!(cancelled.code(), "operation_timeout");
    assert!(before_submit_backend.calls().is_empty());
}

#[test]
fn cancellation_after_oversized_confirmation_keeps_timeout_precedence() {
    let cancelled = Arc::new(AtomicBool::new(false));
    let backend = Arc::new(OversizedThenCancelBackend {
        cancelled: Arc::clone(&cancelled),
        teardown_count: AtomicUsize::new(0),
    });
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let error = connection
        .dispatch(
            &request("guard", Some(&scope), json!({"text": "synthetic"}), "none"),
            &|| cancelled.load(Ordering::Acquire),
        )
        .unwrap_err();
    assert_eq!(error.code(), "operation_timeout");
    assert!(!plane.stats().backend_invalidated);
    assert_eq!(backend.teardown_count.load(Ordering::Acquire), 0);
}

#[test]
fn malformed_contract_auth_and_cross_field_failures_are_value_free_and_terminal() {
    let sentinel = "SYNTHETIC_RESPONSE_SENTINEL";
    let cases = [
        BackendReply::for_test(200, Some("1"), Some("application/json"), detect_body()),
        BackendReply::for_test(
            401,
            Some("2"),
            Some("application/json"),
            json!({"error": sentinel}),
        ),
        BackendReply::for_test(
            401,
            Some("2"),
            Some("application/json"),
            json!({
                "error": {
                    "category": "authentication",
                    "code": "authentication_required",
                    "count": 0,
                    "retryable": false,
                    "status": 401
                }
            }),
        ),
        BackendReply::for_test(
            200,
            Some("2"),
            Some("application/json"),
            json!({"detected_entity_count": 2, "entity_type_counts": {}, "highlights": []}),
        ),
        BackendReply::for_test(
            200,
            Some("2"),
            Some("text/plain"),
            json!({"value": sentinel}),
        ),
    ];
    for reply in cases {
        let backend = ScriptedBackend::new([BackendCompletion::Confirmed(reply)]);
        let plane = DataPlane::new(backend.clone()).unwrap();
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        let error = connection
            .dispatch(
                &request(
                    "detect",
                    Some(&scope),
                    json!({"text": "synthetic"}),
                    "external_tner_possible",
                ),
                &|| false,
            )
            .unwrap_err();
        assert_eq!(error.code(), "operation_failed");
        assert!(!format!("{error:?}").contains(sentinel));
        assert_eq!(backend.teardowns(), 1);
    }
}

fn detect_body() -> Value {
    json!({"detected_entity_count": 0, "entity_type_counts": {}, "highlights": []})
}

#[test]
fn backend_generation_teardown_invalidates_all_connections_and_never_revives_handles() {
    let old_backend = ScriptedBackend::with_generation(
        41,
        [
            sanitize_success(BACKEND_SESSION_A),
            guard_success(),
            BackendCompletion::Unknown(BackendFailure::BackendDied),
        ],
    );
    let old_plane = DataPlane::new(old_backend.clone()).unwrap();
    let mut first = old_plane.open_connection("desktop").unwrap();
    let mut second = old_plane.open_connection("desktop").unwrap();
    let first_scope = open_scope(&mut first);
    let second_scope = open_scope(&mut second);
    let handle = create_session(&mut first, &first_scope);
    second
        .dispatch(
            &request(
                "guard",
                Some(&second_scope),
                json!({"text": "synthetic"}),
                "none",
            ),
            &|| false,
        )
        .unwrap();
    let crash = second
        .dispatch(
            &request(
                "detect",
                Some(&second_scope),
                json!({"text": "synthetic"}),
                "external_tner_possible",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(crash.code(), "operation_failed");
    let invalidated = first
        .dispatch(
            &request(
                "reidentify",
                Some(&first_scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(invalidated.code(), "session_unavailable");

    let new_backend = ScriptedBackend::with_generation(42, []);
    let new_plane = DataPlane::new(new_backend).unwrap();
    assert_ne!(old_plane.stats().generation, new_plane.stats().generation);
    let mut reconnected = new_plane.open_connection("desktop").unwrap();
    let new_scope = open_scope(&mut reconnected);
    let stale = reconnected
        .dispatch(
            &request(
                "reidentify",
                Some(&new_scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(stale.code(), "session_unavailable");
}

#[test]
fn request_id_reuse_and_role_violation_never_reach_the_data_plane() {
    let backend = ScriptedBackend::new([]);
    let _plane = DataPlane::new(backend.clone()).unwrap();

    let hello = canonical_json_bytes(&json!({
        "claimed_role": "extension",
        "client_product_version": "2.5.0",
        "request_id": "hello-slice3",
        "supported_protocol_versions": [1]
    }))
    .unwrap();
    let negotiation = negotiate_hello(&hello, "extension", "2.5.0").unwrap();
    let mut state = negotiation.state;
    let forbidden = canonical_json_bytes(&json!({
        "broker_protocol_version": 1,
        "operation": "detect",
        "payload": {"text": "synthetic"},
        "request_id": "duplicate-id",
        "scope_id": "scope-a"
    }))
    .unwrap();
    assert_eq!(
        validate_request(&forbidden, &mut state, false)
            .unwrap_err()
            .code(),
        "broker_unauthorized"
    );
    assert_eq!(
        validate_request(&forbidden, &mut state, false)
            .unwrap_err()
            .code(),
        "request_invalid"
    );
    assert!(backend.calls().is_empty());
}

#[test]
fn scope_session_and_role_accounting_are_bounded_without_backend_side_effects() {
    let mut completions = Vec::new();
    for index in 0..MAX_SESSIONS_PER_CONNECTION {
        let backend_id = format!("00000000-0000-4000-8000-{index:012x}");
        completions.push(sanitize_success(&backend_id));
    }
    for _ in 0..MAX_SESSIONS_PER_CONNECTION {
        completions.push(disposal_success());
    }
    let backend = ScriptedBackend::new(completions);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let mut scopes = Vec::new();
    for _ in 0..MAX_SCOPES_PER_CONNECTION {
        scopes.push(open_scope(&mut connection));
    }
    let scope_limit = connection
        .dispatch(
            &request(
                "scope_open",
                None,
                json!({"scope_kind": "desktop_ui"}),
                "connection_state",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(scope_limit.code(), "broker_busy");

    for _ in 0..MAX_SESSIONS_PER_CONNECTION {
        create_session(&mut connection, &scopes[0]);
    }
    let before = backend.calls().len();
    let session_limit = connection
        .dispatch(
            &request(
                "sanitize",
                Some(&scopes[0]),
                json!({"text": "synthetic"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(session_limit.code(), "broker_busy");
    assert_eq!(backend.calls().len(), before);
}

#[test]
fn repeated_connect_create_dispose_disconnect_releases_all_bounded_state() {
    let cycles = 64;
    let mut completions = Vec::new();
    for index in 0..cycles {
        completions.push(sanitize_success(&format!(
            "00000000-0000-4000-8001-{index:012x}"
        )));
        completions.push(disposal_success());
    }
    let backend = ScriptedBackend::new(completions);
    let plane = DataPlane::new(backend.clone()).unwrap();
    for _ in 0..cycles {
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        let handle = create_session(&mut connection, &scope);
        connection
            .dispatch(
                &request(
                    "session_dispose",
                    Some(&scope),
                    json!({"session_id": handle}),
                    "known_session_mutation",
                ),
                &|| false,
            )
            .unwrap();
        connection.close().unwrap();
    }
    let stats = plane.stats();
    assert_eq!(stats.desktop_sessions, 0);
    assert_eq!(stats.extension_sessions, 0);
    assert_eq!(stats.in_flight, 0);
    assert_eq!(backend.teardowns(), 0);
}

#[test]
fn independent_connections_and_stateless_requests_run_concurrently() {
    let entered = Arc::new(Barrier::new(3));
    let release = Arc::new(Barrier::new(3));
    let backend = ScriptedBackend::concurrent(
        [guard_success(), guard_success()],
        entered.clone(),
        release.clone(),
    );
    let plane = DataPlane::new(backend).unwrap();
    let mut first = plane.open_connection("desktop").unwrap();
    let mut second = plane.open_connection("desktop").unwrap();
    let first_scope = open_scope(&mut first);
    let second_scope = open_scope(&mut second);

    let first_thread = std::thread::spawn(move || {
        first.dispatch(
            &request(
                "guard",
                Some(&first_scope),
                json!({"text": "synthetic-a"}),
                "none",
            ),
            &|| false,
        )
    });
    let second_thread = std::thread::spawn(move || {
        second.dispatch(
            &request(
                "guard",
                Some(&second_scope),
                json!({"text": "synthetic-b"}),
                "none",
            ),
            &|| false,
        )
    });
    entered.wait();
    release.wait();
    assert!(first_thread.join().unwrap().is_ok());
    assert!(second_thread.join().unwrap().is_ok());
}

#[test]
fn global_and_per_role_operation_admission_are_strictly_bounded() {
    assert_eq!(MAX_IN_FLIGHT_OPERATIONS, MAX_IN_FLIGHT_PER_ROLE * 2);
    let entered = Arc::new(Barrier::new(MAX_IN_FLIGHT_OPERATIONS + 1));
    let release = Arc::new(Barrier::new(MAX_IN_FLIGHT_OPERATIONS + 1));
    let backend = Arc::new(BoundedConcurrencyBackend {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
        calls: AtomicUsize::new(0),
        active: AtomicUsize::new(0),
        maximum_active: AtomicUsize::new(0),
    });
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut workers = Vec::new();

    for role_index in 0..MAX_IN_FLIGHT_PER_ROLE {
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        workers.push(std::thread::spawn(move || {
            connection.dispatch(
                &request(
                    "guard",
                    Some(&scope),
                    json!({"text": format!("synthetic-{role_index}")}),
                    "none",
                ),
                &|| false,
            )
        }));
    }
    for role_index in 0..MAX_IN_FLIGHT_PER_ROLE {
        let mut connection = plane.open_connection("extension").unwrap();
        let scope = connection
            .dispatch(
                &request(
                    "scope_open",
                    None,
                    json!({"scope_kind": "extension_panel"}),
                    "connection_state",
                ),
                &|| false,
            )
            .unwrap()["scope_id"]
            .as_str()
            .unwrap()
            .to_owned();
        workers.push(std::thread::spawn(move || {
            connection.dispatch(
                &request(
                    "sanitize",
                    Some(&scope),
                    json!({"text": format!("synthetic-{role_index}")}),
                    "possible_session_publication_or_known_session_mutation",
                ),
                &|| false,
            )
        }));
    }

    entered.wait();
    assert_eq!(plane.stats().in_flight, MAX_IN_FLIGHT_OPERATIONS);
    let mut extra = plane.open_connection("desktop").unwrap();
    let extra_scope = open_scope(&mut extra);
    let busy = extra
        .dispatch(
            &request(
                "guard",
                Some(&extra_scope),
                json!({"text": "synthetic-extra"}),
                "none",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(busy.code(), "broker_busy");
    assert_eq!(
        backend.calls.load(Ordering::Acquire),
        MAX_IN_FLIGHT_OPERATIONS
    );
    release.wait();

    for worker in workers {
        assert!(worker.join().unwrap().is_ok());
    }
    assert_eq!(
        backend.maximum_active.load(Ordering::Acquire),
        MAX_IN_FLIGHT_OPERATIONS
    );
    assert_eq!(plane.stats().in_flight, 0);
    assert_eq!(plane.stats().extension_sessions, 0);
}

#[test]
fn publication_lease_holds_role_admission_until_native_write_finishes() {
    let backend = ScriptedBackend::new((0..=MAX_IN_FLIGHT_PER_ROLE).map(|_| guard_success()));
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connections = Vec::new();
    let mut publications = Vec::new();
    for index in 0..MAX_IN_FLIGHT_PER_ROLE {
        let mut connection = plane.open_connection("desktop").unwrap();
        let scope = open_scope(&mut connection);
        publications.push(
            connection
                .dispatch_for_publication(
                    &request(
                        "guard",
                        Some(&scope),
                        json!({"text": format!("synthetic-{index}")}),
                        "none",
                    ),
                    &|| false,
                )
                .unwrap(),
        );
        connections.push(connection);
    }
    assert_eq!(plane.stats().in_flight, MAX_IN_FLIGHT_PER_ROLE);

    let mut extra = plane.open_connection("desktop").unwrap();
    let extra_scope = open_scope(&mut extra);
    let busy = extra
        .dispatch_for_publication(
            &request(
                "guard",
                Some(&extra_scope),
                json!({"text": "synthetic-extra"}),
                "none",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(busy.code(), "broker_busy");
    assert_eq!(backend.calls().len(), MAX_IN_FLIGHT_PER_ROLE);

    drop(publications.pop());
    assert_eq!(plane.stats().in_flight, MAX_IN_FLIGHT_PER_ROLE - 1);
    let publication = extra
        .dispatch_for_publication(
            &request(
                "guard",
                Some(&extra_scope),
                json!({"text": "synthetic-after-write"}),
                "none",
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(publication.value()["broker_protocol_version"], 1);
    assert_eq!(publication.value()["result"]["flagged"], false);
    drop(publication);
    drop(publications);
    assert_eq!(plane.stats().in_flight, 0);
}

#[test]
fn concurrent_generation_teardown_prevents_late_session_publication() {
    let entered = Arc::new(Barrier::new(2));
    let release = Arc::new(Barrier::new(2));
    let backend = Arc::new(PublicationRaceBackend {
        entered: Arc::clone(&entered),
        release: Arc::clone(&release),
        teardown_count: AtomicUsize::new(0),
    });
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut creating = plane.open_connection("desktop").unwrap();
    let mut uncertain = plane.open_connection("desktop").unwrap();
    let creating_scope = open_scope(&mut creating);
    let uncertain_scope = open_scope(&mut uncertain);

    let creating_thread = std::thread::spawn(move || {
        creating.dispatch(
            &request(
                "sanitize",
                Some(&creating_scope),
                json!({"text": "synthetic", "mode": "token"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &|| false,
        )
    });
    entered.wait();
    let roundtrip = uncertain
        .dispatch(
            &request(
                "roundtrip",
                Some(&uncertain_scope),
                json!({"text": "synthetic", "mode": "token", "provider": "fake"}),
                "request_transient_mapping_cleanup",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(roundtrip.code(), "operation_failed");
    release.wait();
    let creation = creating_thread.join().unwrap().unwrap_err();
    assert_eq!(creation.code(), "broker_unavailable");
    assert_eq!(plane.stats().desktop_sessions, 0);
    assert_eq!(backend.teardown_count.load(Ordering::Acquire), 1);
}

#[test]
fn disposal_on_one_connection_does_not_invalidate_an_unrelated_session() {
    let backend = ScriptedBackend::new([
        sanitize_success(BACKEND_SESSION_A),
        sanitize_success(BACKEND_SESSION_B),
        disposal_success(),
        reidentify_success(),
        disposal_success(),
    ]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut first = plane.open_connection("desktop").unwrap();
    let mut second = plane.open_connection("desktop").unwrap();
    let first_scope = open_scope(&mut first);
    let second_scope = open_scope(&mut second);
    let first_handle = create_session(&mut first, &first_scope);
    let second_handle = create_session(&mut second, &second_scope);
    first
        .dispatch(
            &request(
                "session_dispose",
                Some(&first_scope),
                json!({"session_id": first_handle}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap();
    assert!(second
        .dispatch(
            &request(
                "reidentify",
                Some(&second_scope),
                json!({"session_id": second_handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .is_ok());
    assert_eq!(backend.teardowns(), 0);
}

#[test]
fn pdf_boundary_bytes_and_remote_tner_limits_are_forwarded_without_policy_duplication() {
    let raw_limit = aiguard_native_broker_protocol::CONTRACT_JSON;
    let contract: Value = serde_json::from_str(raw_limit).unwrap();
    let max_pdf = contract["framing"]["max_pdf_raw_bytes"].as_u64().unwrap() as usize;
    let pdf = vec![b'X'; max_pdf];
    let encoded = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, pdf);
    let backend = ScriptedBackend::new([confirmed(
        200,
        json!({
            "after_png_b64": "WA==",
            "detected_entity_count": 0,
            "entity_type_counts": {},
            "fields": [],
            "human_review": false,
            "ocr_confidence": null,
            "redacted_pdf_b64": "WA==",
            "section26_categories": [],
            "source_type": "pdf_text",
            "warnings": []
        }),
    )]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    connection
        .dispatch(
            &request(
                "redact_pdf",
                Some(&scope),
                json!({"pdf_b64": encoded}),
                "none",
            ),
            &|| false,
        )
        .unwrap();
    assert_eq!(backend.calls()[0].document_bytes, Some(max_pdf));

    let hello = canonical_json_bytes(&json!({
        "claimed_role": "desktop",
        "client_product_version": "2.5.0",
        "request_id": "hello-tner-slice3",
        "supported_protocol_versions": [1]
    }))
    .unwrap();
    let mut state: ConnectionState = negotiate_hello(&hello, "desktop", "2.5.0").unwrap().state;
    let request_bytes = canonical_json_bytes(&json!({
        "broker_protocol_version": 1,
        "operation": "detect",
        "payload": {"text": "x".repeat(500)},
        "request_id": "remote-tner-slice3",
        "scope_id": "scope-a"
    }))
    .unwrap();
    let remote = validate_request(&request_bytes, &mut state, true).unwrap();
    assert_eq!(remote.remote_tner_max_calls, 501);
    assert_eq!(remote.remote_tner_text_chars, Some(500));
    assert_eq!(remote.deadline_ms, Some(7_520_000));
}

#[test]
fn errors_debug_and_state_debug_never_expose_payload_or_authority_values() {
    let sentinel = "SYNTHETIC_PAYLOAD_SENTINEL";
    let backend = ScriptedBackend::new([BackendCompletion::Confirmed(BackendReply::for_test(
        200,
        Some("2"),
        Some("application/json"),
        json!({"unexpected": sentinel}),
    ))]);
    let plane = DataPlane::new(backend).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let error = connection
        .dispatch(
            &request("guard", Some(&scope), json!({"text": sentinel}), "none"),
            &|| false,
        )
        .unwrap_err();
    for rendered in [
        format!("{error:?}"),
        format!("{plane:?}"),
        format!("{connection:?}"),
    ] {
        assert!(!rendered.contains(sentinel));
        assert!(!rendered.contains("127.0.0.1"));
        assert!(!rendered.contains(BACKEND_SESSION_A));
    }
}

#[test]
fn cancellation_race_has_only_confirmed_or_unknown_outcomes_and_never_a_second_call() {
    let cancelled = Arc::new(AtomicBool::new(false));
    let backend = ScriptedBackend::new([BackendCompletion::Unknown(BackendFailure::Cancelled)]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    cancelled.store(true, Ordering::Release);
    let flag = cancelled.clone();
    let error = connection
        .dispatch(
            &request(
                "detect",
                Some(&scope),
                json!({"text": "synthetic"}),
                "external_tner_possible",
            ),
            &move || flag.load(Ordering::Acquire),
        )
        .unwrap_err();
    assert_eq!(error.code(), "operation_timeout");
    assert!(backend.calls().is_empty() || backend.calls().len() == 1);
    assert!(backend.calls().len() <= 1);
}

#[test]
fn cancellation_after_confirmed_creation_never_publishes_session_authority() {
    let cancelled = Arc::new(AtomicBool::new(false));
    let backend = Arc::new(CancelBeforePublishBackend {
        cancelled: Arc::clone(&cancelled),
        calls: AtomicUsize::new(0),
        teardown_count: AtomicUsize::new(0),
    });
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let observed = Arc::clone(&cancelled);
    let error = connection
        .dispatch(
            &request(
                "sanitize",
                Some(&scope),
                json!({"text": "synthetic"}),
                "possible_session_publication_or_known_session_mutation",
            ),
            &move || observed.load(Ordering::Acquire),
        )
        .unwrap_err();

    assert_eq!(error.code(), "operation_timeout");
    assert_eq!(plane.stats().desktop_sessions, 0);
    assert!(plane.stats().backend_invalidated);
    assert_eq!(backend.calls.load(Ordering::Acquire), 2);
    assert_eq!(backend.teardown_count.load(Ordering::Acquire), 1);
}

#[test]
fn session_expiry_from_backend_removes_only_the_stale_broker_handle() {
    let backend =
        ScriptedBackend::new([sanitize_success(BACKEND_SESSION_A), session_unavailable()]);
    let plane = DataPlane::new(backend.clone()).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let handle = create_session(&mut connection, &scope);
    let expired = connection
        .dispatch(
            &request(
                "reidentify",
                Some(&scope),
                json!({"session_id": handle, "text": "synthetic"}),
                "known_session_mutation",
            ),
            &|| false,
        )
        .unwrap_err();
    assert_eq!(expired.code(), "session_unavailable");
    assert_eq!(plane.stats().desktop_sessions, 0);
    assert_eq!(backend.teardowns(), 0);
}

#[test]
fn fixed_deadline_is_monotonic_and_not_client_extendable() {
    let backend = ScriptedBackend::new([guard_success()]);
    let plane = DataPlane::new(backend).unwrap();
    let mut connection = plane.open_connection("desktop").unwrap();
    let scope = open_scope(&mut connection);
    let mut operation = request("guard", Some(&scope), json!({"text": "synthetic"}), "none");
    operation.deadline_ms = Some(Duration::from_secs(60).as_millis() as u64);
    let started = Instant::now();
    connection.dispatch(&operation, &|| false).unwrap();
    assert!(started.elapsed() < Duration::from_secs(1));
}
