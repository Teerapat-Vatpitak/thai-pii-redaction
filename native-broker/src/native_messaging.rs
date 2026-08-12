//! Strict Chrome Native Messaging framing and Extension scope projection.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::ffi::OsString;
use std::fmt;
use std::io::{Read, Write};
use std::path::PathBuf;

use serde::de::{Error as _, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{Map, Number, Value};

use crate::extension_client::{ExtensionBrokerClient, ExtensionClientError, ExtensionScopeKind};
use crate::manifest::NativeHostPolicy;
use crate::{canonical_json_bytes, safe_error_code, success_message};

pub const NATIVE_HOST_NAME: &str = "th.ac.psu.aiguard.native_host";
pub const NATIVE_MESSAGE_MAX_BYTES: u64 = 1_048_576;
const NATIVE_PROTOCOL_VERSION: u64 = 1;
const MAX_MESSAGES: usize = 4_096;
const MAX_SCOPES: usize = 32;
const MAX_TEXT_CHARS: usize = 200_000;
const MAX_CONTAINER_DEPTH: usize = 32;

#[derive(Clone, Eq, PartialEq)]
pub struct NativeMessagingError {
    code: String,
}

impl NativeMessagingError {
    fn new(code: &str) -> Self {
        Self {
            code: safe_error_code(code).to_owned(),
        }
    }

    pub fn code(&self) -> &str {
        &self.code
    }
}

impl fmt::Debug for NativeMessagingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeMessagingError")
            .field("code", &self.code)
            .finish()
    }
}

impl fmt::Display for NativeMessagingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.code)
    }
}

impl std::error::Error for NativeMessagingError {}

pub struct BrowserProcessEvidence {
    executable_name: String,
    same_user: bool,
    stable_process_reference: bool,
    guard: BrowserProcessGuard,
}

enum BrowserProcessGuard {
    Test,
    #[cfg(target_os = "linux")]
    Linux(std::os::fd::OwnedFd),
    #[cfg(target_os = "macos")]
    Macos {
        process_id: u32,
        start_seconds: u64,
        start_microseconds: u64,
    },
    #[cfg(windows)]
    Windows(Vec<windows_sys::Win32::Foundation::HANDLE>),
}

#[cfg(windows)]
unsafe impl Send for BrowserProcessGuard {}

#[cfg(windows)]
impl Drop for BrowserProcessGuard {
    fn drop(&mut self) {
        if let Self::Windows(handles) = self {
            for handle in handles.drain(..) {
                if !handle.is_null() {
                    // SAFETY: this variant owns each process handle.
                    unsafe { windows_sys::Win32::Foundation::CloseHandle(handle) };
                }
            }
        }
    }
}

impl BrowserProcessEvidence {
    #[doc(hidden)]
    pub fn for_test(
        executable_name: &str,
        same_user: bool,
        stable_process_reference: bool,
    ) -> Self {
        Self {
            executable_name: executable_name.to_owned(),
            same_user,
            stable_process_reference,
            guard: BrowserProcessGuard::Test,
        }
    }

    fn ensure_stable(&self) -> bool {
        match &self.guard {
            BrowserProcessGuard::Test => self.stable_process_reference,
            #[cfg(target_os = "linux")]
            BrowserProcessGuard::Linux(pidfd) => {
                use std::os::fd::AsRawFd;
                let mut descriptor = libc::pollfd {
                    fd: pidfd.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                };
                (unsafe { libc::poll(&mut descriptor, 1, 0) }) == 0
            }
            #[cfg(target_os = "macos")]
            BrowserProcessGuard::Macos {
                process_id,
                start_seconds,
                start_microseconds,
            } => macos_process_identity(*process_id).is_some_and(|identity| {
                identity.pbi_start_tvsec == *start_seconds
                    && identity.pbi_start_tvusec == *start_microseconds
            }),
            #[cfg(windows)]
            BrowserProcessGuard::Windows(handles) => {
                use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
                use windows_sys::Win32::System::Threading::WaitForSingleObject;
                !handles.is_empty()
                    && handles
                        .iter()
                        .all(|handle| unsafe { WaitForSingleObject(*handle, 0) } == WAIT_TIMEOUT)
            }
        }
    }
}

impl fmt::Debug for BrowserProcessEvidence {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BrowserProcessEvidence")
            .field("same_user", &self.same_user)
            .field("stable_process_reference", &self.stable_process_reference)
            .finish_non_exhaustive()
    }
}

