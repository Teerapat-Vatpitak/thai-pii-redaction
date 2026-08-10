use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, TryLockError};
use std::time::Duration;

use aiguard_native_broker_protocol::desktop_client::{
    DesktopBrokerClient, DesktopClientAbortHandle, DesktopClientError, DesktopScopeKind,
};
use aiguard_native_broker_protocol::safe_error_code;
use aiguard_native_broker_protocol::transport::PlatformEndpoint;
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State, WebviewWindow};
use tauri_plugin_clipboard_manager::ClipboardExt;

const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const KEEPALIVE_INTERVAL: Duration = Duration::from_secs(2);
const AUTHORITY_INVALIDATED_EVENT: &str = "desktop-authority-invalidated";

fn keepalive_requires_disconnect(code: &str, connection_invalidated: bool) -> bool {
    connection_invalidated || code != "broker_busy"
}

#[derive(Clone)]
pub struct DesktopBrokerState {
    inner: Arc<Mutex<BrokerManager>>,
    lifecycle: Arc<DesktopLifecycle>,
}

impl Default for DesktopBrokerState {
    fn default() -> Self {
        let lifecycle = Arc::new(DesktopLifecycle::default());
        Self {
            inner: Arc::new(Mutex::new(BrokerManager::with_lifecycle(Arc::clone(
                &lifecycle,
            )))),
            lifecycle,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum OperationOwner {
    Health,
    Hotkey,
    Window { label: String, generation: u64 },
}

#[derive(Default)]
struct DesktopLifecycle {
    terminal: AtomicBool,
    operation_active: AtomicBool,
    active_owner: Mutex<Option<OperationOwner>>,
    window_generations: Mutex<BTreeMap<String, u64>>,
    abort_handle: Mutex<Option<DesktopClientAbortHandle>>,
    pending_window_cleanups: Mutex<BTreeMap<String, u64>>,
    cleanup_worker_active: AtomicBool,
    publication_gate: Mutex<()>,
}

impl DesktopLifecycle {
    fn begin(
        self: &Arc<Self>,
        owner: OperationOwner,
    ) -> Result<OperationPermit, DesktopCommandError> {
        if self.terminal.load(Ordering::Acquire) {
            return Err(DesktopCommandError::fixed("broker_unavailable", true, true));
        }
        if self
            .operation_active
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(DesktopCommandError::fixed("broker_busy", false, false));
        }
        *lock_recover(&self.active_owner) = Some(owner);
        let permit = OperationPermit {
            _lease: Arc::new(OperationLease {
                lifecycle: Arc::clone(self),
            }),
        };
        if self.terminal.load(Ordering::Acquire) {
            drop(permit);
            return Err(DesktopCommandError::fixed("broker_unavailable", true, true));
        }
        Ok(permit)
    }

    fn window_generation(&self, label: &str) -> u64 {
        *lock_recover(&self.window_generations)
            .entry(label.to_owned())
            .or_default()
    }

    fn invalidate_window(&self, label: &str) -> u64 {
        let _publication = lock_recover(&self.publication_gate);
        let mut generations = lock_recover(&self.window_generations);
        let generation = generations.entry(label.to_owned()).or_default();
        *generation = generation.saturating_add(1);
        *generation
    }

    fn window_is_current(&self, label: &str, generation: u64) -> bool {
        self.window_generation(label) == generation && !self.terminal.load(Ordering::Acquire)
    }

    fn publish_if_window_current<T, F>(&self, label: &str, generation: u64, publish: F) -> Option<T>
    where
        F: FnOnce() -> T,
    {
        let _publication = lock_recover(&self.publication_gate);
        let generations = lock_recover(&self.window_generations);
        if self.terminal.load(Ordering::Acquire)
            || generations.get(label).copied().unwrap_or_default() != generation
        {
            return None;
        }
        Some(publish())
    }

    fn publish_if_running<T, F>(&self, publish: F) -> Option<T>
    where
        F: FnOnce() -> T,
    {
        let _publication = lock_recover(&self.publication_gate);
        if self.terminal.load(Ordering::Acquire) {
            return None;
        }
        Some(publish())
    }

    fn abort_window_operation(&self, label: &str, replacement_generation: u64) -> bool {
        let active_owner = lock_recover(&self.active_owner);
        let matches = matches!(
            active_owner.as_ref(),
            Some(OperationOwner::Window {
                label: active_label,
                generation,
            }) if active_label == label && *generation < replacement_generation
        );
        if matches {
            self.abort_connection();
        }
        matches
    }

    fn install_abort_handle_if_running(&self, handle: DesktopClientAbortHandle) -> bool {
        let _publication = lock_recover(&self.publication_gate);
        if self.terminal.load(Ordering::Acquire) {
            return false;
        }
        *lock_recover(&self.abort_handle) = Some(handle);
        true
    }

    fn clear_abort_handle(&self) {
        lock_recover(&self.abort_handle).take();
    }

    fn abort_connection(&self) {
        if let Some(handle) = lock_recover(&self.abort_handle).as_ref() {
            handle.abort();
        }
    }

    fn stop(&self) {
        let _publication = lock_recover(&self.publication_gate);
        self.terminal.store(true, Ordering::Release);
        self.abort_connection();
    }
}

#[derive(Clone)]
struct OperationPermit {
    _lease: Arc<OperationLease>,
}

struct OperationLease {
    lifecycle: Arc<DesktopLifecycle>,
}

impl std::fmt::Debug for OperationPermit {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("OperationPermit").finish()
    }
}

impl Drop for OperationLease {
    fn drop(&mut self) {
        lock_recover(&self.lifecycle.active_owner).take();
        self.lifecycle
            .operation_active
            .store(false, Ordering::Release);
    }
}

#[derive(Clone)]
struct UiScope {
    id: String,
    generation: u64,
}

struct BrokerManager {
    client: Option<DesktopBrokerClient>,
    ui_scopes: BTreeMap<String, UiScope>,
    hotkey_scope: Option<String>,
    lifecycle: Arc<DesktopLifecycle>,
}

impl Default for BrokerManager {
    fn default() -> Self {
        Self::with_lifecycle(Arc::new(DesktopLifecycle::default()))
    }
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopCommandError {
    code: String,
    session_invalidated: bool,
    restart_required: bool,
}

#[derive(Serialize)]
pub struct DesktopCommandResult {
    operation: &'static str,
    result: Value,
}

impl DesktopCommandResult {
    fn new(operation: &'static str, result: Value) -> Self {
        Self { operation, result }
    }
}

impl DesktopCommandError {
    fn fixed(code: &str, session_invalidated: bool, restart_required: bool) -> Self {
        Self {
            code: safe_error_code(code).to_owned(),
            session_invalidated,
            restart_required,
        }
    }

