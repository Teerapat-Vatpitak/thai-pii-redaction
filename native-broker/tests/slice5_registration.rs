use std::path::Path;

use aiguard_native_broker_protocol::manifest::NativeHostPolicy;
use aiguard_native_broker_protocol::native_host_registration::{
    manifest_bytes, registration_paths_for_test, PackageShape, RegistrationPlatform,
    NATIVE_HOST_MANIFEST_NAME,
};
use serde_json::Value;

const ORIGIN: &str = "chrome-extension://efocdbdljgaaiflfleofbjpenncenhee/";
const PRODUCTION_ORIGIN: &str = "chrome-extension://kdjmkknedgmfphpkjhjdhmjadaelgggm/";

fn policy(origin: &str) -> NativeHostPolicy {
    NativeHostPolicy::for_test(
        "th.ac.psu.aiguard.native_host",
        origin,
        "synthetic_test_only",
    )
}

#[test]
fn native_host_manifest_contains_one_exact_origin_and_absolute_adapter() {
    let adapter = if cfg!(windows) {
        Path::new(r"C:\Program Files\AI Guard\aiguard-chrome-native-host.exe")
    } else {
        Path::new("/opt/ai-guard/aiguard-chrome-native-host")
    };
    let bytes = manifest_bytes(adapter, &policy(ORIGIN)).unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        value,
        serde_json::json!({
            "allowed_origins": [ORIGIN],
            "description": "AI Guard Chrome Native Messaging adapter",
            "name": "th.ac.psu.aiguard.native_host",
            "path": adapter.to_str().unwrap(),
            "type": "stdio"
        })
    );
    assert!(!String::from_utf8(bytes).unwrap().contains('*'));
}

#[test]
fn production_identity_generates_one_exact_owner_approved_origin() {
    let identity: Value =
        serde_json::from_str(include_str!("../../config/chrome-extension-identity.json")).unwrap();
    assert_eq!(identity["classification"], "production_owner_approved");
    assert_eq!(identity["origin"], PRODUCTION_ORIGIN);

    let adapter = if cfg!(windows) {
        Path::new(r"C:\Program Files\AI Guard\aiguard-chrome-native-host.exe")
    } else {
        Path::new("/opt/ai-guard/aiguard-chrome-native-host")
    };
    let policy = NativeHostPolicy::for_test(
        "th.ac.psu.aiguard.native_host",
        PRODUCTION_ORIGIN,
        "production_owner_approved",
    );
    let value: Value = serde_json::from_slice(&manifest_bytes(adapter, &policy).unwrap()).unwrap();

    assert_eq!(
        value["allowed_origins"],
        serde_json::json!([PRODUCTION_ORIGIN])
    );
    assert_eq!(value["name"], "th.ac.psu.aiguard.native_host");
    assert!(!value.to_string().contains(ORIGIN));
    assert!(!value.to_string().contains('*'));
}

#[test]
fn registration_layouts_are_distinct_and_product_owned() {
    let install = if cfg!(windows) {
        Path::new(r"C:\Program Files\AI Guard")
    } else {
        Path::new("/opt/ai-guard")
    };
    let windows_root = if cfg!(windows) {
        Path::new(r"C:\Program Files\AI Guard")
    } else {
        Path::new("/windows")
    };
    let windows = registration_paths_for_test(
        RegistrationPlatform::Windows,
        PackageShape::Nsis,
        windows_root,
        install,
    )
    .unwrap();
    assert_eq!(windows, [install.join(NATIVE_HOST_MANIFEST_NAME)]);

    let macos_root = if cfg!(windows) {
        Path::new(r"C:\Users\synthetic\Library\Application Support")
    } else {
        Path::new("/Users/synthetic/Library/Application Support")
    };
    let macos = registration_paths_for_test(
        RegistrationPlatform::Macos,
        PackageShape::Macos,
        macos_root,
        install,
    )
    .unwrap();
    assert_eq!(macos.len(), 3);
    assert!(macos
        .iter()
        .any(|path| path.to_string_lossy().contains("ChromeForTesting")));
    assert!(macos
        .iter()
        .any(|path| path.components().any(|part| part.as_os_str() == "Chrome")));
    assert!(macos
        .iter()
        .any(|path| path.components().any(|part| part.as_os_str() == "Chromium")));

    let deb_root = if cfg!(windows) {
        Path::new(r"C:\synthetic\etc")
    } else {
        Path::new("/etc")
    };
    let appimage_root = if cfg!(windows) {
        Path::new(r"C:\Users\synthetic\.config")
    } else {
        Path::new("/home/synthetic/.config")
    };
    let deb = registration_paths_for_test(
        RegistrationPlatform::Linux,
        PackageShape::Deb,
        deb_root,
        install,
    )
    .unwrap();
    let appimage = registration_paths_for_test(
        RegistrationPlatform::Linux,
        PackageShape::AppImage,
        appimage_root,
        install,
    )
    .unwrap();
    assert!(deb.iter().all(|path| path.starts_with(deb_root)));
    assert_eq!(deb.len(), 3);
    assert!(deb
        .iter()
        .any(|path| path.to_string_lossy().contains("chrome_for_testing")));
    assert!(appimage.iter().all(|path| path.starts_with(appimage_root)));
    assert_eq!(appimage.len(), 3);
    assert!(appimage
        .iter()
        .any(|path| path.to_string_lossy().contains("google-chrome-for-testing")));
    assert_ne!(deb, appimage);
    for paths in [windows, macos, deb, appimage] {
        assert!(paths
            .iter()
            .all(|path| path.file_name().unwrap() == NATIVE_HOST_MANIFEST_NAME));
    }
}

#[test]
fn wrong_platform_shape_and_relative_adapter_fail_closed() {
    assert!(registration_paths_for_test(
        RegistrationPlatform::Linux,
        PackageShape::Nsis,
        Path::new("/tmp"),
        Path::new("/opt/ai-guard"),
    )
    .is_err());
    assert!(manifest_bytes(Path::new("relative-adapter"), &policy(ORIGIN)).is_err());
    assert!(manifest_bytes(
        Path::new("/opt/ai-guard/aiguard-chrome-native-host"),
        &NativeHostPolicy::for_test("wrong.host", ORIGIN, "synthetic_test_only"),
    )
    .is_err());
}
