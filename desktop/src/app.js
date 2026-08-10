import { health, rotateScope } from "./api.js";
import { safeErrorMessage } from "./errors.js";
import { initTheme } from "./theme.js";
import { renderText } from "./screen-text.js";
import { renderRedact } from "./screen-redact.js";
import { renderReport } from "./screen-report.js";
import { renderSettings } from "./screen-settings.js";
import { renderAudit } from "./screen-audit.js";

const SCREENS = {
  text: renderText,
  redact: renderRedact,
  report: renderReport,
  settings: renderSettings,
  audit: renderAudit,
};

const AUTHORITY_INVALIDATED_EVENT = "desktop-authority-invalidated";

async function waitForBroker() {
  const msg = document.getElementById("boot-msg");
  try {
    await health();
    return true;
  } catch (error) {
    msg.textContent = safeErrorMessage(error);
    const closeApp = document.createElement("button");
    closeApp.className = "btn btn--primary";
    closeApp.textContent = "ปิดแอป";
    closeApp.addEventListener("click", () => {
      void window.__TAURI__?.core?.invoke("quit_app");
    });
    msg.after(closeApp);
    return false;
  }
}

let activeCleanup = null;
let activeTab = null;
let authorityInvalidated = false;
let tabTransition = Promise.resolve();

function discardPublishedScreen() {
  if (authorityInvalidated) return;
  authorityInvalidated = true;

  const cleanup = activeCleanup;
  activeCleanup = null;
  if (typeof cleanup?.invalidatePublication === "function") {
    try {
      cleanup.invalidatePublication();
    } catch {
      // Replacing the screen below remains the fail-closed publication barrier.
    }
  }

  const screen = document.getElementById("screen");
  if (screen) {
    screen.replaceWith(screen.cloneNode(false));
  }
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.remove("active");
  });
  document.getElementById("app")?.classList.add("hidden");
  document.getElementById("boot")?.classList.remove("hidden");
  const message = document.getElementById("boot-msg");
  if (message) {
    message.textContent = "สิทธิ์ของหน้าต่างหมดอายุ กรุณาเปิดแอปใหม่";
  }
}

async function registerAuthorityInvalidationListener() {
  const listen = window.__TAURI__?.event?.listen;
  if (typeof listen !== "function") {
    throw new Error("desktop event bridge unavailable");
  }
  await listen(AUTHORITY_INVALIDATED_EVENT, discardPublishedScreen);
}

async function performTabSelection(name) {
  if (authorityInvalidated || !Object.hasOwn(SCREENS, name)) return;
  if (activeTab !== null) {
    if (activeCleanup) {
      const cleanup = activeCleanup;
      activeCleanup = null;
      await cleanup();
    }
    if (authorityInvalidated) return;
    try {
      await rotateScope();
    } catch {
      discardPublishedScreen();
      return;
    }
    if (authorityInvalidated) return;
  }
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  const root = document.getElementById("screen");
  root.innerHTML = "";
  activeTab = name;
  activeCleanup = SCREENS[name](root) || null;
}

function selectTab(name) {
  const transition = tabTransition.then(() => performTabSelection(name));
  tabTransition = transition.catch(() => {});
  return transition;
}

async function checkForUpdateBanner() {
  if (!window.__TAURI__) return;
  try {
    const info = await window.__TAURI__.core.invoke("update_check");
    if (!info.available) return;
    const toast = document.createElement("div");
    toast.className = "toast";
    const label = document.createElement("span");
    label.textContent = `มีอัปเดตใหม่ ${info.version} ไปที่หน้า Settings เพื่ออัปเดต`;
    const close = document.createElement("button");
    close.className = "toast__close";
    close.setAttribute("aria-label", "ปิด");
    close.textContent = "×";
    close.addEventListener("click", () => toast.remove());
    toast.append(label, close);
    document.body.appendChild(toast);
  } catch {
    // offline, or no published release yet: stay silent
  }
}

async function main() {
  initTheme();
  try {
    await registerAuthorityInvalidationListener();
  } catch (error) {
    const message = document.getElementById("boot-msg");
    if (message) message.textContent = safeErrorMessage(error);
    return false;
  }
  const ok = await waitForBroker();
  if (!ok || authorityInvalidated) return false;
  document.getElementById("boot").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.addEventListener("click", () => {
      void selectTab(b.dataset.tab).catch(() => {});
    });
  });
  await selectTab("text");
  checkForUpdateBanner();
  return !authorityInvalidated;
}

window.__AIGUARD_APP_READY__ = main();