    pub fn code(&self) -> &str {
        &self.code
    }

    pub fn session_invalidated(&self) -> bool {
        self.session_invalidated
    }

    pub(crate) fn operation_failed() -> Self {
        Self::fixed("operation_failed", false, false)
    }
}

impl From<DesktopClientError> for DesktopCommandError {
    fn from(error: DesktopClientError) -> Self {
        let restart_required = error.connection_invalidated()
            || matches!(
                error.code(),
                "broker_incompatible" | "broker_unauthorized" | "broker_unavailable"
            );
        Self::fixed(error.code(), error.session_invalidated(), restart_required)
    }
}

impl BrokerManager {
    fn with_lifecycle(lifecycle: Arc<DesktopLifecycle>) -> Self {
        Self {
            client: None,
            ui_scopes: BTreeMap::new(),
            hotkey_scope: None,
            lifecycle,
        }
    }

    fn connect(&mut self) -> Result<(), DesktopCommandError> {
        if self.client.is_some() {
            return Ok(());
        }
        if self.lifecycle.terminal.load(Ordering::Acquire) {
            return Err(DesktopCommandError::fixed("broker_unavailable", true, true));
        }
        let (endpoint_root, manifest_path) = component_paths()?;
        let client = DesktopBrokerClient::connect_or_start(
            &endpoint_root,
            &manifest_path,
            aiguard_native_broker_protocol::native_component_build_id(),
            STARTUP_TIMEOUT,
        )
        .map_err(DesktopCommandError::from)?;
        let abort_handle = client.abort_handle().map_err(DesktopCommandError::from)?;
        if !self.lifecycle.install_abort_handle_if_running(abort_handle) {
            return Err(DesktopCommandError::fixed("broker_unavailable", true, true));
        }
        self.client = Some(client);
        Ok(())
    }

    fn health(&mut self) -> Result<Value, DesktopCommandError> {
        self.connect()?;
        let result = self
            .client
            .as_mut()
            .expect("connected client")
            .health()
            .map(|()| serde_json::json!({"status": "ok"}));
        self.finish(result)
    }

    fn keepalive(&mut self) -> bool {
        let Some(client) = self.client.as_mut() else {
            return false;
        };
        if let Err(error) = client.health() {
            if keepalive_requires_disconnect(error.code(), error.connection_invalidated()) {
                self.disconnect();
                return true;
            }
        }
        false
    }

    fn with_ui_scope<F>(
        &mut self,
        window_label: &str,
        generation: u64,
        operation: F,
    ) -> Result<Value, DesktopCommandError>
    where
        F: FnOnce(&mut DesktopBrokerClient, &str) -> Result<Value, DesktopClientError>,
    {
        if !self.lifecycle.window_is_current(window_label, generation) {
            return Err(DesktopCommandError::fixed(
                "session_unavailable",
                true,
                false,
            ));
        }
        self.connect()?;
        if self
            .ui_scopes
            .get(window_label)
            .is_some_and(|scope| scope.generation > generation)
        {
            return Err(DesktopCommandError::fixed(
                "session_unavailable",
                true,
                false,
            ));
        }
        if self
            .ui_scopes
            .get(window_label)
            .is_some_and(|scope| scope.generation < generation)
        {
            let stale = self.ui_scopes.remove(window_label).expect("checked scope");
            if self
                .client
                .as_mut()
                .is_none_or(|client| client.close_scope(&stale.id).is_err())
            {
                return Err(self.fail_closed_cleanup("operation_failed"));
            }
        }
        if !self.ui_scopes.contains_key(window_label) {
            let opened = self
                .client
                .as_mut()
                .expect("connected client")
                .open_scope(DesktopScopeKind::Ui);
            let scope = self.finish(opened)?;
            if !self.lifecycle.window_is_current(window_label, generation) {
                let confirmed = self
                    .client
                    .as_mut()
                    .is_some_and(|client| client.close_scope(&scope).is_ok());
                if !confirmed {
                    self.disconnect();
                }
                return Err(DesktopCommandError::fixed(
                    "session_unavailable",
                    true,
                    !confirmed,
                ));
            }
            self.ui_scopes.insert(
                window_label.to_owned(),
                UiScope {
                    id: scope,
                    generation,
                },
            );
        }
        let scope = self
            .ui_scopes
            .get(window_label)
            .expect("opened UI scope")
            .id
            .clone();
        let result = operation(self.client.as_mut().expect("connected client"), &scope);
        self.finish_ui_operation(window_label, result)
    }

