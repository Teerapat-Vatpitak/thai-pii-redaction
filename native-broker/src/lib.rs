//! Transport-free native-broker protocol v1 codec and policy.
//!
//! Slice 2 adds authenticated native transport and broker-owned bootstrap.
//! Slice 3 adds connection-owned data forwarding to the private HTTP-v2 child.

#[used]
static NATIVE_COMPONENT_BUILD_MARKER: &str = concat!(
    "AIGUARD_NATIVE_COMPONENT_BUILD_ID=",
    env!("CARGO_PKG_VERSION"),
    "\0"
);

pub fn native_component_build_id() -> &'static str {
    let _ = NATIVE_COMPONENT_BUILD_MARKER;
    env!("CARGO_PKG_VERSION")
}

pub mod admission;
pub mod backend;
pub mod bootstrap;
pub mod broker;
pub mod control;
pub mod control_client;
pub mod data_plane;
pub mod desktop_client;
mod installed_product;
pub mod manifest;
mod process;
pub mod transport;

use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::fmt;
use std::sync::OnceLock;

use base64::engine::general_purpose::STANDARD as BASE64_STANDARD;
use base64::Engine;
use serde_json::{Map, Value};

pub const CONTRACT_JSON: &str = include_str!("../protocol-v1.json");

static CONTRACT: OnceLock<Value> = OnceLock::new();

fn contract() -> &'static Value {
    CONTRACT.get_or_init(|| {
        let value: Value =
            serde_json::from_str(CONTRACT_JSON).expect("embedded broker contract must be JSON");
        validate_embedded_contract(&value).expect("embedded broker contract must be valid");
        value
    })
}

