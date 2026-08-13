//! Authenticated native broker runtime and private HTTP-v2 data forwarding.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, TryLockError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use zeroize::Zeroizing;

use crate::admission::{decide_admission, BrokerOsContext};
use crate::backend::{managed_backend_executor, BackendTimeouts, ManagedBackend};
use crate::control::{ControlAction, Slice2ControlPlane};
use crate::data_plane::DataPlane;
use crate::manifest::ComponentManifest;
use crate::transport::{
    AcceptedConnection, ConnectionLimiter, NativeStreamAbortHandle, PlatformEndpoint,
};
use crate::{
    default_message_bytes, error_message, max_frame_bytes, max_hello_bytes, negotiate_hello,
    response_message_bytes, success_message, validate_request, ProtocolError,
};

#[derive(Clone, Copy)]
pub struct BrokerRuntimeConfig {
    pub accept_poll: Duration,
    pub hello_timeout: Duration,
    pub request_timeout: Duration,
    pub idle_timeout: Duration,
    pub drain_timeout: Duration,
}

impl Default for BrokerRuntimeConfig {
    fn default() -> Self {
        Self {
            accept_poll: Duration::from_millis(50),
            hello_timeout: Duration::from_secs(5),
            request_timeout: Duration::from_secs(5),
            idle_timeout: Duration::from_secs(30),
            drain_timeout: Duration::from_secs(6),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrokerExit {
    Idle,
    Maintenance,
    BackendFailed,
    ForcedShutdown,
}

pub struct BrokerRuntime {
    endpoint: PlatformEndpoint,
    manifest: Arc<ComponentManifest>,
    backend: Arc<Mutex<ManagedBackend>>,
    data_plane: DataPlane,
    product_version: String,
    component_root: Option<PathBuf>,
    config: BrokerRuntimeConfig,
    stop: Arc<AtomicBool>,
}

struct ConnectionWorker {
    join: JoinHandle<()>,
    abort: NativeStreamAbortHandle,
}

impl std::fmt::Debug for BrokerRuntime {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("BrokerRuntime")
            .field("product_version", &self.product_version)
            .finish_non_exhaustive()
    }
}

impl BrokerRuntime {
    pub fn start(
        endpoint_root: &Path,
        manifest_path: &Path,
        product_version: &str,
        backend_timeouts: BackendTimeouts,
        config: BrokerRuntimeConfig,
    ) -> Result<Self, ProtocolError> {
        crate::installed_product::validate_requested_configuration()?;
        validate_config(config)?;
        let current_executable =
            std::env::current_exe().map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        let component_root = current_executable
            .parent()
            .filter(|path| path.is_absolute())
            .ok_or_else(|| ProtocolError::new("broker_unavailable", None))?;
        // Hold the endpoint reservation across package verification. A maintenance
        // transaction cannot prove the broker inactive while this admission is in
        // progress, and a marker created before the reservation is held fails here.
        let endpoint_reservation = PlatformEndpoint::reserve(endpoint_root)?;
        if crate::lifecycle::component_replacement_active(component_root)? {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let manifest = Arc::new(ComponentManifest::load(manifest_path, product_version)?);
        manifest.verify_broker_executable(&current_executable)?;
        let verified_backend = manifest.verify_backend()?;
        // Verification can be slow. Recheck before starting the backend so a
        // replacement that began while the reservation was held remains closed.
        if crate::lifecycle::component_replacement_active(component_root)? {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let backend = Arc::new(Mutex::new(ManagedBackend::spawn_verified(
            &verified_backend,
            product_version,
            backend_timeouts,
        )?));
        let data_plane = DataPlane::new(managed_backend_executor(&backend)?)?;
        let endpoint = endpoint_reservation.publish()?;
        Ok(Self {
            endpoint,
            manifest,
            backend,
            data_plane,
            product_version: product_version.to_owned(),
            component_root: Some(component_root.to_owned()),
            config,
            stop: Arc::new(AtomicBool::new(false)),
        })
    }

    #[doc(hidden)]
    pub fn from_parts_for_test(
        endpoint: PlatformEndpoint,
        manifest: ComponentManifest,
        backend: ManagedBackend,
        product_version: &str,
        config: BrokerRuntimeConfig,
    ) -> Result<Self, ProtocolError> {
        validate_config(config)?;
        if manifest.product_version() != product_version {
            return Err(ProtocolError::new("broker_incompatible", None));
        }
        let backend = Arc::new(Mutex::new(backend));
        let data_plane = DataPlane::new(managed_backend_executor(&backend)?)?;
        Ok(Self {
            endpoint,
            manifest: Arc::new(manifest),
            backend,
            data_plane,
            product_version: product_version.to_owned(),
            component_root: None,
            config,
            stop: Arc::new(AtomicBool::new(false)),
        })
    }

    pub fn publication(&self) -> String {
        self.endpoint.publication()
    }

    #[doc(hidden)]
    pub fn force_backend_terminate_for_test(&self) {
        match self.backend.lock() {
            Ok(mut backend) => backend.force_terminate(),
            Err(poisoned) => poisoned.into_inner().force_terminate(),
        }
    }

    #[doc(hidden)]
    pub fn data_plane_for_test(&self) -> DataPlane {
        self.data_plane.clone()
    }

    #[doc(hidden)]
    pub fn backend_handle_for_test(&self) -> Arc<Mutex<ManagedBackend>> {
        Arc::clone(&self.backend)
    }

    #[doc(hidden)]
    pub fn stop_signal_for_test(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.stop)
    }

    pub fn run(mut self) -> Result<BrokerExit, ProtocolError> {
        let broker_context = Arc::new(self.endpoint.broker_context()?);
        let limiter = ConnectionLimiter::new(crate::transport::MAX_ACTIVE_CONNECTIONS);
        let stop = Arc::clone(&self.stop);
        let backend_failed = Arc::new(AtomicBool::new(false));
        let maintenance_stop = Arc::new(AtomicBool::new(false));
        let mut workers: Vec<ConnectionWorker> = Vec::new();
        let mut idle_since = Instant::now();
        let mut was_active = false;

        loop {
            if let Some(component_root) = self.component_root.as_deref() {
                match crate::lifecycle::component_replacement_active(component_root) {
                    Ok(true) => {
                        maintenance_stop.store(true, Ordering::Release);
                        stop.store(true, Ordering::Release);
                    }
                    Ok(false) => {}
                    Err(_) => {
                        backend_failed.store(true, Ordering::Release);
                        stop.store(true, Ordering::Release);
                    }
                }
            }
            if reap_finished_workers(&mut workers) {
                backend_failed.store(true, Ordering::Release);
                stop.store(true, Ordering::Release);
            }
            let active = limiter.active();
            if active > 0 {
                was_active = true;
            } else if was_active {
                idle_since = Instant::now();
                was_active = false;
            }
            if stop.load(Ordering::Acquire) {
                break;
            }
            if active == 0 && idle_since.elapsed() >= self.config.idle_timeout {
                break;
            }
            match self.backend.try_lock() {
                Ok(mut backend) => {
                    if !backend.is_alive() {
                        backend_failed.store(true, Ordering::Release);
                        stop.store(true, Ordering::Release);
                        break;
                    }
                }
                Err(TryLockError::WouldBlock) => {}
                Err(TryLockError::Poisoned(_)) => {
                    backend_failed.store(true, Ordering::Release);
                    stop.store(true, Ordering::Release);
                    break;
                }
            }
            match self.endpoint.accept(self.config.accept_poll) {
                Ok(Some(connection)) => {
                    let mut connection = connection;
                    if replacement_blocks_admission(self.component_root.as_deref()) {
                        maintenance_stop.store(true, Ordering::Release);
                        stop.store(true, Ordering::Release);
                        continue;
                    }
                    let permit = match limiter.try_acquire() {
                        Ok(permit) => permit,
                        Err(_) => {
                            send_terminal_fixed_error(
                                connection.stream_mut(),
                                "broker_busy",
                                None,
                                1,
                                self.config.request_timeout,
                            );
                            continue;
                        }
                    };
                    let abort = match connection.stream().abort_handle() {
                        Ok(abort) => abort,
                        Err(_) => {
                            backend_failed.store(true, Ordering::Release);
                            stop.store(true, Ordering::Release);
                            continue;
                        }
                    };
                    let manifest = Arc::clone(&self.manifest);
                    let backend = Arc::clone(&self.backend);
                    let data_plane = self.data_plane.clone();
                    let broker_context = Arc::clone(&broker_context);
                    let stop = Arc::clone(&stop);
                    let backend_failed = Arc::clone(&backend_failed);
                    let maintenance_stop = Arc::clone(&maintenance_stop);
                    let product_version = self.product_version.clone();
                    let component_root = self.component_root.clone();
                    let config = self.config;
                    workers.push(ConnectionWorker {
                        abort,
                        join: std::thread::spawn(move || {
                            let _permit = permit;
                            handle_connection(
                                connection,
                                &manifest,
                                &broker_context,
                                &backend,
                                &data_plane,
                                &stop,
                                &backend_failed,
                                &maintenance_stop,
                                &product_version,
                                component_root.as_deref(),
                                config,
                            );
                        }),
                    });
                }
                Ok(None) => {}
                Err(error) if error.code() == "broker_unauthorized" => {}
                Err(_) => {
                    stop.store(true, Ordering::Release);
                    backend_failed.store(true, Ordering::Release);
                    break;
                }
            }
        }

        stop.store(true, Ordering::Release);
        abort_workers(&workers);
        if drain_workers(&mut workers, self.config.drain_timeout) {
            backend_failed.store(true, Ordering::Release);
        }
        let requested_exit = if backend_failed.load(Ordering::Acquire) {
            BrokerExit::BackendFailed
        } else if maintenance_stop.load(Ordering::Acquire) {
            BrokerExit::Maintenance
        } else {
            BrokerExit::Idle
        };
        let mut backend = self
            .backend
            .lock()
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        if requested_exit == BrokerExit::BackendFailed {
            backend.force_terminate();
            return Ok(requested_exit);
        }
        match backend.shutdown() {
            Ok(()) => Ok(requested_exit),
            Err(_) => {
                backend.force_terminate();
                Ok(BrokerExit::ForcedShutdown)
            }
        }
    }
}

fn replacement_blocks_admission(component_root: Option<&Path>) -> bool {
    component_root.is_some_and(|root| {
        !matches!(
            crate::lifecycle::component_replacement_active(root),
            Ok(false)
        )
    })
}

#[allow(clippy::too_many_arguments)]
fn handle_connection(
    mut connection: AcceptedConnection,
    manifest: &ComponentManifest,
    broker_context: &BrokerOsContext,
    backend: &Mutex<ManagedBackend>,
    data_plane: &DataPlane,
    stop: &AtomicBool,
    backend_failed: &AtomicBool,
    maintenance_stop: &AtomicBool,
    product_version: &str,
    component_root: Option<&Path>,
    config: BrokerRuntimeConfig,
) {
    if replacement_blocks_admission(component_root) {
        maintenance_stop.store(true, Ordering::Release);
        stop.store(true, Ordering::Release);
        return;
    }
    let Some(hello_deadline) = Instant::now().checked_add(config.hello_timeout) else {
        return;
    };
    let package = match manifest.verify_client_executable(connection.peer_executable()) {
        Ok(evidence) => evidence,
        Err(_) => return,
    };
    if connection.ensure_peer_stable().is_err() {
        return;
    }
    if replacement_blocks_admission(component_root) {
        maintenance_stop.store(true, Ordering::Release);
        stop.store(true, Ordering::Release);
        return;
    }
    let hello_raw = match connection
        .stream_mut()
        .read_hello_frame_until(max_hello_bytes(), hello_deadline)
    {
        Ok(Some(frame)) => frame,
        Ok(None) => return,
        Err(error) => {
            send_terminal_fixed_error_until(
                connection.stream_mut(),
                error.code(),
                error.request_id(),
                1,
                hello_deadline,
            );
            return;
        }
    };
    let negotiation = match negotiate_hello(&hello_raw, &package.allowed_role, product_version) {
        Ok(negotiation) => negotiation,
        Err(error) => {
            send_terminal_fixed_error_until(
                connection.stream_mut(),
                error.code(),
                error.request_id(),
                1,
                hello_deadline,
            );
            return;
        }
    };
    let admission = match decide_admission(
        broker_context,
        connection.peer_context(),
        &package,
        negotiation.state.role(),
    ) {
        Ok(admission) => admission,
        Err(error) => {
            send_terminal_fixed_error_until(
                connection.stream_mut(),
                error.code(),
                error.request_id(),
                negotiation.state.protocol_version(),
                hello_deadline,
            );
            return;
        }
    };
    if connection.ensure_peer_stable().is_err() {
        return;
    }
    if let Err(error) = connection.stream_mut().ensure_no_pending_input() {
        send_terminal_fixed_error_until(
            connection.stream_mut(),
            error.code(),
            error.request_id(),
            negotiation.state.protocol_version(),
            hello_deadline,
        );
        return;
    }
    if replacement_blocks_admission(component_root) {
        maintenance_stop.store(true, Ordering::Release);
        stop.store(true, Ordering::Release);
        return;
    }
    if connection
        .stream_mut()
        .write_value_until(
            &negotiation.response,
            default_message_bytes(),
            hello_deadline,
        )
        .is_err()
    {
        return;
    }
    let mut state = negotiation.state;
    let request_frame_limit = if state.role() == "desktop" {
        max_frame_bytes()
    } else {
        default_message_bytes()
    };
    if replacement_blocks_admission(component_root) {
        maintenance_stop.store(true, Ordering::Release);
        stop.store(true, Ordering::Release);
        return;
    }
    let mut data_connection = match admission.admitted_role() {
        "desktop" | "extension" => match data_plane.open_connection(admission.admitted_role()) {
            Ok(connection) => Some(connection),
            Err(error) => {
                send_terminal_fixed_error(
                    connection.stream_mut(),
                    error.code(),
                    error.request_id(),
                    state.protocol_version(),
                    config.request_timeout,
                );
                return;
            }
        },
        _ => None,
    };
    let control = Slice2ControlPlane::new();
    loop {
        if replacement_blocks_admission(component_root) {
            maintenance_stop.store(true, Ordering::Release);
            stop.store(true, Ordering::Release);
            return;
        }
        if stop.load(Ordering::Acquire) {
            return;
        }
        loop {
            match connection.stream_mut().has_pending_input() {
                Ok(true) => break,
                Ok(false) => match connection.stream_mut().peer_connected() {
                    Ok(true) => std::thread::sleep(Duration::from_millis(10)),
                    Ok(false) | Err(_) => return,
                },
                Err(_) => return,
            }
            if stop.load(Ordering::Acquire) {
                return;
            }
        }
        let Some(read_deadline) = Instant::now().checked_add(config.request_timeout) else {
            return;
        };
        let raw = match connection
            .stream_mut()
            .read_frame_until(request_frame_limit, read_deadline)
        {
            Ok(Some(frame)) => Zeroizing::new(frame),
            Ok(None) => return,
            Err(error) => {
                send_terminal_fixed_error_until(
                    connection.stream_mut(),
                    error.code(),
                    error.request_id(),
                    state.protocol_version(),
                    read_deadline,
                );
                return;
            }
        };
        if replacement_blocks_admission(component_root) {
            maintenance_stop.store(true, Ordering::Release);
            stop.store(true, Ordering::Release);
            return;
        }
        let request = match validate_request(&raw, &mut state, false) {
            Ok(request) => request,
            Err(error) => {
                send_terminal_fixed_error_until(
                    connection.stream_mut(),
                    error.code(),
                    error.request_id(),
                    state.protocol_version(),
                    read_deadline,
                );
                return;
            }
        };
        let Some(operation_deadline) = request.deadline_ms.and_then(|milliseconds| {
            Instant::now().checked_add(Duration::from_millis(milliseconds))
        }) else {
            send_terminal_fixed_error_until(
                connection.stream_mut(),
                "operation_failed",
                Some(&request.request_id),
                state.protocol_version(),
                read_deadline,
            );
            return;
        };

        let mut publication_lease = None;
        let response = if request.operation == "broker_health" {
            match control.authorize(&admission, &request.operation) {
                Ok(ControlAction::Health) => {}
                _ => {
                    send_terminal_fixed_error_until(
                        connection.stream_mut(),
                        "broker_unauthorized",
                        Some(&request.request_id),
                        state.protocol_version(),
                        operation_deadline,
                    );
                    return;
                }
            }
            let healthy = match backend.try_lock() {
                Ok(mut backend) => {
                    if stop.load(Ordering::Acquire) {
                        return;
                    }
                    backend.health_until(operation_deadline).is_ok()
                }
                Err(TryLockError::WouldBlock) => {
                    if !send_fixed_error_until(
                        connection.stream_mut(),
                        "broker_busy",
                        Some(&request.request_id),
                        state.protocol_version(),
                        operation_deadline,
                    ) {
                        return;
                    }
                    continue;
                }
                Err(TryLockError::Poisoned(_)) => false,
            };
            if !healthy {
                backend_failed.store(true, Ordering::Release);
                stop.store(true, Ordering::Release);
                send_terminal_fixed_error_until(
                    connection.stream_mut(),
                    "broker_unavailable",
                    Some(&request.request_id),
                    state.protocol_version(),
                    operation_deadline,
                );
                return;
            }
            success_message(
                "broker_health",
                &request.request_id,
                serde_json::json!({"status": "ok"}),
                admission.admitted_role(),
                state.protocol_version(),
            )
        } else if request.operation == "maintenance_drain_stop" {
            match control.authorize(&admission, &request.operation) {
                Ok(ControlAction::DrainStop) => {}
                _ => {
                    send_terminal_fixed_error_until(
                        connection.stream_mut(),
                        "broker_unauthorized",
                        Some(&request.request_id),
                        state.protocol_version(),
                        operation_deadline,
                    );
                    return;
                }
            }
            maintenance_stop.store(true, Ordering::Release);
            let response = success_message(
                "maintenance_drain_stop",
                &request.request_id,
                serde_json::json!({"accepted": true}),
                admission.admitted_role(),
                state.protocol_version(),
            );
            if let Ok(response) = &response {
                let _ = connection.stream_mut().write_value_until(
                    response,
                    default_message_bytes(),
                    operation_deadline,
                );
                connection
                    .stream_mut()
                    .finish_response_until(operation_deadline);
            }
            stop.store(true, Ordering::Release);
            return;
        } else {
            let Some(data_connection) = data_connection.as_mut() else {
                send_terminal_fixed_error_until(
                    connection.stream_mut(),
                    "broker_unauthorized",
                    Some(&request.request_id),
                    state.protocol_version(),
                    operation_deadline,
                );
                return;
            };
            let cancelled = || {
                stop.load(Ordering::Acquire)
                    || replacement_blocks_admission(component_root)
                    || connection.ensure_peer_stable().is_err()
                    || !connection.stream().peer_connected().unwrap_or(false)
            };
            match data_connection.dispatch_for_publication_until(
                &request,
                operation_deadline,
                &cancelled,
            ) {
                Ok(publication) => {
                    let (response, lease) = publication.into_parts();
                    publication_lease = Some(lease);
                    Ok(response)
                }
                Err(error) => {
                    let invalidated = data_plane.stats().backend_invalidated;
                    if invalidated {
                        backend_failed.store(true, Ordering::Release);
                        stop.store(true, Ordering::Release);
                    }
                    let terminal = invalidated
                        || matches!(
                            error.code(),
                            "broker_unauthorized" | "broker_unavailable" | "operation_timeout"
                        );
                    if terminal {
                        send_terminal_fixed_error_until(
                            connection.stream_mut(),
                            error.code(),
                            Some(&request.request_id),
                            state.protocol_version(),
                            operation_deadline,
                        );
                        return;
                    }
                    if !send_fixed_error_until(
                        connection.stream_mut(),
                        error.code(),
                        Some(&request.request_id),
                        state.protocol_version(),
                        operation_deadline,
                    ) {
                        return;
                    }
                    continue;
                }
            }
        };
        let Ok(response) = response else {
            send_terminal_fixed_error_until(
                connection.stream_mut(),
                "operation_failed",
                Some(&request.request_id),
                state.protocol_version(),
                operation_deadline,
            );
            return;
        };
        if replacement_blocks_admission(component_root) {
            maintenance_stop.store(true, Ordering::Release);
            stop.store(true, Ordering::Release);
            return;
        }
        let response_limit = response_message_bytes(admission.admitted_role(), &request.operation)
            .unwrap_or(default_message_bytes());
        if connection
            .stream_mut()
            .write_value_until(&response, response_limit, operation_deadline)
            .is_err()
        {
            return;
        }
        drop(publication_lease);
    }
}

fn send_terminal_fixed_error(
    stream: &mut crate::transport::NativeStream,
    code: &str,
    request_id: Option<&str>,
    protocol_version: u64,
    timeout: Duration,
) {
    let Some(deadline) = Instant::now().checked_add(timeout) else {
        return;
    };
    send_terminal_fixed_error_until(stream, code, request_id, protocol_version, deadline);
}

fn send_terminal_fixed_error_until(
    stream: &mut crate::transport::NativeStream,
    code: &str,
    request_id: Option<&str>,
    protocol_version: u64,
    deadline: Instant,
) {
    if let Ok(response) = error_message(code, request_id, protocol_version) {
        let _ = stream.write_value_until(&response, default_message_bytes(), deadline);
        stream.finish_response_until(deadline);
    }
}

fn send_fixed_error_until(
    stream: &mut crate::transport::NativeStream,
    code: &str,
    request_id: Option<&str>,
    protocol_version: u64,
    deadline: Instant,
) -> bool {
    if let Ok(response) = error_message(code, request_id, protocol_version) {
        return stream
            .write_value_until(&response, default_message_bytes(), deadline)
            .is_ok();
    }
    false
}

fn abort_workers(workers: &[ConnectionWorker]) {
    for worker in workers {
        worker.abort.abort();
    }
}

fn reap_finished_workers(workers: &mut Vec<ConnectionWorker>) -> bool {
    let mut panicked = false;
    let mut index = 0;
    while index < workers.len() {
        if workers[index].join.is_finished() {
            let worker = workers.swap_remove(index);
            panicked |= worker.join.join().is_err();
        } else {
            index += 1;
        }
    }
    panicked
}

fn drain_workers(workers: &mut Vec<ConnectionWorker>, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let mut panicked = false;
    while !workers.is_empty() && Instant::now() < deadline {
        panicked |= reap_finished_workers(workers);
        if !workers.is_empty() {
            std::thread::sleep(Duration::from_millis(10));
        }
    }
    panicked |= reap_finished_workers(workers);
    panicked || !workers.is_empty()
}

fn validate_config(config: BrokerRuntimeConfig) -> Result<(), ProtocolError> {
    if config.accept_poll.is_zero()
        || config.hello_timeout.is_zero()
        || config.request_timeout.is_zero()
        || config.idle_timeout.is_zero()
        || config.drain_timeout.is_zero()
        || config.accept_poll > Duration::from_secs(1)
        || config.hello_timeout > Duration::from_secs(30)
        || config.request_timeout > Duration::from_secs(30)
        || config.drain_timeout < config.request_timeout
        || config.drain_timeout < config.hello_timeout
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(())
}

#[cfg(test)]
mod admission_tests {
    use super::replacement_blocks_admission;
    use std::sync::{Arc, Barrier};

    #[test]
    fn every_live_admission_check_fails_closed_during_replacement() {
        let root =
            std::env::temp_dir().join(format!("aiguard-broker-admission-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir(&root).unwrap();
        assert!(!replacement_blocks_admission(Some(&root)));
        crate::lifecycle::begin_component_replacement(&root).unwrap();
        assert!(replacement_blocks_admission(Some(&root)));
        std::fs::remove_file(root.join(crate::lifecycle::COMPONENT_MAINTENANCE_FILE)).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn marker_created_after_accept_check_blocks_worker_admission() {
        let root = Arc::new(
            std::env::temp_dir().join(format!("aiguard-broker-accept-race-{}", std::process::id())),
        );
        let _ = std::fs::remove_dir_all(root.as_path());
        std::fs::create_dir(root.as_path()).unwrap();
        let accepted = Arc::new(Barrier::new(2));
        let admit = Arc::new(Barrier::new(2));
        let worker = {
            let root = Arc::clone(&root);
            let accepted = Arc::clone(&accepted);
            let admit = Arc::clone(&admit);
            std::thread::spawn(move || {
                assert!(!replacement_blocks_admission(Some(root.as_path())));
                accepted.wait();
                admit.wait();
                replacement_blocks_admission(Some(root.as_path()))
            })
        };
        accepted.wait();
        crate::lifecycle::begin_component_replacement(root.as_path()).unwrap();
        admit.wait();
        assert!(worker.join().unwrap());
        std::fs::remove_file(root.join(crate::lifecycle::COMPONENT_MAINTENANCE_FILE)).unwrap();
        std::fs::remove_dir(root.as_path()).unwrap();
    }

    #[test]
    fn startup_reservation_blocks_inactive_proof_across_marker_creation() {
        let endpoint_root =
            std::env::temp_dir().join(format!("aiguard-broker-start-race-{}", std::process::id()));
        let component_root = std::env::temp_dir().join(format!(
            "aiguard-broker-start-components-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&endpoint_root);
        let _ = std::fs::remove_dir_all(&component_root);
        std::fs::create_dir(&component_root).unwrap();
        let startup = crate::transport::PlatformEndpoint::reserve_for_test(&endpoint_root).unwrap();
        crate::lifecycle::begin_component_replacement(&component_root).unwrap();
        assert!(crate::transport::PlatformEndpoint::reserve_for_test(&endpoint_root).is_err());
        assert!(replacement_blocks_admission(Some(&component_root)));
        drop(startup);
        crate::transport::PlatformEndpoint::cleanup_runtime_root_for_test(&endpoint_root).unwrap();
        std::fs::remove_file(component_root.join(crate::lifecycle::COMPONENT_MAINTENANCE_FILE))
            .unwrap();
        std::fs::remove_dir(component_root).unwrap();
    }
}
