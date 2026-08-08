//! Slice 2 broker runtime: authenticated hello, health, and maintenance stop.

use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, TryLockError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use zeroize::Zeroizing;

use crate::admission::{decide_admission, BrokerOsContext};
use crate::backend::{BackendTimeouts, ManagedBackend};
use crate::control::{ControlAction, Slice2ControlPlane};
use crate::manifest::ComponentManifest;
use crate::transport::{AcceptedConnection, ConnectionLimiter, PlatformEndpoint};
use crate::{
    deadline_ms, default_message_bytes, error_message, max_frame_bytes, max_hello_bytes,
    negotiate_hello, success_message, validate_request, ProtocolError,
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
    product_version: String,
    config: BrokerRuntimeConfig,
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
        validate_config(config)?;
        let manifest = Arc::new(ComponentManifest::load(manifest_path, product_version)?);
        let current_executable =
            std::env::current_exe().map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        manifest.verify_broker_executable(&current_executable)?;
        let endpoint_reservation = PlatformEndpoint::reserve(endpoint_root)?;
        let verified_backend = manifest.verify_backend()?;
        let backend =
            ManagedBackend::spawn_verified(&verified_backend, product_version, backend_timeouts)?;
        let endpoint = endpoint_reservation.publish()?;
        Ok(Self {
            endpoint,
            manifest,
            backend: Arc::new(Mutex::new(backend)),
            product_version: product_version.to_owned(),
            config,
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
        Ok(Self {
            endpoint,
            manifest: Arc::new(manifest),
            backend: Arc::new(Mutex::new(backend)),
            product_version: product_version.to_owned(),
            config,
        })
    }

    pub fn publication(&self) -> String {
        self.endpoint.publication()
    }

    pub fn run(mut self) -> Result<BrokerExit, ProtocolError> {
        let broker_context = Arc::new(self.endpoint.broker_context()?);
        let limiter = ConnectionLimiter::new(crate::transport::MAX_ACTIVE_CONNECTIONS);
        let stop = Arc::new(AtomicBool::new(false));
        let backend_failed = Arc::new(AtomicBool::new(false));
        let maintenance_stop = Arc::new(AtomicBool::new(false));
        let mut workers: Vec<JoinHandle<()>> = Vec::new();
        let mut idle_since = Instant::now();
        let mut was_active = false;

        loop {
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
                    let permit = match limiter.try_acquire() {
                        Ok(permit) => permit,
                        Err(_) => {
                            send_fixed_error(
                                connection.stream_mut(),
                                "broker_busy",
                                None,
                                1,
                                self.config.request_timeout,
                            );
                            continue;
                        }
                    };
                    let manifest = Arc::clone(&self.manifest);
                    let backend = Arc::clone(&self.backend);
                    let broker_context = Arc::clone(&broker_context);
                    let stop = Arc::clone(&stop);
                    let backend_failed = Arc::clone(&backend_failed);
                    let maintenance_stop = Arc::clone(&maintenance_stop);
                    let product_version = self.product_version.clone();
                    let config = self.config;
                    workers.push(std::thread::spawn(move || {
                        let _permit = permit;
                        handle_connection(
                            connection,
                            &manifest,
                            &broker_context,
                            &backend,
                            &stop,
                            &backend_failed,
                            &maintenance_stop,
                            &product_version,
                            config,
                        );
                    }));
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

#[allow(clippy::too_many_arguments)]
fn handle_connection(
    mut connection: AcceptedConnection,
    manifest: &ComponentManifest,
    broker_context: &BrokerOsContext,
    backend: &Mutex<ManagedBackend>,
    stop: &AtomicBool,
    backend_failed: &AtomicBool,
    maintenance_stop: &AtomicBool,
    product_version: &str,
    config: BrokerRuntimeConfig,
) {
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
    let hello_raw = match connection
        .stream_mut()
        .read_hello_frame_until(max_hello_bytes(), hello_deadline)
    {
        Ok(Some(frame)) => frame,
        Ok(None) => return,
        Err(error) => {
            send_fixed_error_until(
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
            send_fixed_error_until(
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
            send_fixed_error_until(
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
        send_fixed_error_until(
            connection.stream_mut(),
            error.code(),
            error.request_id(),
            negotiation.state.protocol_version(),
            hello_deadline,
        );
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
    let control = Slice2ControlPlane::new();
    loop {
        if stop.load(Ordering::Acquire) {
            return;
        }
        let control_budget =
            Duration::from_millis(deadline_ms("broker_health", false).unwrap_or(5000))
                .min(config.request_timeout);
        let Some(request_deadline) = Instant::now().checked_add(control_budget) else {
            return;
        };
        let raw = match connection
            .stream_mut()
            .read_frame_until(request_frame_limit, request_deadline)
        {
            Ok(Some(frame)) => Zeroizing::new(frame),
            Ok(None) => return,
            Err(error) => {
                send_fixed_error_until(
                    connection.stream_mut(),
                    error.code(),
                    error.request_id(),
                    state.protocol_version(),
                    request_deadline,
                );
                return;
            }
        };
        let request = match validate_request(&raw, &mut state, false) {
            Ok(request) => request,
            Err(error) => {
                send_fixed_error_until(
                    connection.stream_mut(),
                    error.code(),
                    error.request_id(),
                    state.protocol_version(),
                    request_deadline,
                );
                return;
            }
        };
        let action = match control.authorize(&admission, &request.operation) {
            Ok(action) => action,
            Err(error) => {
                send_fixed_error_until(
                    connection.stream_mut(),
                    error.code(),
                    Some(&request.request_id),
                    state.protocol_version(),
                    request_deadline,
                );
                if error.code() == "broker_unauthorized" {
                    return;
                }
                continue;
            }
        };
        let response = match action {
            ControlAction::Health => {
                let healthy = match backend.try_lock() {
                    Ok(mut backend) => {
                        if stop.load(Ordering::Acquire) {
                            return;
                        }
                        backend.health_until(request_deadline).is_ok()
                    }
                    Err(TryLockError::WouldBlock) => {
                        send_fixed_error_until(
                            connection.stream_mut(),
                            "broker_busy",
                            Some(&request.request_id),
                            state.protocol_version(),
                            request_deadline,
                        );
                        return;
                    }
                    Err(TryLockError::Poisoned(_)) => false,
                };
                if !healthy {
                    backend_failed.store(true, Ordering::Release);
                    stop.store(true, Ordering::Release);
                    send_fixed_error_until(
                        connection.stream_mut(),
                        "broker_unavailable",
                        Some(&request.request_id),
                        state.protocol_version(),
                        request_deadline,
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
            }
            ControlAction::DrainStop => {
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
                        request_deadline,
                    );
                }
                stop.store(true, Ordering::Release);
                return;
            }
        };
        let Ok(response) = response else {
            send_fixed_error_until(
                connection.stream_mut(),
                "operation_failed",
                Some(&request.request_id),
                state.protocol_version(),
                request_deadline,
            );
            return;
        };
        if connection
            .stream_mut()
            .write_value_until(&response, default_message_bytes(), request_deadline)
            .is_err()
        {
            return;
        }
    }
}

fn send_fixed_error(
    stream: &mut crate::transport::NativeStream,
    code: &str,
    request_id: Option<&str>,
    protocol_version: u64,
    timeout: Duration,
) {
    if let Ok(response) = error_message(code, request_id, protocol_version) {
        let _ = stream.write_value(&response, default_message_bytes(), timeout);
    }
}

fn send_fixed_error_until(
    stream: &mut crate::transport::NativeStream,
    code: &str,
    request_id: Option<&str>,
    protocol_version: u64,
    deadline: Instant,
) {
    if let Ok(response) = error_message(code, request_id, protocol_version) {
        let _ = stream.write_value_until(&response, default_message_bytes(), deadline);
    }
}

fn reap_finished_workers(workers: &mut Vec<JoinHandle<()>>) -> bool {
    let mut panicked = false;
    let mut index = 0;
    while index < workers.len() {
        if workers[index].is_finished() {
            let worker = workers.swap_remove(index);
            panicked |= worker.join().is_err();
        } else {
            index += 1;
        }
    }
    panicked
}

fn drain_workers(workers: &mut Vec<JoinHandle<()>>, timeout: Duration) -> bool {
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