fn validate_embedded_contract(value: &Value) -> Result<(), ProtocolError> {
    if value["contract_schema_version"].as_u64() != Some(1)
        || value["supported_protocol_versions"] != serde_json::json!([1])
        || value["framing"]["length_prefix_bytes"] != 4
        || value["framing"]["byte_order"] != "big"
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let raw = value["framing"]["max_pdf_raw_bytes"]
        .as_u64()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let encoded = value["framing"]["max_pdf_base64_bytes"]
        .as_u64()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let default = value["framing"]["default_message_bytes"]
        .as_u64()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let frame = value["framing"]["max_frame_bytes"]
        .as_u64()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    if encoded != 4 * raw.div_ceil(3) || frame != encoded + default {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let roles = value["roles"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let operations = value["operations"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    value["result_schema_definitions"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let serialization = value["serialization"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let max_depth = serialization["max_container_depth"]
        .as_u64()
        .filter(|depth| (1..=64).contains(depth))
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let blank_points = serialization["blank_text_code_points"]
        .as_array()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    if max_depth == 0
        || blank_points.iter().any(|point| {
            point
                .as_u64()
                .is_none_or(|point| point > 0x10_FFFF || (0xD800..=0xDFFF).contains(&point))
        })
        || blank_points.windows(2).any(|pair| {
            pair[0]
                .as_u64()
                .zip(pair[1].as_u64())
                .is_none_or(|(left, right)| left >= right)
        })
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    if operations
        .values()
        .any(|operation| !operation["result_schema"].is_object())
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let calls_per_scan = value["field_limits"]["remote_tner_calls_per_scan"]
        .as_u64()
        .filter(|value| *value > 0)
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    value["field_limits"]["connection_messages"]
        .as_u64()
        .filter(|value| *value > 1)
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    if value["field_limits"]["local_intermediate_text_chars"].as_u64()
        != value["field_limits"]["text_chars"].as_u64()
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let disabled_remote: BTreeSet<&str> = value["remote_tner_policy"]["disabled_operations"]
        .as_array()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?
        .iter()
        .map(|item| {
            item.as_str()
                .ok_or_else(|| ProtocolError::new("operation_failed", None))
        })
        .collect::<Result<_, _>>()?;
    let source_only_remote: BTreeSet<&str> = value["remote_tner_policy"]["source_only_operations"]
        .as_array()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?
        .iter()
        .map(|item| {
            item.as_str()
                .ok_or_else(|| ProtocolError::new("operation_failed", None))
        })
        .collect::<Result<_, _>>()?;
    if disabled_remote != BTreeSet::from(["redact_pdf", "reidentify", "roundtrip", "sanitize"])
        || source_only_remote != BTreeSet::from(["analyze", "analyze_report", "detect"])
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let components = value["deadline_components_ms"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let profiles = value["deadline_profiles_ms"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    let component = |name: &str| {
        components[name]
            .as_u64()
            .ok_or_else(|| ProtocolError::new("operation_failed", None))
    };
    let profile = |name: &str| {
        profiles[name]
            .as_u64()
            .ok_or_else(|| ProtocolError::new("operation_failed", None))
    };
    let adapter = component("adapter")?;
    let local_phase = component("local_detection_phase")?;
    let restore = component("local_restore_and_disposal")?;
    let provider_attempt = component("provider_attempt")?;
    let provider_backoff = component("provider_backoff_total")?;
    let remote_call = component("remote_tner_call")?;
    if profile("local_sanitize")? != 2 * local_phase + adapter
        || profile("local_reidentify")? != local_phase + restore
        || profile("local_provider")?
            != 6 * local_phase + 3 * provider_attempt + provider_backoff + adapter
        || profile("remote_tner_text")? != calls_per_scan * remote_call + adapter
        || profile("remote_tner_report")? != profile("remote_tner_text")? + restore
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    let errors = value["errors"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
    if errors.values().any(|spec| {
        spec.as_object()
            .and_then(|spec| spec.get("retry"))
            .and_then(Value::as_str)
            .is_none_or(|retry| !matches!(retry, "never" | "reconnect_only"))
    }) {
        return Err(ProtocolError::new("operation_failed", None));
    }
    for policy_error in [
        &value["connection_policy"]["message_limit_error"],
        &value["connection_policy"]["terminal_error"],
        &value["local_detection_policy"]["intermediate_limit_error"],
        &value["remote_tner_policy"]["unsupported_operation_error"],
    ] {
        if policy_error
            .as_str()
            .is_none_or(|code| !errors.contains_key(code))
        {
            return Err(ProtocolError::new("operation_failed", None));
        }
    }
    let positive_remote_operations: BTreeSet<&str> = operations
        .iter()
        .filter(|(_, operation)| {
            operation["remote_tner_primary_scans"]
                .as_u64()
                .is_some_and(|scans| scans > 0)
        })
        .map(|(name, _)| name.as_str())
        .collect();
    let null_remote_operations: BTreeSet<&str> = operations
        .iter()
        .filter(|(_, operation)| operation["deadline_remote_tner"].is_null())
        .map(|(name, _)| name.as_str())
        .collect();
    if positive_remote_operations != source_only_remote || null_remote_operations != disabled_remote
    {
        return Err(ProtocolError::new("operation_failed", None));
    }
    for (operation_name, operation) in operations {
        if operation["local_detection_phases"].as_u64().is_none()
            && !operation["local_detection_phases"].is_null()
        {
            return Err(ProtocolError::new("operation_failed", None));
        }
        let primary_scans = operation.get("remote_tner_primary_scans");
        let max_calls = operation.get("remote_tner_max_calls");
        if operation["deadline_remote_tner"].is_null() {
            if primary_scans.is_some_and(|value| !value.is_null())
                || max_calls.is_some_and(|value| !value.is_null())
            {
                return Err(ProtocolError::new("operation_failed", None));
            }
        } else {
            let primary_scans = primary_scans
                .and_then(Value::as_u64)
                .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
            if max_calls.and_then(Value::as_u64) != Some(primary_scans * calls_per_scan) {
                return Err(ProtocolError::new("operation_failed", None));
            }
        }
        if disabled_remote.contains(operation_name.as_str())
            && !operation["deadline_remote_tner"].is_null()
        {
            return Err(ProtocolError::new("operation_failed", None));
        }
        if source_only_remote.contains(operation_name.as_str())
            && (primary_scans.and_then(Value::as_u64) != Some(1)
                || max_calls.and_then(Value::as_u64) != Some(calls_per_scan))
        {
            return Err(ProtocolError::new("operation_failed", None));
        }
    }
    for (role, allowed) in roles {
        if !matches!(role.as_str(), "desktop" | "extension" | "maintenance") {
            return Err(ProtocolError::new("operation_failed", None));
        }
        let allowed = allowed
            .as_array()
            .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
        if allowed.iter().any(|operation| {
            operation
                .as_str()
                .is_none_or(|name| !operations.contains_key(name))
        }) {
            return Err(ProtocolError::new("operation_failed", None));
        }
    }
    Ok(())
}

#[derive(Clone, Eq, PartialEq)]
pub struct ProtocolError {
    code: String,
    request_id: Option<String>,
}

impl fmt::Debug for ProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProtocolError")
            .field("code", &self.code)
            .finish_non_exhaustive()
    }
}

impl ProtocolError {
    pub fn new(code: &str, request_id: Option<&str>) -> Self {
        Self {
            code: safe_error_code(code).to_owned(),
            request_id: request_id
                .filter(|value| valid_id(value))
                .map(str::to_owned),
        }
    }

    pub fn code(&self) -> &str {
        &self.code
    }

    pub fn request_id(&self) -> Option<&str> {
        self.request_id.as_deref()
    }
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.code)
    }
}

impl std::error::Error for ProtocolError {}

#[derive(Eq, PartialEq)]
pub struct ConnectionState {
    role: String,
    protocol_version: u64,
    seen_request_ids: BTreeSet<String>,
    messages_seen: u64,
    terminal: bool,
}

impl ConnectionState {
    #[doc(hidden)]
    pub(crate) fn for_authenticated_client(
        role: &str,
        protocol_version: u64,
        hello_request_id: &str,
    ) -> Result<Self, ProtocolError> {
        if !valid_role(role)
            || !valid_id(hello_request_id)
            || !contract()["supported_protocol_versions"]
                .as_array()
                .is_some_and(|versions| {
                    versions
                        .iter()
                        .any(|version| version.as_u64() == Some(protocol_version))
                })
        {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        Ok(Self {
            role: role.to_owned(),
            protocol_version,
            seen_request_ids: BTreeSet::from([hello_request_id.to_owned()]),
            messages_seen: 1,
            terminal: false,
        })
    }

    pub fn role(&self) -> &str {
        &self.role
    }

    pub fn protocol_version(&self) -> u64 {
        self.protocol_version
    }

    pub fn terminal(&self) -> bool {
        self.terminal
    }
}

impl fmt::Debug for ConnectionState {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ConnectionState")
            .field("role", &self.role)
            .field("protocol_version", &self.protocol_version)
            .field("terminal", &self.terminal)
            .finish_non_exhaustive()
    }
}

#[derive(PartialEq)]
pub struct HelloNegotiation {
    pub state: ConnectionState,
    pub response: Value,
}

impl fmt::Debug for HelloNegotiation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HelloNegotiation")
            .field("state", &self.state)
            .finish_non_exhaustive()
    }
}

#[derive(PartialEq)]
pub struct BrokerRequest {
    pub protocol_version: u64,
    pub request_id: String,
    pub operation: String,
    pub scope_id: Option<String>,
    pub payload: Value,
    pub deadline_ms: Option<u64>,
    pub local_detection_phases: Option<u64>,
    pub local_intermediate_text_chars: Option<u64>,
    pub remote_tner_max_calls: u64,
    pub remote_tner_text_chars: Option<u64>,
    pub replay: String,
    pub uncertain_completion: String,
}

impl fmt::Debug for BrokerRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrokerRequest")
            .field("protocol_version", &self.protocol_version)
            .field("operation", &self.operation)
            .field("deadline_ms", &self.deadline_ms)
            .field("local_detection_phases", &self.local_detection_phases)
            .field("remote_tner_max_calls", &self.remote_tner_max_calls)
            .field("replay", &self.replay)
            .field("uncertain_completion", &self.uncertain_completion)
            .finish_non_exhaustive()
    }
}

pub fn safe_error_code(code: &str) -> &str {
    if contract()["errors"].get(code).is_some() {
        code
    } else {
        "operation_failed"
    }
}

fn json_integer_max() -> u64 {
    contract()["field_limits"]["json_integer_max"]
        .as_u64()
        .expect("validated JSON integer limit")
}

fn max_container_depth() -> usize {
    contract()["serialization"]["max_container_depth"]
        .as_u64()
        .expect("validated JSON depth limit") as usize
}

