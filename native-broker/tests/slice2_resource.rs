use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use aiguard_native_broker_protocol::backend::{BackendTimeouts, ManagedBackend};

fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn python_executable(root: &Path) -> PathBuf {
    if let Some(value) = std::env::var_os("AIGUARD_TEST_PYTHON") {
        return PathBuf::from(value);
    }
    #[cfg(windows)]
    let candidate = root.join(".venv/Scripts/python.exe");
    #[cfg(unix)]
    let candidate = root.join(".venv/bin/python");
    assert!(candidate.is_file());
    candidate
}

fn launch_backend() -> ManagedBackend {
    let root = repository_root();
    let arguments = vec![
        root.join("launcher.py").to_string_lossy().into_owned(),
        "--native-broker-backend".to_owned(),
    ];
    ManagedBackend::spawn_synthetic_for_test(
        &python_executable(&root),
        &arguments,
        &root,
        "2.5.0",
        BackendTimeouts {
            startup: Duration::from_secs(20),
            request: Duration::from_secs(2),
            shutdown: Duration::from_secs(5),
        },
    )
    .unwrap()
}

#[test]
fn repeated_backend_boot_and_teardown_do_not_accumulate_broker_resources() {
    let mut warmup = launch_backend();
    warmup.shutdown().unwrap();
    drop(warmup);
    let baseline = resource_count();

    for _ in 0..3 {
        let started = Instant::now();
        let mut backend = launch_backend();
        assert!(started.elapsed() < Duration::from_secs(20));
        assert!(backend.health().unwrap().status_ok);
        backend.shutdown().unwrap();
        drop(backend);
    }

    let final_count = resource_count();
    assert!(
        final_count <= baseline + 1,
        "broker resource count grew across complete boot/teardown cycles"
    );
}

#[cfg(windows)]
fn resource_count() -> u32 {
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, GetProcessHandleCount};

    let mut count = 0;
    // SAFETY: count is a valid output and the pseudo-handle needs no close.
    assert_ne!(
        unsafe { GetProcessHandleCount(GetCurrentProcess(), &mut count) },
        0
    );
    count
}

#[cfg(unix)]
fn resource_count() -> u32 {
    #[cfg(target_os = "linux")]
    let directory = "/proc/self/fd";
    #[cfg(target_os = "macos")]
    let directory = "/dev/fd";
    u32::try_from(std::fs::read_dir(directory).unwrap().count()).unwrap()
}
