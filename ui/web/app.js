// The worker web app (add-web-application, Stage 3b): routing, API calls, and buttons.
//
// Screens come from screens.js. Every write sends the session's CSRF token and a fresh
// Idempotency-Key, so a repeat after a lost answer never makes anything twice. The service worker
// (sw.js) caches the app shell listed in SHELL, and only that. Offline is capture only: review,
// corrections, Confirm, and look-ups need a connection.
//
// A note is checked for SSNs and sealed in memory before anything else happens to it. The same
// sealed envelope, under the same Idempotency-Key, is sent if the server can be reached and saved on
// the device if it cannot, so a lost answer can never make two drafts.
import * as device from "./device.js";
import { classify, createQueue, createSync, parseRetryAfter, pingDelay, pingGate, signOutGate, writeAllowed } from "./queue.js";
import { seal, verifyKey } from "./seal.js";
import * as screens from "./screens.js";
import { compileRules, guard } from "./ssn.js";

export const SHELL = ["./", "index.html", "offline.html", "style.css", "app.js", "screens.js", "device.js", "queue.js", "seal.js", "ssn.js", "manifest.webmanifest", "fonts/inter-latin-wght-normal.woff2", "icons/icon-192.png", "icons/icon-512.png"];
const ONLINE_CHECK_SECONDS = 60;  // also the slow check for notes that are waiting
const SETUP_REFRESH_MINUTES = 10;
const NOTE_LIMIT = 20000;
const TITLE_LIMIT = 200;
const MASKED_NOTICE = "A full Social Security number was hidden: only the last four digits were kept. Check your note, then press the button again.";
const SIGN_OUT_UNFINISHED = "This device is finishing the last sign-out. Please try again in a moment.";

const main = document.getElementById("main");
const state = { user: null, csrf: null, flash: null, forms: {}, options: null, result: null, online: navigator.onLine,
  offlineView: false, rendering: false, queue: { uploading: 0, needsAttention: 0 }, checkUpdate: () => {},
  setup: null, ssnLabel: null, finishing: false, current: null, pingTimer: null, offlineChecks: 0 };

// Replaced by the server's values with the setup; used to expire notes when no one is signed in.
const limits = { offline_write_hours: 12, queue_expiry_hours: 72, queue_warning_hours: 60 };
const queue = createQueue({ store: device.queueStore, now: () => Date.now(), limits, upload: async (row) => classify(await sendSealed(row)), onChange: deviceChanged });

// Tell other open tabs that the queue changed. The message says nothing else.
const channel = "BroadcastChannel" in self ? new BroadcastChannel("outreach-queue") : null;
const pings = pingGate({ now: () => Date.now() });

// One upload at a time across tabs: a tab that cannot take the lock leaves it to the one holding it.
// Uploading twice would still be safe, because the Idempotency-Key makes the repeat a replay.
function withUploadLock(work) {
  if (!navigator.locks) return work();
  return navigator.locks.request("outreach-upload", { ifAvailable: true }, (held) => (held ? work() : { busy: true }));
}

const sync = createSync({
  attempt: attemptUpload, now: () => Date.now(), random: Math.random, lock: withUploadLock,
  memo: { get: async () => (await device.getMeta("upload_backoff")) || { failures: 0, next_at: 0, retry_until: 0 }, set: (value) => device.setMeta("upload_backoff", value) },
  isReady: () => Boolean(state.online && state.csrf && state.user && state.user.role === "worker"),
  schedule: (fn, ms) => setTimeout(fn, ms), cancel: (timer) => clearTimeout(timer),
  onSignIn: sessionEnded, onDone: uploadsFinished,
});

// Every request waits for an unfinished sign-out to reach the server first. Only the connection
// check goes ahead of it, and that sends no session.
const flushSignOut = signOutGate({
  isPending: async () => Boolean(await device.getMeta("pending_sign_out")),
  clear: () => device.deleteMeta("pending_sign_out"),
  post: () => fetch("/api/v1/auth/sign-out-device", { method: "POST", credentials: "same-origin" }),
});

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
  try {
    await flushSignOut();
  } catch {
    throw Object.assign(new Error(SIGN_OUT_UNFINISHED), { network: true });
  }
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

