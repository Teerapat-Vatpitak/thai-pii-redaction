import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  health: vi.fn(),
  rotateScope: vi.fn(),
  initTheme: vi.fn(),
  renderText: vi.fn(),
  renderRedact: vi.fn(),
  renderReport: vi.fn(),
  renderSettings: vi.fn(),
  renderAudit: vi.fn(),
}));

vi.mock("../src/api.js", () => ({
  health: mocks.health,
  rotateScope: mocks.rotateScope,
}));
vi.mock("../src/theme.js", () => ({ initTheme: mocks.initTheme }));
vi.mock("../src/screen-text.js", () => ({ renderText: mocks.renderText }));
vi.mock("../src/screen-redact.js", () => ({ renderRedact: mocks.renderRedact }));
vi.mock("../src/screen-report.js", () => ({ renderReport: mocks.renderReport }));
vi.mock("../src/screen-settings.js", () => ({
  renderSettings: mocks.renderSettings,
}));
vi.mock("../src/screen-audit.js", () => ({ renderAudit: mocks.renderAudit }));

function appMarkup() {
  return `
    <div id="boot"><p id="boot-msg"></p></div>
    <div id="app" class="hidden">
      <button class="nav-item" data-tab="text"></button>
      <button class="nav-item" data-tab="redact"></button>
      <button class="nav-item" data-tab="report"></button>
      <button class="nav-item" data-tab="settings"></button>
      <button class="nav-item" data-tab="audit"></button>
      <main id="screen"></main>
    </div>
  `;
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

async function startApp() {
  vi.resetModules();
  await import("../src/app.js");
  await flush();
}

beforeEach(() => {
  document.body.innerHTML = appMarkup();
  vi.clearAllMocks();
  mocks.health.mockResolvedValue({ status: "ok" });
  mocks.rotateScope.mockResolvedValue({ rotated: true });
  for (const render of [
    mocks.renderText,
    mocks.renderRedact,
    mocks.renderReport,
    mocks.renderSettings,
    mocks.renderAudit,
  ]) {
    render.mockImplementation((root) => {
      root.textContent = "published-screen-state";
      return vi.fn().mockResolvedValue(undefined);
    });
  }
});

describe("Desktop authority and tab lifecycle", () => {
  it("requires a process restart after initial broker authority fails", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    mocks.health.mockRejectedValue(
      Object.assign(new Error("safe failure"), {
        code: "broker_unavailable",
        restartRequired: true,
      })
    );
    window.__TAURI__ = {
      core: { invoke },
      event: { listen: vi.fn().mockResolvedValue(vi.fn()) },
    };

    await startApp();

    const closeApp = document.querySelector("#boot button");
    expect(closeApp?.textContent).toBe("ปิดแอป");
    closeApp.click();
    expect(invoke).toHaveBeenCalledWith("quit_app");
    expect(mocks.renderText).not.toHaveBeenCalled();
  });

  it("registers the fixed invalidation event and discards publication state without an operation", async () => {
    let invalidationHandler;
    const invalidatePublication = vi.fn(() => {
      throw new Error("local cleanup failed");
    });
    mocks.renderText.mockImplementation((root) => {
      root.textContent = "published-screen-state";
      const cleanup = vi.fn().mockResolvedValue(undefined);
      cleanup.invalidatePublication = invalidatePublication;
      return cleanup;
    });
    const listen = vi.fn().mockImplementation(async (eventName, handler) => {
      invalidationHandler = handler;
      return vi.fn();
    });
    window.__TAURI__ = {
      core: { invoke: vi.fn() },
      event: { listen },
    };

    await startApp();

    expect(listen).toHaveBeenCalledWith(
      "desktop-authority-invalidated",
      expect.any(Function)
    );
    const priorScreen = document.getElementById("screen");
    expect(priorScreen.textContent).toBe("published-screen-state");

    invalidationHandler({ payload: "ignored-private-value" });

    expect(invalidatePublication).toHaveBeenCalledOnce();
    expect(document.getElementById("screen")).not.toBe(priorScreen);
    expect(document.body.textContent).not.toContain("published-screen-state");
    expect(document.body.textContent).not.toContain("ignored-private-value");
    expect(document.getElementById("app").classList).toContain("hidden");
    expect(mocks.rotateScope).not.toHaveBeenCalled();
  });

  it("serializes rapid tab cleanup, rotation, and render transitions", async () => {
    let finishTextCleanup;
    const textCleanupGate = new Promise((resolve) => {
      finishTextCleanup = resolve;
    });
    const order = [];
    mocks.renderText.mockImplementation((root) => {
      order.push("render:text");
      root.textContent = "text";
      return async () => {
        order.push("cleanup:text:start");
        await textCleanupGate;
        order.push("cleanup:text:end");
      };
    });
    mocks.renderRedact.mockImplementation((root) => {
      order.push("render:redact");
      root.textContent = "redact";
      return async () => {
        order.push("cleanup:redact");
      };
    });
    mocks.renderReport.mockImplementation((root) => {
      order.push("render:report");
      root.textContent = "report";
      return vi.fn().mockResolvedValue(undefined);
    });
    mocks.rotateScope.mockImplementation(async () => {
      order.push("rotate");
      return { rotated: true };
    });
    window.__TAURI__ = {
      core: { invoke: vi.fn() },
      event: { listen: vi.fn().mockResolvedValue(vi.fn()) },
    };
    await startApp();

    document.querySelector('[data-tab="redact"]').click();
    document.querySelector('[data-tab="report"]').click();
    await flush();

    expect(order).toEqual(["render:text", "cleanup:text:start"]);
    expect(mocks.rotateScope).not.toHaveBeenCalled();
    expect(mocks.renderRedact).not.toHaveBeenCalled();
    expect(mocks.renderReport).not.toHaveBeenCalled();

    finishTextCleanup();
    await flush();
    await flush();

    expect(order).toEqual([
      "render:text",
      "cleanup:text:start",
      "cleanup:text:end",
      "rotate",
      "render:redact",
      "cleanup:redact",
      "rotate",
      "render:report",
    ]);
  });

  it("never activates a replacement screen when native scope rotation fails", async () => {
    window.__TAURI__ = {
      core: { invoke: vi.fn() },
      event: { listen: vi.fn().mockResolvedValue(vi.fn()) },
    };
    mocks.rotateScope.mockRejectedValue(
      Object.assign(new Error("safe failure"), { code: "broker_busy" })
    );
    await startApp();

    document.querySelector('[data-tab="redact"]').click();
    await flush();
    await flush();

    expect(mocks.rotateScope).toHaveBeenCalledOnce();
    expect(mocks.renderRedact).not.toHaveBeenCalled();
    expect(document.getElementById("app").classList).toContain("hidden");
    expect(document.getElementById("boot").classList).not.toContain("hidden");
  });
});
