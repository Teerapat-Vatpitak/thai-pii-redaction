//! Native control-plane client used for bootstrap and health validation.
//!
//! This module exposes no broker data operation and no backend endpoint.

use std::collections::BTreeSet;
use std::fmt;
use std::path::Path;
use std::process::ExitStatus;
use std::time::{Duration, Instant};

#[cfg(unix)]
use std::process::{Command, Stdio};

use serde_json::Value;

use crate::manifest::ComponentManifest;
use crate::transport::{NativeStream, PlatformEndpoint};
use crate::{
    canonical_json_bytes, deadline_ms, default_message_bytes, error_message, max_hello_bytes,
    parse_canonical_object, validate_response, ProtocolError,
};

pub struct BrokerControlClient {
    stream: NativeStream,
    role: String,
    protocol_version: u64,
    hello_request_id: String,
    timeout: Duration,
}

pub(crate) struct AuthenticatedClientParts {
    pub stream: NativeStream,
    pub protocol_version: u64,
    pub hello_request_id: String,
}

pub(crate) struct PreparedExistingControlClient {
    prepared: PreparedClient,
}

impl PreparedExistingControlClient {
    pub(crate) fn connect_until(
        &self,
        outer_deadline: Instant,
    ) -> Result<BrokerControlClient, ProtocolError> {
        let (handshake_timeout, deadline) =
            handshake_window_after_preparation(Duration::from_secs(5), Some(outer_deadline))?;
        BrokerControlClient::connect_prepared(
            &self.prepared,
            handshake_timeout,
            deadline,
            handshake_timeout,
        )
    }
}

#[doc(hidden)]
pub struct SealedBrokerProcess {
    #[cfg(unix)]
    child: std::process::Child,
    #[cfg(windows)]
    child: crate::process::WindowsSealedChild,
}

impl SealedBrokerProcess {
    pub fn try_wait(&mut self) -> std::io::Result<Option<ExitStatus>> {
        self.child.try_wait()
    }

    pub fn kill(&mut self) -> std::io::Result<()> {
        self.child.kill()
    }

    pub fn wait(&mut self) -> std::io::Result<ExitStatus> {
        self.child.wait()
    }
}

impl fmt::Debug for BrokerControlClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrokerControlClient")
            .field("role", &self.role)
            .field("protocol_version", &self.protocol_version)
            .finish_non_exhaustive()
    }
}

