use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use tauri::AppHandle;

const PACKAGE_SMOKE_EVIDENCE: &str = "desktop-smoke-evidence.json";
const PACKAGE_SMOKE_READY: &str = "desktop-smoke-ready";
const PACKAGE_SMOKE_FAILURE: &str = "desktop-smoke-failure";
const PACKAGE_SMOKE_INVALIDATED: &str = "desktop-smoke-upgrade-invalidated";
const PACKAGE_SMOKE_NATIVE_START: &str = "desktop-smoke-native-start";
const PACKAGE_SMOKE_RELEASE: &str = "desktop-smoke-release";
const PACKAGE_SMOKE_ROOT: &str = "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT";
const PACKAGE_SMOKE_RELEASE_ENV: &str = "AIGUARD_DESKTOP_PACKAGE_SMOKE_RELEASE";
const PACKAGE_SMOKE_RELEASE_WAIT_SECONDS: u64 = 90;
const MAX_METRIC_MS: f64 = 900_000.0;
static MARKER_TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy)]
enum PackageSmokeMarker {
    Evidence,
    Failure,
    Invalidated,
    NativeStart,
    Ready,
}

impl PackageSmokeMarker {
    fn as_str(self) -> &'static str {
        match self {
            Self::Evidence => PACKAGE_SMOKE_EVIDENCE,
            Self::Failure => PACKAGE_SMOKE_FAILURE,
            Self::Invalidated => PACKAGE_SMOKE_INVALIDATED,
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
    AppBuild,
    AppExit,
    AppReady,
    AppRuntime,
    AppimageDesktop,
    AppimageEnvironment,
    AppimageExecutable,
    AppimageExec,
    AppimageManifest,
    AppimageRepair,
    AppimageRoot,
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
    UpgradeInvalidation,
    BootstrapImport,
    BootstrapEval,
    WebviewProcess,
}

impl PackageSmokeFailure {
    fn as_str(self) -> &'static str {
        match self {
            Self::AppBuild => "app_build",
            Self::AppExit => "app_exit",
            Self::AppReady => "app_ready",
            Self::AppRuntime => "app_runtime",
            Self::AppimageDesktop => "appimage_desktop",
            Self::AppimageEnvironment => "appimage_environment",
            Self::AppimageExecutable => "appimage_executable",
            Self::AppimageExec => "appimage_exec",
            Self::AppimageManifest => "appimage_manifest",
            Self::AppimageRepair => "appimage_repair",
            Self::AppimageRoot => "appimage_root",
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
            Self::UpgradeInvalidation => "upgrade_invalidation",
            Self::BootstrapImport => "bootstrap_import",
            Self::BootstrapEval => "bootstrap_eval",
            Self::WebviewProcess => "webview_process",
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

fn open_pending_marker(
    root: &Path,
    marker: PackageSmokeMarker,
) -> Result<(PathBuf, std::fs::File), &'static str> {
    (0..16)
        .find_map(|_| {
            let sequence = MARKER_TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let candidate = root.join(format!(
                ".{}.pending-{}-{sequence}",
                marker.as_str(),
                std::process::id()
            ));
            match std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&candidate)
            {
                Ok(output) => Some(Ok((candidate, output))),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => None,
                Err(_) => Some(Err("operation_failed")),
            }
        })
        .unwrap_or(Err("operation_failed"))
}

fn publish_pending_marker(
    temporary: PathBuf,
    mut output: std::fs::File,
    path: &Path,
    value: &[u8],
) -> Result<(), &'static str> {
    let result = (|| {
        output
            .write_all(value)
            .and_then(|()| output.flush())
            .map_err(|_| "operation_failed")?;
        drop(output);
        std::fs::hard_link(&temporary, path).map_err(|_| "operation_failed")
    })();
    let _ = std::fs::remove_file(temporary);
    result
}

fn write_marker_at(
    root: &Path,
    marker: PackageSmokeMarker,
    value: &[u8],
) -> Result<(), &'static str> {
    let path = root.join(marker.as_str());
    let (temporary, output) = open_pending_marker(root, marker)?;
    publish_pending_marker(temporary, output, &path, value)
}

