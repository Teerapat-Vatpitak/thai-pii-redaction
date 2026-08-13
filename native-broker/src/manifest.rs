//! Strict package-consistency evidence for native components.
//!
//! These checks detect a mismatched installed component. They are deliberately
//! not publisher attestation and do not defend against same-user replacement
//! of an unsigned installation.

use std::collections::BTreeSet;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::admission::PackageConsistencyEvidence;
use crate::ProtocolError;

const MANIFEST_MAX_BYTES: u64 = 64 * 1024;
const COMPONENT_MAX_BYTES: u64 = 512 * 1024 * 1024;
const BUILD_MARKER_PREFIX: &[u8] = b"AIGUARD_NATIVE_COMPONENT_BUILD_ID=";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawManifest {
    schema_version: u64,
    product_version: String,
    broker: RawComponent,
    clients: Vec<RawClient>,
    backend: RawBackend,
    #[serde(default)]
    native_host: Option<RawNativeHost>,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawComponent {
    component_id: String,
    path: String,
    sha256: String,
    build_id: String,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawClient {
    component_id: String,
    role: String,
    path: String,
    sha256: String,
    build_id: String,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawBackend {
    component_id: String,
    path: String,
    sha256: String,
    build_id: String,
    arguments: Vec<String>,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawNativeHost {
    name: String,
    allowed_origin: String,
    identity_classification: String,
}

#[derive(Clone, Eq, PartialEq)]
pub struct NativeHostPolicy {
    name: String,
    allowed_origin: String,
    identity_classification: String,
}

impl NativeHostPolicy {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn allowed_origin(&self) -> &str {
        &self.allowed_origin
    }

    pub fn identity_classification(&self) -> &str {
        &self.identity_classification
    }

    #[doc(hidden)]
    pub fn for_test(name: &str, allowed_origin: &str, identity_classification: &str) -> Self {
        Self {
            name: name.to_owned(),
            allowed_origin: allowed_origin.to_owned(),
            identity_classification: identity_classification.to_owned(),
        }
    }
}

impl fmt::Debug for NativeHostPolicy {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NativeHostPolicy")
            .field("identity_classification", &self.identity_classification)
            .finish_non_exhaustive()
    }
}

pub struct ComponentManifest {
    root: PathBuf,
    product_version: String,
    broker: RawComponent,
    clients: Vec<RawClient>,
    backend: RawBackend,
    native_host: Option<RawNativeHost>,
    file_policy: PackageFilePolicy,
    allow_incomplete_removal: bool,
}

#[derive(Clone, Copy)]
struct PackageFilePolicy {
    strict_installed_set: bool,
    #[cfg(unix)]
    owner: u32,
}

impl PackageFilePolicy {
    fn for_manifest(path: &Path, strict_installed_set: bool) -> Result<Self, ProtocolError> {
        #[cfg(unix)]
        let owner = {
            use std::os::unix::fs::MetadataExt;

            let metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable_error())?;
            let owner = metadata.uid();
            if strict_installed_set && owner != 0 && owner != unsafe { libc::geteuid() } {
                return Err(unavailable_error());
            }
            owner
        };
        let policy = Self {
            strict_installed_set,
            #[cfg(unix)]
            owner,
        };
        verify_file_security(path, false, policy)?;
        Ok(policy)
    }
}

impl fmt::Debug for ComponentManifest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ComponentManifest")
            .field("product_version", &self.product_version)
            .field("client_count", &self.clients.len())
            .finish_non_exhaustive()
    }
}

pub struct VerifiedBackend {
    component_id: String,
    executable: PathBuf,
    arguments: Vec<String>,
    build_id: String,
}

impl VerifiedBackend {
    pub fn component_id(&self) -> &str {
        &self.component_id
    }

    pub fn executable(&self) -> &Path {
        &self.executable
    }

    pub fn arguments(&self) -> &[String] {
        &self.arguments
    }

    pub fn build_id(&self) -> &str {
        &self.build_id
    }
}

impl fmt::Debug for VerifiedBackend {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedBackend")
            .field("component_id", &self.component_id)
            .finish_non_exhaustive()
    }
}

