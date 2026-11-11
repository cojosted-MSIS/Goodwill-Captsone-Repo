// The worker web app (add-web-application, Stage 3b): routing, API calls, and buttons.
//
// Screens come from screens.js. Every write sends the session's CSRF token and a fresh
// Idempotency-Key, so a repeat after a lost answer never makes anything twice. The service worker
// (sw.js) caches the app shell listed in SHELL, and only that. Offline is capture only: review,
// corrections, Confirm, and look-ups need a connection.
import * as device from "./device.js";
import * as screens from "./screens.js";

export const SHELL = ["./", "index.html", "offline.html", "style.css", "app.js", "screens.js", "device.js", "manifest.webmanifest", "fonts/inter-latin-wght-normal.woff2", "icons/icon-192.png", "icons/icon-512.png"];
const PING_SECONDS = 15;

const main = document.getElementById("main");
const state = { user: null, csrf: null, flash: null, forms: {}, options: null, result: null, online: navigator.onLine,
  offlineView: false, rendering: false, queue: { uploading: 0, needsAttention: 0 }, checkUpdate: () => {} };

const OUTCOMES = {
  drafted: "Your draft is ready to check.",
  search_requested: "Please confirm you searched HMIS first.",
  pick_client: "Pick the client this visit is for.",
  revised: "Your correction was applied. Check the new version.",
  rephrase: "Your correction could not be matched to a field.",
  submitted: "Entered in HMIS.",
  entry_failed: "HMIS did not accept the entry. Your draft is kept.",
  verification: "Please decide about the same name and date of birth first.",
  verified_same: "This is now a visit for the client you chose. Check it, then confirm.",
  verified_different: "Your reason was saved. Check the draft, then confirm.",
  still_missing: "Some answers are still needed before entry.",
  old_version: "There is a newer version. Please check it.",
  expired: "This draft is with your supervisor.",
  not_failed: "Nothing to try again: this draft is waiting for you to check it.",
  already_submitted: "This draft was already entered in HMIS.",
  parse_failed: "Your note could not be drafted.",
};

function key() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function api(method, path, body) {
  const headers = { Accept: "application/json" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
    headers["Idempotency-Key"] = key();
  }
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
  } catch {
    setOnline(false);
    throw Object.assign(new Error("There is no connection. Nothing was sent, and nothing was saved."), { network: true });
  }
  setOnline(true);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith("/api/v1/auth/")) {
    state.user = null;
    go("#/sign-in", { kind: "error", text: "Please sign in again." });
    throw new Error("signed out");
  }
  if (!res.ok) {
    const d = data.detail;
    const err = new Error(typeof d === "string" ? d : (d && d.message) || "Something went wrong. Please try again.");
    err.status = res.status;
    throw err;
  }
  return data;
}

function go(hash, flash) {
  state.flash = flash || null;
  if (location.hash === hash) render(); else location.hash = hash;
}

// The sync status line: whether the server can really be reached, and the device queue's state.
function syncLine() {
  const line = document.getElementById("sync-status");
  const pill = screens.syncPill(screens.syncState({ online: state.online, ...state.queue }));
  line.className = pill.className;
  line.innerHTML = pill.html;
}

function setOnline(now) {
  if (state.online === now) return;
  state.online = now;
  syncLine();
  applyConnectivity();
  if (!state.rendering) connectionChanged();
}

async function connectionChanged() {
  if (state.online) {
    await finishPendingSignOut();
    if (!state.csrf) state.user = null;  // opened offline: get a real session and a CSRF token
  }
  const hash = location.hash || "#/";
  if (state.offlineView || hash === "#/" || hash.startsWith("#/queries")) render();
}

// The real check: can the server be reached? The browser's own flag only says a network exists.
async function ping() {
  try {
    const res = await fetch("/api/v1/ping", { cache: "no-store", signal: AbortSignal.timeout(5000) });
    setOnline(res.ok);
  } catch {
    setOnline(false);
  }
}

// A screen left open when the connection goes keeps what is on it, but nothing on it can be sent.
// Only the note forms stay usable: writing a note is what works offline.
function applyConnectivity() {
  const disable = !state.online && !state.offlineView;
  const note = document.getElementById("offline-note");
  if (disable && !note) main.insertAdjacentHTML("afterbegin", screens.offlineNote());
  if (!disable && note) note.remove();
  for (const button of main.querySelectorAll("button[data-action], form button[type=submit]")) {
    const form = button.closest("form");
    if (form && ["new-note", "update-note"].includes(form.dataset.form)) continue;
    if (disable && !button.disabled) {
      button.disabled = true;
      button.dataset.offlineDisabled = "1";
    }
    if (!disable && button.dataset.offlineDisabled) {
      button.disabled = false;
      delete button.dataset.offlineDisabled;
    }
  }
}

