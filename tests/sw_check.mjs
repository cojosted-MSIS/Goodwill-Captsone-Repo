// Runs ui/web/sw.js in a sandbox and reports what it does with each kind of request, for
// tests/test_web_shell.py. Usage: node sw_check.mjs <sw.js>
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(process.argv[2], "utf8").replace("__SHELL_VERSION__", "abc123");
const listeners = {};
const installed = [];
let skipped = 0;
const caches = {
  names: ["outreach-shell-old", "outreach-shell-abc123", "something-else"],
  deleted: [],
  async open() { return { addAll: async (reqs) => installed.push(...reqs.map((r) => r.url || r)), match: async () => ({ hit: true }) }; },
  async keys() { return this.names; },
  async delete(name) { this.deleted.push(name); return true; },
  async match() { return { hit: true, offlinePage: true }; },
};
const self = {
  location: new URL("http://127.0.0.1:8000/app/sw.js"),
  addEventListener: (type, fn) => { listeners[type] = fn; },
  skipWaiting: () => { skipped += 1; },
  clients: { claim: async () => {} },
};
class Req { constructor(url, init) { this.url = url; Object.assign(this, init); } }
const fetchStub = async () => { throw new TypeError("no network"); };
vm.runInNewContext(source, { self, caches, URL, Request: Req, fetch: fetchStub, Promise, location: self.location, console });

const out = {};
async function ask(label, url, method = "GET", mode = "cors") {
  let responded = null;
  listeners.fetch({ request: { url: new URL(url, "http://127.0.0.1:8000").href, method, mode }, respondWith: (p) => { responded = p; } });
  if (!responded) { out[label] = "not-handled"; return; }
  const r = await responded;
  out[label] = r && r.offlinePage ? "network-then-offline-page" : "cache-first";
}
for (const u of ["/app/", "/app/index.html", "/app/app.js", "/app/style.css", "/app/fonts/inter-latin-wght-normal.woff2",
  "/api/v1/drafts", "/api/v1/session", "/api/v1/ping", "/api/v1/supervisor/queue", "/app/sw.js", "/drafts/ENC-1"]) await ask(`GET ${u}`, u);
await ask("POST /app/app.js", "/app/app.js", "POST");
await ask("POST /api/v1/notes/new-client", "/api/v1/notes/new-client", "POST");
await ask("GET https://other.example/app/app.js", "https://other.example/app/app.js");
await ask("NAVIGATE /app/unknown", "/app/unknown", "GET", "navigate");
await ask("NAVIGATE /api/v1/drafts", "/api/v1/drafts", "GET", "navigate");

let wait;
listeners.install({ waitUntil: (p) => { wait = p; } });
await wait;
out.installed = installed;
out.skip_waiting_on_install = skipped > 0;
listeners.message({ data: { type: "activate" } });
out.skip_waiting_on_message = skipped > 0;
listeners.activate({ waitUntil: (p) => { wait = p; } });
await wait;
out.deleted_on_activate = caches.deleted;
out.kept_unrelated = !caches.deleted.includes("something-else");
process.stdout.write(JSON.stringify(out));