    fn with_hotkey_scope<F>(&mut self, operation: F) -> Result<Value, DesktopCommandError>
    where
        F: FnOnce(&mut DesktopBrokerClient, &str) -> Result<Value, DesktopClientError>,
    {
        self.connect()?;
        if self.hotkey_scope.is_none() {
            let opened = self
                .client
                .as_mut()
                .expect("connected client")
                .open_scope(DesktopScopeKind::Hotkey);
            self.hotkey_scope = Some(self.finish(opened)?);
        }
        let scope = self.hotkey_scope.as_deref().expect("opened hotkey scope");
        let result = operation(self.client.as_mut().expect("connected client"), scope);
        self.finish_hotkey_operation(result)
    }

    fn reset_ui_scope(
        &mut self,
        window_label: &str,
        generation: u64,
    ) -> Result<Value, DesktopCommandError> {
        let Some(scope) = self.take_ui_scope_generation(window_label, generation) else {
            return Err(DesktopCommandError::fixed(
                "session_unavailable",
                true,
                false,
            ));
        };
        let Some(client) = self.client.as_mut() else {
            return Err(DesktopCommandError::fixed("broker_unavailable", true, true));
        };
        match client.close_scope(&scope.id) {
            Ok(()) => Ok(serde_json::json!({"closed": true})),
            Err(error) => Err(self.fail_closed_cleanup(error.code())),
        }
    }

    fn dispose_ui_session(
        &mut self,
        window_label: &str,
        generation: u64,
        session_id: &str,
    ) -> Result<Value, DesktopCommandError> {
        let result = self.with_ui_scope(window_label, generation, |client, scope| {
            client
                .dispose_session(scope, session_id)
                .map(|()| serde_json::json!({"disposed": true}))
        });
        match result {
            Ok(value) => Ok(value),
            Err(error) => Err(self.fail_closed_cleanup(error.code())),
        }
    }

    fn reset_hotkey_scope(&mut self) {
        let Some(scope) = self.hotkey_scope.take() else {
            return;
        };
        let result = self
            .client
            .as_mut()
            .map(|client| client.close_scope(&scope));
        if !matches!(result, Some(Ok(()))) {
            self.disconnect();
        }
    }

    fn close_window_before(&mut self, window_label: &str, generation: u64) -> bool {
        if let Some(scope) = self.take_ui_scope_before(window_label, generation) {
            let result = self
                .client
                .as_mut()
                .map(|client| client.close_scope(&scope.id));
            if !matches!(result, Some(Ok(()))) {
                self.disconnect();
                return true;
            }
        }
        false
    }

    #[cfg(test)]
    fn take_ui_scope(&mut self, window_label: &str) -> Option<UiScope> {
        self.ui_scopes.remove(window_label)
    }

    fn take_ui_scope_generation(&mut self, window_label: &str, generation: u64) -> Option<UiScope> {
        if self
            .ui_scopes
            .get(window_label)
            .is_some_and(|scope| scope.generation == generation)
        {
            return self.ui_scopes.remove(window_label);
        }
        None
    }

    fn take_ui_scope_before(&mut self, window_label: &str, generation: u64) -> Option<UiScope> {
        if self
            .ui_scopes
            .get(window_label)
            .is_some_and(|scope| scope.generation < generation)
        {
            return self.ui_scopes.remove(window_label);
        }
        None
    }

    fn shutdown(&mut self) {
        let ui_scopes = std::mem::take(&mut self.ui_scopes);
        let hotkey_scope = self.hotkey_scope.take();
        let mut confirmed = true;
        if let Some(client) = self.client.as_mut() {
            for scope in ui_scopes.values() {
                confirmed &= client.close_scope(&scope.id).is_ok();
            }
            if let Some(scope) = hotkey_scope.as_ref() {
                confirmed &= client.close_scope(scope).is_ok();
            }
        } else if !ui_scopes.is_empty() || hotkey_scope.is_some() {
            confirmed = false;
        }
        if !confirmed {
            self.disconnect();
        } else if let Some(client) = self.client.as_mut() {
            client.disconnect();
        }
        self.client = None;
        self.lifecycle.clear_abort_handle();
    }

