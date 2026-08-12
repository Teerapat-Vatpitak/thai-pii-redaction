// AI Guard MV3 transport owner. Installed production uses one Chrome Native
// Messaging port; content scripts and side panels never open native transport.

if (!globalThis.AIGUARD_CONTRACT_V2 && typeof importScripts === "function") {
  importScripts("contract-v2.js");
}
const CONTRACT = globalThis.AIGUARD_CONTRACT_V2;
if (!CONTRACT) throw new Error("contract-unavailable");

const NATIVE_HOST = "th.ac.psu.aiguard.native_host";
const NATIVE_PROTOCOL_VERSION = 1;
const MAX_NATIVE_RESPONSE_BYTES = 1024 * 1024;
const MAX_TEXT_CODE_POINTS = 200000;
const MAX_PENDING = 128;
const PANEL_PORT_NAME = "aiguard-side-panel-v1";
const NATIVE_ERRORS = new Set([
  "broker_busy",
  "broker_incompatible",
  "broker_unauthorized",
  "broker_unavailable",
  "dependency_unavailable",
  "document_invalid",
  "ner_incomplete",
  "ner_unavailable",
  "ocr_unavailable",
  "operation_failed",
  "operation_timeout",
  "payload_too_large",
  "provider_configuration",
  "provider_rejected",
  "provider_response_invalid",
  "provider_unavailable",
  "request_invalid",
  "residual_pii",
  "restore_failed",
  "session_unavailable",
]);

const workerNonce = randomToken();
const tabContexts = new Map();
const panelContexts = new Map();
const pending = new Map();
let nativePort = null;
let nativeReady = null;
let nativeGeneration = 0;
let requestCounter = 0;
let reconnectAttempts = 0;
let reconnectTimer = null;

function randomToken() {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function exactObject(value, keys) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
    ? value
    : null;
}

function validId(value) {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(value);
}

function validText(value) {
  return typeof value === "string" && Array.from(value).length <= MAX_TEXT_CODE_POINTS;
}

function unavailable(error = "native-unavailable") {
  return { ok: false, status: 0, error };
}

function enableSidePanelOnClick() {
  if (!chrome.sidePanel || !chrome.sidePanel.setPanelBehavior) return;
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}
chrome.runtime.onInstalled.addListener(enableSidePanelOnClick);
enableSidePanelOnClick();

async function clearLegacySessionState() {
  try {
    await chrome.storage.session.clear();
  } catch {
    // No broker or backend handle is retained in JavaScript memory or storage.
  }
}

function httpsOrigin(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" ? parsed.origin : null;
  } catch {
    return null;
  }
}

function admittedTabSender(sender) {
  if (!sender || !sender.tab || !Number.isInteger(sender.tab.id) || sender.tab.id < 0) {
    return null;
  }
  if (sender.frameId !== 0) return null;
  if (sender.documentLifecycle && sender.documentLifecycle !== "active") return null;
  if (typeof sender.documentId !== "string" || sender.documentId.length === 0) return null;
  const evidence = [sender.origin, sender.url, sender.tab.url].filter(
    (value) => typeof value === "string" && value.length > 0
  );
  if (evidence.length === 0) return null;
  const origins = evidence.map(httpsOrigin);
  if (origins.some((origin) => !origin || origin !== origins[0])) return null;
  return {
    tabId: sender.tab.id,
    origin: origins[0],
    documentId: sender.documentId,
  };
}

function nextContextId(kind, stablePart) {
  requestCounter += 1;
  return `${kind}-${stablePart}-${workerNonce}-${requestCounter}`;
}

function makeContext(kind, stablePart, origin = null, documentId = null) {
  return {
    contextId: nextContextId(kind, stablePart),
    documentId,
    generation: nativeGeneration,
    hasSession: false,
    mode: null,
    opened: false,
    opening: null,
    origin,
    revision: 1,
  };
}

function scheduleReconnect() {
  if (reconnectTimer !== null || reconnectAttempts >= 3) return;
  const delay = 250 * 2 ** reconnectAttempts;
  reconnectAttempts += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    void ensureNativeReady();
  }, delay);
}

