//! Build-specific Chrome Native Messaging registration owned by the package.

use std::fmt;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::manifest::NativeHostPolicy;
use crate::native_messaging::NATIVE_HOST_NAME;

pub const NATIVE_HOST_MANIFEST_NAME: &str = "th.ac.psu.aiguard.native_host.json";

#[cfg(target_os = "linux")]
pub fn appimage_component_root() -> Result<PathBuf, RegistrationError> {
    let base = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .or_else(|| {
            std::env::var_os("HOME")
                .map(PathBuf::from)
                .filter(|path| path.is_absolute())
                .map(|path| path.join(".local").join("share"))
        })
        .ok_or_else(|| RegistrationError::new("registration_invalid"))?;
    Ok(base
        .join("aiguard")
        .join("native-host-v1")
        .join(crate::native_component_build_id()))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PackageShape {
    Nsis,
    Macos,
    Deb,
    AppImage,
}

impl PackageShape {
    pub fn parse(value: &str) -> Result<Self, RegistrationError> {
        match value {
            "nsis" => Ok(Self::Nsis),
            "macos" => Ok(Self::Macos),
            "deb" => Ok(Self::Deb),
            "appimage" => Ok(Self::AppImage),
            _ => Err(RegistrationError::new("registration_invalid")),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistrationPlatform {
    Windows,
    Macos,
    Linux,
}

#[derive(Clone, Eq, PartialEq)]
pub struct RegistrationError {
    code: &'static str,
}

impl RegistrationError {
    fn new(code: &'static str) -> Self {
        Self { code }
    }

    pub fn code(&self) -> &'static str {
        self.code
    }
}

impl fmt::Debug for RegistrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RegistrationError")
            .field("code", &self.code)
            .finish()
    }
}

impl fmt::Display for RegistrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code)
    }
}

impl std::error::Error for RegistrationError {}

#[derive(Serialize)]
struct NativeHostManifest<'a> {
    allowed_origins: [&'a str; 1],
    description: &'static str,
    name: &'a str,
    path: &'a str,
    #[serde(rename = "type")]
    host_type: &'static str,
}

pub fn manifest_bytes(
    adapter: &Path,
    policy: &NativeHostPolicy,
) -> Result<Vec<u8>, RegistrationError> {
    if policy.name() != NATIVE_HOST_NAME || !adapter.is_absolute() || adapter.as_os_str().is_empty()
    {
        return Err(RegistrationError::new("registration_invalid"));
    }
    let adapter = native_messaging_path_string(adapter)?;
    let manifest = NativeHostManifest {
        allowed_origins: [policy.allowed_origin()],
        description: "AI Guard Chrome Native Messaging adapter",
        name: policy.name(),
        path: &adapter,
        host_type: "stdio",
    };
    let mut bytes = serde_json::to_vec_pretty(&manifest)
        .map_err(|_| RegistrationError::new("registration_invalid"))?;
    bytes.push(b'\n');
    if bytes.len() > 16 * 1024 {
        return Err(RegistrationError::new("registration_invalid"));
    }
    Ok(bytes)
}

pub fn registration_paths_for_test(
    platform: RegistrationPlatform,
    shape: PackageShape,
    config_root: &Path,
    install_root: &Path,
) -> Result<Vec<PathBuf>, RegistrationError> {
    registration_paths(platform, shape, config_root, install_root)
}

