// Stage 4c offline queue scenarios in real Chrome, for tests/test_offline_queue_browser.py. A plan
// comes in on stdin; observations go out as JSON, and pytest makes the assertions. "Offline" here
// always means the app server process is really stopped.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { App, Browser, until } from "./cdp.mjs";

const plan = JSON.parse(readFileSync(0, "utf8"));
const app = new App(plan);
const b = await Browser.launch(plan.browser);
const out = {};
const pw = plan.passwords;

const nudge = (type) => b.eval(`window.dispatchEvent(new Event(${JSON.stringify(type)}))`);
const pillIs = (word) => until(async () => (await b.pill()) === word, `the status line to say ${word}`);
const fill = (title, text) => b.eval(`(() => { document.getElementById("note-title").value = ${JSON.stringify(title)};
  document.getElementById("note-text").value = ${JSON.stringify(text)}; })()`);
const submitForm = 'document.querySelector("form[data-form=new-note]").requestSubmit()';
async function submit(hash) {
  const before = await b.renders();
  await b.eval(submitForm);
  await b.afterRender(before, hash);
}
async function click(selector, hash) {
  const before = await b.renders();
  await b.eval(`document.querySelector(${JSON.stringify(selector)}).click()`);
  await b.afterRender(before, hash);
}
async function goOffline() {
  await app.stop();
  await b.reload();
  await pillIs("Offline");
}
async function goOnline() {
  await app.start("first-build");
  await nudge("online");
  await pillIs("Online");
}
async function write(title, text) {
  await b.hash("#/new");
  await fill(title, text);
  await submit("#/");
}
const queueRows = async () => {
  const seen = await b.inspect();
  return ((seen.idb["outreach-device"] || {}).queue || []).map(([, value]) => value);
};
const backdate = (id, hoursAgo) => b.eval(`(async () => {
  const db = await new Promise((res, rej) => { const r = indexedDB.open("outreach-device"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const row = await new Promise((res) => { const r = db.transaction("queue").objectStore("queue").get(${JSON.stringify(id)}); r.onsuccess = () => res(r.result); });
  row.saved_at = new Date(Date.now() - ${hoursAgo} * 3600 * 1000).toISOString();
  await new Promise((res, rej) => { const tx = db.transaction("queue", "readwrite"); tx.objectStore("queue").put(row); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  db.close();
})()`);
const apiRequests = (from) => b.requests.slice(from).filter((r) => r.url.includes("/api/"));
const sessionCookie = async () => (await b.page("Network.getCookies", { urls: [app.base] })).cookies.find((c) => c.name === "hmis_session");