function notifyUnavailable() {
  for (const [tabId] of tabContexts) {
    try {
      const promise = chrome.tabs.sendMessage(tabId, {
        type: "aiguard-native-state",
        state: "session-expired",
      });
      if (promise && typeof promise.catch === "function") promise.catch(() => {});
    } catch {
      // A closing tab needs no notification.
    }
  }
  for (const { port } of panelContexts.values()) {
    try {
      port.postMessage({ type: "lifecycle", state: "session-expired" });
    } catch {
      // A closing panel needs no notification.
    }
  }
}

function invalidateNativePort(port, error = "native-unavailable") {
  if (port && port !== nativePort) return;
  const detached = nativePort;
  nativePort = null;
  nativeReady = null;
  nativeGeneration += 1;
  notifyUnavailable();
  for (const entry of pending.values()) entry.resolve(unavailable(error));
  pending.clear();
  tabContexts.clear();
  for (const panel of panelContexts.values()) {
    panel.context = makeContext("panel", panel.stablePart);
  }
  void clearLegacySessionState();
  if (detached) {
    try {
      detached.disconnect();
    } catch {
      // The browser may already have closed it.
    }
  }
  scheduleReconnect();
}

function validateNativeResult(operation, value) {
  if (operation === "health") return CONTRACT.validateNativeHealth(value);
  if (operation === "scope_open") {
    const item = exactObject(value, ["status"]);
    if (!item || item.status !== "ready") throw new Error("contract-invalid");
    return { status: "ready" };
  }
  if (operation === "scope_close") {
    const item = exactObject(value, ["closed"]);
    if (!item || item.closed !== true) throw new Error("contract-invalid");
    return { closed: true };
  }
  if (operation === "sanitize") return CONTRACT.validateNativeSanitize(value);
  if (operation === "reidentify") return CONTRACT.validateReidentify(value);
  throw new Error("contract-invalid");
}

function onNativeMessage(port, message) {
  if (port !== nativePort) return;
  let encoded;
  try {
    encoded = JSON.stringify(message);
  } catch {
    invalidateNativePort(port, "contract-invalid");
    return;
  }
  if (encoded.length === 0 || new TextEncoder().encode(encoded).length > MAX_NATIVE_RESPONSE_BYTES) {
    invalidateNativePort(port, "contract-invalid");
    return;
  }
  const base = exactObject(
    message,
    message && message.ok === true
      ? ["native_protocol_version", "ok", "request_id", "result"]
      : ["error", "native_protocol_version", "ok", "request_id"]
  );
  if (
    !base ||
    base.native_protocol_version !== NATIVE_PROTOCOL_VERSION ||
    typeof base.ok !== "boolean" ||
    !validId(base.request_id)
  ) {
    invalidateNativePort(port, "contract-invalid");
    return;
  }
  const entry = pending.get(base.request_id);
  if (!entry || entry.generation !== nativeGeneration) {
    invalidateNativePort(port, "contract-invalid");
    return;
  }
  let response;
  if (!base.ok) {
    const error = exactObject(base.error, ["code"]);
    if (!error || !NATIVE_ERRORS.has(error.code)) {
      invalidateNativePort(port, "contract-invalid");
      return;
    }
    response = unavailable(error.code);
  } else {
    try {
      const result = validateNativeResult(entry.operation, base.result);
      response = { ok: true, status: 200, data: result };
    } catch {
      invalidateNativePort(port, "contract-invalid");
      return;
    }
  }
  pending.delete(base.request_id);
  if (entry.context && entry.context.revision !== entry.revision) {
    entry.resolve(unavailable("session-expired"));
    return;
  }
  entry.resolve(response);
}

function openNativePort() {
  if (nativePort) return nativePort;
  let port;
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST);
  } catch {
    scheduleReconnect();
    return null;
  }
  nativePort = port;
  nativeGeneration += 1;
  port.onMessage.addListener((message) => onNativeMessage(port, message));
  port.onDisconnect.addListener(() => {
    void chrome.runtime.lastError;
    invalidateNativePort(port);
  });
  return port;
}

function sendNative(operation, context, payload) {
  if (pending.size >= MAX_PENDING) return Promise.resolve(unavailable("native-busy"));
  const port = openNativePort();
  if (!port) return Promise.resolve(unavailable());
  requestCounter += 1;
  const requestId = `req-${workerNonce}-${requestCounter}`;
  const message = {
    native_protocol_version: NATIVE_PROTOCOL_VERSION,
    operation,
    payload,
    request_id: requestId,
  };
  if (context) message.context_id = context.contextId;
  return new Promise((resolve) => {
    pending.set(requestId, {
      context,
      generation: nativeGeneration,
      operation,
      resolve,
      revision: context ? context.revision : 0,
    });
    try {
      port.postMessage(message);
    } catch {
      pending.delete(requestId);
      resolve(unavailable());
      invalidateNativePort(port);
    }
  });
}

