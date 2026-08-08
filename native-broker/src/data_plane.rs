//! Slice 3 connection-bound ownership and strict private-backend forwarding.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use base64::Engine;
use getrandom::fill;
use serde_json::{Map, Value};
use zeroize::Zeroizing;

use crate::{operation_allowed, success_message, BrokerRequest, ProtocolError};

pub const MAX_SCOPES_PER_CONNECTION: usize = 32;
pub const MAX_SESSIONS_PER_CONNECTION: usize = 32;
pub const MAX_SESSIONS_PER_ROLE: usize = 64;
pub const MAX_IN_FLIGHT_OPERATIONS: usize = 8;
pub const MAX_IN_FLIGHT_PER_ROLE: usize = 4;

const BACKEND_SESSION_ID_LEN: usize = 36;
const DISPOSAL_BUDGET: Duration = Duration::from_secs(60);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperationKind {
    Control,
    ConnectionState,
    Stateless,
    SessionCreate,
    SessionMutation,
    TransientMapping,
    TerminalSession,
    TerminalScope,
    GlobalControl,
}

pub fn operation_kind(operation: &str, payload: &Value) -> Option<OperationKind> {
    match operation {
        "broker_health" => Some(OperationKind::Control),
        "scope_open" => Some(OperationKind::ConnectionState),
        "scope_close" => Some(OperationKind::TerminalScope),
        "session_dispose" => Some(OperationKind::TerminalSession),
        "detect" | "analyze" | "guard" | "analyze_report" | "redact_pdf" | "audit_log" => {
            Some(OperationKind::Stateless)
        }
        "sanitize" => Some(
            if payload
                .as_object()
                .is_some_and(|payload| payload.contains_key("session_id"))
            {
                OperationKind::SessionMutation
            } else {
                OperationKind::SessionCreate
            },
        ),
        "reidentify" => Some(OperationKind::SessionMutation),
        "roundtrip" => Some(OperationKind::TransientMapping),
        "maintenance_drain_stop" => Some(OperationKind::GlobalControl),
        _ => None,
    }
}

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
pub struct BackendGeneration(u64);

impl BackendGeneration {
    pub fn generate() -> Result<Self, ProtocolError> {
        let mut bytes = [0_u8; 8];
        fill(&mut bytes).map_err(|_| ProtocolError::new("operation_failed", None))?;
        let value = u64::from_be_bytes(bytes);
        if value == 0 {
            return Err(ProtocolError::new("operation_failed", None));
        }
        Ok(Self(value))
    }

    #[doc(hidden)]
    pub const fn for_test(value: u64) -> Self {
        Self(value)
    }
}

impl fmt::Debug for BackendGeneration {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("BackendGeneration(<redacted>)")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BackendFailure {
    Timeout,
    Cancelled,
    Transport,
    BackendDied,
}

pub struct BackendReply {
    status: u16,
    contract_version: Option<String>,
    content_type: Option<String>,
    body: Value,
}

impl BackendReply {
    pub fn new(
        status: u16,
        contract_version: Option<String>,
        content_type: Option<String>,
        body: Value,
    ) -> Self {
        Self {
            status,
            contract_version,
            content_type,
            body,
        }
    }

    #[doc(hidden)]
    pub fn for_test(
        status: u16,
        contract_version: Option<&str>,
        content_type: Option<&str>,
        body: Value,
    ) -> Self {
        Self::new(
            status,
            contract_version.map(str::to_owned),
            content_type.map(str::to_owned),
            body,
        )
    }
}

impl fmt::Debug for BackendReply {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BackendReply")
            .field("status", &self.status)
            .finish_non_exhaustive()
    }
}

pub enum BackendCompletion {
    NotSubmitted(BackendFailure),
    Confirmed(BackendReply),
    ConfirmedTooLarge,
    Unknown(BackendFailure),
}

impl fmt::Debug for BackendCompletion {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotSubmitted(reason) => {
                formatter.debug_tuple("NotSubmitted").field(reason).finish()
            }
            Self::Confirmed(reply) => formatter.debug_tuple("Confirmed").field(reply).finish(),
            Self::ConfirmedTooLarge => formatter.write_str("ConfirmedTooLarge"),
            Self::Unknown(reason) => formatter.debug_tuple("Unknown").field(reason).finish(),
        }
    }
}

pub struct BackendCall {
    operation: String,
    payload: Value,
    backend_session_id: Option<Zeroizing<String>>,
    document: Option<Zeroizing<Vec<u8>>>,
    local_detection_phases: Option<u64>,
    local_intermediate_text_chars: Option<u64>,
}

impl BackendCall {
    pub fn operation(&self) -> &str {
        &self.operation
    }

    pub(crate) fn payload(&self) -> &Value {
        &self.payload
    }

    pub(crate) fn backend_session_id(&self) -> Option<&str> {
        self.backend_session_id.as_deref().map(String::as_str)
    }

    pub(crate) fn document(&self) -> Option<&[u8]> {
        self.document.as_deref().map(Vec::as_slice)
    }

    pub(crate) fn local_detection_phases(&self) -> Option<u64> {
        self.local_detection_phases
    }

    pub(crate) fn local_intermediate_text_chars(&self) -> Option<u64> {
        self.local_intermediate_text_chars
    }

    #[doc(hidden)]
    pub fn backend_session_id_for_test(&self) -> Option<&str> {
        self.backend_session_id()
    }

    #[doc(hidden)]
    pub fn document_len_for_test(&self) -> Option<usize> {
        self.document().map(<[u8]>::len)
    }
}

impl fmt::Debug for BackendCall {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BackendCall")
            .field("operation", &self.operation)
            .field("has_backend_session", &self.backend_session_id.is_some())
            .field("has_document", &self.document.is_some())
            .field(
                "has_local_detection",
                &self.local_detection_phases.is_some(),
            )
            .finish_non_exhaustive()
    }
}

pub trait BackendExecutor: Send + Sync {
    fn generation(&self) -> BackendGeneration;
    fn execute(
        &self,
        call: &BackendCall,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> BackendCompletion;
    fn teardown(&self);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Role {
    Desktop,
    Extension,
}

impl Role {
    fn parse(value: &str) -> Option<Self> {
        match value {
            "desktop" => Some(Self::Desktop),
            "extension" => Some(Self::Extension),
            _ => None,
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Desktop => "desktop",
            Self::Extension => "extension",
        }
    }
}

struct RoleCounters {
    sessions: AtomicUsize,
    in_flight: AtomicUsize,
}

impl Default for RoleCounters {
    fn default() -> Self {
        Self {
            sessions: AtomicUsize::new(0),
            in_flight: AtomicUsize::new(0),
        }
    }
}

struct DataPlaneInner {
    backend: Arc<dyn BackendExecutor>,
    generation: BackendGeneration,
    backend_invalidated: AtomicBool,
    teardown_started: AtomicBool,
    in_flight: AtomicUsize,
    desktop: RoleCounters,
    extension: RoleCounters,
}

#[derive(Clone)]
pub struct DataPlane {
    inner: Arc<DataPlaneInner>,
}

impl fmt::Debug for DataPlane {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DataPlane")
            .field(
                "backend_invalidated",
                &self.inner.backend_invalidated.load(Ordering::Acquire),
            )
            .field("in_flight", &self.inner.in_flight.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DataPlaneStats {
    pub generation: BackendGeneration,
    pub backend_invalidated: bool,
    pub desktop_sessions: usize,
    pub extension_sessions: usize,
    pub in_flight: usize,
}

impl DataPlane {
    pub fn new(backend: Arc<dyn BackendExecutor>) -> Result<Self, ProtocolError> {
        let generation = backend.generation();
        if generation == BackendGeneration(0) {
            return Err(ProtocolError::new("operation_failed", None));
        }
        Ok(Self {
            inner: Arc::new(DataPlaneInner {
                backend,
                generation,
                backend_invalidated: AtomicBool::new(false),
                teardown_started: AtomicBool::new(false),
                in_flight: AtomicUsize::new(0),
                desktop: RoleCounters::default(),
                extension: RoleCounters::default(),
            }),
        })
    }

    pub fn open_connection(&self, role: &str) -> Result<DataConnection, ProtocolError> {
        let role =
            Role::parse(role).ok_or_else(|| ProtocolError::new("broker_unauthorized", None))?;
        if self.inner.backend_invalidated.load(Ordering::Acquire) {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(DataConnection {
            plane: self.clone(),
            role,
            scopes: HashMap::new(),
            sessions: HashMap::new(),
            closed: false,
        })
    }

    pub fn stats(&self) -> DataPlaneStats {
        DataPlaneStats {
            generation: self.inner.generation,
            backend_invalidated: self.inner.backend_invalidated.load(Ordering::Acquire),
            desktop_sessions: self.inner.desktop.sessions.load(Ordering::Acquire),
            extension_sessions: self.inner.extension.sessions.load(Ordering::Acquire),
            in_flight: self.inner.in_flight.load(Ordering::Acquire),
        }
    }

    fn counters(&self, role: Role) -> &RoleCounters {
        match role {
            Role::Desktop => &self.inner.desktop,
            Role::Extension => &self.inner.extension,
        }
    }

    fn reserve_session(&self, role: Role) -> Result<SessionReservation, ProtocolError> {
        let counter = &self.counters(role).sessions;
        if counter
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < MAX_SESSIONS_PER_ROLE).then_some(current + 1)
            })
            .is_err()
        {
            return Err(ProtocolError::new("broker_busy", None));
        }
        Ok(SessionReservation {
            plane: Arc::clone(&self.inner),
            role,
            committed: false,
        })
    }

    fn acquire_operation(&self, role: Role) -> Result<OperationPermit, ProtocolError> {
        if self.inner.backend_invalidated.load(Ordering::Acquire) {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        if self
            .inner
            .in_flight
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < MAX_IN_FLIGHT_OPERATIONS).then_some(current + 1)
            })
            .is_err()
        {
            return Err(ProtocolError::new("broker_busy", None));
        }
        let role_counter = &self.counters(role).in_flight;
        if role_counter
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < MAX_IN_FLIGHT_PER_ROLE).then_some(current + 1)
            })
            .is_err()
        {
            self.inner.in_flight.fetch_sub(1, Ordering::AcqRel);
            return Err(ProtocolError::new("broker_busy", None));
        }
        Ok(OperationPermit {
            plane: Arc::clone(&self.inner),
            role,
        })
    }

    fn teardown_backend(&self) {
        self.inner
            .backend_invalidated
            .store(true, Ordering::Release);
        if !self.inner.teardown_started.swap(true, Ordering::AcqRel) {
            self.inner.backend.teardown();
        }
    }
}

