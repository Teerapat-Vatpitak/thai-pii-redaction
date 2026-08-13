#[cfg(target_os = "linux")]
use std::collections::BTreeSet;
#[cfg(unix)]
use std::fs::{File, OpenOptions};
#[cfg(unix)]
use std::os::fd::AsRawFd;
#[cfg(unix)]
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;
#[cfg(any(target_os = "linux", windows))]
use std::path::PathBuf;
use std::process::ExitCode;
#[cfg(target_os = "linux")]
use std::process::{Command, Stdio};
use std::time::Duration;
#[cfg(target_os = "linux")]
use std::time::Instant;

use aiguard_native_broker_protocol::manifest::ComponentManifest;
#[cfg(target_os = "linux")]
use aiguard_native_broker_protocol::native_host_registration::{
    appimage_component_root, isolate_appimage_registration_for_replacement,
    PreviousAppImageRegistration,
};
use aiguard_native_broker_protocol::native_host_registration::{
    install_or_repair, unregister, PackageShape,
};

fn action_matches_replacement_state(
    operation: &str,
    replacement_active: bool,
    abandoned_appimage: bool,
) -> bool {
    match operation {
        "install" => !replacement_active,
        "repair" | "uninstall" => !replacement_active || abandoned_appimage,
        _ => false,
    }
}

fn operation_supports_shape(operation: &str, shape: PackageShape) -> bool {
    match operation {
        "drain" => matches!(
            shape,
            PackageShape::Nsis | PackageShape::Deb | PackageShape::AppImage
        ),
        "resume-package" => shape == PackageShape::Nsis,
        _ => true,
    }
}

#[cfg(windows)]
fn windows_package_lock_path() -> Result<PathBuf, ()> {
    let local_app_data = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or(())?;
    Ok(local_app_data.join("AI Guard.aiguard-package-lifecycle-v1.lock"))
}

struct OrdinaryActionLock {
    #[cfg(windows)]
    handle: windows_sys::Win32::Foundation::HANDLE,
    #[cfg(unix)]
    _directory: File,
}

impl OrdinaryActionLock {
    fn acquire(install_root: &Path) -> Result<Self, ()> {
        #[cfg(windows)]
        {
            use std::os::windows::ffi::OsStrExt;
            use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
            use windows_sys::Win32::Storage::FileSystem::{
                CreateFileW, DELETE, FILE_ATTRIBUTE_HIDDEN, FILE_FLAG_DELETE_ON_CLOSE,
                FILE_FLAG_OPEN_REPARSE_POINT, FILE_GENERIC_READ, FILE_GENERIC_WRITE, OPEN_ALWAYS,
            };

            let _ = install_root;
            let lock_path = windows_package_lock_path()?;
            let mut wide = lock_path.as_os_str().encode_wide().collect::<Vec<_>>();
            if wide.contains(&0) {
                return Err(());
            }
            wide.push(0);
            let handle = unsafe {
                CreateFileW(
                    wide.as_ptr(),
                    FILE_GENERIC_READ | FILE_GENERIC_WRITE | DELETE,
                    0,
                    std::ptr::null(),
                    OPEN_ALWAYS,
                    FILE_ATTRIBUTE_HIDDEN
                        | FILE_FLAG_DELETE_ON_CLOSE
                        | FILE_FLAG_OPEN_REPARSE_POINT,
                    std::ptr::null_mut(),
                )
            };
            if handle == INVALID_HANDLE_VALUE {
                return Err(());
            }
            Ok(Self { handle })
        }
        #[cfg(unix)]
        {
            let directory = OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
                .open(install_root)
                .map_err(|_| ())?;
            let named = std::fs::symlink_metadata(install_root).map_err(|_| ())?;
            let opened = directory.metadata().map_err(|_| ())?;
            if named.file_type().is_symlink()
                || !opened.file_type().is_dir()
                || opened.dev() != named.dev()
                || opened.ino() != named.ino()
                || (opened.uid() != 0 && opened.uid() != unsafe { libc::geteuid() })
                || unsafe { libc::flock(directory.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0
            {
                return Err(());
            }
            Ok(Self {
                _directory: directory,
            })
        }
    }
}

#[cfg(windows)]
impl Drop for OrdinaryActionLock {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.handle);
        }
    }
}

fn write_transaction_token(token: &str) -> Result<(), ()> {
    use std::io::Write;

    let mut stdout = std::io::stdout().lock();
    stdout.write_all(token.as_bytes()).map_err(|_| ())?;
    stdout.flush().map_err(|_| ())
}

fn load_operation_manifest(
    operation: &str,
    shape: PackageShape,
    manifest_path: &Path,
    product_version: &str,
) -> Result<ComponentManifest, ()> {
    #[cfg(target_os = "linux")]
    if operation == "cleanup" && shape == PackageShape::Deb {
        return ComponentManifest::load_incomplete_for_removal(manifest_path, product_version)
            .map_err(|_| ());
    }
    #[cfg(not(target_os = "linux"))]
    let _ = (operation, shape);
    ComponentManifest::load(manifest_path, product_version).map_err(|_| ())
}

fn run() -> Result<(), ()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let operation = arguments.first().map(String::as_str).ok_or(())?;
    let valid_arity = match operation {
        "complete" => arguments.len() == 3,
        _ => arguments.len() == 2,
    };
    if !valid_arity
        || !matches!(
            operation,
            "capability"
                | "install"
                | "repair"
                | "complete"
                | "complete-legacy"
                | "resume-package"
                | "uninstall"
                | "remove"
                | "drain"
                | "cleanup"
        )
    {
        return Err(());
    }
    let shape = PackageShape::parse(&arguments[1]).map_err(|_| ())?;
    let product_version = aiguard_native_broker_protocol::native_component_build_id();
    let executable = std::env::current_exe().map_err(|_| ())?;
    let install_root = executable.parent().ok_or(())?;
    let manifest_path = install_root.join("native-components-v1.json");
    let manifest = load_operation_manifest(operation, shape, &manifest_path, product_version)?;
    let package = manifest
        .verify_client_executable(&executable)
        .map_err(|_| ())?;
    if package.allowed_role != "maintenance" {
        return Err(());
    }
    if operation == "capability" {
        return Ok(());
    }
    if !operation_supports_shape(operation, shape) {
        return Err(());
    }
    if operation == "resume-package" {
        let token =
            aiguard_native_broker_protocol::lifecycle::package_replacement_token(install_root)
                .map_err(|_| ())?
                .ok_or(())?;
        return write_transaction_token(&token);
    }
    if operation == "cleanup" {
        #[cfg(target_os = "linux")]
        if shape == PackageShape::Deb
            && unsafe { libc::geteuid() } == 0
            && aiguard_native_broker_protocol::lifecycle::package_replacement_token(install_root)
                .map_err(|_| ())?
                .is_some()
        {
            return aiguard_native_broker_protocol::transport::PlatformEndpoint::cleanup_deb_runtime_roots(
            )
            .map_err(|_| ());
        }
        return Err(());
    }
    let adapter = manifest
        .verified_client_executable_for_role("extension")
        .map_err(|_| ())?;
    let policy = manifest.native_host_policy().map_err(|_| ())?;
    #[cfg(target_os = "linux")]
    if shape == PackageShape::AppImage && running_from_appimage(&adapter) {
        return manage_transient_appimage(
            operation,
            &manifest,
            &manifest_path,
            &policy,
            product_version,
        );
    }
    if operation == "drain" {
        let token = if matches!(shape, PackageShape::Nsis | PackageShape::Deb) {
            Some(
                aiguard_native_broker_protocol::lifecycle::begin_package_replacement(install_root)
                    .map_err(|_| ())?,
            )
        } else {
            aiguard_native_broker_protocol::lifecycle::begin_component_replacement(install_root)
                .map_err(|_| ())?;
            None
        };
        aiguard_native_broker_protocol::lifecycle::drain_existing_broker(
            install_root,
            &manifest_path,
            product_version,
            Duration::from_secs(30),
        )
        .map_err(|_| ())?;
        if let Some(token) = token {
            write_transaction_token(&token)?;
        }
        return Ok(());
    }
    #[cfg(target_os = "linux")]
    let _appimage_lease = if shape == PackageShape::AppImage {
        Some(
            aiguard_native_broker_protocol::lifecycle::AppImageComponentLease::acquire(
                install_root,
            )
            .map_err(|_| ())?,
        )
    } else {
        None
    };
    #[cfg(target_os = "linux")]
    let abandoned_appimage = _appimage_lease.is_some();
    #[cfg(not(target_os = "linux"))]
    let abandoned_appimage = false;
    let _ordinary_lock = if matches!(operation, "install" | "repair" | "uninstall")
        && shape != PackageShape::AppImage
    {
        Some(OrdinaryActionLock::acquire(install_root)?)
    } else {
        None
    };
    let replacement_active =
        aiguard_native_broker_protocol::lifecycle::component_replacement_active(install_root)
            .map_err(|_| ())?;
    if matches!(operation, "install" | "repair" | "uninstall") {
        // A receipt without its marker is the fail-closed interruption point
        // between package-transaction publication and barrier creation.
        aiguard_native_broker_protocol::lifecycle::package_replacement_token(install_root)
            .map_err(|_| ())?;
    }
    if matches!(operation, "install" | "repair" | "uninstall")
        && !action_matches_replacement_state(operation, replacement_active, abandoned_appimage)
    {
        return Err(());
    }
    match operation {
        "install" | "repair" => {
            install_or_repair(shape, &adapter, &policy).map_err(|_| ())?;
            if replacement_active && abandoned_appimage {
                aiguard_native_broker_protocol::lifecycle::finish_component_replacement(
                    install_root,
                )
                .map_err(|_| ())?;
            }
            Ok(())
        }
        "complete" => {
            if !matches!(shape, PackageShape::Nsis | PackageShape::Deb) {
                return Err(());
            }
            if aiguard_native_broker_protocol::lifecycle::validate_package_replacement(
                install_root,
                &arguments[2],
            )
            .is_ok()
            {
                install_or_repair(shape, &adapter, &policy).map_err(|_| ())?;
            }
            aiguard_native_broker_protocol::lifecycle::finish_package_replacement(
                install_root,
                &arguments[2],
            )
            .map_err(|_| ())?;
            Ok(())
        }
        "complete-legacy" => {
            if !matches!(shape, PackageShape::Nsis | PackageShape::Deb) {
                return Err(());
            }
            aiguard_native_broker_protocol::lifecycle::validate_legacy_component_replacement(
                install_root,
            )
            .map_err(|_| ())?;
            install_or_repair(shape, &adapter, &policy).map_err(|_| ())?;
            aiguard_native_broker_protocol::lifecycle::finish_legacy_component_replacement(
                install_root,
            )
            .map_err(|_| ())
        }
        "uninstall" | "remove" => {
            let package_remove = arguments[0] == "remove";
            let transaction = if package_remove {
                if !matches!(shape, PackageShape::Nsis | PackageShape::Deb) {
                    return Err(());
                }
                Some(
                    aiguard_native_broker_protocol::lifecycle::begin_package_replacement(
                        install_root,
                    )
                    .map_err(|_| ())?,
                )
            } else {
                aiguard_native_broker_protocol::lifecycle::begin_owned_component_replacement(
                    install_root,
                )
                .map_err(|_| ())?;
                None
            };
            aiguard_native_broker_protocol::lifecycle::drain_existing_broker(
                install_root,
                &manifest_path,
                product_version,
                Duration::from_secs(30),
            )
            .map_err(|_| ())?;
            unregister(shape, &adapter, &policy).map_err(|_| ())?;
            #[cfg(target_os = "linux")]
            let package_script_will_cleanup =
                shape == PackageShape::Deb && unsafe { libc::geteuid() } == 0;
            #[cfg(not(target_os = "linux"))]
            let package_script_will_cleanup = false;
            if !package_script_will_cleanup {
                aiguard_native_broker_protocol::transport::PlatformEndpoint::cleanup_default_runtime_root(
                    install_root,
                )
                .map_err(|_| ())?;
            }
            if !package_remove {
                aiguard_native_broker_protocol::lifecycle::finish_component_replacement(
                    install_root,
                )
                .map_err(|_| ())?;
            }
            if let Some(token) = transaction {
                write_transaction_token(&token)?;
            }
            Ok(())
        }
        _ => Err(()),
    }
}

