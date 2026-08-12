use std::path::{Path, PathBuf};
use std::process::Command;

use sha2::{Digest, Sha256};

const ORIGIN: &str = "chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/";
const PRODUCT_VERSION: &str = "2.5.0";

struct TempPackage(PathBuf);

impl Drop for TempPackage {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn digest(path: &Path) -> String {
    let bytes = std::fs::read(path).unwrap();
    hex::encode(Sha256::digest(bytes))
}

fn package(adapter_digest: Option<&str>) -> (TempPackage, PathBuf, PathBuf) {
    let token = format!(
        "aiguard-slice5-binary-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    );
    let root = std::env::temp_dir().join(token);
    std::fs::create_dir(&root).unwrap();
    let source = Path::new(env!("CARGO_BIN_EXE_aiguard-chrome-native-host"));
    let adapter = root.join(if cfg!(windows) {
        "aiguard-chrome-native-host.exe"
    } else {
        "aiguard-chrome-native-host"
    });
    std::fs::copy(source, &adapter).unwrap();
    let broker_name = if cfg!(windows) {
        "broker.exe"
    } else {
        "broker"
    };
    let backend_name = if cfg!(windows) {
        "backend.exe"
    } else {
        "backend"
    };
    std::fs::write(root.join(broker_name), b"synthetic broker fixture").unwrap();
    std::fs::write(root.join(backend_name), b"synthetic backend fixture").unwrap();
    let manifest = serde_json::json!({
        "schema_version": 1,
        "product_version": PRODUCT_VERSION,
        "broker": {
            "component_id": "native-broker",
            "path": broker_name,
            "sha256": digest(&root.join(broker_name)),
            "build_id": PRODUCT_VERSION
        },
        "clients": [{
            "component_id": "chrome-native-host",
            "role": "extension",
            "path": adapter.file_name().unwrap().to_str().unwrap(),
            "sha256": adapter_digest.map(str::to_owned).unwrap_or_else(|| digest(&adapter)),
            "build_id": PRODUCT_VERSION
        }],
        "backend": {
            "component_id": "python-backend",
            "path": backend_name,
            "sha256": digest(&root.join(backend_name)),
            "build_id": PRODUCT_VERSION,
            "arguments": ["--native-broker-backend"]
        },
        "native_host": {
            "name": "th.ac.psu.aiguard.native_host",
            "allowed_origin": ORIGIN,
            "identity_classification": "synthetic_test_only"
        }
    });
    let manifest_path = root.join("native-components-v1.json");
    std::fs::write(
        &manifest_path,
        serde_json::to_vec_pretty(&manifest).unwrap(),
    )
    .unwrap();
    (TempPackage(root), adapter, manifest_path)
}

#[test]
fn standalone_adapter_invocation_is_rejected_with_clean_stdout_and_fixed_stderr() {
    let (_package, adapter, _manifest) = package(None);
    for arguments in [Vec::<&str>::new(), vec![ORIGIN, "pii-sentinel"]] {
        let output = Command::new(&adapter).args(arguments).output().unwrap();
        assert_eq!(output.status.code(), Some(72));
        assert!(output.stdout.is_empty());
        assert_eq!(output.stderr, b"native_host_admission_failed\n");
        assert!(!String::from_utf8_lossy(&output.stderr).contains("pii-sentinel"));
    }
}

#[test]
fn wrong_adapter_digest_fails_before_browser_admission_and_emits_no_values() {
    let (_package, adapter, _manifest) = package(Some(&"0".repeat(64)));
    let output = Command::new(&adapter)
        .args([ORIGIN, "pii-sentinel"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(71));
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, b"native_host_package_failed\n");
    assert!(!String::from_utf8_lossy(&output.stderr).contains("pii-sentinel"));
}
