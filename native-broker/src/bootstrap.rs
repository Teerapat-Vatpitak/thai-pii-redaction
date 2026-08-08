//! Backend boot secrets and terminal lifecycle decisions.

use std::fmt;

use getrandom::fill;
use zeroize::Zeroizing;

use crate::ProtocolError;

pub struct BootstrapSecrets {
    api_key: Zeroizing<String>,
    control_token: Zeroizing<String>,
}

impl BootstrapSecrets {
    pub fn generate() -> Result<Self, ProtocolError> {
        let api_key = generate_secret()?;
        let mut control_token = generate_secret()?;
        if api_key == control_token {
            control_token = generate_secret()?;
        }
        if api_key == control_token {
            return Err(ProtocolError::new("operation_failed", None));
        }
        Ok(Self {
            api_key: Zeroizing::new(api_key),
            control_token: Zeroizing::new(control_token),
        })
    }

    pub fn api_key(&self) -> &str {
        self.api_key.as_str()
    }

    pub fn control_token(&self) -> &str {
        self.control_token.as_str()
    }
}

impl fmt::Debug for BootstrapSecrets {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("BootstrapSecrets(<redacted>)")
    }
}

fn generate_secret() -> Result<String, ProtocolError> {
    let mut bytes = Zeroizing::new([0_u8; 32]);
    fill(bytes.as_mut()).map_err(|_| ProtocolError::new("operation_failed", None))?;
    let mut encoded = String::with_capacity(64);
    for byte in bytes.iter() {
        use std::fmt::Write;
        write!(&mut encoded, "{byte:02x}")
            .map_err(|_| ProtocolError::new("operation_failed", None))?;
    }
    Ok(encoded)
}
