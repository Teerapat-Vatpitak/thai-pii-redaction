use std::fs::{DirBuilder, File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{DirBuilderExt, FileTypeExt, MetadataExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use zeroize::{Zeroize, Zeroizing};

use crate::admission::{BrokerOsContext, OsPeerContext};
use crate::transport::{checked_mode, current_uid, EndpointSecurityReport, ReadOutcome};
use crate::ProtocolError;

pub(crate) struct UnixEndpoint {
    listener: UnixListener,
    lock: File,
    socket_path: PathBuf,
    runtime_root: PathBuf,
    socket_device: u64,
    socket_inode: u64,
}

pub(crate) struct UnixEndpointReservation {
    lock: File,
    runtime_root: PathBuf,
}

impl UnixEndpoint {
    pub(crate) fn current_context() -> Result<BrokerOsContext, ProtocolError> {
        let uid = current_uid().to_string();
        Ok(BrokerOsContext {
            user_boundary: uid.clone(),
            logon_session: uid,
        })
    }

    pub(crate) fn default_runtime_root(_install_root: &Path) -> Result<PathBuf, ProtocolError> {
        Ok(PathBuf::from(format!(
            "/tmp/aiguard-native-broker-{}-v1",
            current_uid()
        )))
    }

    pub(crate) fn publication_for(root: &Path) -> Result<String, ProtocolError> {
        if root.as_os_str().is_empty() || !root.is_absolute() {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(root.join("broker.sock").to_string_lossy().into_owned())
    }

    pub(crate) fn reserve(root: &Path) -> Result<UnixEndpointReservation, ProtocolError> {
        UnixEndpointReservation::reserve(root)
    }

    pub(crate) fn accept(
        &mut self,
        timeout: Duration,
    ) -> Result<Option<(UnixNativeStream, OsPeerContext, PathBuf, UnixPeerGuard)>, ProtocolError>
    {
        if timeout.is_zero() {
            return Ok(None);
        }
        validate_or_create_runtime_root(&self.runtime_root)?;
        let metadata = secure_socket_metadata(&self.socket_path)?;
        if metadata.dev() != self.socket_device || metadata.ino() != self.socket_inode {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let deadline = Instant::now() + timeout;
        loop {
            match self.listener.accept() {
                Ok((stream, _)) => {
                    stream
                        .set_nonblocking(false)
                        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
                    let (context, executable, guard) = inspect_peer(&stream)?;
                    return Ok(Some((
                        UnixNativeStream { stream },
                        context,
                        executable,
                        guard,
                    )));
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    if Instant::now() >= deadline {
                        return Ok(None);
                    }
                    std::thread::sleep(Duration::from_millis(5));
                }
                Err(_) => return Err(ProtocolError::new("broker_unavailable", None)),
            }
        }
    }

    pub(crate) fn broker_context(&self) -> Result<BrokerOsContext, ProtocolError> {
        Self::current_context()
    }

    pub(crate) fn security_report(&self) -> EndpointSecurityReport {
        let lock_held =
            unsafe { libc::flock(self.lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) == 0 };
        EndpointSecurityReport {
            os_user_isolated: true,
            peer_credentials_required: true,
            single_instance_held: lock_held,
            remote_clients_rejected: true,
            runtime_directory_mode: Some(0o700),
            endpoint_mode: Some(0o600),
            uses_abstract_socket: false,
            explicit_dacl: false,
            current_logon_sid_only: false,
            client_pid_inspection: true,
        }
    }

    pub(crate) fn publication(&self) -> String {
        self.socket_path.to_string_lossy().into_owned()
    }

    pub(crate) fn filesystem_path(&self) -> Option<&Path> {
        Some(&self.socket_path)
    }
}

impl UnixEndpointReservation {
    fn reserve(root: &Path) -> Result<Self, ProtocolError> {
        validate_or_create_runtime_root(root)?;
        let lock_path = root.join("broker.lock");
        let lock = open_secure_lock(&lock_path)?;
        // SAFETY: the fd remains owned by the reservation and published endpoint.
        if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(Self {
            lock,
            runtime_root: root.to_path_buf(),
        })
    }

    pub(crate) fn publish(self) -> Result<UnixEndpoint, ProtocolError> {
        validate_or_create_runtime_root(&self.runtime_root)?;
        let socket_path = self.runtime_root.join("broker.sock");
        remove_stale_socket_while_locked(&socket_path)?;
        let listener = UnixListener::bind(&socket_path)
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        let configured = (|| {
            std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600))
                .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
            listener
                .set_nonblocking(true)
                .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
            secure_socket_metadata(&socket_path)
        })();
        let socket_metadata = match configured {
            Ok(metadata) => metadata,
            Err(error) => {
                if std::fs::symlink_metadata(&socket_path).is_ok_and(|metadata| {
                    metadata.file_type().is_socket()
                        && !metadata.file_type().is_symlink()
                        && metadata.uid() == current_uid()
                }) {
                    let _ = std::fs::remove_file(&socket_path);
                }
                return Err(error);
            }
        };
        Ok(UnixEndpoint {
            listener,
            lock: self.lock,
            socket_path,
            runtime_root: self.runtime_root,
            socket_device: socket_metadata.dev(),
            socket_inode: socket_metadata.ino(),
        })
    }
}

impl Drop for UnixEndpoint {
    fn drop(&mut self) {
        if let Ok(metadata) = std::fs::symlink_metadata(&self.socket_path) {
            if metadata.file_type().is_socket()
                && !metadata.file_type().is_symlink()
                && metadata.uid() == current_uid()
                && metadata.dev() == self.socket_device
                && metadata.ino() == self.socket_inode
            {
                let _ = std::fs::remove_file(&self.socket_path);
            }
        }
        let _ = &self.runtime_root;
    }
}

pub(crate) struct UnixNativeStream {
    stream: UnixStream,
}

impl UnixNativeStream {
    pub(crate) fn connect(publication: &str, timeout: Duration) -> Result<Self, ProtocolError> {
        let path = Path::new(publication);
        validate_client_endpoint_path(path)?;
        let stream = connect_with_timeout(path, timeout)?;
        stream
            .set_read_timeout(Some(timeout))
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        stream
            .set_write_timeout(Some(timeout))
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        Ok(Self { stream })
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
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(ProtocolError::new("operation_timeout", None));
            }
            self.stream
                .set_read_timeout(Some(remaining))
                .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
            match self.stream.read(&mut target[offset..]) {
                Ok(0) if offset == 0 && clean_disconnect_allowed => {
                    return Ok(ReadOutcome::Disconnected)
                }
                Ok(0) => return Err(ProtocolError::new("request_invalid", None)),
                Ok(read) => offset += read,
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                    ) =>
                {
                    return Err(ProtocolError::new("operation_timeout", None));
                }
                Err(_) => return Err(ProtocolError::new("request_invalid", None)),
            }
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
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(ProtocolError::new("operation_timeout", None));
            }
            self.stream
                .set_write_timeout(Some(remaining))
                .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
            match self.stream.write(&bytes[offset..]) {
                Ok(0) => return Err(ProtocolError::new("broker_unavailable", None)),
                Ok(written) => offset += written,
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                    ) =>
                {
                    return Err(ProtocolError::new("operation_timeout", None));
                }
                Err(_) => return Err(ProtocolError::new("broker_unavailable", None)),
            }
        }
        Ok(())
    }

    pub(crate) fn has_pending_input(&self) -> Result<bool, ProtocolError> {
        let mut byte = 0_u8;
        loop {
            // SAFETY: byte is a valid one-byte output and the stream remains live.
            let received = unsafe {
                libc::recv(
                    self.stream.as_raw_fd(),
                    (&mut byte as *mut u8).cast(),
                    1,
                    libc::MSG_PEEK | libc::MSG_DONTWAIT,
                )
            };
            if received > 0 {
                return Ok(true);
            }
            if received == 0 {
                return Ok(false);
            }
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            if error.kind() == std::io::ErrorKind::WouldBlock {
                return Ok(false);
            }
            return Err(ProtocolError::new("request_invalid", None));
        }
    }

    pub(crate) fn peer_connected(&self) -> Result<bool, ProtocolError> {
        let mut byte = 0_u8;
        loop {
            // SAFETY: byte is a valid one-byte output and the stream remains live.
            let received = unsafe {
                libc::recv(
                    self.stream.as_raw_fd(),
                    (&mut byte as *mut u8).cast(),
                    1,
                    libc::MSG_PEEK | libc::MSG_DONTWAIT,
                )
            };
            if received > 0 {
                return Ok(true);
            }
            if received == 0 {
                return Ok(false);
            }
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::Interrupted {
                continue;
            }
            if error.kind() == std::io::ErrorKind::WouldBlock {
                return Ok(true);
            }
            return Err(ProtocolError::new("broker_unavailable", None));
        }
    }

    pub(crate) fn shutdown(&mut self) {
        let _ = self.stream.shutdown(std::net::Shutdown::Both);
    }

    pub(crate) fn finish_response(&mut self, timeout: Duration) {
        const MAX_DISCARD_BYTES: usize = 64 * 1024;

        let _ = self.stream.shutdown(std::net::Shutdown::Write);
        if timeout.is_zero() {
            return;
        }
        let deadline = Instant::now() + timeout;
        let mut discarded = 0_usize;
        let mut buffer = Zeroizing::new([0_u8; 4096]);
        while discarded < MAX_DISCARD_BYTES {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() || self.stream.set_read_timeout(Some(remaining)).is_err() {
                break;
            }
            let limit = buffer.len().min(MAX_DISCARD_BYTES - discarded);
            match self.stream.read(&mut buffer[..limit]) {
                Ok(0) => break,
                Ok(read) => {
                    buffer[..read].zeroize();
                    discarded += read;
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                    ) =>
                {
                    break;
                }
                Err(_) => break,
            }
        }
    }

    pub(crate) fn inspect_server(
        &self,
    ) -> Result<(OsPeerContext, PathBuf, UnixPeerGuard), ProtocolError> {
        inspect_peer(&self.stream)
    }
}