fn registration_paths(
    platform: RegistrationPlatform,
    shape: PackageShape,
    config_root: &Path,
    install_root: &Path,
) -> Result<Vec<PathBuf>, RegistrationError> {
    let paths = match (platform, shape) {
        (RegistrationPlatform::Windows, PackageShape::Nsis) => {
            vec![install_root.join(NATIVE_HOST_MANIFEST_NAME)]
        }
        (RegistrationPlatform::Macos, PackageShape::Macos) => vec![
            config_root
                .join("Google")
                .join("Chrome")
                .join("NativeMessagingHosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
            config_root
                .join("Google")
                .join("ChromeForTesting")
                .join("NativeMessagingHosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
            config_root
                .join("Chromium")
                .join("NativeMessagingHosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
        ],
        (RegistrationPlatform::Linux, PackageShape::Deb) => vec![
            config_root
                .join("opt")
                .join("chrome")
                .join("native-messaging-hosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
            config_root
                .join("opt")
                .join("chrome_for_testing")
                .join("native-messaging-hosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
            config_root
                .join("chromium")
                .join("native-messaging-hosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
        ],
        (RegistrationPlatform::Linux, PackageShape::AppImage) => vec![
            config_root
                .join("google-chrome")
                .join("NativeMessagingHosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
            config_root
                .join("google-chrome-for-testing")
                .join("NativeMessagingHosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
            config_root
                .join("chromium")
                .join("NativeMessagingHosts")
                .join(NATIVE_HOST_MANIFEST_NAME),
        ],
        _ => return Err(RegistrationError::new("registration_invalid")),
    };
    if paths.iter().any(|path| !path.is_absolute()) {
        return Err(RegistrationError::new("registration_invalid"));
    }
    Ok(paths)
}

pub fn install_or_repair(
    shape: PackageShape,
    adapter: &Path,
    policy: &NativeHostPolicy,
) -> Result<(), RegistrationError> {
    let bytes = manifest_bytes(adapter, policy)?;
    let install_root = adapter
        .parent()
        .ok_or_else(|| RegistrationError::new("registration_invalid"))?;
    let (platform, config_root) = production_roots(shape, adapter)?;
    let paths = registration_paths(platform, shape, &config_root, install_root)?;
    for path in &paths {
        write_owned_file(path, &bytes)?;
    }
    #[cfg(windows)]
    if shape == PackageShape::Nsis {
        register_windows(&paths[0])?;
    }
    Ok(())
}

pub fn unregister(
    shape: PackageShape,
    adapter: &Path,
    policy: &NativeHostPolicy,
) -> Result<(), RegistrationError> {
    let bytes = manifest_bytes(adapter, policy)?;
    let install_root = adapter
        .parent()
        .ok_or_else(|| RegistrationError::new("registration_invalid"))?;
    let (platform, config_root) = production_roots(shape, adapter)?;
    let paths = registration_paths(platform, shape, &config_root, install_root)?;
    #[cfg(windows)]
    if shape == PackageShape::Nsis {
        unregister_windows(&paths[0])?;
    }
    for path in paths {
        remove_owned_file(&path, &bytes)?;
    }
    Ok(())
}

fn production_roots(
    shape: PackageShape,
    adapter: &Path,
) -> Result<(RegistrationPlatform, PathBuf), RegistrationError> {
    #[cfg(windows)]
    {
        if shape != PackageShape::Nsis {
            return Err(RegistrationError::new("registration_invalid"));
        }
        Ok((
            RegistrationPlatform::Windows,
            adapter.parent().unwrap().to_owned(),
        ))
    }
    #[cfg(target_os = "macos")]
    {
        if shape != PackageShape::Macos {
            return Err(RegistrationError::new("registration_invalid"));
        }
        let home = checked_environment_path("HOME")?;
        Ok((
            RegistrationPlatform::Macos,
            home.join("Library").join("Application Support"),
        ))
    }
    #[cfg(target_os = "linux")]
    {
        match shape {
            PackageShape::Deb => Ok((RegistrationPlatform::Linux, PathBuf::from("/etc"))),
            PackageShape::AppImage => {
                let adapter_text = adapter.to_string_lossy();
                if adapter_text.contains("/.mount_") || adapter_text.contains("/.mount-") {
                    return Err(RegistrationError::new("registration_invalid"));
                }
                let config = std::env::var_os("XDG_CONFIG_HOME")
                    .map(PathBuf::from)
                    .filter(|path| path.is_absolute())
                    .or_else(|| {
                        checked_environment_path("HOME")
                            .ok()
                            .map(|home| home.join(".config"))
                    })
                    .ok_or_else(|| RegistrationError::new("registration_invalid"))?;
                Ok((RegistrationPlatform::Linux, config))
            }
            _ => Err(RegistrationError::new("registration_invalid")),
        }
    }
    #[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
    {
        let _ = (shape, adapter);
        Err(RegistrationError::new("registration_invalid"))
    }
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
fn checked_environment_path(name: &str) -> Result<PathBuf, RegistrationError> {
    std::env::var_os(name)
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| RegistrationError::new("registration_invalid"))
}

fn write_owned_file(path: &Path, bytes: &[u8]) -> Result<(), RegistrationError> {
    let parent = path
        .parent()
        .ok_or_else(|| RegistrationError::new("registration_invalid"))?;
    std::fs::create_dir_all(parent).map_err(|_| RegistrationError::new("registration_failed"))?;
    if std::fs::symlink_metadata(path)
        .is_ok_and(|metadata| !metadata.file_type().is_file() || metadata.file_type().is_symlink())
    {
        return Err(RegistrationError::new("registration_failed"));
    }
    let mut random = [0_u8; 8];
    getrandom::fill(&mut random).map_err(|_| RegistrationError::new("registration_failed"))?;
    let suffix = random
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let temporary = parent.join(format!(".{NATIVE_HOST_MANIFEST_NAME}.{suffix}.tmp"));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|_| RegistrationError::new("registration_failed"))?;
        file.write_all(bytes)
            .and_then(|()| file.flush())
            .and_then(|()| file.sync_all())
            .map_err(|_| RegistrationError::new("registration_failed"))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            file.set_permissions(std::fs::Permissions::from_mode(0o644))
                .map_err(|_| RegistrationError::new("registration_failed"))?;
        }
        replace_file(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(not(windows))]
fn replace_file(temporary: &Path, destination: &Path) -> Result<(), RegistrationError> {
    std::fs::rename(temporary, destination)
        .map_err(|_| RegistrationError::new("registration_failed"))
}

#[cfg(windows)]
fn replace_file(temporary: &Path, destination: &Path) -> Result<(), RegistrationError> {
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source = wide_os(temporary.as_os_str())?;
    let destination = wide_os(destination.as_os_str())?;
    if unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        return Err(RegistrationError::new("registration_failed"));
    }
    Ok(())
}

fn remove_owned_file(path: &Path, expected: &[u8]) -> Result<(), RegistrationError> {
    let current = match std::fs::read(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(RegistrationError::new("registration_failed")),
    };
    if current != expected {
        return Err(RegistrationError::new("registration_failed"));
    }
    std::fs::remove_file(path).map_err(|_| RegistrationError::new("registration_failed"))
}

#[cfg(windows)]
fn register_windows(manifest: &Path) -> Result<(), RegistrationError> {
    use windows_sys::Win32::Foundation::ERROR_SUCCESS;
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegCreateKeyExW, RegSetValueExW, HKEY_CURRENT_USER, KEY_SET_VALUE,
        KEY_WOW64_32KEY, KEY_WOW64_64KEY, REG_OPTION_NON_VOLATILE, REG_SZ,
    };
    let value = wide_registry(&native_messaging_path_string(manifest)?)?;
    for product in ["Google\\Chrome", "Chromium"] {
        let subkey = wide_registry(&format!(
            "Software\\{product}\\NativeMessagingHosts\\{NATIVE_HOST_NAME}"
        ))?;
        for view in [KEY_WOW64_32KEY, KEY_WOW64_64KEY] {
            let mut key = std::ptr::null_mut();
            let status = unsafe {
                RegCreateKeyExW(
                    HKEY_CURRENT_USER,
                    subkey.as_ptr(),
                    0,
                    std::ptr::null_mut(),
                    REG_OPTION_NON_VOLATILE,
                    KEY_SET_VALUE | view,
                    std::ptr::null(),
                    &mut key,
                    std::ptr::null_mut(),
                )
            };
            if status != ERROR_SUCCESS || key.is_null() {
                return Err(RegistrationError::new("registration_failed"));
            }
            let written = unsafe {
                RegSetValueExW(
                    key,
                    std::ptr::null(),
                    0,
                    REG_SZ,
                    value.as_ptr().cast(),
                    (value.len() * 2) as u32,
                )
            };
            unsafe { RegCloseKey(key) };
            if written != ERROR_SUCCESS {
                return Err(RegistrationError::new("registration_failed"));
            }
        }
    }
    Ok(())
}

#[cfg(windows)]
fn unregister_windows(manifest: &Path) -> Result<(), RegistrationError> {
    use windows_sys::Win32::Foundation::{ERROR_FILE_NOT_FOUND, ERROR_SUCCESS};
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegDeleteKeyExW, RegOpenKeyExW, RegQueryValueExW, HKEY_CURRENT_USER,
        KEY_QUERY_VALUE, KEY_WOW64_32KEY, KEY_WOW64_64KEY, REG_SZ,
    };
    let expected = wide_registry(&native_messaging_path_string(manifest)?)?;
    for product in ["Google\\Chrome", "Chromium"] {
        let subkey = wide_registry(&format!(
            "Software\\{product}\\NativeMessagingHosts\\{NATIVE_HOST_NAME}"
        ))?;
        for view in [KEY_WOW64_32KEY, KEY_WOW64_64KEY] {
            let mut key = std::ptr::null_mut();
            let opened = unsafe {
                RegOpenKeyExW(
                    HKEY_CURRENT_USER,
                    subkey.as_ptr(),
                    0,
                    KEY_QUERY_VALUE | view,
                    &mut key,
                )
            };
            if opened == ERROR_FILE_NOT_FOUND {
                continue;
            }
            if opened != ERROR_SUCCESS || key.is_null() {
                return Err(RegistrationError::new("registration_failed"));
            }
            let mut value_type = 0_u32;
            let mut byte_count = 0_u32;
            let sized = unsafe {
                RegQueryValueExW(
                    key,
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    &mut value_type,
                    std::ptr::null_mut(),
                    &mut byte_count,
                )
            };
            if sized != ERROR_SUCCESS
                || value_type != REG_SZ
                || byte_count == 0
                || byte_count > 64 * 1024
            {
                unsafe { RegCloseKey(key) };
                return Err(RegistrationError::new("registration_failed"));
            }
            let mut value = vec![0_u16; (byte_count as usize).div_ceil(2)];
            let read = unsafe {
                RegQueryValueExW(
                    key,
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    &mut value_type,
                    value.as_mut_ptr().cast(),
                    &mut byte_count,
                )
            };
            unsafe { RegCloseKey(key) };
            if read != ERROR_SUCCESS || value != expected {
                return Err(RegistrationError::new("registration_failed"));
            }
            let deleted = unsafe { RegDeleteKeyExW(HKEY_CURRENT_USER, subkey.as_ptr(), view, 0) };
            if deleted != ERROR_SUCCESS {
                return Err(RegistrationError::new("registration_failed"));
            }
        }
    }
    Ok(())
}

#[cfg(windows)]
fn wide_registry(value: &str) -> Result<Vec<u16>, RegistrationError> {
    wide_os(std::ffi::OsStr::new(value))
}

fn native_messaging_path_string(path: &Path) -> Result<String, RegistrationError> {
    let value = path
        .to_str()
        .ok_or_else(|| RegistrationError::new("registration_invalid"))?;
    #[cfg(windows)]
    {
        if let Some(suffix) = value.strip_prefix(r"\\?\UNC\") {
            return Ok(format!(r"\\{suffix}"));
        }
        if let Some(suffix) = value.strip_prefix(r"\\?\") {
            return Ok(suffix.to_owned());
        }
    }
    Ok(value.to_owned())
}

#[cfg(windows)]
fn wide_os(value: &std::ffi::OsStr) -> Result<Vec<u16>, RegistrationError> {
    use std::os::windows::ffi::OsStrExt;
    let mut wide = value.encode_wide().collect::<Vec<_>>();
    if wide.is_empty() || wide.contains(&0) {
        return Err(RegistrationError::new("registration_invalid"));
    }
    wide.push(0);
    Ok(wide)
}
