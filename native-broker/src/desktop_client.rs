//! Typed authenticated native-broker client for the Tauri Desktop shell.

use std::fmt;
use std::path::Path;
use std::time::{Duration, Instant};

use serde_json::{Map, Value};

use crate::control_client::{AuthenticatedClientParts, BrokerControlClient};
use crate::transport::{NativeStream, NativeStreamAbortHandle};
use crate::{
    canonical_json_bytes, deadline_ms, max_frame_bytes, response_message_bytes, safe_error_code,
    validate_request, validate_response, ConnectionState, ProtocolError,
};

const DESKTOP_ROLE: &str = "desktop";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DesktopScopeKind {
    Ui,
    Hotkey,
}

impl DesktopScopeKind {
    pub const fn as_protocol_value(self) -> &'static str {
        match self {
            Self::Ui => "desktop_ui",
            Self::Hotkey => "desktop_hotkey",
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct DesktopClientError {
    code: String,
    connection_invalidated: bool,
    session_invalidated: bool,
}

impl DesktopClientError {
    pub fn code(&self) -> &str {
        &self.code
    }

    pub fn connection_invalidated(&self) -> bool {
        self.connection_invalidated
    }

    pub fn session_invalidated(&self) -> bool {
        self.session_invalidated
    }

    fn from_protocol(
        error: ProtocolError,
        connection_invalidated: bool,
        session_invalidated: bool,
    ) -> Self {
        Self {
            code: safe_error_code(error.code()).to_owned(),
            connection_invalidated,
            session_invalidated,
        }
    }
}

impl fmt::Debug for DesktopClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DesktopClientError")
            .field("code", &self.code)
            .field("connection_invalidated", &self.connection_invalidated)
            .field("session_invalidated", &self.session_invalidated)
            .finish()
    }
}

impl fmt::Display for DesktopClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.code)
    }
}

impl std::error::Error for DesktopClientError {}

pub struct DesktopBrokerClient {
    stream: Option<NativeStream>,
    protocol_version: u64,
    validation_state: ConnectionState,
}

#[derive(Debug)]
pub struct DesktopClientAbortHandle {
    inner: NativeStreamAbortHandle,
}

impl DesktopClientAbortHandle {
    pub fn abort(&self) {
        self.inner.abort();
    }
}

impl fmt::Debug for DesktopBrokerClient {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DesktopBrokerClient")
            .field("connected", &self.stream.is_some())
            .field("protocol_version", &self.protocol_version)
            .finish_non_exhaustive()
    }
}

impl DesktopBrokerClient {
    pub fn connect_or_start(
        endpoint_root: &Path,
        manifest_path: &Path,
        product_version: &str,
        timeout: Duration,
    ) -> Result<Self, DesktopClientError> {
        Self::validate_requested_configuration()?;
        let control = BrokerControlClient::connect_or_start(
            endpoint_root,
            manifest_path,
            DESKTOP_ROLE,
            product_version,
            timeout,
        )
        .map_err(|error| DesktopClientError::from_protocol(error, false, false))?;
        Self::from_control(control)
    }

    #[doc(hidden)]
    pub fn connect_or_start_for_test(
        endpoint_root: &Path,
        manifest_path: &Path,
        product_version: &str,
        timeout: Duration,
    ) -> Result<Self, DesktopClientError> {
        Self::validate_requested_configuration()?;
        let control = BrokerControlClient::connect_or_start_for_test(
            endpoint_root,
            manifest_path,
            DESKTOP_ROLE,
            product_version,
            timeout,
        )
        .map_err(|error| DesktopClientError::from_protocol(error, false, false))?;
        Self::from_control(control)
    }

    #[doc(hidden)]
    pub fn connect_or_start_with_launcher_for_test<F>(
        endpoint_root: &Path,
        manifest_path: &Path,
        product_version: &str,
        timeout: Duration,
        launcher: F,
    ) -> Result<Self, DesktopClientError>
    where
        F: FnOnce() -> Result<(), ProtocolError>,
    {
        Self::validate_requested_configuration()?;
        let control = BrokerControlClient::connect_or_start_with_launcher_for_test(
            endpoint_root,
            manifest_path,
            DESKTOP_ROLE,
            product_version,
            timeout,
            launcher,
        )
        .map_err(|error| DesktopClientError::from_protocol(error, false, false))?;
        Self::from_control(control)
    }

    fn from_control(control: BrokerControlClient) -> Result<Self, DesktopClientError> {
        let AuthenticatedClientParts {
            stream,
            protocol_version,
            hello_request_id,
        } = control
            .into_authenticated_parts(DESKTOP_ROLE)
            .map_err(|error| DesktopClientError::from_protocol(error, false, false))?;
        let validation_state = ConnectionState::for_authenticated_client(
            DESKTOP_ROLE,
            protocol_version,
            &hello_request_id,
        )
        .map_err(|error| DesktopClientError::from_protocol(error, false, false))?;
        Ok(Self {
            stream: Some(stream),
            protocol_version,
            validation_state,
        })
    }

