// Shared render helpers for the desktop screens. Kept separate from app.js to
// avoid a circular import (app.js imports the screens; the screens import this).

/** Escape a string for safe insertion into innerHTML. */
export function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Consistent screen header: a title plus one muted description line. */
export function screenHeader(title, desc) {
  return `<div class="screen-header">
      <h1 class="title">${escapeHtml(title)}</h1>
      ${desc ? `<p class="desc">${escapeHtml(desc)}</p>` : ""}
    </div>`;
}
