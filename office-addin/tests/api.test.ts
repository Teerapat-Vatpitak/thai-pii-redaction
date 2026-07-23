import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "../src/api";

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ApiClient", () => {
  it("uses relative API paths and never sends credentials", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(response(200, { status: "ok", version: "2.4.0" }));
    const client = new ApiClient("/api", fetcher);
    await client.health();
    expect(fetcher).toHaveBeenCalledWith("/api/health", expect.objectContaining({ credentials: "omit", cache: "no-store" }));
  });

  it("invokes fetch without binding ApiClient as its receiver", async () => {
    const fetcher = vi.fn(function (this: unknown) {
      expect(this).toBeUndefined();
      return Promise.resolve(response(200, { status: "ok", version: "2.4.0" }));
    }) as typeof fetch;

    await new ApiClient("/api", fetcher).health();
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("reports backend offline without exposing a request body", async () => {
    const client = new ApiClient("/api", vi.fn<typeof fetch>().mockRejectedValue(new Error("network detail")));
    await expect(client.health()).rejects.toMatchObject({ code: "offline", status: 0 });
  });

  it("treats a dev-proxy health failure as backend offline, not Pathumma failure", async () => {
    const client = new ApiClient("/api", vi.fn<typeof fetch>().mockResolvedValue(response(502, {})));
    await expect(client.health()).rejects.toMatchObject({ code: "offline", status: 502 });
    await expect(client.health()).rejects.toMatchObject({ message: expect.stringContaining("ติดต่อ AI Guard") });
  });

  it("maps missing Pathumma key and provider failures", async () => {
    const missing = new ApiClient("/api", vi.fn<typeof fetch>().mockResolvedValue(response(503, { detail: "secret backend detail" })));
    await expect(missing.roundtrip("fixture", "token")).rejects.toMatchObject({ code: "missing-key" });
    const failed = new ApiClient("/api", vi.fn<typeof fetch>().mockResolvedValue(response(502, {})));
    await expect(failed.roundtrip("fixture", "token")).rejects.toBeInstanceOf(ApiError);
    await expect(failed.roundtrip("fixture", "token")).rejects.toMatchObject({ code: "provider" });
  });

  it("treats missing sessions as expired and never guesses", async () => {
    const client = new ApiClient("/api", vi.fn<typeof fetch>().mockResolvedValue(response(404, {})));
    await expect(client.reidentify("gone", "[NAME_1]")).rejects.toMatchObject({ code: "expired" });
  });

  it("does not mislabel an unrelated 404 as an expired session", async () => {
    const client = new ApiClient("/api", vi.fn<typeof fetch>().mockResolvedValue(response(404, {})));
    await expect(client.detect("fixture")).rejects.toMatchObject({ code: "request", status: 404 });
  });
});
