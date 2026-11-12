// A small DevTools-protocol driver for the offline tests: real Chrome, a real app server that can
// be stopped and restarted, and helpers that inspect everything a browser could have stored.
// Node's built-in WebSocket only: no packages.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, openSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function until(check, label, tries = 400, gap = 50) {
  for (let i = 0; i < tries; i++) {
    const value = await check().catch(() => null);
    if (value) return value;
    await sleep(gap);
  }
  throw new Error(`timed out waiting for ${label}`);
}

// The real app server: a separate process, so "offline" can mean it is actually gone.
export class App {
  constructor(plan) { this.plan = plan; this.base = `http://127.0.0.1:${plan.port}`; }
  async start(salt = "first-build") {
    const log = openSync(this.plan.log, "a");
    this.proc = spawn(this.plan.python, ["-m", "app", "--port", String(this.plan.port), "--db", this.plan.db, ...(this.plan.app_args || [])], {
      cwd: this.plan.root, stdio: ["ignore", log, log], env: { ...process.env, ...this.plan.env, INTAKE_SHELL_SALT: salt },
    });
    await until(async () => (await fetch(`${this.base}/api/v1/ping`)).ok, "the app server to start");
  }
  async stop() {
    const proc = this.proc;
    this.proc = null;  // stopped: a later clean-up must not wait for it again
    const gone = new Promise((r) => proc.once("exit", r));
    proc.kill();
    await gone;
    await until(async () => { try { await fetch(`${this.base}/api/v1/ping`); return false; } catch { return true; } }, "the app server to stop");
  }
}