struct SessionReservation {
    plane: Arc<DataPlaneInner>,
    role: Role,
    committed: bool,
}

impl SessionReservation {
    fn commit(mut self) {
        self.committed = true;
    }
}

impl Drop for SessionReservation {
    fn drop(&mut self) {
        if !self.committed {
            let counter = match self.role {
                Role::Desktop => &self.plane.desktop.sessions,
                Role::Extension => &self.plane.extension.sessions,
            };
            counter.fetch_sub(1, Ordering::AcqRel);
        }
    }
}

struct OperationPermit {
    plane: Arc<DataPlaneInner>,
    role: Role,
}

pub struct PendingPublication {
    value: Value,
    permit: Option<OperationPermit>,
}

impl PendingPublication {
    fn unbounded(value: Value) -> Self {
        Self {
            value,
            permit: None,
        }
    }

    fn bounded(value: Value, permit: OperationPermit) -> Self {
        Self {
            value,
            permit: Some(permit),
        }
    }

    pub fn value(&self) -> &Value {
        &self.value
    }

    pub fn into_parts(mut self) -> (Value, PublicationLease) {
        let value = std::mem::take(&mut self.value);
        let permit = self.permit.take();
        (value, PublicationLease { permit })
    }

    fn into_result(mut self) -> Result<Value, ProtocolError> {
        self.value
            .as_object_mut()
            .and_then(|response| response.remove("result"))
            .ok_or_else(|| ProtocolError::new("operation_failed", None))
    }
}

impl fmt::Debug for PendingPublication {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PendingPublication")
            .field("bounded", &self.permit.is_some())
            .finish_non_exhaustive()
    }
}

pub struct PublicationLease {
    permit: Option<OperationPermit>,
}

impl fmt::Debug for PublicationLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PublicationLease")
            .field("bounded", &self.permit.is_some())
            .finish_non_exhaustive()
    }
}

impl Drop for OperationPermit {
    fn drop(&mut self) {
        let role = match self.role {
            Role::Desktop => &self.plane.desktop.in_flight,
            Role::Extension => &self.plane.extension.in_flight,
        };
        role.fetch_sub(1, Ordering::AcqRel);
        self.plane.in_flight.fetch_sub(1, Ordering::AcqRel);
    }
}

struct ScopeBinding {
    kind: String,
}

struct SessionBinding {
    backend_session_id: Zeroizing<String>,
    scope_id: String,
    mode: String,
    generation: BackendGeneration,
}

impl fmt::Debug for SessionBinding {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SessionBinding")
            .field("mode", &self.mode)
            .field("generation", &self.generation)
            .finish_non_exhaustive()
    }
}

pub struct DataConnection {
    plane: DataPlane,
    role: Role,
    scopes: HashMap<String, ScopeBinding>,
    sessions: HashMap<String, SessionBinding>,
    closed: bool,
}

impl fmt::Debug for DataConnection {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DataConnection")
            .field("role", &self.role)
            .field("scope_count", &self.scopes.len())
            .field("session_count", &self.sessions.len())
            .field("closed", &self.closed)
            .finish_non_exhaustive()
    }
}