fn write_marker(marker: PackageSmokeMarker, value: &[u8]) -> Result<(), &'static str> {
    write_marker_at(&smoke_root()?, marker, value)
}

fn wait_for_optional_release_at(
    root: &Path,
    requested: Option<std::ffi::OsString>,
) -> Result<(), &'static str> {
    let Some(requested) = requested else {
        return Ok(());
    };
    let release = root.join(PACKAGE_SMOKE_RELEASE);
    if Path::new(&requested) != release {
        return Err("operation_failed");
    }
    let deadline = std::time::Instant::now()
        .checked_add(std::time::Duration::from_secs(
            PACKAGE_SMOKE_RELEASE_WAIT_SECONDS,
        ))
        .ok_or("operation_failed")?;
    loop {
        match std::fs::symlink_metadata(&release) {
            Ok(metadata)
                if metadata.file_type().is_file()
                    && !metadata.file_type().is_symlink()
                    && !is_reparse(&metadata)
                    && metadata.len() == b"release".len() as u64
                    && std::fs::read(&release).ok().as_deref() == Some(b"release") =>
            {
                return Ok(())
            }
            Ok(_) => return Err("operation_failed"),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err("operation_failed"),
        }
        if std::time::Instant::now() >= deadline {
            return Err("operation_failed");
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
}

fn wait_for_optional_release(root: &Path) -> Result<(), &'static str> {
    wait_for_optional_release_at(root, std::env::var_os(PACKAGE_SMOKE_RELEASE_ENV))
}

fn published_evidence_at(root: &Path) -> bool {
    let path = root.join(PACKAGE_SMOKE_EVIDENCE);
    let Ok(metadata) = std::fs::symlink_metadata(&path) else {
        return false;
    };
    // Python validates the DTO; this only detects completed atomic publication.
    metadata.file_type().is_file()
        && !is_reparse(&metadata)
        && metadata.len() > 0
        && metadata.len() <= 4096
}

fn fixed_marker_at(root: &Path, name: &str, expected: &[u8]) -> bool {
    let path = root.join(name);
    let Ok(metadata) = std::fs::symlink_metadata(&path) else {
        return false;
    };
    metadata.file_type().is_file()
        && !is_reparse(&metadata)
        && metadata.len() == expected.len() as u64
        && std::fs::read(path).ok().as_deref() == Some(expected)
}

fn write_failure_unless_finished_at(root: &Path, stage: PackageSmokeFailure) {
    if !published_evidence_at(root)
        && !fixed_marker_at(root, PACKAGE_SMOKE_INVALIDATED, b"invalidated")
    {
        let _ = write_marker_at(root, PackageSmokeMarker::Failure, stage.as_str().as_bytes());
    }
}

pub fn desktop_package_smoke_native_start() -> Result<(), &'static str> {
    if !requested() {
        return Err("operation_failed");
    }
    write_marker(PackageSmokeMarker::NativeStart, b"started")
}

pub fn desktop_package_smoke_bootstrap_fail(stage: PackageSmokeFailure) {
    if requested() {
        let _ = write_marker(PackageSmokeMarker::Failure, stage.as_str().as_bytes());
    }
}

pub fn desktop_package_smoke_runtime_fail(stage: PackageSmokeFailure) {
    if requested() {
        if let Ok(root) = smoke_root() {
            write_failure_unless_finished_at(&root, stage);
        }
    }
}

async fn shutdown_and_exit(app: AppHandle, code: i32) {
    let cleanup_app = app.clone();
    let _ =
        tauri::async_runtime::spawn_blocking(move || crate::broker::shutdown(&cleanup_app)).await;
    app.exit(code);
}

