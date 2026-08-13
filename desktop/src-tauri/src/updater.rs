use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

use std::sync::atomic::{AtomicBool, Ordering};

use crate::broker::DesktopCommandError;

static UPDATE_INSTALL_ACTIVE: AtomicBool = AtomicBool::new(false);

struct UpdateInstallGuard;

impl UpdateInstallGuard {
    fn acquire() -> Result<Self, DesktopCommandError> {
        UPDATE_INSTALL_ACTIVE
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map(|_| Self)
            .map_err(|_| DesktopCommandError::operation_failed())
    }
}

impl Drop for UpdateInstallGuard {
    fn drop(&mut self) {
        UPDATE_INSTALL_ACTIVE.store(false, Ordering::Release);
    }
}

#[derive(serde::Serialize)]
pub struct UpdateInfo {
    pub available: bool,
    pub version: String,
    pub notes: String,
}

/// Ask the configured endpoint whether a newer signed release exists.
#[tauri::command]
pub async fn update_check(app: AppHandle) -> Result<UpdateInfo, DesktopCommandError> {
    if !crate::native_host_lifecycle::in_app_update_supported() {
        return Ok(UpdateInfo {
            available: false,
            version: String::new(),
            notes: String::new(),
        });
    }
    let updater = app
        .updater()
        .map_err(|_| DesktopCommandError::operation_failed())?;
    match updater.check().await {
        Ok(Some(update)) => Ok(UpdateInfo {
            available: true,
            version: update.version.clone(),
            notes: update.body.clone().unwrap_or_default(),
        }),
        Ok(None) => Ok(UpdateInfo {
            available: false,
            version: String::new(),
            notes: String::new(),
        }),
        Err(_) => Err(DesktopCommandError::operation_failed()),
    }
}

/// Verify and hand the pending update to the Windows installer.
#[tauri::command]
pub async fn update_install(app: AppHandle) -> Result<(), DesktopCommandError> {
    if !crate::native_host_lifecycle::in_app_update_supported() {
        return Err(DesktopCommandError::operation_failed());
    }
    let _install_guard = UpdateInstallGuard::acquire()?;
    let updater = app
        .updater()
        .map_err(|_| DesktopCommandError::operation_failed())?;
    if let Some(update) = updater
        .check()
        .await
        .map_err(|_| DesktopCommandError::operation_failed())?
    {
        let bytes = update
            .download(|_downloaded, _total| {}, || {})
            .await
            .map_err(|_| DesktopCommandError::operation_failed())?;
        // The updater verifies the downloaded bytes before install. On Windows,
        // the launched NSIS process owns the cross-session package lock and drain.
        if update.install(bytes).is_err() {
            return Err(DesktopCommandError::operation_failed());
        }
        app.restart();
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn update_info_serializes_to_json() {
        let info = UpdateInfo {
            available: false,
            version: String::new(),
            notes: String::new(),
        };
        let json = serde_json::to_string(&info).unwrap();
        assert!(json.contains("\"available\":false"));
    }

    #[test]
    fn concurrent_update_installs_are_rejected() {
        let first = UpdateInstallGuard::acquire().unwrap();
        assert!(UpdateInstallGuard::acquire().is_err());
        drop(first);
        assert!(UpdateInstallGuard::acquire().is_ok());
    }
}
