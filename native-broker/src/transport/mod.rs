//! Security-critical native endpoint construction and bounded framed I/O.

use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::admission::{BrokerOsContext, OsPeerContext};
use crate::{canonical_json_bytes, encode_frame, validate_declared_length, ProtocolError};

#[cfg(unix)]
mod unix;
#[cfg(windows)]
mod windows;

pub const MAX_ACTIVE_CONNECTIONS: usize = 16;

#[derive(Clone)]
pub struct ConnectionLimiter {
    active: Arc<AtomicUsize>,
    limit: usize,
}

impl ConnectionLimiter {
    pub fn new(limit: usize) -> Self {
        Self {
            active: Arc::new(AtomicUsize::new(0)),
            limit,
        }
    }

    pub fn try_acquire(&self) -> Result<ConnectionPermit, ProtocolError> {
        let admitted = self
            .active
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < self.limit).then_some(current + 1)
            });
        if admitted.is_err() {
            return Err(ProtocolError::new("broker_busy", None));
        }
        Ok(ConnectionPermit {
            active: Arc::clone(&self.active),
        })
    }

    pub fn active(&self) -> usize {
        self.active.load(Ordering::Acquire)
    }
}

#[derive(Debug)]
pub struct ConnectionPermit {
    active: Arc<AtomicUsize>,
}

impl Drop for ConnectionPermit {
    fn drop(&mut self) {
        self.active.fetch_sub(1, Ordering::AcqRel);
    }
}

#[derive(Clone, Copy)]
pub struct EndpointSecurityReport {
    pub os_user_isolated: bool,
    pub peer_credentials_required: bool,
    pub single_instance_held: bool,
    pub remote_clients_rejected: bool,
    pub runtime_directory_mode: Option<u32>,
    pub endpoint_mode: Option<u32>,
    pub uses_abstract_socket: bool,
    pub explicit_dacl: bool,
    pub current_logon_sid_only: bool,
    pub client_pid_inspection: bool,
}

pub struct AcceptedConnection {
    stream: NativeStream,
    inspection: PeerInspection,
}

impl AcceptedConnection {
    pub fn peer_context(&self) -> &OsPeerContext {
        self.inspection.context()
    }

    pub fn peer_executable(&self) -> &Path {
        self.inspection.executable()
    }

    pub fn ensure_peer_stable(&self) -> Result<(), ProtocolError> {
        self.inspection.ensure_stable()
    }

    pub fn stream_mut(&mut self) -> &mut NativeStream {
        &mut self.stream
    }
}

impl fmt::Debug for AcceptedConnection {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AcceptedConnection")
            .field(
                "credential_verified",
                &self.inspection.context.credential_verified,
            )
            .field(
                "stable_process_reference",
                &self.inspection.context.stable_process_reference,
            )
            .finish_non_exhaustive()
    }
}

pub struct PeerInspection {
    context: OsPeerContext,
    executable: PathBuf,
    guard: PlatformPeerGuard,
}

impl PeerInspection {
    pub fn context(&self) -> &OsPeerContext {
        &self.context
    }

    pub fn executable(&self) -> &Path {
        &self.executable
    }

    pub fn ensure_stable(&self) -> Result<(), ProtocolError> {
        self.guard.ensure_stable()
    }
}

impl fmt::Debug for PeerInspection {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PeerInspection")
            .field("credential_verified", &self.context.credential_verified)
            .field(
                "stable_process_reference",
                &self.context.stable_process_reference,
            )
            .finish_non_exhaustive()
    }
}

pub struct NativeStream {
    inner: PlatformStream,
}

impl NativeStream {
    pub fn connect(publication: &str, timeout: Duration) -> Result<Self, ProtocolError> {
        if publication.is_empty() || timeout.is_zero() {
            return Err(ProtocolError::new("broker_unavailable", None));
        }
        Ok(Self {
            inner: PlatformStream::connect(publication, timeout)?,
        })
    }

