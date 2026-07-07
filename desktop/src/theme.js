// Theme control: "system" (default) / "light" / "dark", persisted in localStorage.
// tokens.css defines dark values under :root[data-theme="dark"]; light is the base
// :root, so we set data-theme to the resolved concrete theme ("light" or "dark").

const KEY = "aiguard.theme";
const mq = window.matchMedia("(prefers-color-scheme: dark)");

export function getThemePref() {
  return localStorage.getItem(KEY) || "system";
}

function resolve(pref) {
  if (pref === "dark") return "dark";
  if (pref === "light") return "light";
  return mq.matches ? "dark" : "light";
}

export function applyTheme() {
  document.documentElement.setAttribute("data-theme", resolve(getThemePref()));
}

export function setThemePref(pref) {
  localStorage.setItem(KEY, pref);
  applyTheme();
}

export function initTheme() {
  applyTheme();
  // follow the OS while the preference is "system"
  mq.addEventListener("change", () => {
    if (getThemePref() === "system") applyTheme();
  });
}
