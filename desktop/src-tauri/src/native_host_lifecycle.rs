use std::ffi::{OsStr, OsString};
use std::path::Path;
use std::process::{Command, Stdio};

#[cfg(target_os = "linux")]
use std::path::PathBuf;

#[cfg(target_os = "linux")]
use aiguard_native_broker_protocol::manifest::ComponentManifest;
#[cfg(target_os = "linux")]
use aiguard_native_broker_protocol::native_host_registration::appimage_component_root;

#[cfg(target_os = "linux")]
#[derive(Clone, Copy)]
enum AppImageBootstrapFailure {
    Desktop,
    Environment,
    Executable,
    Exec,
    Manifest,
    Repair,
    Root,
}

#[cfg(target_os = "linux")]
fn appimage_bootstrap_failure(stage: AppImageBootstrapFailure) -> Option<i32> {
    #[cfg(feature = "package-smoke")]
    {
        use crate::package_smoke::PackageSmokeFailure;

        let stage = match stage {
            AppImageBootstrapFailure::Desktop => PackageSmokeFailure::AppimageDesktop,
            AppImageBootstrapFailure::Environment => PackageSmokeFailure::AppimageEnvironment,
            AppImageBootstrapFailure::Executable => PackageSmokeFailure::AppimageExecutable,
            AppImageBootstrapFailure::Exec => PackageSmokeFailure::AppimageExec,
            AppImageBootstrapFailure::Manifest => PackageSmokeFailure::AppimageManifest,
            AppImageBootstrapFailure::Repair => PackageSmokeFailure::AppimageRepair,
            AppImageBootstrapFailure::Root => PackageSmokeFailure::AppimageRoot,
        };
        crate::package_smoke::desktop_package_smoke_bootstrap_fail(stage);
    }
    #[cfg(not(feature = "package-smoke"))]
    let _ = stage;
    Some(75)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Action {
    Install,
    Repair,
    Uninstall,
}

impl Action {
    fn manager_value(self) -> &'static str {
        match self {
            Self::Install => "install",
            Self::Repair => "repair",
            Self::Uninstall => "uninstall",
        }
    }
}

pub fn requested_action(arguments: impl IntoIterator<Item = OsString>) -> Option<Action> {
    let arguments = arguments.into_iter().collect::<Vec<_>>();
    if arguments.len() != 2 {
        return None;
    }
    match arguments[1].to_str()? {
        "--register-native-host" => Some(Action::Install),
        "--repair-native-host" => Some(Action::Repair),
        "--unregister-native-host" => Some(Action::Uninstall),
        _ => None,
    }
}

fn package_shape(executable: &Path) -> Result<&'static str, ()> {
    #[cfg(windows)]
    {
        let _ = executable;
        Ok("nsis")
    }
    #[cfg(target_os = "macos")]
    {
        let macos = executable.parent().ok_or(())?;
        let contents = macos.parent().ok_or(())?;
        let app = contents.parent().ok_or(())?;
        if macos.file_name() != Some(OsStr::new("MacOS"))
            || contents.file_name() != Some(OsStr::new("Contents"))
            || app.extension() != Some(OsStr::new("app"))
        {
            return Err(());
        }
        Ok("macos")
    }
    #[cfg(target_os = "linux")]
    {
        let image = std::env::var_os("APPIMAGE").map(std::path::PathBuf::from);
        let appdir = std::env::var_os("APPDIR").map(std::path::PathBuf::from);
        if matches!((image, appdir), (Some(image), Some(appdir)) if image.is_absolute() && appdir.is_absolute() && executable.starts_with(&appdir))
        {
            return Ok("appimage");
        }
        if executable == Path::new("/usr/bin/desktop") {
            return Ok("deb");
        }
        Err(())
    }
}

pub fn run(action: Action) -> Result<(), ()> {
    let executable = std::env::current_exe().map_err(|_| ())?;
    let directory = executable.parent().ok_or(())?;
    let shape = package_shape(&executable)?;
    #[cfg(windows)]
    let manager_name = OsStr::new("aiguard-native-host-manager.exe");
    #[cfg(not(windows))]
    let manager_name = OsStr::new("aiguard-native-host-manager");
    let manager = directory.join(manager_name);
    let status = Command::new(manager)
        .args([action.manager_value(), shape])
        .current_dir(directory)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|_| ())?;
    status.success().then_some(()).ok_or(())
}

#[cfg(target_os = "linux")]
fn appimage_stable_manifest(
    executable: &Path,
    appimage: Option<&Path>,
    appdir: Option<&Path>,
    stable_root: &Path,
) -> Option<PathBuf> {
    let (appimage, appdir) = (appimage?, appdir?);
    if !executable.is_absolute()
        || !appimage.is_absolute()
        || !appdir.is_absolute()
        || !stable_root.is_absolute()
        || !executable.starts_with(appdir)
        || stable_root.starts_with(appdir)
    {
        return None;
    }
    Some(stable_root.join("native-components-v1.json"))
}