function hasUnsavedText() {
  return [...main.querySelectorAll("textarea, input:not([type=radio])")].some((field) => field.value.trim());
}

async function finishPendingSignOut() {
  if (!(await device.getMeta("pending_sign_out"))) return;
  try {
    const res = await fetch("/api/v1/session", { credentials: "same-origin" });
    if (res.ok) {
      const me = await res.json();
      await fetch("/api/v1/auth/sign-out", { method: "POST", headers: { "X-CSRF-Token": me.csrf_token }, credentials: "same-origin" });
    }
    await device.deleteMeta("pending_sign_out");
  } catch { /* still offline: try at the next connection */ }
}

function remember(me) {
  state.user = me;
  state.csrf = me.csrf_token;
  return me.role === "worker" ? device.saveProfile(me) : device.clearProfile();
}

// The bottom navigation is for a worker's top-level screens; a screen with its own bottom bar has none.
// Supervisor and staff tables get a wider column.
function layout() {
  const role = state.user ? state.user.role : null;
  if (role && role !== "worker") document.body.dataset.wide = "1"; else delete document.body.dataset.wide;
  const hash = location.hash || "#/";
  const nav = document.getElementById("bottom-nav");
  nav.hidden = role !== "worker" || !["#/", "#/new", "#/update", "#/queries"].includes(hash);
  for (const link of nav.querySelectorAll("a")) {
    if (link.getAttribute("href") === hash) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
}

function show(html) {
  syncLine();
  const flash = screens.flash(state.flash);
  state.flash = null;
  main.innerHTML = flash + html;
  const heading = main.querySelector("h1");
  if (heading) heading.focus();
  document.title = `${heading ? heading.textContent : "Outreach notes"} | Outreach notes`;
  document.getElementById("who").textContent = state.user ? `Signed in as ${state.user.display_name}` : "";
  layout();
  const signOut = document.getElementById("sign-out");
  signOut.hidden = !state.user;
  signOut.disabled = false;
  applyConnectivity();
  state.checkUpdate();
  document.documentElement.dataset.pageHeight = String(document.documentElement.scrollHeight);
  document.documentElement.dataset.renders = String(Number(document.documentElement.dataset.renders || 0) + 1);
  document.documentElement.dataset.ready = "1";
}

async function ensureSession() {
  if (state.user) return true;
  try {
    await remember(await api("GET", "/api/v1/session"));
    return true;
  } catch (err) {
    if (!err.network) return false;
    const profile = await device.getProfile();  // opened offline: who this device was signed in as
    if (!profile) return false;
    state.user = profile;
    state.csrf = null;
    return true;
  }
}

// Offline, only what needs no server: the note forms and plain messages. Never draft or client data.
function showOffline(parts) {
  state.offlineView = true;
  if (state.user.role !== "worker") return show(screens.needsConnection({}));
  if (parts.length === 0) return show(screens.offlineHome({ user: state.user }));
  if (parts[0] === "new" || parts[0] === "update") return show(screens.noteForm({ kind: parts[0], online: false, ...(state.forms[parts[0]] || {}) }));
  if (parts[0] === "queries" && !parts[1]) return show(screens.queriesHome({ options: state.options, online: false }));
  if (parts[0] === "queries" && screens.QUERY_KINDS[parts[1]]) return show(screens.queryForm(parts[1], { options: state.options, online: false }));
  return show(screens.needsConnection({}));
}

async function render() {
  state.rendering = true;
  try {
    await renderScreen();
  } finally {
    state.rendering = false;
  }
}

async function renderScreen() {
  document.documentElement.dataset.ready = "0";
  state.offlineView = false;
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/").filter(Boolean);
  if (parts[0] === "sign-in") {
    if (state.online) return show(screens.signIn(state.forms.signIn || {}));
    state.offlineView = true;
    return show(screens.needsConnection({ signedOut: true }));
  }
  if (!(await ensureSession())) {
    if (state.online) return show(screens.signIn({}));
    state.offlineView = true;
    return show(screens.needsConnection({ signedOut: true }));
  }
  try {
    if (!state.online) return showOffline(parts);
    if (state.user.role === "supervisor") return await renderSupervisor(parts);
    if (state.user.role === "staff") return await renderStaff(parts);
    if (parts.length === 0) {
      const [drafts, held, messages] = await Promise.all([api("GET", "/api/v1/drafts"), api("GET", "/api/v1/held"), api("GET", "/api/v1/messages")]);
      return show(screens.home({ user: state.user, drafts, held, messages }));
    }
    if (parts[0] === "queries") {
      if (state.online && !state.options) state.options = await api("GET", "/api/v1/queries/options");
      const kind = parts[1];
      if (!kind) return show(screens.queriesHome({ options: state.options, online: state.online }));
      if (!screens.QUERY_KINDS[kind]) return show(screens.notFound());
      if (parts[2] === "result" && state.result && state.result.kind === kind) {
        const shown = screens.queryResult(kind, state.result.out);
        state.result = null;  // shown once, never stored
        return show(shown);
      }
      return show(screens.queryForm(kind, { options: state.options, online: state.online, ...(state.forms.query || {}) }));
    }
    if (parts[0] === "new" || parts[0] === "update") return show(screens.noteForm({ kind: parts[0], ...(state.forms[parts[0]] || {}) }));
    if (parts[0] === "held" && parts[1]) {
      const held = await api("GET", `/api/v1/held/${encodeURIComponent(parts[1])}`);
      return show(held.kind === "pick_client" ? screens.pickClient(held) : screens.heldSearch(held));
    }
    if (parts[0] === "drafts" && parts[1]) {
      const view = await api("GET", `/api/v1/drafts/${encodeURIComponent(parts[1])}`);
      if (parts[2] === "correct") return show(screens.correction(view, state.forms.correction || {}));
      if (parts[2] === "different") return show(screens.differentPerson(view, state.forms.different || {}));
      return show(screens.draft(view, state.forms.different || {}));
    }
    return show(screens.notFound());
  } catch (err) {
    if (err.network) return showOffline(parts);
    if (err.status === 404) return show(screens.notFound());
    if (err.message !== "signed out") show(screens.flash({ kind: "error", text: err.message }) + screens.notFound());
  } finally {
    state.forms = {};
  }
}

// Supervisor and staff screens: read-only, so only links and no actions.
async function renderSupervisor(parts) {
  const base = "/api/v1/supervisor";
  if (parts.length === 0) {
    const [queue, flags] = await Promise.all([api("GET", `${base}/queue`), api("GET", `${base}/flags`)]);
    return show(screens.supervisorHome({ user: state.user, queue, flags }));
  }
  if (parts[0] === "queue") return show(screens.supervisorQueue(await api("GET", `${base}/queue`)));
  if (parts[0] === "flags") return show(screens.supervisorFlags(await api("GET", `${base}/flags`)));
  if (parts[0] === "drafts" && !parts[1]) return show(screens.supervisorDrafts(await api("GET", `${base}/drafts`)));
  if (parts[0] === "drafts") return show(screens.supervisorDraft(await api("GET", `${base}/drafts/${encodeURIComponent(parts[1])}`)));
  return show(screens.notFound());
}

async function renderStaff(parts) {
  const base = "/api/v1/staff";
  if (parts.length === 0) return show(screens.staffHome({ user: state.user }));
  if (parts[0] === "queries") return show(screens.staffQueries(await api("GET", `${base}/queries`)));
  if (parts[0] === "drafts" && !parts[1]) return show(screens.staffDrafts(await api("GET", `${base}/drafts`)));
  if (parts[0] === "drafts") return show(screens.staffAudit(await api("GET", `${base}/drafts/${encodeURIComponent(parts[1])}/audit`)));
  return show(screens.notFound());
}

// After an action: where to go, and what to say.
function landing(out, fallbackRef) {
  const flash = { text: OUTCOMES[out.action] || "Done.", messages: out.messages || [] };
  if (out.ssn && out.ssn.masked) flash.text += " A full Social Security number was hidden: only the last four digits were kept.";
  if (out.action === "search_requested" || out.action === "pick_client") return go(`#/held/${out.ref}`, flash);
  if (out.ref && out.ref.startsWith("ENC-")) return go(`#/drafts/${out.ref}`, flash);
  return go(fallbackRef ? `#/drafts/${fallbackRef}` : "#/", flash);
}

async function busy(button, work) {
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    await work();
  } catch (err) {
    if (err.message !== "signed out") {
      main.insertAdjacentHTML("afterbegin", screens.flash({ kind: "error", text: err.message }));
      main.querySelector(".banner.error").focus?.();
    }
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

main.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button || button.disabled) return;
  const { action, ref, client, version } = button.dataset;
  const enc = encodeURIComponent(ref);
  busy(button, async () => {
    if (action === "searched") landing(await api("POST", `/api/v1/held/${enc}/searched`, {}));
    if (action === "pick") landing(await api("POST", `/api/v1/held/${enc}/client`, { client_id: client }));
    if (action === "confirm") landing(await api("POST", `/api/v1/drafts/${enc}/confirm`, { version: Number(version) }), ref);
    if (action === "retry") landing(await api("POST", `/api/v1/drafts/${enc}/retry`), ref);
    if (action === "same-client") landing(await api("POST", `/api/v1/drafts/${enc}/same-client`, { client_id: client }), ref);
  });
});

