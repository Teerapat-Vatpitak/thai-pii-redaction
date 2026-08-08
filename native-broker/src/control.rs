//! Slice 2 health and maintenance-only control authorization.

use crate::admission::AdmissionDecision;
use crate::{operation_allowed, ProtocolError};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlAction {
    Health,
    DrainStop,
}

#[derive(Default)]
pub struct Slice2ControlPlane;

impl Slice2ControlPlane {
    pub fn new() -> Self {
        Self
    }

    pub fn authorize(
        &self,
        admission: &AdmissionDecision,
        operation: &str,
    ) -> Result<ControlAction, ProtocolError> {
        let role = admission.admitted_role();
        if !operation_allowed(role, operation) {
            return Err(ProtocolError::new("broker_unauthorized", None));
        }
        match operation {
            "broker_health" => Ok(ControlAction::Health),
            "maintenance_drain_stop" if role == "maintenance" => Ok(ControlAction::DrainStop),
            _ => Err(ProtocolError::new("operation_failed", None)),
        }
    }
}