impl ComponentManifest {
    pub fn load(path: &Path, expected_product_version: &str) -> Result<Self, ProtocolError> {
        Self::load_inner(path, Some(expected_product_version), true)
    }

    #[doc(hidden)]
    pub fn load_declared(path: &Path) -> Result<Self, ProtocolError> {
        Self::load_inner(path, None, true)
    }

    #[doc(hidden)]
    pub fn load_incomplete_for_removal(
        path: &Path,
        expected_product_version: &str,
    ) -> Result<Self, ProtocolError> {
        Self::load_inner(path, Some(expected_product_version), false)
    }

    #[doc(hidden)]
    pub fn valid_declared_product_version(value: &str) -> bool {
        valid_version(value)
    }

    fn load_inner(
        path: &Path,
        expected_product_version: Option<&str>,
        verify_complete_set: bool,
    ) -> Result<Self, ProtocolError> {
        if expected_product_version.is_some_and(|value| !valid_version(value))
            || path.as_os_str().is_empty()
        {
            return unavailable();
        }
        let metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable_error())?;
        if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
            return unavailable();
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.mode() & 0o022 != 0 {
                return unavailable();
            }
        }
        if metadata.len() == 0 || metadata.len() > MANIFEST_MAX_BYTES {
            return unavailable();
        }
        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        File::open(path)
            .map_err(|_| unavailable_error())?
            .take(MANIFEST_MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| unavailable_error())?;
        if bytes.len() as u64 != metadata.len() {
            return unavailable();
        }
        let raw: RawManifest = serde_json::from_slice(&bytes).map_err(|_| unavailable_error())?;
        if raw.schema_version != 1 {
            return unavailable();
        }
        let validation_version = expected_product_version
            .map(str::to_owned)
            .unwrap_or_else(|| raw.product_version.clone());
        if !valid_version(&validation_version) {
            return unavailable();
        }
        let file_policy = PackageFilePolicy::for_manifest(path, raw.native_host.is_some())?;
        let root = path
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
            .ok_or_else(unavailable_error)?
            .canonicalize()
            .map_err(|_| unavailable_error())?;
        let manifest = Self {
            root,
            product_version: raw.product_version,
            broker: raw.broker,
            clients: raw.clients,
            backend: raw.backend,
            native_host: raw.native_host,
            file_policy,
            allow_incomplete_removal: !verify_complete_set,
        };
        manifest.validate(&validation_version, verify_complete_set)?;
        Ok(manifest)
    }

    pub fn product_version(&self) -> &str {
        &self.product_version
    }

    pub fn verify_client_executable(
        &self,
        observed_path: &Path,
    ) -> Result<PackageConsistencyEvidence, ProtocolError> {
        let observed = observed_path
            .canonicalize()
            .map_err(|_| unauthorized_error())?;
        let allow_missing_siblings = self.allow_incomplete_removal;
        for client in &self.clients {
            if allow_missing_siblings && Path::new(&client.path).file_name() != observed.file_name()
            {
                continue;
            }
            let expected = match self.resolve_component_path(&client.path, "broker_unauthorized") {
                Ok(path) => path,
                Err(_) if allow_missing_siblings => continue,
                Err(error) => return Err(error),
            };
            if expected != observed {
                continue;
            }
            verify_component_bytes(
                &expected,
                &client.sha256,
                Some(&client.build_id),
                "broker_unauthorized",
                self.file_policy,
                true,
            )?;
            return Ok(PackageConsistencyEvidence {
                component_id: client.component_id.clone(),
                allowed_role: client.role.clone(),
                canonical_path_matches: true,
                build_id_matches: true,
                digest_matches: true,
            });
        }
        Err(unauthorized_error())
    }

    pub fn verified_client_executable_for_role(
        &self,
        role: &str,
    ) -> Result<PathBuf, ProtocolError> {
        let client = self
            .clients
            .iter()
            .find(|client| client.role == role)
            .ok_or_else(unauthorized_error)?;
        let expected = self.resolve_component_path(&client.path, "broker_unauthorized")?;
        verify_component_bytes(
            &expected,
            &client.sha256,
            Some(&client.build_id),
            "broker_unauthorized",
            self.file_policy,
            true,
        )?;
        Ok(expected)
    }

    pub fn native_host_policy(&self) -> Result<NativeHostPolicy, ProtocolError> {
        let policy = self.native_host.as_ref().ok_or_else(unavailable_error)?;
        validate_native_host(policy)?;
        Ok(NativeHostPolicy {
            name: policy.name.clone(),
            allowed_origin: policy.allowed_origin.clone(),
            identity_classification: policy.identity_classification.clone(),
        })
    }

    #[doc(hidden)]
    pub fn declared_component_paths_for_removal(&self) -> Vec<PathBuf> {
        let mut paths = Vec::with_capacity(self.clients.len() + 2);
        paths.push(self.root.join(&self.broker.path));
        paths.extend(
            self.clients
                .iter()
                .map(|client| self.root.join(&client.path)),
        );
        paths.push(self.root.join(&self.backend.path));
        paths
    }

    #[doc(hidden)]
    pub fn verify_present_component_for_removal(&self, path: &Path) -> Result<bool, ProtocolError> {
        match std::fs::symlink_metadata(path) {
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(_) => return unavailable(),
        }
        if path == self.root.join(&self.broker.path) {
            verify_component_bytes(
                path,
                &self.broker.sha256,
                Some(&self.broker.build_id),
                "broker_unavailable",
                self.file_policy,
                true,
            )?;
            return Ok(true);
        }
        if let Some(client) = self
            .clients
            .iter()
            .find(|client| path == self.root.join(&client.path))
        {
            verify_component_bytes(
                path,
                &client.sha256,
                Some(&client.build_id),
                "broker_unavailable",
                self.file_policy,
                true,
            )?;
            return Ok(true);
        }
        if path == self.root.join(&self.backend.path) {
            verify_component_bytes(
                path,
                &self.backend.sha256,
                None,
                "broker_unavailable",
                self.file_policy,
                true,
            )?;
            return Ok(true);
        }
        unavailable()
    }

    pub fn verify_broker_executable(&self, observed_path: &Path) -> Result<(), ProtocolError> {
        let expected = self.verified_broker_executable()?;
        let observed = observed_path
            .canonicalize()
            .map_err(|_| unauthorized_error())?;
        if observed != expected {
            return Err(unauthorized_error());
        }
        Ok(())
    }

    pub fn verified_broker_executable(&self) -> Result<PathBuf, ProtocolError> {
        let expected = self.resolve_component_path(&self.broker.path, "broker_unauthorized")?;
        verify_component_bytes(
            &expected,
            &self.broker.sha256,
            Some(&self.broker.build_id),
            "broker_unauthorized",
            self.file_policy,
            true,
        )?;
        Ok(expected)
    }

    pub fn verify_backend(&self) -> Result<VerifiedBackend, ProtocolError> {
        let executable = self.resolve_component_path(&self.backend.path, "broker_unavailable")?;
        verify_component_bytes(
            &executable,
            &self.backend.sha256,
            None,
            "broker_unavailable",
            self.file_policy,
            true,
        )?;
        Ok(VerifiedBackend {
            component_id: self.backend.component_id.clone(),
            executable,
            arguments: self.backend.arguments.clone(),
            build_id: self.backend.build_id.clone(),
        })
    }

    fn validate(
        &self,
        expected_product_version: &str,
        verify_complete_set: bool,
    ) -> Result<(), ProtocolError> {
        if self.product_version != expected_product_version
            || !valid_version(&self.product_version)
            || self.clients.is_empty()
            || self.clients.len() > 8
        {
            return unavailable();
        }
        validate_component(&self.broker, &self.product_version)?;
        validate_backend(&self.backend, &self.product_version)?;
        let mut ids = BTreeSet::from([
            self.broker.component_id.as_str(),
            self.backend.component_id.as_str(),
        ]);
        let mut paths = BTreeSet::from([self.broker.path.as_str(), self.backend.path.as_str()]);
        if ids.len() != 2 || paths.len() != 2 {
            return unavailable();
        }
        let mut roles = BTreeSet::new();
        for client in &self.clients {
            validate_client(client, &self.product_version)?;
            if !ids.insert(&client.component_id)
                || !paths.insert(&client.path)
                || !roles.insert(&client.role)
            {
                return unavailable();
            }
        }
        if let Some(native_host) = &self.native_host {
            validate_native_host(native_host)?;
            let exact_clients = BTreeSet::from([
                ("desktop", "desktop"),
                ("extension", "chrome-native-host"),
                ("maintenance", "native-host-manager"),
            ]);
            let actual_clients = self
                .clients
                .iter()
                .map(|client| (client.role.as_str(), client.component_id.as_str()))
                .collect::<BTreeSet<_>>();
            if self.broker.component_id != "native-broker"
                || self.backend.component_id != "python-backend"
                || actual_clients != exact_clients
                || !self.has_exact_installed_paths()
            {
                return unavailable();
            }
        }
        if verify_complete_set {
            let mut resolved_paths = BTreeSet::new();
            for path in paths {
                let resolved = self.resolve_component_path(path, "broker_unavailable")?;
                if !resolved_paths.insert(resolved) {
                    return unavailable();
                }
            }
            if self.native_host.is_some() {
                self.verify_complete_installed_set()?;
            }
        }
        Ok(())
    }

    fn has_exact_installed_paths(&self) -> bool {
        #[cfg(windows)]
        let expected = [
            ("broker", "aiguard-native-broker.exe"),
            ("backend", "aiguard.exe"),
            ("desktop", "desktop.exe"),
            ("extension", "aiguard-chrome-native-host.exe"),
            ("maintenance", "aiguard-native-host-manager.exe"),
        ];
        #[cfg(not(windows))]
        let expected = [
            ("broker", "aiguard-native-broker"),
            ("backend", "aiguard"),
            ("desktop", "desktop"),
            ("extension", "aiguard-chrome-native-host"),
            ("maintenance", "aiguard-native-host-manager"),
        ];
        self.broker.path == expected[0].1
            && self.backend.path == expected[1].1
            && expected[2..].iter().all(|(role, path)| {
                self.clients
                    .iter()
                    .any(|client| client.role == *role && client.path == *path)
            })
    }

    fn verify_complete_installed_set(&self) -> Result<(), ProtocolError> {
        let broker = self.resolve_component_path(&self.broker.path, "broker_unavailable")?;
        verify_component_bytes(
            &broker,
            &self.broker.sha256,
            Some(&self.broker.build_id),
            "broker_unavailable",
            self.file_policy,
            true,
        )?;
        for client in &self.clients {
            let path = self.resolve_component_path(&client.path, "broker_unavailable")?;
            verify_component_bytes(
                &path,
                &client.sha256,
                Some(&client.build_id),
                "broker_unavailable",
                self.file_policy,
                true,
            )?;
        }
        let backend = self.resolve_component_path(&self.backend.path, "broker_unavailable")?;
        verify_component_bytes(
            &backend,
            &self.backend.sha256,
            None,
            "broker_unavailable",
            self.file_policy,
            true,
        )
    }

    fn resolve_component_path(
        &self,
        relative: &str,
        error_code: &str,
    ) -> Result<PathBuf, ProtocolError> {
        let relative_path = Path::new(relative);
        if relative_path.as_os_str().is_empty()
            || relative_path.is_absolute()
            || relative_path
                .components()
                .any(|component| !matches!(component, Component::Normal(_)))
        {
            return Err(ProtocolError::new(error_code, None));
        }
        let mut candidate = self.root.clone();
        let mut components = relative_path.components().peekable();
        while let Some(Component::Normal(component)) = components.next() {
            candidate.push(component);
            let metadata = std::fs::symlink_metadata(&candidate)
                .map_err(|_| ProtocolError::new(error_code, None))?;
            if metadata.file_type().is_symlink()
                || (components.peek().is_some() && !metadata.file_type().is_dir())
                || (components.peek().is_none() && !metadata.file_type().is_file())
            {
                return Err(ProtocolError::new(error_code, None));
            }
        }
        let canonical = candidate
            .canonicalize()
            .map_err(|_| ProtocolError::new(error_code, None))?;
        if canonical.parent().is_none()
            || !canonical.starts_with(&self.root)
            || canonical != candidate
        {
            return Err(ProtocolError::new(error_code, None));
        }
        Ok(canonical)
    }
}

