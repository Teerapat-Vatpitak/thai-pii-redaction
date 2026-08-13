//! Package-maintenance drain and replacement lifecycle.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::process::Command;
use std::time::{Duration, Instant};

use crate::control_client::BrokerControlClient;
use crate::manifest::ComponentManifest;
use crate::transport::PlatformEndpoint;
use crate::ProtocolError;

pub const COMPONENT_MAINTENANCE_FILE: &str = ".aiguard-component-maintenance-v1";
pub const COMPONENT_TRANSACTION_FILE: &str = ".aiguard-component-transaction-v1";
const COMPONENT_MAINTENANCE_BYTES: &[u8] = b"AIGUARD_COMPONENT_MAINTENANCE_V1\n";
const COMPONENT_TRANSACTION_TOKEN_BYTES: usize = 32;
const COMPONENT_TRANSACTION_TEXT_BYTES: usize = COMPONENT_TRANSACTION_TOKEN_BYTES * 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DrainOutcome {
    AlreadyStopped,
    Stopped,
}

#[cfg(target_os = "linux")]
pub struct AppImageComponentLease {
    _directory: std::fs::File,
}

#[cfg(target_os = "linux")]
impl AppImageComponentLease {
    pub fn acquire(component_root: &Path) -> Result<Self, ProtocolError> {
        use std::os::fd::AsRawFd;
        use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

        let shared_root = appimage_shared_root(component_root)?;
        let named = validate_appimage_shared_root(shared_root)?;
        let directory = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
            .open(shared_root)
            .map_err(|_| unavailable_error())?;
        let opened = directory.metadata().map_err(|_| unavailable_error())?;
        if opened.dev() != named.dev() || opened.ino() != named.ino() {
            return unavailable();
        }
        // SAFETY: directory is a live owned descriptor held for the lease lifetime.
        if unsafe { libc::flock(directory.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return unavailable();
        }
        Ok(Self {
            _directory: directory,
        })
    }
}

#[cfg(target_os = "linux")]
fn appimage_shared_root(component_root: &Path) -> Result<&Path, ProtocolError> {
    component_root
        .parent()
        .filter(|path| path.is_absolute())
        .ok_or_else(unavailable_error)
}

#[cfg(target_os = "linux")]
fn validate_appimage_shared_root(shared_root: &Path) -> Result<std::fs::Metadata, ProtocolError> {
    use std::os::unix::fs::MetadataExt;

    let named = std::fs::symlink_metadata(shared_root).map_err(|_| unavailable_error())?;
    if !named.file_type().is_dir()
        || named.file_type().is_symlink()
        || named.uid() != unsafe { libc::geteuid() }
        || named.mode() & 0o7777 != 0o700
    {
        return unavailable();
    }
    Ok(named)
}

pub fn begin_component_replacement(install_root: &Path) -> Result<(), ProtocolError> {
    validate_install_root(install_root)?;
    let marker = install_root.join(COMPONENT_MAINTENANCE_FILE);
    match create_component_marker(&marker) {
        Ok(()) => verify_component_marker(&marker),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            verify_component_marker(&marker)
        }
        Err(_) => unavailable(),
    }
}

pub fn begin_owned_component_replacement(install_root: &Path) -> Result<(), ProtocolError> {
    validate_install_root(install_root)?;
    let marker = install_root.join(COMPONENT_MAINTENANCE_FILE);
    create_component_marker(&marker).map_err(|_| unavailable_error())?;
    verify_component_marker(&marker)
}

pub fn begin_package_replacement(install_root: &Path) -> Result<String, ProtocolError> {
    validate_install_root(install_root)?;
    let receipt = install_root.join(COMPONENT_TRANSACTION_FILE);
    let token = match std::fs::symlink_metadata(&receipt) {
        Ok(_) => read_component_transaction(&receipt),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let token = random_component_transaction()?;
            let mut bytes = token.as_bytes().to_vec();
            bytes.push(b'\n');
            match create_owned_file(&receipt, &bytes) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(_) => return unavailable(),
            }
            let observed = read_component_transaction(&receipt)?;
            if observed != token {
                return unavailable();
            }
            Ok(token)
        }
        Err(_) => unavailable(),
    }?;
    // Publish the private receipt first. A crash at that boundary leaves no
    // replacement in progress, and every ordinary manager action rejects the
    // orphan receipt until the package transaction resumes and creates the
    // public admission barrier.
    begin_component_replacement(install_root)?;
    Ok(token)
}

