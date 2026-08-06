import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { verifyCertificates } from "office-addin-dev-certs";

const CERTIFICATE_DIRECTORY_NAME = ".office-addin-dev-certs";
const CERTIFICATE_FILE_NAMES = {
  ca: "ca.crt",
  cert: "localhost.crt",
  key: "localhost.key",
};

export function inspectExistingDevCertificates({ files, exists, verify }) {
  try {
    if (![files.ca, files.cert, files.key].every((path) => exists(path))) {
      return {
        status: "pending",
        reason: "certificate-files-missing",
      };
    }

    if (!verify(files.cert, files.key)) {
      return {
        status: "pending",
        reason: "not-trusted-or-invalid",
      };
    }

    return { status: "ready" };
  } catch {
    return {
      status: "error",
      reason: "verification-error",
    };
  }
}

function inspectDefaultCertificates() {
  const certificateDirectory = join(homedir(), CERTIFICATE_DIRECTORY_NAME);
  const files = {
    ca: join(certificateDirectory, CERTIFICATE_FILE_NAMES.ca),
    cert: join(certificateDirectory, CERTIFICATE_FILE_NAMES.cert),
    key: join(certificateDirectory, CERTIFICATE_FILE_NAMES.key),
  };

  return inspectExistingDevCertificates({
    files,
    exists: existsSync,
    verify: verifyCertificates,
  });
}

function run() {
  let result;
  try {
    result = inspectDefaultCertificates();
  } catch {
    result = {
      status: "error",
      reason: "verification-error",
    };
  }
  const exitCodes = {
    ready: 0,
    pending: 3,
    error: 1,
  };

  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = exitCodes[result.status];
}

const scriptPath = fileURLToPath(import.meta.url);
const invokedPath = process.argv[1];
if (invokedPath && resolve(invokedPath) === scriptPath) {
  run();
}
