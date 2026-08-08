//! Broker-owned prebound backend bootstrap and process-tree supervision.

use std::fmt;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde_json::Value;
use zeroize::Zeroizing;

use crate::bootstrap::BootstrapSecrets;
use crate::manifest::VerifiedBackend;
use crate::ProtocolError;

const BOOTSTRAP_MAGIC: &[u8; 8] = b"AIGB2IPC";
const BOOTSTRAP_VERSION: u16 = 1;
const BOOTSTRAP_MAX_BYTES: usize = 4096;
const HTTP_MAX_BYTES: usize = 16 * 1024;
const FORCED_REAP_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Clone, Copy)]
pub struct BackendTimeouts {
    pub startup: Duration,
    pub request: Duration,
    pub shutdown: Duration,
}

impl Default for BackendTimeouts {
    fn default() -> Self {
        Self {
            startup: Duration::from_secs(30),
            request: Duration::from_secs(2),
            shutdown: Duration::from_secs(5),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BackendHealth {
    pub status_ok: bool,
    pub product_compatible: bool,
    pub data_auth_required: bool,
    pub control_auth_required: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BackendSecurityReport {
    pub listener_prebound: bool,
    pub listener_exclusive: bool,
    pub listener_non_inheritable: bool,
    pub bootstrap_inherited_channel: bool,
    pub credentials_absent_from_argv: bool,
    pub credentials_absent_from_environment: bool,
    pub process_tree_owned: bool,
}

struct BackendLaunchSpec {
    executable: PathBuf,
    arguments: Vec<String>,
    working_directory: PathBuf,
    product_version: String,
}

impl BackendLaunchSpec {
    fn from_verified(
        backend: &VerifiedBackend,
        product_version: &str,
    ) -> Result<Self, ProtocolError> {
        if backend.build_id() != product_version {
            return unavailable();
        }
        let executable = backend
            .executable()
            .canonicalize()
            .map_err(|_| unavailable_error())?;
        let working_directory = executable
            .parent()
            .ok_or_else(unavailable_error)?
            .to_path_buf();
        Ok(Self {
            executable,
            arguments: backend.arguments().to_vec(),
            working_directory,
            product_version: product_version.to_owned(),
        })
    }

    fn synthetic(
        executable: &Path,
        arguments: &[String],
        working_directory: &Path,
        product_version: &str,
    ) -> Result<Self, ProtocolError> {
        if arguments.is_empty()
            || arguments.len() > 8
            || !valid_product_version(product_version)
            || arguments.iter().any(|value| {
                value.is_empty()
                    || value.len() > 4096
                    || value.chars().any(|character| character == '\0')
            })
        {
            return unavailable();
        }
        let executable = std::path::absolute(executable).map_err(|_| unavailable_error())?;
        if !executable.is_file() {
            return unavailable();
        }
        Ok(Self {
            // Test environments commonly expose a virtual-environment Python
            // through a symlink. Preserve that entry path so Python retains its
            // environment prefix; installed components use the stricter
            // manifest-verified, non-symlink path above.
            executable,
            arguments: arguments.to_vec(),
            working_directory: working_directory
                .canonicalize()
                .map_err(|_| unavailable_error())?,
            product_version: product_version.to_owned(),
        })
    }
}

pub struct ManagedBackend {
    child: ChildProcess,
    _bootstrap_guard: BootstrapGuard,
    _listener_guard: TcpListener,
    address: SocketAddr,
    secrets: BootstrapSecrets,
    process_tree: ProcessTree,
    product_version: String,
    timeouts: BackendTimeouts,
    healthy: bool,
    shutdown_complete: bool,
    security: BackendSecurityReport,
}

impl fmt::Debug for ManagedBackend {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedBackend")
            .field("healthy", &self.healthy)
            .field("shutdown_complete", &self.shutdown_complete)
            .finish_non_exhaustive()
    }
}

impl ManagedBackend {
    pub fn spawn_verified(
        backend: &VerifiedBackend,
        product_version: &str,
        timeouts: BackendTimeouts,
    ) -> Result<Self, ProtocolError> {
        let spec = BackendLaunchSpec::from_verified(backend, product_version)?;
        Self::spawn_spec(spec, timeouts)
    }

    #[doc(hidden)]
    pub fn spawn_synthetic_for_test(
        executable: &Path,
        arguments: &[String],
        working_directory: &Path,
        product_version: &str,
        timeouts: BackendTimeouts,
    ) -> Result<Self, ProtocolError> {
        let spec = BackendLaunchSpec::synthetic(
            executable,
            arguments,
            working_directory,
            product_version,
        )?;
        Self::spawn_spec(spec, timeouts)
    }

    fn spawn_spec(
        spec: BackendLaunchSpec,
        timeouts: BackendTimeouts,
    ) -> Result<Self, ProtocolError> {
        if timeouts.startup.is_zero() || timeouts.request.is_zero() || timeouts.shutdown.is_zero() {
            return unavailable();
        }
        let (listener, listener_exclusive) = create_backend_listener()?;
        let address = listener.local_addr().map_err(|_| unavailable_error())?;
        if address.ip() != IpAddr::V4(Ipv4Addr::LOCALHOST) || address.port() == 0 {
            return unavailable();
        }
        let listener_non_inheritable = listener_is_non_inheritable(&listener)?;
        if !listener_non_inheritable {
            return unavailable();
        }
        let secrets = BootstrapSecrets::generate()?;
        let (child, process_tree, bootstrap_guard) =
            spawn_and_transfer(&spec, &listener, &secrets)?;
        let mut backend = Self {
            child,
            _bootstrap_guard: bootstrap_guard,
            _listener_guard: listener,
            address,
            secrets,
            process_tree,
            product_version: spec.product_version,
            timeouts,
            healthy: false,
            shutdown_complete: false,
            security: BackendSecurityReport {
                listener_prebound: true,
                listener_exclusive,
                listener_non_inheritable,
                bootstrap_inherited_channel: true,
                credentials_absent_from_argv: true,
                credentials_absent_from_environment: true,
                process_tree_owned: true,
            },
        };
        if backend.wait_until_healthy().is_err() {
            backend.force_terminate();
            return unavailable();
        }
        backend.healthy = true;
        Ok(backend)
    }

    pub fn health(&mut self) -> Result<BackendHealth, ProtocolError> {
        let deadline = Instant::now()
            .checked_add(self.timeouts.request)
            .ok_or_else(unavailable_error)?;
        self.health_until(deadline)
    }

    pub fn health_until(&mut self, deadline: Instant) -> Result<BackendHealth, ProtocolError> {
        if !self.healthy
            || self
                .child
                .try_wait()
                .map_err(|_| unavailable_error())?
                .is_some()
        {
            self.healthy = false;
            return unavailable();
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(ProtocolError::new("operation_timeout", None));
        }
        match request_health(
            self.address,
            &self.product_version,
            remaining.min(self.timeouts.request),
        ) {
            Ok(health) => Ok(health),
            Err(_) => {
                self.healthy = false;
                Err(unavailable_error())
            }
        }
    }

    pub fn security_report(&self) -> BackendSecurityReport {
        self.security
    }

    pub fn is_alive(&mut self) -> bool {
        self.child.try_wait().is_ok_and(|status| status.is_none())
    }

    #[doc(hidden)]
    pub fn process_id_for_test(&self) -> u32 {
        self.child.id()
    }

    #[doc(hidden)]
    pub fn address_for_test(&self) -> SocketAddr {
        self.address
    }

    pub fn shutdown(&mut self) -> Result<(), ProtocolError> {
        if self.shutdown_complete {
            return Ok(());
        }
        match self.child.try_wait() {
            Ok(Some(_)) => {
                self.healthy = false;
                self.shutdown_complete = true;
                return Ok(());
            }
            Ok(None) => {}
            Err(_) => {
                self.force_terminate();
                return Err(ProtocolError::new("broker_unavailable", None));
            }
        }
        let request = Zeroizing::new(format!(
            "POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\nX-AIGuard-Contract-Version: 2\r\nX-AIGuard-Token: {}\r\nContent-Length: 0\r\n\r\n",
            self.secrets.control_token()
        ));
        let response = http_request(self.address, request.as_bytes(), self.timeouts.request);
        if !matches!(response, Ok(ref response) if response.status == 200) {
            self.force_terminate();
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let deadline = Instant::now() + self.timeouts.shutdown;
        loop {
            match self.child.try_wait() {
                Ok(Some(_)) => {
                    self.healthy = false;
                    self.shutdown_complete = true;
                    return Ok(());
                }
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(20));
                }
                _ => {
                    self.force_terminate();
                    return Err(ProtocolError::new("operation_timeout", None));
                }
            }
        }
    }

    pub fn force_terminate(&mut self) {
        if self.shutdown_complete {
            return;
        }
        self.process_tree.terminate();
        kill_and_reap_bounded(&mut self.child);
        self.healthy = false;
        self.shutdown_complete = true;
    }

    fn wait_until_healthy(&mut self) -> Result<(), ProtocolError> {
        let deadline = Instant::now() + self.timeouts.startup;
        loop {
            if self
                .child
                .try_wait()
                .map_err(|_| unavailable_error())?
                .is_some()
            {
                return unavailable();
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return unavailable();
            }
            if let Ok(health) = request_health(
                self.address,
                &self.product_version,
                self.timeouts.request.min(remaining),
            ) {
                if health
                    == (BackendHealth {
                        status_ok: true,
                        product_compatible: true,
                        data_auth_required: true,
                        control_auth_required: true,
                    })
                {
                    return Ok(());
                }
                return unavailable();
            }
            if Instant::now() >= deadline {
                return unavailable();
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}

impl Drop for ManagedBackend {
    fn drop(&mut self) {
        if !self.shutdown_complete && self.shutdown().is_err() {
            self.force_terminate();
        }
    }
}

struct HttpResponse {
    status: u16,
    contract_version: Option<String>,
    body: Vec<u8>,
}

fn request_health(
    address: SocketAddr,
    product_version: &str,
    timeout: Duration,
) -> Result<BackendHealth, ProtocolError> {
    let response = http_request(
        address,
        b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
        timeout,
    )?;
    if response.status != 200 || response.contract_version.as_deref() != Some("2") {
        return unavailable();
    }
    let value: Value = serde_json::from_slice(&response.body).map_err(|_| unavailable_error())?;
    let expected = serde_json::json!({
        "status": "ok",
        "version": product_version,
        "contract_version": 2,
        "capabilities": {
            "control_token_required": true,
            "api_key_required": true,
        },
    });
    if value != expected {
        return unavailable();
    }
    Ok(BackendHealth {
        status_ok: true,
        product_compatible: true,
        data_auth_required: true,
        control_auth_required: true,
    })
}

fn http_request(
    address: SocketAddr,
    request: &[u8],
    timeout: Duration,
) -> Result<HttpResponse, ProtocolError> {
    if timeout.is_zero() {
        return Err(ProtocolError::new("operation_timeout", None));
    }
    let deadline = Instant::now()
        .checked_add(timeout)
        .ok_or_else(|| ProtocolError::new("operation_timeout", None))?;
    let mut stream = TcpStream::connect_timeout(&address, backend_remaining(deadline)?)
        .map_err(|_| unavailable_error())?;
    let mut written = 0;
    while written < request.len() {
        stream
            .set_write_timeout(Some(backend_remaining(deadline)?))
            .map_err(|_| unavailable_error())?;
        match stream.write(&request[written..]) {
            Ok(0) => return unavailable(),
            Ok(size) => written += size,
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                return Err(ProtocolError::new("operation_timeout", None));
            }
            Err(_) => return unavailable(),
        }
    }
    let mut response = Vec::new();
    let mut buffer = [0_u8; 4096];
    loop {
        stream
            .set_read_timeout(Some(backend_remaining(deadline)?))
            .map_err(|_| unavailable_error())?;
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(size) => {
                if response.len() + size > HTTP_MAX_BYTES {
                    return unavailable();
                }
                response.extend_from_slice(&buffer[..size]);
            }
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                return Err(ProtocolError::new("operation_timeout", None));
            }
            Err(_) => return unavailable(),
        }
    }
    if response.is_empty() || response.len() > HTTP_MAX_BYTES {
        return unavailable();
    }
    parse_http_response(&response)
}

fn backend_remaining(deadline: Instant) -> Result<Duration, ProtocolError> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        return Err(ProtocolError::new("operation_timeout", None));
    }
    Ok(remaining)
}

