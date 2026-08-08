//! Strict package-consistency evidence for native components.
//!
//! These checks detect a mismatched installed component. They are deliberately
//! not publisher attestation and do not defend against same-user replacement
//! of an unsigned installation.

use std::collections::BTreeSet;
use std::fmt;
use std::fs::File;
use std::io::{Read, Take};
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

pub struct ComponentManifest {
    root: PathBuf,
    product_version: String,
    broker: RawComponent,
    clients: Vec<RawClient>,
    backend: RawBackend,
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
        if !valid_version(expected_product_version) || path.as_os_str().is_empty() {
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
        };
        manifest.validate(expected_product_version)?;
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
        for client in &self.clients {
            let expected = self.resolve_component_path(&client.path, "broker_unauthorized")?;
            if expected != observed {
                continue;
            }
            verify_component_bytes(
                &expected,
                &client.sha256,
                Some(&client.build_id),
                "broker_unauthorized",
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
        )?;
        Ok(VerifiedBackend {
            component_id: self.backend.component_id.clone(),
            executable,
            arguments: self.backend.arguments.clone(),
            build_id: self.backend.build_id.clone(),
        })
    }

    fn validate(&self, expected_product_version: &str) -> Result<(), ProtocolError> {
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
        let mut resolved_paths = BTreeSet::new();
        for path in paths {
            let resolved = self.resolve_component_path(path, "broker_unavailable")?;
            if !resolved_paths.insert(resolved) {
                return unavailable();
            }
        }
        Ok(())
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
) -> Result<(), ProtocolError> {
    let file = File::open(path).map_err(|_| ProtocolError::new(error_code, None))?;
    let metadata = file
        .metadata()
        .map_err(|_| ProtocolError::new(error_code, None))?;
    if !metadata.file_type().is_file()
        || metadata.len() == 0
        || metadata.len() > COMPONENT_MAX_BYTES
    {
        return Err(ProtocolError::new(error_code, None));
    }
    let marker = expected_build_id.map(|build_id| {
        let mut value = Vec::with_capacity(BUILD_MARKER_PREFIX.len() + build_id.len() + 1);
        value.extend_from_slice(BUILD_MARKER_PREFIX);
        value.extend_from_slice(build_id.as_bytes());
        value.push(0);
        value
    });
    let (digest, marker_found) =
        digest_and_find(file.take(COMPONENT_MAX_BYTES + 1), marker.as_deref())
            .map_err(|_| ProtocolError::new(error_code, None))?;
    if digest != expected_digest || marker.is_some() && !marker_found {
        return Err(ProtocolError::new(error_code, None));
    }
    Ok(())
}

fn digest_and_find(
    mut reader: Take<File>,
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