impl DataConnection {
    pub fn dispatch(
        &mut self,
        request: &BrokerRequest,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Value, ProtocolError> {
        let deadline_ms = request
            .deadline_ms
            .filter(|value| *value > 0)
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request.request_id)))?;
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(deadline_ms))
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request.request_id)))?;
        self.dispatch_for_publication_until(request, deadline, cancelled)?
            .into_result()
    }

    pub fn dispatch_for_publication(
        &mut self,
        request: &BrokerRequest,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<PendingPublication, ProtocolError> {
        let deadline_ms = request
            .deadline_ms
            .filter(|value| *value > 0)
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request.request_id)))?;
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(deadline_ms))
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request.request_id)))?;
        self.dispatch_for_publication_until(request, deadline, cancelled)
    }

    pub fn dispatch_until(
        &mut self,
        request: &BrokerRequest,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Value, ProtocolError> {
        self.dispatch_for_publication_until(request, deadline, cancelled)?
            .into_result()
    }

    pub fn dispatch_for_publication_until(
        &mut self,
        request: &BrokerRequest,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<PendingPublication, ProtocolError> {
        if self.closed {
            return Err(ProtocolError::new(
                "broker_unavailable",
                Some(&request.request_id),
            ));
        }
        let kind = operation_kind(&request.operation, &request.payload)
            .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request.request_id)))?;
        if !operation_allowed(self.role.as_str(), &request.operation) {
            return Err(ProtocolError::new(
                "broker_unauthorized",
                Some(&request.request_id),
            ));
        }
        self.sync_generation();
        if self.plane.inner.backend_invalidated.load(Ordering::Acquire) {
            let code = if matches!(
                kind,
                OperationKind::SessionMutation | OperationKind::TerminalSession
            ) {
                "session_unavailable"
            } else {
                "broker_unavailable"
            };
            return Err(ProtocolError::new(code, Some(&request.request_id)));
        }
        if cancelled() {
            return Err(ProtocolError::new(
                "operation_timeout",
                Some(&request.request_id),
            ));
        }
        if deadline <= Instant::now() {
            return Err(ProtocolError::new(
                "operation_timeout",
                Some(&request.request_id),
            ));
        }
        match kind {
            OperationKind::ConnectionState if request.operation == "scope_open" => {
                let result = self.scope_open(request)?;
                self.unbounded_publication(request, result)
            }
            OperationKind::TerminalScope => {
                let result = self.scope_close(request, deadline, cancelled)?;
                self.unbounded_publication(request, result)
            }
            OperationKind::TerminalSession => {
                let result = self.session_dispose(request, deadline, cancelled)?;
                self.unbounded_publication(request, result)
            }
            OperationKind::Stateless
            | OperationKind::SessionCreate
            | OperationKind::SessionMutation
            | OperationKind::TransientMapping => self.forward(request, kind, deadline, cancelled),
            _ => Err(ProtocolError::new(
                "operation_failed",
                Some(&request.request_id),
            )),
        }
    }

    fn unbounded_publication(
        &self,
        request: &BrokerRequest,
        result: Value,
    ) -> Result<PendingPublication, ProtocolError> {
        let response = success_message(
            &request.operation,
            &request.request_id,
            result,
            self.role.as_str(),
            request.protocol_version,
        )?;
        Ok(PendingPublication::unbounded(response))
    }

    pub fn close(&mut self) -> Result<(), ProtocolError> {
        if self.closed {
            return Ok(());
        }
        self.closed = true;
        self.scopes.clear();
        let sessions = self.take_all_sessions();
        if sessions.is_empty() || self.plane.inner.backend_invalidated.load(Ordering::Acquire) {
            return Ok(());
        }
        let deadline = Instant::now()
            .checked_add(DISPOSAL_BUDGET)
            .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
        for binding in sessions {
            if self
                .dispose_backend_binding(binding, deadline, &|| false)
                .is_err()
            {
                self.plane.teardown_backend();
                return Err(ProtocolError::new("operation_failed", None));
            }
        }
        Ok(())
    }

    fn scope_open(&mut self, request: &BrokerRequest) -> Result<Value, ProtocolError> {
        if request.scope_id.is_some() || self.scopes.len() >= MAX_SCOPES_PER_CONNECTION {
            let code = if self.scopes.len() >= MAX_SCOPES_PER_CONNECTION {
                "broker_busy"
            } else {
                "request_invalid"
            };
            return Err(ProtocolError::new(code, Some(&request.request_id)));
        }
        let payload = object(&request.payload, &["scope_kind"])?;
        let scope_kind = string(&payload["scope_kind"])?;
        let allowed = match self.role {
            Role::Desktop => matches!(scope_kind, "desktop_ui" | "desktop_hotkey"),
            Role::Extension => matches!(scope_kind, "extension_tab" | "extension_panel"),
        };
        if !allowed {
            return Err(ProtocolError::new(
                "broker_unauthorized",
                Some(&request.request_id),
            ));
        }
        let scope_id = unique_handle("scope", &self.scopes)?;
        self.scopes.insert(
            scope_id.clone(),
            ScopeBinding {
                kind: scope_kind.to_owned(),
            },
        );
        Ok(serde_json::json!({"scope_id": scope_id}))
    }

    fn scope_close(
        &mut self,
        request: &BrokerRequest,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Value, ProtocolError> {
        let scope_id = self.required_scope(request)?;
        if self.scopes.remove(scope_id).is_none() {
            return Err(ProtocolError::new(
                "broker_unauthorized",
                Some(&request.request_id),
            ));
        }
        let handles: Vec<String> = self
            .sessions
            .iter()
            .filter_map(|(handle, binding)| {
                (binding.scope_id == scope_id).then_some(handle.clone())
            })
            .collect();
        let bindings: Vec<SessionBinding> = handles
            .into_iter()
            .filter_map(|handle| self.remove_session(&handle))
            .collect();
        for binding in bindings {
            if let Err(error) = self.dispose_backend_binding(binding, deadline, cancelled) {
                self.plane.teardown_backend();
                let code = if terminal_cleanup_timed_out(&error, deadline, cancelled) {
                    "operation_timeout"
                } else {
                    "operation_failed"
                };
                return Err(ProtocolError::new(code, Some(&request.request_id)));
            }
        }
        if cancelled() || deadline <= Instant::now() {
            return Err(ProtocolError::new(
                "operation_timeout",
                Some(&request.request_id),
            ));
        }
        Ok(serde_json::json!({"closed": true}))
    }

    fn session_dispose(
        &mut self,
        request: &BrokerRequest,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Value, ProtocolError> {
        let scope_id = self.required_live_scope(request)?;
        let payload = object(&request.payload, &["session_id"])?;
        let handle = string(&payload["session_id"])?;
        let binding = self
            .sessions
            .get(handle)
            .filter(|binding| binding.scope_id == scope_id)
            .ok_or_else(|| ProtocolError::new("session_unavailable", Some(&request.request_id)))?;
        if binding.generation != self.plane.inner.generation {
            self.remove_session(handle);
            return Err(ProtocolError::new(
                "session_unavailable",
                Some(&request.request_id),
            ));
        }
        let binding = self.remove_session(handle).expect("checked above");
        match self.dispose_backend_binding(binding, deadline, cancelled) {
            Ok(_) if cancelled() || deadline <= Instant::now() => Err(ProtocolError::new(
                "operation_timeout",
                Some(&request.request_id),
            )),
            Ok(disposed) => Ok(serde_json::json!({"disposed": disposed})),
            Err(error) => {
                self.plane.teardown_backend();
                let code = if terminal_cleanup_timed_out(&error, deadline, cancelled) {
                    "operation_timeout"
                } else {
                    error.code()
                };
                Err(ProtocolError::new(code, Some(&request.request_id)))
            }
        }
    }

    fn forward(
        &mut self,
        request: &BrokerRequest,
        kind: OperationKind,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<PendingPublication, ProtocolError> {
        let scope_id = self.required_live_scope(request)?.to_owned();
        let mut existing_handle = None;
        let mut existing_backend_id = None;
        let mut new_reservation = None;
        let mut pending_handle = None;
        if kind == OperationKind::SessionCreate {
            if self.sessions.len() >= MAX_SESSIONS_PER_CONNECTION {
                return Err(ProtocolError::new("broker_busy", Some(&request.request_id)));
            }
            new_reservation =
                Some(self.plane.reserve_session(self.role).map_err(|error| {
                    ProtocolError::new(error.code(), Some(&request.request_id))
                })?);
            pending_handle = Some(unique_handle("session", &self.sessions)?);
        } else if kind == OperationKind::SessionMutation {
            let payload = request
                .payload
                .as_object()
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request.request_id)))?;
            let handle = payload
                .get("session_id")
                .and_then(Value::as_str)
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request.request_id)))?;
            let binding = self
                .sessions
                .get(handle)
                .filter(|binding| {
                    binding.scope_id == scope_id
                        && binding.generation == self.plane.inner.generation
                })
                .ok_or_else(|| {
                    ProtocolError::new("session_unavailable", Some(&request.request_id))
                })?;
            if request.operation == "sanitize" {
                if let Some(mode) = payload.get("mode").and_then(Value::as_str) {
                    if mode != binding.mode {
                        return Err(ProtocolError::new(
                            "request_invalid",
                            Some(&request.request_id),
                        ));
                    }
                }
            }
            existing_handle = Some(handle.to_owned());
            existing_backend_id = Some(binding.backend_session_id.to_string());
        }

        let call = build_backend_call(request, existing_backend_id.as_deref())?;
        let permit = self
            .plane
            .acquire_operation(self.role)
            .map_err(|error| ProtocolError::new(error.code(), Some(&request.request_id)))?;
        let completion = self.plane.inner.backend.execute(&call, deadline, cancelled);

        match completion {
            BackendCompletion::NotSubmitted(reason) => {
                if reason == BackendFailure::BackendDied {
                    self.plane.teardown_backend();
                }
                Err(ProtocolError::new(
                    failure_code(reason),
                    Some(&request.request_id),
                ))
            }
            BackendCompletion::Unknown(reason) => {
                self.handle_unknown(
                    request,
                    kind,
                    existing_handle.as_deref(),
                    reason,
                    deadline,
                    cancelled,
                );
                Err(ProtocolError::new(
                    failure_code(reason),
                    Some(&request.request_id),
                ))
            }
            BackendCompletion::ConfirmedTooLarge => {
                self.handle_oversized_response(
                    kind,
                    existing_handle.as_deref(),
                    deadline,
                    cancelled,
                );
                let code = if cancelled() || deadline <= Instant::now() {
                    "operation_timeout"
                } else {
                    "payload_too_large"
                };
                Err(ProtocolError::new(code, Some(&request.request_id)))
            }
            BackendCompletion::Confirmed(reply) => {
                let projected = match validate_backend_reply(request, &call, reply) {
                    Ok(BackendProjection::Success(result)) => result,
                    Ok(BackendProjection::Failure(failure)) => {
                        if failure.integrity_failure {
                            self.plane.teardown_backend();
                        } else if failure.uncertain {
                            self.handle_unknown(
                                request,
                                kind,
                                existing_handle.as_deref(),
                                BackendFailure::Transport,
                                deadline,
                                cancelled,
                            );
                        } else if failure.code == "session_unavailable" {
                            if let Some(handle) = existing_handle.as_deref() {
                                self.remove_session(handle);
                            }
                        }
                        let code = if cancelled() || deadline <= Instant::now() {
                            "operation_timeout"
                        } else {
                            failure.code
                        };
                        return Err(ProtocolError::new(code, Some(&request.request_id)));
                    }
                    Err(error) => {
                        self.handle_invalid_success(
                            request,
                            kind,
                            existing_handle.as_deref(),
                            None,
                            deadline,
                            cancelled,
                        );
                        let code = if cancelled() || deadline <= Instant::now() {
                            "operation_timeout"
                        } else {
                            error.code()
                        };
                        return Err(ProtocolError::new(code, Some(&request.request_id)));
                    }
                };
                let value = self.publish_success(
                    request,
                    kind,
                    &scope_id,
                    existing_handle.as_deref(),
                    new_reservation.take(),
                    pending_handle,
                    projected,
                    deadline,
                    cancelled,
                )?;
                Ok(PendingPublication::bounded(value, permit))
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn publish_success(
        &mut self,
        request: &BrokerRequest,
        kind: OperationKind,
        scope_id: &str,
        existing_handle: Option<&str>,
        reservation: Option<SessionReservation>,
        pending_handle: Option<String>,
        mut result: Value,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<Value, ProtocolError> {
        if self.plane.inner.backend_invalidated.load(Ordering::Acquire) {
            self.sync_generation();
            let code = if kind == OperationKind::SessionMutation {
                "session_unavailable"
            } else {
                "broker_unavailable"
            };
            return Err(ProtocolError::new(code, Some(&request.request_id)));
        }
        let mut new_backend_id = None;
        if request.operation == "sanitize" {
            let backend_id = result
                .as_object()
                .and_then(|result| result.get("session_id"))
                .and_then(Value::as_str)
                .filter(|value| valid_backend_session_id(value))
                .map(str::to_owned);
            let Some(backend_id) = backend_id else {
                self.handle_invalid_success(
                    request,
                    kind,
                    existing_handle,
                    None,
                    deadline,
                    cancelled,
                );
                return Err(ProtocolError::new(
                    "operation_failed",
                    Some(&request.request_id),
                ));
            };
            if kind == OperationKind::SessionMutation {
                let handle = existing_handle.expect("session mutation checked above");
                let expected = self
                    .sessions
                    .get(handle)
                    .map(|binding| binding.backend_session_id.as_str());
                if expected != Some(backend_id.as_str()) {
                    self.plane.teardown_backend();
                    return Err(ProtocolError::new(
                        "operation_failed",
                        Some(&request.request_id),
                    ));
                }
                result["session_id"] = Value::String(handle.to_owned());
            } else {
                let Some(handle) = pending_handle else {
                    self.handle_invalid_success(
                        request,
                        kind,
                        existing_handle,
                        Some(&backend_id),
                        deadline,
                        cancelled,
                    );
                    return Err(ProtocolError::new(
                        "operation_failed",
                        Some(&request.request_id),
                    ));
                };
                result["session_id"] = Value::String(handle.clone());
                new_backend_id = Some((handle, backend_id));
            }
        }

        if cancelled() || deadline <= Instant::now() {
            match kind {
                OperationKind::SessionCreate => self.handle_invalid_success(
                    request,
                    kind,
                    existing_handle,
                    new_backend_id.as_ref().map(|(_, value)| value.as_str()),
                    deadline,
                    cancelled,
                ),
                OperationKind::SessionMutation => self.handle_unknown(
                    request,
                    kind,
                    existing_handle,
                    BackendFailure::Cancelled,
                    deadline,
                    cancelled,
                ),
                OperationKind::Stateless | OperationKind::TransientMapping => {}
                _ => self.plane.teardown_backend(),
            }
            return Err(ProtocolError::new(
                "operation_timeout",
                Some(&request.request_id),
            ));
        }

        let response = match success_message(
            &request.operation,
            &request.request_id,
            result,
            self.role.as_str(),
            request.protocol_version,
        ) {
            Ok(response) => response,
            Err(error) => {
                self.handle_invalid_success(
                    request,
                    kind,
                    existing_handle,
                    new_backend_id.as_ref().map(|(_, value)| value.as_str()),
                    deadline,
                    cancelled,
                );
                return Err(ProtocolError::new(error.code(), Some(&request.request_id)));
            }
        };

        if let Some((handle, backend_id)) = new_backend_id {
            let mode = request
                .payload
                .get("mode")
                .and_then(Value::as_str)
                .unwrap_or("token")
                .to_owned();
            self.sessions.insert(
                handle,
                SessionBinding {
                    backend_session_id: Zeroizing::new(backend_id),
                    scope_id: scope_id.to_owned(),
                    mode,
                    generation: self.plane.inner.generation,
                },
            );
            reservation.expect("new session has reservation").commit();
        }
        Ok(response)
    }

    fn handle_unknown(
        &mut self,
        request: &BrokerRequest,
        kind: OperationKind,
        existing_handle: Option<&str>,
        reason: BackendFailure,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) {
        if reason == BackendFailure::BackendDied {
            self.plane.teardown_backend();
            return;
        }
        match kind {
            OperationKind::SessionCreate | OperationKind::TransientMapping => {
                self.plane.teardown_backend();
            }
            OperationKind::SessionMutation => {
                let Some(handle) = existing_handle else {
                    self.plane.teardown_backend();
                    return;
                };
                let Some(binding) = self.remove_session(handle) else {
                    self.plane.teardown_backend();
                    return;
                };
                let cleanup_deadline = if deadline > Instant::now() {
                    deadline
                } else {
                    Instant::now()
                        .checked_add(DISPOSAL_BUDGET)
                        .unwrap_or_else(Instant::now)
                };
                if self
                    .dispose_backend_binding(binding, cleanup_deadline, cancelled)
                    .is_err()
                {
                    self.plane.teardown_backend();
                }
            }
            OperationKind::Stateless => self.plane.teardown_backend(),
            _ => {
                let _ = request;
                self.plane.teardown_backend();
            }
        }
    }

    fn handle_oversized_response(
        &mut self,
        kind: OperationKind,
        existing_handle: Option<&str>,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) {
        match kind {
            OperationKind::SessionCreate => self.plane.teardown_backend(),
            OperationKind::SessionMutation => {
                let Some(handle) = existing_handle else {
                    self.plane.teardown_backend();
                    return;
                };
                let Some(binding) = self.remove_session(handle) else {
                    self.plane.teardown_backend();
                    return;
                };
                let cleanup_deadline = if deadline > Instant::now() {
                    deadline
                } else {
                    Instant::now()
                        .checked_add(DISPOSAL_BUDGET)
                        .unwrap_or_else(Instant::now)
                };
                if self
                    .dispose_backend_binding(binding, cleanup_deadline, cancelled)
                    .is_err()
                {
                    self.plane.teardown_backend();
                }
            }
            OperationKind::Stateless | OperationKind::TransientMapping => {}
            _ => self.plane.teardown_backend(),
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn handle_invalid_success(
        &mut self,
        request: &BrokerRequest,
        kind: OperationKind,
        existing_handle: Option<&str>,
        new_backend_id: Option<&str>,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) {
        match kind {
            OperationKind::SessionCreate => {
                if let Some(backend_id) = new_backend_id {
                    let binding = SessionBinding {
                        backend_session_id: Zeroizing::new(backend_id.to_owned()),
                        scope_id: String::new(),
                        mode: String::new(),
                        generation: self.plane.inner.generation,
                    };
                    if self
                        .dispose_backend_binding(binding, deadline, cancelled)
                        .is_err()
                    {
                        self.plane.teardown_backend();
                    }
                } else {
                    self.plane.teardown_backend();
                }
            }
            OperationKind::SessionMutation => self.handle_unknown(
                request,
                kind,
                existing_handle,
                BackendFailure::Transport,
                deadline,
                cancelled,
            ),
            OperationKind::TransientMapping => self.plane.teardown_backend(),
            OperationKind::Stateless => self.plane.teardown_backend(),
            _ => self.plane.teardown_backend(),
        }
    }

    fn dispose_backend_binding(
        &self,
        binding: SessionBinding,
        deadline: Instant,
        cancelled: &dyn Fn() -> bool,
    ) -> Result<bool, ProtocolError> {
        if self.plane.inner.backend_invalidated.load(Ordering::Acquire)
            || binding.generation != self.plane.inner.generation
        {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let call = BackendCall {
            operation: "session_dispose".to_owned(),
            payload: serde_json::json!({}),
            backend_session_id: Some(binding.backend_session_id),
            document: None,
            local_detection_phases: Some(0),
            local_intermediate_text_chars: None,
        };
        let _permit = self.plane.acquire_operation(self.role)?;
        let completion = self.plane.inner.backend.execute(&call, deadline, cancelled);
        match completion {
            BackendCompletion::Confirmed(reply) => {
                let request = BrokerRequest {
                    protocol_version: 1,
                    request_id: "cleanup".to_owned(),
                    operation: "session_dispose".to_owned(),
                    scope_id: Some("cleanup".to_owned()),
                    payload: serde_json::json!({"session_id": "cleanup"}),
                    deadline_ms: Some(60_000),
                    local_detection_phases: Some(0),
                    local_intermediate_text_chars: None,
                    remote_tner_max_calls: 0,
                    remote_tner_text_chars: None,
                    replay: "never".to_owned(),
                    uncertain_completion: "known_session_mutation".to_owned(),
                };
                match validate_backend_reply(&request, &call, reply)? {
                    BackendProjection::Success(result) => result["disposed"]
                        .as_bool()
                        .ok_or_else(|| ProtocolError::new("operation_failed", None)),
                    BackendProjection::Failure(failure)
                        if failure.code == "session_unavailable"
                            && !failure.integrity_failure
                            && !failure.uncertain =>
                    {
                        Ok(false)
                    }
                    BackendProjection::Failure(_) => {
                        Err(ProtocolError::new("operation_failed", None))
                    }
                }
            }
            BackendCompletion::ConfirmedTooLarge => {
                Err(ProtocolError::new("payload_too_large", None))
            }
            BackendCompletion::NotSubmitted(reason) | BackendCompletion::Unknown(reason) => {
                Err(ProtocolError::new(failure_code(reason), None))
            }
        }
    }

    fn required_scope<'a>(&self, request: &'a BrokerRequest) -> Result<&'a str, ProtocolError> {
        request
            .scope_id
            .as_deref()
            .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request.request_id)))
    }

    fn required_live_scope<'a>(
        &self,
        request: &'a BrokerRequest,
    ) -> Result<&'a str, ProtocolError> {
        let scope_id = self.required_scope(request)?;
        let binding = self
            .scopes
            .get(scope_id)
            .ok_or_else(|| ProtocolError::new("broker_unauthorized", Some(&request.request_id)))?;
        let _ = &binding.kind;
        Ok(scope_id)
    }

    fn remove_session(&mut self, handle: &str) -> Option<SessionBinding> {
        let binding = self.sessions.remove(handle)?;
        self.plane
            .counters(self.role)
            .sessions
            .fetch_sub(1, Ordering::AcqRel);
        Some(binding)
    }

    fn take_all_sessions(&mut self) -> Vec<SessionBinding> {
        let count = self.sessions.len();
        let sessions = self.sessions.drain().map(|(_, binding)| binding).collect();
        if count > 0 {
            self.plane
                .counters(self.role)
                .sessions
                .fetch_sub(count, Ordering::AcqRel);
        }
        sessions
    }

    fn sync_generation(&mut self) {
        if self.plane.inner.backend_invalidated.load(Ordering::Acquire) {
            self.take_all_sessions();
        }
    }
}