try {
  await app.start("first-build");
  await b.open();
  await b.goto(`${app.base}/app/#/sign-in`, "#/sign-in");
  await b.signIn("j.alvarez", pw.j_alvarez);
  await b.workerActive();
  await until(async () => ((await b.inspect()).idb["outreach-device"].meta || []).some(([k]) => k === "setup"), "the device setup");
  out.signed_in = await b.inspect();

  // A. A note written with the server really stopped.
  await app.stop();
  let mark = b.requests.length;
  await b.reload();
  await b.hash("#/new");
  out.a_form = await b.eval(`({ text: document.body.innerText, button: document.querySelector("form button[type=submit]").innerText,
    form: document.querySelector("form[data-form=new-note]").getAttribute("autocomplete"),
    textarea: [document.getElementById("note-text").getAttribute("autocomplete"), document.getElementById("note-text").getAttribute("spellcheck")] })`);
  await fill(plan.title, plan.note);
  await submit("#/");
  out.a_home = { text: await b.text(), pill: await b.pill(), html: await b.eval("document.getElementById('main').innerHTML") };
  out.a_inspect = await b.inspect();
  out.a_requests = b.requests.slice(mark);

  // B. A full SSN is masked first, shown, and only then saved.
  await b.hash("#/new");
  await fill("Pat 345-67-8912", plan.masked_note);
  const rowsBeforeMask = (await queueRows()).length;
  await submit("#/new");
  out.b_form = await b.eval(`({ text: document.getElementById("note-text").value, title: document.getElementById("note-title").value, page: document.body.innerText })`);
  out.b_saved_after_first_press = (await queueRows()).length - rowsBeforeMask;
  out.b_mid_inspect = await b.inspect();
  await submit("#/");
  out.b_inspect = await b.inspect();

  // C. A refused note is written nowhere.
  mark = b.requests.length;
  await b.hash("#/new");
  await fill(plan.refused_title, plan.refused_note);
  const rowsBeforeRefusal = (await queueRows()).length;
  await submit("#/new");
  out.c_form = await b.eval(`({ text: document.getElementById("note-text").value, page: document.body.innerText })`);
  out.c_saved = (await queueRows()).length - rowsBeforeRefusal;
  out.c_in_form_inspect = await b.inspect();
  await b.hash("#/");
  await b.hash("#/new");
  out.c_after_leaving = await b.eval('document.getElementById("note-text").value');
  out.c_inspect = await b.inspect();
  out.c_requests = b.requests.slice(mark);

  // D. The 60-hour warning, then the 72-hour expiry (the saved time moved back; the clock is real).
  const idsBefore = new Set((await queueRows()).map((r) => r.id));
  await write("", plan.expiring_note);
  const expiring = (await queueRows()).find((r) => !idsBefore.has(r.id)).id;
  await backdate(expiring, 61);
  await b.hash("#/");
  out.d_warning = await b.text();
  await backdate(expiring, 73);
  await b.reload();
  out.d_expired = await b.text();
  out.d_inspect = await b.inspect();
  out.d_stopped = await fetch(`${app.base}/api/v1/ping`).then(() => false, () => true);
  await click("[data-action=dismiss]", "#/");
  out.d_dismissed = await b.text();

  // E. Back online: still waiting until the worker presses Upload (automatic upload is checkpoint 4d).
  await goOnline();
  await until(async () => (await b.text()).includes("Recent"), "the real home screen");
  out.e_before = await b.text();
  mark = b.requests.length;
  await click("[data-action=upload-all]");
  await until(async () => !(await b.text()).includes("Saved on device"), "the notes to upload");
  out.e_home = await b.text();
  out.e_html = await b.eval("document.getElementById('main').innerHTML");
  out.e_inspect = await b.inspect();
  out.e_requests = apiRequests(mark);
  out.e_drafts = await b.eval('fetch("/api/v1/drafts").then((r) => r.json())');
  out.e_held = await b.eval('fetch("/api/v1/held").then((r) => r.json())');

  // E2. A refused note is not sent even when the server can be reached.
  mark = b.requests.length;
  await b.hash("#/new");
  await fill(plan.refused_title, plan.refused_note);
  await submit("#/new");
  out.e2_form = await b.eval(`({ text: document.getElementById("note-text").value, page: document.body.innerText })`);
  out.e2_inspect = await b.inspect();
  out.e2_requests = apiRequests(mark);

  // F. The server goes while the page still thinks it is online: the failed upload is saved.
  await b.hash("#/new");
  await fill("", plan.failed_note);
  await app.stop();
  mark = b.requests.length;
  await submit("#/");
  out.f_home = { text: await b.text(), pill: await b.pill() };
  out.f_inspect = await b.inspect();
  out.f_requests = b.requests.slice(mark);

  // G. Sign-out warns, and can upload first.
  await goOnline();
  await until(async () => (await b.text()).includes("Upload my saved notes"), "the home screen with the saved note");
  await click("#sign-out", "#/sign-out");
  out.g_warning = await b.text();
  mark = b.requests.length;
  await click("[data-action=upload-all]");
  await until(async () => (await queueRows()).every((r) => !r.envelope), "the upload from the warning");
  out.g_inspect = await b.inspect();
  out.g_requests = apiRequests(mark);

  // H. Sign-out while offline wipes at once and leaves only the pending flag.
  await goOffline();
  await write("", plan.wiped_note);
  const cookie = await sessionCookie();
  await click("#sign-out", "#/sign-out");
  out.h_warning = await b.text();
  await click("[data-action=sign-out-wipe]", "#/sign-in");
  out.h_after = await b.text();
  out.h_inspect = await b.inspect();
  out.h_stopped = await fetch(`${app.base}/api/v1/ping`).then(() => false, () => true);

  // I. Back online, the sign-out goes first; nobody can sign in until it completes.
  await b.page("Network.setBlockedURLs", { urls: ["*sign-out-device*"] });
  mark = b.requests.length;
  await app.start("first-build");
  await nudge("online");
  await until(async () => (await b.text()).includes("finishing"), "the finishing notice");
  out.i_blocked_text = await b.text();
  out.i_blocked_form = await b.eval('Boolean(document.querySelector("form[data-form=sign-in]"))');
  out.i_blocked_session = (await fetch(`${app.base}/api/v1/session`, { headers: { Cookie: `hmis_session=${cookie.value}` } })).status;
  out.i_blocked_flag = ((await b.inspect()).idb["outreach-device"].meta || []).some(([k]) => k === "pending_sign_out");
  await b.page("Network.setBlockedURLs", { urls: [] });
  await nudge("online");
  await until(() => b.eval('Boolean(document.querySelector("form[data-form=sign-in]"))'), "the sign-in form");
  out.i_old_session = (await fetch(`${app.base}/api/v1/session`, { headers: { Cookie: `hmis_session=${cookie.value}` } })).status;
  out.i_inspect = await b.inspect();

  // Another worker signs in on the same device.
  await b.signIn("m.chen", pw.m_chen);
  out.i_requests = apiRequests(mark);
  out.i_chen_home = await b.text();
  out.i_chen_inspect = await b.inspect();
  out.i_chen_session = await b.eval('fetch("/api/v1/session").then((r) => r.json())');
  await click("#sign-out", "#/sign-in");

  // J. A timed-out session keeps the envelope; another account sees only that one is waiting.
  await b.signIn("j.alvarez", pw.j_alvarez);
  await until(async () => ((await b.inspect()).idb["outreach-device"].meta || []).some(([k, v]) => k === "setup" && v.owner === "j.alvarez"), "the setup for j.alvarez");
  await goOffline();
  await write("", plan.shared_note);
  await app.start("first-build");
  await b.page("Network.deleteCookies", { name: "hmis_session", url: `${app.base}/` });
  await nudge("online");
  await until(() => b.eval('Boolean(document.querySelector("form[data-form=sign-in]"))'), "the sign-in form after the session ended");
  out.j_timed_out_text = await b.text();
  out.j_timed_out_inspect = await b.inspect();
  const [held] = (await queueRows()).filter((r) => r.envelope);

  await b.signIn("m.chen", pw.m_chen);
  out.j_chen_text = await b.text();
  out.j_chen_html = await b.eval("document.getElementById('main').innerHTML");
  out.j_chen_view_inspect = await b.inspect();
  mark = b.requests.length;
  out.j_forced = await b.eval(`(async () => {
    const me = await (await fetch("/api/v1/session")).json();
    const held = ${JSON.stringify(held)};
    const res = await fetch("/api/v1/notes/sealed", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token, "Idempotency-Key": held.idempotency_key },
      body: JSON.stringify({ kind: held.kind, saved_at: held.saved_at, envelope: held.envelope }) });
    return { status: res.status, code: (await res.json()).detail.code, drafts: await (await fetch("/api/v1/drafts")).json() };
  })()`);
  await click("#sign-out", "#/sign-in");
  out.j_after_chen_inspect = await b.inspect();

  await b.signIn("j.alvarez", pw.j_alvarez);
  await until(async () => (await b.text()).includes("Upload my saved notes"), "the owner's note");
  out.j_owner_text = await b.text();
  await click("[data-action=upload-all]");
  await until(async () => (await queueRows()).every((r) => !r.envelope), "the owner's upload");
  out.j_owner_inspect = await b.inspect();

  out.violations = b.violations;
  out.all_requests = b.requests;
} catch (err) {
  out.error = String(err && err.stack || err);
  try { out.error_text = await b.text(); } catch { /* the page may be gone */ }
} finally {
  await b.close();
  if (app.proc && app.proc.exitCode === null) await app.stop().catch(() => {});
  // Supporting evidence only: storage engines may compress values, so a clean search proves little.
  const hits = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      try {
        if (statSync(path).isDirectory()) walk(path);
        else {
          const data = readFileSync(path);
          for (const word of plan.sentinels) if (data.includes(word)) hits.push(`${word} in ${path.slice(b.profile.length)}`);
        }
      } catch { /* a file still held by the browser */ }
    }
  };
  try { walk(b.profile); } catch { /* the profile may be gone */ }
  out.profile_hits = hits;
  b.removeProfile();
}
process.stdout.write(JSON.stringify(out));