fn parse_http_response(bytes: &[u8]) -> Result<HttpResponse, ProtocolError> {
    let separator = bytes
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(unavailable_error)?;
    let head = std::str::from_utf8(&bytes[..separator]).map_err(|_| unavailable_error())?;
    let mut lines = head.split("\r\n");
    let status_line = lines.next().ok_or_else(unavailable_error)?;
    let mut status_fields = status_line.split_ascii_whitespace();
    if status_fields.next() != Some("HTTP/1.1") {
        return unavailable();
    }
    let status = status_fields
        .next()
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|value| (100..=599).contains(value))
        .ok_or_else(unavailable_error)?;
    let mut content_length = None;
    let mut contract_version = None;
    for line in lines {
        let (name, value) = line.split_once(':').ok_or_else(unavailable_error)?;
        let value = value.trim();
        if name.eq_ignore_ascii_case("content-length") {
            if content_length.is_some() {
                return unavailable();
            }
            content_length = value.parse::<usize>().ok();
        } else if name.eq_ignore_ascii_case("x-aiguard-contract-version") {
            if contract_version.is_some() {
                return unavailable();
            }
            contract_version = Some(value.to_owned());
        }
    }
    let body = &bytes[separator + 4..];
    if content_length != Some(body.len()) {
        return unavailable();
    }
    Ok(HttpResponse {
        status,
        contract_version,
        body: body.to_vec(),
    })
}

