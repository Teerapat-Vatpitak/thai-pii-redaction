import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({
  copyMasked: vi.fn(),
  disposeSession: vi.fn(),
  sanitize: vi.fn(),
  reidentify: vi.fn(),
}));

import { copyMasked, disposeSession, reidentify, sanitize } from "../src/api.js";
import { renderText } from "../src/screen-text.js";

const TOKEN = `[ชื่อ_${"a".repeat(25)}_${"n".repeat(20)}_1]`;

function validSanitize(overrides = {}) {
  return {
    session_id: "session",
    sanitized_text: `😀 ${TOKEN}`,
    detected_entity_count: 1,
    replacement_count: 1,
    entity_type_counts: { NAME: 1 },
    highlights: [
      {
        start: 2,
        end: 2 + Array.from(TOKEN).length,
        data_type: "NAME",
        redact_type: "TB",
      },
    ],
    section26_categories: [],
    guard_findings: [],
    warnings: [],
    safety: { status: "pass", residual_count: 0 },
    ...overrides,
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => {
  document.body.innerHTML = '<div id="root"></div>';
  vi.clearAllMocks();
  copyMasked.mockResolvedValue({ copied: true });
});

describe("Desktop text write boundary", () => {
  it("highlights sanitized-space code-point offsets and copies only a safe result", async () => {
    sanitize.mockResolvedValue(validSanitize());
    const root = document.getElementById("root");
    renderText(root);
    root.querySelector("#t-input").value = "synthetic";
    root.querySelector("#t-mask").click();
    await flush();

    expect(root.querySelector("#t-masked").innerHTML).toContain(
      `<span class="chip chip--token">${TOKEN}</span>`
    );
    root.querySelector("#t-copy").click();
    await flush();
    expect(copyMasked).toHaveBeenCalledWith("session", `😀 ${TOKEN}`);
  });

  it("preserves source whitespace and Unicode exactly through sanitize and copy", async () => {
    const source = "  \r\nA\u0301 นาย ก\u200b  ";
    const sanitized = `  \r\nA\u0301 ${TOKEN}\u200b  `;
    const tokenStart = Array.from(sanitized.slice(0, sanitized.indexOf(TOKEN))).length;
    sanitize.mockResolvedValue(
      validSanitize({
        sanitized_text: sanitized,
        highlights: [
          {
            start: tokenStart,
            end: tokenStart + Array.from(TOKEN).length,
            data_type: "NAME",
            redact_type: "TB",
          },
        ],
      })
    );
    const root = document.getElementById("root");
    renderText(root);
    root.querySelector("#t-input").value = source;
    const browserSource = root.querySelector("#t-input").value;
    root.querySelector("#t-mask").click();
    await flush();

    expect(sanitize).toHaveBeenCalledWith(browserSource, "token");
    root.querySelector("#t-copy").click();
    await flush();
    expect(copyMasked).toHaveBeenCalledWith("session", sanitized);
  });

  it("does not expose or copy a response with unsafe safety state", async () => {
    sanitize.mockResolvedValue(
      validSanitize({ safety: { status: "pass", residual_count: 1 } })
    );
    const root = document.getElementById("root");
    renderText(root);
    root.querySelector("#t-input").value = "synthetic";
    root.querySelector("#t-mask").click();
    await flush();

    expect(root.querySelector("#t-out").classList).toContain("hidden");
    expect(root.textContent).not.toContain(TOKEN);
    expect(copyMasked).not.toHaveBeenCalled();
  });

  it("does not expose or copy an empty sanitize success payload", async () => {
    sanitize.mockResolvedValue(
      validSanitize({
        sanitized_text: "",
        detected_entity_count: 0,
        replacement_count: 0,
        entity_type_counts: {},
        highlights: [],
      })
    );
    const root = document.getElementById("root");
    renderText(root);
    root.querySelector("#t-input").value = "synthetic";
    root.querySelector("#t-mask").click();
    await flush();

    expect(root.querySelector("#t-out").classList).toContain("hidden");
    expect(root.querySelector("#t-err").classList).not.toContain("hidden");
    root.querySelector("#t-copy").click();
    await flush();
    expect(copyMasked).not.toHaveBeenCalled();
  });

  it("does not render an incomplete or warning-bearing restoration", async () => {
    sanitize.mockResolvedValue(validSanitize());
    reidentify.mockResolvedValue({
      restored_text: "synthetic restored",
      replaced_count: 1,
      leftover_count: 1,
      warnings: [],
    });
    const root = document.getElementById("root");
    renderText(root);
    root.querySelector("#t-input").value = "synthetic";
    root.querySelector("#t-mask").click();
    await flush();
    root.querySelector("#t-reply").value = TOKEN;
    root.querySelector("#t-restore").click();
    await flush();

    expect(root.querySelector("#t-restored").classList).toContain("hidden");
    expect(root.textContent).not.toContain("synthetic restored");
  });

  it("reuses one session so an older masked reply keeps its mapping", async () => {
    sanitize
      .mockResolvedValueOnce(
        validSanitize({
          session_id: "session-1",
          sanitized_text: "[โทรศัพท์_1]",
          highlights: [
            {
              start: 0,
              end: 12,
              data_type: "PHONE",
              redact_type: "FP",
            },
          ],
        })
      )
      .mockResolvedValueOnce(
        validSanitize({
          session_id: "session-1",
          sanitized_text: "[โทรศัพท์_2]",
          highlights: [
            {
              start: 0,
              end: 12,
              data_type: "PHONE",
              redact_type: "FP",
            },
          ],
        })
      );
    reidentify.mockResolvedValue({
      restored_text: "081-234-5678",
      replaced_count: 1,
      leftover_count: 0,
      warnings: [],
    });
    const root = document.getElementById("root");
    renderText(root);

    root.querySelector("#t-input").value = "081-234-5678";
    root.querySelector("#t-mask").click();
    await flush();
    root.querySelector("#t-input").value = "099-999-9999";
    root.querySelector("#t-mask").click();
    await flush();
    root.querySelector("#t-reply").value = "[โทรศัพท์_1]";
    root.querySelector("#t-restore").click();
    await flush();

    expect(sanitize).toHaveBeenNthCalledWith(1, "081-234-5678", "token");
    expect(sanitize).toHaveBeenNthCalledWith(
      2,
      "099-999-9999",
      "token",
      "session-1"
    );
    expect(reidentify).toHaveBeenCalledWith("session-1", "[โทรศัพท์_1]");
    expect(root.querySelector("#t-restored").textContent).toBe("081-234-5678");
  });

  it("invalidates stale session authority and never retries an ambiguous mutation", async () => {
    sanitize
      .mockResolvedValueOnce(validSanitize({ session_id: "stale-session" }))
      .mockRejectedValueOnce(
        Object.assign(new Error("safe failure"), {
          name: "ApiError",
          code: "operation_failed",
          sessionInvalidated: true,
        })
      );
    const root = document.getElementById("root");
    renderText(root);

    root.querySelector("#t-input").value = "first";
    root.querySelector("#t-mask").click();
    await flush();
    root.querySelector("#t-input").value = "second";
    root.querySelector("#t-mask").click();
    await flush();

    expect(sanitize).toHaveBeenNthCalledWith(2, "second", "token", "stale-session");
    expect(sanitize).toHaveBeenCalledTimes(2);
    expect(root.querySelector("#t-out").classList).toContain("hidden");
    expect(copyMasked).not.toHaveBeenCalled();
  });

  it("invalidates cached publication when native copy authority is gone", async () => {
    sanitize.mockResolvedValue(validSanitize());
    copyMasked.mockRejectedValue(
      Object.assign(new Error("safe failure"), {
        name: "ApiError",
        code: "session_unavailable",
        sessionInvalidated: true,
      })
    );
    const root = document.getElementById("root");
    renderText(root);
    root.querySelector("#t-input").value = "synthetic";
    root.querySelector("#t-mask").click();
    await flush();

    root.querySelector("#t-copy").click();
    await flush();
    root.querySelector("#t-copy").click();
    await flush();

    expect(copyMasked).toHaveBeenCalledTimes(1);
    expect(root.querySelector("#t-out").classList).toContain("hidden");
  });

  it("invalidates published text locally without issuing a data operation", async () => {
    sanitize.mockResolvedValue(validSanitize());
    const root = document.getElementById("root");
    const cleanup = renderText(root);
    root.querySelector("#t-input").value = "synthetic-private-value";
    root.querySelector("#t-mask").click();
    await flush();
    root.querySelector("#t-reply").value = TOKEN;

    cleanup.invalidatePublication();

    expect(root.querySelector("#t-input").value).toBe("");
    expect(root.querySelector("#t-reply").value).toBe("");
    expect(root.querySelector("#t-masked").textContent).toBe("");
    expect(root.querySelector("#t-restored").textContent).toBe("");
    expect(root.querySelector("#t-out").classList).toContain("hidden");
    root.querySelector("#t-copy").click();
    await flush();
    expect(copyMasked).not.toHaveBeenCalled();
    expect(disposeSession).not.toHaveBeenCalled();
  });
});