    fn validate_requested_configuration() -> Result<(), DesktopClientError> {
        crate::installed_product::validate_requested_configuration()
            .map_err(|error| DesktopClientError::from_protocol(error, false, false))
    }

    pub fn health(&mut self) -> Result<(), DesktopClientError> {
        let result = self.request("broker_health", None, serde_json::json!({}), false)?;
        if result != serde_json::json!({"status": "ok"}) {
            self.invalidate_connection();
            return Err(DesktopClientError {
                code: "operation_failed".to_owned(),
                connection_invalidated: true,
                session_invalidated: true,
            });
        }
        Ok(())
    }

    pub fn open_scope(&mut self, kind: DesktopScopeKind) -> Result<String, DesktopClientError> {
        let result = self.request(
            "scope_open",
            None,
            serde_json::json!({"scope_kind": kind.as_protocol_value()}),
            true,
        )?;
        result["scope_id"]
            .as_str()
            .map(str::to_owned)
            .ok_or_else(|| self.integrity_failure(true))
    }

    pub fn close_scope(&mut self, scope_id: &str) -> Result<(), DesktopClientError> {
        let result = self.request("scope_close", Some(scope_id), serde_json::json!({}), true)?;
        if result != serde_json::json!({"closed": true}) {
            return Err(self.integrity_failure(true));
        }
        Ok(())
    }

    pub fn detect(&mut self, scope_id: &str, text: &str) -> Result<Value, DesktopClientError> {
        self.request(
            "detect",
            Some(scope_id),
            serde_json::json!({"text": text}),
            false,
        )
    }

    pub fn analyze(&mut self, scope_id: &str, text: &str) -> Result<Value, DesktopClientError> {
        self.request(
            "analyze",
            Some(scope_id),
            serde_json::json!({"text": text}),
            false,
        )
    }

    pub fn guard(&mut self, scope_id: &str, text: &str) -> Result<Value, DesktopClientError> {
        self.request(
            "guard",
            Some(scope_id),
            serde_json::json!({"text": text}),
            false,
        )
    }

    pub fn sanitize(
        &mut self,
        scope_id: &str,
        text: &str,
        mode: &str,
        session_id: Option<&str>,
    ) -> Result<Value, DesktopClientError> {
        let mut payload = serde_json::json!({"mode": mode, "text": text});
        if let Some(session_id) = session_id {
            payload["session_id"] = Value::String(session_id.to_owned());
        }
        self.request("sanitize", Some(scope_id), payload, session_id.is_some())
    }

    pub fn reidentify(
        &mut self,
        scope_id: &str,
        session_id: &str,
        text: &str,
    ) -> Result<Value, DesktopClientError> {
        self.request(
            "reidentify",
            Some(scope_id),
            serde_json::json!({"session_id": session_id, "text": text}),
            true,
        )
    }

    pub fn roundtrip(
        &mut self,
        scope_id: &str,
        text: &str,
        mode: &str,
        provider: &str,
    ) -> Result<Value, DesktopClientError> {
        self.request(
            "roundtrip",
            Some(scope_id),
            serde_json::json!({"mode": mode, "provider": provider, "text": text}),
            true,
        )
    }

    pub fn analyze_report(
        &mut self,
        scope_id: &str,
        text: &str,
    ) -> Result<Value, DesktopClientError> {
        self.request(
            "analyze_report",
            Some(scope_id),
            serde_json::json!({"text": text}),
            false,
        )
    }

    pub fn redact_pdf(
        &mut self,
        scope_id: &str,
        pdf_b64: &str,
    ) -> Result<Value, DesktopClientError> {
        self.request(
            "redact_pdf",
            Some(scope_id),
            serde_json::json!({"pdf_b64": pdf_b64}),
            false,
        )
    }

    pub fn audit_log(
        &mut self,
        scope_id: &str,
        limit: Option<u64>,
        offset: Option<u64>,
    ) -> Result<Value, DesktopClientError> {
        let mut payload = Map::new();
        if let Some(limit) = limit {
            payload.insert("limit".to_owned(), Value::from(limit));
        }
        if let Some(offset) = offset {
            payload.insert("offset".to_owned(), Value::from(offset));
        }
        self.request("audit_log", Some(scope_id), Value::Object(payload), false)
    }

    pub fn dispose_session(
        &mut self,
        scope_id: &str,
        session_id: &str,
    ) -> Result<(), DesktopClientError> {
        let result = self.request(
            "session_dispose",
            Some(scope_id),
            serde_json::json!({"session_id": session_id}),
            true,
        )?;
        if result != serde_json::json!({"disposed": true}) {
            return Err(self.integrity_failure(true));
        }
        Ok(())
    }

