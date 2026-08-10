// Apply the saved theme before first paint without weakening script-src.
try {
  const preference = localStorage.getItem("aiguard.theme") || "system";
  const dark =
    preference === "dark" ||
    (preference === "system" &&
      matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
} catch {
  document.documentElement.setAttribute("data-theme", "light");
}
