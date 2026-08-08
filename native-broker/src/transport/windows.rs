use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::ptr::null_mut;
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};
use windows_sys::Win32::Foundation::{
    CloseHandle, GetLastError, LocalFree, ERROR_ALREADY_EXISTS, ERROR_BROKEN_PIPE, ERROR_NO_DATA,
    ERROR_PIPE_BUSY, ERROR_PIPE_CONNECTED, ERROR_PIPE_LISTENING, GENERIC_READ, GENERIC_WRITE,
    HANDLE, INVALID_HANDLE_VALUE, WAIT_TIMEOUT,
};
use windows_sys::Win32::Security::Authorization::{
    ConvertSidToStringSidW, ConvertStringSecurityDescriptorToSecurityDescriptorW,
    ConvertStringSidToSidW, GetSecurityInfo, SE_KERNEL_OBJECT,
};
use windows_sys::Win32::Security::{
    AclSizeInformation, EqualSid, GetAce, GetAclInformation, GetSecurityDescriptorControl,
    GetTokenInformation, TokenGroups, TokenStatistics, TokenUser, ACCESS_ALLOWED_ACE,
    ACL_SIZE_INFORMATION, DACL_SECURITY_INFORMATION, SECURITY_ATTRIBUTES, SE_DACL_PROTECTED,
    TOKEN_GROUPS, TOKEN_QUERY, TOKEN_STATISTICS, TOKEN_USER,
};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, ReadFile, WriteFile, FILE_ATTRIBUTE_NORMAL, FILE_FLAG_FIRST_PIPE_INSTANCE,
    OPEN_EXISTING, PIPE_ACCESS_DUPLEX, SECURITY_IDENTIFICATION, SECURITY_SQOS_PRESENT,
};
use windows_sys::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, GetNamedPipeClientProcessId,
    GetNamedPipeServerProcessId, PeekNamedPipe, WaitNamedPipeW, PIPE_NOWAIT, PIPE_READMODE_BYTE,
    PIPE_REJECT_REMOTE_CLIENTS, PIPE_TYPE_BYTE,
};
use windows_sys::Win32::System::Threading::{
    CreateMutexW, GetCurrentProcess, OpenProcess, OpenProcessToken, QueryFullProcessImageNameW,
    WaitForSingleObject, PROCESS_QUERY_LIMITED_INFORMATION,
};

use crate::admission::{BrokerOsContext, OsPeerContext};
use crate::transport::{EndpointSecurityReport, ReadOutcome, MAX_ACTIVE_CONNECTIONS};
use crate::ProtocolError;

const SE_GROUP_LOGON_ID: u32 = 0xC000_0000;
const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;
const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const MUTEX_LOGON_ACCESS: u32 = 0x0002_0001;
const PIPE_LOGON_ACCESS: u32 = 0x0012_019f;
// Keep bounded kernel room for one rejected client and the next listener.
const MAX_PIPE_INSTANCES: u32 = (MAX_ACTIVE_CONNECTIONS + 2) as u32;

pub(crate) struct WindowsEndpoint {
    pending_pipe: HANDLE,
    mutex: HANDLE,
    name: String,
    logon_sid: String,
    acl_verified: bool,
}

pub(crate) struct WindowsEndpointReservation {
    mutex: HANDLE,
    name: String,
    logon_sid: String,
}

// Endpoint handles are uniquely owned and the complete endpoint moves to the
// broker thread before it accepts connections.
unsafe impl Send for WindowsEndpoint {}
unsafe impl Send for WindowsEndpointReservation {}

impl WindowsEndpoint {
    pub(crate) fn current_context() -> Result<BrokerOsContext, ProtocolError> {
        let identity = token_identity_for_process(unsafe { GetCurrentProcess() })?;
        Ok(BrokerOsContext {
            user_boundary: identity.user_sid,
            logon_session: identity.logon_sid,
        })
    }