impl BrokerControlClient {
    pub(crate) fn into_authenticated_parts(
        self,
        expected_role: &str,
    ) -> Result<AuthenticatedClientParts, ProtocolError> {
        if self.role != expected_role {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        Ok(AuthenticatedClientParts {
            stream: self.stream,
            protocol_version: self.protocol_version,
            hello_request_id: self.hello_request_id,
        })
    }

    pub fn connect_existing(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
        timeout: Duration,
    ) -> Result<Self, ProtocolError> {
        if timeout.is_zero() {
            return unavailable();
        }
        let (prepared, handshake_timeout, deadline) =
            prepare_then_handshake_window(timeout, None, || {
                Self::prepare_existing(endpoint_root, manifest_path, role, product_version)
            })?;
        Self::connect_prepared(
            &prepared.prepared,
            handshake_timeout,
            deadline,
            handshake_timeout,
        )
    }

    #[doc(hidden)]
    pub fn connect_existing_for_test(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
        timeout: Duration,
    ) -> Result<Self, ProtocolError> {
        if timeout.is_zero() {
            return unavailable();
        }
        let (prepared, handshake_timeout, deadline) =
            prepare_then_handshake_window(timeout, None, || {
                Self::prepare_existing_for_test(endpoint_root, manifest_path, role, product_version)
            })?;
        Self::connect_prepared(
            &prepared.prepared,
            handshake_timeout,
            deadline,
            handshake_timeout,
        )
    }

    pub(crate) fn prepare_existing(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
    ) -> Result<PreparedExistingControlClient, ProtocolError> {
        Ok(PreparedExistingControlClient {
            prepared: PreparedClient::new(
                endpoint_root,
                manifest_path,
                role,
                product_version,
                false,
            )?,
        })
    }

    pub(crate) fn prepare_existing_for_test(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
    ) -> Result<PreparedExistingControlClient, ProtocolError> {
        Ok(PreparedExistingControlClient {
            prepared: PreparedClient::new(
                endpoint_root,
                manifest_path,
                role,
                product_version,
                true,
            )?,
        })
    }

    pub fn connect_or_start(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
        timeout: Duration,
    ) -> Result<Self, ProtocolError> {
        let prepared =
            PreparedClient::new(endpoint_root, manifest_path, role, product_version, false)?;
        Self::connect_or_start_prepared(prepared, timeout)
    }

    #[doc(hidden)]
    pub fn connect_or_start_for_test(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
        timeout: Duration,
    ) -> Result<Self, ProtocolError> {
        let prepared =
            PreparedClient::new(endpoint_root, manifest_path, role, product_version, true)?;
        Self::connect_or_start_prepared(prepared, timeout)
    }

    #[doc(hidden)]
    pub fn connect_or_start_with_launcher_for_test<F>(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
        timeout: Duration,
        launcher: F,
    ) -> Result<Self, ProtocolError>
    where
        F: FnOnce() -> Result<(), ProtocolError>,
    {
        let prepared =
            PreparedClient::new(endpoint_root, manifest_path, role, product_version, true)?;
        Self::connect_or_start_prepared_with(prepared, timeout, |_| launcher())
    }

    fn connect_or_start_prepared(
        prepared: PreparedClient,
        timeout: Duration,
    ) -> Result<Self, ProtocolError> {
        Self::connect_or_start_prepared_with(prepared, timeout, spawn_expected_broker)
    }

    fn connect_or_start_prepared_with<F>(
        prepared: PreparedClient,
        timeout: Duration,
        launcher: F,
    ) -> Result<Self, ProtocolError>
    where
        F: FnOnce(&ComponentManifest) -> Result<(), ProtocolError>,
    {
        if timeout.is_zero() || timeout > Duration::from_secs(30) {
            return unavailable();
        }
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(unavailable_error)?;
        let established_timeout = control_timeout(timeout);
        let first_attempt = deadline
            .saturating_duration_since(Instant::now())
            .min(Duration::from_millis(250));
        match Self::connect_prepared(&prepared, first_attempt, deadline, established_timeout) {
            Ok(client) => return Ok(client),
            Err(error) if error.code() == "broker_unavailable" => {}
            Err(error) => return Err(error),
        }
        if deadline.saturating_duration_since(Instant::now()).is_zero() {
            return unavailable();
        }
        launcher(&prepared.manifest)?;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return unavailable();
            }
            match Self::connect_prepared(
                &prepared,
                remaining.min(Duration::from_millis(250)),
                deadline,
                established_timeout,
            ) {
                Ok(client) => return Ok(client),
                Err(error) if error.code() == "broker_unavailable" => {
                    std::thread::sleep(
                        deadline
                            .saturating_duration_since(Instant::now())
                            .min(Duration::from_millis(25)),
                    );
                }
                Err(error) => return Err(error),
            }
        }
    }

    pub fn health(&mut self) -> Result<(), ProtocolError> {
        let request_id = random_request_id("health")?;
        let response = self.send_request("broker_health", &request_id, serde_json::json!({}))?;
        if response["result"] != serde_json::json!({"status": "ok"}) {
            return unavailable();
        }
        Ok(())
    }

    pub fn maintenance_drain_stop(&mut self) -> Result<(), ProtocolError> {
        let deadline = request_deadline(self.timeout, None)?;
        self.maintenance_drain_stop_until(deadline)
    }

    pub(crate) fn maintenance_drain_stop_until(
        &mut self,
        outer_deadline: Instant,
    ) -> Result<(), ProtocolError> {
        if self.role != "maintenance" {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        let request_id = random_request_id("stop")?;
        let response = self.send_request_until(
            "maintenance_drain_stop",
            &request_id,
            serde_json::json!({}),
            outer_deadline,
        )?;
        if response["result"] != serde_json::json!({"accepted": true}) {
            return unavailable();
        }
        Ok(())
    }

    fn connect_prepared(
        prepared: &PreparedClient,
        connect_timeout: Duration,
        overall_deadline: Instant,
        established_timeout: Duration,
    ) -> Result<Self, ProtocolError> {
        if connect_timeout.is_zero() || established_timeout.is_zero() {
            return unavailable();
        }
        let mut stream = NativeStream::connect(
            &prepared.publication,
            connect_timeout.min(overall_deadline.saturating_duration_since(Instant::now())),
        )?;
        let protocol_deadline = Instant::now()
            .checked_add(established_timeout)
            .ok_or_else(unavailable_error)?;
        let deadline = protocol_deadline.min(overall_deadline);
        if deadline.saturating_duration_since(Instant::now()).is_zero() {
            return Err(ProtocolError::new("operation_timeout", None));
        }
        let server = stream.inspect_server()?;
        let local = PlatformEndpoint::current_os_context()?;
        let peer = server.context();
        if !peer.credential_verified
            || !peer.stable_process_reference
            || peer.process_id == 0
            || peer.user_boundary != local.user_boundary
            || peer.logon_session != local.logon_session
        {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        server.ensure_stable()?;
        prepared
            .manifest
            .verify_broker_executable(server.executable())?;
        server.ensure_stable()?;

        let request_id = random_request_id("hello")?;
        let hello = serde_json::json!({
            "claimed_role": prepared.role,
            "client_product_version": prepared.product_version,
            "request_id": request_id,
            "supported_protocol_versions": [1],
        });
        if stream.has_pending_input()? {
            return read_pre_hello_response(
                &mut stream,
                &prepared.role,
                &request_id,
                &prepared.product_version,
                deadline,
            );
        }
        if let Err(write_error) = stream.write_value_until(&hello, max_hello_bytes(), deadline) {
            if let Ok(Some(raw)) = stream.read_hello_frame_until(max_hello_bytes(), deadline) {
                validate_hello_response(
                    &raw,
                    &prepared.role,
                    &request_id,
                    &prepared.product_version,
                )?;
            }
            return Err(write_error);
        }
        let raw = stream
            .read_hello_frame_until(max_hello_bytes(), deadline)?
            .ok_or_else(unavailable_error)?;
        validate_hello_response(&raw, &prepared.role, &request_id, &prepared.product_version)?;
        Ok(Self {
            stream,
            role: prepared.role.clone(),
            protocol_version: 1,
            hello_request_id: request_id,
            timeout: established_timeout,
        })
    }

    fn send_request(
        &mut self,
        operation: &str,
        request_id: &str,
        payload: Value,
    ) -> Result<Value, ProtocolError> {
        let deadline = request_deadline(self.timeout, None)?;
        self.send_request_until(operation, request_id, payload, deadline)
    }

    fn send_request_until(
        &mut self,
        operation: &str,
        request_id: &str,
        payload: Value,
        outer_deadline: Instant,
    ) -> Result<Value, ProtocolError> {
        let request = serde_json::json!({
            "broker_protocol_version": self.protocol_version,
            "operation": operation,
            "payload": payload,
            "request_id": request_id,
        });
        let deadline = request_deadline(self.timeout, Some(outer_deadline))?;
        self.stream
            .write_value_until(&request, default_message_bytes(), deadline)?;
        let raw = self
            .stream
            .read_frame_until(default_message_bytes(), deadline)?
            .ok_or_else(unavailable_error)?;
        let response = validate_response(&raw, &self.role, operation, request_id)?;
        if let Some(code) = response["error"]["code"].as_str() {
            return Err(ProtocolError::new(code, Some(request_id)));
        }
        Ok(response)
    }
}

fn read_pre_hello_response(
    stream: &mut NativeStream,
    role: &str,
    request_id: &str,
    product_version: &str,
    deadline: Instant,
) -> Result<BrokerControlClient, ProtocolError> {
    let raw = stream
        .read_hello_frame_until(max_hello_bytes(), deadline)?
        .ok_or_else(unavailable_error)?;
    match validate_hello_response(&raw, role, request_id, product_version) {
        Err(error) => Err(error),
        Ok(()) => Err(ProtocolError::new("request_invalid", None)),
    }
}

fn control_timeout(requested: Duration) -> Duration {
    let protocol = Duration::from_millis(deadline_ms("broker_health", false).unwrap_or(5000));
    requested.min(protocol)
}

fn request_deadline(
    timeout: Duration,
    outer_deadline: Option<Instant>,
) -> Result<Instant, ProtocolError> {
    let now = Instant::now();
    let protocol_deadline = now.checked_add(timeout).ok_or_else(unavailable_error)?;
    let deadline = outer_deadline
        .map(|outer| outer.min(protocol_deadline))
        .unwrap_or(protocol_deadline);
    if deadline.saturating_duration_since(now).is_zero() {
        return Err(ProtocolError::new("operation_timeout", None));
    }
    Ok(deadline)
}

fn prepare_then_handshake_window<T>(
    requested_timeout: Duration,
    outer_deadline: Option<Instant>,
    prepare: impl FnOnce() -> Result<T, ProtocolError>,
) -> Result<(T, Duration, Instant), ProtocolError> {
    let prepared = prepare()?;
    let (handshake_timeout, deadline) =
        handshake_window_after_preparation(requested_timeout, outer_deadline)?;
    Ok((prepared, handshake_timeout, deadline))
}

fn handshake_window_after_preparation(
    requested_timeout: Duration,
    outer_deadline: Option<Instant>,
) -> Result<(Duration, Instant), ProtocolError> {
    let now = Instant::now();
    let available = outer_deadline
        .map(|deadline| deadline.saturating_duration_since(now))
        .unwrap_or(requested_timeout);
    let handshake_timeout = control_timeout(requested_timeout.min(available));
    if handshake_timeout.is_zero() {
        return unavailable();
    }
    let deadline = now
        .checked_add(handshake_timeout)
        .ok_or_else(unavailable_error)?;
    Ok((handshake_timeout, deadline))
}

struct PreparedClient {
    manifest: ComponentManifest,
    publication: String,
    role: String,
    product_version: String,
}

impl PreparedClient {
    fn new(
        endpoint_root: &Path,
        manifest_path: &Path,
        role: &str,
        product_version: &str,
        allow_test_root: bool,
    ) -> Result<Self, ProtocolError> {
        if !matches!(role, "desktop" | "extension" | "maintenance") {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        let manifest = ComponentManifest::load(manifest_path, product_version)?;
        let current =
            std::env::current_exe().map_err(|_| ProtocolError::new("broker_unauthorized", None))?;
        let evidence = manifest.verify_client_executable(&current)?;
        if evidence.allowed_role != role {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        manifest.verified_broker_executable()?;
        let publication = if allow_test_root {
            PlatformEndpoint::publication_for_test(endpoint_root)?
        } else {
            PlatformEndpoint::publication_for(endpoint_root)?
        };
        Ok(Self {
            manifest,
            publication,
            role: role.to_owned(),
            product_version: product_version.to_owned(),
        })
    }
}

fn validate_hello_response(
    raw: &[u8],
    role: &str,
    request_id: &str,
    product_version: &str,
) -> Result<(), ProtocolError> {
    let value = parse_canonical_object(raw)?;
    if value.get("error").is_some() {
        if value.get("request_id").is_some_and(Value::is_null) {
            let busy = error_message("broker_busy", None, 1)?;
            if canonical_json_bytes(&busy)? == raw {
                return Err(ProtocolError::new("broker_busy", None));
            }
            return Err(ProtocolError::new("request_invalid", None));
        }
        let response = validate_response(raw, role, "broker_health", request_id)?;
        let code = response["error"]["code"]
            .as_str()
            .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
        return Err(ProtocolError::new(code, Some(request_id)));
    }
    let object = value
        .as_object()
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    let fields: BTreeSet<&str> = object.keys().map(String::as_str).collect();
    let expected = BTreeSet::from([
        "broker_product_version",
        "broker_protocol_version",
        "request_id",
        "role",
    ]);
    if fields != expected
        || object["broker_product_version"].as_str() != Some(product_version)
        || object["broker_protocol_version"].as_u64() != Some(1)
        || object["request_id"].as_str() != Some(request_id)
        || object["role"].as_str() != Some(role)
        || canonical_json_bytes(&value)? != raw
    {
        return Err(ProtocolError::new("broker_incompatible", Some(request_id)));
    }
    Ok(())
}

fn spawn_expected_broker(manifest: &ComponentManifest) -> Result<(), ProtocolError> {
    let executable = manifest.verified_broker_executable()?;
    let working_directory = executable.parent().ok_or_else(unavailable_error)?;
    let mut child = spawn_sealed_broker_process(&executable, &[], working_directory)?;
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}

#[cfg(unix)]
fn configure_broker_command(command: &mut Command) -> Result<(), ProtocolError> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    crate::installed_product::configure_child_command(command);
    use std::os::unix::process::CommandExt;
    let descriptor_limit = crate::process::descriptor_limit()?;
    // SAFETY: only async-signal-safe libc calls run before exec.
    unsafe {
        command.pre_exec(move || {
            crate::process::seal_inherited_descriptors(descriptor_limit)?;
            if libc::setsid() < 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    Ok(())
}

#[doc(hidden)]
pub fn spawn_sealed_broker_process_for_test(
    executable: &Path,
    arguments: &[String],
    working_directory: &Path,
) -> Result<SealedBrokerProcess, ProtocolError> {
    spawn_sealed_broker_process(executable, arguments, working_directory)
}

#[cfg(unix)]
fn spawn_sealed_broker_process(
    executable: &Path,
    arguments: &[String],
    working_directory: &Path,
) -> Result<SealedBrokerProcess, ProtocolError> {
    let mut command = Command::new(executable);
    command.args(arguments).current_dir(working_directory);
    configure_broker_command(&mut command)?;
    Ok(SealedBrokerProcess {
        child: command.spawn().map_err(|_| unavailable_error())?,
    })
}

#[cfg(windows)]
fn spawn_sealed_broker_process(
    executable: &Path,
    arguments: &[String],
    working_directory: &Path,
) -> Result<SealedBrokerProcess, ProtocolError> {
    Ok(SealedBrokerProcess {
        child: crate::process::spawn_sealed_process(executable, arguments, working_directory)?,
    })
}

fn random_request_id(prefix: &str) -> Result<String, ProtocolError> {
    let mut bytes = [0_u8; 12];
    getrandom::fill(&mut bytes).map_err(|_| ProtocolError::new("operation_failed", None))?;
    let mut value = String::with_capacity(prefix.len() + 1 + bytes.len() * 2);
    value.push_str(prefix);
    value.push('-');
    for byte in bytes {
        use std::fmt::Write;
        write!(&mut value, "{byte:02x}")
            .map_err(|_| ProtocolError::new("operation_failed", None))?;
    }
    Ok(value)
}

fn unavailable<T>() -> Result<T, ProtocolError> {
    Err(unavailable_error())
}

fn unavailable_error() -> ProtocolError {
    ProtocolError::new("broker_unavailable", None)
}

#[cfg(test)]
mod tests {
    use std::time::{Duration, Instant};

    use super::{prepare_then_handshake_window, request_deadline, validate_hello_response};
    use crate::{canonical_json_bytes, error_message};

    #[test]
    fn canonical_pre_hello_capacity_error_keeps_its_fixed_code() {
        let raw = canonical_json_bytes(&error_message("broker_busy", None, 1).unwrap()).unwrap();
        let error = validate_hello_response(&raw, "desktop", "hello-1", "2.5.0").unwrap_err();
        assert_eq!(error.code(), "broker_busy");
        assert_eq!(error.request_id(), None);
    }

    #[test]
    fn unrelated_null_id_hello_error_is_not_trusted() {
        let raw =
            canonical_json_bytes(&error_message("operation_failed", None, 1).unwrap()).unwrap();
        assert_eq!(
            validate_hello_response(&raw, "desktop", "hello-1", "2.5.0")
                .unwrap_err()
                .code(),
            "request_invalid"
        );
    }

    #[test]
    fn strict_preparation_keeps_handshake_budget_but_consumes_outer_deadline() {
        let requested = Duration::from_millis(100);
        let (preparation_finished, timeout, deadline) =
            prepare_then_handshake_window(requested, None, || {
                std::thread::sleep(Duration::from_millis(125));
                Ok(Instant::now())
            })
            .unwrap();
        assert_eq!(timeout, requested);
        assert!(deadline >= preparation_finished.checked_add(requested).unwrap());

        let outer = Instant::now() + Duration::from_millis(25);
        let expired = prepare_then_handshake_window(requested, Some(outer), || {
            std::thread::sleep(Duration::from_millis(50));
            Ok(())
        })
        .unwrap_err();
        assert_eq!(expired.code(), "broker_unavailable");

        let request_outer = Instant::now() + Duration::from_millis(200);
        std::thread::sleep(Duration::from_millis(25));
        let request = request_deadline(Duration::from_secs(5), Some(request_outer)).unwrap();
        assert_eq!(request, request_outer);
        let expired_request = request_deadline(requested, Some(Instant::now())).unwrap_err();
        assert_eq!(expired_request.code(), "operation_timeout");
    }
}
