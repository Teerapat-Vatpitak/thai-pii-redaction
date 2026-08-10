use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

use crate::broker::DesktopCommandError;

#[derive(serde::Serialize)]
pub struct UpdateInfo {
    pub available: bool,
    pub version: String,
    pub notes: String,
}

/// Ask the configured endpoint whether a newer signed release exists.
#[tauri::command]
pub async fn update_check(app: AppHandle) -> Result<UpdateInfo, DesktopCommandError> {
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

/// Download + install the pending update, then restart into the new version.
#[tauri::command]
pub async fn update_install(app: AppHandle) -> Result<(), DesktopCommandError> {
    let updater = app
        .updater()
        .map_err(|_| DesktopCommandError::operation_failed())?;
    if let Some(update) = updater
        .check()
        .await
        .map_err(|_| DesktopCommandError::operation_failed())?
    {
        update
            .download_and_install(|_downloaded, _total| {}, || {})
            .await
            .map_err(|_| DesktopCommandError::operation_failed())?;
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
}