fn validate_json_value(value: &Value, container_depth: usize) -> Result<(), ProtocolError> {
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(number) => match number.as_u64() {
            Some(value) if value <= json_integer_max() => Ok(()),
            _ => Err(ProtocolError::new("request_invalid", None)),
        },
        Value::Array(values) => {
            let next_depth = container_depth + 1;
            if next_depth > max_container_depth() {
                return Err(ProtocolError::new("request_invalid", None));
            }
            for value in values {
                validate_json_value(value, next_depth)?;
            }
            Ok(())
        }
        Value::Object(values) => {
            let next_depth = container_depth + 1;
            if next_depth > max_container_depth() {
                return Err(ProtocolError::new("request_invalid", None));
            }
            for value in values.values() {
                validate_json_value(value, next_depth)?;
            }
            Ok(())
        }
    }
}

pub fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>, ProtocolError> {
    validate_json_value(value, 0)?;
    serde_json::to_vec(value).map_err(|_| ProtocolError::new("request_invalid", None))
}

fn validate_raw_container_depth(raw: &[u8]) -> Result<(), ProtocolError> {
    let mut depth = 0usize;
    let mut in_string = false;
    let mut escaped = false;
    for byte in raw {
        if in_string {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                in_string = false;
            }
            continue;
        }
        match *byte {
            b'"' => in_string = true,
            b'[' | b'{' => {
                depth += 1;
                if depth > max_container_depth() {
                    return Err(ProtocolError::new("request_invalid", None));
                }
            }
            b']' | b'}' => {
                depth = depth
                    .checked_sub(1)
                    .ok_or_else(|| ProtocolError::new("request_invalid", None))?;
            }
            _ => {}
        }
    }
    Ok(())
}

fn parse_canonical_object_with_limit(
    raw: &[u8],
    max_bytes: Option<u64>,
) -> Result<Value, ProtocolError> {
    if raw.is_empty() {
        return Err(ProtocolError::new("request_invalid", None));
    }
    if max_bytes.is_some_and(|limit| raw.len() as u64 > limit) {
        return Err(ProtocolError::new("payload_too_large", None));
    }
    validate_raw_container_depth(raw)?;
    let value: Value =
        serde_json::from_slice(raw).map_err(|_| ProtocolError::new("request_invalid", None))?;
    if !value.is_object() {
        return Err(ProtocolError::new("request_invalid", None));
    }
    let encoded = canonical_json_bytes(&value)?;
    if encoded != raw {
        return Err(ProtocolError::new("request_invalid", None));
    }
    Ok(value)
}

pub fn parse_canonical_object(raw: &[u8]) -> Result<Value, ProtocolError> {
    parse_canonical_object_with_limit(raw, None)
}

fn production_frame_limit() -> u64 {
    contract()["framing"]["max_frame_bytes"]
        .as_u64()
        .expect("validated frame limit")
}

pub fn max_frame_bytes() -> u64 {
    production_frame_limit()
}

pub fn max_hello_bytes() -> u64 {
    contract()["framing"]["max_hello_bytes"]
        .as_u64()
        .expect("validated hello limit")
}

pub fn default_message_bytes() -> u64 {
    contract()["framing"]["default_message_bytes"]
        .as_u64()
        .expect("validated message limit")
}

fn effective_frame_limit(max_frame_bytes: Option<u64>) -> Result<u64, ProtocolError> {
    match max_frame_bytes {
        Some(0) => Err(ProtocolError::new("request_invalid", None)),
        Some(limit) => Ok(production_frame_limit().min(limit)),
        None => Ok(production_frame_limit()),
    }
}

pub fn validate_declared_length(
    declared_length: u64,
    max_frame_bytes: Option<u64>,
) -> Result<(), ProtocolError> {
    if declared_length == 0 {
        return Err(ProtocolError::new("request_invalid", None));
    }
    if declared_length > effective_frame_limit(max_frame_bytes)? {
        return Err(ProtocolError::new("payload_too_large", None));
    }
    Ok(())
}

pub fn encode_frame(
    message: &[u8],
    max_frame_bytes: Option<u64>,
) -> Result<Vec<u8>, ProtocolError> {
    parse_canonical_object_with_limit(message, Some(effective_frame_limit(max_frame_bytes)?))?;
    validate_declared_length(message.len() as u64, max_frame_bytes)?;
    let length =
        u32::try_from(message.len()).map_err(|_| ProtocolError::new("payload_too_large", None))?;
    let mut frame = Vec::with_capacity(message.len() + 4);
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(message);
    Ok(frame)
}

pub struct FrameDecoder {
    max_frame_bytes: u64,
    buffer: Vec<u8>,
    expected_length: Option<usize>,
    single_frame: bool,
    require_frame: bool,
    frames_decoded: usize,
    failed: bool,
}

impl fmt::Debug for FrameDecoder {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FrameDecoder")
            .field("max_frame_bytes", &self.max_frame_bytes)
            .field("single_frame", &self.single_frame)
            .field("failed", &self.failed)
            .finish_non_exhaustive()
    }
}

impl FrameDecoder {
    pub fn new(max_frame_bytes: Option<u64>) -> Result<Self, ProtocolError> {
        Ok(Self {
            max_frame_bytes: effective_frame_limit(max_frame_bytes)?,
            buffer: Vec::new(),
            expected_length: None,
            single_frame: false,
            require_frame: false,
            frames_decoded: 0,
            failed: false,
        })
    }

    pub fn for_hello() -> Result<Self, ProtocolError> {
        let hello_limit = contract()["framing"]["max_hello_bytes"]
            .as_u64()
            .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
        let mut decoder = Self::new(Some(hello_limit))?;
        decoder.single_frame = true;
        decoder.require_frame = true;
        Ok(decoder)
    }

    fn fail(&mut self, code: &str) -> ProtocolError {
        self.buffer.clear();
        self.expected_length = None;
        self.failed = true;
        ProtocolError::new(code, None)
    }