    pub fn disconnect(&mut self) {
        self.invalidate_connection();
    }

    pub fn abort_handle(&self) -> Result<DesktopClientAbortHandle, DesktopClientError> {
        let stream = self.stream.as_ref().ok_or_else(|| DesktopClientError {
            code: "broker_unavailable".to_owned(),
            connection_invalidated: true,
            session_invalidated: true,
        })?;
        let inner = stream
            .abort_handle()
            .map_err(|error| DesktopClientError::from_protocol(error, true, true))?;
        Ok(DesktopClientAbortHandle { inner })
    }

    fn request(
        &mut self,
        operation: &str,
        scope_id: Option<&str>,
        payload: Value,
        session_operation: bool,
    ) -> Result<Value, DesktopClientError> {
        if self.stream.is_none() {
            return Err(DesktopClientError {
                code: "broker_unavailable".to_owned(),
                connection_invalidated: true,
                session_invalidated: true,
            });
        }
        let request_id = random_request_id(operation)
            .map_err(|error| DesktopClientError::from_protocol(error, false, session_operation))?;
        let mut object = Map::from_iter([
            (
                "broker_protocol_version".to_owned(),
                Value::from(self.protocol_version),
            ),
            ("operation".to_owned(), Value::String(operation.to_owned())),
            ("payload".to_owned(), payload),
            ("request_id".to_owned(), Value::String(request_id.clone())),
        ]);
        if let Some(scope_id) = scope_id {
            object.insert("scope_id".to_owned(), Value::String(scope_id.to_owned()));
        }
        let request = Value::Object(object);
        let encoded = canonical_json_bytes(&request)
            .map_err(|error| DesktopClientError::from_protocol(error, false, session_operation))?;
        if let Err(error) = validate_request(&encoded, &mut self.validation_state, false) {
            let connection_invalidated = self.validation_state.terminal();
            if connection_invalidated {
                self.invalidate_connection();
            }
            return Err(DesktopClientError::from_protocol(
                error,
                connection_invalidated,
                session_operation || connection_invalidated,
            ));
        }
        let duration = deadline_ms(operation, false)
            .map(Duration::from_millis)
            .ok_or_else(|| DesktopClientError {
                code: "operation_failed".to_owned(),
                connection_invalidated: false,
                session_invalidated: session_operation,
            })?;
        let deadline = Instant::now()
            .checked_add(duration)
            .ok_or_else(|| DesktopClientError {
                code: "operation_failed".to_owned(),
                connection_invalidated: false,
                session_invalidated: session_operation,
            })?;
        let Some(limit) = response_message_bytes(DESKTOP_ROLE, operation) else {
            return Err(self.integrity_failure(true));
        };
        let stream = self.stream.as_mut().expect("checked connected stream");
        if let Err(error) = stream.write_value_until(&request, max_frame_bytes(), deadline) {
            return Err(self.transport_failure(error));
        }
        let raw = match stream.read_frame_until(limit, deadline) {
            Ok(Some(raw)) => raw,
            Ok(None) => {
                return Err(self.transport_failure(ProtocolError::new("broker_unavailable", None)))
            }
            Err(error) => return Err(self.transport_failure(error)),
        };
        let response = match validate_response(&raw, DESKTOP_ROLE, operation, &request_id) {
            Ok(response) => response,
            Err(error) => {
                self.invalidate_connection();
                return Err(DesktopClientError::from_protocol(error, true, true));
            }
        };
        if let Some(code) = response["error"]["code"].as_str() {
            let invalidate_session = session_operation
                || matches!(
                    code,
                    "operation_timeout" | "operation_failed" | "session_unavailable"
                );
            let invalidate_connection = matches!(
                code,
                "broker_incompatible"
                    | "broker_unauthorized"
                    | "broker_unavailable"
                    | "request_invalid"
            );
            if invalidate_connection {
                self.invalidate_connection();
            }
            return Err(DesktopClientError {
                code: safe_error_code(code).to_owned(),
                connection_invalidated: invalidate_connection,
                session_invalidated: invalidate_session || invalidate_connection,
            });
        }
        Ok(response["result"].clone())
    }

    fn transport_failure(&mut self, error: ProtocolError) -> DesktopClientError {
        self.invalidate_connection();
        DesktopClientError::from_protocol(error, true, true)
    }

    fn integrity_failure(&mut self, session_invalidated: bool) -> DesktopClientError {
        self.invalidate_connection();
        DesktopClientError {
            code: "operation_failed".to_owned(),
            connection_invalidated: true,
            session_invalidated,
        }
    }

    fn invalidate_connection(&mut self) {
        if let Some(mut stream) = self.stream.take() {
            stream.shutdown();
        }
    }
}

impl Drop for DesktopBrokerClient {
    fn drop(&mut self) {
        self.invalidate_connection();
    }
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