impl Drop for DataConnection {
    fn drop(&mut self) {
        let _ = self.close();
    }
}

fn build_backend_call(
    request: &BrokerRequest,
    backend_session_id: Option<&str>,
) -> Result<BackendCall, ProtocolError> {
    let mut payload = request.payload.clone();
    let mut document = None;
    if let Some(backend_session_id) = backend_session_id {
        payload["session_id"] = Value::String(backend_session_id.to_owned());
    }
    if request.operation == "redact_pdf" {
        let encoded = payload
            .get("pdf_b64")
            .and_then(Value::as_str)
            .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request.request_id)))?;
        let decoded = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|_| ProtocolError::new("request_invalid", Some(&request.request_id)))?;
        let contract: Value = serde_json::from_str(crate::CONTRACT_JSON)
            .map_err(|_| ProtocolError::new("operation_failed", Some(&request.request_id)))?;
        let maximum = contract["framing"]["max_pdf_raw_bytes"]
            .as_u64()
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request.request_id)))?
            as usize;
        if decoded.len() > maximum {
            return Err(ProtocolError::new(
                "payload_too_large",
                Some(&request.request_id),
            ));
        }
        document = Some(Zeroizing::new(decoded));
        payload = serde_json::json!({});
    }
    Ok(BackendCall {
        operation: request.operation.clone(),
        payload,
        backend_session_id: backend_session_id.map(|value| Zeroizing::new(value.to_owned())),
        document,
        local_detection_phases: request.local_detection_phases,
        local_intermediate_text_chars: request.local_intermediate_text_chars,
    })
}