fn validate_native_host(native_host: &RawNativeHost) -> Result<(), ProtocolError> {
    let name = native_host.name.as_bytes();
    let valid_name = (1..=64).contains(&name.len())
        && name[0] != b'.'
        && name[name.len() - 1] != b'.'
        && !native_host.name.contains("..")
        && name.iter().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'.' | b'_')
        });
    let origin = native_host.allowed_origin.as_bytes();
    let prefix = b"chrome-extension://";
    let valid_origin = origin.len() == prefix.len() + 32 + 1
        && origin.starts_with(prefix)
        && origin.ends_with(b"/")
        && origin[prefix.len()..prefix.len() + 32]
            .iter()
            .all(|byte| (b'a'..=b'p').contains(byte));
    if !valid_name
        || !valid_origin
        || !matches!(
            native_host.identity_classification.as_str(),
            "production_owner_approved" | "synthetic_test_only"
        )
    {
        return unavailable();
    }
    Ok(())
}

fn validate_component(
    component: &RawComponent,
    product_version: &str,
) -> Result<(), ProtocolError> {
    if !valid_component_id(&component.component_id)
        || !valid_relative_path(&component.path)
        || !valid_digest(&component.sha256)
        || component.build_id != product_version
    {
        return unavailable();
    }
    Ok(())
}

