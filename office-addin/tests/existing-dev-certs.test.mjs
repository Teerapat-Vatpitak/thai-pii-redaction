import { describe, expect, it, vi } from "vitest";
import { inspectExistingDevCertificates } from "../scripts/existing-dev-certs.mjs";

const FILES = {
  ca: "ca.crt",
  cert: "localhost.crt",
  key: "localhost.key",
};

describe("existing Office development certificate probe", () => {
  it("reports pending without invoking trust verification when a file is absent", () => {
    const verify = vi.fn();
    const result = inspectExistingDevCertificates({
      files: FILES,
      exists: (path) => path !== FILES.key,
      verify,
    });

    expect(result).toEqual({
      status: "pending",
      reason: "certificate-files-missing",
    });
    expect(verify).not.toHaveBeenCalled();
  });

  it("reports ready only for complete, valid, already trusted certificates", () => {
    const verify = vi.fn().mockReturnValue(true);
    const result = inspectExistingDevCertificates({
      files: FILES,
      exists: () => true,
      verify,
    });

    expect(result).toEqual({ status: "ready" });
    expect(verify).toHaveBeenCalledOnce();
    expect(verify).toHaveBeenCalledWith(FILES.cert, FILES.key);
  });

  it("keeps an invalid or untrusted certificate pending", () => {
    const result = inspectExistingDevCertificates({
      files: FILES,
      exists: () => true,
      verify: () => false,
    });

    expect(result).toEqual({
      status: "pending",
      reason: "not-trusted-or-invalid",
    });
  });

  it("returns a constant error without exposing verification details", () => {
    const result = inspectExistingDevCertificates({
      files: FILES,
      exists: () => true,
      verify: () => {
        throw new Error("certificate path or private detail");
      },
    });

    expect(result).toEqual({
      status: "error",
      reason: "verification-error",
    });
    expect(JSON.stringify(result)).not.toContain("private detail");
  });
});