fn build_bootstrap_packet(
    product_version: &str,
    secrets: &BootstrapSecrets,
    socket_info: &[u8],
) -> Result<Zeroizing<Vec<u8>>, ProtocolError> {
    if !valid_product_version(product_version)
        || socket_info.len() > 2048
        || secrets.api_key().len() != 64
        || secrets.control_token().len() != 64
    {
        return unavailable();
    }
    let product_len = u16::try_from(product_version.len()).map_err(|_| unavailable_error())?;
    let socket_len = u32::try_from(socket_info.len()).map_err(|_| unavailable_error())?;
    let body_len = 8
        + 2
        + 2
        + 2
        + 2
        + 4
        + product_version.len()
        + secrets.api_key().len()
        + secrets.control_token().len()
        + socket_info.len();
    if body_len > BOOTSTRAP_MAX_BYTES {
        return unavailable();
    }
    let mut packet = Vec::with_capacity(body_len + 4);
    packet.extend_from_slice(&(body_len as u32).to_be_bytes());
    packet.extend_from_slice(BOOTSTRAP_MAGIC);
    packet.extend_from_slice(&BOOTSTRAP_VERSION.to_be_bytes());
    packet.extend_from_slice(&product_len.to_be_bytes());
    packet.extend_from_slice(&(64_u16).to_be_bytes());
    packet.extend_from_slice(&(64_u16).to_be_bytes());
    packet.extend_from_slice(&socket_len.to_be_bytes());
    packet.extend_from_slice(product_version.as_bytes());
    packet.extend_from_slice(secrets.api_key().as_bytes());
    packet.extend_from_slice(secrets.control_token().as_bytes());
    packet.extend_from_slice(socket_info);
    Ok(Zeroizing::new(packet))
}