    pub fn feed(&mut self, data: &[u8]) -> Result<Vec<Vec<u8>>, ProtocolError> {
        if self.failed {
            return Err(ProtocolError::new("request_invalid", None));
        }
        let mut frames = Vec::new();
        let mut offset = 0;
        while offset < data.len() {
            if self.single_frame && self.frames_decoded >= 1 {
                return Err(self.fail("request_invalid"));
            }
            if self.expected_length.is_none() {
                let header_bytes = (4 - self.buffer.len()).min(data.len() - offset);
                self.buffer
                    .extend_from_slice(&data[offset..offset + header_bytes]);
                offset += header_bytes;
                if self.buffer.len() != 4 {
                    break;
                }
                let declared = u32::from_be_bytes([
                    self.buffer[0],
                    self.buffer[1],
                    self.buffer[2],
                    self.buffer[3],
                ]) as u64;
                self.buffer.clear();
                if let Err(error) = validate_declared_length(declared, Some(self.max_frame_bytes)) {
                    return Err(self.fail(error.code()));
                }
                self.expected_length = Some(declared as usize);
            }
            let expected = self.expected_length.expect("set above");
            let body_bytes = (expected - self.buffer.len()).min(data.len() - offset);
            self.buffer
                .extend_from_slice(&data[offset..offset + body_bytes]);
            offset += body_bytes;
            if self.buffer.len() != expected {
                break;
            }
            let frame = std::mem::take(&mut self.buffer);
            self.expected_length = None;
            frames.push(frame);
            self.frames_decoded += 1;
        }
        Ok(frames)
    }

    pub fn finish(&mut self) -> Result<(), ProtocolError> {
        if self.failed
            || self.expected_length.is_some()
            || !self.buffer.is_empty()
            || (self.require_frame && self.frames_decoded != 1)
        {
            return Err(self.fail("request_invalid"));
        }
        Ok(())
    }
}

fn exact_fields(
    value: &Map<String, Value>,
    expected: &[&str],
    request_id: Option<&str>,
) -> Result<(), ProtocolError> {
    let actual: BTreeSet<&str> = value.keys().map(String::as_str).collect();
    let expected: BTreeSet<&str> = expected.iter().copied().collect();
    if actual == expected {
        Ok(())
    } else {
        Err(ProtocolError::new("request_invalid", request_id))
    }
}

fn valid_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=128).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}

fn valid_operation(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'_')
}

fn valid_product_version(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'+' | b'-'))
}

fn valid_provider(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes[1..].iter().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-')
        })
}

fn valid_role(role: &str) -> bool {
    contract()["roles"].get(role).is_some()
}

fn request_id_from(message: &Map<String, Value>) -> Option<&str> {
    message
        .get("request_id")
        .and_then(Value::as_str)
        .filter(|value| valid_id(value))
}