enum BackendProjection {
    Success(Value),
    Failure(BackendErrorProjection),
}

struct BackendErrorProjection {
    code: &'static str,
    integrity_failure: bool,
    uncertain: bool,
}

fn validate_backend_reply(
    request: &BrokerRequest,
    call: &BackendCall,
    reply: BackendReply,
) -> Result<BackendProjection, ProtocolError> {
    if reply.contract_version.as_deref() != Some("2")
        || reply.content_type.as_deref() != Some("application/json")
    {
        return Ok(BackendProjection::Failure(BackendErrorProjection {
            code: "operation_failed",
            integrity_failure: true,
            uncertain: false,
        }));
    }
    if reply.status == 200 {
        let result = validate_http_success(&request.operation, call, reply.body)?;
        return Ok(BackendProjection::Success(result));
    }
    validate_http_error(reply.status, &reply.body, &request.operation)
        .map(BackendProjection::Failure)
}

fn validate_http_error(
    status: u16,
    body: &Value,
    operation: &str,
) -> Result<BackendErrorProjection, ProtocolError> {
    let envelope = object(body, &["error"])?;
    let error = object(
        &envelope["error"],
        &["code", "category", "count", "retryable", "status"],
    )?;
    let code = string(&error["code"])?;
    let category = string(&error["category"])?;
    let count = nonnegative_integer(&error["count"])?;
    let retryable = boolean(&error["retryable"])?;
    if nonnegative_integer(&error["status"])? != status as u64 {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let counted = matches!(
        code,
        "request_schema_invalid" | "residual_pii" | "ner_incomplete" | "ner_unavailable"
    );
    if !counted && count != 0 {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let expected = match code {
        "contract_version_required" => (426, "contract", false),
        "invalid_request" => (400, "request", false),
        "request_schema_invalid" => (422, "request", false),
        "authentication_required" => (401, "authentication", false),
        "control_forbidden" => (403, "authentication", false),
        "route_not_found" => (404, "request", false),
        "session_unavailable" => (404, "session", false),
        "method_not_allowed" => (405, "request", false),
        "rate_limited" => (429, "service", true),
        "payload_too_large" => (413, "request", false),
        "residual_pii" => (422, "privacy", false),
        "document_invalid" => (422, "document", false),
        "provider_unavailable" => (502, "upstream", true),
        "provider_rejected" | "provider_response_invalid" | "ner_incomplete" => {
            (502, "upstream", false)
        }
        "provider_configuration" => (503, "configuration", false),
        "dependency_unavailable" | "ocr_unavailable" => (503, "dependency", false),
        "ner_unavailable" => {
            if !matches!(
                category,
                "configuration" | "dependency" | "network" | "upstream"
            ) {
                return Err(ProtocolError::new("operation_failed", None));
            }
            (503, category, matches!(category, "network" | "upstream"))
        }
        "service_unavailable" => (503, "service", true),
        "restore_failed" | "internal_error" => (500, "internal", false),
        _ => return Err(ProtocolError::new("operation_failed", None)),
    };
    if (status, category, retryable) != expected {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let integrity_failure = matches!(
        code,
        "contract_version_required"
            | "authentication_required"
            | "control_forbidden"
            | "route_not_found"
            | "method_not_allowed"
    );
    let uncertain = (matches!(
        operation,
        "sanitize" | "reidentify" | "session_dispose" | "roundtrip"
    ) && matches!(code, "internal_error" | "service_unavailable"))
        || (operation == "reidentify" && code == "restore_failed");
    let projected: &'static str = match code {
        "invalid_request" | "request_schema_invalid" => "request_invalid",
        "payload_too_large" => "payload_too_large",
        "residual_pii" => "residual_pii",
        "document_invalid" => "document_invalid",
        "session_unavailable" => "session_unavailable",
        "provider_unavailable" => "provider_unavailable",
        "provider_rejected" => "provider_rejected",
        "provider_response_invalid" => "provider_response_invalid",
        "provider_configuration" => "provider_configuration",
        "dependency_unavailable" => "dependency_unavailable",
        "ocr_unavailable" => "ocr_unavailable",
        "ner_unavailable" => "ner_unavailable",
        "ner_incomplete" => "ner_incomplete",
        "restore_failed" => "restore_failed",
        _ => "operation_failed",
    };
    Ok(BackendErrorProjection {
        code: projected,
        integrity_failure,
        uncertain,
    })
}

fn validate_http_success(
    operation: &str,
    call: &BackendCall,
    body: Value,
) -> Result<Value, ProtocolError> {
    match operation {
        "detect" => validate_detect(body, call),
        "sanitize" => validate_sanitize(body),
        "reidentify" => validate_reidentify(body),
        "guard" => validate_guard(body),
        "roundtrip" => validate_roundtrip(body, call),
        "analyze" => validate_analyze(body),
        "analyze_report" => validate_analyze_report(body),
        "redact_pdf" => validate_redact_pdf(body),
        "audit_log" => validate_audit_log(body),
        "session_dispose" => validate_disposal(body),
        _ => Err(ProtocolError::new("operation_failed", None)),
    }
}

fn validate_detect(body: Value, call: &BackendCall) -> Result<Value, ProtocolError> {
    let object = object_owned(
        body,
        &["detected_entity_count", "entity_type_counts", "highlights"],
    )?;
    let detected = nonnegative_integer(&object["detected_entity_count"])?;
    let counts = validate_count_map(&object["entity_type_counts"])?;
    let source_len = call
        .payload()
        .get("text")
        .and_then(Value::as_str)
        .map(str::chars)
        .map(Iterator::count)
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let highlights = validate_highlights(&object["highlights"], source_len)?;
    if detected != count_total(&counts)? || detected != highlights.len() as u64 {
        return Err(ProtocolError::new("operation_failed", None));
    }
    Ok(Value::Object(object))
}

fn validate_sanitize(body: Value) -> Result<Value, ProtocolError> {
    let object = object_owned(
        body,
        &[
            "session_id",
            "sanitized_text",
            "detected_entity_count",
            "replacement_count",
            "entity_type_counts",
            "highlights",
            "section26_categories",
            "guard_findings",
            "warnings",
            "safety",
        ],
    )?;
    nonempty_string(&object["session_id"])?;
    let sanitized = nonempty_string(&object["sanitized_text"])?;
    let detected = nonnegative_integer(&object["detected_entity_count"])?;
    let replacements = nonnegative_integer(&object["replacement_count"])?;
    let counts = validate_count_map(&object["entity_type_counts"])?;
    let highlights = validate_highlights(&object["highlights"], sanitized.chars().count())?;
    validate_section26(&object["section26_categories"])?;
    validate_guard_findings(&object["guard_findings"])?;
    if object["warnings"]
        .as_array()
        .is_none_or(|values| !values.is_empty())
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    validate_safety(&object["safety"])?;
    if detected != count_total(&counts)?
        || replacements != highlights.len() as u64
        || replacements < detected
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    Ok(Value::Object(object))
}

fn validate_reidentify(body: Value) -> Result<Value, ProtocolError> {
    let object = object_owned(
        body,
        &[
            "restored_text",
            "replaced_count",
            "leftover_count",
            "warnings",
        ],
    )?;
    string(&object["restored_text"])?;
    nonnegative_integer(&object["replaced_count"])?;
    nonnegative_integer(&object["leftover_count"])?;
    validate_warnings(
        &object["warnings"],
        &["generated_pii", "foreign_replacement"],
    )?;
    Ok(Value::Object(object))
}

fn validate_guard(body: Value) -> Result<Value, ProtocolError> {
    let object = object_owned(body, &["flagged", "guard_findings"])?;
    let findings = validate_guard_findings(&object["guard_findings"])?;
    if boolean(&object["flagged"])? != !findings.is_empty() {
        return Err(ProtocolError::new("operation_failed", None));
    }
    Ok(Value::Object(object))
}

fn validate_roundtrip(body: Value, call: &BackendCall) -> Result<Value, ProtocolError> {
    let object = object_owned(
        body,
        &[
            "sanitized_text",
            "ai_response_masked",
            "restored_text",
            "detected_entity_count",
            "entity_type_counts",
            "provider_used",
            "section26_categories",
            "guard_findings",
            "warnings",
            "safety",
            "restoration",
        ],
    )?;
    nonempty_string(&object["sanitized_text"])?;
    string(&object["ai_response_masked"])?;
    string(&object["restored_text"])?;
    let detected = nonnegative_integer(&object["detected_entity_count"])?;
    let counts = validate_count_map(&object["entity_type_counts"])?;
    if detected != count_total(&counts)? {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let provider = nonempty_string(&object["provider_used"])?;
    if call.payload()["provider"].as_str() != Some(provider) {
        return Err(ProtocolError::new("operation_failed", None));
    }
    validate_section26(&object["section26_categories"])?;
    validate_guard_findings(&object["guard_findings"])?;
    let warnings = validate_warnings(
        &object["warnings"],
        &["generated_pii", "foreign_replacement"],
    )?;
    validate_safety(&object["safety"])?;
    let restoration = object_ref(
        &object["restoration"],
        &["status", "replaced_count", "leftover_count"],
    )?;
    let status = string(&restoration["status"])?;
    let replaced = nonnegative_integer(&restoration["replaced_count"])?;
    let leftover = nonnegative_integer(&restoration["leftover_count"])?;
    let _ = replaced;
    let expected = if !warnings.is_empty() {
        "unsafe"
    } else if leftover > 0 {
        "incomplete"
    } else {
        "complete"
    };
    if status != expected {
        return Err(ProtocolError::new("operation_failed", None));
    }
    Ok(Value::Object(object))
}

fn validate_analyze(body: Value) -> Result<Value, ProtocolError> {
    let mut object = object_owned(
        body,
        &[
            "overall_score",
            "overall_grade",
            "risk_label",
            "direct_pii_count",
            "fp_count",
            "tb_count",
            "section26_categories",
            "reidentification",
            "breakdown",
            "recommendations",
        ],
    )?;
    let overall_score = bounded_decimal(&object["overall_score"], "100")?;
    object.insert(
        "overall_score".to_owned(),
        Value::String(overall_score.clone()),
    );
    enum_string(&object["overall_grade"], &["A", "B", "C", "D", "F"])?;
    enum_string(
        &object["risk_label"],
        &[
            "Very Low Risk",
            "Low Risk",
            "Medium Risk",
            "High Risk",
            "Very High Risk",
        ],
    )?;
    let direct = nonnegative_integer(&object["direct_pii_count"])?;
    let fp = nonnegative_integer(&object["fp_count"])?;
    let tb = nonnegative_integer(&object["tb_count"])?;
    if direct != fp.checked_add(tb).ok_or_else(failed)? {
        return Err(failed());
    }
    let has_section26 = !validate_section26(&object["section26_categories"])?.is_empty();
    let mut reidentification = object["reidentification"]
        .as_object()
        .cloned()
        .ok_or_else(failed)?;
    exact_keys(
        &reidentification,
        &[
            "score",
            "grade",
            "quasi_identifier_categories",
            "high_risk_combination",
        ],
    )?;
    let reid_score = bounded_decimal(&reidentification["score"], "100")?;
    reidentification.insert("score".to_owned(), Value::String(reid_score));
    enum_string(&reidentification["grade"], &["A", "B", "C", "D", "F"])?;
    validate_ordered_strings(
        &reidentification["quasi_identifier_categories"],
        &[
            "gender",
            "date_of_birth",
            "age",
            "district",
            "province",
            "occupation",
            "religion",
        ],
    )?;
    let high_risk = boolean(&reidentification["high_risk_combination"])?;
    object.insert(
        "reidentification".to_owned(),
        Value::Object(reidentification),
    );

    let breakdown = object["breakdown"].as_array().ok_or_else(failed)?;
    let mut seen = HashSet::new();
    let mut fp_total = 0_u64;
    let mut tb_total = 0_u64;
    for item in breakdown {
        let item = object_ref(item, &["data_type", "redact_type", "count"])?;
        let data_type = string(&item["data_type"])?;
        if !valid_data_type(data_type) {
            return Err(failed());
        }
        let redact_type = enum_string(&item["redact_type"], &["FP", "TB"])?;
        let count = positive_integer(&item["count"])?;
        if !seen.insert((data_type, redact_type)) {
            return Err(failed());
        }
        if redact_type == "FP" {
            fp_total = fp_total.checked_add(count).ok_or_else(failed)?;
        } else {
            tb_total = tb_total.checked_add(count).ok_or_else(failed)?;
        }
    }
    if fp != fp_total || tb != tb_total {
        return Err(failed());
    }
    validate_recommendations(
        &object["recommendations"],
        direct > 0,
        has_section26,
        high_risk,
        decimal_at_least(&overall_score, "60")?,
    )?;
    Ok(Value::Object(object))
}

fn validate_analyze_report(body: Value) -> Result<Value, ProtocolError> {
    let mut object = object_owned(body, &["report_pdf_b64", "overall_score", "overall_grade"])?;
    string(&object["report_pdf_b64"])?;
    let score = bounded_decimal(&object["overall_score"], "100")?;
    object.insert("overall_score".to_owned(), Value::String(score));
    enum_string(&object["overall_grade"], &["A", "B", "C", "D", "F"])?;
    Ok(Value::Object(object))
}

fn validate_redact_pdf(body: Value) -> Result<Value, ProtocolError> {
    let mut object = object_owned(
        body,
        &[
            "source_type",
            "ocr_confidence",
            "human_review",
            "warnings",
            "detected_entity_count",
            "entity_type_counts",
            "fields",
            "section26_categories",
            "redacted_pdf_b64",
            "after_png_b64",
        ],
    )?;
    enum_string(&object["source_type"], &["pdf_text", "pdf_hybrid"])?;
    if !object["ocr_confidence"].is_null() {
        let confidence = bounded_decimal(&object["ocr_confidence"], "1")?;
        object.insert("ocr_confidence".to_owned(), Value::String(confidence));
    }
    boolean(&object["human_review"])?;
    validate_warnings(
        &object["warnings"],
        &["ocr_low_confidence", "human_review_required"],
    )?;
    let detected = nonnegative_integer(&object["detected_entity_count"])?;
    let counts = validate_count_map(&object["entity_type_counts"])?;
    if detected != count_total(&counts)? {
        return Err(failed());
    }
    let fields = object["fields"].as_array().ok_or_else(failed)?;
    let mut seen = HashSet::new();
    for item in fields {
        let item = object_ref(item, &["data_type", "redact_type"])?;
        let data_type = string(&item["data_type"])?;
        let redact_type = enum_string(&item["redact_type"], &["FP", "TB"])?;
        if !valid_data_type(data_type) || !seen.insert((data_type, redact_type)) {
            return Err(failed());
        }
    }
    validate_section26(&object["section26_categories"])?;
    string(&object["redacted_pdf_b64"])?;
    string(&object["after_png_b64"])?;
    Ok(Value::Object(object))
}

fn validate_audit_log(body: Value) -> Result<Value, ProtocolError> {
    let mut object = object_owned(body, &["status", "total_count", "limit", "offset", "logs"])?;
    if string(&object["status"])? != "ok" {
        return Err(failed());
    }
    let total = nonnegative_integer(&object["total_count"])?;
    let limit = positive_integer(&object["limit"])?;
    let offset = nonnegative_integer(&object["offset"])?;
    if limit > 1000 || offset > 2_147_483_647 {
        return Err(failed());
    }
    let logs = object["logs"].as_array().ok_or_else(failed)?;
    if logs.len() as u64 > limit
        || total < logs.len() as u64
        || (offset >= total && !logs.is_empty())
    {
        return Err(failed());
    }
    let mut projected = Vec::with_capacity(logs.len());
    for entry in logs {
        projected.push(validate_audit_event(entry.clone())?);
    }
    object.insert("logs".to_owned(), Value::Array(projected));
    Ok(Value::Object(object))
}

fn validate_audit_event(entry: Value) -> Result<Value, ProtocolError> {
    let event_type = entry
        .get("type")
        .and_then(Value::as_str)
        .ok_or_else(failed)?
        .to_owned();
    let mut object = match event_type.as_str() {
        "process" => object_owned(
            entry,
            &[
                "type",
                "timestamp",
                "step",
                "entity_count",
                "validation_result",
                "latency_ms",
                "flags",
            ],
        )?,
        "security" => object_owned(
            entry,
            &[
                "type",
                "timestamp",
                "layer",
                "pii_scan_result",
                "retry_count",
                "error_type",
                "rollback_occurred",
            ],
        )?,
        _ => return Err(failed()),
    };
    let timestamp = nonnegative_decimal(&object["timestamp"])?;
    object.insert("timestamp".to_owned(), Value::String(timestamp));
    if event_type == "process" {
        enum_string(
            &object["step"],
            &[
                "api_sanitize",
                "api_reidentify",
                "api_analyze",
                "api_analyze_report",
                "api_roundtrip",
                "api_redact_pdf",
            ],
        )?;
        nonnegative_integer(&object["entity_count"])?;
        enum_string(
            &object["validation_result"],
            &["prepared", "blocked", "pass", "warn"],
        )?;
        let latency = nonnegative_decimal(&object["latency_ms"])?;
        object.insert("latency_ms".to_owned(), Value::String(latency));
        let flags = object["flags"].as_array().ok_or_else(failed)?;
        for flag in flags {
            let flag = object_ref(flag, &["code", "count"])?;
            enum_string(
                &flag["code"],
                &[
                    "provider_call",
                    "leftover_replacement",
                    "residual_block",
                    "ocr_review_required",
                    "source_pdf_text",
                    "source_pdf_hybrid",
                ],
            )?;
            nonnegative_integer(&flag["count"])?;
        }
    } else {
        enum_string(
            &object["layer"],
            &[
                "layer1", "layer2", "layer3", "outbound", "provider", "restore",
            ],
        )?;
        enum_string(
            &object["pii_scan_result"],
            &["clean", "unexpected_pii", "blocked", "error"],
        )?;
        nonnegative_integer(&object["retry_count"])?;
        if !object["error_type"].is_null() {
            string(&object["error_type"])?;
        }
        boolean(&object["rollback_occurred"])?;
    }
    Ok(Value::Object(object))
}

fn validate_disposal(body: Value) -> Result<Value, ProtocolError> {
    let object = object_owned(body, &["deleted"])?;
    let deleted = boolean(&object["deleted"])?;
    Ok(serde_json::json!({"disposed": deleted}))
}

fn validate_count_map(value: &Value) -> Result<Map<String, Value>, ProtocolError> {
    let object = value.as_object().ok_or_else(failed)?;
    let mut projected = Map::new();
    for (key, value) in object {
        if !valid_data_type(key) {
            return Err(failed());
        }
        positive_integer(value)?;
        projected.insert(key.clone(), value.clone());
    }
    Ok(projected)
}

fn count_total(values: &Map<String, Value>) -> Result<u64, ProtocolError> {
    values.values().try_fold(0_u64, |total, value| {
        total
            .checked_add(positive_integer(value)?)
            .ok_or_else(failed)
    })
}

fn validate_highlights(value: &Value, text_len: usize) -> Result<&Vec<Value>, ProtocolError> {
    let highlights = value.as_array().ok_or_else(failed)?;
    let mut previous_end = 0_u64;
    for highlight in highlights {
        let item = object_ref(highlight, &["start", "end", "data_type", "redact_type"])?;
        let start = nonnegative_integer(&item["start"])?;
        let end = positive_integer(&item["end"])?;
        if start >= end || start < previous_end || end > text_len as u64 {
            return Err(failed());
        }
        if !valid_data_type(string(&item["data_type"])?) {
            return Err(failed());
        }
        enum_string(&item["redact_type"], &["FP", "TB"])?;
        previous_end = end;
    }
    Ok(highlights)
}

fn validate_section26(value: &Value) -> Result<&Vec<Value>, ProtocolError> {
    validate_ordered_strings(
        value,
        &[
            "RACE_ETHNICITY",
            "POLITICAL_OPINION",
            "RELIGION",
            "HEALTH",
            "SEXUAL_BEHAVIOR",
            "CRIMINAL_RECORD",
            "DISABILITY",
            "LABOR_UNION",
        ],
    )
}

fn validate_guard_findings(value: &Value) -> Result<&Vec<Value>, ProtocolError> {
    let findings = value.as_array().ok_or_else(failed)?;
    let mut seen = HashSet::new();
    for finding in findings {
        let item = object_ref(finding, &["category", "severity"])?;
        let category = enum_string(
            &item["category"],
            &[
                "instruction_override",
                "role_hijack",
                "exfiltration",
                "hidden_chars",
                "suspicious_payload",
            ],
        )?;
        let severity = enum_string(&item["severity"], &["low", "medium", "high"])?;
        if !seen.insert((category, severity)) {
            return Err(failed());
        }
    }
    Ok(findings)
}

fn validate_warnings<'a>(
    value: &'a Value,
    allowed: &[&str],
) -> Result<&'a Vec<Value>, ProtocolError> {
    let warnings = value.as_array().ok_or_else(failed)?;
    let mut observed = Vec::new();
    for warning in warnings {
        let item = object_ref(warning, &["code", "count"])?;
        let code = enum_string(&item["code"], allowed)?;
        positive_integer(&item["count"])?;
        if observed.contains(&code) {
            return Err(failed());
        }
        observed.push(code);
    }
    let expected: Vec<&str> = allowed
        .iter()
        .copied()
        .filter(|code| observed.contains(code))
        .collect();
    if observed != expected {
        return Err(failed());
    }
    Ok(warnings)
}

fn validate_safety(value: &Value) -> Result<(), ProtocolError> {
    let safety = object_ref(value, &["status", "residual_count"])?;
    if string(&safety["status"])? != "pass" || nonnegative_integer(&safety["residual_count"])? != 0
    {
        return Err(failed());
    }
    Ok(())
}

fn validate_ordered_strings<'a>(
    value: &'a Value,
    allowed: &[&str],
) -> Result<&'a Vec<Value>, ProtocolError> {
    let values = value.as_array().ok_or_else(failed)?;
    let mut previous = None;
    for value in values {
        let value = string(value)?;
        let index = allowed
            .iter()
            .position(|candidate| *candidate == value)
            .ok_or_else(failed)?;
        if previous.is_some_and(|previous| index <= previous) {
            return Err(failed());
        }
        previous = Some(index);
    }
    Ok(values)
}

