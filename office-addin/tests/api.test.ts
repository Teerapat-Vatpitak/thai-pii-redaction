import { describe, expect, it, vi } from "vitest";
import {
  ApiClient,
  ApiError,
  codePointOffsetToUtf16,
  type AnalyzeResponse,
  type DetectResponse,
  type HealthResponse,
  type ReidentifyResponse,
  type RoundtripResponse,
  type SanitizeResponse,
} from "../src/api";

const CONTRACT_HEADER = "X-AIGuard-Contract-Version";
const TOKEN = `[NAME_${"a".repeat(25)}_${"n".repeat(20)}_1]`;

const HEALTH: HealthResponse = {
  status: "ok",
  version: "2.5.0",
  contract_version: 2,
  capabilities: {
    control_token_required: false,
    api_key_required: false,
  },
};

const DETECT: DetectResponse = {
  detected_entity_count: 1,
  entity_type_counts: { NAME: 1 },
  highlights: [{ start: 1, end: 9, data_type: "NAME", redact_type: "FP" }],
};

const ANALYZE: AnalyzeResponse = {
  overall_score: 30,
  overall_grade: "B",
  risk_label: "Low Risk",
  direct_pii_count: 1,
  fp_count: 1,
  tb_count: 0,
  section26_categories: [],
  reidentification: {
    score: 10,
    grade: "A",
    quasi_identifier_categories: [],
    high_risk_combination: false,
  },
  breakdown: [{ data_type: "NAME", redact_type: "FP", count: 1 }],
  recommendations: [{
    level: "high",
    title: "Direct PII detected",
    desc: "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
  }],
};

const SANITIZE: SanitizeResponse = {
  session_id: "session-1",
  sanitized_text: `😀${TOKEN}`,
  detected_entity_count: 1,
  replacement_count: 1,
  entity_type_counts: { NAME: 1 },
  highlights: [
    {
      start: 1,
      end: 1 + Array.from(TOKEN).length,
      data_type: "NAME",
      redact_type: "FP",
    },
  ],
  section26_categories: [],
  guard_findings: [],
  warnings: [],
  safety: { status: "pass", residual_count: 0 },
};

const REIDENTIFY: ReidentifyResponse = {
  restored_text: "fixture",
  replaced_count: 1,
  leftover_count: 0,
  warnings: [],
};

const ROUNDTRIP: RoundtripResponse = {
  sanitized_text: TOKEN,
  ai_response_masked: `reply ${TOKEN}`,
  restored_text: "reply fixture",
  detected_entity_count: 1,
  entity_type_counts: { NAME: 1 },
  provider_used: "pathumma",
  section26_categories: [],
  guard_findings: [],
  warnings: [],
  safety: { status: "pass", residual_count: 0 },
  restoration: { status: "complete", replaced_count: 1, leftover_count: 0 },
};

function response(
  status: number,
  body: unknown,
  contractHeader: string | null = "2",
): Response {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (contractHeader !== null) headers.set(CONTRACT_HEADER, contractHeader);
  return new Response(JSON.stringify(body), { status, headers });
}

function duplicateHeaderResponse(status: number, body: unknown): Response {
  const headers = new Headers({ "Content-Type": "application/json" });
  headers.append(CONTRACT_HEADER, "2");
  headers.append(CONTRACT_HEADER, "2");
  return new Response(JSON.stringify(body), { status, headers });
}

function queuedClient(...responses: Response[]): {
  client: ApiClient;
  fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
} {
  const fetcher = vi.fn<typeof fetch>();
  for (const item of responses) fetcher.mockResolvedValueOnce(item);
  return { client: new ApiClient("/api", fetcher), fetcher };
}