fn connect_with_timeout(path: &Path, timeout: Duration) -> Result<UnixStream, ProtocolError> {
    if timeout.is_zero() {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    let path_bytes = path.as_os_str().as_bytes();
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    if path_bytes.is_empty()
        || path_bytes.contains(&0)
        || path_bytes.len() >= address.sun_path.len()
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    for (target, source) in address.sun_path.iter_mut().zip(path_bytes) {
        *target = *source as libc::c_char;
    }
    #[cfg(target_os = "linux")]
    let socket_type = libc::SOCK_STREAM | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK;
    #[cfg(target_os = "macos")]
    let socket_type = libc::SOCK_STREAM;
    // SAFETY: socket creates one private descriptor with no shared ownership.
    let raw = unsafe { libc::socket(libc::AF_UNIX, socket_type, 0) };
    if raw < 0 {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    // SAFETY: raw is newly returned and becomes owned exactly once here.
    let descriptor = unsafe { OwnedFd::from_raw_fd(raw) };
    // macOS has no socket creation flag for close-on-exec. Set it before this
    // descriptor is exposed to any broker code; Linux set both flags atomically.
    // SAFETY: both fcntl calls operate on the owned descriptor and use integer flags.
    let descriptor_flags = unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) };
    let status_flags = unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFL) };
    if descriptor_flags < 0
        || status_flags < 0
        || unsafe {
            libc::fcntl(
                descriptor.as_raw_fd(),
                libc::F_SETFD,
                descriptor_flags | libc::FD_CLOEXEC,
            )
        } < 0
        || unsafe {
            libc::fcntl(
                descriptor.as_raw_fd(),
                libc::F_SETFL,
                status_flags | libc::O_NONBLOCK,
            )
        } < 0
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    let address_len = (std::mem::offset_of!(libc::sockaddr_un, sun_path) + path_bytes.len() + 1)
        as libc::socklen_t;
    #[cfg(target_os = "macos")]
    {
        address.sun_len = u8::try_from(address_len)
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    }
    // SAFETY: address contains a bounded NUL-terminated filesystem UDS path.
    let connected = unsafe {
        libc::connect(
            descriptor.as_raw_fd(),
            (&address as *const libc::sockaddr_un).cast(),
            address_len,
        )
    };
    if connected != 0 {
        let error = std::io::Error::last_os_error();
        if !matches!(error.raw_os_error(), Some(libc::EINPROGRESS | libc::EAGAIN)) {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        let deadline = Instant::now() + timeout;
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            let milliseconds = remaining
                .as_millis()
                .saturating_add(1)
                .min(i32::MAX as u128) as libc::c_int;
            let mut poll_fd = libc::pollfd {
                fd: descriptor.as_raw_fd(),
                events: libc::POLLOUT,
                revents: 0,
            };
            // SAFETY: poll_fd points to one initialized descriptor entry.
            let polled = unsafe { libc::poll(&mut poll_fd, 1, milliseconds) };
            if polled < 0
                && std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted
            {
                continue;
            }
            if polled <= 0 {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            let mut socket_error = 0;
            let mut socket_error_len = std::mem::size_of_val(&socket_error) as libc::socklen_t;
            // SAFETY: both outputs match SO_ERROR's integer representation.
            if unsafe {
                libc::getsockopt(
                    descriptor.as_raw_fd(),
                    libc::SOL_SOCKET,
                    libc::SO_ERROR,
                    (&mut socket_error as *mut libc::c_int).cast(),
                    &mut socket_error_len,
                )
            } != 0
                || socket_error_len as usize != std::mem::size_of_val(&socket_error)
                || socket_error != 0
            {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            break;
        }
    }
    // SAFETY: restore blocking I/O while preserving every pre-existing status flag.
    if unsafe {
        libc::fcntl(
            descriptor.as_raw_fd(),
            libc::F_SETFL,
            status_flags & !libc::O_NONBLOCK,
        )
    } < 0
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(UnixStream::from(descriptor))
}

pub(crate) struct UnixPeerGuard {
    socket: OwnedFd,
    process_id: u32,
    executable: PathBuf,
    #[cfg(target_os = "linux")]
    user_boundary: String,
    #[cfg(target_os = "linux")]
    pidfd: OwnedFd,
    #[cfg(target_os = "macos")]
    audit_token: [u32; 8],
}

impl UnixPeerGuard {
    pub(crate) fn ensure_stable(&self) -> Result<(), ProtocolError> {
        #[cfg(target_os = "linux")]
        {
            let mut poll_fd = libc::pollfd {
                fd: self.pidfd.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            };
            // SAFETY: poll_fd points to one initialized descriptor entry.
            let result = unsafe { libc::poll(&mut poll_fd, 1, 0) };
            if result != 0 || current_executable(self.process_id)? != self.executable {
                return Err(ProtocolError::new("broker_unauthorized", None));
            }
            let (token_context, _) = linux_peer_credentials(self.socket.as_raw_fd())?;
            if token_context.process_id != self.process_id
                || token_context.user_boundary != self.user_boundary
            {
                return Err(ProtocolError::new("broker_unauthorized", None));
            }
        }
        #[cfg(target_os = "macos")]
        {
            let token = macos_peer_token(self.socket.as_raw_fd())?;
            if token != self.audit_token
                || token[5] != self.process_id
                || current_executable(self.process_id)? != self.executable
            {
                return Err(ProtocolError::new("broker_unauthorized", None));
            }
        }
        Ok(())
    }
}

fn validate_or_create_runtime_root(root: &Path) -> Result<(), ProtocolError> {
    if root.as_os_str().is_empty() || !root.is_absolute() {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    if !root.exists() {
        let mut builder = DirBuilder::new();
        builder.mode(0o700);
        builder
            .create(root)
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    }
    let metadata = std::fs::symlink_metadata(root)
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    if !metadata.file_type().is_dir()
        || metadata.file_type().is_symlink()
        || metadata.uid() != current_uid()
        || checked_mode(root)? != 0o700
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(())
}

fn open_secure_lock(path: &Path) -> Result<File, ProtocolError> {
    let existed = path.exists();
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    let metadata = file
        .metadata()
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    let path_metadata = std::fs::symlink_metadata(path)
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    if !metadata.file_type().is_file()
        || path_metadata.file_type().is_symlink()
        || metadata.uid() != current_uid()
        || metadata.dev() != path_metadata.dev()
        || metadata.ino() != path_metadata.ino()
        || metadata.nlink() != 1
        || metadata.mode() & 0o777 != 0o600
        || existed && path_metadata.mode() & 0o777 != 0o600
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(file)
}

fn remove_stale_socket_while_locked(path: &Path) -> Result<(), ProtocolError> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink()
                || !metadata.file_type().is_socket()
                || metadata.uid() != current_uid()
                || metadata.mode() & 0o777 != 0o600
            {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            if !socket_is_proven_stale(path)? {
                return Err(ProtocolError::new("broker_unavailable", None));
            }
            std::fs::remove_file(path)
                .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(ProtocolError::new("broker_unavailable", None)),
    }
    Ok(())
}

fn socket_is_proven_stale(path: &Path) -> Result<bool, ProtocolError> {
    let path_bytes = path.as_os_str().as_bytes();
    let mut address: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    if path_bytes.is_empty()
        || path_bytes.contains(&0)
        || path_bytes.len() >= address.sun_path.len()
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    address.sun_family = libc::AF_UNIX as libc::sa_family_t;
    for (target, source) in address.sun_path.iter_mut().zip(path_bytes) {
        *target = *source as libc::c_char;
    }
    #[cfg(target_os = "linux")]
    let socket_type = libc::SOCK_STREAM | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK;
    #[cfg(target_os = "macos")]
    let socket_type = libc::SOCK_STREAM;
    let raw = unsafe { libc::socket(libc::AF_UNIX, socket_type, 0) };
    if raw < 0 {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    let descriptor = unsafe { OwnedFd::from_raw_fd(raw) };
    let descriptor_flags = unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFD) };
    let status_flags = unsafe { libc::fcntl(descriptor.as_raw_fd(), libc::F_GETFL) };
    if descriptor_flags < 0
        || status_flags < 0
        || unsafe {
            libc::fcntl(
                descriptor.as_raw_fd(),
                libc::F_SETFD,
                descriptor_flags | libc::FD_CLOEXEC,
            )
        } < 0
        || unsafe {
            libc::fcntl(
                descriptor.as_raw_fd(),
                libc::F_SETFL,
                status_flags | libc::O_NONBLOCK,
            )
        } < 0
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    let address_len = (std::mem::offset_of!(libc::sockaddr_un, sun_path) + path_bytes.len() + 1)
        as libc::socklen_t;
    #[cfg(target_os = "macos")]
    {
        address.sun_len = u8::try_from(address_len)
            .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    }
    let connected = unsafe {
        libc::connect(
            descriptor.as_raw_fd(),
            (&address as *const libc::sockaddr_un).cast(),
            address_len,
        )
    };
    if connected == 0 {
        return Ok(false);
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ECONNREFUSED) {
        return Ok(true);
    }
    if !matches!(error.raw_os_error(), Some(libc::EINPROGRESS | libc::EAGAIN)) {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    let mut poll_fd = libc::pollfd {
        fd: descriptor.as_raw_fd(),
        events: libc::POLLOUT,
        revents: 0,
    };
    let polled = unsafe { libc::poll(&mut poll_fd, 1, 100) };
    if polled <= 0 {
        return Ok(false);
    }
    let mut socket_error = 0;
    let mut socket_error_len = std::mem::size_of_val(&socket_error) as libc::socklen_t;
    if unsafe {
        libc::getsockopt(
            descriptor.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_ERROR,
            (&mut socket_error as *mut libc::c_int).cast(),
            &mut socket_error_len,
        )
    } != 0
        || socket_error_len as usize != std::mem::size_of_val(&socket_error)
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(socket_error == libc::ECONNREFUSED)
}

fn secure_socket_metadata(path: &Path) -> Result<std::fs::Metadata, ProtocolError> {
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    if metadata.file_type().is_symlink()
        || !metadata.file_type().is_socket()
        || metadata.uid() != current_uid()
        || checked_mode(path)? != 0o600
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(metadata)
}

fn validate_client_endpoint_path(path: &Path) -> Result<(), ProtocolError> {
    let parent = path
        .parent()
        .ok_or_else(|| ProtocolError::new("broker_unavailable", None))?;
    let parent_metadata = std::fs::symlink_metadata(parent)
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    if !path.is_absolute()
        || parent_metadata.file_type().is_symlink()
        || !parent_metadata.file_type().is_dir()
        || parent_metadata.uid() != current_uid()
        || parent_metadata.mode() & 0o777 != 0o700
    {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    secure_socket_metadata(path)?;
    Ok(())
}

fn inspect_peer(
    stream: &UnixStream,
) -> Result<(OsPeerContext, PathBuf, UnixPeerGuard), ProtocolError> {
    #[cfg(target_os = "linux")]
    let (context, pidfd) = linux_peer_credentials(stream.as_raw_fd())?;
    #[cfg(target_os = "macos")]
    let (context, audit_token) = macos_peer_credentials(stream.as_raw_fd())?;
    if context.user_boundary != current_uid().to_string() {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let executable = current_executable(context.process_id)?;
    // SAFETY: F_DUPFD_CLOEXEC atomically creates a non-inheritable duplicate.
    let socket_fd = unsafe { libc::fcntl(stream.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 0) };
    if socket_fd < 0 {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    // SAFETY: socket_fd was returned as a new descriptor by dup.
    let socket = unsafe { OwnedFd::from_raw_fd(socket_fd) };
    let guard = UnixPeerGuard {
        socket,
        process_id: context.process_id,
        executable: executable.clone(),
        #[cfg(target_os = "linux")]
        user_boundary: context.user_boundary.clone(),
        #[cfg(target_os = "linux")]
        pidfd,
        #[cfg(target_os = "macos")]
        audit_token,
    };
    guard.ensure_stable()?;
    Ok((context, executable, guard))
}

#[cfg(target_os = "linux")]
fn linux_peer_credentials(fd: RawFd) -> Result<(OsPeerContext, OwnedFd), ProtocolError> {
    let mut credentials = libc::ucred {
        pid: 0,
        uid: u32::MAX,
        gid: u32::MAX,
    };
    let mut length = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    // SAFETY: credentials and length are valid output buffers for SO_PEERCRED.
    if unsafe {
        libc::getsockopt(
            fd,
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&mut credentials as *mut libc::ucred).cast(),
            &mut length,
        )
    } != 0
        || length as usize != std::mem::size_of::<libc::ucred>()
        || credentials.pid <= 0
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    // SAFETY: pidfd_open takes a positive PID and zero flags.
    let pidfd_raw = unsafe { libc::syscall(libc::SYS_pidfd_open, credentials.pid, 0) as RawFd };
    if pidfd_raw < 0 {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    // SAFETY: pidfd_raw is a newly returned descriptor.
    let pidfd = unsafe { OwnedFd::from_raw_fd(pidfd_raw) };
    let uid = credentials.uid.to_string();
    Ok((
        OsPeerContext {
            user_boundary: uid.clone(),
            logon_session: uid,
            process_id: credentials.pid as u32,
            credential_verified: true,
            stable_process_reference: true,
        },
        pidfd,
    ))
}

#[cfg(target_os = "macos")]
fn macos_peer_credentials(fd: RawFd) -> Result<(OsPeerContext, [u32; 8]), ProtocolError> {
    let token = macos_peer_token(fd)?;
    let mut uid = u32::MAX;
    let mut gid = u32::MAX;
    // SAFETY: uid and gid are valid outputs and fd is a connected UDS.
    if unsafe { libc::getpeereid(fd, &mut uid, &mut gid) } != 0
        || token[1] != uid
        || token[2] != gid
        || token[5] == 0
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let user = uid.to_string();
    Ok((
        OsPeerContext {
            user_boundary: user.clone(),
            logon_session: user,
            process_id: token[5],
            credential_verified: true,
            stable_process_reference: true,
        },
        token,
    ))
}

#[cfg(target_os = "macos")]
fn macos_peer_token(fd: RawFd) -> Result<[u32; 8], ProtocolError> {
    const SOL_LOCAL: libc::c_int = 0;
    const LOCAL_PEERTOKEN: libc::c_int = 0x006;
    let mut token = [0_u32; 8];
    let mut length = std::mem::size_of_val(&token) as libc::socklen_t;
    // SAFETY: token and length are valid output buffers for LOCAL_PEERTOKEN.
    if unsafe {
        libc::getsockopt(
            fd,
            SOL_LOCAL,
            LOCAL_PEERTOKEN,
            token.as_mut_ptr().cast(),
            &mut length,
        )
    } != 0
        || length as usize != std::mem::size_of_val(&token)
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    Ok(token)
}

#[cfg(target_os = "linux")]
fn current_executable(process_id: u32) -> Result<PathBuf, ProtocolError> {
    std::fs::read_link(format!("/proc/{process_id}/exe"))
        .and_then(|path| path.canonicalize())
        .map_err(|_| ProtocolError::new("broker_unauthorized", None))
}

#[cfg(target_os = "macos")]
fn current_executable(process_id: u32) -> Result<PathBuf, ProtocolError> {
    const PROC_PIDPATHINFO_MAXSIZE: usize = 4096;
    #[link(name = "proc")]
    extern "C" {
        fn proc_pidpath(
            pid: libc::c_int,
            buffer: *mut libc::c_void,
            buffer_size: u32,
        ) -> libc::c_int;
    }
    let mut buffer = vec![0_u8; PROC_PIDPATHINFO_MAXSIZE];
    // SAFETY: buffer is writable for its complete reported length.
    let length = unsafe {
        proc_pidpath(
            process_id as libc::c_int,
            buffer.as_mut_ptr().cast(),
            buffer.len() as u32,
        )
    };
    if length <= 0 || length as usize >= buffer.len() {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    buffer.truncate(length as usize);
    let path = std::str::from_utf8(&buffer)
        .map_err(|_| ProtocolError::new("broker_unauthorized", None))?;
    PathBuf::from(path)
        .canonicalize()
        .map_err(|_| ProtocolError::new("broker_unauthorized", None))
}