fn validate_client(client: &RawClient, product_version: &str) -> Result<(), ProtocolError> {
    if !valid_component_id(&client.component_id)
        || !matches!(
            client.role.as_str(),
            "desktop" | "extension" | "maintenance"
        )
        || !valid_relative_path(&client.path)
        || !valid_digest(&client.sha256)
        || client.build_id != product_version
    {
        return unavailable();
    }
    Ok(())
}

fn validate_backend(backend: &RawBackend, product_version: &str) -> Result<(), ProtocolError> {
    if !valid_component_id(&backend.component_id)
        || !valid_relative_path(&backend.path)
        || !valid_digest(&backend.sha256)
        || backend.build_id != product_version
        || backend.arguments.as_slice() != ["--native-broker-backend"]
    {
        return unavailable();
    }
    Ok(())
}

fn valid_component_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-')
}

fn valid_relative_path(value: &str) -> bool {
    let path = Path::new(value);
    !path.as_os_str().is_empty()
        && !path.is_absolute()
        && path
            .components()
            .all(|component| matches!(component, Component::Normal(_)))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_version(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes[1..]
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'+' | b'-'))
}

fn verify_component_bytes(
    path: &Path,
    expected_digest: &str,
    expected_build_id: Option<&str>,
    error_code: &str,
    file_policy: PackageFilePolicy,
    executable: bool,
) -> Result<(), ProtocolError> {
    let mut file = File::open(path).map_err(|_| ProtocolError::new(error_code, None))?;
    let before = file
        .metadata()
        .map_err(|_| ProtocolError::new(error_code, None))?;
    if !before.file_type().is_file() || before.len() == 0 || before.len() > COMPONENT_MAX_BYTES {
        return Err(ProtocolError::new(error_code, None));
    }
    verify_file_security(path, executable, file_policy)
        .map_err(|_| ProtocolError::new(error_code, None))?;
    let marker = expected_build_id.map(|build_id| {
        let mut value = Vec::with_capacity(BUILD_MARKER_PREFIX.len() + build_id.len() + 1);
        value.extend_from_slice(BUILD_MARKER_PREFIX);
        value.extend_from_slice(build_id.as_bytes());
        value.push(0);
        value
    });
    let (digest, marker_found) =
        digest_and_find((&mut file).take(COMPONENT_MAX_BYTES + 1), marker.as_deref())
            .map_err(|_| ProtocolError::new(error_code, None))?;
    let after = std::fs::metadata(path).map_err(|_| ProtocolError::new(error_code, None))?;
    if !same_file_identity(&file, &before, path, &after)
        || digest != expected_digest
        || marker.is_some() && !marker_found
    {
        return Err(ProtocolError::new(error_code, None));
    }
    Ok(())
}

