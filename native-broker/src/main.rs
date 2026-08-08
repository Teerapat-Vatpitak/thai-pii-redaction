use std::process::ExitCode;

use aiguard_native_broker_protocol::backend::BackendTimeouts;
use aiguard_native_broker_protocol::broker::{BrokerExit, BrokerRuntime, BrokerRuntimeConfig};
use aiguard_native_broker_protocol::transport::PlatformEndpoint;

fn run() -> Result<BrokerExit, ()> {
    if std::env::args_os().len() != 1 {
        return Err(());
    }
    let product_version = aiguard_native_broker_protocol::native_component_build_id();
    let executable = std::env::current_exe().map_err(|_| ())?;
    let install_root = executable.parent().ok_or(())?;
    let manifest = install_root.join("native-components-v1.json");
    let runtime_root = PlatformEndpoint::default_runtime_root(install_root).map_err(|_| ())?;
    let runtime = BrokerRuntime::start(
        &runtime_root,
        &manifest,
        product_version,
        BackendTimeouts::default(),
        BrokerRuntimeConfig::default(),
    )
    .map_err(|_| ())?;
    runtime.run().map_err(|_| ())
}

fn exit_code(result: Result<BrokerExit, ()>) -> ExitCode {
    match result {
        Ok(BrokerExit::Idle | BrokerExit::Maintenance) => ExitCode::SUCCESS,
        Ok(BrokerExit::BackendFailed | BrokerExit::ForcedShutdown) | Err(()) => ExitCode::from(75),
    }
}

fn main() -> ExitCode {
    exit_code(run())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_runtime_failures_are_nonzero_but_clean_stops_succeed() {
        for exit in [BrokerExit::Idle, BrokerExit::Maintenance] {
            assert_eq!(exit_code(Ok(exit)), ExitCode::SUCCESS);
        }
        for exit in [BrokerExit::BackendFailed, BrokerExit::ForcedShutdown] {
            assert_eq!(exit_code(Ok(exit)), ExitCode::from(75));
        }
        assert_eq!(exit_code(Err(())), ExitCode::from(75));
    }
}