#[tauri::command]
pub fn desktop_package_smoke_ready() -> Result<bool, &'static str> {
    let root = smoke_root()?;
    let upgrade = std::env::var_os(PACKAGE_SMOKE_RELEASE_ENV).is_some();
    if !requested()
        || write_marker_at(&root, PackageSmokeMarker::Ready, b"ready").is_err()
        || wait_for_optional_release(&root).is_err()
    {
        return Err("operation_failed");
    }
    Ok(upgrade)
}

#[tauri::command]
pub async fn desktop_package_smoke_upgrade_invalidated(app: AppHandle) {
    let succeeded = smoke_root().ok().is_some_and(|root| {
        let release = root.join(PACKAGE_SMOKE_RELEASE);
        requested()
            && std::env::var_os(PACKAGE_SMOKE_RELEASE_ENV)
                .is_some_and(|requested| Path::new(&requested) == release)
            && fixed_marker_at(&root, PACKAGE_SMOKE_READY, b"ready")
            && fixed_marker_at(&root, PACKAGE_SMOKE_RELEASE, b"release")
            && write_marker_at(&root, PackageSmokeMarker::Invalidated, b"invalidated").is_ok()
    });
    shutdown_and_exit(app, if succeeded { 0 } else { 75 }).await;
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
        assert_eq!(PackageSmokeFailure::AppBuild.as_str(), "app_build");
        assert_eq!(PackageSmokeFailure::AppExit.as_str(), "app_exit");
        assert_eq!(PackageSmokeFailure::AppReady.as_str(), "app_ready");
        assert_eq!(PackageSmokeFailure::AppRuntime.as_str(), "app_runtime");
        assert_eq!(
            PackageSmokeFailure::AppimageEnvironment.as_str(),
            "appimage_environment"
        );
        assert_eq!(
            PackageSmokeFailure::AppimageManifest.as_str(),
            "appimage_manifest"
        );
        assert_eq!(PackageSmokeFailure::Sanitize.as_str(), "sanitize");
        assert_eq!(
            PackageSmokeFailure::BootstrapEval.as_str(),
            "bootstrap_eval"
        );
        assert_eq!(
            PackageSmokeFailure::WebviewProcess.as_str(),
            "webview_process"
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
            PackageSmokeMarker::Invalidated,
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
                PACKAGE_SMOKE_INVALIDATED,
                PACKAGE_SMOKE_NATIVE_START,
                PACKAGE_SMOKE_READY,
            ]
            .into_iter()
            .map(std::ffi::OsString::from)
            .collect()
        );
        assert!(!root
            .join(format!(".{PACKAGE_SMOKE_READY}.pending"))
            .exists());

        std::fs::remove_file(root.join(PACKAGE_SMOKE_READY)).unwrap();
        let root = std::sync::Arc::new(root);
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(3));
        let writers = [b"first".as_slice(), b"second".as_slice()].map(|value| {
            let root = std::sync::Arc::clone(&root);
            let barrier = std::sync::Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                write_marker_at(&root, PackageSmokeMarker::Ready, value)
            })
        });
        barrier.wait();
        let results = writers.map(|writer| writer.join().unwrap());
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        let published = std::fs::read(root.join(PACKAGE_SMOKE_READY)).unwrap();
        assert!([b"first".as_slice(), b"second".as_slice()].contains(&published.as_slice()));
        assert!(std::fs::read_dir(&*root).unwrap().all(|entry| !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .contains(".pending-")));

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
            PACKAGE_SMOKE_INVALIDATED,
            PACKAGE_SMOKE_NATIVE_START,
        ] {
            std::fs::remove_file(root.join(name)).unwrap();
        }
        std::fs::remove_dir(&*root).unwrap();
    }

    #[test]
    fn live_upgrade_hold_accepts_only_the_exact_private_release_marker() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-release-{}-{}",
            std::process::id(),
            MARKER_TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&root).unwrap();
        assert_eq!(wait_for_optional_release_at(&root, None), Ok(()));
        assert_eq!(
            wait_for_optional_release_at(&root, Some(root.join("wrong-release").into_os_string())),
            Err("operation_failed")
        );
        let release = root.join(PACKAGE_SMOKE_RELEASE);
        let writer = {
            let release = release.clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(20));
                let pending = release.with_extension(format!(
                    "pending-{}-{}",
                    std::process::id(),
                    MARKER_TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed)
                ));
                let mut output = std::fs::OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(&pending)
                    .unwrap();
                output.write_all(b"rel").unwrap();
                output.flush().unwrap();
                std::thread::sleep(std::time::Duration::from_millis(20));
                output.write_all(b"ease").unwrap();
                output.flush().unwrap();
                drop(output);
                std::fs::hard_link(&pending, &release).unwrap();
                std::fs::remove_file(pending).unwrap();
            })
        };
        wait_for_optional_release_at(&root, Some(release.clone().into_os_string())).unwrap();
        assert!(fixed_marker_at(&root, PACKAGE_SMOKE_RELEASE, b"release"));
        writer.join().unwrap();
        std::fs::remove_file(release).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn marker_writers_remove_only_their_own_pending_file() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-marker-ownership-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let path = root.join(PACKAGE_SMOKE_READY);

        let (first_pending, first_output) =
            open_pending_marker(&root, PackageSmokeMarker::Ready).unwrap();
        let (second_pending, second_output) =
            open_pending_marker(&root, PackageSmokeMarker::Ready).unwrap();
        assert_ne!(first_pending, second_pending);
        assert!(first_pending.exists());
        assert!(second_pending.exists());

        publish_pending_marker(second_pending, second_output, &path, b"second").unwrap();
        assert!(first_pending.exists());
        assert_eq!(
            publish_pending_marker(first_pending.clone(), first_output, &path, b"first"),
            Err("operation_failed")
        );
        assert!(!first_pending.exists());
        assert_eq!(std::fs::read(&path).unwrap(), b"second");
        assert!(std::fs::read_dir(&root).unwrap().all(|entry| !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .contains(".pending-")));

        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(root).unwrap();
    }

    #[test]
    fn marker_contract_has_only_fixed_value_free_names() {
        assert_eq!(PACKAGE_SMOKE_ROOT, "AIGUARD_DESKTOP_PACKAGE_SMOKE_ROOT");
        assert_eq!(PACKAGE_SMOKE_NATIVE_START, "desktop-smoke-native-start");
        assert_eq!(PACKAGE_SMOKE_READY, "desktop-smoke-ready");
        assert_eq!(PACKAGE_SMOKE_EVIDENCE, "desktop-smoke-evidence.json");
        assert_eq!(PACKAGE_SMOKE_FAILURE, "desktop-smoke-failure");
        assert_eq!(
            PACKAGE_SMOKE_INVALIDATED,
            "desktop-smoke-upgrade-invalidated"
        );
    }

    #[test]
    fn runtime_failure_never_overrides_valid_success_evidence() {
        let root = std::env::temp_dir().join(format!(
            "aiguard-package-finish-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();

        write_failure_unless_finished_at(&root, PackageSmokeFailure::AppExit);
        assert_eq!(
            std::fs::read(root.join(PACKAGE_SMOKE_FAILURE)).unwrap(),
            b"app_exit"
        );
        std::fs::remove_file(root.join(PACKAGE_SMOKE_FAILURE)).unwrap();

        let encoded = serde_json::to_vec(&evidence()).unwrap();
        write_marker_at(&root, PackageSmokeMarker::Evidence, &encoded).unwrap();
        assert!(published_evidence_at(&root));
        write_failure_unless_finished_at(&root, PackageSmokeFailure::WebviewProcess);
        assert!(!root.join(PACKAGE_SMOKE_FAILURE).exists());

        std::fs::remove_file(root.join(PACKAGE_SMOKE_EVIDENCE)).unwrap();
        write_marker_at(&root, PackageSmokeMarker::Invalidated, b"invalidated").unwrap();
        write_failure_unless_finished_at(&root, PackageSmokeFailure::AppExit);
        assert!(!root.join(PACKAGE_SMOKE_FAILURE).exists());
        std::fs::remove_file(root.join(PACKAGE_SMOKE_INVALIDATED)).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}