fn verify_file_security(
    path: &Path,
    executable: bool,
    policy: PackageFilePolicy,
) -> Result<(), ProtocolError> {
    let metadata = std::fs::symlink_metadata(path).map_err(|_| unavailable_error())?;
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return Err(unavailable_error());
    }
    if !policy.strict_installed_set {
        return Ok(());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;

        let mode = metadata.mode() & 0o7777;
        if metadata.uid() != policy.owner
            || metadata.nlink() != 1
            || mode != if executable { 0o755 } else { 0o644 }
        {
            return Err(unavailable_error());
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;

        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
            || windows_file_identity_for_path(path).is_none_or(|identity| identity.links != 1)
            || !windows_owner_is_current_user(path)
        {
            return Err(unavailable_error());
        }
        let _ = executable;
    }
    Ok(())
}

#[cfg(unix)]
fn same_file_identity(
    _file: &File,
    before: &std::fs::Metadata,
    _path: &Path,
    after: &std::fs::Metadata,
) -> bool {
    use std::os::unix::fs::MetadataExt;

    before.dev() == after.dev()
        && before.ino() == after.ino()
        && before.len() == after.len()
        && before.nlink() == after.nlink()
}

#[cfg(windows)]
fn same_file_identity(
    file: &File,
    _before: &std::fs::Metadata,
    path: &Path,
    _after: &std::fs::Metadata,
) -> bool {
    windows_file_identity(file)
        .zip(windows_file_identity_for_path(path))
        .is_some_and(|(before, after)| before == after)
}

