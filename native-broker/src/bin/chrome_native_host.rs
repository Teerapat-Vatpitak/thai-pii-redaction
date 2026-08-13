use std::ffi::OsString;
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use aiguard_native_broker_protocol::extension_client::ExtensionBrokerClient;
use aiguard_native_broker_protocol::manifest::ComponentManifest;
use aiguard_native_broker_protocol::native_messaging::{
    inspect_browser_parent, process_native_messages, validate_chrome_launch, NativeMessagingSession,
};
use aiguard_native_broker_protocol::transport::PlatformEndpoint;

const EXIT_FRAMING: u8 = 70;
const EXIT_PACKAGE: u8 = 71;
const EXIT_BROWSER_ADMISSION: u8 = 72;
const EXIT_BROKER: u8 = 73;

fn start_component_replacement_monitor(install_root: PathBuf) -> Result<(), u8> {
    std::thread::Builder::new()
        .name("aiguard-component-replacement".to_owned())
        .spawn(move || loop {
            match aiguard_native_broker_protocol::lifecycle::component_replacement_active(
                &install_root,
            ) {
                Ok(false) => std::thread::sleep(Duration::from_millis(25)),
                Ok(true) | Err(_) => std::process::exit(i32::from(EXIT_BROKER)),
            }
        })
        .map(|_| ())
        .map_err(|_| EXIT_BROKER)
}

fn require_component_set_available(install_root: &std::path::Path) -> Result<(), u8> {
    match aiguard_native_broker_protocol::lifecycle::component_replacement_active(install_root) {
        Ok(false) => Ok(()),
        Ok(true) | Err(_) => Err(EXIT_BROKER),
    }
}

fn run() -> Result<(), u8> {
    #[cfg(windows)]
    set_binary_stdio().map_err(|_| EXIT_FRAMING)?;

    let arguments = std::env::args_os().skip(1).collect::<Vec<OsString>>();
    let product_version = aiguard_native_broker_protocol::native_component_build_id();
    let executable = std::env::current_exe().map_err(|_| EXIT_PACKAGE)?;
    let install_root = executable.parent().ok_or(EXIT_PACKAGE)?;
    let manifest_path = install_root.join("native-components-v1.json");
    let manifest =
        ComponentManifest::load(&manifest_path, product_version).map_err(|_| EXIT_PACKAGE)?;
    let package = manifest
        .verify_client_executable(&executable)
        .map_err(|_| EXIT_PACKAGE)?;
    if package.allowed_role != "extension" {
        return Err(EXIT_PACKAGE);
    }
    let policy = manifest.native_host_policy().map_err(|_| EXIT_PACKAGE)?;
    let browser = inspect_browser_parent().map_err(|_| EXIT_BROWSER_ADMISSION)?;
    validate_chrome_launch(&arguments, &policy, &browser, cfg!(windows))
        .map_err(|_| EXIT_BROWSER_ADMISSION)?;
    require_component_set_available(install_root)?;
    start_component_replacement_monitor(install_root.to_path_buf())?;
    // Do not depend on the monitor thread being scheduled before admission.
    require_component_set_available(install_root)?;

    let runtime_root =
        PlatformEndpoint::default_runtime_root(install_root).map_err(|_| EXIT_BROKER)?;
    let broker = ExtensionBrokerClient::connect_or_start(
        &runtime_root,
        &manifest_path,
        product_version,
        Duration::from_secs(15),
    )
    .map_err(|_| EXIT_BROKER)?;
    let mut session =
        NativeMessagingSession::new(broker, product_version).map_err(|_| EXIT_BROKER)?;
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    process_native_messages(stdin.lock(), stdout.lock(), &mut session).map_err(|_| EXIT_FRAMING)
}

#[cfg(windows)]
fn set_binary_stdio() -> Result<(), ()> {
    unsafe extern "C" {
        fn _setmode(file_descriptor: libc::c_int, mode: libc::c_int) -> libc::c_int;
    }
    if unsafe { _setmode(0, libc::O_BINARY) } < 0 || unsafe { _setmode(1, libc::O_BINARY) } < 0 {
        return Err(());
    }
    Ok(())
}

fn main() -> ExitCode {
    std::panic::set_hook(Box::new(|_| {}));
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(code) => {
            let event = match code {
                EXIT_FRAMING => "native_host_framing_failed",
                EXIT_PACKAGE => "native_host_package_failed",
                EXIT_BROWSER_ADMISSION => "native_host_admission_failed",
                EXIT_BROKER => "native_host_broker_failed",
                _ => "native_host_failed",
            };
            eprintln!("{event}");
            ExitCode::from(code)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::require_component_set_available;

    #[test]
    fn synchronous_admission_rejects_replacement_before_monitor_scheduling() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-adapter-maintenance-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir(&root).unwrap();
        assert!(require_component_set_available(&root).is_ok());
        aiguard_native_broker_protocol::lifecycle::begin_component_replacement(&root).unwrap();
        assert!(require_component_set_available(&root).is_err());
        std::fs::remove_file(
            root.join(aiguard_native_broker_protocol::lifecycle::COMPONENT_MAINTENANCE_FILE),
        )
        .unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}
