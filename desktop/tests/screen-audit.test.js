import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({ auditLog: vi.fn() }));

import { auditLog } from "../src/api.js";
import { renderAudit } from "../src/screen-audit.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

function response(step) {
  return {
    logs: [
      {
        timestamp: 1,
        step,
        entity_count: 0,
        validation_result: "pass",
        latency_ms: 1,
      },
    ],
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  vi.clearAllMocks();
});

describe("Desktop audit render lifecycle", () => {
  it("does not let an older mount overwrite a remounted audit screen", async () => {
    const first = deferred();
    const second = deferred();
    auditLog.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const root = document.getElementById("root");

    renderAudit(root);
    root.innerHTML = "<p>other screen</p>";
    renderAudit(root);

    second.resolve(response("current"));
    await flush();
    expect(root.querySelector("#au-out").textContent).toContain("current");

    first.resolve(response("stale"));
    await flush();
    expect(root.querySelector("#au-out").textContent).toContain("current");
    expect(root.querySelector("#au-out").textContent).not.toContain("stale");
  });

  it("does not project an older mount rejection into a remounted screen", async () => {
    const first = deferred();
    auditLog.mockReturnValueOnce(first.promise).mockResolvedValueOnce(response("current"));
    const root = document.getElementById("root");

    renderAudit(root);
    root.innerHTML = "<p>other screen</p>";
    renderAudit(root);
    await flush();

    first.reject(new Error("stale failure"));
    await flush();
    expect(root.querySelector("#au-out").textContent).toContain("current");
    expect(root.querySelector("#au-err").classList).toContain("hidden");
    expect(root.querySelector("#au-err").textContent).toBe("");
  });
});