#[cfg(not(any(unix, windows)))]
fn same_file_identity(
    _file: &File,
    before: &std::fs::Metadata,
    _path: &Path,
    after: &std::fs::Metadata,
) -> bool {
    before.len() == after.len()
}

#[cfg(windows)]
#[derive(Clone, Copy, Eq, PartialEq)]
struct WindowsFileIdentity {
    volume: u32,
    index: u64,
    links: u32,
    size: u64,
}

#[cfg(windows)]
fn windows_file_identity_for_path(path: &Path) -> Option<WindowsFileIdentity> {
    windows_file_identity(&File::open(path).ok()?)
}

#[cfg(windows)]
pub(crate) fn windows_file_has_one_link(path: &Path) -> bool {
    windows_file_identity_for_path(path).is_some_and(|identity| identity.links == 1)
}

#[cfg(windows)]
fn windows_file_identity(file: &File) -> Option<WindowsFileIdentity> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        GetFileInformationByHandle, BY_HANDLE_FILE_INFORMATION,
    };

    let mut information = BY_HANDLE_FILE_INFORMATION::default();
    if unsafe { GetFileInformationByHandle(file.as_raw_handle().cast(), &mut information) } == 0 {
        return None;
    }
    Some(WindowsFileIdentity {
        volume: information.dwVolumeSerialNumber,
        index: (u64::from(information.nFileIndexHigh) << 32) | u64::from(information.nFileIndexLow),
        links: information.nNumberOfLinks,
        size: (u64::from(information.nFileSizeHigh) << 32) | u64::from(information.nFileSizeLow),
    })
}