// The session the browser really has now: another tab may have replaced it. A fresh CSRF token comes with it.
async function freshSession(owner) {
  const res = await fetch("/api/v1/session", { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!res.ok) return false;
  const me = await res.json();
  if (me.username !== owner) return false;
  state.csrf = me.csrf_token;
  return true;
}

// Send a sealed note, always with the key it was saved under. A status of 0 means the server could
// not be reached, and the connection check then decides whether the device is really offline.
async function sendSealed(row) {
  const post = () => fetch("/api/v1/notes/sealed", { method: "POST", credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": state.csrf, "Idempotency-Key": row.idempotency_key },
    body: JSON.stringify({ kind: row.kind, saved_at: row.saved_at, envelope: row.envelope }) });
  try {
    await flushSignOut();
    let res = await post();
    if (res.status === 403) {  // a stale CSRF token: get a fresh one and try once more
      if (!(await freshSession(row.owner))) return { status: 401, data: {} };
      res = await post();
    }
    setOnline(true);
    return { status: res.status, data: await res.json().catch(() => ({})), retryAfterMs: parseRetryAfter(res.headers.get("Retry-After"), Date.now()) };
  } catch {
    await ping({ force: true });
    return { status: 0, data: {} };
  }
}

// One upload run, under the tab lock. Anything still marked uploading was left by a closed tab.
async function attemptUpload() {
  await queue.recover();
  const owner = state.user && state.user.username;
  if (!owner || !(await queue.view(owner)).uploadable) return {};
  try {
    await flushSignOut();
    if (!(await freshSession(owner))) return { signIn: true };
  } catch {
    await ping({ force: true });
    return { waiting: true };
  }
  return queue.uploadAll(owner);
}

function syncSoon(reason) {
  sync.trigger(reason).catch(() => {});
}

// The session ended. A worker in the middle of typing keeps the form; their note is safe either way.
function sessionEnded() {
  state.csrf = null;
  if (hasUnsavedText()) return;
  state.user = null;
  go("#/sign-in", { kind: "error", text: "Please sign in again." });
}

async function reloadHome() {
  await Promise.resolve(state.current).catch(() => {});
  if ((location.hash || "#/") === "#/" && state.user && state.online) render();
}

function uploadsFinished(out) {
  if (!out.uploaded) return refreshDevice();
  if (channel) channel.postMessage("uploaded");
  return reloadHome();
}

// Show the queue's current state without reloading the screen.
async function refreshDevice() {
  if (!state.user || state.user.role !== "worker") return;
  const view = await deviceView();
  syncLine();
  const area = document.getElementById("device-notes");
  if (area) {
    area.innerHTML = screens.deviceNotes(view, { online: state.online });
    applyConnectivity();
  }
}

function deviceChanged() {
  if (channel) channel.postMessage("changed");
  refreshDevice().catch(() => {});
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
  state.offlineChecks = 0;
  armPing();
  syncLine();
  applyConnectivity();
  if (!state.rendering) connectionChanged();
}

async function connectionChanged() {
  if (state.online) {
    await flushSignOut().catch(() => {});
    if (!state.csrf) state.user = null;  // opened offline: get a real session and a CSRF token
  }
  const hash = location.hash || "#/";
  if (state.offlineView || hash === "#/" || hash.startsWith("#/queries")) await render();
  if (state.online && await ensureSession()) syncSoon("online");
}

// The real check: can the server be reached? The browser's own flag only says a network exists.
async function ping({ force = false } = {}) {
  if (!state.online && !force && !pings.allow()) return;  // a few a minute at most while offline
  try {
    const res = await fetch("/api/v1/ping", { cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(5000) });
    setOnline(res.ok);
    if (res.ok && state.finishing && !state.rendering) render();
  } catch {
    setOnline(false);
  }
}

// A screen left open when the connection goes keeps what is on it, but nothing on it can be sent.
// Only the note forms stay usable: writing a note is what works offline.
function applyConnectivity() {
  const disable = !state.online && !state.offlineView;
  const noteButton = main.querySelector("form[data-form$=-note] button[type=submit]");
  if (noteButton) noteButton.textContent = state.online ? "Draft my note" : "Save on this device";
  const note = document.getElementById("offline-note");
  if (disable && !note) main.insertAdjacentHTML("afterbegin", screens.offlineNote());
  if (!disable && note) note.remove();
  for (const button of main.querySelectorAll("button[data-action], form button[type=submit]")) {
    const form = button.closest("form");
    if (form && ["new-note", "update-note"].includes(form.dataset.form)) continue;
    if (button.dataset.local) continue;  // works on the device alone
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

async function remember(me) {
  state.user = me;
  state.csrf = me.csrf_token;
  state.setup = null;
  sync.resume();
  if (me.role !== "worker") {
    await device.clearProfile();
    return device.deleteMeta("setup");
  }
  await device.saveProfile(me);
  return refreshSetup().catch(() => {});
}

// The public key, the SSN rules, the limits, and a fresh contact stamp, for saving notes offline.
async function refreshSetup() {
  const setup = await api("GET", "/api/v1/device/setup");
  if (!(await verifyKey(setup.seal.public_key, setup.seal.key_id))) throw new Error("The key ID does not match the key.");
  compileRules(setup.rules);
  state.setup = { owner: state.user.username, ...setup, received_at: Date.now() };
  Object.assign(limits, setup.limits);
  await device.setMeta("setup", state.setup);
}

async function readySetup() {
  const owner = state.user.username;
  if (state.setup && state.setup.owner === owner) return state.setup;
  const stored = await device.getMeta("setup");
  if (stored && stored.owner === owner) {
    state.setup = stored;
    Object.assign(limits, stored.limits);
    return stored;
  }
  if (state.online) await refreshSetup().catch(() => {});
  return state.setup;
}

async function deviceView() {
  const view = await queue.view(state.user.username);
  state.queue = { uploading: view.uploading, needsAttention: view.needsAttention };
  return view;
}

async function noteScreen(kind, online) {
  const setup = await readySetup();
  let blocked = null;
  if (!online && !setup) blocked = "This device is not ready to save notes. Please sign in when you have a connection.";
  else if (!online && !writeAllowed(setup, Date.now())) {
    blocked = `It has been more than ${setup.limits.offline_write_hours} hours since this device reached the server. Please sign in when you have a connection.`;
  }
  return screens.noteForm({ kind, online, blocked, ...(state.forms[kind] || {}) });
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
async function showOffline(parts) {
  state.offlineView = true;
  if (state.user.role !== "worker") return show(screens.needsConnection({}));
  if (parts.length === 0) return show(screens.offlineHome({ user: state.user, device: await deviceView() }));
  if (parts[0] === "new" || parts[0] === "update") return show(await noteScreen(parts[0], false));
  if (parts[0] === "queries" && !parts[1]) return show(screens.queriesHome({ options: state.options, online: false }));
  if (parts[0] === "queries" && screens.QUERY_KINDS[parts[1]]) return show(screens.queryForm(parts[1], { options: state.options, online: false }));
  return show(screens.needsConnection({}));
}

function render() {
  state.current = renderGuarded();
  return state.current;
}

async function renderGuarded() {
  state.rendering = true;
  try {
    await renderScreen();
  } finally {
    state.rendering = false;
  }
}

// Asks the last worker on this device to sign in if notes are waiting; that says all "sign in again" would.
async function showSignIn(form) {
  const profile = await device.getProfile();
  const count = profile ? (await queue.view(profile.username)).uploadable : 0;
  if (count && !form.error) state.flash = null;
  return show(screens.signIn({ ...form, uploadCount: count }));
}

async function renderScreen() {
  document.documentElement.dataset.ready = "0";
  state.offlineView = false;
  state.finishing = false;
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/").filter(Boolean);
  await queue.sweep().catch(() => {});
  if (state.online) {
    try {
      await flushSignOut();
    } catch {
      await ping();
      if (state.online) {
        state.finishing = true;
        state.offlineView = true;
        return show(screens.finishingSignOut());
      }
    }
  }
  if (parts[0] === "sign-in") {
    if (state.online) return showSignIn(state.forms.signIn || {});
    state.offlineView = true;
    return show(screens.needsConnection({ signedOut: true }));
  }
  if (!(await ensureSession())) {
    if (state.online) return showSignIn({});
    state.offlineView = true;
    return show(screens.needsConnection({ signedOut: true }));
  }
  try {
    if (parts[0] === "sign-out") {
      const view = await deviceView();
      if (!view.unsent) return go("#/");
      state.offlineView = !state.online;
      return show(screens.signOutWarning({ count: view.unsent, online: state.online }));
    }
    if (parts[0] === "device" && parts[2] === "delete") {
      state.offlineView = !state.online;
      return show(screens.deleteNoteWarning({ id: parts[1] }));
    }
    if (!state.online) return await showOffline(parts);
    if (state.user.role === "supervisor") return await renderSupervisor(parts);
    if (state.user.role === "staff") return await renderStaff(parts);
    if (!state.setup || Date.now() - state.setup.received_at > SETUP_REFRESH_MINUTES * 60 * 1000) await refreshSetup().catch(() => {});
    if (parts.length === 0) {
      const [drafts, held, messages] = await Promise.all([api("GET", "/api/v1/drafts"), api("GET", "/api/v1/held"), api("GET", "/api/v1/messages")]);
      return show(screens.home({ user: state.user, drafts, held, messages, device: await deviceView() }));
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
    if (parts[0] === "new" || parts[0] === "update") return show(await noteScreen(parts[0], true));
    if ((parts[0] === "held" || parts[0] === "drafts") && parts[1]) await queue.opened(parts[1], state.user.username);
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
    if (err.network) return await showOffline(parts);
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

// Check the note, seal it in memory, then send it or keep it. Refused text is never sealed, sent, or
// stored: it stays only in the open form.
async function submitNote(name, data) {
  if (!data.text.trim()) throw Object.assign(new Error("Please write your note first."), { keep: true });
  const form = name === "new-note" ? "new" : "update";
  const setup = await readySetup();
  if (!setup) throw new Error("This note could not be prepared, so nothing was saved. Please try again when you have a connection.");
  if (!state.online && !writeAllowed(setup, Date.now())) throw new Error("It has been too long since this device reached the server, so nothing was saved.");
  const rules = compileRules(setup.rules);
  const body = guard(data.text.trim(), rules);
  const title = guard(data.title.trim(), rules);
  if (body.refused || title.refused) throw new Error(setup.rules.refused_message);
  if (body.text.length > NOTE_LIMIT || title.text.length > TITLE_LIMIT) throw new Error("This note is too long, so nothing was saved. Please shorten it.");
  if (body.masked || title.masked) {  // show the worker what will be kept before keeping it
    state.ssnLabel = body.invalidLabel || title.invalidLabel;
    state.forms[form] = { text: body.text, title: title.text, notice: MASKED_NOTICE };
    return render();
  }
  const id = key();  // made here, once: every later attempt reuses it
  const owner = state.user.username;
  const kind = name === "new-note" ? "new_client" : "update";
  const savedAt = new Date().toISOString();
  const envelope = await seal({ text: body.text, title: title.text || null, written_at: savedAt, ssn_invalid_label: state.ssnLabel, contact: setup.contact },
    { publicKey: setup.seal.public_key, keyId: setup.seal.key_id, owner, idempotencyKey: id, kind, savedAt });
  state.ssnLabel = null;
  const row = { id, owner, kind, savedAt, envelope };
  let answer = null;
  if (state.online && state.csrf) {
    const sent = await sendSealed({ ...row, idempotency_key: id, saved_at: savedAt });
    answer = classify(sent);
    if (answer.kind === "uploaded") return landing(sent.data);
    if (answer.kind === "attention") throw new Error(answer.reason);  // nothing was kept; the text is still in the form
  }
  await queue.save(row);
  navigator.storage?.persist?.().catch(() => {});
  if (answer && answer.kind === "wait") await sync.failed(answer);
  if (answer && answer.kind === "signin") {
    state.user = null;
    return go("#/sign-in", { kind: "error", text: "Your note is saved on this device. Please sign in again." });
  }
  return go("#/", { text: "Saved on device. It cannot be read on this device. It will upload by itself when you are back online." });
}

// The manual fallback. It skips the backoff, but never a wait the server asked for.
async function uploadSaved() {
  const out = await sync.trigger("manual");
  if (out.signIn) return undefined;  // sessionEnded has asked the worker to sign in
  if (out.paused) {
    state.user = null;
    return go("#/sign-in", { kind: "error", text: "Please sign in again." });
  }
  if (out.deferred) return go("#/", { text: "The server asked the app to wait. Your notes are safe and will upload by themselves." });
  if (out.busy) return go("#/", { text: "Your notes are already uploading." });
  if (out.waiting) return go("#/", { kind: "error", text: "Some notes could not be uploaded yet. They are still saved on this device and will be tried again." });
  return go("#/", { text: "Your saved notes were sent. Check each one and confirm it." });
}

// Delete everything this user has on the device at once, then end the server's session, now or at
// the next connection. The cookie is HttpOnly, so the page cannot end it alone.
async function signOut() {
  await device.wipeUser(state.user.username);
  state.user = null;
  state.csrf = null;
  state.setup = null;
  state.options = null;
  state.queue = { uploading: 0, needsAttention: 0 };
  await flushSignOut().catch(() => {});
  go("#/sign-in", { text: "You are signed out." });
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
    if (action === "upload-all") await uploadSaved();
    if (action === "retry-note") {
      await queue.retry(ref, state.user.username);
      await uploadSaved();
    }
    if (action === "discard-note") {
      await queue.discard(ref, state.user.username);
      go("#/", { text: "The note was deleted from this device." });
    }
    if (action === "sign-out-wipe") await signOut();
    if (action === "dismiss") {
      await queue.dismiss(ref, state.user.username);
      render();
    }
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
        go("#/");
        return syncSoon("sign-in");
      }
      if (name === "new-note" || name === "update-note") return await submitNote(name, data);
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
    const { unsent } = await queue.view(state.user.username);
    if (unsent) return go("#/sign-out");  // warn first
    await signOut();
  });
});

window.addEventListener("hashchange", () => {
  state.ssnLabel = null;
  if (!state.online) ping();
  render();
});
// What is typed never outlives the page.
window.addEventListener("pagehide", () => {
  for (const id of ["note-title", "note-text"]) {
    const field = document.getElementById(id);
    if (field) field.value = "";
  }
});
for (const event of ["online", "offline"]) window.addEventListener(event, () => ping({ force: true }));
document.addEventListener("visibilitychange", () => { if (!document.hidden) ping(); });

// The connection check: once a minute online, slowing to every two minutes offline. Each one also
// applies the 72-hour limit on a page left open, and gives waiting notes a chance to go.
function armPing() {
  clearTimeout(state.pingTimer);
  const delay = state.online ? ONLINE_CHECK_SECONDS * 1000 : pingDelay(state.offlineChecks++, Math.random);
  state.pingTimer = setTimeout(async () => {
    await ping();
    await queue.sweep().catch(() => {});
    syncSoon("tick");
    armPing();
  }, delay);
}

if (channel) {
  channel.addEventListener("message", (event) => {
    refreshDevice().catch(() => {});
    if (event.data === "uploaded") reloadHome();
  });
}

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
armPing();
Promise.resolve(withUploadLock(() => queue.recover())).catch(() => {}).finally(async () => {
  await render();
  syncSoon("open");
});