    fn finish_ui_operation<T>(
        &mut self,
        window_label: &str,
        result: Result<T, DesktopClientError>,
    ) -> Result<T, DesktopCommandError> {
        match result {
            Ok(value) => Ok(value),
            Err(error) if error.connection_invalidated() => self.finish(Err(error)),
            Err(error) if error.session_invalidated() => {
                let projected = DesktopCommandError::from(error);
                let generation = self.lifecycle.window_generation(window_label);
                if let Some(scope) = self.take_ui_scope_generation(window_label, generation) {
                    let confirmed = self
                        .client
                        .as_mut()
                        .is_some_and(|client| client.close_scope(&scope.id).is_ok());
                    if !confirmed {
                        self.disconnect();
                        return Err(DesktopCommandError::fixed(projected.code(), true, true));
                    }
                }
                Err(projected)
            }
            Err(error) => Err(error.into()),
        }
    }

    fn finish_hotkey_operation<T>(
        &mut self,
        result: Result<T, DesktopClientError>,
    ) -> Result<T, DesktopCommandError> {
        match result {
            Ok(value) => Ok(value),
            Err(error) if error.connection_invalidated() => self.finish(Err(error)),
            Err(error) if error.session_invalidated() => {
                let projected = DesktopCommandError::from(error);
                self.reset_hotkey_scope();
                Err(projected)
            }
            Err(error) => Err(error.into()),
        }
    }

    fn finish<T>(
        &mut self,
        result: Result<T, DesktopClientError>,
    ) -> Result<T, DesktopCommandError> {
        match result {
            Ok(value) => Ok(value),
            Err(error) => {
                if error.connection_invalidated() {
                    self.ui_scopes.clear();
                    self.hotkey_scope = None;
                    self.client = None;
                    self.lifecycle.clear_abort_handle();
                }
                Err(error.into())
            }
        }
    }

    fn disconnect(&mut self) {
        self.ui_scopes.clear();
        self.hotkey_scope = None;
        if let Some(client) = self.client.as_mut() {
            client.disconnect();
        }
        self.client = None;
        self.lifecycle.clear_abort_handle();
    }