pub fn validate_chrome_launch(
    arguments: &[OsString],
    policy: &NativeHostPolicy,
    browser: &BrowserProcessEvidence,
    windows: bool,
) -> Result<(), NativeMessagingError> {
    if policy.name() != NATIVE_HOST_NAME
        || !valid_extension_origin(policy.allowed_origin())
        || !matches!(
            policy.identity_classification(),
            "production_owner_approved" | "synthetic_test_only"
        )
        || !browser.same_user
        || !browser.stable_process_reference
        || !browser.ensure_stable()
        || !allowed_browser_name(&browser.executable_name, windows)
    {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let expected_length = if windows { 2 } else { 1 };
    if arguments.len() != expected_length
        || arguments[0].to_str() != Some(policy.allowed_origin())
        || windows && arguments[1].to_str() != Some("--parent-window=0")
    {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    Ok(())
}

pub fn inspect_browser_parent() -> Result<BrowserProcessEvidence, NativeMessagingError> {
    inspect_browser_parent_platform()
}

#[cfg(target_os = "linux")]
fn inspect_browser_parent_platform() -> Result<BrowserProcessEvidence, NativeMessagingError> {
    use std::os::fd::{FromRawFd, OwnedFd};
    use std::os::unix::fs::MetadataExt;

    let process_id = unsafe { libc::getppid() };
    if process_id <= 1 {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let process_root = PathBuf::from(format!("/proc/{process_id}"));
    let metadata = std::fs::metadata(&process_root)
        .map_err(|_| NativeMessagingError::new("broker_unauthorized"))?;
    let executable = std::fs::read_link(process_root.join("exe"))
        .map_err(|_| NativeMessagingError::new("broker_unauthorized"))?;
    let executable_name = executable
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| NativeMessagingError::new("broker_unauthorized"))?
        .to_owned();
    let pidfd_raw = unsafe { libc::syscall(libc::SYS_pidfd_open, process_id, 0) as libc::c_int };
    if pidfd_raw < 0 {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let pidfd = unsafe { OwnedFd::from_raw_fd(pidfd_raw) };
    let evidence = BrowserProcessEvidence {
        executable_name,
        same_user: metadata.uid() == unsafe { libc::geteuid() },
        stable_process_reference: true,
        guard: BrowserProcessGuard::Linux(pidfd),
    };
    if !evidence.ensure_stable() {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    Ok(evidence)
}

#[cfg(target_os = "macos")]
#[repr(C)]
struct MacosProcessIdentity {
    pbi_flags: u32,
    pbi_status: u32,
    pbi_xstatus: u32,
    pbi_pid: u32,
    pbi_ppid: u32,
    pbi_uid: u32,
    pbi_gid: u32,
    pbi_ruid: u32,
    pbi_rgid: u32,
    pbi_svuid: u32,
    pbi_svgid: u32,
    rfu_1: u32,
    pbi_comm: [u8; 16],
    pbi_name: [u8; 32],
    pbi_nfiles: u32,
    pbi_pgid: u32,
    pbi_pjobc: u32,
    e_tdev: u32,
    e_tpgid: u32,
    pbi_nice: i32,
    pbi_start_tvsec: u64,
    pbi_start_tvusec: u64,
}

#[cfg(target_os = "macos")]
fn macos_process_identity(process_id: u32) -> Option<MacosProcessIdentity> {
    const PROC_PIDTBSDINFO: libc::c_int = 3;
    #[link(name = "proc")]
    unsafe extern "C" {
        fn proc_pidinfo(
            pid: libc::c_int,
            flavor: libc::c_int,
            arg: u64,
            buffer: *mut libc::c_void,
            buffer_size: libc::c_int,
        ) -> libc::c_int;
    }
    let mut identity = std::mem::MaybeUninit::<MacosProcessIdentity>::zeroed();
    let expected = std::mem::size_of::<MacosProcessIdentity>();
    let read = unsafe {
        proc_pidinfo(
            process_id as libc::c_int,
            PROC_PIDTBSDINFO,
            0,
            identity.as_mut_ptr().cast(),
            expected as libc::c_int,
        )
    };
    (read as usize == expected).then(|| unsafe { identity.assume_init() })
}

#[cfg(target_os = "macos")]
fn inspect_browser_parent_platform() -> Result<BrowserProcessEvidence, NativeMessagingError> {
    const PROC_PIDPATHINFO_MAXSIZE: usize = 4096;
    #[link(name = "proc")]
    unsafe extern "C" {
        fn proc_pidpath(
            pid: libc::c_int,
            buffer: *mut libc::c_void,
            buffer_size: u32,
        ) -> libc::c_int;
    }
    let process_id = unsafe { libc::getppid() };
    if process_id <= 1 {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let identity = macos_process_identity(process_id as u32)
        .ok_or_else(|| NativeMessagingError::new("broker_unauthorized"))?;
    let mut buffer = vec![0_u8; PROC_PIDPATHINFO_MAXSIZE];
    let length =
        unsafe { proc_pidpath(process_id, buffer.as_mut_ptr().cast(), buffer.len() as u32) };
    if length <= 0 || length as usize >= buffer.len() {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    buffer.truncate(length as usize);
    let executable = std::str::from_utf8(&buffer)
        .map(PathBuf::from)
        .map_err(|_| NativeMessagingError::new("broker_unauthorized"))?;
    let executable_name = executable
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| NativeMessagingError::new("broker_unauthorized"))?
        .to_owned();
    let evidence = BrowserProcessEvidence {
        executable_name,
        same_user: identity.pbi_uid == unsafe { libc::geteuid() },
        stable_process_reference: true,
        guard: BrowserProcessGuard::Macos {
            process_id: process_id as u32,
            start_seconds: identity.pbi_start_tvsec,
            start_microseconds: identity.pbi_start_tvusec,
        },
    };
    if !evidence.ensure_stable() {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    Ok(evidence)
}

#[cfg(windows)]
fn inspect_browser_parent_platform() -> Result<BrowserProcessEvidence, NativeMessagingError> {
    use windows_sys::Win32::Foundation::{CloseHandle, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };
    use windows_sys::Win32::System::Threading::{
        GetCurrentProcessId, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;

    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..PROCESSENTRY32W::default()
    };
    let current = unsafe { GetCurrentProcessId() };
    let mut parents = HashMap::new();
    let mut ok = unsafe { Process32FirstW(snapshot, &mut entry) };
    while ok != 0 {
        parents.insert(entry.th32ProcessID, entry.th32ParentProcessID);
        ok = unsafe { Process32NextW(snapshot, &mut entry) };
    }
    unsafe { CloseHandle(snapshot) };
    let parent_id = parents.get(&current).copied().unwrap_or(0);
    if parent_id == 0 {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let parent_process = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_ACCESS,
            0,
            parent_id,
        )
    };
    if parent_process.is_null() {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    let (parent_name, parent_same_user) = match inspect_windows_process(parent_process) {
        Ok(value) => value,
        Err(error) => {
            unsafe { CloseHandle(parent_process) };
            return Err(error);
        }
    };
    let (executable_name, same_user, handles) = if parent_name.eq_ignore_ascii_case("cmd.exe") {
        let browser_id = parents.get(&parent_id).copied().unwrap_or(0);
        if browser_id == 0 {
            unsafe { CloseHandle(parent_process) };
            return Err(NativeMessagingError::new("broker_unauthorized"));
        }
        let browser_process = unsafe {
            OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_ACCESS,
                0,
                browser_id,
            )
        };
        if browser_process.is_null() {
            unsafe { CloseHandle(parent_process) };
            return Err(NativeMessagingError::new("broker_unauthorized"));
        }
        let (browser_name, browser_same_user) = match inspect_windows_process(browser_process) {
            Ok(value) => value,
            Err(error) => {
                unsafe {
                    CloseHandle(parent_process);
                    CloseHandle(browser_process);
                }
                return Err(error);
            }
        };
        (
            browser_name,
            parent_same_user && browser_same_user,
            vec![parent_process, browser_process],
        )
    } else {
        (parent_name, parent_same_user, vec![parent_process])
    };
    let evidence = BrowserProcessEvidence {
        executable_name,
        same_user,
        stable_process_reference: true,
        guard: BrowserProcessGuard::Windows(handles),
    };
    if !evidence.ensure_stable() {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    Ok(evidence)
}

#[cfg(windows)]
fn inspect_windows_process(
    process: windows_sys::Win32::Foundation::HANDLE,
) -> Result<(String, bool), NativeMessagingError> {
    use std::os::windows::ffi::OsStringExt;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::Security::{EqualSid, TOKEN_USER};
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, QueryFullProcessImageNameW};

    let mut buffer = vec![0_u16; 32_768];
    let mut length = buffer.len() as u32;
    if unsafe { QueryFullProcessImageNameW(process, 0, buffer.as_mut_ptr(), &mut length) } == 0
        || length == 0
    {
        return Err(NativeMessagingError::new("broker_unauthorized"));
    }
    buffer.truncate(length as usize);
    let path = PathBuf::from(std::ffi::OsString::from_wide(&buffer));
    let executable_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| NativeMessagingError::new("broker_unauthorized"))?
        .to_owned();

    fn token_user(
        process: windows_sys::Win32::Foundation::HANDLE,
    ) -> Result<(windows_sys::Win32::Foundation::HANDLE, Vec<usize>), NativeMessagingError> {
        use windows_sys::Win32::Foundation::CloseHandle;
        use windows_sys::Win32::Security::{GetTokenInformation, TokenUser, TOKEN_QUERY};
        use windows_sys::Win32::System::Threading::OpenProcessToken;
        let mut token = std::ptr::null_mut();
        if unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut token) } == 0 {
            return Err(NativeMessagingError::new("broker_unauthorized"));
        }
        let mut needed = 0_u32;
        unsafe { GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed) };
        if needed == 0 || needed > 1024 * 1024 {
            unsafe { CloseHandle(token) };
            return Err(NativeMessagingError::new("broker_unauthorized"));
        }
        let mut words = vec![0_usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
        if unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                words.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } == 0
        {
            unsafe { CloseHandle(token) };
            return Err(NativeMessagingError::new("broker_unauthorized"));
        }
        Ok((token, words))
    }

    let (parent_token, parent_user) = token_user(process)?;
    let (current_token, current_user) = match token_user(unsafe { GetCurrentProcess() }) {
        Ok(value) => value,
        Err(error) => {
            unsafe { CloseHandle(parent_token) };
            return Err(error);
        }
    };
    let parent_sid = unsafe { (*(parent_user.as_ptr().cast::<TOKEN_USER>())).User.Sid };
    let current_sid = unsafe { (*(current_user.as_ptr().cast::<TOKEN_USER>())).User.Sid };
    let same_user = unsafe { EqualSid(parent_sid, current_sid) } != 0;
    unsafe {
        CloseHandle(parent_token);
        CloseHandle(current_token);
    }
    Ok((executable_name, same_user))
}

fn valid_extension_origin(origin: &str) -> bool {
    let bytes = origin.as_bytes();
    let prefix = b"chrome-extension://";
    bytes.len() == prefix.len() + 32 + 1
        && bytes.starts_with(prefix)
        && bytes.ends_with(b"/")
        && bytes[prefix.len()..prefix.len() + 32]
            .iter()
            .all(|byte| (b'a'..=b'p').contains(byte))
}

fn allowed_browser_name(name: &str, windows: bool) -> bool {
    if windows {
        matches!(
            name.to_ascii_lowercase().as_str(),
            "chrome.exe" | "chromium.exe"
        )
    } else {
        matches!(
            name,
            "Google Chrome"
                | "Google Chrome for Testing"
                | "Chromium"
                | "chrome"
                | "chrome-wrapper"
                | "chromium"
                | "chromium-browser"
                | "google-chrome"
                | "google-chrome-stable"
        )
    }
}

pub trait ExtensionBroker {
    fn health(&mut self) -> Result<(), ExtensionClientError>;
    fn open_scope(
        &mut self,
        scope_kind: ExtensionScopeKind,
    ) -> Result<String, ExtensionClientError>;
    fn close_scope(&mut self, scope_id: &str) -> Result<(), ExtensionClientError>;
    fn sanitize(
        &mut self,
        scope_id: &str,
        text: &str,
        mode: &str,
        session_id: Option<&str>,
    ) -> Result<Value, ExtensionClientError>;
    fn reidentify(
        &mut self,
        scope_id: &str,
        session_id: &str,
        text: &str,
    ) -> Result<Value, ExtensionClientError>;
    fn disconnect(&mut self);
}

impl ExtensionBroker for ExtensionBrokerClient {
    fn health(&mut self) -> Result<(), ExtensionClientError> {
        ExtensionBrokerClient::health(self)
    }

    fn open_scope(
        &mut self,
        scope_kind: ExtensionScopeKind,
    ) -> Result<String, ExtensionClientError> {
        ExtensionBrokerClient::open_scope(self, scope_kind)
    }

    fn close_scope(&mut self, scope_id: &str) -> Result<(), ExtensionClientError> {
        ExtensionBrokerClient::close_scope(self, scope_id)
    }

    fn sanitize(
        &mut self,
        scope_id: &str,
        text: &str,
        mode: &str,
        session_id: Option<&str>,
    ) -> Result<Value, ExtensionClientError> {
        ExtensionBrokerClient::sanitize(self, scope_id, text, mode, session_id)
    }

    fn reidentify(
        &mut self,
        scope_id: &str,
        session_id: &str,
        text: &str,
    ) -> Result<Value, ExtensionClientError> {
        ExtensionBrokerClient::reidentify(self, scope_id, session_id, text)
    }

    fn disconnect(&mut self) {
        ExtensionBrokerClient::disconnect(self);
    }
}

struct ScopeState {
    broker_scope_id: String,
    session_id: Option<String>,
}

pub struct NativeMessagingSession<B: ExtensionBroker> {
    broker: B,
    product_version: String,
    request_ids: HashSet<String>,
    scopes: HashMap<String, ScopeState>,
    disconnected: bool,
}

impl<B: ExtensionBroker> NativeMessagingSession<B> {
    pub fn new(broker: B, product_version: &str) -> Result<Self, NativeMessagingError> {
        if !valid_product_version(product_version) {
            return Err(NativeMessagingError::new("broker_incompatible"));
        }
        Ok(Self {
            broker,
            product_version: product_version.to_owned(),
            request_ids: HashSet::new(),
            scopes: HashMap::new(),
            disconnected: false,
        })
    }

    #[doc(hidden)]
    pub fn broker_for_test(&self) -> &B {
        &self.broker
    }

    fn handle(&mut self, raw: &[u8]) -> Result<HandledResponse, NativeMessagingError> {
        if self.disconnected || self.request_ids.len() >= MAX_MESSAGES {
            return Err(NativeMessagingError::new("broker_busy"));
        }
        let request = parse_request(raw)?;
        let request_id = request.request_id().to_owned();
        if !self.request_ids.insert(request_id.clone()) {
            return Err(NativeMessagingError::new("request_invalid"));
        }
        let handled = match request {
            NativeRequest::Health { .. } => match self.broker.health() {
                Ok(()) => HandledResponse::success(
                    &request_id,
                    serde_json::json!({
                        "product_version": self.product_version,
                        "status": "ok"
                    }),
                ),
                Err(error) => self.broker_error(&request_id, error, false),
            },
            NativeRequest::ScopeOpen {
                context_id,
                scope_kind,
                ..
            } => {
                if self.scopes.contains_key(&context_id) || self.scopes.len() >= MAX_SCOPES {
                    HandledResponse::error(&request_id, "broker_busy", false)
                } else {
                    let protocol_kind = match scope_kind.as_str() {
                        "tab" => ExtensionScopeKind::Tab,
                        "panel" => ExtensionScopeKind::Panel,
                        _ => return Err(NativeMessagingError::new("request_invalid")),
                    };
                    match self.broker.open_scope(protocol_kind) {
                        Ok(broker_scope_id) => {
                            self.scopes.insert(
                                context_id,
                                ScopeState {
                                    broker_scope_id,
                                    session_id: None,
                                },
                            );
                            HandledResponse::success(
                                &request_id,
                                serde_json::json!({"status": "ready"}),
                            )
                        }
                        Err(error) => self.broker_error(&request_id, error, true),
                    }
                }
            }
            NativeRequest::Sanitize {
                context_id,
                text,
                mode,
                ..
            } => {
                let Some(scope) = self.scopes.get_mut(&context_id) else {
                    return Ok(HandledResponse::error(
                        &request_id,
                        "session_unavailable",
                        false,
                    ));
                };
                let result = self.broker.sanitize(
                    &scope.broker_scope_id,
                    &text,
                    &mode,
                    scope.session_id.as_deref(),
                );
                match result {
                    Ok(result) => match validated_result("sanitize", result) {
                        Ok(mut result) => {
                            let session_id = result
                                .as_object_mut()
                                .and_then(|object| object.remove("session_id"))
                                .and_then(|value| value.as_str().map(str::to_owned))
                                .ok_or_else(|| NativeMessagingError::new("operation_failed"))?;
                            scope.session_id = Some(session_id);
                            HandledResponse::success(&request_id, result)
                        }
                        Err(error) if error.code() == "payload_too_large" => {
                            self.disconnect();
                            HandledResponse::error(&request_id, error.code(), true)
                        }
                        Err(error) => {
                            self.disconnect();
                            return Err(error);
                        }
                    },
                    Err(error) => {
                        if error.session_invalidated() {
                            scope.session_id = None;
                        }
                        let terminal = error.connection_invalidated();
                        HandledResponse::error(&request_id, error.code(), terminal)
                    }
                }
            }
            NativeRequest::Reidentify {
                context_id, text, ..
            } => {
                let Some(scope) = self.scopes.get_mut(&context_id) else {
                    return Ok(HandledResponse::error(
                        &request_id,
                        "session_unavailable",
                        false,
                    ));
                };
                let Some(session_id) = scope.session_id.clone() else {
                    return Ok(HandledResponse::error(
                        &request_id,
                        "session_unavailable",
                        false,
                    ));
                };
                match self
                    .broker
                    .reidentify(&scope.broker_scope_id, &session_id, &text)
                {
                    Ok(result) => match validated_result("reidentify", result) {
                        Ok(result) => HandledResponse::success(&request_id, result),
                        Err(error) if error.code() == "payload_too_large" => {
                            self.disconnect();
                            HandledResponse::error(&request_id, error.code(), true)
                        }
                        Err(error) => {
                            self.disconnect();
                            return Err(error);
                        }
                    },
                    Err(error) => {
                        if error.session_invalidated() {
                            scope.session_id = None;
                        }
                        let terminal = error.connection_invalidated();
                        HandledResponse::error(&request_id, error.code(), terminal)
                    }
                }
            }
            NativeRequest::ScopeClose { context_id, .. } => {
                let Some(scope) = self.scopes.remove(&context_id) else {
                    return Ok(HandledResponse::error(
                        &request_id,
                        "session_unavailable",
                        false,
                    ));
                };
                match self.broker.close_scope(&scope.broker_scope_id) {
                    Ok(()) => {
                        HandledResponse::success(&request_id, serde_json::json!({"closed": true}))
                    }
                    Err(error) => {
                        self.disconnect();
                        HandledResponse::error(&request_id, error.code(), true)
                    }
                }
            }
        };
        Ok(handled)
    }

    fn broker_error(
        &mut self,
        request_id: &str,
        error: ExtensionClientError,
        lifecycle: bool,
    ) -> HandledResponse {
        let terminal = lifecycle || error.connection_invalidated();
        if terminal {
            self.disconnect();
        }
        HandledResponse::error(request_id, error.code(), terminal)
    }

    fn disconnect(&mut self) {
        if !self.disconnected {
            self.disconnected = true;
            self.scopes.clear();
            self.broker.disconnect();
        }
    }
}

impl<B: ExtensionBroker> Drop for NativeMessagingSession<B> {
    fn drop(&mut self) {
        self.disconnect();
    }
}

struct HandledResponse {
    request_id: String,
    value: Value,
    terminal: bool,
}

impl HandledResponse {
    fn success(request_id: &str, result: Value) -> Self {
        Self {
            request_id: request_id.to_owned(),
            value: serde_json::json!({
                "native_protocol_version": NATIVE_PROTOCOL_VERSION,
                "ok": true,
                "request_id": request_id,
                "result": result
            }),
            terminal: false,
        }
    }

    fn error(request_id: &str, code: &str, terminal: bool) -> Self {
        Self {
            request_id: request_id.to_owned(),
            value: fixed_error_response(request_id, code),
            terminal,
        }
    }
}

fn fixed_error_response(request_id: &str, code: &str) -> Value {
    serde_json::json!({
        "error": {"code": safe_error_code(code)},
        "native_protocol_version": NATIVE_PROTOCOL_VERSION,
        "ok": false,
        "request_id": request_id
    })
}

fn validated_result(operation: &str, result: Value) -> Result<Value, NativeMessagingError> {
    let encoded =
        canonical_json_bytes(&result).map_err(|error| NativeMessagingError::new(error.code()))?;
    if encoded.len() as u64 > NATIVE_MESSAGE_MAX_BYTES {
        return Err(NativeMessagingError::new("payload_too_large"));
    }
    success_message(operation, "adapter-validation", result, "extension", 1)
        .map(|message| message["result"].clone())
        .map_err(|error| NativeMessagingError::new(error.code()))
}

pub fn process_native_messages<R: Read, W: Write, B: ExtensionBroker>(
    mut reader: R,
    mut writer: W,
    session: &mut NativeMessagingSession<B>,
) -> Result<(), NativeMessagingError> {
    loop {
        let Some(raw) = read_native_frame(&mut reader)? else {
            session.disconnect();
            return Ok(());
        };
        let response = match session.handle(&raw) {
            Ok(response) => response,
            Err(error) => {
                session.disconnect();
                return Err(error);
            }
        };
        let mut bytes = canonical_json_bytes(&response.value)
            .map_err(|error| NativeMessagingError::new(error.code()))?;
        let terminal = if bytes.len() as u64 > NATIVE_MESSAGE_MAX_BYTES {
            session.disconnect();
            bytes = canonical_json_bytes(&fixed_error_response(
                &response.request_id,
                "payload_too_large",
            ))
            .map_err(|error| NativeMessagingError::new(error.code()))?;
            true
        } else {
            response.terminal
        };
        write_native_frame(&mut writer, &bytes)?;
        if terminal {
            session.disconnect();
            return Err(NativeMessagingError::new("broker_unavailable"));
        }
    }
}

fn read_native_frame<R: Read>(reader: &mut R) -> Result<Option<Vec<u8>>, NativeMessagingError> {
    let mut header = [0_u8; 4];
    let mut read = 0;
    while read < header.len() {
        match reader.read(&mut header[read..]) {
            Ok(0) if read == 0 => return Ok(None),
            Ok(0) => return Err(NativeMessagingError::new("request_invalid")),
            Ok(count) => read += count,
            Err(_) => return Err(NativeMessagingError::new("request_invalid")),
        }
    }
    let length = u32::from_ne_bytes(header) as u64;
    if length == 0 {
        return Err(NativeMessagingError::new("request_invalid"));
    }
    if length > NATIVE_MESSAGE_MAX_BYTES {
        return Err(NativeMessagingError::new("payload_too_large"));
    }
    let mut body = vec![0_u8; length as usize];
    let mut read = 0;
    while read < body.len() {
        match reader.read(&mut body[read..]) {
            Ok(0) => return Err(NativeMessagingError::new("request_invalid")),
            Ok(count) => read += count,
            Err(_) => return Err(NativeMessagingError::new("request_invalid")),
        }
    }
    Ok(Some(body))
}

fn write_native_frame<W: Write>(writer: &mut W, body: &[u8]) -> Result<(), NativeMessagingError> {
    if body.is_empty() || body.len() as u64 > NATIVE_MESSAGE_MAX_BYTES {
        return Err(NativeMessagingError::new("payload_too_large"));
    }
    let length =
        u32::try_from(body.len()).map_err(|_| NativeMessagingError::new("payload_too_large"))?;
    writer
        .write_all(&length.to_ne_bytes())
        .and_then(|()| writer.write_all(body))
        .and_then(|()| writer.flush())
        .map_err(|_| NativeMessagingError::new("broker_unavailable"))
}

enum NativeRequest {
    Health {
        request_id: String,
    },
    ScopeOpen {
        request_id: String,
        context_id: String,
        scope_kind: String,
    },
    Sanitize {
        request_id: String,
        context_id: String,
        text: String,
        mode: String,
    },
    Reidentify {
        request_id: String,
        context_id: String,
        text: String,
    },
    ScopeClose {
        request_id: String,
        context_id: String,
    },
}

impl NativeRequest {
    fn request_id(&self) -> &str {
        match self {
            Self::Health { request_id }
            | Self::ScopeOpen { request_id, .. }
            | Self::Sanitize { request_id, .. }
            | Self::Reidentify { request_id, .. }
            | Self::ScopeClose { request_id, .. } => request_id,
        }
    }
}

fn parse_request(raw: &[u8]) -> Result<NativeRequest, NativeMessagingError> {
    let value = parse_unique_json(raw)?;
    validate_depth(&value, 1)?;
    let object = value
        .as_object()
        .ok_or_else(|| NativeMessagingError::new("request_invalid"))?;
    let version = object
        .get("native_protocol_version")
        .and_then(Value::as_u64)
        .ok_or_else(|| NativeMessagingError::new("request_invalid"))?;
    if version != NATIVE_PROTOCOL_VERSION {
        return Err(NativeMessagingError::new("broker_incompatible"));
    }
    let operation = string_field(object, "operation")?;
    let request_id = string_field(object, "request_id")?;
    if !valid_id(request_id) {
        return Err(NativeMessagingError::new("request_invalid"));
    }
    let payload = object
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| NativeMessagingError::new("request_invalid"))?;
    match operation {
        "health" => {
            exact_fields(
                object,
                &[
                    "native_protocol_version",
                    "operation",
                    "payload",
                    "request_id",
                ],
            )?;
            exact_fields(payload, &[])?;
            Ok(NativeRequest::Health {
                request_id: request_id.to_owned(),
            })
        }
        "scope_open" => {
            exact_fields(
                object,
                &[
                    "context_id",
                    "native_protocol_version",
                    "operation",
                    "payload",
                    "request_id",
                ],
            )?;
            exact_fields(payload, &["scope_kind"])?;
            let context_id = checked_context(object)?;
            let scope_kind = string_field(payload, "scope_kind")?;
            if !matches!(scope_kind, "tab" | "panel") {
                return Err(NativeMessagingError::new("request_invalid"));
            }
            Ok(NativeRequest::ScopeOpen {
                request_id: request_id.to_owned(),
                context_id,
                scope_kind: scope_kind.to_owned(),
            })
        }
        "sanitize" => {
            exact_fields(
                object,
                &[
                    "context_id",
                    "native_protocol_version",
                    "operation",
                    "payload",
                    "request_id",
                ],
            )?;
            exact_fields(payload, &["mode", "text"])?;
            let context_id = checked_context(object)?;
            let text = checked_text(payload)?;
            let mode = string_field(payload, "mode")?;
            if !matches!(mode, "token" | "surrogate") {
                return Err(NativeMessagingError::new("request_invalid"));
            }
            Ok(NativeRequest::Sanitize {
                request_id: request_id.to_owned(),
                context_id,
                text,
                mode: mode.to_owned(),
            })
        }
        "reidentify" => {
            exact_fields(
                object,
                &[
                    "context_id",
                    "native_protocol_version",
                    "operation",
                    "payload",
                    "request_id",
                ],
            )?;
            exact_fields(payload, &["text"])?;
            Ok(NativeRequest::Reidentify {
                request_id: request_id.to_owned(),
                context_id: checked_context(object)?,
                text: checked_text(payload)?,
            })
        }
        "scope_close" => {
            exact_fields(
                object,
                &[
                    "context_id",
                    "native_protocol_version",
                    "operation",
                    "payload",
                    "request_id",
                ],
            )?;
            exact_fields(payload, &[])?;
            Ok(NativeRequest::ScopeClose {
                request_id: request_id.to_owned(),
                context_id: checked_context(object)?,
            })
        }
        _ => Err(NativeMessagingError::new("request_invalid")),
    }
}

