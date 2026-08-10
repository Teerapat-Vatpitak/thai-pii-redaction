//! Fixed configuration policy for the installed native product boundary.

use std::ffi::{OsStr, OsString};
#[cfg(unix)]
use std::process::Command;

use crate::ProtocolError;

pub(crate) const NER_ENGINE: &str = "thainer";
pub(crate) const PROVIDER_POLICY: &str = "fake";

#[cfg(test)]
const RESTRICTED_ENVIRONMENT_NAMES: &[&str] = &[
    "AIFORTHAI_API_KEY",
    "AIGUARD_API_KEY",
    "AIGUARD_FINETUNED_MODEL_DIR",
    "AIGUARD_NER_ENGINE",
    "AIGUARD_PROVIDERS",
    "AIGUARD_TOKEN",
    "ANTHROPIC_API_KEY",
    "TOKENMIND_ALLOW_HTTP",
    "TOKENMIND_API_KEY",
    "TOKENMIND_BASE_URL",
];

const INHERITED_RUNTIME_ENVIRONMENT_NAMES: &[&str] = &[
    "ALLUSERSPROFILE",
    "APPDATA",
    "COMSPEC",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "FONTCONFIG_FILE",
    "FONTCONFIG_PATH",
    "GSETTINGS_SCHEMA_DIR",
    "GI_TYPELIB_PATH",
    "GST_PLUGIN_PATH",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LD_LIBRARY_PATH",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "PUBLIC",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONIOENCODING",
    "PYTHONNOUSERSITE",
    "PYTHONUTF8",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "TZ",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
    "XDG_DATA_DIRS",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_RUNTIME_DIR",
    "XDG_STATE_HOME",
    "__CF_USER_TEXT_ENCODING",
];

#[cfg(debug_assertions)]
const TEST_ENVIRONMENT_NAMES: &[&str] = &[
    "AIGUARD_SLICE2_CONNECTED_ROOT",
    "AIGUARD_SLICE2_DONE_ROOT",
    "AIGUARD_SLICE2_EARLY_PID_FILE",
    "AIGUARD_SLICE2_ENDPOINT_ROOT",
    "AIGUARD_SLICE2_EXPAND_PATH",
    "AIGUARD_SLICE2_EXPECT_DENIED",
    "AIGUARD_SLICE2_EXPECT_ERROR",
    "AIGUARD_SLICE2_HELLO_DELAY_MS",
    "AIGUARD_SLICE2_HOLD_COUNT",
    "AIGUARD_SLICE2_HOLDERS_ROOT",
    "AIGUARD_SLICE2_IDLE_MS",
    "AIGUARD_SLICE2_KEEPER_READY_PATH",
    "AIGUARD_SLICE2_LAUNCH_BROKER",
    "AIGUARD_SLICE2_MANIFEST",
    "AIGUARD_SLICE2_OWNERS_ROOT",
    "AIGUARD_SLICE2_PID_FILE",
    "AIGUARD_SLICE2_READY",
    "AIGUARD_SLICE2_RELEASE_PATH",
    "AIGUARD_SLICE2_RESULT_PATH",
    "AIGUARD_SLICE2_SKIP_HEALTH",
    "AIGUARD_SLICE2_START_IF_ABSENT",
    "AIGUARD_SLICE4_DESKTOP_CONTINUE",
    "AIGUARD_SLICE4_DESKTOP_ENDPOINT",
    "AIGUARD_SLICE4_DESKTOP_MANIFEST",
    "AIGUARD_SLICE4_DESKTOP_READY",
    "AIGUARD_SLICE4_DESKTOP_SURVIVED",
    "AIGUARD_SLICE4_ENDPOINT_ROOT",
    "AIGUARD_SLICE4_ENVIRONMENT_REPORT",
    "AIGUARD_SLICE4_EXTENSION_CONTINUE",
    "AIGUARD_SLICE4_EXTENSION_ENDPOINT",
    "AIGUARD_SLICE4_EXTENSION_MANIFEST",
    "AIGUARD_SLICE4_EXTENSION_READY",
    "AIGUARD_SLICE4_EXTENSION_SURVIVED",
    "AIGUARD_SLICE4_MANIFEST",
    "AIGUARD_SLICE4_MODE",
    "AIGUARD_SLICE4_OWNERS_ROOT",
    "AIGUARD_TEST_PYTHON",
];

