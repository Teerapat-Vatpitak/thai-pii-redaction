use std::ffi::OsString;
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