pub fn package_replacement_token(install_root: &Path) -> Result<Option<String>, ProtocolError> {
    if !component_replacement_active(install_root)? {
        let receipt = install_root.join(COMPONENT_TRANSACTION_FILE);
        return match std::fs::symlink_metadata(receipt) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            _ => unavailable(),
        };
    }
    let receipt = install_root.join(COMPONENT_TRANSACTION_FILE);
    match std::fs::symlink_metadata(&receipt) {
        Ok(_) => read_component_transaction(&receipt).map(Some),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(_) => unavailable(),
    }
}

pub fn finish_package_replacement(install_root: &Path, token: &str) -> Result<(), ProtocolError> {
    validate_install_root(install_root)?;
    let receipt = install_root.join(COMPONENT_TRANSACTION_FILE);
    let marker = install_root.join(COMPONENT_MAINTENANCE_FILE);
    validate_transaction_token(token)?;
    if read_component_transaction(&receipt)? != token {
        return unavailable();
    }
    match std::fs::symlink_metadata(&marker) {
        Ok(_) => {
            verify_component_marker(&marker)?;
            std::fs::remove_file(&marker).map_err(|_| unavailable_error())?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return unavailable(),
    }
    verify_owned_file(&receipt, COMPONENT_TRANSACTION_TEXT_BYTES as u64 + 1)?;
    std::fs::remove_file(receipt).map_err(|_| unavailable_error())
}

pub fn validate_package_replacement(install_root: &Path, token: &str) -> Result<(), ProtocolError> {
    validate_transaction_token(token)?;
    let observed = package_replacement_token(install_root)?.ok_or_else(unavailable_error)?;
    if observed != token {
        return unavailable();
    }
    Ok(())
}

pub fn validate_legacy_component_replacement(install_root: &Path) -> Result<(), ProtocolError> {
    #[cfg(windows)]
    normalize_legacy_component_marker_owner(install_root)?;
    if package_replacement_token(install_root)?.is_some()
        || !component_replacement_active(install_root)?
    {
        return unavailable();
    }
    Ok(())
}

pub fn finish_legacy_component_replacement(install_root: &Path) -> Result<(), ProtocolError> {
    validate_legacy_component_replacement(install_root)?;
    finish_component_replacement(install_root)
}

pub fn component_replacement_active(install_root: &Path) -> Result<bool, ProtocolError> {
    validate_install_root(install_root)?;
    let marker = install_root.join(COMPONENT_MAINTENANCE_FILE);
    match std::fs::symlink_metadata(&marker) {
        Ok(_) => {
            verify_component_marker(&marker)?;
            Ok(true)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => unavailable(),
    }
}

pub fn finish_component_replacement(install_root: &Path) -> Result<(), ProtocolError> {
    validate_install_root(install_root)?;
    match std::fs::symlink_metadata(install_root.join(COMPONENT_TRANSACTION_FILE)) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        _ => return unavailable(),
    }
    let marker = install_root.join(COMPONENT_MAINTENANCE_FILE);
    match std::fs::symlink_metadata(&marker) {
        Ok(_) => {
            verify_component_marker(&marker)?;
            std::fs::remove_file(marker).map_err(|_| unavailable_error())
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => unavailable(),
    }
}

fn create_component_marker(path: &Path) -> std::io::Result<()> {
    create_owned_file(path, COMPONENT_MAINTENANCE_BYTES)
}

fn create_owned_file(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    #[cfg(windows)]
    if !crate::manifest::windows_set_owner_to_current_user(path) {
        let _ = std::fs::remove_file(path);
        return Err(std::io::Error::other("component marker owner"));
    }
    Ok(())
}

fn random_component_transaction() -> Result<String, ProtocolError> {
    let mut random = [0_u8; COMPONENT_TRANSACTION_TOKEN_BYTES];
    getrandom::fill(&mut random).map_err(|_| unavailable_error())?;
    let mut token = String::with_capacity(COMPONENT_TRANSACTION_TEXT_BYTES);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in random {
        token.push(HEX[usize::from(byte >> 4)] as char);
        token.push(HEX[usize::from(byte & 0x0f)] as char);
    }
    Ok(token)
}

fn validate_transaction_token(token: &str) -> Result<(), ProtocolError> {
    if token.len() != COMPONENT_TRANSACTION_TEXT_BYTES
        || !token
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return unavailable();
    }
    Ok(())
}

fn read_component_transaction(path: &Path) -> Result<String, ProtocolError> {
    verify_owned_file(path, COMPONENT_TRANSACTION_TEXT_BYTES as u64 + 1)?;
    let bytes = std::fs::read(path).map_err(|_| unavailable_error())?;
    if bytes.last() != Some(&b'\n') {
        return unavailable();
    }
    let token = std::str::from_utf8(&bytes[..bytes.len() - 1])
        .map_err(|_| unavailable_error())?
        .to_owned();
    validate_transaction_token(&token)?;
    Ok(token)
}

fn validate_install_root(path: &Path) -> Result<(), ProtocolError> {
    if !path.is_absolute() {
        return unavailable();
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable_error())?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return unavailable();
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;

        if metadata.uid() != 0 && metadata.uid() != unsafe { libc::geteuid() } {
            return unavailable();
        }
    }
    Ok(())
}