    pub(crate) fn default_runtime_root(install_root: &Path) -> Result<PathBuf, ProtocolError> {
        if install_root.as_os_str().is_empty() || !install_root.is_absolute() {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        // Windows uses this only as a stable namespace seed. Keeping it
        // install-independent makes one endpoint/mutex own the complete logon.
        Ok(PathBuf::from(r"C:\AI-Guard-Native-Broker-v1"))
    }

    pub(crate) fn publication_for(root: &Path) -> Result<String, ProtocolError> {
        if root.as_os_str().is_empty() || !root.is_absolute() {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let identity = token_identity_for_process(unsafe { GetCurrentProcess() })?;
        let suffix = stable_endpoint_suffix(root, &identity.logon_sid);
        Ok(format!(r"\\.\pipe\AI-Guard-Native-Broker-{suffix}"))
    }

    pub(crate) fn reserve(root: &Path) -> Result<WindowsEndpointReservation, ProtocolError> {
        WindowsEndpointReservation::reserve(root)
    }

    pub(crate) fn accept(
        &mut self,
        timeout: Duration,
    ) -> Result<
        Option<(
            WindowsNativeStream,
            OsPeerContext,
            PathBuf,
            WindowsPeerGuard,
        )>,
        ProtocolError,
    > {
        if timeout.is_zero() {
            return Ok(None);
        }
        if !verify_logon_sid_only_dacl(self.pending_pipe, &self.logon_sid, PIPE_LOGON_ACCESS) {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let deadline = Instant::now() + timeout;
        loop {
            // SAFETY: pending_pipe is a live server pipe and non-overlapped mode uses null.
            let connected = unsafe { ConnectNamedPipe(self.pending_pipe, null_mut()) } != 0;
            let error = if connected {
                0
            } else {
                unsafe { GetLastError() }
            };
            if connected || error == ERROR_PIPE_CONNECTED {
                let connected_pipe = self.pending_pipe;
                self.pending_pipe = create_pipe(&self.name, &self.logon_sid, false)?;
                match inspect_named_pipe_peer(connected_pipe, true) {
                    Ok((context, executable, guard)) => {
                        return Ok(Some((
                            WindowsNativeStream {
                                handle: connected_pipe,
                                server_side: true,
                            },
                            context,
                            executable,
                            guard,
                        )));
                    }
                    Err(error) => {
                        unsafe {
                            DisconnectNamedPipe(connected_pipe);
                            CloseHandle(connected_pipe);
                        }
                        return Err(error);
                    }
                }
            }
            if error == ERROR_NO_DATA {
                // A client can connect and close before the accept loop starts.
                // Reset this instance before polling again.
                unsafe { DisconnectNamedPipe(self.pending_pipe) };
            } else if error != ERROR_PIPE_LISTENING {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            if Instant::now() >= deadline {
                return Ok(None);
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }

    pub(crate) fn broker_context(&self) -> Result<BrokerOsContext, ProtocolError> {
        Self::current_context()
    }

    pub(crate) fn security_report(&self) -> EndpointSecurityReport {
        EndpointSecurityReport {
            os_user_isolated: self.acl_verified,
            peer_credentials_required: true,
            single_instance_held: !self.mutex.is_null(),
            remote_clients_rejected: true,
            runtime_directory_mode: None,
            endpoint_mode: None,
            uses_abstract_socket: false,
            explicit_dacl: self.acl_verified,
            current_logon_sid_only: self.acl_verified,
            client_pid_inspection: true,
        }
    }

    pub(crate) fn publication(&self) -> String {
        self.name.clone()
    }

    pub(crate) fn filesystem_path(&self) -> Option<&Path> {
        None
    }
}

impl WindowsEndpointReservation {
    fn reserve(root: &Path) -> Result<Self, ProtocolError> {
        if root.as_os_str().is_empty() || !root.is_absolute() {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let identity = token_identity_for_process(unsafe { GetCurrentProcess() })?;
        let name = WindowsEndpoint::publication_for(root)?;
        let suffix = name
            .rsplit('-')
            .next()
            .ok_or_else(|| ProtocolError::new("broker_unavailable", None))?;
        let mutex_name = format!(r"Local\AI-Guard-Native-Broker-{suffix}");
        let descriptor = ExplicitDescriptor::for_logon_sid(&identity.logon_sid)?;
        let mutex_wide = wide(&mutex_name);
        // SAFETY: descriptor and NUL-terminated name remain live for this call.
        let mutex = unsafe { CreateMutexW(descriptor.attributes(), 1, mutex_wide.as_ptr()) };
        let last_error = unsafe { GetLastError() };
        if mutex.is_null() || last_error == ERROR_ALREADY_EXISTS {
            if !mutex.is_null() {
                unsafe { CloseHandle(mutex) };
            }
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        if !verify_logon_sid_only_dacl(mutex, &identity.logon_sid, MUTEX_LOGON_ACCESS) {
            unsafe { CloseHandle(mutex) };
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(Self {
            mutex,
            name,
            logon_sid: identity.logon_sid,
        })
    }

    pub(crate) fn publish(mut self) -> Result<WindowsEndpoint, ProtocolError> {
        let pending_pipe = create_pipe(&self.name, &self.logon_sid, true)?;
        let acl_verified =
            verify_logon_sid_only_dacl(pending_pipe, &self.logon_sid, PIPE_LOGON_ACCESS);
        if !acl_verified {
            unsafe { CloseHandle(pending_pipe) };
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let mutex = self.mutex;
        self.mutex = null_mut();
        Ok(WindowsEndpoint {
            pending_pipe,
            mutex,
            name: self.name.clone(),
            logon_sid: self.logon_sid.clone(),
            acl_verified,
        })
    }
}

impl Drop for WindowsEndpointReservation {
    fn drop(&mut self) {
        if !self.mutex.is_null() {
            unsafe { CloseHandle(self.mutex) };
        }
    }
}

impl Drop for WindowsEndpoint {
    fn drop(&mut self) {
        // SAFETY: both handles are uniquely owned and closed once here.
        unsafe {
            CloseHandle(self.pending_pipe);
            CloseHandle(self.mutex);
        }
    }
}

pub(crate) struct WindowsNativeStream {
    handle: HANDLE,
    server_side: bool,
}

// Windows kernel handles are valid process-wide. This wrapper owns one handle
// and does not permit concurrent access after it moves to a worker thread.
unsafe impl Send for WindowsNativeStream {}

impl WindowsNativeStream {
    pub(crate) fn connect(publication: &str, timeout: Duration) -> Result<Self, ProtocolError> {
        if !publication.starts_with(r"\\.\pipe\AI-Guard-Native-Broker-") {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let name = wide(publication);
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| ProtocolError::new("broker_unavailable", None))?;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            let timeout_ms = u32::try_from(remaining.as_millis().clamp(1, u32::MAX as u128))
                .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
            // SAFETY: name is NUL-terminated and the timeout is bounded.
            if unsafe { WaitNamedPipeW(name.as_ptr(), timeout_ms) } == 0 {
                if unsafe { GetLastError() } == ERROR_PIPE_BUSY && Instant::now() < deadline {
                    continue;
                }
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            // SAFETY: all pointers and flag combinations follow CreateFile named-pipe rules.
            let handle = unsafe {
                CreateFileW(
                    name.as_ptr(),
                    GENERIC_READ | GENERIC_WRITE,
                    0,
                    null_mut(),
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION,
                    null_mut(),
                )
            };
            if handle != INVALID_HANDLE_VALUE {
                return Ok(Self {
                    handle,
                    server_side: false,
                });
            }
            if unsafe { GetLastError() } != ERROR_PIPE_BUSY || Instant::now() >= deadline {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
        }
    }

    pub(crate) fn read_exact_bounded(
        &mut self,
        target: &mut [u8],
        timeout: Duration,
        clean_disconnect_allowed: bool,
    ) -> Result<ReadOutcome, ProtocolError> {
        let deadline = Instant::now() + timeout;
        let mut offset = 0;
        while offset < target.len() {
            let mut available = 0_u32;
            // SAFETY: available is a valid output and other optional buffers are null.
            let peeked = unsafe {
                PeekNamedPipe(
                    self.handle,
                    null_mut(),
                    0,
                    null_mut(),
                    &mut available,
                    null_mut(),
                )
            };
            if peeked == 0 {
                let error = unsafe { GetLastError() };
                if error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA {
                    if offset == 0 && clean_disconnect_allowed {
                        return Ok(ReadOutcome::Disconnected);
                    }
                    return Err(ProtocolError::new("request_invalid", None));
                }
                return Err(ProtocolError::new("request_invalid", None));
            }
            if available == 0 {
                if Instant::now() >= deadline {
                    return Err(ProtocolError::new("operation_timeout", None));
                }
                std::thread::sleep(Duration::from_millis(5));
                continue;
            }
            let request = (target.len() - offset)
                .min(available as usize)
                .min(u32::MAX as usize);
            let mut read = 0_u32;
            // SAFETY: the target sub-slice is writable for request bytes.
            if unsafe {
                ReadFile(
                    self.handle,
                    target[offset..].as_mut_ptr(),
                    request as u32,
                    &mut read,
                    null_mut(),
                )
            } == 0
                || read == 0
            {
                return Err(ProtocolError::new("request_invalid", None));
            }
            offset += read as usize;
        }
        Ok(ReadOutcome::Complete)
    }

    pub(crate) fn write_all_bounded(
        &mut self,
        bytes: &[u8],
        timeout: Duration,
    ) -> Result<(), ProtocolError> {
        let deadline = Instant::now() + timeout;
        let mut offset = 0;
        while offset < bytes.len() {
            let request = (bytes.len() - offset).min(u32::MAX as usize);
            let mut written = 0_u32;
            // SAFETY: the source sub-slice is readable for request bytes.
            let result = unsafe {
                WriteFile(
                    self.handle,
                    bytes[offset..].as_ptr(),
                    request as u32,
                    &mut written,
                    null_mut(),
                )
            };
            if result != 0 && written > 0 {
                offset += written as usize;
                continue;
            }
            let error = unsafe { GetLastError() };
            if error == ERROR_NO_DATA && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(5));
                continue;
            }
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(())
    }

    pub(crate) fn has_pending_input(&self) -> Result<bool, ProtocolError> {
        let mut available = 0_u32;
        // SAFETY: available is a valid output and the pipe handle remains live.
        if unsafe {
            PeekNamedPipe(
                self.handle,
                null_mut(),
                0,
                null_mut(),
                &mut available,
                null_mut(),
            )
        } == 0
        {
            let error = unsafe { GetLastError() };
            if error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA {
                return Ok(false);
            }
            return Err(ProtocolError::new("request_invalid", None));
        }
        Ok(available > 0)
    }

    pub(crate) fn shutdown(&mut self) {
        if self.server_side {
            unsafe { DisconnectNamedPipe(self.handle) };
        }
    }

    pub(crate) fn finish_response(&mut self, _timeout: Duration) {
        // Closing the server handle preserves buffered pipe bytes. A forced
        // disconnect would discard the terminal response before the client reads it.
    }

    pub(crate) fn inspect_server(
        &self,
    ) -> Result<(OsPeerContext, PathBuf, WindowsPeerGuard), ProtocolError> {
        inspect_named_pipe_peer(self.handle, false)
    }
}

impl Drop for WindowsNativeStream {
    fn drop(&mut self) {
        // Closing preserves already-buffered response bytes for the client;
        // DisconnectNamedPipe would discard them before a final fixed error is read.
        unsafe { CloseHandle(self.handle) };
    }
}

pub(crate) struct WindowsPeerGuard {
    process: HANDLE,
    process_id: u32,
    executable: PathBuf,
    user_sid: String,
    logon_sid: String,
}

// The process handle is uniquely owned and may be queried from any thread.
unsafe impl Send for WindowsPeerGuard {}

impl WindowsPeerGuard {
    pub(crate) fn ensure_stable(&self) -> Result<(), ProtocolError> {
        // SAFETY: process is a live SYNCHRONIZE handle owned by this guard.
        if unsafe { WaitForSingleObject(self.process, 0) } != WAIT_TIMEOUT
            || process_path(self.process)? != self.executable
        {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        let identity = token_identity_for_process(self.process)?;
        if identity.process_id != self.process_id
            || identity.user_sid != self.user_sid
            || identity.logon_sid != self.logon_sid
        {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        Ok(())
    }
}

impl Drop for WindowsPeerGuard {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.process) };
    }
}

fn inspect_named_pipe_peer(
    pipe: HANDLE,
    client: bool,
) -> Result<(OsPeerContext, PathBuf, WindowsPeerGuard), ProtocolError> {
    let mut process_id = 0_u32;
    // SAFETY: process_id is a valid output and pipe is connected.
    let ok = unsafe {
        if client {
            GetNamedPipeClientProcessId(pipe, &mut process_id)
        } else {
            GetNamedPipeServerProcessId(pipe, &mut process_id)
        }
    };
    if ok == 0 || process_id == 0 {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    // SAFETY: process_id came from the kernel for this connected pipe.
    let process = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE_ACCESS,
            0,
            process_id,
        )
    };
    if process.is_null() {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let inspected = (|| {
        let identity = token_identity_for_process(process)?;
        let executable = process_path(process)?;
        let context = OsPeerContext {
            user_boundary: identity.user_sid,
            logon_session: identity.logon_sid,
            process_id,
            credential_verified: true,
            stable_process_reference: true,
        };
        Ok((context, executable))
    })();
    let (context, executable) = match inspected {
        Ok(value) => value,
        Err(error) => {
            unsafe { CloseHandle(process) };
            return Err(error);
        }
    };
    let guard = WindowsPeerGuard {
        process,
        process_id,
        executable: executable.clone(),
        user_sid: context.user_boundary.clone(),
        logon_sid: context.logon_session.clone(),
    };
    guard.ensure_stable()?;
    Ok((context, executable, guard))
}

struct TokenIdentity {
    user_sid: String,
    logon_sid: String,
    process_id: u32,
}

fn token_identity_for_process(process: HANDLE) -> Result<TokenIdentity, ProtocolError> {
    let mut token = null_mut();
    // SAFETY: process is queryable and token is a valid output pointer.
    if unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut token) } == 0 {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let result = (|| {
        let user = token_information(token, TokenUser)?;
        let token_user = user.as_ptr().cast::<TOKEN_USER>();
        // SAFETY: token_information returned a TOKEN_USER buffer.
        let user_sid = unsafe { sid_to_string((*token_user).User.Sid)? };

        let groups = token_information(token, TokenGroups)?;
        let token_groups = groups.as_ptr().cast::<TOKEN_GROUPS>();
        // SAFETY: TOKEN_GROUPS is a variable-length array backed by groups.
        let count = unsafe { (*token_groups).GroupCount as usize };
        let first = unsafe { (*token_groups).Groups.as_ptr() };
        let mut logon_sid = None;
        for index in 0..count {
            // SAFETY: index is bounded by GroupCount from the returned buffer.
            let group = unsafe { &*first.add(index) };
            if group.Attributes & SE_GROUP_LOGON_ID == SE_GROUP_LOGON_ID {
                logon_sid = Some(unsafe { sid_to_string(group.Sid)? });
                break;
            }
        }
        let Some(logon_sid) = logon_sid else {
            return Err(ProtocolError::new("broker_unauthorized", None));
        };
        let statistics = token_information(token, TokenStatistics)?;
        let token_statistics = statistics.as_ptr().cast::<TOKEN_STATISTICS>();
        // SAFETY: token_information returned a TOKEN_STATISTICS buffer.
        let authentication_id = unsafe { (*token_statistics).AuthenticationId };
        if authentication_id.LowPart == 0 && authentication_id.HighPart == 0 {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        Ok(TokenIdentity {
            user_sid,
            logon_sid,
            process_id: unsafe { windows_sys::Win32::System::Threading::GetProcessId(process) },
        })
    })();
    unsafe { CloseHandle(token) };
    result
}

fn token_information(handle: HANDLE, class: i32) -> Result<Vec<usize>, ProtocolError> {
    let mut needed = 0_u32;
    // SAFETY: null buffer requests the required size.
    unsafe { GetTokenInformation(handle, class, null_mut(), 0, &mut needed) };
    if needed == 0 || needed > 1024 * 1024 {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let words = (needed as usize).div_ceil(std::mem::size_of::<usize>());
    let mut buffer = vec![0_usize; words];
    // SAFETY: buffer is pointer-aligned and covers at least the required bytes.
    if unsafe {
        GetTokenInformation(
            handle,
            class,
            buffer.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    Ok(buffer)
}

unsafe fn sid_to_string(sid: *mut c_void) -> Result<String, ProtocolError> {
    let mut string_sid = null_mut();
    if ConvertSidToStringSidW(sid, &mut string_sid) == 0 || string_sid.is_null() {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let mut length = 0;
    while *string_sid.add(length) != 0 {
        length += 1;
    }
    let value = String::from_utf16(std::slice::from_raw_parts(string_sid, length))
        .map_err(|_| ProtocolError::new("broker_unauthorized", None));
    LocalFree(string_sid.cast());
    value
}

fn process_path(process: HANDLE) -> Result<PathBuf, ProtocolError> {
    let mut buffer = vec![0_u16; 32_768];
    let mut length = buffer.len() as u32;
    // SAFETY: buffer is writable for length UTF-16 units.
    if unsafe { QueryFullProcessImageNameW(process, 0, buffer.as_mut_ptr(), &mut length) } == 0
        || length == 0
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    buffer.truncate(length as usize);
    let path = PathBuf::from(
        String::from_utf16(&buffer).map_err(|_| ProtocolError::new("broker_unauthorized", None))?,
    );
    path.canonicalize()
        .map_err(|_| ProtocolError::new("broker_unauthorized", None))
}

fn create_pipe(name: &str, logon_sid: &str, first: bool) -> Result<HANDLE, ProtocolError> {
    let descriptor = ExplicitDescriptor::for_logon_sid(logon_sid)?;
    let name = wide(name);
    let first_flag = if first {
        FILE_FLAG_FIRST_PIPE_INSTANCE
    } else {
        0
    };
    // SAFETY: arguments are bounded and the descriptor remains live for the call.
    let pipe = unsafe {
        CreateNamedPipeW(
            name.as_ptr(),
            PIPE_ACCESS_DUPLEX | first_flag,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
            MAX_PIPE_INSTANCES,
            64 * 1024,
            64 * 1024,
            5000,
            descriptor.attributes(),
        )
    };
    if pipe == INVALID_HANDLE_VALUE
        || !verify_logon_sid_only_dacl(pipe, logon_sid, PIPE_LOGON_ACCESS)
    {
        if pipe != INVALID_HANDLE_VALUE {
            unsafe { CloseHandle(pipe) };
        }
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(pipe)
}

struct ExplicitDescriptor {
    descriptor: *mut c_void,
    attributes: SECURITY_ATTRIBUTES,
}

impl ExplicitDescriptor {
    fn for_logon_sid(logon_sid: &str) -> Result<Self, ProtocolError> {
        let sddl = wide(&format!("D:P(A;;GRGW;;;{logon_sid})"));
        let mut descriptor = null_mut();
        // SAFETY: SDDL is NUL-terminated and descriptor is an output pointer.
        if unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.as_ptr(),
                1,
                &mut descriptor,
                null_mut(),
            )
        } == 0
            || descriptor.is_null()
        {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(Self {
            descriptor,
            attributes: SECURITY_ATTRIBUTES {
                nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
                lpSecurityDescriptor: descriptor,
                bInheritHandle: 0,
            },
        })
    }

    fn attributes(&self) -> *const SECURITY_ATTRIBUTES {
        &self.attributes
    }
}

impl Drop for ExplicitDescriptor {
    fn drop(&mut self) {
        unsafe { LocalFree(self.descriptor) };
    }
}

fn verify_logon_sid_only_dacl(handle: HANDLE, logon_sid: &str, expected_mask: u32) -> bool {
    let mut dacl = null_mut();
    let mut descriptor = null_mut();
    // SAFETY: output pointers are valid and descriptor is freed below.
    let result = unsafe {
        GetSecurityInfo(
            handle,
            SE_KERNEL_OBJECT,
            DACL_SECURITY_INFORMATION,
            null_mut(),
            null_mut(),
            &mut dacl,
            null_mut(),
            &mut descriptor,
        )
    };
    if result != 0 || dacl.is_null() || descriptor.is_null() {
        return false;
    }
    let verified = (|| {
        let mut control = 0_u16;
        let mut revision = 0_u32;
        if unsafe { GetSecurityDescriptorControl(descriptor, &mut control, &mut revision) } == 0
            || control & SE_DACL_PROTECTED == 0
        {
            return false;
        }
        let mut info = ACL_SIZE_INFORMATION::default();
        if unsafe {
            GetAclInformation(
                dacl,
                (&mut info as *mut ACL_SIZE_INFORMATION).cast(),
                std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
        } == 0
            || info.AceCount != 1
        {
            return false;
        }
        let mut ace_pointer = null_mut();
        if unsafe { GetAce(dacl, 0, &mut ace_pointer) } == 0 || ace_pointer.is_null() {
            return false;
        }
        let ace = ace_pointer.cast::<ACCESS_ALLOWED_ACE>();
        if unsafe { (*ace).Header.AceType } != ACCESS_ALLOWED_ACE_TYPE
            || unsafe { (*ace).Header.AceFlags } != 0
            || unsafe { (*ace).Mask } != expected_mask
        {
            return false;
        }
        let expected_wide = wide(logon_sid);
        let mut expected_sid = null_mut();
        if unsafe { ConvertStringSidToSidW(expected_wide.as_ptr(), &mut expected_sid) } == 0
            || expected_sid.is_null()
        {
            return false;
        }
        // SID bytes begin at SidStart in an ACCESS_ALLOWED_ACE.
        let actual_sid = unsafe { (&mut (*ace).SidStart as *mut u32).cast() };
        let equal = unsafe { EqualSid(actual_sid, expected_sid) } != 0;
        unsafe { LocalFree(expected_sid.cast()) };
        equal
    })();
    unsafe { LocalFree(descriptor) };
    verified
}

fn stable_endpoint_suffix(root: &Path, logon_sid: &str) -> String {
    let normalized = root.to_string_lossy().replace('/', "\\").to_lowercase();
    let digest = Sha256::digest(format!(
        "{normalized}\0{logon_sid}\0aiguard-native-broker-v1"
    ));
    format!("{:x}", digest)[..24].to_owned()
}

fn wide(value: &str) -> Vec<u16> {
    std::ffi::OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}