fn valid_product_version(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'+' | b'-'))
}

#[cfg(unix)]
type ProcessTree = unix_process::UnixProcessTree;
#[cfg(unix)]
type ChildProcess = std::process::Child;
#[cfg(windows)]
type ProcessTree = windows_process::WindowsProcessTree;
#[cfg(windows)]
type ChildProcess = windows_process::WindowsChild;

#[cfg(unix)]
struct BootstrapGuard {
    _channel: std::os::unix::net::UnixStream,
}

#[cfg(windows)]
struct BootstrapGuard;

fn kill_and_reap_bounded(child: &mut ChildProcess) {
    let _ = child.kill();
    let deadline = Instant::now() + FORCED_REAP_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(10));
            }
            _ => return,
        }
    }
}

#[cfg(unix)]
fn spawn_and_transfer(
    spec: &BackendLaunchSpec,
    listener: &TcpListener,
    secrets: &BootstrapSecrets,
) -> Result<(ChildProcess, ProcessTree, BootstrapGuard), ProtocolError> {
    unix_process::spawn_and_transfer(spec, listener, secrets)
}

#[cfg(windows)]
fn spawn_and_transfer(
    spec: &BackendLaunchSpec,
    listener: &TcpListener,
    secrets: &BootstrapSecrets,
) -> Result<(ChildProcess, ProcessTree, BootstrapGuard), ProtocolError> {
    windows_process::spawn_and_transfer(spec, listener, secrets)
}

#[cfg(unix)]
fn create_backend_listener() -> Result<(TcpListener, bool), ProtocolError> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).map_err(|_| unavailable_error())?;
    Ok((listener, true))
}

#[cfg(windows)]
fn create_backend_listener() -> Result<(TcpListener, bool), ProtocolError> {
    use std::mem::MaybeUninit;
    use std::os::windows::io::FromRawSocket;
    use std::sync::OnceLock;
    use windows_sys::Win32::Networking::WinSock::{
        bind, closesocket, getsockopt, listen, setsockopt, WSASocketW, WSAStartup, AF_INET,
        INVALID_SOCKET, IN_ADDR, IPPROTO_TCP, SOCKADDR, SOCKADDR_IN, SOCKET_ERROR, SOCK_STREAM,
        SOL_SOCKET, SOMAXCONN, SO_EXCLUSIVEADDRUSE, WSADATA, WSA_FLAG_NO_HANDLE_INHERIT,
        WSA_FLAG_OVERLAPPED,
    };

    static WINSOCK_READY: OnceLock<bool> = OnceLock::new();
    let ready = WINSOCK_READY.get_or_init(|| {
        let mut data = MaybeUninit::<WSADATA>::zeroed();
        // SAFETY: data is a valid process-lifetime Winsock initialization output.
        (unsafe { WSAStartup(0x0202, data.as_mut_ptr()) }) == 0
    });
    if !*ready {
        return unavailable();
    }

    // SAFETY: arguments select a bounded IPv4 TCP socket with no inherited handle.
    let socket = unsafe {
        WSASocketW(
            AF_INET as i32,
            SOCK_STREAM,
            IPPROTO_TCP,
            std::ptr::null(),
            0,
            WSA_FLAG_NO_HANDLE_INHERIT | WSA_FLAG_OVERLAPPED,
        )
    };
    if socket == INVALID_SOCKET {
        return unavailable();
    }
    let exclusive = 1_i32;
    // SAFETY: exclusive is a live i32 option value for this socket.
    if unsafe {
        setsockopt(
            socket,
            SOL_SOCKET,
            SO_EXCLUSIVEADDRUSE,
            (&exclusive as *const i32).cast(),
            std::mem::size_of::<i32>() as i32,
        )
    } == SOCKET_ERROR
    {
        unsafe { closesocket(socket) };
        return unavailable();
    }
    let mut verified = 0_i32;
    let mut verified_length = std::mem::size_of::<i32>() as i32;
    // SAFETY: verified and its length are valid outputs for this socket option.
    if unsafe {
        getsockopt(
            socket,
            SOL_SOCKET,
            SO_EXCLUSIVEADDRUSE,
            (&mut verified as *mut i32).cast(),
            &mut verified_length,
        )
    } == SOCKET_ERROR
        || verified_length != std::mem::size_of::<i32>() as i32
        || verified != 1
    {
        unsafe { closesocket(socket) };
        return unavailable();
    }
    let address = SOCKADDR_IN {
        sin_family: AF_INET,
        sin_port: 0,
        sin_addr: IN_ADDR {
            S_un: windows_sys::Win32::Networking::WinSock::IN_ADDR_0 {
                S_addr: u32::from_ne_bytes([127, 0, 0, 1]),
            },
        },
        sin_zero: [0; 8],
    };
    // SAFETY: address is a complete IPv4 loopback sockaddr for the live socket.
    if unsafe {
        bind(
            socket,
            (&address as *const SOCKADDR_IN).cast::<SOCKADDR>(),
            std::mem::size_of::<SOCKADDR_IN>() as i32,
        )
    } == SOCKET_ERROR
        || unsafe { listen(socket, SOMAXCONN as i32) } == SOCKET_ERROR
    {
        unsafe { closesocket(socket) };
        return unavailable();
    }
    // SAFETY: ownership of the successfully bound socket moves to TcpListener.
    let listener = unsafe { TcpListener::from_raw_socket(socket as _) };
    Ok((listener, true))
}