#[cfg(target_os = "linux")]
fn running_from_appimage(adapter: &Path) -> bool {
    let appimage = std::env::var_os("APPIMAGE").map(PathBuf::from);
    let appdir = std::env::var_os("APPDIR").map(PathBuf::from);
    matches!((appimage, appdir), (Some(image), Some(root)) if image.is_absolute() && root.is_absolute() && adapter.starts_with(&root))
}

#[cfg(target_os = "linux")]
fn verified_component_sources(
    manifest: &ComponentManifest,
    manifest_path: &Path,
) -> Result<Vec<PathBuf>, ()> {
    let mut sources = vec![
        manifest
            .verified_client_executable_for_role("desktop")
            .map_err(|_| ())?,
        manifest
            .verified_client_executable_for_role("extension")
            .map_err(|_| ())?,
        manifest
            .verified_client_executable_for_role("maintenance")
            .map_err(|_| ())?,
        manifest.verified_broker_executable().map_err(|_| ())?,
        manifest
            .verify_backend()
            .map_err(|_| ())?
            .executable()
            .to_owned(),
    ];
    sources.push(manifest_path.to_owned());
    let mut names = BTreeSet::new();
    if sources.iter().any(|path| {
        path.file_name()
            .and_then(|name| name.to_str())
            .is_none_or(|name| !names.insert(name.to_owned()))
    }) {
        return Err(());
    }
    Ok(sources)
}