describe("ApiClient HTTP v2 boundary", () => {
  it("does not send a PII-bearing operation when its fresh health gate fails", async () => {
    const { client, fetcher } = queuedClient(response(200, {
      ...HEALTH,
      contract_version: 1,
    }));

    await expect(client.sanitize("fixture", "token")).rejects.toMatchObject({
      code: "contract",
    });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/health");
  });

  it("uses a fresh headerless health request, then asserts contract v2 on every operation", async () => {
    const { client, fetcher } = queuedClient(
      response(200, HEALTH),
      response(200, SANITIZE),
    );

    await client.sanitize("fixture", "token");

    const healthInit = fetcher.mock.calls[0]?.[1];
    const sanitizeInit = fetcher.mock.calls[1]?.[1];
    expect(new Headers(healthInit?.headers).has(CONTRACT_HEADER)).toBe(false);
    expect(healthInit).toMatchObject({ credentials: "omit", cache: "no-store" });
    expect(new Headers(sanitizeInit?.headers).get(CONTRACT_HEADER)).toBe("2");
    expect(new Headers(sanitizeInit?.headers).get("Content-Type")).toBe("application/json");
    expect(sanitizeInit).toMatchObject({ credentials: "omit", cache: "no-store" });
    expect(new Headers(sanitizeInit?.headers).has("X-AIGuard-Key")).toBe(false);
    expect(new Headers(sanitizeInit?.headers).has("X-AIGuard-Token")).toBe(false);
  });

  it("rechecks health after startup and sends no PII after a backend restart", async () => {
    const { client, fetcher } = queuedClient(
      response(200, HEALTH),
      response(200, { ...HEALTH, contract_version: 1 }),
    );

    await expect(client.health()).resolves.toEqual(HEALTH);
    await expect(client.sanitize("fixture", "token")).rejects.toMatchObject({
      code: "contract",
    });

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/health",
      "/api/health",
    ]);
    expect(fetcher.mock.calls[1]?.[1]).toMatchObject({
      method: "GET",
      credentials: "omit",
      cache: "no-store",
    });
  });

  it("invokes fetch without binding ApiClient as its receiver", async () => {
    const fetcher = vi.fn(function (this: unknown) {
      expect(this).toBeUndefined();
      return Promise.resolve(response(200, HEALTH));
    }) as typeof fetch;

    await new ApiClient("/api", fetcher).health();
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it.each([
    ["missing", response(200, HEALTH, null)],
    ["malformed", response(200, HEALTH, "02")],
    ["mismatched", response(200, HEALTH, "1")],
    ["duplicate", duplicateHeaderResponse(200, HEALTH)],
  ])("rejects a %s health response assertion before enabling operations", async (_label, healthResponse) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(healthResponse);
    const client = new ApiClient("/api", fetcher);

    await expect(client.detect("fixture")).rejects.toMatchObject({ code: "contract" });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/health");
  });

  it("invalidates the health gate when an operation response assertion is absent", async () => {
    const { client, fetcher } = queuedClient(
      response(200, HEALTH),
      response(200, SANITIZE, null),
      response(200, HEALTH, null),
    );

    await expect(client.sanitize("fixture", "token")).rejects.toMatchObject({ code: "contract" });
    await expect(client.detect("fixture")).rejects.toMatchObject({ code: "contract" });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/health",
      "/api/sanitize",
      "/api/health",
    ]);
  });

  it("fails health closed when Office would need a data-plane credential", async () => {
    const keyRequired = {
      ...HEALTH,
      capabilities: { control_token_required: false, api_key_required: true },
    };
    const { client, fetcher } = queuedClient(response(200, keyRequired));

    await expect(client.detect("fixture")).rejects.toMatchObject({ code: "authentication" });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/health");
  });

  it("validates and freshly projects every complete v2 response", async () => {
    const { client } = queuedClient(
      response(200, HEALTH),
      response(200, DETECT),
      response(200, HEALTH),
      response(200, ANALYZE),
      response(200, HEALTH),
      response(200, SANITIZE),
      response(200, HEALTH),
      response(200, REIDENTIFY),
      response(200, HEALTH),
      response(200, ROUNDTRIP),
    );

    await expect(client.detect("😀[NAME_1]")).resolves.toEqual(DETECT);
    await expect(client.analyze("fixture")).resolves.toEqual(ANALYZE);
    await expect(client.sanitize("fixture", "token")).resolves.toEqual(SANITIZE);
    await expect(client.reidentify("session-1", "fixture")).resolves.toEqual(REIDENTIFY);
    await expect(client.roundtrip("fixture", "token")).resolves.toEqual(ROUNDTRIP);
  });

  it("constructs a fresh DTO instead of passing through a backend object", async () => {
    const raw = structuredClone(SANITIZE);
    const rawResponse = {
      ok: true,
      status: 200,
      headers: new Headers({ [CONTRACT_HEADER]: "2" }),
      json: vi.fn().mockResolvedValue(raw),
    } as unknown as Response;
    const { client } = queuedClient(response(200, HEALTH), rawResponse);

    const projected = await client.sanitize("fixture", "token");
    expect(projected).not.toBe(raw);
    expect(projected.highlights).not.toBe(raw.highlights);
    expect(projected.safety).not.toBe(raw.safety);
  });

  it.each([
    ["health", { status: "ok", version: "2.5.0", contract_version: 2 }, "health"],
    ["detect", { detected_entity_count: 0, entity_type_counts: {} }, "detect"],
    ["analyze", { ...ANALYZE, recommendations: undefined }, "analyze"],
    ["sanitize", { ...SANITIZE, safety: undefined }, "sanitize"],
    ["reidentify", { ...REIDENTIFY, leftover_count: undefined }, "reidentify"],
    ["roundtrip", { ...ROUNDTRIP, restoration: undefined }, "roundtrip"],
  ])("rejects missing or malformed required fields: %s", async (_label, body, endpoint) => {
    const responses = endpoint === "health"
      ? [response(200, body)]
      : [response(200, HEALTH), response(200, body)];
    const { client } = queuedClient(...responses);
    const call = endpoint === "health"
      ? client.health()
      : endpoint === "detect"
        ? client.detect("fixture")
        : endpoint === "analyze"
          ? client.analyze("fixture")
          : endpoint === "sanitize"
            ? client.sanitize("fixture", "token")
            : endpoint === "reidentify"
              ? client.reidentify("session-1", "fixture")
              : client.roundtrip("fixture", "token");
    await expect(call).rejects.toMatchObject({ code: "contract" });
  });

  it.each([
    ["health top level", { ...HEALTH, token_required: false }, "health"],
    ["health capabilities", { ...HEALTH, capabilities: { ...HEALTH.capabilities, token: "forbidden" } }, "health"],
    ["detect highlight", { ...DETECT, highlights: [{ ...DETECT.highlights[0], token: "[NAME_1]" }] }, "detect"],
    ["analyze recommendation", {
      ...ANALYZE,
      recommendations: [{ ...ANALYZE.recommendations[0], original: "forbidden" }],
    }, "analyze"],
    ["sanitize top level", { ...SANITIZE, original_text: "forbidden" }, "sanitize"],
    ["sanitize safety", { ...SANITIZE, safety: { ...SANITIZE.safety, override: true } }, "sanitize"],
    ["reidentify mapping", { ...REIDENTIFY, replaced: [{ token: "[NAME_1]", original: "forbidden" }] }, "reidentify"],
    ["roundtrip restoration", {
      ...ROUNDTRIP,
      restoration: { ...ROUNDTRIP.restoration, leftover_tokens: ["[NAME_1]"] },
    }, "roundtrip"],
  ])("rejects unknown fields recursively: %s", async (_label, body, endpoint) => {
    const responses = endpoint === "health"
      ? [response(200, body)]
      : [response(200, HEALTH), response(200, body)];
    const { client } = queuedClient(...responses);

    const call = endpoint === "health"
      ? client.health()
      : endpoint === "detect"
        ? client.detect("😀[NAME_1]")
        : endpoint === "analyze"
          ? client.analyze("fixture")
          : endpoint === "sanitize"
            ? client.sanitize("fixture", "token")
            : endpoint === "reidentify"
              ? client.reidentify("session-1", "fixture")
              : client.roundtrip("fixture", "token");
    await expect(call).rejects.toMatchObject({
      code: "contract",
      message: "รูปแบบคำตอบจาก AI Guard ไม่ถูกต้อง",
    });
  });

  it("rejects count, offset, safety, restoration, and selected-provider mismatches", async () => {
    const invalidBodies = [
      { ...DETECT, detected_entity_count: 2 },
      {
        ...SANITIZE,
        highlights: [
          {
            ...SANITIZE.highlights[0],
            end: [...SANITIZE.sanitized_text].length + 1,
          },
        ],
      },
      {
        ...SANITIZE,
        detected_entity_count: 2,
        entity_type_counts: { NAME: 2 },
      },
      { ...SANITIZE, safety: { status: "pass", residual_count: 1 } },
      { ...ROUNDTRIP, provider_used: "other-provider" },
      {
        ...ROUNDTRIP,
        restoration: { status: "complete", replaced_count: 1, leftover_count: 1 },
      },
      {
        ...ROUNDTRIP,
        warnings: [{ code: "generated_pii", count: 1 }],
        restoration: { status: "complete", replaced_count: 1, leftover_count: 0 },
      },
    ];

    for (const [index, body] of invalidBodies.entries()) {
      const endpoint = index === 0 ? "detect" : index < 4 ? "sanitize" : "roundtrip";
      const { client } = queuedClient(response(200, HEALTH), response(200, body));
      const call = endpoint === "detect"
        ? client.detect("😀[NAME_1]")
        : endpoint === "sanitize"
          ? client.sanitize("fixture", "token")
          : client.roundtrip("fixture", "token");
      await expect(call).rejects.toMatchObject({ code: "contract" });
    }
  });

  it.each([
    ["sanitize", {
      ...SANITIZE,
      sanitized_text: "",
      detected_entity_count: 0,
      replacement_count: 0,
      entity_type_counts: {},
      highlights: [],
    }],
    ["roundtrip", { ...ROUNDTRIP, sanitized_text: "" }],
  ])("rejects empty masked text from %s", async (endpoint, body) => {
    const { client } = queuedClient(response(200, HEALTH), response(200, body));
    const call = endpoint === "sanitize"
      ? client.sanitize("fixture", "token")
      : client.roundtrip("fixture", "token");

    await expect(call).rejects.toMatchObject({ code: "contract" });
  });

  it("uses Unicode code-point offsets and converts them before JavaScript slicing", () => {
    const text = "😀ก\u0E49[NAME_1]";
    expect(codePointOffsetToUtf16(text, 0)).toBe(0);
    expect(codePointOffsetToUtf16(text, 1)).toBe(2);
    expect(codePointOffsetToUtf16(text, 3)).toBe(4);
    expect(codePointOffsetToUtf16(text, 11)).toBe(text.length);
    expect(() => codePointOffsetToUtf16(text, 12)).toThrow("invalid response shape");
  });

  it.each([
    ["an ordered subset", [
      ANALYZE.recommendations[0],
      {
        level: "medium",
        title: "High re-identification risk",
        desc: "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
      },
      {
        level: "info",
        title: "Consider data minimization",
        desc: "เก็บเฉพาะข้อมูลที่จำเป็นตามวัตถุประสงค์ที่กำหนด ตาม PDPA มาตรา 22",
      },
    ]],
    ["the clear singleton", [{
      level: "info",
      title: "No significant PDPA risk detected",
      desc: "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
    }]],
  ])("accepts canonical analyze recommendations: %s", async (_label, recommendations) => {
    const valid = { ...ANALYZE, recommendations };
    const { client } = queuedClient(response(200, HEALTH), response(200, valid));
    await expect(client.analyze("fixture")).resolves.toEqual(valid);
  });

  it.each([
    ["arbitrary text", [{
      level: "high",
      title: "Direct PII detected",
      desc: "arbitrary backend text",
    }]],
    ["reversed templates", [
      {
        level: "medium",
        title: "High re-identification risk",
        desc: "ลดการรวมข้อมูลกึ่งระบุตัวบุคคลก่อนนำข้อมูลไปใช้",
      },
      {
        level: "high",
        title: "Direct PII detected",
        desc: "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
      },
    ]],
    ["clear template mixed with another", [
      {
        level: "high",
        title: "Direct PII detected",
        desc: "ใช้ AI Guard เพื่อปกปิดข้อมูลทั้งหมดก่อนส่งให้ AI ภายนอก",
      },
      {
        level: "info",
        title: "No significant PDPA risk detected",
        desc: "ไม่พบข้อมูลส่วนบุคคลที่มีความเสี่ยงสูงในข้อความนี้",
      },
    ]],
  ])("rejects non-canonical analyze recommendations: %s", async (_label, recommendations) => {
    const invalid = { ...ANALYZE, recommendations };
    const { client } = queuedClient(response(200, HEALTH), response(200, invalid));
    await expect(client.analyze("fixture")).rejects.toMatchObject({ code: "contract" });
  });

  it("rejects analyze breakdown rows whose FP/TB subtotals disagree", async () => {
    const invalid = {
      ...ANALYZE,
      fp_count: 0,
      tb_count: 1,
    };
    const { client } = queuedClient(response(200, HEALTH), response(200, invalid));

    await expect(client.analyze("fixture")).rejects.toMatchObject({ code: "contract" });
  });

  it("validates safe v2 error envelopes and never displays backend-controlled text", async () => {
    const errorBody = {
      error: {
        code: "provider_configuration",
        category: "configuration",
        count: 0,
        retryable: false,
        status: 503,
      },
    };
    const { client } = queuedClient(response(200, HEALTH), response(503, errorBody));

    await expect(client.roundtrip("fixture", "token")).rejects.toMatchObject({
      code: "missing-key",
      status: 503,
      message: expect.not.stringContaining("provider_configuration"),
    });
  });

  it("maps a v2 session error to an opaque expiry failure", async () => {
    const body = {
      error: {
        code: "session_unavailable",
        category: "session",
        count: 0,
        retryable: false,
        status: 404,
      },
    };
    const { client } = queuedClient(response(200, HEALTH), response(404, body));
    await expect(client.reidentify("opaque-session", "fixture")).rejects.toMatchObject({
      code: "expired",
      status: 404,
    });
  });

  it("rejects restore warnings outside their canonical order", async () => {
    const body = {
      ...REIDENTIFY,
      warnings: [
        { code: "foreign_replacement", count: 1 },
        { code: "generated_pii", count: 1 },
      ],
    };
    const { client } = queuedClient(response(200, HEALTH), response(200, body));

    await expect(client.reidentify("opaque-session", "fixture")).rejects.toMatchObject({
      code: "contract",
    });
  });

  it("rejects nonzero counts for fixed-zero error codes", async () => {
    const body = {
      error: {
        code: "provider_configuration",
        category: "configuration",
        count: 1,
        retryable: false,
        status: 503,
      },
    };
    const { client } = queuedClient(response(200, HEALTH), response(503, body));

    await expect(client.roundtrip("fixture", "token")).rejects.toMatchObject({
      code: "contract",
    });
  });

  it.each([
    [
      "residual PII",
      422,
      {
        error: {
          code: "residual_pii",
          category: "privacy",
          count: 2,
          retryable: false,
          status: 422,
        },
      },
      "privacy",
    ],
    [
      "incomplete TNER",
      502,
      {
        error: {
          code: "ner_incomplete",
          category: "upstream",
          count: 2,
          retryable: false,
          status: 502,
        },
      },
      "provider",
    ],
    [
      "unavailable TNER",
      503,
      {
        error: {
          code: "ner_unavailable",
          category: "network",
          count: 2,
          retryable: true,
          status: 503,
        },
      },
      "provider",
    ],
  ])("accepts the defined count semantics for %s", async (_label, status, body, code) => {
    const { client } = queuedClient(response(200, HEALTH), response(status, body));

    await expect(client.roundtrip("fixture", "token")).rejects.toMatchObject({ code });
  });

  it("rejects malformed error envelopes and error responses without v2 assertion", async () => {
    for (const invalidResponse of [
      response(503, {
        error: {
          code: "provider_configuration",
          category: "configuration",
          count: 0,
          retryable: false,
          status: 502,
          detail: "forbidden",
        },
      }),
      response(503, {
        error: {
          code: "provider_configuration",
          category: "configuration",
          count: 0,
          retryable: false,
          status: 503,
        },
      }, null),
    ]) {
      const { client } = queuedClient(response(200, HEALTH), invalidResponse);
      await expect(client.roundtrip("fixture", "token")).rejects.toBeInstanceOf(ApiError);
    }
  });

  it("reports backend offline without exposing a request body and requires health again", async () => {
    const fetcher = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response(200, HEALTH))
      .mockRejectedValueOnce(new Error("network detail"))
      .mockResolvedValueOnce(response(200, HEALTH, null));
    const client = new ApiClient("/api", fetcher);

    await expect(client.detect("fixture")).rejects.toMatchObject({ code: "offline", status: 0 });
    await expect(client.detect("fixture")).rejects.toMatchObject({ code: "contract", status: 200 });
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/health",
      "/api/detect",
      "/api/health",
    ]);
  });
});
