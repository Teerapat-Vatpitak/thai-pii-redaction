use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};
use tauri::AppHandle;

const PACKAGE_SMOKE_EVIDENCE: &str = "desktop-smoke-evidence.json";
const PACKAGE_SMOKE_READY: &str = "desktop-smoke-ready";
const PACKAGE_SMOKE_FAILURE: &str = "desktop-smoke-failure";
const PACKAGE_SMOKE_NATIVE_START: &str = "desktop-smoke-native-start";
const PACKAGE_SMOKE_ROOT: &str = "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT";
const MAX_METRIC_MS: f64 = 900_000.0;

#[derive(Clone, Copy)]
enum PackageSmokeMarker {
    Evidence,
    Failure,
    NativeStart,
    Ready,
}

impl PackageSmokeMarker {
    fn as_str(self) -> &'static str {
        match self {
            Self::Evidence => PACKAGE_SMOKE_EVIDENCE,
            Self::Failure => PACKAGE_SMOKE_FAILURE,
            Self::NativeStart => PACKAGE_SMOKE_NATIVE_START,
            Self::Ready => PACKAGE_SMOKE_READY,
        }
    }
}

pub const BOOTSTRAP_SCRIPT: &str = r#"
void import("./package-smoke.js")
  .then(({ runPackageSmoke }) => runPackageSmoke())
  .catch(() => window.__TAURI__?.core?.invoke("desktop_package_smoke_fail", { stage: "bootstrap_import" }));
"#;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PackageSmokeFailure {
    AppReady,
    Health,
    ReadySignal,
    Analyze,
    Sanitize,
    Continuation,
    Copy,
    Reidentify,
    Report,
    Pdf,
    Audit,
    Cleanup,
    Finish,
    BootstrapImport,
    BootstrapEval,
}

impl PackageSmokeFailure {
    fn as_str(self) -> &'static str {
        match self {
            Self::AppReady => "app_ready",
            Self::Health => "health",
            Self::ReadySignal => "ready_signal",
            Self::Analyze => "analyze",
            Self::Sanitize => "sanitize",
            Self::Continuation => "continuation",
            Self::Copy => "copy",
            Self::Reidentify => "reidentify",
            Self::Report => "report",
            Self::Pdf => "pdf",
            Self::Audit => "audit",
            Self::Cleanup => "cleanup",
            Self::Finish => "finish",
            Self::BootstrapImport => "bootstrap_import",
            Self::BootstrapEval => "bootstrap_eval",
        }
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(
    deny_unknown_fields,
    rename_all(serialize = "snake_case", deserialize = "camelCase")
)]
pub struct PackageSmokeEvidence {
    health_connect_ms: f64,
    analyze_ms: f64,
    sanitize_ms: f64,
    continuation_ms: f64,
    copy_ms: f64,
    reidentify_ms: f64,
    report_ms: f64,
    pdf_ms: f64,
    audit_ms: f64,
    cleanup_ms: f64,
    workflow_ms: f64,
}

impl PackageSmokeEvidence {
    fn metrics(&self) -> [f64; 11] {
        [
            self.health_connect_ms,
            self.analyze_ms,
            self.sanitize_ms,
            self.continuation_ms,
            self.copy_ms,
            self.reidentify_ms,
            self.report_ms,
            self.pdf_ms,
            self.audit_ms,
            self.cleanup_ms,
            self.workflow_ms,
        ]
    }

    fn is_bounded(&self) -> bool {
        let metrics = self.metrics();
        metrics
            .iter()
            .all(|value| value.is_finite() && *value >= 0.0 && *value <= MAX_METRIC_MS)
            && metrics[..metrics.len() - 1]
                .iter()
                .all(|value| *value <= self.workflow_ms)
    }
}

pub fn requested() -> bool {
    std::env::var_os("AIGUARD_DESKTOP_PACKAGE_SMOKE").is_some_and(|value| value == "1")
}

#[cfg(windows)]
fn is_reparse(metadata: &std::fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;

    metadata.file_attributes() & 0x400 != 0
}

#[cfg(not(windows))]
fn is_reparse(_metadata: &std::fs::Metadata) -> bool {
    false
}

