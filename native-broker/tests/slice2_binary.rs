use std::process::Command;

#[test]
fn broker_binary_fails_closed_without_verified_package_state_and_emits_nothing() {
    let binary = env!("CARGO_BIN_EXE_aiguard-native-broker");
    for arguments in [Vec::<&str>::new(), vec!["--unexpected"]] {
        let output = Command::new(binary).args(arguments).output().unwrap();
        assert_eq!(output.status.code(), Some(75));
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
}