#[cfg(windows)]
pub(crate) fn windows_owner_is_current_user(path: &Path) -> bool {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::{CloseHandle, LocalFree, ERROR_SUCCESS};
    use windows_sys::Win32::Security::Authorization::{GetNamedSecurityInfoW, SE_FILE_OBJECT};
    use windows_sys::Win32::Security::{
        EqualSid, GetTokenInformation, TokenUser, OWNER_SECURITY_INFORMATION, TOKEN_QUERY,
        TOKEN_USER,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    let mut path = path.as_os_str().encode_wide().collect::<Vec<_>>();
    if path.is_empty() || path.contains(&0) {
        return false;
    }
    path.push(0);
    let mut owner = std::ptr::null_mut();
    let mut descriptor = std::ptr::null_mut();
    let status = unsafe {
        GetNamedSecurityInfoW(
            path.as_ptr(),
            SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION,
            &mut owner,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    if status != ERROR_SUCCESS || owner.is_null() || descriptor.is_null() {
        if !descriptor.is_null() {
            unsafe { LocalFree(descriptor) };
        }
        return false;
    }
    let mut token = std::ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        unsafe { LocalFree(descriptor) };
        return false;
    }
    let mut required = 0_u32;
    unsafe { GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut required) };
    let mut buffer = vec![0_u8; required as usize];
    let loaded = required >= std::mem::size_of::<TOKEN_USER>() as u32
        && unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                buffer.as_mut_ptr().cast(),
                required,
                &mut required,
            )
        } != 0;
    let matches = if loaded {
        let user = unsafe { std::ptr::read_unaligned(buffer.as_ptr().cast::<TOKEN_USER>()) };
        unsafe { EqualSid(owner, user.User.Sid) != 0 }
    } else {
        false
    };
    unsafe {
        CloseHandle(token);
        LocalFree(descriptor);
    }
    matches
}

#[cfg(windows)]
pub(crate) fn windows_set_owner_to_current_user(path: &Path) -> bool {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_SUCCESS};
    use windows_sys::Win32::Security::Authorization::{SetNamedSecurityInfoW, SE_FILE_OBJECT};
    use windows_sys::Win32::Security::{
        GetTokenInformation, TokenUser, OWNER_SECURITY_INFORMATION, TOKEN_QUERY, TOKEN_USER,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

    let mut path = path.as_os_str().encode_wide().collect::<Vec<_>>();
    if path.is_empty() || path.contains(&0) {
        return false;
    }
    path.push(0);
    let mut token = std::ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return false;
    }
    let mut required = 0_u32;
    unsafe { GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut required) };
    let mut buffer = vec![0_u8; required as usize];
    let loaded = required >= std::mem::size_of::<TOKEN_USER>() as u32
        && unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                buffer.as_mut_ptr().cast(),
                required,
                &mut required,
            )
        } != 0;
    let status = if loaded {
        let user = unsafe { std::ptr::read_unaligned(buffer.as_ptr().cast::<TOKEN_USER>()) };
        unsafe {
            SetNamedSecurityInfoW(
                path.as_mut_ptr(),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION,
                user.User.Sid,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        }
    } else {
        u32::MAX
    };
    unsafe { CloseHandle(token) };
    status == ERROR_SUCCESS
}

#[cfg(windows)]
#[doc(hidden)]
pub fn windows_set_owner_to_current_user_for_test(path: &Path) -> bool {
    windows_set_owner_to_current_user(path)
}

fn digest_and_find(
    mut reader: impl Read,
    marker: Option<&[u8]>,
) -> std::io::Result<(String, bool)> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut carry = Vec::new();
    let mut marker_found = marker.is_none();
    let mut total = 0_u64;
    loop {
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total += read as u64;
        if total > COMPONENT_MAX_BYTES {
            return Err(std::io::Error::other("component_too_large"));
        }
        hasher.update(&buffer[..read]);
        if let Some(needle) = marker.filter(|_| !marker_found) {
            carry.extend_from_slice(&buffer[..read]);
            marker_found = carry.windows(needle.len()).any(|window| window == needle);
            if !marker_found && carry.len() >= needle.len() {
                let retain = needle.len().saturating_sub(1);
                carry.drain(..carry.len() - retain);
            }
        }
    }
    Ok((format!("{:x}", hasher.finalize()), marker_found))
}

fn unavailable<T>() -> Result<T, ProtocolError> {
    Err(unavailable_error())
}

fn unavailable_error() -> ProtocolError {
    ProtocolError::new("broker_unavailable", None)
}

fn unauthorized_error() -> ProtocolError {
    ProtocolError::new("broker_unauthorized", None)
}