pub fn negotiate_hello(
    raw: &[u8],
    authenticated_role: &str,
    broker_product_version: &str,
) -> Result<HelloNegotiation, ProtocolError> {
    let hello_limit = contract()["framing"]["max_hello_bytes"]
        .as_u64()
        .expect("validated hello limit");
    let message = parse_canonical_object_with_limit(raw, Some(hello_limit))?;
    let object = message.as_object().expect("parser requires object");
    let request_id = request_id_from(object);
    exact_fields(
        object,
        &[
            "claimed_role",
            "client_product_version",
            "request_id",
            "supported_protocol_versions",
        ],
        request_id,
    )?;
    let request_id = request_id.ok_or_else(|| ProtocolError::new("request_invalid", None))?;
    let claimed_role = object
        .get("claimed_role")
        .and_then(Value::as_str)
        .ok_or_else(|| ProtocolError::new("broker_unauthorized", Some(request_id)))?;
    if !valid_role(claimed_role)
        || !valid_role(authenticated_role)
        || claimed_role != authenticated_role
    {
        return Err(ProtocolError::new("broker_unauthorized", Some(request_id)));
    }
    let client_product_version = object
        .get("client_product_version")
        .and_then(Value::as_str)
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    if !valid_product_version(client_product_version) {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    if !valid_product_version(broker_product_version) {
        return Err(ProtocolError::new("operation_failed", Some(request_id)));
    }
    let versions = object
        .get("supported_protocol_versions")
        .and_then(Value::as_array)
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    let version_limit = contract()["field_limits"]["supported_versions_count"]
        .as_u64()
        .expect("validated version list limit") as usize;
    if versions.is_empty() || versions.len() > version_limit {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    let mut parsed_versions = Vec::with_capacity(versions.len());
    for version in versions {
        let version = version
            .as_u64()
            .filter(|value| *value > 0)
            .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
        parsed_versions.push(version);
    }
    if parsed_versions.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    let supported: BTreeSet<u64> = contract()["supported_protocol_versions"]
        .as_array()
        .expect("validated supported versions")
        .iter()
        .filter_map(Value::as_u64)
        .collect();
    let selected = parsed_versions
        .into_iter()
        .filter(|version| supported.contains(version))
        .max()
        .ok_or_else(|| ProtocolError::new("broker_incompatible", Some(request_id)))?;
    let state = ConnectionState {
        role: authenticated_role.to_owned(),
        protocol_version: selected,
        seen_request_ids: BTreeSet::from([request_id.to_owned()]),
        messages_seen: 1,
        terminal: false,
    };
    let response = serde_json::json!({
        "broker_product_version": broker_product_version,
        "broker_protocol_version": selected,
        "request_id": request_id,
        "role": authenticated_role,
    });
    Ok(HelloNegotiation { state, response })
}

pub fn operation_allowed(role: &str, operation: &str) -> bool {
    contract()["roles"]
        .get(role)
        .and_then(Value::as_array)
        .is_some_and(|allowed| allowed.iter().any(|item| item.as_str() == Some(operation)))
}

pub fn operation_replay(operation: &str) -> Option<&'static str> {
    let replay = contract()["operations"]
        .get(operation)?
        .get("replay")?
        .as_str()?;
    match replay {
        "startup_only" => Some("startup_only"),
        "never" => Some("never"),
        _ => None,
    }
}

pub fn deadline_ms(operation: &str, remote_tner: bool) -> Option<u64> {
    let operation = contract()["operations"].get(operation)?;
    let field = if remote_tner {
        "deadline_remote_tner"
    } else {
        "deadline_local"
    };
    let profile = operation.get(field)?.as_str()?;
    contract()["deadline_profiles_ms"].get(profile)?.as_u64()
}

fn message_limit(role: &str, operation: &str, response: bool) -> Option<u64> {
    if !valid_role(role) {
        return None;
    }
    let spec = contract()["operations"].get(operation)?;
    let limit_name = spec
        .get(if response {
            "response_limit"
        } else {
            "request_limit"
        })?
        .as_str()?;
    let framing = &contract()["framing"];
    let mut limit = if limit_name == "pdf" {
        framing["max_frame_bytes"].as_u64()?
    } else {
        framing["default_message_bytes"].as_u64()?
    };
    if response && role == "extension" {
        limit = limit.min(framing["extension_response_bytes"].as_u64()?);
    }
    Some(limit)
}

pub fn local_detection_phase_ms() -> Option<u64> {
    contract()["deadline_components_ms"]["local_detection_phase"].as_u64()
}

pub fn response_message_bytes(role: &str, operation: &str) -> Option<u64> {
    message_limit(role, operation, true)
}

fn uses_remote_tner_limit(spec: &Value, remote_tner: bool) -> bool {
    remote_tner
        && spec["remote_tner_primary_scans"]
            .as_u64()
            .is_some_and(|value| value > 0)
}

fn validate_text(value: &Value, remote_tner: bool, request_id: &str) -> Result<(), ProtocolError> {
    let blank_points = contract()["serialization"]["blank_text_code_points"]
        .as_array()
        .expect("validated blank text table");
    let text = value
        .as_str()
        .filter(|text| {
            !text.is_empty()
                && !text.chars().all(|character| {
                    blank_points
                        .binary_search_by_key(&(character as u64), |point| {
                            point.as_u64().expect("validated blank code point")
                        })
                        .is_ok()
                })
        })
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    let limit_name = if remote_tner {
        "remote_tner_text_chars"
    } else {
        "text_chars"
    };
    let limit = contract()["field_limits"][limit_name]
        .as_u64()
        .expect("validated text limit") as usize;
    if text.chars().count() > limit {
        return Err(ProtocolError::new("payload_too_large", Some(request_id)));
    }
    Ok(())
}

fn validate_pdf_base64(value: &Value, request_id: &str) -> Result<(), ProtocolError> {
    let value = value
        .as_str()
        .filter(|value| !value.is_empty() && value.is_ascii())
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    let encoded_limit = contract()["framing"]["max_pdf_base64_bytes"]
        .as_u64()
        .expect("validated PDF base64 limit") as usize;
    if value.len() > encoded_limit {
        return Err(ProtocolError::new("payload_too_large", Some(request_id)));
    }
    let decoded = BASE64_STANDARD
        .decode(value)
        .map_err(|_| ProtocolError::new("request_invalid", Some(request_id)))?;
    let raw_limit = contract()["framing"]["max_pdf_raw_bytes"]
        .as_u64()
        .expect("validated PDF raw limit") as usize;
    if decoded.len() > raw_limit {
        return Err(ProtocolError::new("payload_too_large", Some(request_id)));
    }
    if BASE64_STANDARD.encode(decoded) != value {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    Ok(())
}

fn decimal_parts(value: &str) -> Option<(&str, &str)> {
    let (integer, fraction) = value.split_once('.').unwrap_or((value, ""));
    if integer.is_empty()
        || !integer.bytes().all(|byte| byte.is_ascii_digit())
        || (integer.len() > 1 && integer.starts_with('0'))
        || (!fraction.is_empty()
            && (!fraction.bytes().all(|byte| byte.is_ascii_digit()) || fraction.ends_with('0')))
        || value.ends_with('.')
    {
        return None;
    }
    Some((integer, fraction))
}

fn compare_decimals(left: &str, right: &str) -> Option<Ordering> {
    let (left_integer, left_fraction) = decimal_parts(left)?;
    let (right_integer, right_fraction) = decimal_parts(right)?;
    let integer_order = left_integer
        .len()
        .cmp(&right_integer.len())
        .then_with(|| left_integer.cmp(right_integer));
    if integer_order != Ordering::Equal {
        return Some(integer_order);
    }
    let width = left_fraction.len().max(right_fraction.len());
    for index in 0..width {
        let left = left_fraction.as_bytes().get(index).copied().unwrap_or(b'0');
        let right = right_fraction
            .as_bytes()
            .get(index)
            .copied()
            .unwrap_or(b'0');
        if left != right {
            return Some(left.cmp(&right));
        }
    }
    Some(Ordering::Equal)
}

fn valid_data_type(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes[0].is_ascii_uppercase()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || *byte == b'_')
}

fn enum_contains(values: Option<&Vec<Value>>, value: &Value) -> bool {
    values.is_some_and(|values| values.iter().any(|candidate| candidate == value))
}

fn validate_result_schema(
    value: &Value,
    schema: &Value,
    request_id: &str,
) -> Result<(), ProtocolError> {
    validate_result_schema_inner(value, schema, request_id, &mut BTreeSet::new())
}

fn validate_result_schema_inner(
    value: &Value,
    schema: &Value,
    request_id: &str,
    active_refs: &mut BTreeSet<String>,
) -> Result<(), ProtocolError> {
    let schema = schema
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
    if let Some(reference) = schema.get("ref") {
        if schema.len() != 1 {
            return Err(ProtocolError::new("operation_failed", Some(request_id)));
        }
        let reference = reference
            .as_str()
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
        let resolved = contract()["result_schema_definitions"]
            .get(reference)
            .filter(|resolved| resolved.is_object())
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
        if !active_refs.insert(reference.to_owned()) {
            return Err(ProtocolError::new("operation_failed", Some(request_id)));
        }
        let result = validate_result_schema_inner(value, resolved, request_id, active_refs);
        active_refs.remove(reference);
        return result;
    }

    let kind = schema
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
    match kind {
        "boolean" => {
            if value.is_boolean() {
                Ok(())
            } else {
                Err(ProtocolError::new("request_invalid", Some(request_id)))
            }
        }
        "integer" => {
            let number = value
                .as_u64()
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
            let minimum = schema.get("minimum").map_or(Some(0), Value::as_u64);
            let maximum = schema
                .get("maximum")
                .map_or(Some(json_integer_max()), Value::as_u64);
            let (minimum, maximum) = match (minimum, maximum) {
                (Some(minimum), Some(maximum))
                    if minimum <= maximum && maximum <= json_integer_max() =>
                {
                    (minimum, maximum)
                }
                _ => return Err(ProtocolError::new("operation_failed", Some(request_id))),
            };
            if !(minimum..=maximum).contains(&number)
                || (schema.contains_key("enum")
                    && !enum_contains(schema.get("enum").and_then(Value::as_array), value))
            {
                return Err(ProtocolError::new("request_invalid", Some(request_id)));
            }
            Ok(())
        }
        "decimal" => {
            let decimal = value
                .as_str()
                .filter(|value| decimal_parts(value).is_some())
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
            if let Some(minimum) = schema.get("minimum") {
                let minimum = minimum
                    .as_str()
                    .filter(|minimum| decimal_parts(minimum).is_some())
                    .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
                if compare_decimals(decimal, minimum) == Some(Ordering::Less) {
                    return Err(ProtocolError::new("request_invalid", Some(request_id)));
                }
            }
            if let Some(maximum) = schema.get("maximum") {
                let maximum = maximum
                    .as_str()
                    .filter(|maximum| decimal_parts(maximum).is_some())
                    .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
                if compare_decimals(decimal, maximum) == Some(Ordering::Greater) {
                    return Err(ProtocolError::new("request_invalid", Some(request_id)));
                }
            }
            Ok(())
        }
        "string" => {
            let string = value
                .as_str()
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
            let minimum = schema.get("min_chars").map_or(Some(0), Value::as_u64);
            let maximum = schema.get("max_chars").map(Value::as_u64);
            let (minimum, maximum) = match (minimum, maximum) {
                (Some(minimum), None) => (minimum, None),
                (Some(minimum), Some(Some(maximum))) if minimum <= maximum => {
                    (minimum, Some(maximum))
                }
                _ => return Err(ProtocolError::new("operation_failed", Some(request_id))),
            };
            let length = string.chars().count() as u64;
            if length < minimum || maximum.is_some_and(|maximum| length > maximum) {
                return Err(ProtocolError::new("request_invalid", Some(request_id)));
            }
            if schema.contains_key("enum")
                && !enum_contains(schema.get("enum").and_then(Value::as_array), value)
            {
                return Err(ProtocolError::new("request_invalid", Some(request_id)));
            }
            let valid_pattern = match schema.get("pattern").map(Value::as_str) {
                None => true,
                Some(Some("opaque_id")) => valid_id(string),
                Some(Some("data_type")) => valid_data_type(string),
                Some(Some("provider")) => valid_provider(string),
                Some(Some("base64")) => BASE64_STANDARD
                    .decode(string)
                    .is_ok_and(|decoded| BASE64_STANDARD.encode(decoded) == string),
                _ => return Err(ProtocolError::new("operation_failed", Some(request_id))),
            };
            if !valid_pattern {
                return Err(ProtocolError::new("request_invalid", Some(request_id)));
            }
            Ok(())
        }
        "object" => {
            let object = value
                .as_object()
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
            let fields = schema
                .get("fields")
                .and_then(Value::as_object)
                .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
            let actual: BTreeSet<&str> = object.keys().map(String::as_str).collect();
            let expected: BTreeSet<&str> = fields.keys().map(String::as_str).collect();
            if actual != expected {
                return Err(ProtocolError::new("request_invalid", Some(request_id)));
            }
            for (field, field_schema) in fields {
                validate_result_schema_inner(
                    &object[field],
                    field_schema,
                    request_id,
                    active_refs,
                )?;
            }
            Ok(())
        }
        "map" => {
            let object = value
                .as_object()
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
            let values_schema = schema
                .get("values")
                .filter(|values| values.is_object())
                .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
            if schema.get("key_pattern").and_then(Value::as_str) != Some("data_type") {
                return Err(ProtocolError::new("operation_failed", Some(request_id)));
            }
            for (key, item) in object {
                if !valid_data_type(key) {
                    return Err(ProtocolError::new("request_invalid", Some(request_id)));
                }
                validate_result_schema_inner(item, values_schema, request_id, active_refs)?;
            }
            Ok(())
        }
        "array" => {
            let array = value
                .as_array()
                .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
            let items_schema = schema
                .get("items")
                .filter(|items| items.is_object())
                .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
            let minimum = schema.get("min_items").map_or(Some(0), Value::as_u64);
            let maximum = schema.get("max_items").map(Value::as_u64);
            let (minimum, maximum) = match (minimum, maximum) {
                (Some(minimum), None) => (minimum, None),
                (Some(minimum), Some(Some(maximum))) if minimum <= maximum => {
                    (minimum, Some(maximum))
                }
                _ => return Err(ProtocolError::new("operation_failed", Some(request_id))),
            };
            let length = array.len() as u64;
            if length < minimum || maximum.is_some_and(|maximum| length > maximum) {
                return Err(ProtocolError::new("request_invalid", Some(request_id)));
            }
            for item in array {
                validate_result_schema_inner(item, items_schema, request_id, active_refs)?;
            }
            if let Some(ordered) = schema.get("ordered_values") {
                let ordered = ordered
                    .as_array()
                    .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
                let mut previous = None;
                for item in array {
                    let index = ordered
                        .iter()
                        .position(|candidate| candidate == item)
                        .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
                    if previous.is_some_and(|previous| index <= previous) {
                        return Err(ProtocolError::new("request_invalid", Some(request_id)));
                    }
                    previous = Some(index);
                }
            }
            Ok(())
        }
        "nullable" => {
            let nested = schema
                .get("schema")
                .filter(|nested| nested.is_object())
                .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
            if value.is_null() {
                Ok(())
            } else {
                validate_result_schema_inner(value, nested, request_id, active_refs)
            }
        }
        "one_of" => {
            let variants = schema
                .get("variants")
                .and_then(Value::as_array)
                .filter(|variants| !variants.is_empty())
                .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
            let mut matches = 0;
            for variant in variants {
                match validate_result_schema_inner(value, variant, request_id, active_refs) {
                    Ok(()) => matches += 1,
                    Err(error) if error.code() == "operation_failed" => return Err(error),
                    Err(_) => {}
                }
            }
            if matches == 1 {
                Ok(())
            } else {
                Err(ProtocolError::new("request_invalid", Some(request_id)))
            }
        }
        _ => Err(ProtocolError::new("operation_failed", Some(request_id))),
    }
}

fn validate_payload_field(
    kind: &str,
    value: &Value,
    role: &str,
    request_id: &str,
    remote_tner: bool,
) -> Result<(), ProtocolError> {
    match kind {
        "text" => validate_text(value, remote_tner, request_id),
        "mode" => match value.as_str() {
            Some("token" | "surrogate") => Ok(()),
            _ => Err(ProtocolError::new("request_invalid", Some(request_id))),
        },
        "opaque_id" => match value.as_str().filter(|value| valid_id(value)) {
            Some(_) => Ok(()),
            None => Err(ProtocolError::new("request_invalid", Some(request_id))),
        },
        "provider_name" => match value.as_str().filter(|value| valid_provider(value)) {
            Some(_) => Ok(()),
            None => Err(ProtocolError::new("request_invalid", Some(request_id))),
        },
        "role_scope_kind" => {
            let allowed = contract()["scope_kinds"]
                .get(role)
                .and_then(Value::as_array);
            if value.as_str().is_some_and(|value| {
                allowed.is_some_and(|items| items.iter().any(|item| item.as_str() == Some(value)))
            }) {
                Ok(())
            } else {
                Err(ProtocolError::new("broker_unauthorized", Some(request_id)))
            }
        }
        "pdf_base64" => validate_pdf_base64(value, request_id),
        "audit_limit" => {
            let number = value.as_u64();
            let minimum = contract()["field_limits"]["audit_limit_min"]
                .as_u64()
                .expect("validated audit minimum");
            let maximum = contract()["field_limits"]["audit_limit_max"]
                .as_u64()
                .expect("validated audit maximum");
            if number.is_some_and(|number| (minimum..=maximum).contains(&number)) {
                Ok(())
            } else {
                Err(ProtocolError::new("request_invalid", Some(request_id)))
            }
        }
        "audit_offset" => {
            let maximum = contract()["field_limits"]["audit_offset_max"]
                .as_u64()
                .expect("validated audit offset maximum");
            if value.as_u64().is_some_and(|number| number <= maximum) {
                Ok(())
            } else {
                Err(ProtocolError::new("request_invalid", Some(request_id)))
            }
        }
        _ => Err(ProtocolError::new("operation_failed", Some(request_id))),
    }
}

pub fn validate_request(
    raw: &[u8],
    state: &mut ConnectionState,
    remote_tner: bool,
) -> Result<BrokerRequest, ProtocolError> {
    if !valid_role(&state.role)
        || !contract()["supported_protocol_versions"]
            .as_array()
            .is_some_and(|versions| {
                versions
                    .iter()
                    .any(|version| version.as_u64() == Some(state.protocol_version))
            })
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    if state.terminal {
        return Err(ProtocolError::new(
            contract()["connection_policy"]["terminal_error"]
                .as_str()
                .expect("validated terminal error"),
            None,
        ));
    }
    let connection_message_limit = contract()["field_limits"]["connection_messages"]
        .as_u64()
        .expect("validated connection message limit");
    if state.messages_seen >= connection_message_limit {
        state.terminal = true;
        return Err(ProtocolError::new(
            contract()["connection_policy"]["message_limit_error"]
                .as_str()
                .expect("validated message-limit error"),
            None,
        ));
    }
    state.messages_seen += 1;
    let initial_limit = if state.role == "desktop" {
        contract()["framing"]["max_frame_bytes"]
            .as_u64()
            .expect("validated frame limit")
    } else {
        contract()["framing"]["default_message_bytes"]
            .as_u64()
            .expect("validated message limit")
    };
    let message = parse_canonical_object_with_limit(raw, Some(initial_limit))?;
    let object = message.as_object().expect("parser requires object");
    let request_id = request_id_from(object)
        .ok_or_else(|| ProtocolError::new("request_invalid", None))?
        .to_owned();
    if state.seen_request_ids.contains(&request_id) {
        return Err(ProtocolError::new("request_invalid", Some(&request_id)));
    }
    state.seen_request_ids.insert(request_id.clone());
    let operation = object
        .get("operation")
        .and_then(Value::as_str)
        .filter(|value| valid_operation(value))
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request_id)))?
        .to_owned();
    let operation_spec = contract()["operations"]
        .get(&operation)
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request_id)))?;
    if !operation_allowed(&state.role, &operation) {
        return Err(ProtocolError::new("broker_unauthorized", Some(&request_id)));
    }
    let scope_rule = operation_spec["scope"]
        .as_str()
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request_id)))?;
    let fields = if scope_rule == "required" {
        vec![
            "broker_protocol_version",
            "operation",
            "payload",
            "request_id",
            "scope_id",
        ]
    } else {
        vec![
            "broker_protocol_version",
            "operation",
            "payload",
            "request_id",
        ]
    };
    exact_fields(object, &fields, Some(&request_id))?;
    if object["broker_protocol_version"].as_u64() != Some(state.protocol_version) {
        return Err(ProtocolError::new("broker_incompatible", Some(&request_id)));
    }
    let scope_id = if scope_rule == "required" {
        let scope = object
            .get("scope_id")
            .and_then(Value::as_str)
            .filter(|value| valid_id(value))
            .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request_id)))?;
        Some(scope.to_owned())
    } else {
        None
    };
    let request_limit = message_limit(&state.role, &operation, false)
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request_id)))?;
    if raw.len() as u64 > request_limit {
        return Err(ProtocolError::new("payload_too_large", Some(&request_id)));
    }
    let selected_deadline = deadline_ms(&operation, remote_tner).ok_or_else(|| {
        let code = if remote_tner {
            contract()["remote_tner_policy"]["unsupported_operation_error"]
                .as_str()
                .expect("validated remote TNER error")
        } else {
            "request_invalid"
        };
        ProtocolError::new(code, Some(&request_id))
    })?;
    let remote_tner_max_calls = if remote_tner {
        operation_spec["remote_tner_max_calls"]
            .as_u64()
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request_id)))?
    } else {
        0
    };
    let payload = object
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(&request_id)))?;
    let required = operation_spec["payload_required"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request_id)))?;
    let optional = operation_spec["payload_optional"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request_id)))?;
    if required.keys().any(|field| !payload.contains_key(field))
        || payload
            .keys()
            .any(|field| !required.contains_key(field) && !optional.contains_key(field))
    {
        return Err(ProtocolError::new("request_invalid", Some(&request_id)));
    }
    let remote_text_limit = uses_remote_tner_limit(operation_spec, remote_tner);
    let local_detection_phases = (!remote_tner)
        .then(|| operation_spec["local_detection_phases"].as_u64())
        .flatten();
    for (field, value) in payload {
        let kind = required
            .get(field)
            .or_else(|| optional.get(field))
            .and_then(Value::as_str)
            .ok_or_else(|| ProtocolError::new("operation_failed", Some(&request_id)))?;
        validate_payload_field(kind, value, &state.role, &request_id, remote_text_limit)?;
    }
    Ok(BrokerRequest {
        protocol_version: state.protocol_version,
        request_id,
        operation,
        scope_id,
        payload: Value::Object(payload.clone()),
        deadline_ms: Some(selected_deadline),
        local_detection_phases,
        local_intermediate_text_chars: local_detection_phases.filter(|phases| *phases > 0).map(
            |_| {
                contract()["field_limits"]["local_intermediate_text_chars"]
                    .as_u64()
                    .expect("validated local intermediate text limit")
            },
        ),
        remote_tner_max_calls,
        remote_tner_text_chars: (remote_tner && remote_tner_max_calls > 0).then(|| {
            contract()["field_limits"]["remote_tner_text_chars"]
                .as_u64()
                .expect("validated remote TNER text limit")
        }),
        replay: operation_spec["replay"]
            .as_str()
            .expect("validated replay policy")
            .to_owned(),
        uncertain_completion: operation_spec["uncertain_completion"]
            .as_str()
            .expect("validated completion policy")
            .to_owned(),
    })
}

