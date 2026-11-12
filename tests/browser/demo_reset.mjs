// Stage 4e: what the demo reset does to a real device, in real Chrome, for
// tests/test_demo_reset_browser.py. "Offline" means the app server process is really stopped.
import { readFileSync } from "node:fs";
import { App, Browser, sleep, until } from "./cdp.mjs";

const plan = JSON.parse(readFileSync(0, "utf8"));
const app = new App(plan);
const b = await Browser.launch(plan.browser);
const out = {};

const nudge = () => b.eval('window.dispatchEvent(new Event("online"))');
const pillIs = (word) => until(async () => (await b.pill()) === word, `the status line to say ${word}`);
const rows = async () => (((await b.inspect()).idb["outreach-device"] || {}).queue || []).map(([, v]) => v);
const meta = async () => Object.fromEntries(((await b.inspect()).idb["outreach-device"] || {}).meta || []);
async function write(text) {
  await b.hash("#/new");
  const before = await b.renders();
  await b.eval(`(() => { document.getElementById("note-text").value = ${JSON.stringify(text)}; document.querySelector("form[data-form=new-note]").requestSubmit(); })()`);
  await b.afterRender(before, "#/");
}

try {
  await app.start("first-build");
  await b.open();
  await b.goto(`${app.base}/app/#/sign-in`, "#/sign-in");
  await b.signIn("j.alvarez", plan.password);
  await b.workerActive();
  await until(async () => (await meta()).setup, "the device setup");
  out.first_epoch = (await meta()).demo_epoch;

  // A restart is not a reset: the K key must never lose a note.
  await app.stop();
  await b.reload();
  await pillIs("Offline");
  await write(plan.note);
  out.before_restart = await b.inspect();
  await b.intercept("*/api/v1/notes/sealed", "Request", (p) => b.drop(p));  // keep the note waiting
  await app.start("first-build");
  await nudge();
  await until(async () => (await b.text()).includes("Upload my saved notes"), "the home screen after the restart");
  out.after_restart = await b.inspect();
  out.after_restart_text = await b.text();

  // The reset, as demo.py sends it.
  const mark = b.requests.length;
  out.reset = await b.eval(`(async () => {
    const me = await (await fetch("/api/v1/session")).json();
    const res = await fetch("/api/v1/demo/reset", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token }, body: JSON.stringify({ confirm: "reset demo" }) });
    return { status: res.status, body: await res.json() };
  })()`);
  await nudge();
  await until(async () => (await rows()).length === 0, "the device to be cleared");
  await until(async () => (await b.text()).includes("Demo reset"), "the notice");
  await b.stopIntercept();
  await sleep(300);
  out.after_reset = await b.inspect();
  out.after_reset_text = await b.text();
  out.after_reset_requests = b.requests.slice(mark).filter((r) => r.url.includes("/api/"));
  out.violations = b.violations;
} catch (err) {
  out.error = String(err && err.stack || err);
  try { out.error_text = await b.text(); } catch { /* the page may be gone */ }
} finally {
  await b.close();
  if (app.proc && app.proc.exitCode === null) await app.stop().catch(() => {});
  b.removeProfile();
}
process.stdout.write(JSON.stringify(out));
