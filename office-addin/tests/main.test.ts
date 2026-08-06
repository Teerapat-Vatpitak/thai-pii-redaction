import { afterEach, describe, expect, it, vi } from "vitest";

const CONTRACT_HEADER = "X-AIGuard-Contract-Version";

function installTaskPaneDom(): void {
  document.body.innerHTML = `
    <section id="backend-banner"></section>
    <p id="host-note"></p>
    <p id="summary"></p>
    <pre id="output"></pre>
    <ul id="warnings"></ul>
    <span id="state-pill"></span>
    <select id="mode"><option value="token" selected>Token</option></select>
    <textarea id="prompt"></textarea>
    <button data-action="detect">Detect</button>
    <button data-action="analyze">Analyze</button>
    <button data-action="mask">Mask</button>
    <button data-action="restore">Restore</button>
    <button data-action="apply">Apply</button>
    <button data-action="ask">Ask</button>
    <button data-action="insert">Insert</button>
    <button data-action="copy">Copy</button>
  `;
}

function healthResponse(
  apiKeyRequired = false,
  controlTokenRequired = true,
): Response {
  return new Response(JSON.stringify({
    status: "ok",
    version: "2.5.0",
    contract_version: 2,
    capabilities: {
      control_token_required: controlTokenRequired,
      api_key_required: apiKeyRequired,
    },
  }), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      [CONTRACT_HEADER]: "2",
    },
  });
}

function apiResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      [CONTRACT_HEADER]: "2",
    },
  });
}

afterEach(() => {
  vi.resetModules();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "clipboard");
  document.body.replaceChildren();
});