#[cfg(target_os = "linux")]
fn checked_directory(path: &Path) -> Result<(), ()> {
    if !path.is_absolute() {
        return Err(());
    }
    match std::fs::symlink_metadata(path) {
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            match std::fs::create_dir(path) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(_) => return Err(()),
            }
        }
        Err(_) => return Err(()),
    }
    let metadata = std::fs::symlink_metadata(path).map_err(|_| ())?;
    if !metadata.file_type().is_dir()
        || metadata.file_type().is_symlink()
        || metadata.uid() != unsafe { libc::geteuid() }
    {
        return Err(());
    }
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).map_err(|_| ())?;
    let after = std::fs::symlink_metadata(path).map_err(|_| ())?;
    if !after.file_type().is_dir()
        || after.file_type().is_symlink()
        || after.uid() != unsafe { libc::geteuid() }
        || after.dev() != metadata.dev()
        || after.ino() != metadata.ino()
        || after.mode() & 0o7777 != 0o700
    {
        return Err(());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
const STABLE_REPAIR_LOCK: &str = ".component-repair-v1.lock";

#[cfg(target_os = "linux")]
struct StableRepairLock {
    file: File,
    path: PathBuf,
}

#[cfg(target_os = "linux")]
impl StableRepairLock {
    fn acquire(root: &Path) -> Result<Self, ()> {
        let path = root.join(STABLE_REPAIR_LOCK);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&path)
            .map_err(|_| ())?;
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(30))
            .ok_or(())?;
        loop {
            // SAFETY: flock operates on the live descriptor owned by file.
            let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
            if result == 0 {
                break;
            }
            if std::io::Error::last_os_error().raw_os_error() != Some(libc::EWOULDBLOCK)
                || Instant::now() >= deadline
            {
                return Err(());
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        let metadata = file.metadata().map_err(|_| ())?;
        let path_metadata = std::fs::symlink_metadata(&path).map_err(|_| ())?;
        if !metadata.file_type().is_file()
            || path_metadata.file_type().is_symlink()
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.dev() != path_metadata.dev()
            || metadata.ino() != path_metadata.ino()
            || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
        {
            return Err(());
        }
        Ok(Self { file, path })
    }

    fn remove_owned_file(&self) -> Result<(), ()> {
        let metadata = self.file.metadata().map_err(|_| ())?;
        let path_metadata = std::fs::symlink_metadata(&self.path).map_err(|_| ())?;
        if !metadata.file_type().is_file()
            || path_metadata.file_type().is_symlink()
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.dev() != path_metadata.dev()
            || metadata.ino() != path_metadata.ino()
            || metadata.nlink() != 1
            || metadata.mode() & 0o7777 != 0o600
        {
            return Err(());
        }
        std::fs::remove_file(&self.path).map_err(|_| ())
    }
}

#[cfg(target_os = "linux")]
fn prepare_stable_root(path: &Path) -> Result<(), ()> {
    let base = path
        .ancestors()
        .nth(3)
        .filter(|base| base.is_absolute())
        .ok_or(())?;
    std::fs::create_dir_all(base).map_err(|_| ())?;
    let metadata = std::fs::symlink_metadata(base).map_err(|_| ())?;
    if !metadata.file_type().is_dir()
        || metadata.file_type().is_symlink()
        || metadata.uid() != unsafe { libc::geteuid() }
    {
        return Err(());
    }
    let mut current = base.to_owned();
    for component in path.strip_prefix(base).map_err(|_| ())?.components() {
        current.push(component);
        checked_directory(&current)?;
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn copy_atomic(source: &Path, destination: &Path, executable: bool) -> Result<(), ()> {
    use std::io::{Read, Write};
    use std::os::unix::fs::PermissionsExt;

    let mut input = std::fs::File::open(source).map_err(|_| ())?;
    let mut temporary = None;
    for index in 0..16 {
        let candidate =
            destination.with_extension(format!("aiguard-tmp-{}-{index}", std::process::id()));
        match std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&candidate)
        {
            Ok(file) => {
                temporary = Some((candidate, file));
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(_) => return Err(()),
        }
    }
    let (temporary_path, mut output) = temporary.ok_or(())?;
    let result = (|| -> Result<(), ()> {
        let mut buffer = [0_u8; 64 * 1024];
        loop {
            let read = input.read(&mut buffer).map_err(|_| ())?;
            if read == 0 {
                break;
            }
            output.write_all(&buffer[..read]).map_err(|_| ())?;
        }
        output.sync_all().map_err(|_| ())?;
        output
            .set_permissions(std::fs::Permissions::from_mode(if executable {
                0o755
            } else {
                0o644
            }))
            .map_err(|_| ())?;
        drop(output);
        std::fs::rename(&temporary_path, destination).map_err(|_| ())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary_path);
    }
    result
}

#[cfg(target_os = "linux")]
fn cleanup_owned_staging_files(stable_root: &Path, sources: &[PathBuf]) -> Result<(), ()> {
    let expected_destinations = sources
        .iter()
        .map(|source| {
            source
                .file_stem()
                .and_then(|name| name.to_str())
                .map(str::to_owned)
                .ok_or(())
        })
        .collect::<Result<BTreeSet<_>, _>>()?;
    let entries = std::fs::read_dir(stable_root)
        .map_err(|_| ())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| ())?;
    for entry in entries {
        let name = entry.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        if !name.contains(".aiguard-tmp-") {
            continue;
        }
        let Some((destination, suffix)) = name.rsplit_once(".aiguard-tmp-") else {
            return Err(());
        };
        let Some((pid, index)) = suffix.split_once('-') else {
            return Err(());
        };
        if !expected_destinations.contains(destination)
            || pid.parse::<u32>().is_err()
            || index
                .parse::<u8>()
                .ok()
                .filter(|value| *value < 16)
                .is_none()
        {
            return Err(());
        }
        let path = entry.path();
        let metadata = std::fs::symlink_metadata(&path).map_err(|_| ())?;
        if metadata.file_type().is_symlink()
            || !metadata.file_type().is_file()
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.nlink() != 1
            || path.parent() != Some(stable_root)
        {
            return Err(());
        }
        std::fs::remove_file(path).map_err(|_| ())?;
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn bounded_manifest_bytes(path: &Path) -> Result<Vec<u8>, ()> {
    use std::io::Read;

    const MAX_BYTES: u64 = 64 * 1024;
    let metadata = std::fs::symlink_metadata(path).map_err(|_| ())?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() == 0
        || metadata.len() > MAX_BYTES
    {
        return Err(());
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    File::open(path)
        .map_err(|_| ())?
        .take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ())?;
    if bytes.len() as u64 != metadata.len() {
        return Err(());
    }
    Ok(bytes)
}

#[cfg(target_os = "linux")]
fn read_only_filesystem(path: &Path) -> bool {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let Ok(path) = CString::new(path.as_os_str().as_bytes()) else {
        return false;
    };
    let mut statistics = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    // SAFETY: path is NUL-terminated and statistics points to writable storage.
    if unsafe { libc::statvfs(path.as_ptr(), statistics.as_mut_ptr()) } != 0 {
        return false;
    }
    // SAFETY: statvfs returned success and initialized statistics.
    unsafe { statistics.assume_init().f_flag & libc::ST_RDONLY != 0 }
}

#[cfg(target_os = "linux")]
fn trusted_transient_appimage_owner(
    owner: u32,
    effective_user: u32,
    source_root: &Path,
    appdir: Option<&Path>,
    filesystem_read_only: bool,
) -> bool {
    if owner == effective_user {
        return true;
    }
    if owner != 0 || !filesystem_read_only {
        return false;
    }
    let Some(appdir) = appdir.filter(|path| path.is_absolute()) else {
        return false;
    };
    let Ok(canonical_appdir) = appdir.canonicalize() else {
        return false;
    };
    canonical_appdir == appdir && source_root == canonical_appdir.join("usr").join("bin")
}

#[cfg(target_os = "linux")]
fn verified_direct_component_layout(
    root: &Path,
    sources: &[PathBuf],
    manifest_path: &Path,
    expected_owner: u32,
) -> bool {
    let Ok(root) = root.canonicalize() else {
        return false;
    };
    let Ok(root_metadata) = std::fs::symlink_metadata(&root) else {
        return false;
    };
    if root_metadata.file_type().is_symlink()
        || !root_metadata.file_type().is_dir()
        || root_metadata.uid() != expected_owner
    {
        return false;
    }
    let Ok(manifest_path) = manifest_path.canonicalize() else {
        return false;
    };
    sources.iter().all(|source| {
        if source.parent() != Some(root.as_path()) {
            return false;
        }
        let Ok(metadata) = std::fs::symlink_metadata(source) else {
            return false;
        };
        let expected_mode = if source == &manifest_path {
            0o644
        } else {
            0o755
        };
        metadata.file_type().is_file()
            && !metadata.file_type().is_symlink()
            && metadata.uid() == expected_owner
            && metadata.dev() == root_metadata.dev()
            && metadata.nlink() == 1
            && metadata.mode() & 0o7777 == expected_mode
    })
}

#[cfg(target_os = "linux")]
fn verified_existing_stable_adapter(
    stable_root: &Path,
    manifest_name: &std::ffi::OsStr,
    source_manifest_bytes: &[u8],
    product_version: &str,
) -> Option<PathBuf> {
    let stable_root = stable_root.canonicalize().ok()?;
    let stable_manifest = stable_root.join(manifest_name);
    if source_manifest_bytes != bounded_manifest_bytes(&stable_manifest).ok()? {
        return None;
    }
    let installed = ComponentManifest::load(&stable_manifest, product_version).ok()?;
    let sources = verified_component_sources(&installed, &stable_manifest).ok()?;
    let adapter = installed
        .verified_client_executable_for_role("extension")
        .ok()?;
    if adapter.parent() != Some(stable_root.as_path())
        || !verified_direct_component_layout(&stable_root, &sources, &stable_manifest, unsafe {
            libc::geteuid()
        })
    {
        return None;
    }
    if source_manifest_bytes != bounded_manifest_bytes(&stable_manifest).ok()? {
        return None;
    }
    Some(adapter)
}

#[cfg(target_os = "linux")]
fn stage_appimage_components_locked(
    stable_root: &Path,
    manifest: &ComponentManifest,
    manifest_path: &Path,
    product_version: &str,
) -> Result<PathBuf, ()> {
    let source_manifest_bytes = bounded_manifest_bytes(manifest_path)?;
    let sources = verified_component_sources(manifest, manifest_path)?;
    cleanup_owned_staging_files(stable_root, &sources)?;
    let source_root = manifest_path.parent().ok_or(())?;
    let source_owner = std::fs::symlink_metadata(manifest_path)
        .map_err(|_| ())?
        .uid();
    // FUSE exposes immutable AppImage bytes as root; extraction uses the caller.
    let appdir = std::env::var_os("APPDIR").map(PathBuf::from);
    if !trusted_transient_appimage_owner(
        source_owner,
        unsafe { libc::geteuid() },
        source_root,
        appdir.as_deref(),
        read_only_filesystem(source_root),
    ) || !verified_direct_component_layout(source_root, &sources, manifest_path, source_owner)
        || source_manifest_bytes != bounded_manifest_bytes(manifest_path)?
    {
        return Err(());
    }
    let manifest_name = manifest_path.file_name().ok_or(())?;
    if let Some(adapter) = verified_existing_stable_adapter(
        stable_root,
        manifest_name,
        &source_manifest_bytes,
        product_version,
    ) {
        return Ok(adapter);
    }
    for source in sources.iter().filter(|path| *path != manifest_path) {
        let destination = stable_root.join(source.file_name().ok_or(())?);
        copy_atomic(source, &destination, true)?;
    }
    let stable_manifest = stable_root.join(manifest_name);
    copy_atomic(manifest_path, &stable_manifest, false)?;
    verified_existing_stable_adapter(
        stable_root,
        manifest_name,
        &source_manifest_bytes,
        product_version,
    )
    .ok_or(())
}

#[cfg(all(test, target_os = "linux"))]
fn stage_appimage_components_at(
    stable_root: &Path,
    manifest: &ComponentManifest,
    manifest_path: &Path,
    product_version: &str,
) -> Result<PathBuf, ()> {
    prepare_stable_root(stable_root)?;
    let _lock = StableRepairLock::acquire(stable_root)?;
    stage_appimage_components_locked(stable_root, manifest, manifest_path, product_version)
}

#[cfg(target_os = "linux")]
fn remove_owned_stable_root(stable_root: &Path, lock: &StableRepairLock) -> Result<(), ()> {
    lock.remove_owned_file()?;
    match std::fs::remove_dir(stable_root) {
        Ok(()) => {}
        Err(_) => return Err(()),
    }
    for owned_parent in stable_root.ancestors().skip(1).take(2) {
        match std::fs::remove_dir(owned_parent) {
            Ok(()) => {}
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::NotFound | std::io::ErrorKind::DirectoryNotEmpty
                ) => {}
            Err(_) => return Err(()),
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn same_file_bytes(first: &Path, second: &Path) -> Result<bool, ()> {
    use std::io::Read;

    let first_metadata = std::fs::symlink_metadata(first).map_err(|_| ())?;
    let second_metadata = std::fs::symlink_metadata(second).map_err(|_| ())?;
    if first_metadata.len() != second_metadata.len() {
        return Ok(false);
    }
    let mut first = File::open(first).map_err(|_| ())?;
    let mut second = File::open(second).map_err(|_| ())?;
    let mut first_buffer = [0_u8; 64 * 1024];
    let mut second_buffer = [0_u8; 64 * 1024];
    loop {
        let first_read = first.read(&mut first_buffer).map_err(|_| ())?;
        let second_read = second.read(&mut second_buffer).map_err(|_| ())?;
        if first_read != second_read || first_buffer[..first_read] != second_buffer[..second_read] {
            return Ok(false);
        }
        if first_read == 0 {
            return Ok(true);
        }
    }
}

#[cfg(target_os = "linux")]
fn verify_owned_root_entries(stable_root: &Path, sources: &[PathBuf]) -> Result<(), ()> {
    let mut allowed = sources
        .iter()
        .map(|path| path.file_name().map(std::ffi::OsStr::to_owned).ok_or(()))
        .collect::<Result<BTreeSet<_>, _>>()?;
    allowed.insert(std::ffi::OsString::from(STABLE_REPAIR_LOCK));
    allowed.insert(std::ffi::OsString::from(
        aiguard_native_broker_protocol::lifecycle::COMPONENT_MAINTENANCE_FILE,
    ));
    for entry in std::fs::read_dir(stable_root).map_err(|_| ())? {
        let entry = entry.map_err(|_| ())?;
        if !allowed.contains(&entry.file_name()) {
            return Err(());
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn remove_verified_manifest_set_locked(
    stable_root: &Path,
    installed: &ComponentManifest,
    stable_manifest: &Path,
    lock: &StableRepairLock,
) -> Result<(), ()> {
    let declared = installed.declared_component_paths_for_removal();
    let mut sources = declared.clone();
    sources.push(stable_manifest.to_owned());
    cleanup_owned_staging_files(stable_root, &sources)?;
    verify_owned_root_entries(stable_root, &sources)?;
    let mut present = Vec::new();
    for path in declared {
        match installed.verify_present_component_for_removal(&path) {
            Ok(true) => present.push(path),
            Ok(false) => {}
            Err(_) => return Err(()),
        }
    }
    for path in present {
        std::fs::remove_file(path).map_err(|_| ())?;
    }
    std::fs::remove_file(stable_manifest).map_err(|_| ())?;
    aiguard_native_broker_protocol::lifecycle::finish_component_replacement(stable_root)
        .map_err(|_| ())?;
    remove_owned_stable_root(stable_root, lock)
}

#[cfg(target_os = "linux")]
fn remove_stable_appimage_components_locked(
    stable_root: &Path,
    manifest_path: &Path,
    product_version: &str,
    lock: &StableRepairLock,
) -> Result<(), ()> {
    let stable_manifest = stable_root.join(manifest_path.file_name().ok_or(())?);
    if !stable_manifest.exists() {
        let source = ComponentManifest::load(manifest_path, product_version).map_err(|_| ())?;
        let sources = verified_component_sources(&source, manifest_path)?;
        cleanup_owned_staging_files(stable_root, &sources)?;
        verify_owned_root_entries(stable_root, &sources)?;
        for source in sources {
            let destination = stable_root.join(source.file_name().ok_or(())?);
            let metadata = match std::fs::symlink_metadata(&destination) {
                Ok(value) => value,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(_) => return Err(()),
            };
            let expected_mode = if source == manifest_path {
                0o644
            } else {
                0o755
            };
            if metadata.file_type().is_symlink()
                || !metadata.file_type().is_file()
                || metadata.uid() != unsafe { libc::geteuid() }
                || metadata.nlink() != 1
                || metadata.mode() & 0o7777 != expected_mode
                || !same_file_bytes(&source, &destination)?
            {
                return Err(());
            }
            std::fs::remove_file(destination).map_err(|_| ())?;
        }
        aiguard_native_broker_protocol::lifecycle::finish_component_replacement(stable_root)
            .map_err(|_| ())?;
        return remove_owned_stable_root(stable_root, lock);
    }
    let source_manifest_bytes = bounded_manifest_bytes(manifest_path)?;
    if source_manifest_bytes != bounded_manifest_bytes(&stable_manifest)? {
        return Err(());
    }
    let installed =
        ComponentManifest::load_incomplete_for_removal(&stable_manifest, product_version)
            .map_err(|_| ())?;
    remove_verified_manifest_set_locked(stable_root, &installed, &stable_manifest, lock)
}

#[cfg(target_os = "linux")]
fn remove_previous_appimage_root(
    previous: &PreviousAppImageRegistration,
    policy: &aiguard_native_broker_protocol::manifest::NativeHostPolicy,
) -> Result<(), ()> {
    let stable_root = &previous.component_root;
    let lock = StableRepairLock::acquire(stable_root)?;
    let stable_manifest = stable_root.join("native-components-v1.json");
    if !stable_manifest.exists() {
        let allowed = BTreeSet::from([
            std::ffi::OsString::from(STABLE_REPAIR_LOCK),
            std::ffi::OsString::from(
                aiguard_native_broker_protocol::lifecycle::COMPONENT_MAINTENANCE_FILE,
            ),
        ]);
        for entry in std::fs::read_dir(stable_root).map_err(|_| ())? {
            if !allowed.contains(&entry.map_err(|_| ())?.file_name()) {
                return Err(());
            }
        }
        if !aiguard_native_broker_protocol::lifecycle::component_replacement_active(stable_root)
            .map_err(|_| ())?
        {
            return Err(());
        }
        aiguard_native_broker_protocol::lifecycle::finish_component_replacement(stable_root)
            .map_err(|_| ())?;
        return remove_owned_stable_root(stable_root, &lock);
    }
    let installed =
        ComponentManifest::load_incomplete_for_removal(&stable_manifest, &previous.product_version)
            .map_err(|_| ())?;
    if installed.native_host_policy().map_err(|_| ())? != *policy {
        return Err(());
    }
    if !aiguard_native_broker_protocol::lifecycle::component_replacement_active(stable_root)
        .map_err(|_| ())?
    {
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(stable_root)
            .map_err(|_| ())?;
    }
    remove_verified_manifest_set_locked(stable_root, &installed, &stable_manifest, &lock)
}

#[cfg(all(test, target_os = "linux"))]
fn remove_stable_appimage_components_at(
    stable_root: &Path,
    manifest_path: &Path,
    product_version: &str,
) -> Result<(), ()> {
    if !stable_root.exists() {
        return Ok(());
    }
    let lock = StableRepairLock::acquire(stable_root)?;
    remove_stable_appimage_components_locked(stable_root, manifest_path, product_version, &lock)
}

#[cfg(target_os = "linux")]
struct TransientAppImageSource<'a> {
    manifest: &'a ComponentManifest,
    manifest_path: &'a Path,
    product_version: &'a str,
}

#[cfg(target_os = "linux")]
struct AppImageReplacementGuard {
    _endpoint: Option<aiguard_native_broker_protocol::transport::PlatformEndpointReservation>,
    previous: Vec<PreviousAppImageRegistration>,
}

#[cfg(target_os = "linux")]
impl AppImageReplacementGuard {
    fn unreserved(previous: Vec<PreviousAppImageRegistration>) -> Self {
        Self {
            _endpoint: None,
            previous,
        }
    }

    fn reserved(
        endpoint: aiguard_native_broker_protocol::transport::PlatformEndpointReservation,
        previous: Vec<PreviousAppImageRegistration>,
    ) -> Self {
        Self {
            _endpoint: Some(endpoint),
            previous,
        }
    }
}

#[cfg(target_os = "linux")]
fn manage_transient_appimage_at<Prepare, Install, Unregister, Cleanup>(
    stable_root: &Path,
    operation: &str,
    source: TransientAppImageSource<'_>,
    mut prepare_replacement: Prepare,
    install_registration: Install,
    unregister_registration: Unregister,
    cleanup_runtime_root: Cleanup,
) -> Result<(), ()>
where
    Prepare: FnMut(&Path) -> Result<AppImageReplacementGuard, ()>,
    Install: FnOnce(&Path) -> Result<(), ()>,
    Unregister: FnOnce(&Path) -> Result<(), ()>,
    Cleanup: FnOnce(&Path) -> Result<(), ()>,
{
    if !matches!(operation, "install" | "repair" | "uninstall") {
        return Err(());
    }
    let adapter_name = source
        .manifest
        .verified_client_executable_for_role("extension")
        .map_err(|_| ())?
        .file_name()
        .ok_or(())?
        .to_owned();
    let stable_adapter = stable_root.join(adapter_name);
    prepare_stable_root(stable_root)?;
    let lock = StableRepairLock::acquire(stable_root)?;
    match operation {
        "install" | "repair" => {
            let source_manifest_bytes = bounded_manifest_bytes(source.manifest_path)?;
            let manifest_name = source.manifest_path.file_name().ok_or(())?;
            let exact_set = verified_existing_stable_adapter(
                stable_root,
                manifest_name,
                &source_manifest_bytes,
                source.product_version,
            )
            .is_some();
            let interrupted =
                aiguard_native_broker_protocol::lifecycle::component_replacement_active(
                    stable_root,
                )
                .map_err(|_| ())?;
            if !exact_set {
                aiguard_native_broker_protocol::lifecycle::begin_component_replacement(stable_root)
                    .map_err(|_| ())?;
            }
            let replacement_guard = if !exact_set || interrupted {
                Some(prepare_replacement(stable_root)?)
            } else {
                None
            };
            let adapter = stage_appimage_components_locked(
                stable_root,
                source.manifest,
                source.manifest_path,
                source.product_version,
            )?;
            install_registration(&adapter)?;
            if let Some(guard) = &replacement_guard {
                let policy = source.manifest.native_host_policy().map_err(|_| ())?;
                for previous in &guard.previous {
                    remove_previous_appimage_root(previous, &policy)?;
                }
            }
            if !exact_set || interrupted {
                aiguard_native_broker_protocol::lifecycle::finish_component_replacement(
                    stable_root,
                )
                .map_err(|_| ())?;
            }
            Ok(())
        }
        "uninstall" => {
            aiguard_native_broker_protocol::lifecycle::begin_component_replacement(stable_root)
                .map_err(|_| ())?;
            let replacement_guard = prepare_replacement(stable_root)?;
            unregister_registration(&stable_adapter)?;
            remove_stable_appimage_components_locked(
                stable_root,
                source.manifest_path,
                source.product_version,
                &lock,
            )?;
            let policy = source.manifest.native_host_policy().map_err(|_| ())?;
            for previous in &replacement_guard.previous {
                remove_previous_appimage_root(previous, &policy)?;
            }
            drop(replacement_guard);
            cleanup_runtime_root(stable_root)
        }
        _ => Err(()),
    }
}

#[cfg(target_os = "linux")]
fn prepare_appimage_replacement_at<Run, Isolate, Reserve>(
    stable_root: &Path,
    product_version: &str,
    run_manager: Run,
    isolate_registration: Isolate,
    reserve_inactive: Reserve,
) -> Result<AppImageReplacementGuard, ()>
where
    Run: FnOnce(&Path) -> bool,
    Isolate: FnOnce() -> Result<Vec<PreviousAppImageRegistration>, ()>,
    Reserve: FnOnce(
        &[PreviousAppImageRegistration],
    ) -> Result<
        aiguard_native_broker_protocol::transport::PlatformEndpointReservation,
        (),
    >,
{
    let manifest_path = stable_root.join("native-components-v1.json");
    if let Ok(manifest) = ComponentManifest::load(&manifest_path, product_version) {
        if let Ok(manager) = manifest.verified_client_executable_for_role("maintenance") {
            if manager.parent() == Some(stable_root) && run_manager(&manager) {
                let previous = isolate_registration()?;
                if previous.is_empty() {
                    return Ok(AppImageReplacementGuard::unreserved(previous));
                }
                return reserve_inactive(&previous)
                    .map(|endpoint| AppImageReplacementGuard::reserved(endpoint, previous));
            }
        }
    }
    // A pre-Slice-6 manager, or a manager already replaced before the
    // manifest-last commit, cannot perform the drain. Continue only after the
    // endpoint lock proves no broker is live.
    let previous = isolate_registration()?;
    reserve_inactive(&previous)
        .map(|endpoint| AppImageReplacementGuard::reserved(endpoint, previous))
}

#[cfg(target_os = "linux")]
fn reserve_appimage_broker_inactive(
    stable_root: &Path,
) -> Result<aiguard_native_broker_protocol::transport::PlatformEndpointReservation, ()> {
    let endpoint_root =
        aiguard_native_broker_protocol::transport::PlatformEndpoint::default_runtime_root(
            stable_root,
        )
        .map_err(|_| ())?;
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or(())?;
    loop {
        match aiguard_native_broker_protocol::transport::PlatformEndpoint::reserve(&endpoint_root) {
            Ok(reservation) => return Ok(reservation),
            Err(error) if error.code() == "broker_unavailable" && Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(25));
            }
            Err(_) => return Err(()),
        }
    }
}

#[cfg(target_os = "linux")]
fn prepare_previous_appimage_roots(previous: &[PreviousAppImageRegistration]) -> Result<(), ()> {
    for previous in previous {
        let manifest_path = previous.component_root.join("native-components-v1.json");
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(
            &previous.component_root,
        )
        .map_err(|_| ())?;
        if manifest_path.exists() {
            let manifest = ComponentManifest::load_incomplete_for_removal(
                &manifest_path,
                &previous.product_version,
            )
            .map_err(|_| ())?;
            if let Ok(manager) = manifest.verified_client_executable_for_role("maintenance") {
                if manager.parent() != Some(previous.component_root.as_path()) {
                    return Err(());
                }
                let mut command = Command::new(manager);
                command
                    .args(["drain", "appimage"])
                    .current_dir(&previous.component_root)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null());
                aiguard_native_broker_protocol::lifecycle::configure_maintenance_command(
                    &mut command,
                );
                let _ = command.status();
            }
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn merge_discovered_previous_appimage_roots(
    stable_root: &Path,
    policy: &aiguard_native_broker_protocol::manifest::NativeHostPolicy,
    mut previous: Vec<PreviousAppImageRegistration>,
) -> Result<Vec<PreviousAppImageRegistration>, ()> {
    let shared_root = stable_root.parent().ok_or(())?;
    for entry in std::fs::read_dir(shared_root).map_err(|_| ())? {
        let entry = entry.map_err(|_| ())?;
        let root = entry.path();
        if root == stable_root {
            continue;
        }
        let metadata = std::fs::symlink_metadata(&root).map_err(|_| ())?;
        if !metadata.file_type().is_dir()
            || metadata.file_type().is_symlink()
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.mode() & 0o7777 != 0o700
        {
            return Err(());
        }
        let version = root
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or(())?;
        if !ComponentManifest::valid_declared_product_version(version) {
            return Err(());
        }
        let active = aiguard_native_broker_protocol::lifecycle::component_replacement_active(&root)
            .map_err(|_| ())?;
        let manifest_path = root.join("native-components-v1.json");
        if manifest_path.exists() {
            let manifest = if active {
                ComponentManifest::load_incomplete_for_removal(&manifest_path, version)
            } else {
                ComponentManifest::load_declared(&manifest_path)
            }
            .map_err(|_| ())?;
            if manifest.product_version() != version
                || manifest.native_host_policy().map_err(|_| ())? != *policy
            {
                return Err(());
            }
            for path in manifest.declared_component_paths_for_removal() {
                manifest
                    .verify_present_component_for_removal(&path)
                    .map_err(|_| ())?;
            }
        } else {
            if !active {
                return Err(());
            }
            let allowed = BTreeSet::from([
                std::ffi::OsString::from(STABLE_REPAIR_LOCK),
                std::ffi::OsString::from(
                    aiguard_native_broker_protocol::lifecycle::COMPONENT_MAINTENANCE_FILE,
                ),
            ]);
            for entry in std::fs::read_dir(&root).map_err(|_| ())? {
                if !allowed.contains(&entry.map_err(|_| ())?.file_name()) {
                    return Err(());
                }
            }
        }
        let product_version = version.to_owned();
        let candidate = PreviousAppImageRegistration {
            component_root: root,
            product_version,
        };
        if let Some(existing) = previous
            .iter()
            .find(|value| value.component_root == candidate.component_root)
        {
            if existing != &candidate {
                return Err(());
            }
        } else {
            previous.push(candidate);
        }
    }
    previous.sort_by(|left, right| left.component_root.cmp(&right.component_root));
    Ok(previous)
}

#[cfg(target_os = "linux")]
fn prepare_appimage_replacement(
    stable_root: &Path,
    product_version: &str,
    stable_adapter: &Path,
    policy: &aiguard_native_broker_protocol::manifest::NativeHostPolicy,
) -> Result<AppImageReplacementGuard, ()> {
    prepare_appimage_replacement_at(
        stable_root,
        product_version,
        |manager| {
            let mut command = Command::new(manager);
            command
                .args(["drain", "appimage"])
                .current_dir(stable_root)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            aiguard_native_broker_protocol::lifecycle::configure_maintenance_command(&mut command);
            command.status().is_ok_and(|status| status.success())
        },
        || {
            let previous = isolate_appimage_registration_for_replacement(stable_adapter, policy)
                .map_err(|_| ())?;
            merge_discovered_previous_appimage_roots(stable_root, policy, previous)
        },
        |previous| {
            prepare_previous_appimage_roots(previous)?;
            reserve_appimage_broker_inactive(stable_root)
        },
    )
}

#[cfg(target_os = "linux")]
fn manage_transient_appimage(
    operation: &str,
    manifest: &ComponentManifest,
    manifest_path: &Path,
    policy: &aiguard_native_broker_protocol::manifest::NativeHostPolicy,
    product_version: &str,
) -> Result<(), ()> {
    let stable_root = appimage_component_root().map_err(|_| ())?;
    prepare_stable_root(&stable_root)?;
    let _component_lease =
        aiguard_native_broker_protocol::lifecycle::AppImageComponentLease::acquire(&stable_root)
            .map_err(|_| ())?;
    let stable_adapter = stable_root.join(
        manifest
            .verified_client_executable_for_role("extension")
            .map_err(|_| ())?
            .file_name()
            .ok_or(())?,
    );
    manage_transient_appimage_at(
        &stable_root,
        operation,
        TransientAppImageSource {
            manifest,
            manifest_path,
            product_version,
        },
        |root| prepare_appimage_replacement(root, product_version, &stable_adapter, policy),
        |adapter| install_or_repair(PackageShape::AppImage, adapter, policy).map_err(|_| ()),
        |adapter| unregister(PackageShape::AppImage, adapter, policy).map_err(|_| ()),
        |install_root| {
            aiguard_native_broker_protocol::transport::PlatformEndpoint::cleanup_default_runtime_root(
                install_root,
            )
            .map_err(|_| ())
        },
    )
}

fn main() -> ExitCode {
    std::panic::set_hook(Box::new(|_| {}));
    if run().is_ok() {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(75)
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};
    use std::collections::BTreeMap;
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{mpsc, Arc, Barrier, Mutex, MutexGuard, OnceLock};

    const VERSION: &str = "2.5.0";
    const BUILD_MARKER: &str = "AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0";

    #[test]
    fn transient_appimage_source_accepts_only_root_or_effective_user_owner() {
        let effective_user = unsafe { libc::geteuid() };
        let foreign = if effective_user == u32::MAX {
            effective_user - 1
        } else {
            effective_user + 1
        };
        let appdir = std::env::temp_dir().join(format!(
            "aiguard-appimage-owner-policy-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _guard = TempRoot(appdir.clone());
        let source_root = appdir.join("usr/bin");
        std::fs::create_dir_all(&source_root).unwrap();

        assert!(trusted_transient_appimage_owner(
            effective_user,
            effective_user,
            &source_root,
            None,
            false,
        ));
        assert!(trusted_transient_appimage_owner(
            0,
            effective_user,
            &source_root,
            Some(&appdir),
            true,
        ));
        assert!(!trusted_transient_appimage_owner(
            0,
            effective_user,
            &source_root,
            Some(&appdir),
            false,
        ));
        assert!(!trusted_transient_appimage_owner(
            0,
            effective_user,
            Path::new("/tmp/writable-appdir/usr/bin"),
            Some(&appdir),
            true,
        ));
        assert!(!trusted_transient_appimage_owner(
            0,
            effective_user,
            &source_root,
            None,
            true,
        ));
        assert!(!trusted_transient_appimage_owner(
            foreign,
            effective_user,
            &source_root,
            Some(&appdir),
            true,
        ));
    }

    fn endpoint_test_guard() -> MutexGuard<'static, ()> {
        static ENDPOINT_TEST_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        ENDPOINT_TEST_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap()
    }

    struct TempRoot(PathBuf);

    impl Drop for TempRoot {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn digest(bytes: &[u8]) -> String {
        hex::encode(Sha256::digest(bytes))
    }

    fn write_executable(root: &Path, name: &str, bytes: &[u8]) {
        let path = root.join(name);
        std::fs::write(&path, bytes).unwrap();
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755)).unwrap();
    }

    fn fixture_source(
        root: &Path,
        source_name: &str,
        version: &str,
    ) -> (ComponentManifest, PathBuf) {
        let source = root.join(source_name);
        std::fs::create_dir_all(&source).unwrap();

        let marker = format!("AIGUARD_NATIVE_COMPONENT_BUILD_ID={version}\0");
        let desktop = format!("fixture-desktop-{marker}").into_bytes();
        let adapter = format!("fixture-adapter-{marker}").into_bytes();
        let manager = format!("fixture-manager-{marker}").into_bytes();
        let broker = format!("fixture-broker-{marker}").into_bytes();
        let backend = b"fixture-backend".to_vec();
        for (name, bytes) in [
            ("desktop", desktop.as_slice()),
            ("aiguard-chrome-native-host", adapter.as_slice()),
            ("aiguard-native-host-manager", manager.as_slice()),
            ("aiguard-native-broker", broker.as_slice()),
            ("aiguard", backend.as_slice()),
        ] {
            write_executable(&source, name, bytes);
        }

        let manifest = serde_json::json!({
            "schema_version": 1,
            "product_version": version,
            "broker": {
                "component_id": "native-broker",
                "path": "aiguard-native-broker",
                "sha256": digest(&broker),
                "build_id": version
            },
            "clients": [
                {
                    "component_id": "desktop",
                    "role": "desktop",
                    "path": "desktop",
                    "sha256": digest(&desktop),
                    "build_id": version
                },
                {
                    "component_id": "chrome-native-host",
                    "role": "extension",
                    "path": "aiguard-chrome-native-host",
                    "sha256": digest(&adapter),
                    "build_id": version
                },
                {
                    "component_id": "native-host-manager",
                    "role": "maintenance",
                    "path": "aiguard-native-host-manager",
                    "sha256": digest(&manager),
                    "build_id": version
                }
            ],
            "backend": {
                "component_id": "python-backend",
                "path": "aiguard",
                "sha256": digest(&backend),
                "build_id": version,
                "arguments": ["--native-broker-backend"]
            },
            "native_host": {
                "name": "th.ac.psu.aiguard.native_host",
                "allowed_origin": "chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/",
                "identity_classification": "synthetic_test_only"
            }
        });
        let manifest_path = source.join("native-components-v1.json");
        std::fs::write(&manifest_path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        let loaded = ComponentManifest::load(&manifest_path, version).unwrap();
        (loaded, manifest_path)
    }

    fn fixture() -> (TempRoot, ComponentManifest, PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "aiguard-appimage-manager-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let stable = root
            .join("data")
            .join("aiguard")
            .join("native-host-v1")
            .join(VERSION);
        let (loaded, manifest_path) = fixture_source(&root, "source", VERSION);
        (TempRoot(root), loaded, manifest_path, stable)
    }

    #[test]
    fn deb_cleanup_admits_the_owned_manager_after_an_early_component_unlink() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-deb-partial-cleanup-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let guard = TempRoot(root.clone());
        let (_manifest, manifest_path) = fixture_source(&root, "package", VERSION);
        let package_root = manifest_path.parent().unwrap();
        let manager = package_root.join("aiguard-native-host-manager");
        std::fs::remove_file(package_root.join("desktop")).unwrap();

        assert!(ComponentManifest::load(&manifest_path, VERSION).is_err());
        let cleanup =
            load_operation_manifest("cleanup", PackageShape::Deb, &manifest_path, VERSION).unwrap();
        assert_eq!(
            cleanup
                .verify_client_executable(&manager)
                .unwrap()
                .allowed_role,
            "maintenance"
        );
        assert!(
            load_operation_manifest("remove", PackageShape::Deb, &manifest_path, VERSION).is_err()
        );
        assert!(
            load_operation_manifest("cleanup", PackageShape::Nsis, &manifest_path, VERSION)
                .is_err()
        );
        drop(guard);
    }

    fn installed_identity(stable: &Path) -> BTreeMap<String, (u64, u64)> {
        std::fs::read_dir(stable)
            .unwrap()
            .map(|entry| {
                let entry = entry.unwrap();
                let metadata = entry.metadata().unwrap();
                (
                    entry.file_name().into_string().unwrap(),
                    (metadata.dev(), metadata.ino()),
                )
            })
            .collect()
    }

    #[test]
    fn repeated_exact_appimage_repair_preserves_the_live_broker_inode() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        let first_identity = installed_identity(&stable);

        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();

        assert_eq!(installed_identity(&stable), first_identity);
    }

    #[test]
    fn hard_linked_stable_component_is_replaced_instead_of_preserved() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        let broker = stable.join("aiguard-native-broker");
        let held_broker = _root.0.join("held-broker");
        std::fs::hard_link(&broker, held_broker).unwrap();
        assert_eq!(broker.metadata().unwrap().nlink(), 2);

        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();

        assert_eq!(broker.metadata().unwrap().nlink(), 1);
    }

    #[test]
    fn invalid_stable_component_mode_is_repaired() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        let broker = stable.join("aiguard-native-broker");
        let first_inode = broker.metadata().unwrap().ino();
        std::fs::set_permissions(&broker, std::fs::Permissions::from_mode(0o700)).unwrap();

        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();

        let metadata = broker.metadata().unwrap();
        assert_eq!(metadata.mode() & 0o7777, 0o755);
        assert_ne!(metadata.ino(), first_inode);
    }

    #[test]
    fn interrupted_manager_before_manifest_uses_inactive_endpoint_recovery() {
        let _endpoint = endpoint_test_guard();
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&stable).unwrap();
        write_executable(
            &stable,
            "aiguard-native-host-manager",
            format!("new-manager-before-old-manifest-{BUILD_MARKER}").as_bytes(),
        );
        let waited = Arc::new(AtomicBool::new(false));

        manage_transient_appimage_at(
            &stable,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            {
                let waited = Arc::clone(&waited);
                move |root| {
                    prepare_appimage_replacement_at(
                        root,
                        VERSION,
                        |_| panic!("a manager that mismatches the old manifest must not run"),
                        || Ok(Vec::new()),
                        |_| {
                            waited.store(true, Ordering::SeqCst);
                            reserve_appimage_broker_inactive(root)
                        },
                    )
                }
            },
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();

        assert!(waited.load(Ordering::SeqCst));
        ComponentManifest::load(&stable.join("native-components-v1.json"), VERSION).unwrap();
        assert!(
            !aiguard_native_broker_protocol::lifecycle::component_replacement_active(&stable)
                .unwrap()
        );
        aiguard_native_broker_protocol::transport::PlatformEndpoint::cleanup_default_runtime_root(
            &stable,
        )
        .unwrap();
    }

    #[test]
    fn concurrent_initial_appimage_repairs_publish_one_complete_set() {
        let (_root, _manifest, manifest_path, stable) = fixture();
        let barrier = Arc::new(Barrier::new(3));
        let threads = (0..2)
            .map(|_| {
                let barrier = Arc::clone(&barrier);
                let manifest_path = manifest_path.clone();
                let stable = stable.clone();
                std::thread::spawn(move || {
                    let manifest = ComponentManifest::load(&manifest_path, VERSION).unwrap();
                    barrier.wait();
                    stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION)
                })
            })
            .collect::<Vec<_>>();
        barrier.wait();

        for thread in threads {
            thread.join().unwrap().unwrap();
        }

        assert_eq!(
            installed_identity(&stable)
                .keys()
                .cloned()
                .collect::<Vec<_>>(),
            vec![
                STABLE_REPAIR_LOCK.to_owned(),
                "aiguard".to_owned(),
                "aiguard-chrome-native-host".to_owned(),
                "aiguard-native-broker".to_owned(),
                "aiguard-native-host-manager".to_owned(),
                "desktop".to_owned(),
                "native-components-v1.json".to_owned(),
            ]
        );
    }

    #[test]
    fn appimage_uninstall_removes_the_owned_lock_and_component_root() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();

        remove_stable_appimage_components_at(&stable, &manifest_path, VERSION).unwrap();

        assert!(!stable.exists());
        remove_stable_appimage_components_at(&stable, &manifest_path, VERSION).unwrap();
    }

    #[test]
    fn appimage_uninstall_reports_runtime_cleanup_failure_after_fail_closed_removal() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        let cleanup_attempted = Arc::new(AtomicBool::new(false));

        let result = manage_transient_appimage_at(
            &stable,
            "uninstall",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            |_| Err(()),
            |_| Ok(()),
            {
                let cleanup_attempted = Arc::clone(&cleanup_attempted);
                let stable = stable.clone();
                move |install_root| {
                    assert_eq!(install_root, stable);
                    assert!(!stable.exists());
                    cleanup_attempted.store(true, Ordering::SeqCst);
                    Err(())
                }
            },
        );
        assert!(result.is_err());
        assert!(cleanup_attempted.load(Ordering::SeqCst));
        assert!(!stable.exists());

        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        manage_transient_appimage_at(
            &stable,
            "uninstall",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            |_| Err(()),
            |_| Ok(()),
            |install_root| {
                assert_eq!(install_root, stable);
                assert!(!stable.exists());
                Ok(())
            },
        )
        .unwrap();
        assert!(!stable.exists());
    }

    #[test]
    fn interrupted_staging_temp_is_removed_but_unrelated_temp_is_fail_closed() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        let owned_temp = stable.join("aiguard-native-broker.aiguard-tmp-4242-0");
        std::fs::write(&owned_temp, b"interrupted staging bytes").unwrap();
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&stable).unwrap();

        manage_transient_appimage_at(
            &stable,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();
        assert!(!owned_temp.exists());

        let unrelated = stable.join("unrelated.aiguard-tmp-4242-0");
        std::fs::write(&unrelated, b"unrelated bytes").unwrap();
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&stable).unwrap();
        assert!(manage_transient_appimage_at(
            &stable,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .is_err());
        assert!(unrelated.is_file());
        assert!(
            aiguard_native_broker_protocol::lifecycle::component_replacement_active(&stable)
                .unwrap()
        );
    }

    #[test]
    fn interrupted_registration_or_partial_staging_recovers_one_complete_set() {
        let (_root, manifest, manifest_path, stable) = fixture();
        assert!(manage_transient_appimage_at(
            &stable,
            "install",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            |_| Err(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .is_err());
        assert!(
            aiguard_native_broker_protocol::lifecycle::component_replacement_active(&stable)
                .unwrap()
        );

        manage_transient_appimage_at(
            &stable,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();
        assert!(
            !aiguard_native_broker_protocol::lifecycle::component_replacement_active(&stable)
                .unwrap()
        );

        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&stable).unwrap();
        std::fs::write(
            stable.join("aiguard-chrome-native-host"),
            b"partial replacement",
        )
        .unwrap();
        std::fs::set_permissions(
            stable.join("aiguard-chrome-native-host"),
            std::fs::Permissions::from_mode(0o755),
        )
        .unwrap();
        let prepared = Arc::new(AtomicBool::new(false));
        manage_transient_appimage_at(
            &stable,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            {
                let prepared = Arc::clone(&prepared);
                move |_| {
                    prepared.store(true, Ordering::SeqCst);
                    Ok(AppImageReplacementGuard::unreserved(Vec::new()))
                }
            },
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();
        assert!(prepared.load(Ordering::SeqCst));
        ComponentManifest::load(&stable.join("native-components-v1.json"), VERSION).unwrap();
        assert!(
            !aiguard_native_broker_protocol::lifecycle::component_replacement_active(&stable)
                .unwrap()
        );
    }

    #[test]
    fn repair_registration_and_unregister_removal_are_one_transaction() {
        let (_root, manifest, manifest_path, stable) = fixture();
        let registered = Arc::new(AtomicBool::new(false));
        manage_transient_appimage_at(
            &stable,
            "install",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
            {
                let registered = Arc::clone(&registered);
                move |adapter| {
                    assert!(adapter.is_file());
                    registered.store(true, Ordering::SeqCst);
                    Ok(())
                }
            },
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();

        let (install_entered_tx, install_entered_rx) = mpsc::channel();
        let (release_install_tx, release_install_rx) = mpsc::channel();
        let install_manifest_path = manifest_path.clone();
        let install_stable = stable.clone();
        let install_registered = Arc::clone(&registered);
        let install_thread = std::thread::spawn(move || {
            let manifest = ComponentManifest::load(&install_manifest_path, VERSION).unwrap();
            manage_transient_appimage_at(
                &install_stable,
                "repair",
                TransientAppImageSource {
                    manifest: &manifest,
                    manifest_path: &install_manifest_path,
                    product_version: VERSION,
                },
                |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
                |adapter| {
                    assert!(adapter.is_file());
                    install_entered_tx.send(()).unwrap();
                    release_install_rx.recv().unwrap();
                    install_registered.store(true, Ordering::SeqCst);
                    Ok(())
                },
                |_| Err(()),
                |_| Ok(()),
            )
        });
        install_entered_rx
            .recv_timeout(Duration::from_secs(5))
            .unwrap();

        let (uninstall_started_tx, uninstall_started_rx) = mpsc::channel();
        let (unregister_called_tx, unregister_called_rx) = mpsc::channel();
        let uninstall_manifest_path = manifest_path.clone();
        let uninstall_stable = stable.clone();
        let uninstall_registered = Arc::clone(&registered);
        let uninstall_thread = std::thread::spawn(move || {
            let manifest = ComponentManifest::load(&uninstall_manifest_path, VERSION).unwrap();
            uninstall_started_tx.send(()).unwrap();
            manage_transient_appimage_at(
                &uninstall_stable,
                "uninstall",
                TransientAppImageSource {
                    manifest: &manifest,
                    manifest_path: &uninstall_manifest_path,
                    product_version: VERSION,
                },
                |_| Ok(AppImageReplacementGuard::unreserved(Vec::new())),
                |_| Err(()),
                |adapter| {
                    assert!(adapter.is_file());
                    uninstall_registered.store(false, Ordering::SeqCst);
                    unregister_called_tx.send(()).unwrap();
                    Ok(())
                },
                |_| Ok(()),
            )
        });
        uninstall_started_rx
            .recv_timeout(Duration::from_secs(5))
            .unwrap();
        assert!(
            unregister_called_rx
                .recv_timeout(Duration::from_secs(1))
                .is_err(),
            "unregister ran before repair registration completed"
        );

        release_install_tx.send(()).unwrap();
        install_thread.join().unwrap().unwrap();
        unregister_called_rx
            .recv_timeout(Duration::from_secs(5))
            .unwrap();
        uninstall_thread.join().unwrap().unwrap();

        assert!(!registered.load(Ordering::SeqCst));
        assert!(!stable.exists());
    }

    #[test]
    fn shared_appimage_component_lease_blocks_foreign_repair_until_owner_exits() {
        let (_root, _manifest, _manifest_path, stable) = fixture();
        prepare_stable_root(&stable).unwrap();
        let lease =
            aiguard_native_broker_protocol::lifecycle::AppImageComponentLease::acquire(&stable)
                .unwrap();
        assert!(
            aiguard_native_broker_protocol::lifecycle::AppImageComponentLease::acquire(&stable)
                .is_err()
        );
        drop(lease);
        assert!(
            aiguard_native_broker_protocol::lifecycle::AppImageComponentLease::acquire(&stable)
                .is_ok()
        );
    }

    #[test]
    fn cross_version_appimage_replacement_isolates_and_removes_verified_old_root() {
        let _endpoint = endpoint_test_guard();
        use aiguard_native_broker_protocol::native_host_registration::{
            isolate_appimage_registration_for_replacement_at_for_test, manifest_bytes,
            registration_paths_for_test, RegistrationPlatform,
        };

        let (root, manifest, manifest_path, old_root) = fixture();
        stage_appimage_components_at(&old_root, &manifest, &manifest_path, VERSION).unwrap();
        let policy = manifest.native_host_policy().unwrap();
        let old_adapter = old_root.join("aiguard-chrome-native-host");
        let registration = manifest_bytes(&old_adapter, &policy).unwrap();
        let config_root = root.0.join("config");
        let paths = registration_paths_for_test(
            RegistrationPlatform::Linux,
            PackageShape::AppImage,
            &config_root,
            &old_root,
        )
        .unwrap();
        for path in &paths {
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, &registration).unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o644)).unwrap();
        }
        let new_version = "2.6.0";
        let (new_manifest, new_manifest_path) = fixture_source(&root.0, "new-source", new_version);
        let new_root = old_root.parent().unwrap().join(new_version);
        let new_adapter = new_root.join("aiguard-chrome-native-host");
        let isolated_before_interruption =
            isolate_appimage_registration_for_replacement_at_for_test(
                &new_adapter,
                &policy,
                &config_root,
            )
            .unwrap();
        assert_eq!(isolated_before_interruption.len(), 1);
        assert!(paths.iter().all(|path| !path.exists()));
        let config_for_prepare = config_root.clone();
        let policy_for_prepare = policy.clone();
        let adapter_for_prepare = new_adapter.clone();

        manage_transient_appimage_at(
            &new_root,
            "repair",
            TransientAppImageSource {
                manifest: &new_manifest,
                manifest_path: &new_manifest_path,
                product_version: new_version,
            },
            move |root| {
                prepare_appimage_replacement_at(
                    root,
                    new_version,
                    |_| false,
                    || {
                        let previous = isolate_appimage_registration_for_replacement_at_for_test(
                            &adapter_for_prepare,
                            &policy_for_prepare,
                            &config_for_prepare,
                        )
                        .map_err(|_| ())?;
                        merge_discovered_previous_appimage_roots(
                            root,
                            &policy_for_prepare,
                            previous,
                        )
                    },
                    |previous| {
                        prepare_previous_appimage_roots(previous)?;
                        reserve_appimage_broker_inactive(root)
                    },
                )
            },
            |adapter| {
                assert_eq!(adapter, new_adapter);
                Ok(())
            },
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();

        assert!(!old_root.exists());
        assert!(new_root.join("native-components-v1.json").is_file());
        assert!(paths.iter().all(|path| !path.exists()));
        aiguard_native_broker_protocol::transport::PlatformEndpoint::cleanup_default_runtime_root(
            &new_root,
        )
        .unwrap();
    }

    #[test]
    fn cross_version_isolation_preserves_registration_with_wrong_origin() {
        use aiguard_native_broker_protocol::native_host_registration::{
            isolate_appimage_registration_for_replacement_at_for_test, manifest_bytes,
            registration_paths_for_test, RegistrationPlatform,
        };

        let (root, manifest, manifest_path, old_root) = fixture();
        stage_appimage_components_at(&old_root, &manifest, &manifest_path, VERSION).unwrap();
        let policy = manifest.native_host_policy().unwrap();
        let old_adapter = old_root.join("aiguard-chrome-native-host");
        let mut registration: serde_json::Value =
            serde_json::from_slice(&manifest_bytes(&old_adapter, &policy).unwrap()).unwrap();
        registration["allowed_origins"][0] = serde_json::Value::String(
            "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/".into(),
        );
        let mut registration = serde_json::to_vec_pretty(&registration).unwrap();
        registration.push(b'\n');
        let config_root = root.0.join("config");
        let paths = registration_paths_for_test(
            RegistrationPlatform::Linux,
            PackageShape::AppImage,
            &config_root,
            &old_root,
        )
        .unwrap();
        for path in &paths {
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, &registration).unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o644)).unwrap();
        }
        let new_adapter = old_root
            .parent()
            .unwrap()
            .join("2.6.0")
            .join("aiguard-chrome-native-host");

        assert!(isolate_appimage_registration_for_replacement_at_for_test(
            &new_adapter,
            &policy,
            &config_root,
        )
        .is_err());
        assert!(paths
            .iter()
            .all(|path| std::fs::read(path).unwrap() == registration));
        assert!(old_root.join("native-components-v1.json").is_file());
    }

    #[test]
    fn cross_version_retry_finishes_partial_old_root_removal() {
        let (_root, manifest, manifest_path, old_root) = fixture();
        stage_appimage_components_at(&old_root, &manifest, &manifest_path, VERSION).unwrap();
        let policy = manifest.native_host_policy().unwrap();
        let new_root = old_root.parent().unwrap().join("2.6.0");
        prepare_stable_root(&new_root).unwrap();

        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&old_root).unwrap();
        std::fs::remove_file(old_root.join("desktop")).unwrap();
        std::fs::write(old_root.join("aiguard-native-broker"), b"tampered").unwrap();
        assert!(merge_discovered_previous_appimage_roots(&new_root, &policy, Vec::new()).is_err());
        std::fs::copy(
            manifest_path
                .parent()
                .unwrap()
                .join("aiguard-native-broker"),
            old_root.join("aiguard-native-broker"),
        )
        .unwrap();
        let previous =
            merge_discovered_previous_appimage_roots(&new_root, &policy, Vec::new()).unwrap();
        assert_eq!(previous.len(), 1);
        remove_previous_appimage_root(&previous[0], &policy).unwrap();
        assert!(!old_root.exists());

        let manifestless = new_root.parent().unwrap().join("2.4.0");
        prepare_stable_root(&manifestless).unwrap();
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&manifestless)
            .unwrap();
        drop(StableRepairLock::acquire(&manifestless).unwrap());
        let previous =
            merge_discovered_previous_appimage_roots(&new_root, &policy, Vec::new()).unwrap();
        assert_eq!(previous.len(), 1);
        assert_eq!(previous[0].component_root, manifestless);
        remove_previous_appimage_root(&previous[0], &policy).unwrap();
        assert!(!manifestless.exists());
    }

    #[test]
    fn interrupted_post_registration_retry_removes_previous_root_before_opening_barrier() {
        let (_root, manifest, manifest_path, old_root) = fixture();
        stage_appimage_components_at(&old_root, &manifest, &manifest_path, VERSION).unwrap();
        let unexpected = old_root.join("unexpected-state");
        std::fs::write(&unexpected, b"preserve until positively owned").unwrap();
        let new_root = old_root.parent().unwrap().join("retry-new");
        let previous = PreviousAppImageRegistration {
            component_root: old_root.clone(),
            product_version: VERSION.to_owned(),
        };

        assert!(manage_transient_appimage_at(
            &new_root,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(vec![previous.clone()])),
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .is_err());
        assert!(
            ComponentManifest::load(&new_root.join("native-components-v1.json"), VERSION).is_ok()
        );
        assert!(
            aiguard_native_broker_protocol::lifecycle::component_replacement_active(&new_root)
                .unwrap()
        );
        assert!(old_root.exists());

        std::fs::remove_file(unexpected).unwrap();
        manage_transient_appimage_at(
            &new_root,
            "repair",
            TransientAppImageSource {
                manifest: &manifest,
                manifest_path: &manifest_path,
                product_version: VERSION,
            },
            |_| Ok(AppImageReplacementGuard::unreserved(vec![previous.clone()])),
            |_| Ok(()),
            |_| Err(()),
            |_| Ok(()),
        )
        .unwrap();
        assert!(!old_root.exists());
        assert!(
            !aiguard_native_broker_protocol::lifecycle::component_replacement_active(&new_root)
                .unwrap()
        );
    }

    #[test]
    fn direct_uninstall_recovers_owned_temp_and_manifestless_partial_set() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        std::fs::write(
            stable.join("aiguard-native-broker.aiguard-tmp-4242-0"),
            b"owned interrupted bytes",
        )
        .unwrap();
        std::fs::remove_file(stable.join("native-components-v1.json")).unwrap();
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&stable).unwrap();

        remove_stable_appimage_components_at(&stable, &manifest_path, VERSION).unwrap();
        assert!(!stable.exists());
    }

    #[test]
    fn direct_uninstall_preserves_unknown_extra_and_complete_set_fail_closed() {
        let (_root, manifest, manifest_path, stable) = fixture();
        stage_appimage_components_at(&stable, &manifest, &manifest_path, VERSION).unwrap();
        let unexpected = stable.join("unrelated-state");
        std::fs::write(&unexpected, b"unrelated").unwrap();
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&stable).unwrap();

        assert!(remove_stable_appimage_components_at(&stable, &manifest_path, VERSION).is_err());
        assert!(unexpected.is_file());
        assert!(stable.join("native-components-v1.json").is_file());
        assert!(
            aiguard_native_broker_protocol::lifecycle::component_replacement_active(&stable)
                .unwrap()
        );
    }
}