async function ensureNativeReady() {
  if (nativeReady) return nativeReady;
  nativeReady = (async () => {
    const response = await sendNative("health", null, {});
    if (!response.ok) {
      nativeReady = null;
      invalidateNativePort(nativePort, response.error);
      return response;
    }
    reconnectAttempts = 0;
    return response;
  })();
  return nativeReady;
}

async function ensureScope(context, kind) {
  const ready = await ensureNativeReady();
  if (!ready.ok) return ready;
  if (context.generation !== nativeGeneration) {
    if (context.opened || context.hasSession || context.opening) return unavailable();
    context.generation = nativeGeneration;
  }
  if (context.opened) return { ok: true };
  if (!context.opening) {
    context.opening = sendNative("scope_open", context, { scope_kind: kind }).then((response) => {
      context.opening = null;
      if (response.ok && context.generation === nativeGeneration) context.opened = true;
      return response;
    });
  }
  return context.opening;
}

async function closeContext(context) {
  const opening = context.opening;
  context.revision += 1;
  context.hasSession = false;
  context.mode = null;
  if (opening) {
    // Chrome may close the context before scope publication is known. The
    // connection teardown is the only confirmed cleanup boundary in that case.
    invalidateNativePort(nativePort);
    return unavailable();
  }
  if (!context.opened) return { ok: true };
  if (context.generation !== nativeGeneration || !nativePort) return unavailable();
  context.opened = false;
  return sendNative("scope_close", context, {});
}

async function invalidateContext(context, kind, stablePart) {
  await closeContext(context);
  return makeContext(kind, stablePart, context.origin, context.documentId);
}

function contextIsActive(context, kind, stablePart) {
  if (kind === "tab") return tabContexts.get(Number(stablePart)) === context;
  for (const panel of panelContexts.values()) {
    if (panel.stablePart === stablePart && panel.context === context) return true;
  }
  return false;
}

async function activateTabContext(evidence, create) {
  let context = tabContexts.get(evidence.tabId);
  if (
    context &&
    (context.origin !== evidence.origin || context.documentId !== evidence.documentId)
  ) {
    tabContexts.delete(evidence.tabId);
    await closeContext(context);
    context = null;
  }
  if (!context && create) {
    context = makeContext("tab", evidence.tabId, evidence.origin, evidence.documentId);
    tabContexts.set(evidence.tabId, context);
  }
  return context;
}

function validClientMessage(message) {
  if (!message || typeof message !== "object" || Array.isArray(message)) return false;
  if (message.type === "health") return Boolean(exactObject(message, ["type"]));
  if (message.type === "reidentify") {
    return Boolean(exactObject(message, ["text", "type"])) && validText(message.text);
  }
  if (message.type === "sanitize") {
    const keys = Object.hasOwn(message, "mode") ? ["mode", "text", "type"] : ["text", "type"];
    return (
      Boolean(exactObject(message, keys)) &&
      validText(message.text) &&
      (!Object.hasOwn(message, "mode") || ["token", "surrogate"].includes(message.mode))
    );
  }
  return false;
}

async function selectedMode(message) {
  if (message.mode === "surrogate" || message.mode === "token") return message.mode;
  try {
    const value = await chrome.storage.local.get("mode");
    return value.mode === "surrogate" ? "surrogate" : "token";
  } catch {
    return "token";
  }
}