pub fn error_message(
    code: &str,
    request_id: Option<&str>,
    protocol_version: u64,
) -> Result<Value, ProtocolError> {
    let code = safe_error_code(code);
    let request_id = request_id.filter(|value| valid_id(value));
    let version = if contract()["supported_protocol_versions"]
        .as_array()
        .is_some_and(|versions| {
            versions
                .iter()
                .any(|value| value.as_u64() == Some(protocol_version))
        }) {
        protocol_version
    } else {
        1
    };
    let retry = contract()["errors"][code]["retry"]
        .as_str()
        .ok_or_else(|| ProtocolError::new("operation_failed", request_id))?;
    Ok(serde_json::json!({
        "broker_protocol_version": version,
        "error": {
            "code": code,
            "retry": retry,
        },
        "request_id": request_id,
    }))
}

pub fn success_message(
    operation: &str,
    request_id: &str,
    result: Value,
    role: &str,
    protocol_version: u64,
) -> Result<Value, ProtocolError> {
    if !operation_allowed(role, operation) || !valid_id(request_id) {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    if !contract()["supported_protocol_versions"]
        .as_array()
        .is_some_and(|versions| {
            versions
                .iter()
                .any(|value| value.as_u64() == Some(protocol_version))
        })
    {
        return Err(ProtocolError::new("operation_failed", Some(request_id)));
    }
    let mut message = Map::new();
    message.insert(
        "broker_protocol_version".to_owned(),
        Value::from(protocol_version),
    );
    message.insert(
        "request_id".to_owned(),
        Value::String(request_id.to_owned()),
    );
    message.insert("result".to_owned(), result);
    let message = Value::Object(message);
    let encoded = canonical_json_bytes(&message)?;
    let limit = message_limit(role, operation, true)
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
    if encoded.len() as u64 > limit {
        return Err(ProtocolError::new("payload_too_large", Some(request_id)));
    }
    validate_result_schema(
        &message["result"],
        &contract()["operations"][operation]["result_schema"],
        request_id,
    )?;
    Ok(message)
}

pub fn validate_response(
    raw: &[u8],
    role: &str,
    operation: &str,
    request_id: &str,
) -> Result<Value, ProtocolError> {
    if !operation_allowed(role, operation) || !valid_id(request_id) {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let limit = message_limit(role, operation, true)
        .ok_or_else(|| ProtocolError::new("operation_failed", Some(request_id)))?;
    let message = parse_canonical_object_with_limit(raw, Some(limit))?;
    let object = message.as_object().expect("parser requires object");
    if object["broker_protocol_version"].as_u64() != Some(1)
        || object["request_id"].as_str() != Some(request_id)
    {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    let has_result = object.contains_key("result");
    let has_error = object.contains_key("error");
    if has_result == has_error {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    if has_result {
        exact_fields(
            object,
            &["broker_protocol_version", "request_id", "result"],
            Some(request_id),
        )?;
        validate_result_schema(
            &object["result"],
            &contract()["operations"][operation]["result_schema"],
            request_id,
        )?;
        return Ok(message);
    }

    exact_fields(
        object,
        &["broker_protocol_version", "error", "request_id"],
        Some(request_id),
    )?;
    let error = object["error"]
        .as_object()
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    exact_fields(error, &["code", "retry"], Some(request_id))?;
    let code = error["code"]
        .as_str()
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    let spec = contract()["errors"]
        .get(code)
        .ok_or_else(|| ProtocolError::new("request_invalid", Some(request_id)))?;
    if error["retry"].as_str() != spec["retry"].as_str() {
        return Err(ProtocolError::new("request_invalid", Some(request_id)));
    }
    Ok(message)
}

#[cfg(test)]
mod decoder_allocation_tests {
    use super::FrameDecoder;

    #[test]
    fn oversized_prefix_is_rejected_before_attached_body_is_buffered() {
        let mut decoder = FrameDecoder::new(Some(5)).unwrap();
        let mut chunk = 6_u32.to_be_bytes().to_vec();
        chunk.extend(std::iter::repeat_n(0xAA, 65_536));
        assert_eq!(
            decoder.feed(&chunk).unwrap_err().code(),
            "payload_too_large"
        );
        assert!(decoder.buffer.capacity() <= 8);
    }

    #[test]
    fn oversized_hello_prefix_is_rejected_before_attached_body_is_buffered() {
        let mut decoder = FrameDecoder::for_hello().unwrap();
        let mut chunk = 4097_u32.to_be_bytes().to_vec();
        chunk.extend(std::iter::repeat_n(0xAA, 65_536));
        assert_eq!(
            decoder.feed(&chunk).unwrap_err().code(),
            "payload_too_large"
        );
        assert!(decoder.buffer.capacity() <= 8);
    }
}