main.addEventListener("input", (event) => {
  if (event.target.id === "reason") {
    const count = document.getElementById("reason-count");
    count.textContent = `${event.target.value.trim().length} of at least ${count.dataset.min} characters`;
  }
});

main.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  const button = form.querySelector("button[type=submit]");
  const name = form.dataset.form;
  const ref = form.dataset.ref;
  busy(button, async () => {
    try {
      if (name === "sign-in") {
        const pre = await api("GET", "/api/v1/auth/csrf");
        state.csrf = pre.csrf_token;
        await remember(await api("POST", "/api/v1/auth/sign-in", { username: data.username.trim(), password: data.password }));
        return go("#/");
      }
      if (name === "new-note" || name === "update-note") {
        if (!data.text.trim()) throw Object.assign(new Error("Please write your note first."), { keep: true });
        const path = name === "new-note" ? "/api/v1/notes/new-client" : "/api/v1/notes/update";
        return landing(await api("POST", path, { text: data.text, title: data.title.trim() || null }));
      }
      if (name === "correction") {
        if (!data.text.trim()) throw Object.assign(new Error("Please write what should change."), { keep: true });
        return landing(await api("POST", `/api/v1/drafts/${encodeURIComponent(ref)}/corrections`, { text: data.text }), ref);
      }
      if (name === "query") {
        const kind = form.dataset.kind;
        const body = Object.fromEntries(Object.entries(data).filter(([, v]) => String(v).trim() !== "").map(([k, v]) => [k, String(v).trim()]));
        const out = await api("POST", `/api/v1/queries/${kind}`, body);
        state.result = { kind, out };
        return go(`#/queries/${kind}/result`);
      }
      if (name === "different-person") {
        const out = await api("POST", `/api/v1/drafts/${encodeURIComponent(ref)}/different-person`, { reason: data.reason });
        if (out.action === "verification") state.forms.different = { reason: data.reason };  // asked again: keep what was typed
        return landing(out, ref);
      }
    } catch (err) {
      // Show the form again with the error and what was typed (kept in this page only, never stored).
      const key = { "sign-in": "signIn", "new-note": "new", "update-note": "update", correction: "correction",
        "different-person": "different", query: "query" }[name];
      state.forms[key] = name === "query" ? { values: data, error: err.message } : { ...data, password: undefined, error: err.message };
      if (name === "sign-in") state.forms[key] = { error: err.message };
      render();
    }
  });
});