async function performContextOperation(context, kind, stablePart, message) {
  if (message.type === "sanitize") {
    const mode = await selectedMode(message);
    if (!contextIsActive(context, kind, stablePart)) return unavailable("session-expired");
    if (context.hasSession && context.mode !== mode) {
      const disposed = await closeContext(context);
      if (!disposed.ok) return disposed;
    }
    if (!contextIsActive(context, kind, stablePart)) return unavailable("session-expired");
    const scope = await ensureScope(context, kind);
    if (!scope.ok) return scope;
    if (!contextIsActive(context, kind, stablePart)) {
      const disposed = await closeContext(context);
      if (!disposed.ok) invalidateNativePort(nativePort);
      return unavailable("session-expired");
    }
    const response = await sendNative("sanitize", context, {
      mode,
      text: message.text,
    });
    if (response.ok) {
      context.hasSession = true;
      context.mode = mode;
      return response;
    }
    const replacement = await invalidateContext(context, kind, stablePart);
    if (kind === "tab" && tabContexts.get(Number(stablePart)) === context) {
      tabContexts.set(Number(stablePart), replacement);
    } else if (kind === "panel") {
      for (const panel of panelContexts.values()) {
        if (panel.stablePart === stablePart && panel.context === context) {
          panel.context = replacement;
        }
      }
    }
    return response;
  }
  if (message.type === "reidentify") {
    if (
      !contextIsActive(context, kind, stablePart) ||
      !context.opened ||
      !context.hasSession ||
      context.generation !== nativeGeneration
    ) {
      return unavailable("session-expired");
    }
    const response = await sendNative("reidentify", context, { text: message.text });
    if (!response.ok) {
      const replacement = await invalidateContext(context, kind, stablePart);
      if (kind === "tab" && tabContexts.get(Number(stablePart)) === context) {
        tabContexts.set(Number(stablePart), replacement);
      } else if (kind === "panel") {
        for (const panel of panelContexts.values()) {
          if (panel.stablePart === stablePart && panel.context === context) {
            panel.context = replacement;
          }
        }
      }
    }
    return response;
  }
  return unavailable("unknown-message");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (!validClientMessage(message)) return unavailable("invalid-message");
    if (message.type === "health") {
      const evidence = admittedTabSender(sender);
      if (evidence) await activateTabContext(evidence, false);
      return ensureNativeReady();
    }
    const evidence = admittedTabSender(sender);
    if (!evidence) return unavailable("invalid-sender-context");
    const context = await activateTabContext(evidence, message.type === "sanitize");
    if (!context) return unavailable("session-expired");
    return performContextOperation(context, "tab", String(evidence.tabId), message);
  })()
    .then(sendResponse)
    .catch(() => sendResponse(unavailable("operation-failed")));
  return true;
});

function admittedPanelPort(port) {
  const sender = port && port.sender;
  if (!sender || sender.id !== chrome.runtime.id) return false;
  if (sender.frameId !== undefined && sender.frameId !== 0) return false;
  if (sender.documentLifecycle && sender.documentLifecycle !== "active") return false;
  if (sender.documentId !== undefined && !validId(sender.documentId)) return false;
  if (
    sender.tab !== undefined &&
    (!sender.tab || !Number.isInteger(sender.tab.id) || sender.tab.id < 0)
  ) {
    return false;
  }
  try {
    const url = new URL(sender.url);
    return (
      url.protocol === "chrome-extension:" &&
      url.hostname === chrome.runtime.id &&
      url.pathname === "/sidepanel.html" &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== PANEL_PORT_NAME || !admittedPanelPort(port)) {
    port.disconnect();
    return;
  }
  const stablePart = randomToken();
  const panel = { context: makeContext("panel", stablePart), port, stablePart };
  panelContexts.set(port, panel);
  port.onMessage.addListener((envelope) => {
    const item = exactObject(envelope, ["message", "panel_request_id"]);
    if (!item || !validId(item.panel_request_id) || !validClientMessage(item.message)) {
      port.disconnect();
      return;
    }
    (async () => {
      if (item.message.type === "health") return ensureNativeReady();
      return performContextOperation(
        panel.context,
        "panel",
        panel.stablePart,
        item.message
      );
    })()
      .then((response) => {
        if (!panelContexts.has(port)) return;
        port.postMessage({
          panel_request_id: item.panel_request_id,
          response,
          type: "response",
        });
      })
      .catch(() => {
        if (!panelContexts.has(port)) return;
        port.postMessage({
          panel_request_id: item.panel_request_id,
          response: unavailable("operation-failed"),
          type: "response",
        });
      });
  });
  port.onDisconnect.addListener(() => {
    if (!panelContexts.delete(port)) return;
    void closeContext(panel.context);
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const context = tabContexts.get(tabId);
  if (!context) return;
  tabContexts.delete(tabId);
  void closeContext(context);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!Object.hasOwn(changeInfo, "url")) return;
  const context = tabContexts.get(tabId);
  if (!context) return;
  const origin = httpsOrigin(changeInfo.url);
  if (origin === context.origin) return;
  tabContexts.delete(tabId);
  void closeContext(context);
});

void clearLegacySessionState();
void ensureNativeReady();