    fn fail_closed_cleanup(&mut self, code: &str) -> DesktopCommandError {
        let projected = DesktopCommandError::fixed(code, true, true);
        self.disconnect();
        projected
    }
}

fn lock_recover<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    match mutex.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

fn lock_manager_for_operation(
    inner: &Mutex<BrokerManager>,
) -> Result<MutexGuard<'_, BrokerManager>, DesktopCommandError> {
    match inner.lock() {
        Ok(manager) => Ok(manager),
        Err(poisoned) => {
            let mut manager = poisoned.into_inner();
            manager.disconnect();
            inner.clear_poison();
            Err(DesktopCommandError::fixed("operation_failed", true, true))
        }
    }
}

fn lock_manager_for_cleanup(inner: &Mutex<BrokerManager>) -> (MutexGuard<'_, BrokerManager>, bool) {
    match inner.lock() {
        Ok(manager) => (manager, false),
        Err(poisoned) => {
            let mut manager = poisoned.into_inner();
            manager.disconnect();
            inner.clear_poison();
            (manager, true)
        }
    }
}

fn emit_authority_invalidated(app: &AppHandle) {
    if let Some(state) = app.try_state::<DesktopBrokerState>() {
        state.lifecycle.stop();
    }
    crate::hotkey::invalidate_session(app);
    let _ = app.emit(AUTHORITY_INVALIDATED_EVENT, ());
}

fn component_paths() -> Result<(PathBuf, PathBuf), DesktopCommandError> {
    let executable = std::env::current_exe()
        .map_err(|_| DesktopCommandError::fixed("broker_unavailable", false, true))?;
    let install_root = executable
        .parent()
        .ok_or_else(|| DesktopCommandError::fixed("broker_unavailable", false, true))?;
    let manifest_path = install_root.join("native-components-v1.json");
    let endpoint_root = PlatformEndpoint::default_runtime_root(install_root)
        .map_err(|error| DesktopCommandError::fixed(error.code(), false, true))?;
    Ok((endpoint_root, manifest_path))
}

fn reidentify_confirms_copy_authority(result: &Value) -> bool {
    let Some(result) = result.as_object() else {
        return false;
    };
    result.len() == 4
        && result["restored_text"].is_string()
        && result["replaced_count"].as_u64().is_some()
        && result["leftover_count"].as_u64() == Some(0)
        && result["warnings"]
            .as_array()
            .is_some_and(|warnings| warnings.is_empty())
}

async fn run_blocking<F>(
    app: AppHandle,
    state: State<'_, DesktopBrokerState>,
    owner: OperationOwner,
    operation: F,
) -> Result<Value, DesktopCommandError>
where
    F: FnOnce(&mut BrokerManager) -> Result<Value, DesktopCommandError> + Send + 'static,
{
    let inner = Arc::clone(&state.inner);
    let lifecycle = Arc::clone(&state.lifecycle);
    let verify_owner = owner.clone();
    let permit = lifecycle.begin(owner)?;
    let worker_lifecycle = Arc::clone(&lifecycle);
    let worker_permit = permit.clone();
    let joined = tauri::async_runtime::spawn_blocking(move || {
        let _permit = worker_permit;
        if let OperationOwner::Window { label, generation } = &verify_owner {
            if !worker_lifecycle.window_is_current(label, *generation) {
                return Err(DesktopCommandError::fixed(
                    "session_unavailable",
                    true,
                    false,
                ));
            }
        }
        let mut manager = lock_manager_for_operation(&inner)?;
        operation(&mut manager)
    })
    .await;
    let result = match joined {
        Ok(result) => result,
        Err(_) => {
            lifecycle.abort_connection();
            Err(DesktopCommandError::fixed("operation_failed", true, true))
        }
    };
    if result.as_ref().is_err_and(|error| error.restart_required) {
        emit_authority_invalidated(&app);
    }
    drop(permit);
    result
}

async fn run_ui<F>(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    operation_name: &'static str,
    operation: F,
) -> Result<DesktopCommandResult, DesktopCommandError>
where
    F: FnOnce(&mut DesktopBrokerClient, &str) -> Result<Value, DesktopClientError> + Send + 'static,
{
    let label = window.label().to_owned();
    let generation = state.lifecycle.window_generation(&label);
    let owner = OperationOwner::Window {
        label: label.clone(),
        generation,
    };
    let app = window.app_handle().clone();
    run_blocking(app, state, owner, move |manager| {
        manager.with_ui_scope(&label, generation, operation)
    })
    .await
    .map(|result| DesktopCommandResult::new(operation_name, result))
}

#[tauri::command]
pub async fn desktop_health(
    app: AppHandle,
    state: State<'_, DesktopBrokerState>,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_blocking(app, state, OperationOwner::Health, BrokerManager::health)
        .await
        .map(|result| DesktopCommandResult::new("broker_health", result))
}

#[tauri::command]
pub async fn desktop_analyze(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    text: String,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_ui(window, state, "analyze", move |client, scope| {
        client.analyze(scope, &text)
    })
    .await
}

#[tauri::command]
pub async fn desktop_sanitize(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    text: String,
    mode: String,
    session_id: Option<String>,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_ui(window, state, "sanitize", move |client, scope| {
        client.sanitize(scope, &text, &mode, session_id.as_deref())
    })
    .await
}

#[tauri::command]
pub async fn desktop_reidentify(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    session_id: String,
    text: String,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_ui(window, state, "reidentify", move |client, scope| {
        client.reidentify(scope, &session_id, &text)
    })
    .await
}

#[tauri::command]
pub async fn desktop_copy_masked(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    session_id: String,
    text: String,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    let label = window.label().to_owned();
    let generation = state.lifecycle.window_generation(&label);
    let owner = OperationOwner::Window {
        label: label.clone(),
        generation,
    };
    let app = window.app_handle().clone();
    let clipboard_app = app.clone();
    run_blocking(app, state, owner, move |manager| {
        let authority = manager.with_ui_scope(&label, generation, |client, scope| {
            client.reidentify(scope, &session_id, &text)
        })?;
        if !reidentify_confirms_copy_authority(&authority) {
            return Err(manager.fail_closed_cleanup("operation_failed"));
        }
        let published =
            manager
                .lifecycle
                .publish_if_window_current(&label, generation, move || {
                    clipboard_app.clipboard().write_text(text)
                });
        match published {
            Some(Ok(())) => Ok(serde_json::json!({"copied": true})),
            Some(Err(_)) => match manager.reset_ui_scope(&label, generation) {
                Ok(_) => Err(DesktopCommandError::fixed("operation_failed", true, false)),
                Err(error) => Err(error),
            },
            None => Err(DesktopCommandError::fixed(
                "session_unavailable",
                true,
                false,
            )),
        }
    })
    .await
    .map(|result| DesktopCommandResult::new("copy_masked", result))
}

#[tauri::command]
pub async fn desktop_analyze_report(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    text: String,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_ui(window, state, "analyze_report", move |client, scope| {
        client.analyze_report(scope, &text)
    })
    .await
}

#[tauri::command]
pub async fn desktop_redact_pdf(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    pdf_b64: String,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_ui(window, state, "redact_pdf", move |client, scope| {
        client.redact_pdf(scope, &pdf_b64)
    })
    .await
}

#[tauri::command]
pub async fn desktop_audit_log(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    limit: u64,
    offset: u64,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    run_ui(window, state, "audit_log", move |client, scope| {
        client.audit_log(scope, Some(limit), Some(offset))
    })
    .await
}

#[tauri::command]
pub async fn desktop_session_dispose(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
    session_id: String,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    let label = window.label().to_owned();
    let generation = state.lifecycle.window_generation(&label);
    let owner = OperationOwner::Window {
        label: label.clone(),
        generation,
    };
    let app = window.app_handle().clone();
    run_blocking(app, state, owner, move |manager| {
        manager.dispose_ui_session(&label, generation, &session_id)
    })
    .await
    .map(|result| DesktopCommandResult::new("session_dispose", result))
}

#[tauri::command]
pub async fn desktop_scope_reset(
    window: WebviewWindow,
    state: State<'_, DesktopBrokerState>,
) -> Result<DesktopCommandResult, DesktopCommandError> {
    let label = window.label().to_owned();
    let generation = state.lifecycle.window_generation(&label);
    let owner = OperationOwner::Window {
        label: label.clone(),
        generation,
    };
    let app = window.app_handle().clone();
    run_blocking(app, state, owner, move |manager| {
        manager.reset_ui_scope(&label, generation)
    })
    .await
    .map(|result| DesktopCommandResult::new("scope_close", result))
}

#[tauri::command]
pub fn desktop_scope_rotate(window: WebviewWindow) -> DesktopCommandResult {
    close_window(window.app_handle(), window.label());
    DesktopCommandResult::new("scope_rotate", serde_json::json!({"rotated": true}))
}

pub fn hotkey_sanitize<F>(
    app: &AppHandle,
    text: &str,
    session_id: Option<&str>,
    publish: F,
) -> Result<(), DesktopCommandError>
where
    F: FnOnce(Value) -> bool,
{
    let state = app.state::<DesktopBrokerState>();
    let lifecycle = Arc::clone(&state.lifecycle);
    let _permit = lifecycle.begin(OperationOwner::Hotkey)?;
    let mut manager = lock_manager_for_operation(&state.inner)?;
    let operation = manager
        .with_hotkey_scope(|client, scope| client.sanitize(scope, text, "token", session_id));
    let result = match operation {
        Ok(value) => match lifecycle.publish_if_running(|| publish(value)) {
            Some(true) => Ok(()),
            _ => Err(manager.fail_closed_cleanup("operation_failed")),
        },
        Err(error) => Err(error),
    };
    if result.as_ref().is_err_and(|error| error.restart_required) {
        emit_authority_invalidated(app);
    }
    result
}

pub fn hotkey_reidentify<F>(
    app: &AppHandle,
    session_id: &str,
    text: &str,
    publish: F,
) -> Result<(), DesktopCommandError>
where
    F: FnOnce(Value) -> bool,
{
    let state = app.state::<DesktopBrokerState>();
    let lifecycle = Arc::clone(&state.lifecycle);
    let _permit = lifecycle.begin(OperationOwner::Hotkey)?;
    let mut manager = lock_manager_for_operation(&state.inner)?;
    let operation =
        manager.with_hotkey_scope(|client, scope| client.reidentify(scope, session_id, text));
    let result = match operation {
        Ok(value) => match lifecycle.publish_if_running(|| publish(value)) {
            Some(true) => Ok(()),
            _ => Err(manager.fail_closed_cleanup("operation_failed")),
        },
        Err(error) => Err(error),
    };
    if result.as_ref().is_err_and(|error| error.restart_required) {
        emit_authority_invalidated(app);
    }
    result
}

pub fn reset_hotkey_scope(app: &AppHandle) {
    let state = app.state::<DesktopBrokerState>();
    let (mut manager, poisoned) = lock_manager_for_cleanup(&state.inner);
    manager.reset_hotkey_scope();
    if poisoned {
        emit_authority_invalidated(app);
    }
}

pub fn close_window(app: &AppHandle, label: &str) {
    let Some(state) = app.try_state::<DesktopBrokerState>() else {
        return;
    };
    let generation = state.lifecycle.invalidate_window(label);
    state.lifecycle.abort_window_operation(label, generation);
    schedule_window_cleanup(
        app.clone(),
        Arc::clone(&state.inner),
        Arc::clone(&state.lifecycle),
        label.to_owned(),
        generation,
    );
}

pub fn shutdown(app: &AppHandle) {
    let state = app.state::<DesktopBrokerState>();
    state.lifecycle.stop();
    let (mut manager, _poisoned) = lock_manager_for_cleanup(&state.inner);
    manager.shutdown();
}

pub fn start_keepalive(app: &AppHandle) {
    let state = app.state::<DesktopBrokerState>();
    let inner = Arc::clone(&state.inner);
    let lifecycle = Arc::clone(&state.lifecycle);
    let app = app.clone();
    std::thread::Builder::new()
        .name("aiguard-desktop-broker-keepalive".to_owned())
        .spawn(move || {
            while !lifecycle.terminal.load(Ordering::Acquire) {
                std::thread::sleep(KEEPALIVE_INTERVAL);
                if lifecycle.terminal.load(Ordering::Acquire) {
                    break;
                }
                let Ok(_permit) = lifecycle.begin(OperationOwner::Health) else {
                    continue;
                };
                let mut invalidated = false;
                match inner.try_lock() {
                    Ok(mut manager) => invalidated = manager.keepalive(),
                    Err(TryLockError::WouldBlock) => {}
                    Err(TryLockError::Poisoned(poisoned)) => {
                        let mut manager = poisoned.into_inner();
                        manager.disconnect();
                        inner.clear_poison();
                        invalidated = true;
                    }
                }
                if invalidated {
                    emit_authority_invalidated(&app);
                }
            }
        })
        .expect("Desktop broker keepalive thread must start");
}

fn schedule_window_cleanup(
    app: AppHandle,
    inner: Arc<Mutex<BrokerManager>>,
    lifecycle: Arc<DesktopLifecycle>,
    label: String,
    generation: u64,
) {
    {
        let mut pending = lock_recover(&lifecycle.pending_window_cleanups);
        let cutoff = pending.entry(label).or_default();
        *cutoff = (*cutoff).max(generation);
    }
    if lifecycle
        .cleanup_worker_active
        .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
        .is_err()
    {
        return;
    }
    tauri::async_runtime::spawn_blocking(move || loop {
        let pending = {
            let mut queued = lock_recover(&lifecycle.pending_window_cleanups);
            std::mem::take(&mut *queued)
        };
        if !pending.is_empty() {
            let (mut manager, mut invalidated) = lock_manager_for_cleanup(&inner);
            for (label, generation) in pending {
                invalidated |= manager.close_window_before(&label, generation);
            }
            if invalidated {
                emit_authority_invalidated(&app);
            }
            drop(manager);
            continue;
        }

        lifecycle
            .cleanup_worker_active
            .store(false, Ordering::Release);
        if lock_recover(&lifecycle.pending_window_cleanups).is_empty()
            || lifecycle
                .cleanup_worker_active
                .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        {
            break;
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use aiguard_native_broker_protocol::broker::BrokerRuntimeConfig;

    #[test]
    fn keepalive_precedes_the_broker_request_idle_deadline() {
        assert!(KEEPALIVE_INTERVAL < BrokerRuntimeConfig::default().request_timeout);
    }

    #[test]
    fn keepalive_ignores_only_nonterminal_busy_responses() {
        assert!(!keepalive_requires_disconnect("broker_busy", false));
        assert!(keepalive_requires_disconnect("broker_busy", true));
        assert!(keepalive_requires_disconnect("broker_unavailable", false));
    }

    #[test]
    fn unconfirmed_cleanup_drops_every_local_authority() {
        let mut manager = BrokerManager::default();
        manager.ui_scopes.insert(
            "main".to_owned(),
            UiScope {
                id: "scope-ui".to_owned(),
                generation: 0,
            },
        );
        manager.hotkey_scope = Some("scope-hotkey".to_owned());

        let error = manager.fail_closed_cleanup("operation_failed");

        assert_eq!(error.code, "operation_failed");
        assert!(error.session_invalidated);
        assert!(error.restart_required);
        assert!(manager.ui_scopes.is_empty());
        assert!(manager.hotkey_scope.is_none());
        assert!(manager.client.is_none());
    }

    #[test]
    fn taking_one_window_scope_preserves_unrelated_local_authority() {
        let mut manager = BrokerManager::default();
        manager.ui_scopes.insert(
            "first".to_owned(),
            UiScope {
                id: "scope-first".to_owned(),
                generation: 0,
            },
        );
        manager.ui_scopes.insert(
            "second".to_owned(),
            UiScope {
                id: "scope-second".to_owned(),
                generation: 0,
            },
        );
        manager.hotkey_scope = Some("scope-hotkey".to_owned());

        assert_eq!(
            manager.take_ui_scope("first").map(|scope| scope.id),
            Some("scope-first".to_owned())
        );
        assert_eq!(
            manager
                .ui_scopes
                .get("second")
                .map(|scope| scope.id.as_str()),
            Some("scope-second")
        );
        assert_eq!(manager.hotkey_scope.as_deref(), Some("scope-hotkey"));
    }

    #[test]
    fn operation_admission_is_bounded_before_work_is_queued() {
        let lifecycle = Arc::new(DesktopLifecycle::default());
        let first = lifecycle
            .begin(OperationOwner::Health)
            .expect("first operation is admitted");
        let worker = first.clone();

        let rejected = lifecycle.begin(OperationOwner::Hotkey).unwrap_err();

        assert_eq!(rejected.code(), "broker_busy");
        assert!(!rejected.session_invalidated());
        drop(first);
        assert!(lifecycle.begin(OperationOwner::Hotkey).is_err());
        drop(worker);
        assert!(lifecycle.begin(OperationOwner::Hotkey).is_ok());
    }

    #[test]
    fn fatal_invalidation_tombstones_already_admitted_and_future_work() {
        let lifecycle = Arc::new(DesktopLifecycle::default());
        let manager = Arc::new(Mutex::new(BrokerManager::with_lifecycle(Arc::clone(
            &lifecycle,
        ))));
        let manager_lock = manager.lock().unwrap();
        let (admitted, wait_for_admission) = std::sync::mpsc::channel();
        let (finished, wait_for_finish) = std::sync::mpsc::channel();
        let worker_lifecycle = Arc::clone(&lifecycle);
        let worker_manager = Arc::clone(&manager);
        let worker = std::thread::spawn(move || {
            let _permit = worker_lifecycle
                .begin(OperationOwner::Hotkey)
                .expect("operation is admitted before invalidation");
            admitted.send(()).unwrap();
            let mut manager = worker_manager.lock().unwrap();
            let error = manager.connect().unwrap_err();
            let publication = worker_lifecycle.publish_if_running(|| true);
            finished
                .send((
                    error.code().to_owned(),
                    error.restart_required,
                    publication,
                    manager.client.is_none()
                        && manager.ui_scopes.is_empty()
                        && manager.hotkey_scope.is_none(),
                ))
                .unwrap();
        });
        wait_for_admission.recv().unwrap();

        lifecycle.stop();
        drop(manager_lock);

        let (code, restart_required, publication, authority_empty) = wait_for_finish
            .recv_timeout(Duration::from_secs(1))
            .expect("queued work must fail without deadlock");
        worker.join().unwrap();
        assert_eq!(code, "broker_unavailable");
        assert!(restart_required);
        assert!(publication.is_none());
        assert!(authority_empty);
        let future_error = lifecycle.begin(OperationOwner::Health).unwrap_err();
        assert_eq!(future_error.code(), "broker_unavailable");
        assert!(future_error.restart_required);
    }

    #[test]
    fn shutdown_waits_for_an_atomic_publication_boundary() {
        let lifecycle = Arc::new(DesktopLifecycle::default());
        let (publication_started, wait_for_publication) = std::sync::mpsc::channel();
        let (release_publication, publication_release) = std::sync::mpsc::channel();
        let publisher = Arc::clone(&lifecycle);
        let publishing = std::thread::spawn(move || {
            publisher.publish_if_running(|| {
                publication_started.send(()).unwrap();
                publication_release.recv().unwrap();
                true
            })
        });
        wait_for_publication.recv().unwrap();

        let (shutdown_finished, wait_for_shutdown) = std::sync::mpsc::channel();
        let stopper = Arc::clone(&lifecycle);
        let stopping = std::thread::spawn(move || {
            stopper.stop();
            shutdown_finished.send(()).unwrap();
        });

        assert!(wait_for_shutdown
            .recv_timeout(Duration::from_millis(50))
            .is_err());
        release_publication.send(()).unwrap();
        assert_eq!(publishing.join().unwrap(), Some(true));
        wait_for_shutdown
            .recv_timeout(Duration::from_secs(1))
            .unwrap();
        stopping.join().unwrap();
        assert!(lifecycle.publish_if_running(|| true).is_none());
    }

    #[test]
    fn renderer_generation_rejects_queued_work_after_reload() {
        let lifecycle = Arc::new(DesktopLifecycle::default());
        let original = lifecycle.window_generation("main");
        let owner = OperationOwner::Window {
            label: "main".to_owned(),
            generation: original,
        };
        let permit = lifecycle.begin(owner.clone()).unwrap();

        let replacement = lifecycle.invalidate_window("main");

        assert!(replacement > original);
        assert!(!lifecycle.window_is_current("main", original));
        assert!(lifecycle.abort_window_operation("main", replacement));
        drop(permit);
        assert!(lifecycle
            .begin(OperationOwner::Window {
                label: "main".to_owned(),
                generation: replacement,
            })
            .is_ok());
    }

    #[test]
    fn delayed_cleanup_never_removes_a_replacement_generation() {
        let mut manager = BrokerManager::default();
        manager.ui_scopes.insert(
            "main".to_owned(),
            UiScope {
                id: "scope-new".to_owned(),
                generation: 2,
            },
        );

        assert!(manager.take_ui_scope_before("main", 2).is_none());
        assert_eq!(
            manager.ui_scopes.get("main").map(|scope| scope.id.as_str()),
            Some("scope-new")
        );
        assert_eq!(
            manager
                .take_ui_scope_before("main", 3)
                .map(|scope| scope.id),
            Some("scope-new".to_owned())
        );
    }

    #[test]
    fn clipboard_publication_is_bound_to_the_current_renderer_generation() {
        let lifecycle = DesktopLifecycle::default();
        let generation = lifecycle.window_generation("main");
        assert_eq!(
            lifecycle.publish_if_window_current("main", generation, || "published"),
            Some("published")
        );
        lifecycle.invalidate_window("main");
        assert!(lifecycle
            .publish_if_window_current("main", generation, || "forbidden")
            .is_none());
        lifecycle.stop();
        let replacement = lifecycle.window_generation("main");
        assert!(lifecycle
            .publish_if_window_current("main", replacement, || "forbidden")
            .is_none());
    }

    #[test]
    fn copy_authority_requires_a_complete_reidentification() {
        assert!(reidentify_confirms_copy_authority(&serde_json::json!({
            "restored_text": "synthetic",
            "replaced_count": 1,
            "leftover_count": 0,
            "warnings": []
        })));
        assert!(!reidentify_confirms_copy_authority(&serde_json::json!({
            "restored_text": "synthetic",
            "replaced_count": 0,
            "leftover_count": 1,
            "warnings": []
        })));
    }

    #[test]
    fn poisoned_manager_is_recovered_only_to_drop_authority() {
        let inner = Arc::new(Mutex::new(BrokerManager::default()));
        {
            let mut manager = inner.lock().unwrap();
            manager.ui_scopes.insert(
                "main".to_owned(),
                UiScope {
                    id: "scope-ui".to_owned(),
                    generation: 0,
                },
            );
            manager.hotkey_scope = Some("scope-hotkey".to_owned());
        }
        let poisoned = Arc::clone(&inner);
        let _ = std::panic::catch_unwind(move || {
            let _manager = poisoned.lock().unwrap();
            panic!("synthetic manager panic");
        });

        let error = match lock_manager_for_operation(&inner) {
            Ok(_) => panic!("poisoned authority must not be reused"),
            Err(error) => error,
        };

        assert_eq!(error.code(), "operation_failed");
        assert!(error.session_invalidated());
        let manager = inner.lock().unwrap();
        assert!(manager.ui_scopes.is_empty());
        assert!(manager.hotkey_scope.is_none());
        assert!(manager.client.is_none());
    }
}
