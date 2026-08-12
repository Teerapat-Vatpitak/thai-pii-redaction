(function applySavedTheme() {
  "use strict";

  try {
    const preference = localStorage.getItem("aiguard.theme") || "system";
    const dark =
      preference === "dark" ||
      (preference === "system" &&
        matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  } catch {
    // The panel applies the system theme again after startup.
  }
})();