#[cfg(test)]
mod action_tests {
    #[cfg(windows)]
    use super::windows_package_lock_path;
    use super::{
        action_matches_replacement_state, operation_supports_shape, OrdinaryActionLock,
        PackageShape,
    };

    #[test]
    fn ordinary_actions_cannot_complete_an_unowned_replacement() {
        for operation in ["install", "repair"] {
            assert!(action_matches_replacement_state(operation, false, false));
            assert!(!action_matches_replacement_state(operation, true, false));
        }
        assert!(!action_matches_replacement_state("complete", false, false));
        assert!(!action_matches_replacement_state("complete", true, false));
        assert!(!action_matches_replacement_state("remove", false, false));
        assert!(!action_matches_replacement_state("remove", true, false));
        assert!(action_matches_replacement_state("uninstall", false, false));
        assert!(!action_matches_replacement_state("uninstall", true, false));
        assert!(action_matches_replacement_state("repair", true, true));
        assert!(action_matches_replacement_state("uninstall", true, true));
    }

    #[test]
    fn appimage_drain_is_a_supported_manager_command() {
        assert!(operation_supports_shape("drain", PackageShape::AppImage));
        assert!(!operation_supports_shape("drain", PackageShape::Macos));
        assert!(operation_supports_shape(
            "resume-package",
            PackageShape::Nsis
        ));
        assert!(!operation_supports_shape(
            "resume-package",
            PackageShape::Deb
        ));
    }

    #[test]
    fn ordinary_action_lock_is_exclusive_and_reacquirable() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-manager-action-lock-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir(&root).unwrap();
        let first = OrdinaryActionLock::acquire(&root).unwrap();
        #[cfg(windows)]
        let competing_root = std::env::temp_dir().join(format!(
            "aiguard-manager-action-lock-other-{}",
            std::process::id()
        ));
        #[cfg(not(windows))]
        let competing_root = root.clone();
        #[cfg(windows)]
        {
            let _ = std::fs::remove_dir_all(&competing_root);
            std::fs::create_dir(&competing_root).unwrap();
        }
        assert!(OrdinaryActionLock::acquire(&competing_root).is_err());
        drop(first);
        #[cfg(windows)]
        assert!(!windows_package_lock_path().unwrap().exists());
        assert!(OrdinaryActionLock::acquire(&competing_root).is_ok());
        std::fs::remove_dir(root).unwrap();
        #[cfg(windows)]
        std::fs::remove_dir(competing_root).unwrap();
    }
}