pub(crate) fn validate_requested_configuration() -> Result<(), ProtocolError> {
    validate_selector(
        std::env::var_os("AIGUARD_NER_ENGINE").as_deref(),
        NER_ENGINE,
        "ner_unavailable",
    )?;
    validate_selector(
        std::env::var_os("AIGUARD_PROVIDERS").as_deref(),
        PROVIDER_POLICY,
        "provider_configuration",
    )
}

fn validate_selector(
    requested: Option<&OsStr>,
    supported: &str,
    error_code: &'static str,
) -> Result<(), ProtocolError> {
    match requested {
        None => Ok(()),
        Some(value) if value == OsStr::new(supported) => Ok(()),
        Some(_) => Err(ProtocolError::new(error_code, None)),
    }
}

#[cfg(unix)]
pub(crate) fn configure_child_command(command: &mut Command) {
    command.env_clear().envs(child_environment());
}

pub(crate) fn child_environment() -> Vec<(OsString, OsString)> {
    child_environment_with(|name| std::env::var_os(name))
}

fn child_environment_with(
    mut read: impl FnMut(&str) -> Option<OsString>,
) -> Vec<(OsString, OsString)> {
    let mut environment = INHERITED_RUNTIME_ENVIRONMENT_NAMES
        .iter()
        .filter_map(|name| read(name).map(|value| (OsString::from(name), value)))
        .collect::<Vec<_>>();
    #[cfg(debug_assertions)]
    environment.extend(
        TEST_ENVIRONMENT_NAMES
            .iter()
            .filter_map(|name| read(name).map(|value| (OsString::from(name), value))),
    );
    environment.push((
        OsString::from("AIGUARD_NER_ENGINE"),
        OsString::from(NER_ENGINE),
    ));
    environment.push((
        OsString::from("AIGUARD_PROVIDERS"),
        OsString::from(PROVIDER_POLICY),
    ));
    environment
}

pub(crate) fn validate_desktop_provider_request(
    operation: &str,
    payload: &serde_json::Value,
) -> Result<(), ProtocolError> {
    if operation != "roundtrip" {
        return Ok(());
    }
    match payload.get("provider").and_then(serde_json::Value::as_str) {
        Some(PROVIDER_POLICY) | None => Ok(()),
        Some(_) => Err(ProtocolError::new("provider_configuration", None)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selector_policy_accepts_only_the_fixed_installed_configuration() {
        assert!(validate_selector(None, NER_ENGINE, "ner_unavailable").is_ok());
        assert!(
            validate_selector(Some(OsStr::new(NER_ENGINE)), NER_ENGINE, "ner_unavailable").is_ok()
        );
        assert_eq!(
            validate_selector(Some(OsStr::new("tner")), NER_ENGINE, "ner_unavailable")
                .unwrap_err()
                .code(),
            "ner_unavailable"
        );
        assert_eq!(
            validate_selector(
                Some(OsStr::new("pathumma")),
                PROVIDER_POLICY,
                "provider_configuration"
            )
            .unwrap_err()
            .code(),
            "provider_configuration"
        );
    }

    #[test]
    fn child_environment_queries_only_safe_names_and_pins_policy() {
        let mut queried = Vec::new();
        let environment = child_environment_with(|name| {
            queried.push(name.to_owned());
            (name == "PATH").then(|| OsString::from("synthetic-path"))
        });
        assert!(environment
            .iter()
            .any(|(name, value)| name == "PATH" && value == "synthetic-path"));
        assert!(queried.iter().all(|name| !RESTRICTED_ENVIRONMENT_NAMES
            .iter()
            .any(|restricted| name.eq_ignore_ascii_case(restricted))));
        assert!(INHERITED_RUNTIME_ENVIRONMENT_NAMES.iter().all(|name| {
            !RESTRICTED_ENVIRONMENT_NAMES
                .iter()
                .any(|restricted| name.eq_ignore_ascii_case(restricted))
        }));
        assert_eq!(
            environment
                .iter()
                .filter(|(name, value)| name == "AIGUARD_NER_ENGINE" && value == NER_ENGINE)
                .count(),
            1
        );
        assert_eq!(
            environment
                .iter()
                .filter(|(name, value)| name == "AIGUARD_PROVIDERS" && value == PROVIDER_POLICY)
                .count(),
            1
        );
    }

    #[cfg(unix)]
    #[test]
    fn non_utf8_selector_fails_closed() {
        use std::os::unix::ffi::OsStrExt;

        let value = OsStr::from_bytes(b"thainer\xff");
        assert_eq!(
            validate_selector(Some(value), NER_ENGINE, "ner_unavailable")
                .unwrap_err()
                .code(),
            "ner_unavailable"
        );
    }
}