#[cfg(unix)]
fn listener_is_non_inheritable(listener: &TcpListener) -> Result<bool, ProtocolError> {
    use std::os::fd::AsRawFd;
    // SAFETY: F_GETFD only reads flags for the live listener descriptor.
    let flags = unsafe { libc::fcntl(listener.as_raw_fd(), libc::F_GETFD) };
    if flags < 0 {
        return unavailable();
    }
    Ok(flags & libc::FD_CLOEXEC != 0)
}

#[cfg(windows)]
fn listener_is_non_inheritable(listener: &TcpListener) -> Result<bool, ProtocolError> {
    use std::os::windows::io::AsRawSocket;
    use windows_sys::Win32::Foundation::{GetHandleInformation, HANDLE_FLAG_INHERIT};
    let mut flags = 0_u32;
    // SAFETY: a Windows socket is a kernel handle accepted by GetHandleInformation.
    if unsafe { GetHandleInformation(listener.as_raw_socket() as _, &mut flags) } == 0 {
        return unavailable();
    }
    Ok(flags & HANDLE_FLAG_INHERIT == 0)
}

#[cfg(unix)]
mod unix_process {
    use std::os::fd::{AsRawFd, OwnedFd};
    use std::os::unix::net::UnixStream;
    use std::os::unix::process::CommandExt;
    use std::process::{Child, Command, Stdio};

    use super::*;

    pub(crate) struct UnixProcessTree {
        process_group: libc::pid_t,
    }

    impl UnixProcessTree {
        pub(crate) fn terminate(&self) {
            if self.process_group > 0 {
                // SAFETY: the negative PID targets only the child's process group.
                unsafe { libc::kill(-self.process_group, libc::SIGKILL) };
            }
        }
    }