describe("Office task-pane startup boundary", () => {
  it("keeps every operation disabled while health is pending, then enables only after v2 passes", async () => {
    installTaskPaneDom();
    type ReadyInfo = { host: Office.HostType; platform: Office.PlatformType };
    let readyCallback: ((info: ReadyInfo) => Promise<void>) | undefined;
    vi.stubGlobal("Office", {
      HostType: { Word: 0, Excel: 1, PowerPoint: 2 },
      PlatformType: { PC: 0 },
      onReady(callback: (info: ReadyInfo) => Promise<void>) {
        readyCallback = callback;
      },
    });
    let resolveHealth!: (value: Response) => void;
    const pendingHealth = new Promise<Response>((resolve) => {
      resolveHealth = resolve;
    });
    const fetcher = vi.fn<typeof fetch>().mockReturnValue(pendingHealth);
    vi.stubGlobal("fetch", fetcher);

    await import("../src/main");
    const startup = readyCallback?.({
      host: 0 as Office.HostType,
      platform: 0 as Office.PlatformType,
    });
    await Promise.resolve();

    expect(fetcher).toHaveBeenCalledOnce();
    for (const action of document.querySelectorAll<HTMLButtonElement>("button[data-action]")) {
      expect(action.disabled).toBe(true);
    }
    expect(document.querySelector<HTMLSelectElement>("#mode")?.disabled).toBe(true);

    resolveHealth(healthResponse());
    await startup;

    expect(document.querySelector<HTMLButtonElement>('button[data-action="detect"]')?.disabled).toBe(false);
    expect(document.querySelector<HTMLButtonElement>('button[data-action="mask"]')?.disabled).toBe(false);
    expect(document.querySelector<HTMLButtonElement>('button[data-action="copy"]')?.disabled).toBe(true);
    expect(document.querySelector<HTMLSelectElement>("#mode")?.disabled).toBe(false);
  });

  it("leaves operations disabled when the strict health gate requires an API key", async () => {
    installTaskPaneDom();
    type ReadyInfo = { host: Office.HostType; platform: Office.PlatformType };
    let readyCallback: ((info: ReadyInfo) => Promise<void>) | undefined;
    vi.stubGlobal("Office", {
      HostType: { Word: 0, Excel: 1, PowerPoint: 2 },
      PlatformType: { PC: 0 },
      onReady(callback: (info: ReadyInfo) => Promise<void>) {
        readyCallback = callback;
      },
    });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(healthResponse(true)));

    await import("../src/main");
    await readyCallback?.({
      host: 0 as Office.HostType,
      platform: 0 as Office.PlatformType,
    });

    for (const action of document.querySelectorAll<HTMLButtonElement>("button[data-action]")) {
      expect(action.disabled).toBe(true);
    }
    expect(document.querySelector<HTMLSelectElement>("#mode")?.disabled).toBe(true);
  });

  it.each([
    [false, true],
    [true, false],
  ])(
    "handles a backend without control-plane protection when API-key-required is %s",
    async (apiKeyRequired, expectedReady) => {
      installTaskPaneDom();
      type ReadyInfo = { host: Office.HostType; platform: Office.PlatformType };
      let readyCallback: ((info: ReadyInfo) => Promise<void>) | undefined;
      vi.stubGlobal("Office", {
        HostType: { Word: 0, Excel: 1, PowerPoint: 2 },
        PlatformType: { PC: 0 },
        onReady(callback: (info: ReadyInfo) => Promise<void>) {
          readyCallback = callback;
        },
      });
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>().mockResolvedValue(healthResponse(apiKeyRequired, false)),
      );

      await import("../src/main");
      await readyCallback?.({
        host: 0 as Office.HostType,
        platform: 0 as Office.PlatformType,
      });

      expect(document.querySelector<HTMLSelectElement>("#mode")?.disabled).toBe(!expectedReady);
      expect(document.querySelector<HTMLElement>("#backend-banner")?.className).toBe(
        expectedReady ? "banner ok" : "banner error",
      );
      expect(document.querySelector<HTMLButtonElement>(
        'button[data-action="detect"]',
      )?.disabled).toBe(!expectedReady);
    },
  );

  it.each([
    [
      "missing v2 assertion",
      new Response(JSON.stringify({
        status: "ok",
        version: "2.5.0",
        contract_version: 2,
        capabilities: {
          control_token_required: true,
          api_key_required: false,
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    ],
    [
      "missing capability",
      apiResponse({
        status: "ok",
        version: "2.5.0",
        contract_version: 2,
        capabilities: { control_token_required: true },
      }),
    ],
    [
      "unknown capability",
      apiResponse({
        status: "ok",
        version: "2.5.0",
        contract_version: 2,
        capabilities: {
          control_token_required: true,
          api_key_required: false,
          token: "must-not-cross",
        },
      }),
    ],
    [
      "wrong contract version",
      apiResponse({
        status: "ok",
        version: "2.5.0",
        contract_version: 1,
        capabilities: {
          control_token_required: true,
          api_key_required: false,
        },
      }),
    ],
  ])("keeps every operation disabled at startup for %s", async (_label, response) => {
    installTaskPaneDom();
    type ReadyInfo = { host: Office.HostType; platform: Office.PlatformType };
    let readyCallback: ((info: ReadyInfo) => Promise<void>) | undefined;
    vi.stubGlobal("Office", {
      HostType: { Word: 0, Excel: 1, PowerPoint: 2 },
      PlatformType: { PC: 0 },
      onReady(callback: (info: ReadyInfo) => Promise<void>) {
        readyCallback = callback;
      },
    });
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(response));

    await import("../src/main");
    await readyCallback?.({
      host: 0 as Office.HostType,
      platform: 0 as Office.PlatformType,
    });

    for (const action of document.querySelectorAll<HTMLButtonElement>("button[data-action]")) {
      expect(action.disabled).toBe(true);
    }
    expect(document.querySelector<HTMLSelectElement>("#mode")?.disabled).toBe(true);
    expect(document.querySelector<HTMLElement>("#backend-banner")?.className).toBe("banner error");
  });

  it("sends no PII request or Office write when the operation health gate becomes invalid", async () => {
    installTaskPaneDom();
    type ReadyInfo = { host: Office.HostType; platform: Office.PlatformType };
    let readyCallback: ((info: ReadyInfo) => Promise<void>) | undefined;
    vi.stubGlobal("Office", {
      HostType: { Word: 0, Excel: 1, PowerPoint: 2 },
      PlatformType: { PC: 0 },
      onReady(callback: (info: ReadyInfo) => Promise<void>) {
        readyCallback = callback;
      },
    });
    const getCell = vi.fn();
    const range = {
      address: "Sheet1!A1",
      values: [["synthetic name"]],
      formulas: [["synthetic name"]],
      text: [["synthetic name"]],
      load: vi.fn(),
      getCell,
    };
    vi.stubGlobal("Excel", {
      run: async (callback: (context: unknown) => Promise<unknown>) => callback({
        workbook: { getSelectedRange: () => range },
        sync: vi.fn().mockResolvedValue(undefined),
      }),
    });
    const invalidHealth = apiResponse({
      status: "ok",
      version: "2.5.0",
      contract_version: 1,
      capabilities: {
        control_token_required: true,
        api_key_required: false,
      },
    });
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(healthResponse())
      .mockResolvedValueOnce(invalidHealth);
    vi.stubGlobal("fetch", fetcher);

    await import("../src/main");
    await readyCallback?.({
      host: 1 as Office.HostType,
      platform: 0 as Office.PlatformType,
    });
    document.querySelector<HTMLButtonElement>('button[data-action="mask"]')?.click();

    await vi.waitFor(() => {
      expect(document.querySelector<HTMLElement>("#state-pill")?.textContent).toBe("error");
    });
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/health",
      "/api/health",
    ]);
    expect(document.querySelector<HTMLButtonElement>('button[data-action="apply"]')?.disabled).toBe(true);
    document.querySelector<HTMLButtonElement>('button[data-action="apply"]')?.click();
    expect(getCell).not.toHaveBeenCalled();
  });

  it("never places skipped Excel values in Preview or the clipboard", async () => {
    installTaskPaneDom();
    type ReadyInfo = { host: Office.HostType; platform: Office.PlatformType };
    let readyCallback: ((info: ReadyInfo) => Promise<void>) | undefined;
    vi.stubGlobal("Office", {
      HostType: { Word: 0, Excel: 1, PowerPoint: 2 },
      PlatformType: { PC: 0 },
      onReady(callback: (info: ReadyInfo) => Promise<void>) {
        readyCallback = callback;
      },
    });
    const range = {
      address: "Sheet1!A1:E1",
      values: [["synthetic name", 424242, "formula result", 45123, ""]],
      formulas: [["synthetic name", 424242, "=\"synthetic secret\"", 45123, ""]],
      text: [["synthetic name", "424242", "formula result", "1/1/2023", ""]],
      load: vi.fn(),
    };
    vi.stubGlobal("Excel", {
      run: async (callback: (context: unknown) => Promise<unknown>) => callback({
        workbook: { getSelectedRange: () => range },
        sync: vi.fn().mockResolvedValue(undefined),
      }),
    });
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(healthResponse())
      .mockResolvedValueOnce(healthResponse())
      .mockResolvedValueOnce(apiResponse({
        session_id: "session-1",
        sanitized_text: "[NAME_1]",
        detected_entity_count: 1,
        replacement_count: 1,
        entity_type_counts: { NAME: 1 },
        highlights: [{ start: 0, end: 8, data_type: "NAME", redact_type: "FP" }],
        section26_categories: [],
        guard_findings: [],
        warnings: [],
        safety: { status: "pass", residual_count: 0 },
      }));
    vi.stubGlobal("fetch", fetcher);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    await import("../src/main");
    await readyCallback?.({
      host: 1 as Office.HostType,
      platform: 0 as Office.PlatformType,
    });
    document.querySelector<HTMLButtonElement>('button[data-action="mask"]')?.click();

    await vi.waitFor(() => {
      expect(fetcher).toHaveBeenCalledTimes(3);
      expect(document.querySelector<HTMLButtonElement>('button[data-action="copy"]')?.disabled).toBe(true);
    });
    const preview = document.querySelector<HTMLElement>("#output")?.textContent ?? "";
    expect(preview).toContain("[NAME_1]");
    expect(preview).not.toContain("424242");
    expect(preview).not.toContain("formula result");
    expect(preview).not.toContain("45123");
    expect(preview).not.toContain("1/1/2023");

    document.querySelector<HTMLButtonElement>('button[data-action="copy"]')?.click();
    expect(writeText).not.toHaveBeenCalled();
  });
});