document.getElementById("sign-out").addEventListener("click", async (event) => {
  await busy(event.currentTarget, async () => {
    try {
      if (!state.online || !state.csrf) throw Object.assign(new Error("offline"), { network: true });
      await api("POST", "/api/v1/auth/sign-out", {});
    } catch (err) {
      if (!err.network) throw err;
      await device.setMeta("pending_sign_out", true);  // the server's session ends at the next connection
    }
    await device.clearProfile();
    state.user = null;
    state.csrf = null;
    go("#/sign-in", { text: "You are signed out." });
  });
});

window.addEventListener("hashchange", () => {
  if (!state.online) ping();
  render();
});
for (const event of ["online", "offline"]) window.addEventListener(event, ping);
document.addEventListener("visibilitychange", () => { if (!document.hidden) ping(); });
setInterval(ping, PING_SECONDS * 1000);

// A new version installs and waits. It takes over only when no note is being typed, so an update can
// never interrupt a worker or the queue; the check runs again at every screen.
async function watchForUpdates() {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.register("sw.js");
  let controlled = Boolean(navigator.serviceWorker.controller);
  state.checkUpdate = () => {
    if (registration.waiting && !hasUnsavedText()) registration.waiting.postMessage({ type: "activate" });
  };
  registration.addEventListener("updatefound", () => {
    const incoming = registration.installing;
    incoming.addEventListener("statechange", () => { if (incoming.state === "installed") state.checkUpdate(); });
  });
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (controlled && !hasUnsavedText()) location.reload();
    controlled = true;
  });
  state.checkUpdate();
}

watchForUpdates();
render();