    pub fn read_frame(
        &mut self,
        max_frame_bytes: u64,
        timeout: Duration,
    ) -> Result<Option<Vec<u8>>, ProtocolError> {
        if max_frame_bytes == 0 || timeout.is_zero() {
            return Err(ProtocolError::new("request_invalid", None));
        }
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| ProtocolError::new("operation_timeout", None))?;
        self.read_frame_until(max_frame_bytes, deadline)
    }

    pub fn read_frame_until(
        &mut self,
        max_frame_bytes: u64,
        deadline: Instant,
    ) -> Result<Option<Vec<u8>>, ProtocolError> {
        if max_frame_bytes == 0 {
            return Err(ProtocolError::new("request_invalid", None));
        }
        let mut header = [0_u8; 4];
        match self
            .inner
            .read_exact_bounded(&mut header, remaining(deadline)?, true)?
        {
            ReadOutcome::Disconnected => return Ok(None),
            ReadOutcome::Complete => {}
        }
        let declared = u32::from_be_bytes(header) as u64;
        validate_declared_length(declared, Some(max_frame_bytes))?;
        let mut body = vec![0_u8; declared as usize];
        match self
            .inner
            .read_exact_bounded(&mut body, remaining(deadline)?, false)?
        {
            ReadOutcome::Complete => Ok(Some(body)),
            ReadOutcome::Disconnected => Err(ProtocolError::new("request_invalid", None)),
        }
    }

    pub fn read_hello_frame(
        &mut self,
        max_frame_bytes: u64,
        timeout: Duration,
    ) -> Result<Option<Vec<u8>>, ProtocolError> {
        if timeout.is_zero() {
            return Err(ProtocolError::new("request_invalid", None));
        }
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| ProtocolError::new("operation_timeout", None))?;
        self.read_hello_frame_until(max_frame_bytes, deadline)
    }

    pub fn read_hello_frame_until(
        &mut self,
        max_frame_bytes: u64,
        deadline: Instant,
    ) -> Result<Option<Vec<u8>>, ProtocolError> {
        let frame = self.read_frame_until(max_frame_bytes, deadline)?;
        if frame.is_some() && self.inner.has_pending_input()? {
            return Err(ProtocolError::new("request_invalid", None));
        }
        Ok(frame)
    }

    pub fn ensure_no_pending_input(&self) -> Result<(), ProtocolError> {
        if self.inner.has_pending_input()? {
            return Err(ProtocolError::new("request_invalid", None));
        }
        Ok(())
    }

    pub(crate) fn has_pending_input(&self) -> Result<bool, ProtocolError> {
        self.inner.has_pending_input()
    }

    pub fn write_value(
        &mut self,
        value: &Value,
        max_frame_bytes: u64,
        timeout: Duration,
    ) -> Result<(), ProtocolError> {
        if timeout.is_zero() {
            return Err(ProtocolError::new("operation_timeout", None));
        }
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or_else(|| ProtocolError::new("operation_timeout", None))?;
        self.write_value_until(value, max_frame_bytes, deadline)
    }

    pub fn write_value_until(
        &mut self,
        value: &Value,
        max_frame_bytes: u64,
        deadline: Instant,
    ) -> Result<(), ProtocolError> {
        let bytes = canonical_json_bytes(value)?;
        let frame = encode_frame(&bytes, Some(max_frame_bytes))?;
        self.inner.write_all_bounded(&frame, remaining(deadline)?)
    }

    pub fn shutdown(&mut self) {
        self.inner.shutdown();
    }

    pub(crate) fn finish_response_until(&mut self, deadline: Instant) {
        let grace = deadline.saturating_duration_since(Instant::now());
        self.inner.finish_response(grace);
    }

    #[doc(hidden)]
    pub fn write_raw_for_test(
        &mut self,
        bytes: &[u8],
        timeout: Duration,
    ) -> Result<(), ProtocolError> {
        self.inner.write_all_bounded(bytes, timeout)
    }

    pub fn inspect_server(&self) -> Result<PeerInspection, ProtocolError> {
        let (context, executable, guard) = self.inner.inspect_server()?;
        Ok(PeerInspection {
            context,
            executable,
            guard,
        })
    }
}

fn remaining(deadline: Instant) -> Result<Duration, ProtocolError> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        return Err(ProtocolError::new("operation_timeout", None));
    }
    Ok(remaining)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ReadOutcome {
    Complete,
    Disconnected,
}

pub struct PlatformEndpoint {
    inner: Option<PlatformEndpointInner>,
    hello_timeout: Duration,
}

pub struct PlatformEndpointReservation {
    inner: Option<PlatformEndpointReservationInner>,
}

#[cfg(unix)]
type PlatformEndpointInner = unix::UnixEndpoint;
#[cfg(unix)]
type PlatformEndpointReservationInner = unix::UnixEndpointReservation;
#[cfg(unix)]
type PlatformStream = unix::UnixNativeStream;
#[cfg(unix)]
type PlatformPeerGuard = unix::UnixPeerGuard;

#[cfg(windows)]
type PlatformEndpointInner = windows::WindowsEndpoint;
#[cfg(windows)]
type PlatformEndpointReservationInner = windows::WindowsEndpointReservation;
#[cfg(windows)]
type PlatformStream = windows::WindowsNativeStream;
#[cfg(windows)]
type PlatformPeerGuard = windows::WindowsPeerGuard;