fn validate_recommendations(
    value: &Value,
    direct: bool,
    section26: bool,
    high_risk: bool,
    minimize: bool,
) -> Result<(), ProtocolError> {
    const DIRECT: (&str, &str, &str) = (
        "high",
        "Direct PII detected",
        "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
    );
    const SECTION26: (&str, &str, &str) = (
        "high",
        "Section 26 sensitive data detected",
        "ต้องได้รับความยินยอมโดยชัดแจ้งจากเจ้าของข้อมูลก่อนประมวลผล ตาม PDPA มาตรา 26",
    );
    const REIDENTIFICATION: (&str, &str, &str) = (
        "medium",
        "High re-identification risk",
        "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
    );
    const MINIMIZATION: (&str, &str, &str) = (
        "info",
        "Consider data minimization",
        "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
    );
    const CLEAR: (&str, &str, &str) = (
        "info",
        "No significant PDPA risk detected",
        "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
    );
    let mut expected = Vec::new();
    if direct {
        expected.push(DIRECT);
    }
    if section26 {
        expected.push(SECTION26);
    }
    if high_risk {
        expected.push(REIDENTIFICATION);
    }
    if minimize {
        expected.push(MINIMIZATION);
    }
    if expected.is_empty() {
        expected.push(CLEAR);
    }
    let actual = value.as_array().ok_or_else(failed)?;
    if actual.len() != expected.len() {
        return Err(failed());
    }
    for (actual, expected) in actual.iter().zip(expected) {
        let actual = object_ref(actual, &["level", "title", "desc"])?;
        if string(&actual["level"])? != expected.0
            || string(&actual["title"])? != expected.1
            || string(&actual["desc"])? != expected.2
        {
            return Err(failed());
        }
    }
    Ok(())
}

