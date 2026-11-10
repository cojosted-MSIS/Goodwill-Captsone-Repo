// The worker web app (add-web-application, Stage 3b): routing, API calls, and buttons.
//
// Screens come from screens.js. Every write sends the session's CSRF token and a fresh
// Idempotency-Key, so a repeat after a lost answer never makes anything twice. The app shell
// (index.html, style.css, screens.js, app.js) lives in this one folder so a service worker can
// cache it in Stage 4; SHELL lists it.
import * as screens from "./screens.js";

export const SHELL = ["./", "index.html", "style.css", "screens.js", "app.js"];

const main = document.getElementById("main");
const state = { user: null, csrf: null, flash: null, forms: {}, options: null, result: null,
  online: navigator.onLine };  // Stage 4 replaces this with the real sync state

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
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" });
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

// The sync status line. For now only Online or Offline; Stage 4 adds the device queue's state.
function syncLine() {
  const line = document.getElementById("sync-status");
  line.classList.toggle("offline", !state.online);
  line.innerHTML = `<span class="dot" aria-hidden="true"></span>${state.online ? "Online" : "Offline"}`;
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
  const signOut = document.getElementById("sign-out");
  signOut.hidden = !state.user;
  signOut.disabled = false;
  document.documentElement.dataset.pageHeight = String(document.documentElement.scrollHeight);
  document.documentElement.dataset.renders = String(Number(document.documentElement.dataset.renders || 0) + 1);
  document.documentElement.dataset.ready = "1";
}

async function ensureSession() {
  if (state.user) return true;
  try {
    const me = await api("GET", "/api/v1/session");
    state.user = me;
    state.csrf = me.csrf_token;
    return true;
  } catch {
    return false;
  }
}

async function render() {
  document.documentElement.dataset.ready = "0";
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/").filter(Boolean);
  if (parts[0] === "sign-in") return show(screens.signIn(state.forms.signIn || {}));
  if (!(await ensureSession())) return show(screens.signIn({}));
  if (state.user.role !== "worker") {
    return show(`<h1 tabindex="-1">Signed in as ${screens.esc(state.user.role)}</h1><p>The ${screens.esc(state.user.role)} screens come in a later step.</p>`);
  }
  try {
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
      return show(screens.draft(view));
    }
    return show(screens.notFound());
  } catch (err) {
    if (err.status === 404) return show(screens.notFound());
    if (err.message !== "signed out") show(screens.flash({ kind: "error", text: err.message }) + screens.notFound());
  } finally {
    state.forms = {};
  }
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
        const me = await api("POST", "/api/v1/auth/sign-in", { username: data.username.trim(), password: data.password });
        state.user = me;
        state.csrf = me.csrf_token;
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
        return landing(await api("POST", `/api/v1/drafts/${encodeURIComponent(ref)}/different-person`, { reason: data.reason }), ref);
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
    await api("POST", "/api/v1/auth/sign-out", {});
    state.user = null;
    state.csrf = null;
    go("#/sign-in", { text: "You are signed out." });
  });
});

window.addEventListener("hashchange", render);
// Queries need a connection. Stage 4 replaces this with the sync state; for now the browser's online flag.
for (const event of ["online", "offline"]) {
  window.addEventListener(event, () => {
    state.online = navigator.onLine;
    syncLine();
    if (location.hash.startsWith("#/queries")) render();
  });
}
render();