export class Browser {
  static async launch(path, { headless = true } = {}) {
    const b = new Browser();
    b.profile = mkdtempSync(join(tmpdir(), "offline-test-"));
    b.proc = spawn(path, [...(headless ? ["--headless=new", "--disable-gpu"] : []), "--no-first-run", "--remote-debugging-port=0", `--user-data-dir=${b.profile}`, "about:blank"], { stdio: "ignore" });
    const file = join(b.profile, "DevToolsActivePort");
    const url = await until(async () => {
      if (!existsSync(file)) return null;
      const [port, p] = readFileSync(file, "utf8").split("\n");
      return port && p ? `ws://127.0.0.1:${port.trim()}${p.trim()}` : null;
    }, "the browser to start");
    b.ws = new WebSocket(url);
    await new Promise((res, rej) => { b.ws.onopen = res; b.ws.onerror = rej; });
    b.id = 0; b.pending = new Map(); b.requests = []; b.violations = []; b.workers = new Set(); b.cookies = new Map();
    b.ws.onmessage = (e) => b.onMessage(JSON.parse(e.data));
    return b;
  }
  onMessage(m) {
    if (m.id && this.pending.has(m.id)) {
      const { res, rej } = this.pending.get(m.id);
      this.pending.delete(m.id);
      if (m.error) rej(new Error(m.error.message)); else res(m.result);
      return;
    }
    if (m.method === "Network.requestWillBeSent") {
      this.requests.push({ id: m.params.requestId, url: m.params.request.url, method: m.params.request.method, postData: m.params.request.postData || "", headers: m.params.request.headers, sentCookie: this.cookies.get(m.params.requestId), at: Date.now() });
    }
    if (m.method === "Network.requestWillBeSentExtraInfo") {  // what was really sent; only whether a cookie went is kept
      const sent = Object.keys(m.params.headers).some((h) => h.toLowerCase() === "cookie");
      this.cookies.set(m.params.requestId, sent);
      const r = this.requests.findLast((q) => q.id === m.params.requestId);
      if (r) r.sentCookie = sent;
    }
    if (m.method === "Network.responseReceived") {
      const r = this.requests.findLast((q) => q.url === m.params.response.url);
      if (r) { r.status = m.params.response.status; r.fromServiceWorker = Boolean(m.params.response.fromServiceWorker); r.cacheControl = m.params.response.headers["cache-control"] || m.params.response.headers["Cache-Control"]; }
    }
    if (m.method === "Fetch.requestPaused" && this.onPaused) this.onPaused(m.params, m.sessionId);
    if (m.method === "Log.entryAdded" && /Content Security Policy/i.test(m.params.entry.text)) this.violations.push(m.params.entry.text);
    if (m.method === "Target.attachedToTarget" && m.params.targetInfo.type === "service_worker") {
      this.workers.add(m.params.sessionId);
      this.send("Network.enable", {}, m.params.sessionId).catch(() => {});
    }
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((res, rej) => this.pending.set(id, { res, rej }));
  }
  async open() {
    const { targetId } = await this.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await this.send("Target.attachToTarget", { targetId, flatten: true });
    this.session = sessionId;
    for (const d of ["Page", "Runtime", "Network", "Log"]) await this.page(`${d}.enable`);
    await this.send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true }, sessionId);
    await this.send("Target.setDiscoverTargets", { discover: true });
    await this.send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
  }
  page(method, params) { return this.send(method, params, this.session); }
  // Stop requests matching `url` at a stage ("Request", or "Response" after the server has answered), in
  // the given tabs. `handler(paused, sessionId)` then continues, fails, or answers each one.
  async intercept(url, stage, handler, sessions = [this.session]) {
    this.onPaused = handler;
    this.intercepted = sessions;
    for (const s of sessions) await this.send("Fetch.enable", { patterns: [{ urlPattern: url, requestStage: stage }] }, s);
  }
  async stopIntercept() {
    for (const s of this.intercepted || []) await this.send("Fetch.disable", {}, s);
    this.onPaused = null;
  }
  proceed(paused, session = this.session) { return this.send("Fetch.continueRequest", { requestId: paused.requestId }, session).catch(() => {}); }
  drop(paused, session = this.session) { return this.send("Fetch.failRequest", { requestId: paused.requestId, errorReason: "ConnectionReset" }, session).catch(() => {}); }
  answer(paused, status, headers, session = this.session) {
    return this.send("Fetch.fulfillRequest", { requestId: paused.requestId, responseCode: status, responseHeaders: headers, body: btoa("{}") }, session);
  }
  async openTab(url) {
    const { targetId } = await this.send("Target.createTarget", { url });
    const { sessionId } = await this.send("Target.attachToTarget", { targetId, flatten: true });
    for (const d of ["Page", "Runtime", "Network", "Log"]) await this.send(`${d}.enable`, {}, sessionId);
    return { targetId, sessionId };
  }
  closeTab(tab) { return this.send("Target.closeTarget", { targetId: tab.targetId }); }
  async evalIn(sessionId, expression) {
    const r = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  }
  async eval(expression) {
    const r = await this.page("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  }
  renders() { return this.eval("Number(document.documentElement.dataset.renders || 0)"); }
  async afterRender(before, hash) {
    await until(async () => {
      const [n, ready, at] = await this.eval("[Number(document.documentElement.dataset.renders || 0), document.documentElement.dataset.ready, location.hash]");
      return n > before && ready === "1" && (!hash || at === hash);
    }, `the screen ${hash || ""} to render`);
  }
  async goto(url, hash) { await this.page("Page.navigate", { url }); await sleep(100); await this.afterRender(0, hash); }
  async reload() { await this.page("Page.reload", { ignoreCache: false }); await sleep(200); await this.afterRender(0); }
  async hash(hash) {
    const before = await this.renders();
    await this.eval(`location.hash === ${JSON.stringify(hash)} ? window.dispatchEvent(new HashChangeEvent("hashchange")) : (location.hash = ${JSON.stringify(hash)})`);
    await this.afterRender(before, hash);
  }
  async signIn(username, password) {
    const before = await this.renders();
    await this.eval(`(() => { document.getElementById("username").value = ${JSON.stringify(username)};
      document.getElementById("password").value = ${JSON.stringify(password)};
      document.querySelector("form[data-form=sign-in]").requestSubmit(); })()`);
    await this.afterRender(before, "#/");
  }
  workerActive() { return until(() => this.eval("navigator.serviceWorker.ready.then(() => Boolean(navigator.serviceWorker.controller))"), "the service worker to take control"); }
  async network(offline) {
    const c = { offline, latency: 0, downloadThroughput: -1, uploadThroughput: -1 };
    await this.page("Network.emulateNetworkConditions", c);
    for (const w of this.workers) await this.send("Network.emulateNetworkConditions", c, w).catch(() => {});
  }
  // Everything the browser could have kept, for the test to check.
  inspect() {
    return this.eval(`(async () => {
      const dump = (s) => Object.fromEntries(Object.keys(s).map((k) => [k, s.getItem(k)]));
      const idb = {};
      for (const info of await indexedDB.databases()) {
        const db = await new Promise((res, rej) => { const r = indexedDB.open(info.name); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
        idb[info.name] = {};
        for (const store of db.objectStoreNames) {
          const tx = db.transaction(store);
          const os = tx.objectStore(store);
          const [keys, values] = await Promise.all([os.getAllKeys(), os.getAll()].map((r) => new Promise((res) => { r.onsuccess = () => res(r.result); })));
          idb[info.name][store] = keys.map((k, i) => [k, values[i]]);
        }
        db.close();
      }
      const cache = {};
      for (const name of await caches.keys()) cache[name] = (await (await caches.open(name)).keys()).map((r) => new URL(r.url).pathname);
      return { local: dump(localStorage), session: dump(sessionStorage), idb, cache };
    })()`);
  }
  text() { return this.eval("document.body.innerText"); }
  pill() { return this.eval('document.getElementById("sync-status").innerText.trim()'); }
  async close() {
    this.ws.close();
    this.proc.kill();
    await sleep(500);
  }
  removeProfile() { try { rmSync(this.profile, { recursive: true, force: true }); } catch { /* the browser may still hold a file */ } }
}