fn verify_component_marker(path: &Path) -> Result<(), ProtocolError> {
    verify_owned_file(path, COMPONENT_MAINTENANCE_BYTES.len() as u64)?;
    let bytes = std::fs::read(path).map_err(|_| unavailable_error())?;
    if bytes != COMPONENT_MAINTENANCE_BYTES {
        return unavailable();
    }
    Ok(())
}

fn verify_owned_file(path: &Path, expected_len: u64) -> Result<(), ProtocolError> {
    let metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable_error())?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() != expected_len
    {
        return unavailable();
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;

        if (metadata.uid() != 0 && metadata.uid() != unsafe { libc::geteuid() })
            || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
        {
            return unavailable();
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;

        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || !crate::manifest::windows_file_has_one_link(path)
            || !crate::manifest::windows_owner_is_current_user(path)
        {
            return unavailable();
        }
    }
    Ok(())
}

#[cfg(windows)]
fn normalize_legacy_component_marker_owner(install_root: &Path) -> Result<(), ProtocolError> {
    let marker = install_root.join(COMPONENT_MAINTENANCE_FILE);
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    let metadata = std::fs::symlink_metadata(&marker).map_err(|_| unavailable_error())?;
    if !metadata.file_type().is_file()
        || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
        || metadata.len() != COMPONENT_MAINTENANCE_BYTES.len() as u64
        || !crate::manifest::windows_file_has_one_link(&marker)
        || std::fs::read(&marker).map_err(|_| unavailable_error())? != COMPONENT_MAINTENANCE_BYTES
        || !crate::manifest::windows_set_owner_to_current_user(&marker)
    {
        return unavailable();
    }
    verify_component_marker(&marker)
}

pub fn drain_existing_broker(
    install_root: &Path,
    manifest_path: &Path,
    product_version: &str,
    timeout: Duration,
) -> Result<DrainOutcome, ProtocolError> {
    let endpoint_root = PlatformEndpoint::default_runtime_root(install_root)?;
    drain_existing_broker_inner(
        &endpoint_root,
        manifest_path,
        product_version,
        timeout,
        false,
    )
}

pub fn prove_broker_inactive(install_root: &Path) -> Result<(), ProtocolError> {
    let endpoint_root = PlatformEndpoint::default_runtime_root(install_root)?;
    prove_inactive(&endpoint_root, false)
}