#[cfg(windows)]
fn is_canonical_input(path: &Path, canonical: &Path) -> bool {
    fn normalized(path: &Path) -> Option<String> {
        let value = path.to_str()?.replace('/', "\\");
        if let Some(value) = value.strip_prefix(r"\\?\UNC\") {
            Some(format!(r"\\{value}").trim_end_matches('\\').to_owned())
        } else {
            Some(
                value
                    .strip_prefix(r"\\?\")
                    .unwrap_or(&value)
                    .trim_end_matches('\\')
                    .to_owned(),
            )
        }
    }

    normalized(path)
        .zip(normalized(canonical))
        .is_some_and(|(path, canonical)| path.eq_ignore_ascii_case(&canonical))
}

#[cfg(not(windows))]
fn is_canonical_input(path: &Path, canonical: &Path) -> bool {
    path.as_os_str() == canonical.as_os_str()
}

fn validated_smoke_root(path: &Path, require_private: bool) -> Result<PathBuf, &'static str> {
    #[cfg(not(unix))]
    let _ = require_private;
    let metadata = std::fs::symlink_metadata(path).map_err(|_| "operation_failed")?;
    let canonical = path.canonicalize().map_err(|_| "operation_failed")?;
    let target_metadata = std::fs::symlink_metadata(&canonical).map_err(|_| "operation_failed")?;
    if !path.is_absolute()
        || !metadata.is_dir()
        || metadata.file_type().is_symlink()
        || is_reparse(&metadata)
        || !is_canonical_input(path, &canonical)
        || !target_metadata.is_dir()
        || target_metadata.file_type().is_symlink()
        || is_reparse(&target_metadata)
    {
        return Err("operation_failed");
    }
    #[cfg(unix)]
    if require_private {
        use std::os::unix::fs::PermissionsExt;

        if target_metadata.permissions().mode() & 0o777 != 0o700 {
            return Err("operation_failed");
        }
    }
    Ok(canonical)
}

fn smoke_root_for(value: Option<std::ffi::OsString>) -> Result<PathBuf, &'static str> {
    match value {
        Some(value) => validated_smoke_root(Path::new(&value), true),
        None => {
            let current = std::env::current_dir().map_err(|_| "operation_failed")?;
            validated_smoke_root(&current, false)
        }
    }
}

fn smoke_root() -> Result<PathBuf, &'static str> {
    smoke_root_for(std::env::var_os(PACKAGE_SMOKE_ROOT))
}

fn write_marker_at(
    root: &Path,
    marker: PackageSmokeMarker,
    value: &[u8],
) -> Result<(), &'static str> {
    let path = root.join(marker.as_str());
    let mut output = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| "operation_failed")?;
    output.write_all(value).map_err(|_| "operation_failed")
}

fn write_marker(marker: PackageSmokeMarker, value: &[u8]) -> Result<(), &'static str> {
    write_marker_at(&smoke_root()?, marker, value)
}

pub fn desktop_package_smoke_native_start() -> Result<(), &'static str> {
    if !requested() {
        return Err("operation_failed");
    }
    write_marker(PackageSmokeMarker::NativeStart, b"started")
}

async fn shutdown_and_exit(app: AppHandle, code: i32) {
    let cleanup_app = app.clone();
    let _ =
        tauri::async_runtime::spawn_blocking(move || crate::broker::shutdown(&cleanup_app)).await;
    app.exit(code);
}

#[tauri::command]
pub fn desktop_package_smoke_ready() -> Result<(), &'static str> {
    if !requested() || write_marker(PackageSmokeMarker::Ready, b"ready").is_err() {
        return Err("operation_failed");
    }
    Ok(())
}

#[tauri::command]
pub async fn desktop_package_smoke_finish(app: AppHandle, evidence: PackageSmokeEvidence) {
    let succeeded = requested()
        && evidence.is_bounded()
        && serde_json::to_vec(&evidence)
            .ok()
            .is_some_and(|encoded| write_marker(PackageSmokeMarker::Evidence, &encoded).is_ok());
    shutdown_and_exit(app, if succeeded { 0 } else { 75 }).await;
}