    pub(crate) fn configure(command: &mut Command) -> Result<(), ProtocolError> {
        let descriptor_limit = crate::process::descriptor_limit()?;
        #[cfg(target_os = "linux")]
        let parent = unsafe { libc::getpid() };
        // SAFETY: only async-signal-safe libc calls run before exec.
        unsafe {
            command.pre_exec(move || {
                crate::process::seal_inherited_descriptors(descriptor_limit)?;
                if libc::setpgid(0, 0) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                #[cfg(target_os = "linux")]
                {
                    if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL) != 0
                        || libc::getppid() != parent
                    {
                        return Err(std::io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }
        Ok(())
    }

    pub(crate) fn spawn_and_transfer(
        spec: &BackendLaunchSpec,
        listener: &TcpListener,
        secrets: &BootstrapSecrets,
    ) -> Result<(Child, UnixProcessTree, BootstrapGuard), ProtocolError> {
        let mut command = Command::new(&spec.executable);
        command
            .args(&spec.arguments)
            .current_dir(&spec.working_directory)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .env_remove("AIGUARD_API_KEY")
            .env_remove("AIGUARD_TOKEN");
        let (parent_channel, child_channel) =
            UnixStream::pair().map_err(|_| unavailable_error())?;
        let child_fd: OwnedFd = child_channel.into();
        command.stdin(Stdio::from(child_fd));
        configure(&mut command)?;
        let mut child = command.spawn().map_err(|_| unavailable_error())?;
        let packet = build_bootstrap_packet(&spec.product_version, secrets, &[])?;
        if send_fd(parent_channel.as_raw_fd(), &packet, listener.as_raw_fd()).is_err() {
            kill_and_reap_bounded(&mut child);
            return unavailable();
        }
        let process_group = child.id() as libc::pid_t;
        Ok((
            child,
            UnixProcessTree { process_group },
            BootstrapGuard {
                _channel: parent_channel,
            },
        ))
    }

    fn send_fd(channel: i32, packet: &[u8], descriptor: i32) -> Result<(), ProtocolError> {
        let mut iov = libc::iovec {
            iov_base: packet.as_ptr().cast_mut().cast(),
            iov_len: packet.len(),
        };
        let control_len = unsafe { libc::CMSG_SPACE(std::mem::size_of::<i32>() as u32) } as usize;
        let mut control = vec![0_usize; control_len.div_ceil(std::mem::size_of::<usize>())];
        let mut message: libc::msghdr = unsafe { std::mem::zeroed() };
        message.msg_iov = &mut iov;
        message.msg_iovlen = 1;
        message.msg_control = control.as_mut_ptr().cast();
        message.msg_controllen = control_len as _;
        // SAFETY: usize backing gives cmsghdr alignment and msg_controllen keeps
        // the exact CMSG_SPACE byte count.
        unsafe {
            let header = libc::CMSG_FIRSTHDR(&message);
            if header.is_null() {
                return unavailable();
            }
            (*header).cmsg_level = libc::SOL_SOCKET;
            (*header).cmsg_type = libc::SCM_RIGHTS;
            (*header).cmsg_len = libc::CMSG_LEN(std::mem::size_of::<i32>() as u32) as _;
            std::ptr::copy_nonoverlapping(
                &descriptor as *const i32,
                libc::CMSG_DATA(header).cast::<i32>(),
                1,
            );
            if libc::sendmsg(channel, &message, 0) != packet.len() as isize {
                return unavailable();
            }
        }
        Ok(())
    }
}

#[cfg(windows)]
mod windows_process {
    use std::ffi::c_void;
    use std::mem::MaybeUninit;
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::AsRawSocket;
    use std::os::windows::process::ExitStatusExt;
    use std::process::ExitStatus;

    use windows_sys::Win32::Foundation::{
        CloseHandle, SetHandleInformation, GENERIC_WRITE, HANDLE, HANDLE_FLAG_INHERIT,
        INVALID_HANDLE_VALUE, STILL_ACTIVE,
    };
    use windows_sys::Win32::Networking::WinSock::{WSADuplicateSocketW, WSAPROTOCOL_INFOW};
    use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
    use windows_sys::Win32::Storage::FileSystem::{
        CreateFileW, WriteFile, FILE_ATTRIBUTE_NORMAL, FILE_SHARE_READ, FILE_SHARE_WRITE,
        OPEN_EXISTING,
    };
    use windows_sys::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Pipes::CreatePipe;
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, DeleteProcThreadAttributeList, GetExitCodeProcess,
        InitializeProcThreadAttributeList, ResumeThread, TerminateProcess,
        UpdateProcThreadAttribute, CREATE_NO_WINDOW, CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT,
        EXTENDED_STARTUPINFO_PRESENT, PROCESS_INFORMATION, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
        PROC_THREAD_ATTRIBUTE_JOB_LIST, STARTF_USESTDHANDLES, STARTUPINFOEXW,
    };

    use super::*;

    pub(crate) struct WindowsChild {
        process: HANDLE,
        process_id: u32,
    }

    // The process handle is uniquely owned and can be waited from any thread.
    unsafe impl Send for WindowsChild {}

    impl WindowsChild {
        pub(crate) fn id(&self) -> u32 {
            self.process_id
        }

        pub(crate) fn try_wait(&mut self) -> std::io::Result<Option<ExitStatus>> {
            let mut code = 0_u32;
            if unsafe { GetExitCodeProcess(self.process, &mut code) } == 0 {
                return Err(std::io::Error::last_os_error());
            }
            if code == STILL_ACTIVE as u32 {
                Ok(None)
            } else {
                Ok(Some(ExitStatus::from_raw(code)))
            }
        }

        pub(crate) fn kill(&mut self) -> std::io::Result<()> {
            if unsafe { TerminateProcess(self.process, 70) } == 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        }
    }

    impl Drop for WindowsChild {
        fn drop(&mut self) {
            if !self.process.is_null() {
                unsafe { CloseHandle(self.process) };
            }
        }
    }

    pub(crate) struct WindowsProcessTree {
        job: HANDLE,
    }

    // Job handles are process-wide and this wrapper has unique ownership.
    unsafe impl Send for WindowsProcessTree {}

    impl WindowsProcessTree {
        pub(crate) fn terminate(&self) {
            if !self.job.is_null() {
                unsafe { TerminateJobObject(self.job, 70) };
            }
        }
    }

    impl Drop for WindowsProcessTree {
        fn drop(&mut self) {
            if !self.job.is_null() {
                unsafe { CloseHandle(self.job) };
            }
        }
    }

    pub(crate) fn spawn_and_transfer(
        spec: &BackendLaunchSpec,
        listener: &TcpListener,
        secrets: &BootstrapSecrets,
    ) -> Result<(WindowsChild, WindowsProcessTree, BootstrapGuard), ProtocolError> {
        let (mut child, tree, bootstrap_write, primary_thread) = create_process_in_job(spec)?;
        let mut protocol_info = MaybeUninit::<WSAPROTOCOL_INFOW>::zeroed();
        // SAFETY: protocol_info is a valid output for the live listener socket.
        if unsafe {
            WSADuplicateSocketW(
                listener.as_raw_socket() as _,
                child.id(),
                protocol_info.as_mut_ptr(),
            )
        } != 0
        {
            tree.terminate();
            kill_and_reap_bounded(&mut child);
            return unavailable();
        }
        // SAFETY: WSADuplicateSocketW initialized the complete structure.
        let protocol_info = unsafe { protocol_info.assume_init() };
        let socket_info = unsafe {
            std::slice::from_raw_parts(
                (&protocol_info as *const WSAPROTOCOL_INFOW).cast::<u8>(),
                std::mem::size_of::<WSAPROTOCOL_INFOW>(),
            )
        };
        let packet = build_bootstrap_packet(&spec.product_version, secrets, socket_info)?;
        if write_handle_all(bootstrap_write.0, &packet).is_err() {
            tree.terminate();
            kill_and_reap_bounded(&mut child);
            return unavailable();
        }
        drop(bootstrap_write);
        if unsafe { ResumeThread(primary_thread.0) } == u32::MAX {
            tree.terminate();
            kill_and_reap_bounded(&mut child);
            return unavailable();
        }
        drop(primary_thread);
        Ok((child, tree, BootstrapGuard))
    }

    fn create_process_in_job(
        spec: &BackendLaunchSpec,
    ) -> Result<(WindowsChild, WindowsProcessTree, OwnedHandle, OwnedHandle), ProtocolError> {
        let job = create_job()?;
        let inheritable = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: std::ptr::null_mut(),
            bInheritHandle: 1,
        };
        let mut child_read = std::ptr::null_mut();
        let mut parent_write = std::ptr::null_mut();
        if unsafe {
            CreatePipe(
                &mut child_read,
                &mut parent_write,
                &inheritable,
                (BOOTSTRAP_MAX_BYTES + 4) as u32,
            )
        } == 0
            || child_read.is_null()
            || parent_write.is_null()
        {
            return unavailable();
        }
        let child_read = OwnedHandle(child_read);
        let parent_write = OwnedHandle(parent_write);
        if unsafe { SetHandleInformation(parent_write.0, HANDLE_FLAG_INHERIT, 0) } == 0 {
            return unavailable();
        }
        let null_stdout = open_inheritable_null(&inheritable)?;
        let null_stderr = open_inheritable_null(&inheritable)?;
        let handle_list = [child_read.0, null_stdout.0, null_stderr.0];
        let mut attributes = AttributeList::new(2)?;
        attributes.update(
            PROC_THREAD_ATTRIBUTE_JOB_LIST as usize,
            (&job.job as *const HANDLE).cast(),
            std::mem::size_of::<HANDLE>(),
        )?;
        attributes.update(
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
            handle_list.as_ptr().cast(),
            std::mem::size_of_val(&handle_list),
        )?;

        let mut startup = STARTUPINFOEXW::default();
        startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = child_read.0;
        startup.StartupInfo.hStdOutput = null_stdout.0;
        startup.StartupInfo.hStdError = null_stderr.0;
        startup.lpAttributeList = attributes.pointer();
        let application = wide_os(spec.executable.as_os_str())?;
        let mut command_line = command_line(spec)?;
        let current_directory = wide_os(spec.working_directory.as_os_str())?;
        let environment = environment_block()?;
        let mut process_info = PROCESS_INFORMATION::default();
        let created = unsafe {
            CreateProcessW(
                application.as_ptr(),
                command_line.as_mut_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                1,
                CREATE_NO_WINDOW
                    | CREATE_SUSPENDED
                    | CREATE_UNICODE_ENVIRONMENT
                    | EXTENDED_STARTUPINFO_PRESENT,
                environment.as_ptr().cast(),
                current_directory.as_ptr(),
                &startup.StartupInfo as *const _,
                &mut process_info,
            )
        };
        if created == 0 || process_info.hProcess.is_null() || process_info.hThread.is_null() {
            if !process_info.hProcess.is_null() {
                unsafe { CloseHandle(process_info.hProcess) };
            }
            if !process_info.hThread.is_null() {
                unsafe { CloseHandle(process_info.hThread) };
            }
            return unavailable();
        }
        drop(child_read);
        drop(null_stdout);
        drop(null_stderr);
        Ok((
            WindowsChild {
                process: process_info.hProcess,
                process_id: process_info.dwProcessId,
            },
            job,
            parent_write,
            OwnedHandle(process_info.hThread),
        ))
    }

    fn create_job() -> Result<WindowsProcessTree, ProtocolError> {
        // SAFETY: unnamed job with default private security.
        let job = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
        if job.is_null() {
            return unavailable();
        }
        let mut information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        // SAFETY: information points to the exact structure selected by the class.
        if unsafe {
            SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                (&information as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        } == 0
        {
            unsafe { CloseHandle(job) };
            return unavailable();
        }
        Ok(WindowsProcessTree { job })
    }

    fn open_inheritable_null(
        attributes: &SECURITY_ATTRIBUTES,
    ) -> Result<OwnedHandle, ProtocolError> {
        let name: Vec<u16> = "NUL\0".encode_utf16().collect();
        let handle = unsafe {
            CreateFileW(
                name.as_ptr(),
                GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                attributes,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return unavailable();
        }
        Ok(OwnedHandle(handle))
    }

    fn write_handle_all(handle: HANDLE, bytes: &[u8]) -> Result<(), ProtocolError> {
        let mut offset = 0;
        while offset < bytes.len() {
            let request = (bytes.len() - offset).min(u32::MAX as usize);
            let mut written = 0_u32;
            if unsafe {
                WriteFile(
                    handle,
                    bytes[offset..].as_ptr(),
                    request as u32,
                    &mut written,
                    std::ptr::null_mut(),
                )
            } == 0
                || written == 0
            {
                return unavailable();
            }
            offset += written as usize;
        }
        Ok(())
    }

    struct OwnedHandle(HANDLE);

    impl Drop for OwnedHandle {
        fn drop(&mut self) {
            if !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE {
                unsafe { CloseHandle(self.0) };
            }
        }
    }

    struct AttributeList {
        storage: Vec<usize>,
        pointer: *mut c_void,
    }

    impl AttributeList {
        fn new(count: u32) -> Result<Self, ProtocolError> {
            let mut bytes = 0_usize;
            unsafe {
                InitializeProcThreadAttributeList(std::ptr::null_mut(), count, 0, &mut bytes)
            };
            if bytes == 0 || bytes > 64 * 1024 {
                return unavailable();
            }
            let mut storage = vec![0_usize; bytes.div_ceil(std::mem::size_of::<usize>())];
            let pointer = storage.as_mut_ptr().cast();
            if unsafe { InitializeProcThreadAttributeList(pointer, count, 0, &mut bytes) } == 0 {
                return unavailable();
            }
            Ok(Self { storage, pointer })
        }

        fn update(
            &mut self,
            attribute: usize,
            value: *const c_void,
            size: usize,
        ) -> Result<(), ProtocolError> {
            if unsafe {
                UpdateProcThreadAttribute(
                    self.pointer,
                    0,
                    attribute,
                    value,
                    size,
                    std::ptr::null_mut(),
                    std::ptr::null(),
                )
            } == 0
            {
                return unavailable();
            }
            Ok(())
        }

        fn pointer(&mut self) -> *mut c_void {
            self.pointer
        }
    }

    impl Drop for AttributeList {
        fn drop(&mut self) {
            let _ = self.storage.len();
            unsafe { DeleteProcThreadAttributeList(self.pointer) };
        }
    }

    fn command_line(spec: &BackendLaunchSpec) -> Result<Vec<u16>, ProtocolError> {
        let mut values = Vec::with_capacity(spec.arguments.len() + 1);
        values.push(
            spec.executable
                .as_os_str()
                .encode_wide()
                .collect::<Vec<_>>(),
        );
        for argument in &spec.arguments {
            values.push(argument.encode_utf16().collect());
        }
        let mut line = Vec::new();
        for (index, value) in values.iter().enumerate() {
            if value.contains(&0) {
                return unavailable();
            }
            if index > 0 {
                line.push(b' ' as u16);
            }
            append_quoted_argument(&mut line, value);
        }
        line.push(0);
        Ok(line)
    }

    fn append_quoted_argument(output: &mut Vec<u16>, value: &[u16]) {
        output.push(b'"' as u16);
        let mut backslashes = 0;
        for unit in value {
            if *unit == b'\\' as u16 {
                backslashes += 1;
            } else if *unit == b'"' as u16 {
                output.extend(std::iter::repeat_n(b'\\' as u16, backslashes * 2 + 1));
                output.push(*unit);
                backslashes = 0;
            } else {
                output.extend(std::iter::repeat_n(b'\\' as u16, backslashes));
                output.push(*unit);
                backslashes = 0;
            }
        }
        output.extend(std::iter::repeat_n(b'\\' as u16, backslashes * 2));
        output.push(b'"' as u16);
    }

    fn environment_block() -> Result<Vec<u16>, ProtocolError> {
        let mut entries = Vec::new();
        for (key, value) in std::env::vars_os() {
            let key_text = key.to_string_lossy().into_owned();
            if key_text.eq_ignore_ascii_case("AIGUARD_API_KEY")
                || key_text.eq_ignore_ascii_case("AIGUARD_TOKEN")
            {
                continue;
            }
            let key_units: Vec<u16> = key.encode_wide().collect();
            let value_units: Vec<u16> = value.encode_wide().collect();
            if key_units.is_empty()
                || key_units.contains(&0)
                || value_units.contains(&0)
                || key_units.contains(&(b'=' as u16))
            {
                return unavailable();
            }
            let mut entry = Vec::with_capacity(key_units.len() + value_units.len() + 2);
            entry.extend_from_slice(&key_units);
            entry.push(b'=' as u16);
            entry.extend_from_slice(&value_units);
            entry.push(0);
            entries.push((key_text.to_uppercase(), entry));
        }
        entries.sort_by(|left, right| left.0.cmp(&right.0));
        let mut block = Vec::new();
        for (_, entry) in entries {
            block.extend_from_slice(&entry);
        }
        block.push(0);
        Ok(block)
    }

    fn wide_os(value: &std::ffi::OsStr) -> Result<Vec<u16>, ProtocolError> {
        let mut wide: Vec<u16> = value.encode_wide().collect();
        if wide.is_empty() || wide.contains(&0) {
            return unavailable();
        }
        wide.push(0);
        Ok(wide)
    }
}

fn unavailable<T>() -> Result<T, ProtocolError> {
    Err(unavailable_error())
}

fn unavailable_error() -> ProtocolError {
    ProtocolError::new("broker_unavailable", None)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prebound_listener_is_loopback_exclusive_and_non_inheritable() {
        let (listener, exclusive) = create_backend_listener().unwrap();
        assert!(exclusive);
        assert!(listener_is_non_inheritable(&listener).unwrap());
        let address = listener.local_addr().unwrap();
        assert_eq!(address.ip(), IpAddr::V4(Ipv4Addr::LOCALHOST));
        assert_ne!(address.port(), 0);
    }
}