pub fn wait_for_broker_inactive(
    install_root: &Path,
    timeout: Duration,
) -> Result<(), ProtocolError> {
    if timeout.is_zero() || timeout > Duration::from_secs(60) {
        return unavailable();
    }
    let endpoint_root = PlatformEndpoint::default_runtime_root(install_root)?;
    let deadline = Instant::now()
        .checked_add(timeout)
        .ok_or_else(unavailable_error)?;
    wait_for_inactive(deadline, || prove_inactive(&endpoint_root, false))
}

#[doc(hidden)]
pub fn configure_maintenance_command(command: &mut Command) {
    #[cfg(unix)]
    crate::installed_product::configure_child_command(command);
    #[cfg(windows)]
    {
        let environment = crate::installed_product::child_environment();
        command.env_clear().envs(environment);
    }
}

#[doc(hidden)]
pub fn drain_existing_broker_for_test(
    endpoint_root: &Path,
    manifest_path: &Path,
    product_version: &str,
    timeout: Duration,
) -> Result<DrainOutcome, ProtocolError> {
    drain_existing_broker_inner(endpoint_root, manifest_path, product_version, timeout, true)
}

fn drain_existing_broker_inner(
    endpoint_root: &Path,
    manifest_path: &Path,
    product_version: &str,
    timeout: Duration,
    test_endpoint: bool,
) -> Result<DrainOutcome, ProtocolError> {
    if timeout.is_zero() || timeout > Duration::from_secs(60) {
        return unavailable();
    }
    let started = Instant::now();
    let deadline = started.checked_add(timeout).ok_or_else(unavailable_error)?;
    let manifest = ComponentManifest::load(manifest_path, product_version)?;
    let executable = std::env::current_exe().map_err(|_| unavailable_error())?;
    let package = manifest.verify_client_executable(&executable)?;
    if package.allowed_role != "maintenance" {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    let prepared = if test_endpoint {
        BrokerControlClient::prepare_existing_for_test(
            endpoint_root,
            manifest_path,
            "maintenance",
            product_version,
        )
    } else {
        BrokerControlClient::prepare_existing(
            endpoint_root,
            manifest_path,
            "maintenance",
            product_version,
        )
    }?;
    let client = connect_for_drain_until(
        deadline,
        || prepared.connect_until(deadline),
        || prove_inactive(endpoint_root, test_endpoint),
    );
    let mut client = match client {
        Ok(Some(client)) => client,
        Ok(None) => return Ok(DrainOutcome::AlreadyStopped),
        Err(error) => return Err(error),
    };
    let drain_result = client.maintenance_drain_stop_until(deadline);
    drop(client);
    if let Err(error) = drain_result {
        return wait_for_stopped_after_drain_error(error, deadline, || {
            prove_inactive(endpoint_root, test_endpoint)
        });
    }
    wait_for_inactive(deadline, || prove_inactive(endpoint_root, test_endpoint))?;
    Ok(DrainOutcome::Stopped)
}

fn connect_for_drain_until<T>(
    deadline: Instant,
    mut connect: impl FnMut() -> Result<T, ProtocolError>,
    mut prove_inactive: impl FnMut() -> Result<(), ProtocolError>,
) -> Result<Option<T>, ProtocolError> {
    loop {
        if deadline.saturating_duration_since(Instant::now()).is_zero() {
            return unavailable();
        }
        match connect() {
            Ok(client) => return Ok(Some(client)),
            Err(error)
                if matches!(
                    error.code(),
                    "broker_unavailable" | "broker_busy" | "operation_timeout"
                ) =>
            {
                match prove_inactive() {
                    Ok(()) => return Ok(None),
                    Err(inactive_error)
                        if inactive_error.code() == "broker_unavailable"
                            && Instant::now() < deadline =>
                    {
                        std::thread::sleep(
                            deadline
                                .saturating_duration_since(Instant::now())
                                .min(Duration::from_millis(25)),
                        );
                    }
                    Err(_) => return unavailable(),
                }
            }
            Err(error) => return Err(error),
        }
    }
}

fn prove_inactive(root: &Path, test_endpoint: bool) -> Result<(), ProtocolError> {
    let reservation = if test_endpoint {
        PlatformEndpoint::reserve_for_test(root)
    } else {
        PlatformEndpoint::reserve(root)
    }?;
    drop(reservation);
    Ok(())
}

fn wait_for_inactive(
    deadline: Instant,
    mut prove: impl FnMut() -> Result<(), ProtocolError>,
) -> Result<(), ProtocolError> {
    loop {
        match prove() {
            Ok(()) => return Ok(()),
            Err(error) if error.code() == "broker_unavailable" && Instant::now() < deadline => {
                std::thread::sleep(
                    deadline
                        .saturating_duration_since(Instant::now())
                        .min(Duration::from_millis(25)),
                );
            }
            Err(_) => return unavailable(),
        }
    }
}

fn wait_for_already_stopped(
    deadline: Instant,
    prove: impl FnMut() -> Result<(), ProtocolError>,
) -> Result<DrainOutcome, ProtocolError> {
    wait_for_inactive(deadline, prove)?;
    Ok(DrainOutcome::AlreadyStopped)
}

fn wait_for_stopped_after_drain_error(
    error: ProtocolError,
    deadline: Instant,
    prove: impl FnMut() -> Result<(), ProtocolError>,
) -> Result<DrainOutcome, ProtocolError> {
    if matches!(error.code(), "broker_unavailable" | "operation_timeout") {
        return wait_for_already_stopped(deadline, prove);
    }
    Err(error)
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
    fn inactive_wait_is_bounded_and_uses_fixed_failure() {
        let mut attempts = 0;
        wait_for_inactive(Instant::now() + Duration::from_secs(1), || {
            attempts += 1;
            if attempts == 3 {
                Ok(())
            } else {
                unavailable()
            }
        })
        .unwrap();
        assert_eq!(attempts, 3);

        let error = wait_for_inactive(Instant::now(), unavailable).unwrap_err();
        assert_eq!(error.code(), "broker_unavailable");
        assert_eq!(
            format!("{error:?}"),
            "ProtocolError { code: \"broker_unavailable\", .. }"
        );
    }

    #[test]
    fn inactive_wait_reconciles_only_terminal_shutdown_races() {
        let mut attempts = 0;
        let outcome = wait_for_stopped_after_drain_error(
            ProtocolError::new("operation_timeout", None),
            Instant::now() + Duration::from_secs(1),
            || {
                attempts += 1;
                if attempts == 3 {
                    Ok(())
                } else {
                    unavailable()
                }
            },
        )
        .unwrap();
        assert_eq!(attempts, 3);
        assert_eq!(outcome, DrainOutcome::AlreadyStopped);

        let error = wait_for_stopped_after_drain_error(
            ProtocolError::new("broker_unauthorized", None),
            Instant::now() + Duration::from_secs(1),
            || panic!("unauthorized drain must not be reconciled"),
        )
        .unwrap_err();
        assert_eq!(error.code(), "broker_unauthorized");
    }

    #[test]
    fn drain_connect_retries_only_pre_request_transient_failures() {
        let mut attempts = 0;
        let mut inactive_proofs = 0;
        let connected = connect_for_drain_until(
            Instant::now() + Duration::from_secs(1),
            || {
                attempts += 1;
                match attempts {
                    1 => Err(ProtocolError::new("broker_unavailable", None)),
                    2 => Err(ProtocolError::new("broker_busy", None)),
                    3 => Err(ProtocolError::new("operation_timeout", None)),
                    _ => Ok(7_u8),
                }
            },
            || {
                inactive_proofs += 1;
                unavailable()
            },
        )
        .unwrap();
        assert_eq!(connected, Some(7));
        assert_eq!(attempts, 4);
        assert_eq!(inactive_proofs, 3);

        let mut attempts = 0;
        let stopped = connect_for_drain_until(
            Instant::now() + Duration::from_secs(1),
            || {
                attempts += 1;
                Err::<u8, _>(ProtocolError::new("broker_unavailable", None))
            },
            || Ok(()),
        )
        .unwrap();
        assert_eq!(stopped, None);
        assert_eq!(attempts, 1);

        let mut proved = false;
        let error = connect_for_drain_until(
            Instant::now() + Duration::from_secs(1),
            || Err::<u8, _>(ProtocolError::new("broker_unauthorized", None)),
            || {
                proved = true;
                Ok(())
            },
        )
        .unwrap_err();
        assert_eq!(error.code(), "broker_unauthorized");
        assert!(!proved);

        let mut attempts = 0;
        let bounded = connect_for_drain_until(
            Instant::now() + Duration::from_millis(30),
            || {
                attempts += 1;
                Err::<u8, _>(ProtocolError::new("broker_unavailable", None))
            },
            unavailable,
        )
        .unwrap_err();
        assert_eq!(bounded.code(), "broker_unavailable");
        assert!(attempts >= 1);
    }

    #[test]
    fn package_transaction_receipt_is_exact_resumable_and_owner_required() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-transaction-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();

        let token = begin_package_replacement(&root).unwrap();
        assert_eq!(token.len(), COMPONENT_TRANSACTION_TEXT_BYTES);
        assert_eq!(begin_package_replacement(&root).unwrap(), token);
        assert!(begin_owned_component_replacement(&root).is_err());
        assert!(finish_component_replacement(&root).is_err());
        assert!(finish_package_replacement(&root, &"0".repeat(64)).is_err());
        assert!(component_replacement_active(&root).unwrap());
        assert!(root.join(COMPONENT_TRANSACTION_FILE).is_file());

        finish_package_replacement(&root, &token).unwrap();
        assert!(!component_replacement_active(&root).unwrap());
        assert!(!root.join(COMPONENT_TRANSACTION_FILE).exists());

        begin_component_replacement(&root).unwrap();
        finish_legacy_component_replacement(&root).unwrap();
        assert!(!component_replacement_active(&root).unwrap());
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn malformed_package_receipt_never_opens_the_barrier() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-receipt-invalid-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir(&root).unwrap();
        let token = begin_package_replacement(&root).unwrap();
        std::fs::write(
            root.join(COMPONENT_TRANSACTION_FILE),
            format!("{token}\n\n"),
        )
        .unwrap();
        assert!(package_replacement_token(&root).is_err());
        assert!(finish_package_replacement(&root, &token).is_err());
        assert!(component_replacement_active(&root).unwrap());
        std::fs::remove_file(root.join(COMPONENT_TRANSACTION_FILE)).unwrap();
        std::fs::remove_file(root.join(COMPONENT_MAINTENANCE_FILE)).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn package_completion_retry_removes_a_valid_receipt_after_marker_open() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-finish-retry-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir(&root).unwrap();
        let token = begin_package_replacement(&root).unwrap();
        std::fs::remove_file(root.join(COMPONENT_MAINTENANCE_FILE)).unwrap();
        finish_package_replacement(&root, &token).unwrap();
        assert!(!root.join(COMPONENT_TRANSACTION_FILE).exists());
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn package_transaction_resumes_a_receipt_created_before_the_barrier() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-receipt-resume-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir(&root).unwrap();
        let token = "a".repeat(COMPONENT_TRANSACTION_TEXT_BYTES);
        create_owned_file(
            &root.join(COMPONENT_TRANSACTION_FILE),
            format!("{token}\n").as_bytes(),
        )
        .unwrap();

        assert!(package_replacement_token(&root).is_err());
        assert_eq!(begin_package_replacement(&root).unwrap(), token);
        assert!(component_replacement_active(&root).unwrap());
        finish_package_replacement(&root, &token).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn appimage_repair_lease_is_exclusive_and_reacquirable() {
        use std::os::unix::fs::PermissionsExt;

        let root = std::env::temp_dir().join(format!(
            "aiguard-appimage-lease-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let shared = root.join("native-host-v1");
        let component = shared.join("2.5.0");
        std::fs::create_dir_all(&shared).unwrap();
        std::fs::set_permissions(&shared, std::fs::Permissions::from_mode(0o700)).unwrap();
        let owner = AppImageComponentLease::acquire(&component).unwrap();
        assert!(AppImageComponentLease::acquire(&component).is_err());

        drop(owner);
        assert!(AppImageComponentLease::acquire(&component).is_ok());
        std::fs::remove_dir_all(root).unwrap();
    }
}