impl PlatformEndpoint {
    pub fn current_os_context() -> Result<BrokerOsContext, ProtocolError> {
        PlatformEndpointInner::current_context()
    }
    pub fn default_runtime_root(install_root: &Path) -> Result<PathBuf, ProtocolError> {
        PlatformEndpointInner::default_runtime_root(install_root)
    }

    pub fn publication_for(root: &Path) -> Result<String, ProtocolError> {
        validate_production_root(root)?;
        PlatformEndpointInner::publication_for(root)
    }

    #[doc(hidden)]
    pub fn publication_for_test(root: &Path) -> Result<String, ProtocolError> {
        PlatformEndpointInner::publication_for(root)
    }

    pub fn create(root: &Path) -> Result<Self, ProtocolError> {
        Self::reserve(root)?.publish()
    }

    pub fn create_for_test(root: &Path) -> Result<Self, ProtocolError> {
        Self::reserve_for_test(root)?.publish()
    }

    pub fn reserve(root: &Path) -> Result<PlatformEndpointReservation, ProtocolError> {
        validate_production_root(root)?;
        Ok(PlatformEndpointReservation {
            inner: Some(PlatformEndpointInner::reserve(root)?),
        })
    }

    #[doc(hidden)]
    pub fn reserve_for_test(root: &Path) -> Result<PlatformEndpointReservation, ProtocolError> {
        Ok(PlatformEndpointReservation {
            inner: Some(PlatformEndpointInner::reserve(root)?),
        })
    }

    pub fn create_inert_for_test(timeout: Duration) -> Result<Self, ProtocolError> {
        if timeout.is_zero() {
            return Err(ProtocolError::new("operation_failed", None));
        }
        Ok(Self {
            inner: None,
            hello_timeout: timeout,
        })
    }

    pub fn accept(
        &mut self,
        timeout: Duration,
    ) -> Result<Option<AcceptedConnection>, ProtocolError> {
        let inner = self
            .inner
            .as_mut()
            .ok_or_else(|| ProtocolError::new("operation_failed", None))?;
        let Some((stream, peer, executable, guard)) = inner.accept(timeout)? else {
            return Ok(None);
        };
        Ok(Some(AcceptedConnection {
            stream: NativeStream { inner: stream },
            inspection: PeerInspection {
                context: peer,
                executable,
                guard,
            },
        }))
    }

    pub fn broker_context(&self) -> Result<BrokerOsContext, ProtocolError> {
        self.inner
            .as_ref()
            .ok_or_else(|| ProtocolError::new("operation_failed", None))?
            .broker_context()
    }

    pub fn security_report(&self) -> Result<EndpointSecurityReport, ProtocolError> {
        self.inner
            .as_ref()
            .map(PlatformEndpointInner::security_report)
            .ok_or_else(|| ProtocolError::new("operation_failed", None))
    }

    pub fn publication(&self) -> String {
        self.inner
            .as_ref()
            .map(PlatformEndpointInner::publication)
            .unwrap_or_default()
    }

    pub fn filesystem_path(&self) -> Option<&Path> {
        self.inner
            .as_ref()
            .and_then(PlatformEndpointInner::filesystem_path)
    }

    pub fn negotiate_bytes(&self, bytes: &[u8]) -> Result<(), ProtocolError> {
        let _deadline = self.hello_timeout;
        let mut decoder = crate::FrameDecoder::for_hello()?;
        let frames = decoder.feed(bytes)?;
        decoder.finish()?;
        if frames.len() == 1 {
            Ok(())
        } else {
            Err(ProtocolError::new("request_invalid", None))
        }
    }

    pub fn disconnect_during_hello(&self) -> Result<(), ProtocolError> {
        self.negotiate_bytes(&[])
    }
}

impl PlatformEndpointReservation {
    pub fn publish(mut self) -> Result<PlatformEndpoint, ProtocolError> {
        let inner = self
            .inner
            .take()
            .ok_or_else(|| ProtocolError::new("broker_unavailable", None))?;
        Ok(PlatformEndpoint {
            inner: Some(inner.publish()?),
            hello_timeout: Duration::from_secs(5),
        })
    }
}

fn validate_production_root(root: &Path) -> Result<(), ProtocolError> {
    let expected = PlatformEndpointInner::default_runtime_root(root)?;
    if root != expected {
        return Err(ProtocolError::new("broker_unavailable", None));
    }
    Ok(())
}

#[cfg(unix)]
pub(crate) fn checked_mode(path: &Path) -> Result<u32, ProtocolError> {
    use std::os::unix::fs::MetadataExt;

    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| ProtocolError::new("broker_unavailable", None))?;
    Ok(metadata.mode() & 0o777)
}

#[cfg(unix)]
pub(crate) fn current_uid() -> u32 {
    // SAFETY: geteuid takes no pointers and has no preconditions.
    unsafe { libc::geteuid() }
}
