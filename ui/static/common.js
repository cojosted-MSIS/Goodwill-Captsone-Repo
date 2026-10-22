// Helpers shared by the phone screens (app.js) and the staff screens (staff.js).
// Text is always set with textContent, never as HTML.
"use strict";

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "disabled" || k === "open") el[k] = Boolean(v);
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function timeOf(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// Record the rendered page height so scripts/take_screenshots.py can capture the full page.
function markPageHeight() {
  document.documentElement.dataset.pageHeight = String(document.documentElement.scrollHeight);
}