#[tauri::command]
pub async fn desktop_package_smoke_fail(app: AppHandle, stage: PackageSmokeFailure) {
    if requested() {
        let _ = write_marker(PackageSmokeMarker::Failure, stage.as_str().as_bytes());
    }
    shutdown_and_exit(app, 75).await;
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence() -> PackageSmokeEvidence {
        PackageSmokeEvidence {
            health_connect_ms: 10.0,
            analyze_ms: 20.0,
            sanitize_ms: 30.0,
            continuation_ms: 35.0,
            copy_ms: 10.0,
            reidentify_ms: 25.0,
            report_ms: 40.0,
            pdf_ms: 50.0,
            audit_ms: 15.0,
            cleanup_ms: 10.0,
            workflow_ms: 300.0,
        }
    }

    #[test]
    fn evidence_is_exact_bounded_and_contains_no_payload_field() {
        let evidence = evidence();
        assert!(evidence.is_bounded());
        let value = serde_json::to_value(evidence).unwrap();
        assert_eq!(value.as_object().unwrap().len(), 11);
        assert_eq!(value["health_connect_ms"], 10.0);
        assert!(value.get("text").is_none());
        assert!(value.get("session_id").is_none());
        assert!(value.get("result").is_none());
    }

    #[test]
    fn evidence_rejects_unbounded_or_inconsistent_timings() {
        let mut negative = evidence();
        negative.copy_ms = -1.0;
        assert!(!negative.is_bounded());

        let mut oversized = evidence();
        oversized.pdf_ms = MAX_METRIC_MS + 1.0;
        assert!(!oversized.is_bounded());

        let mut inconsistent = evidence();
        inconsistent.workflow_ms = 1.0;
        assert!(!inconsistent.is_bounded());
    }

    #[test]
    fn bootstrap_imports_only_the_fixed_package_harness() {
        assert!(BOOTSTRAP_SCRIPT.contains("./package-smoke.js"));
        assert!(BOOTSTRAP_SCRIPT.contains("desktop_package_smoke_fail"));
        assert!(BOOTSTRAP_SCRIPT.contains("bootstrap_import"));
        for forbidden in ["fetch(", "http://", "https://", "session_id"] {
            assert!(!BOOTSTRAP_SCRIPT.contains(forbidden));
        }
    }

    #[test]
    fn failure_diagnostics_are_closed_fixed_values() {
        assert_eq!(PackageSmokeFailure::AppReady.as_str(), "app_ready");
        assert_eq!(PackageSmokeFailure::Sanitize.as_str(), "sanitize");
        assert_eq!(
            PackageSmokeFailure::BootstrapEval.as_str(),
            "bootstrap_eval"
        );
    }

    #[test]
    fn private_marker_root_requires_a_canonical_private_directory() {
        let root = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "aiguard-package-smoke-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir(&root);
        std::fs::create_dir(&root).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        }

        assert_eq!(
            validated_smoke_root(&root, true).unwrap(),
            root.canonicalize().unwrap()
        );
        let mut aliased = root.parent().unwrap().as_os_str().to_os_string();
        aliased.push(std::path::MAIN_SEPARATOR.to_string());
        aliased.push(".");
        aliased.push(std::path::MAIN_SEPARATOR.to_string());
        aliased.push(root.file_name().unwrap());
        let aliased = PathBuf::from(aliased);
        assert_eq!(
            validated_smoke_root(&aliased, true),
            Err("operation_failed")
        );
        assert_eq!(
            validated_smoke_root(Path::new("."), true),
            Err("operation_failed")
        );
        assert_eq!(
            validated_smoke_root(Path::new(""), true),
            Err("operation_failed")
        );
        let mut parent_aliased = root.as_os_str().to_os_string();
        parent_aliased.push(std::path::MAIN_SEPARATOR.to_string());
        parent_aliased.push("..");
        parent_aliased.push(std::path::MAIN_SEPARATOR.to_string());
        parent_aliased.push(root.file_name().unwrap());
        let parent_aliased = PathBuf::from(parent_aliased);
        assert_eq!(
            validated_smoke_root(&parent_aliased, true),
            Err("operation_failed")
        );
        let missing = root.with_extension("missing");
        let _ = std::fs::remove_file(&missing);
        let _ = std::fs::remove_dir(&missing);
        assert_eq!(
            validated_smoke_root(&missing, true),
            Err("operation_failed")
        );
        assert_eq!(
            smoke_root_for(Some(missing.as_os_str().to_owned())),
            Err("operation_failed")
        );
        let file = root.with_extension("file");
        let _ = std::fs::remove_file(&file);
        std::fs::write(&file, b"not-a-directory").unwrap();
        assert_eq!(validated_smoke_root(&file, true), Err("operation_failed"));
        std::fs::remove_file(file).unwrap();

        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;

            let alias_parent = std::env::temp_dir().join(format!(
                "aiguard-package-smoke-alias-{}",
                std::process::id()
            ));
            let _ = std::fs::remove_file(&alias_parent);
            symlink(root.parent().unwrap(), &alias_parent).unwrap();
            let through_alias = alias_parent.join(root.file_name().unwrap());
            assert_eq!(
                validated_smoke_root(&through_alias, true),
                Err("operation_failed")
            );
            std::fs::remove_file(alias_parent).unwrap();

            let final_alias = root.with_extension("alias");
            let _ = std::fs::remove_file(&final_alias);
            symlink(&root, &final_alias).unwrap();
            assert_eq!(
                validated_smoke_root(&final_alias, true),
                Err("operation_failed")
            );
            std::fs::remove_file(final_alias).unwrap();
        }

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o755)).unwrap();
            assert_eq!(validated_smoke_root(&root, true), Err("operation_failed"));
        }
        std::fs::remove_dir(&root).unwrap();
    }

    #[test]
    fn fixed_markers_never_overwrite_or_follow_links() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-marker-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        write_marker_at(&root, PackageSmokeMarker::Ready, b"ready").unwrap();
        assert_eq!(
            write_marker_at(&root, PackageSmokeMarker::Ready, b"changed"),
            Err("operation_failed")
        );
        assert_eq!(
            std::fs::read(root.join(PACKAGE_SMOKE_READY)).unwrap(),
            b"ready"
        );
        for marker in [
            PackageSmokeMarker::Evidence,
            PackageSmokeMarker::Failure,
            PackageSmokeMarker::NativeStart,
        ] {
            write_marker_at(&root, marker, b"fixed").unwrap();
        }
        let names = std::fs::read_dir(&root)
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(
            names,
            [
                PACKAGE_SMOKE_EVIDENCE,
                PACKAGE_SMOKE_FAILURE,
                PACKAGE_SMOKE_NATIVE_START,
                PACKAGE_SMOKE_READY,
            ]
            .into_iter()
            .map(std::ffi::OsString::from)
            .collect()
        );

        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;

            let marker = root.join(PACKAGE_SMOKE_READY);
            std::fs::remove_file(&marker).unwrap();
            let target = root.join("target");
            std::fs::write(&target, b"preserve").unwrap();
            symlink(&target, &marker).unwrap();
            assert_eq!(
                write_marker_at(&root, PackageSmokeMarker::Ready, b"changed"),
                Err("operation_failed")
            );
            assert_eq!(std::fs::read(&target).unwrap(), b"preserve");
            std::fs::remove_file(marker).unwrap();
            std::fs::remove_file(target).unwrap();
        }

        #[cfg(not(unix))]
        std::fs::remove_file(root.join(PACKAGE_SMOKE_READY)).unwrap();
        for name in [
            PACKAGE_SMOKE_EVIDENCE,
            PACKAGE_SMOKE_FAILURE,
            PACKAGE_SMOKE_NATIVE_START,
        ] {
            std::fs::remove_file(root.join(name)).unwrap();
        }
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn marker_contract_has_only_fixed_value_free_names() {
        assert_eq!(PACKAGE_SMOKE_ROOT, "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT");
        assert_eq!(PACKAGE_SMOKE_NATIVE_START, "desktop-smoke-native-start");
        assert_eq!(PACKAGE_SMOKE_READY, "desktop-smoke-ready");
        assert_eq!(PACKAGE_SMOKE_EVIDENCE, "desktop-smoke-evidence.json");
        assert_eq!(PACKAGE_SMOKE_FAILURE, "desktop-smoke-failure");
    }
}