fn exact_fields(
    object: &Map<String, Value>,
    expected: &[&str],
) -> Result<(), NativeMessagingError> {
    if object.len() != expected.len() || !expected.iter().all(|field| object.contains_key(*field)) {
        return Err(NativeMessagingError::new("request_invalid"));
    }
    Ok(())
}

fn string_field<'a>(
    object: &'a Map<String, Value>,
    field: &str,
) -> Result<&'a str, NativeMessagingError> {
    object
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| NativeMessagingError::new("request_invalid"))
}

fn checked_context(object: &Map<String, Value>) -> Result<String, NativeMessagingError> {
    let context = string_field(object, "context_id")?;
    if !valid_id(context) {
        return Err(NativeMessagingError::new("request_invalid"));
    }
    Ok(context.to_owned())
}

fn checked_text(payload: &Map<String, Value>) -> Result<String, NativeMessagingError> {
    let text = string_field(payload, "text")?;
    if text.chars().count() > MAX_TEXT_CHARS {
        return Err(NativeMessagingError::new("payload_too_large"));
    }
    Ok(text.to_owned())
}

fn valid_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=128).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}

fn valid_product_version(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'+' | b'-'))
}

fn validate_depth(value: &Value, depth: usize) -> Result<(), NativeMessagingError> {
    if depth > MAX_CONTAINER_DEPTH {
        return Err(NativeMessagingError::new("request_invalid"));
    }
    match value {
        Value::Array(values) => {
            for value in values {
                validate_depth(value, depth + 1)?;
            }
        }
        Value::Object(values) => {
            for value in values.values() {
                validate_depth(value, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}

struct UniqueValue(Value);

impl<'de> Deserialize<'de> for UniqueValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(UniqueVisitor)
    }
}

struct UniqueVisitor;

impl<'de> Visitor<'de> for UniqueVisitor {
    type Value = UniqueValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON value without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(Number::from(value))))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Number(Number::from(value))))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Number::from_f64(value)
            .map(Value::Number)
            .map(UniqueValue)
            .ok_or_else(|| E::custom("invalid JSON number"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Ok(UniqueValue(Value::String(value.to_owned())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(UniqueValue(Value::Null))
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<UniqueValue>()? {
            values.push(value.0);
        }
        Ok(UniqueValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = BTreeMap::new();
        while let Some(key) = map.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(A::Error::custom("duplicate JSON field"));
            }
            values.insert(key, map.next_value::<UniqueValue>()?.0);
        }
        Ok(UniqueValue(Value::Object(values.into_iter().collect())))
    }
}

fn parse_unique_json(raw: &[u8]) -> Result<Value, NativeMessagingError> {
    std::str::from_utf8(raw).map_err(|_| NativeMessagingError::new("request_invalid"))?;
    let mut deserializer = serde_json::Deserializer::from_slice(raw);
    let value = UniqueValue::deserialize(&mut deserializer)
        .map_err(|_| NativeMessagingError::new("request_invalid"))?;
    deserializer
        .end()
        .map_err(|_| NativeMessagingError::new("request_invalid"))?;
    Ok(value.0)
}
