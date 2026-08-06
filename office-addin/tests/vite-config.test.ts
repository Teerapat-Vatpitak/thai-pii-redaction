import { describe, expect, it, vi } from "vitest";
import { resolveHttpsOptions } from "../vite.config";

describe("Office development HTTPS policy", () => {
  it("does not load or provision certificates for a production build", async () => {
    const provision = vi.fn();
    const readFile = vi.fn();

    await expect(resolveHttpsOptions("build", {}, {
      homeDirectory: () => "ignored",
      provision,
      readFile,
    })).resolves.toBeUndefined();
    expect(provision).not.toHaveBeenCalled();
    expect(readFile).not.toHaveBeenCalled();
  });

  it("preserves the interactive development provisioning path", async () => {
    const provisioned = { key: Buffer.from("key"), cert: Buffer.from("cert") };
    const provision = vi.fn().mockResolvedValue(provisioned);

    await expect(resolveHttpsOptions("serve", {}, {
      homeDirectory: () => "ignored",
      provision,
      readFile: vi.fn(),
    })).resolves.toBe(provisioned);
    expect(provision).toHaveBeenCalledOnce();
  });

  it("reads only pre-existing files and never provisions in composition mode", async () => {
    const provision = vi.fn();
    const readFile = vi.fn((path: string) => Buffer.from(path));

    const options = await resolveHttpsOptions(
      "serve",
      {
        AIGUARD_OFFICE_EXISTING_CERTS_ONLY: "1",
      },
      {
        homeDirectory: () => "trusted-certs",
        provision,
        readFile,
      },
    );

    expect(provision).not.toHaveBeenCalled();
    expect(readFile.mock.calls.map(([path]) => path)).toEqual([
      expect.stringMatching(/trusted-certs[\\/]\.office-addin-dev-certs[\\/]ca\.crt$/u),
      expect.stringMatching(/trusted-certs[\\/]\.office-addin-dev-certs[\\/]localhost\.crt$/u),
      expect.stringMatching(/trusted-certs[\\/]\.office-addin-dev-certs[\\/]localhost\.key$/u),
    ]);
    expect(options).toMatchObject({
      ca: expect.any(Buffer),
      cert: expect.any(Buffer),
      key: expect.any(Buffer),
    });
  });

  it("fails closed without provisioning when an existing certificate file is absent", async () => {
    const provision = vi.fn();

    await expect(resolveHttpsOptions(
      "serve",
      { AIGUARD_OFFICE_EXISTING_CERTS_ONLY: "1" },
      {
        homeDirectory: () => "home",
        provision,
        readFile: () => {
          throw new Error("missing");
        },
      },
    )).rejects.toThrow("missing");
    expect(provision).not.toHaveBeenCalled();
  });
});
