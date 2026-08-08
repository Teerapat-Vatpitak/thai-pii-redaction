//! Central role binding after transport and package checks succeed.

use std::fmt;

use crate::ProtocolError;

#[derive(Clone)]
pub struct BrokerOsContext {
    pub user_boundary: String,
    pub logon_session: String,
}

#[derive(Clone)]
pub struct OsPeerContext {
    pub user_boundary: String,
    pub logon_session: String,
    pub process_id: u32,
    pub credential_verified: bool,
    pub stable_process_reference: bool,
}

pub struct PackageConsistencyEvidence {
    pub component_id: String,
    pub allowed_role: String,
    pub canonical_path_matches: bool,
    pub build_id_matches: bool,
    pub digest_matches: bool,
}

impl fmt::Debug for PackageConsistencyEvidence {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PackageConsistencyEvidence")
            .field("component_id", &self.component_id)
            .field("allowed_role", &self.allowed_role)
            .field("canonical_path_matches", &self.canonical_path_matches)
            .field("build_id_matches", &self.build_id_matches)
            .field("digest_matches", &self.digest_matches)
            .finish()
    }
}

pub struct AdmissionDecision {
    claimed_role: String,
    admitted_role: String,
    component_id: String,
}

impl AdmissionDecision {
    pub fn claimed_role(&self) -> &str {
        &self.claimed_role
    }

    pub fn admitted_role(&self) -> &str {
        &self.admitted_role
    }

    pub fn component_id(&self) -> &str {
        &self.component_id
    }
}

impl fmt::Debug for AdmissionDecision {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AdmissionDecision")
            .field("admitted_role", &self.admitted_role)
            .finish_non_exhaustive()
    }
}

fn known_role(role: &str) -> bool {
    matches!(role, "desktop" | "extension" | "maintenance")
}

pub fn decide_admission(
    broker: &BrokerOsContext,
    peer: &OsPeerContext,
    package: &PackageConsistencyEvidence,
    claimed_role: &str,
) -> Result<AdmissionDecision, ProtocolError> {
    let context_matches = peer.credential_verified
        && peer.stable_process_reference
        && peer.process_id > 0
        && !broker.user_boundary.is_empty()
        && !broker.logon_session.is_empty()
        && peer.user_boundary == broker.user_boundary
        && peer.logon_session == broker.logon_session;
    let package_matches = !package.component_id.is_empty()
        && known_role(&package.allowed_role)
        && package.canonical_path_matches
        && package.build_id_matches
        && package.digest_matches;
    if !context_matches
        || !package_matches
        || !known_role(claimed_role)
        || claimed_role != package.allowed_role
    {
        return Err(ProtocolError::new("broker_unauthorized", None));
    }
    Ok(AdmissionDecision {
        claimed_role: claimed_role.to_owned(),
        admitted_role: package.allowed_role.clone(),
        component_id: package.component_id.clone(),
    })
}