pub fn stable_appimage_reexec_exit_code() -> Option<i32> {
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::process::CommandExt;

        let appimage = std::env::var_os("APPIMAGE").map(PathBuf::from);
        let appdir = std::env::var_os("APPDIR").map(PathBuf::from);
        let looks_like_appimage = matches!(
            (&appimage, &appdir),
            (Some(image), Some(root)) if image.is_absolute() && root.is_absolute()
        );
        if !looks_like_appimage {
            return None;
        }
        let executable = match std::env::current_exe() {
            Ok(path) => path,
            Err(_) => return appimage_bootstrap_failure(AppImageBootstrapFailure::Executable),
        };
        let appdir_path = appdir.as_deref().expect("checked AppImage root");
        if !executable.starts_with(appdir_path) {
            return None;
        }
        let stable_root = match appimage_component_root() {
            Ok(path) => path,
            Err(_) => return appimage_bootstrap_failure(AppImageBootstrapFailure::Root),
        };
        let stable_manifest = match appimage_stable_manifest(
            &executable,
            appimage.as_deref(),
            appdir.as_deref(),
            &stable_root,
        ) {
            Some(path) => path,
            None => return appimage_bootstrap_failure(AppImageBootstrapFailure::Environment),
        };
        if run(Action::Repair).is_err() {
            return appimage_bootstrap_failure(AppImageBootstrapFailure::Repair);
        }
        let product_version = aiguard_native_broker_protocol::native_component_build_id();
        let manifest = match ComponentManifest::load(&stable_manifest, product_version) {
            Ok(value) => value,
            Err(_) => return appimage_bootstrap_failure(AppImageBootstrapFailure::Manifest),
        };
        let stable_desktop = match manifest.verified_client_executable_for_role("desktop") {
            Ok(path) => path,
            Err(_) => return appimage_bootstrap_failure(AppImageBootstrapFailure::Desktop),
        };
        let stable_root = match stable_root.canonicalize() {
            Ok(path) => path,
            Err(_) => return appimage_bootstrap_failure(AppImageBootstrapFailure::Desktop),
        };
        if stable_desktop.parent() != Some(stable_root.as_path()) || stable_desktop == executable {
            return appimage_bootstrap_failure(AppImageBootstrapFailure::Desktop);
        }
        let arguments = std::env::args_os().skip(1);
        let _error = Command::new(stable_desktop).args(arguments).exec();
        appimage_bootstrap_failure(AppImageBootstrapFailure::Exec)
    }
    #[cfg(not(target_os = "linux"))]
    {
        None
    }
}

#[cfg(test)]
mod tests {
    #[cfg(target_os = "linux")]
    use super::appimage_stable_manifest;
    use super::{requested_action, Action};
    use std::ffi::OsString;
    #[cfg(target_os = "linux")]
    use std::path::Path;

    #[test]
    fn lifecycle_mode_requires_one_exact_flag() {
        assert_eq!(
            requested_action([
                OsString::from("desktop"),
                OsString::from("--register-native-host")
            ]),
            Some(Action::Install)
        );
        assert_eq!(
            requested_action([
                OsString::from("desktop"),
                OsString::from("--repair-native-host")
            ]),
            Some(Action::Repair)
        );
        assert_eq!(
            requested_action([
                OsString::from("desktop"),
                OsString::from("--unregister-native-host")
            ]),
            Some(Action::Uninstall)
        );
        assert_eq!(requested_action([OsString::from("desktop")]), None);
        assert_eq!(
            requested_action([OsString::from("desktop"), OsString::from("--native-host")]),
            None
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn transient_appimage_uses_the_canonical_stable_component_manifest() {
        let transient = Path::new("/tmp/appimage/usr/bin/desktop");
        let appimage = Path::new("/downloads/AI_Guard.AppImage");
        let appdir = Path::new("/tmp/appimage");
        let stable = Path::new("/home/synthetic/.local/share/aiguard/native-host-v1/2.5.0");

        assert_eq!(
            appimage_stable_manifest(transient, Some(appimage), Some(appdir), stable),
            Some(stable.join("native-components-v1.json"))
        );
        assert_eq!(
            appimage_stable_manifest(
                &stable.join("desktop"),
                Some(appimage),
                Some(appdir),
                stable,
            ),
            None
        );
        assert_eq!(
            appimage_stable_manifest(transient, Some(Path::new("relative")), Some(appdir), stable),
            None
        );
        assert_eq!(
            appimage_stable_manifest(transient, Some(appimage), None, stable),
            None
        );
    }
}