fn nonnegative_decimal(value: &Value) -> Result<String, ProtocolError> {
    let number = value.as_number().ok_or_else(failed)?;
    canonical_decimal(&number.to_string())
}

fn bounded_decimal(value: &Value, maximum: &str) -> Result<String, ProtocolError> {
    let decimal = nonnegative_decimal(value)?;
    if decimal_compare(&decimal, maximum).is_gt() {
        return Err(failed());
    }
    Ok(decimal)
}

fn decimal_at_least(value: &str, minimum: &str) -> Result<bool, ProtocolError> {
    canonical_decimal(value)?;
    canonical_decimal(minimum)?;
    Ok(!decimal_compare(value, minimum).is_lt())
}

fn canonical_decimal(raw: &str) -> Result<String, ProtocolError> {
    if raw.is_empty() || raw.starts_with('-') || raw.starts_with('+') {
        return Err(failed());
    }
    let (mantissa, exponent) = match raw.split_once(['e', 'E']) {
        Some((mantissa, exponent)) => {
            let exponent = exponent.parse::<i32>().map_err(|_| failed())?;
            (mantissa, exponent)
        }
        None => (raw, 0),
    };
    let (integer, fraction) = mantissa.split_once('.').unwrap_or((mantissa, ""));
    if integer.is_empty()
        || !integer.bytes().all(|byte| byte.is_ascii_digit())
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(failed());
    }
    let mut digits = format!("{integer}{fraction}");
    let mut decimal_index = i32::try_from(integer.len()).map_err(|_| failed())? + exponent;
    if decimal_index < 0 {
        let zeros = usize::try_from(-decimal_index).map_err(|_| failed())?;
        digits = format!("{}{digits}", "0".repeat(zeros));
        decimal_index = 0;
    }
    if decimal_index as usize > digits.len() {
        digits.push_str(&"0".repeat(decimal_index as usize - digits.len()));
    }
    let split = decimal_index as usize;
    let mut whole = digits[..split].trim_start_matches('0').to_owned();
    if whole.is_empty() {
        whole.push('0');
    }
    let fraction = digits[split..].trim_end_matches('0');
    if fraction.is_empty() {
        Ok(whole)
    } else {
        Ok(format!("{whole}.{fraction}"))
    }
}

