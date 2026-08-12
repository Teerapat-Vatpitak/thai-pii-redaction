#[cfg(target_os = "linux")]
use std::collections::BTreeSet;
#[cfg(target_os = "linux")]
use std::fs::{File, OpenOptions};
#[cfg(target_os = "linux")]
use std::os::fd::AsRawFd;
#[cfg(target_os = "linux")]
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
#[cfg(target_os = "linux")]
use std::path::{Path, PathBuf};
use std::process::ExitCode;
#[cfg(target_os = "linux")]
use std::time::{Duration, Instant};

use aiguard_native_broker_protocol::manifest::ComponentManifest;
#[cfg(target_os = "linux")]
use aiguard_native_broker_protocol::native_host_registration::appimage_component_root;
use aiguard_native_broker_protocol::native_host_registration::{
    install_or_repair, unregister, PackageShape,
};

fn run() -> Result<(), ()> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if arguments.len() != 2 || !matches!(arguments[0].as_str(), "install" | "repair" | "uninstall")
    {
        return Err(());
    }
    let shape = PackageShape::parse(&arguments[1]).map_err(|_| ())?;
    let product_version = aiguard_native_broker_protocol::native_component_build_id();
    let executable = std::env::current_exe().map_err(|_| ())?;
    let install_root = executable.parent().ok_or(())?;
    let manifest_path = install_root.join("native-components-v1.json");
    let manifest = ComponentManifest::load(&manifest_path, product_version).map_err(|_| ())?;
    let package = manifest
        .verify_client_executable(&executable)
        .map_err(|_| ())?;
    if package.allowed_role != "maintenance" {
        return Err(());
    }
    let adapter = manifest
        .verified_client_executable_for_role("extension")
        .map_err(|_| ())?;
    let policy = manifest.native_host_policy().map_err(|_| ())?;
    #[cfg(target_os = "linux")]
    if shape == PackageShape::AppImage && running_from_appimage(&adapter) {
        return manage_transient_appimage(
            arguments[0].as_str(),
            &manifest,
            &manifest_path,
            &policy,
            product_version,
        );
    }
    match arguments[0].as_str() {
        "install" | "repair" => install_or_repair(shape, &adapter, &policy),
        "uninstall" => unregister(shape, &adapter, &policy),
        _ => return Err(()),
    }
    .map_err(|_| ())
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
fn verified_direct_component_layout(
    root: &Path,
    sources: &[PathBuf],
    manifest_path: &Path,
) -> bool {
    let Ok(root) = root.canonicalize() else {
        return false;
    };
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
            && metadata.uid() == unsafe { libc::geteuid() }
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
        || !verified_direct_component_layout(&stable_root, &sources, &stable_manifest)
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
    let source_root = manifest_path.parent().ok_or(())?;
    if !verified_direct_component_layout(source_root, &sources, manifest_path)
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
fn remove_stable_appimage_components_locked(
    stable_root: &Path,
    manifest_path: &Path,
    product_version: &str,
    lock: &StableRepairLock,
) -> Result<(), ()> {
    let stable_manifest = stable_root.join(manifest_path.file_name().ok_or(())?);
    if !stable_manifest.exists() {
        return remove_owned_stable_root(stable_root, lock);
    }
    let source_manifest_bytes = bounded_manifest_bytes(manifest_path)?;
    if source_manifest_bytes != bounded_manifest_bytes(&stable_manifest)? {
        return Err(());
    }
    let installed = ComponentManifest::load(&stable_manifest, product_version).map_err(|_| ())?;
    let sources = verified_component_sources(&installed, &stable_manifest)?;
    if !verified_direct_component_layout(stable_root, &sources, &stable_manifest) {
        return Err(());
    }
    for source in sources {
        if source != stable_manifest {
            std::fs::remove_file(source).map_err(|_| ())?;
        }
    }
    std::fs::remove_file(&stable_manifest).map_err(|_| ())?;
    remove_owned_stable_root(stable_root, lock)
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
fn manage_transient_appimage_at<Install, Unregister>(
    stable_root: &Path,
    operation: &str,
    manifest: &ComponentManifest,
    manifest_path: &Path,
    product_version: &str,
    install_registration: Install,
    unregister_registration: Unregister,
) -> Result<(), ()>
where
    Install: FnOnce(&Path) -> Result<(), ()>,
    Unregister: FnOnce(&Path) -> Result<(), ()>,
{
    if !matches!(operation, "install" | "repair" | "uninstall") {
        return Err(());
    }
    let adapter_name = manifest
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
            let adapter = stage_appimage_components_locked(
                stable_root,
                manifest,
                manifest_path,
                product_version,
            )?;
            install_registration(&adapter)
        }
        "uninstall" => {
            unregister_registration(&stable_adapter)?;
            remove_stable_appimage_components_locked(
                stable_root,
                manifest_path,
                product_version,
                &lock,
            )
        }
        _ => Err(()),
    }
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
    manage_transient_appimage_at(
        &stable_root,
        operation,
        manifest,
        manifest_path,
        product_version,
        |adapter| install_or_repair(PackageShape::AppImage, adapter, policy).map_err(|_| ()),
        |adapter| unregister(PackageShape::AppImage, adapter, policy).map_err(|_| ()),
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
    use std::sync::{mpsc, Arc, Barrier};

    const VERSION: &str = "2.5.0";
    const BUILD_MARKER: &str = "AIGUARD_NATIVE_COMPONENT_BUILD_ID=2.5.0\0";

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

    fn fixture() -> (TempRoot, ComponentManifest, PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!(
            "aiguard-appimage-manager-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let source = root.join("source");
        let stable = root
            .join("data")
            .join("aiguard")
            .join("native-host-v1")
            .join(VERSION);
        std::fs::create_dir_all(&source).unwrap();

        let desktop = format!("fixture-desktop-{BUILD_MARKER}").into_bytes();
        let adapter = format!("fixture-adapter-{BUILD_MARKER}").into_bytes();
        let manager = format!("fixture-manager-{BUILD_MARKER}").into_bytes();
        let broker = format!("fixture-broker-{BUILD_MARKER}").into_bytes();
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
            "product_version": VERSION,
            "broker": {
                "component_id": "native-broker",
                "path": "aiguard-native-broker",
                "sha256": digest(&broker),
                "build_id": VERSION
            },
            "clients": [
                {
                    "component_id": "desktop-shell",
                    "role": "desktop",
                    "path": "desktop",
                    "sha256": digest(&desktop),
                    "build_id": VERSION
                },
                {
                    "component_id": "chrome-native-host",
                    "role": "extension",
                    "path": "aiguard-chrome-native-host",
                    "sha256": digest(&adapter),
                    "build_id": VERSION
                },
                {
                    "component_id": "native-host-manager",
                    "role": "maintenance",
                    "path": "aiguard-native-host-manager",
                    "sha256": digest(&manager),
                    "build_id": VERSION
                }
            ],
            "backend": {
                "component_id": "python-backend",
                "path": "aiguard",
                "sha256": digest(&backend),
                "build_id": VERSION,
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
        let loaded = ComponentManifest::load(&manifest_path, VERSION).unwrap();
        (TempRoot(root), loaded, manifest_path, stable)
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
    fn repair_registration_and_unregister_removal_are_one_transaction() {
        let (_root, manifest, manifest_path, stable) = fixture();
        let registered = Arc::new(AtomicBool::new(false));
        manage_transient_appimage_at(
            &stable,
            "install",
            &manifest,
            &manifest_path,
            VERSION,
            {
                let registered = Arc::clone(&registered);
                move |adapter| {
                    assert!(adapter.is_file());
                    registered.store(true, Ordering::SeqCst);
                    Ok(())
                }
            },
            |_| Err(()),
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
                &manifest,
                &install_manifest_path,
                VERSION,
                |adapter| {
                    assert!(adapter.is_file());
                    install_entered_tx.send(()).unwrap();
                    release_install_rx.recv().unwrap();
                    install_registered.store(true, Ordering::SeqCst);
                    Ok(())
                },
                |_| Err(()),
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
                &manifest,
                &uninstall_manifest_path,
                VERSION,
                |_| Err(()),
                |adapter| {
                    assert!(adapter.is_file());
                    uninstall_registered.store(false, Ordering::SeqCst);
                    unregister_called_tx.send(()).unwrap();
                    Ok(())
                },
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
}