fn decimal_compare(left: &str, right: &str) -> std::cmp::Ordering {
    let (left_whole, left_fraction) = decimal_parts(left);
    let (right_whole, right_fraction) = decimal_parts(right);
    left_whole
        .len()
        .cmp(&right_whole.len())
        .then_with(|| left_whole.cmp(right_whole))
        .then_with(|| {
            let width = left_fraction.len().max(right_fraction.len());
            format!("{left_fraction:0<width$}").cmp(&format!("{right_fraction:0<width$}"))
        })
}

fn decimal_parts(value: &str) -> (&str, &str) {
    value.split_once('.').unwrap_or((value, ""))
}

fn object<'a>(value: &'a Value, fields: &[&str]) -> Result<&'a Map<String, Value>, ProtocolError> {
    let object = value.as_object().ok_or_else(failed)?;
    exact_keys(object, fields)?;
    Ok(object)
}

fn object_ref<'a>(
    value: &'a Value,
    fields: &[&str],
) -> Result<&'a Map<String, Value>, ProtocolError> {
    object(value, fields)
}

fn object_owned(value: Value, fields: &[&str]) -> Result<Map<String, Value>, ProtocolError> {
    let object = value.as_object().cloned().ok_or_else(failed)?;
    exact_keys(&object, fields)?;
    Ok(object)
}

fn exact_keys(object: &Map<String, Value>, fields: &[&str]) -> Result<(), ProtocolError> {
    if object.len() != fields.len() || fields.iter().any(|field| !object.contains_key(*field)) {
        return Err(failed());
    }
    Ok(())
}

fn string(value: &Value) -> Result<&str, ProtocolError> {
    value.as_str().ok_or_else(failed)
}

fn nonempty_string(value: &Value) -> Result<&str, ProtocolError> {
    string(value).and_then(|value| (!value.is_empty()).then_some(value).ok_or_else(failed))
}

fn enum_string<'a>(value: &'a Value, allowed: &[&str]) -> Result<&'a str, ProtocolError> {
    let value = string(value)?;
    if allowed.contains(&value) {
        Ok(value)
    } else {
        Err(failed())
    }
}

fn boolean(value: &Value) -> Result<bool, ProtocolError> {
    value.as_bool().ok_or_else(failed)
}

fn nonnegative_integer(value: &Value) -> Result<u64, ProtocolError> {
    value.as_u64().ok_or_else(failed)
}

fn positive_integer(value: &Value) -> Result<u64, ProtocolError> {
    nonnegative_integer(value).and_then(|value| (value > 0).then_some(value).ok_or_else(failed))
}

fn valid_data_type(value: &str) -> bool {
    let mut bytes = value.bytes();
    bytes.next().is_some_and(|byte| byte.is_ascii_uppercase())
        && bytes.all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
}

fn valid_backend_session_id(value: &str) -> bool {
    if value.len() != BACKEND_SESSION_ID_LEN {
        return false;
    }
    let bytes = value.as_bytes();
    for (index, byte) in bytes.iter().enumerate() {
        if matches!(index, 8 | 13 | 18 | 23) {
            if *byte != b'-' {
                return false;
            }
        } else if !byte.is_ascii_hexdigit() || byte.is_ascii_uppercase() {
            return false;
        }
    }
    bytes[14] == b'4' && matches!(bytes[19], b'8' | b'9' | b'a' | b'b')
}

fn new_handle(prefix: &str) -> Result<String, ProtocolError> {
    let mut bytes = Zeroizing::new([0_u8; 16]);
    fill(bytes.as_mut()).map_err(|_| ProtocolError::new("operation_failed", None))?;
    let mut handle = String::with_capacity(prefix.len() + 1 + 32);
    handle.push_str(prefix);
    handle.push('-');
    for byte in bytes.iter() {
        use fmt::Write;
        write!(&mut handle, "{byte:02x}")
            .map_err(|_| ProtocolError::new("operation_failed", None))?;
    }
    Ok(handle)
}

fn unique_handle<T>(prefix: &str, existing: &HashMap<String, T>) -> Result<String, ProtocolError> {
    for _ in 0..4 {
        let handle = new_handle(prefix)?;
        if !existing.contains_key(&handle) {
            return Ok(handle);
        }
    }
    Err(ProtocolError::new("operation_failed", None))
}

fn failure_code(reason: BackendFailure) -> &'static str {
    match reason {
        BackendFailure::Timeout | BackendFailure::Cancelled => "operation_timeout",
        BackendFailure::Transport | BackendFailure::BackendDied => "operation_failed",
    }
}

fn terminal_cleanup_timed_out(
    error: &ProtocolError,
    deadline: Instant,
    cancelled: &dyn Fn() -> bool,
) -> bool {
    error.code() == "operation_timeout" || cancelled() || deadline <= Instant::now()
}

fn failed() -> ProtocolError {
    ProtocolError::new("operation_failed", None)
}
