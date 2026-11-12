// Stage 4d sync scenarios in real Chrome, for tests/test_offline_sync_browser.py. A plan comes in on
// stdin; observations go out as JSON, and pytest makes the assertions. "Offline" always means the app
// server process is really stopped. A "lost response" means the real server handled the request and
// the browser then lost its answer, using the DevTools Fetch domain at the response stage.
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { App, Browser, sleep, until } from "./cdp.mjs";

const plan = JSON.parse(readFileSync(0, "utf8"));
const app = new App(plan);
const b = await Browser.launch(plan.browser);
const out = {};
const pw = plan.passwords;
const SEALED = "*/api/v1/notes/sealed";

const nudge = (type) => b.eval(`window.dispatchEvent(new Event(${JSON.stringify(type)}))`);
const pillIs = (word) => until(async () => (await b.pill()) === word, `the status line to say ${word}`);
const fill = (text) => b.eval(`(() => { document.getElementById("note-title").value = "";
  document.getElementById("note-text").value = ${JSON.stringify(text)}; })()`);
async function submit(hash) {
  const before = await b.renders();
  await b.eval('document.querySelector("form[data-form=new-note]").requestSubmit()');
  await b.afterRender(before, hash);
}
// A background refresh can replace a button for a moment, so wait until one is there to press.
const press = (selector) => until(() => b.eval(`(() => { const x = document.querySelector(${JSON.stringify(selector)}); if (!x || x.disabled) return false; x.click(); return true; })()`), `the button ${selector}`);
async function click(selector, hash) {
  const before = await b.renders();
  await press(selector);
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
}
async function write(text) {
  await b.hash("#/new");
  await fill(text);
  await submit("#/");
}
const queueRows = async () => (((await b.inspect()).idb["outreach-device"] || {}).queue || []).map(([, value]) => value);
const noEnvelopes = (label) => until(async () => (await queueRows()).every((r) => !r.envelope), label);
const putRow = (row) => b.eval(`(async () => {
  const db = await new Promise((res, rej) => { const r = indexedDB.open("outreach-device"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  await new Promise((res, rej) => { const tx = db.transaction("queue", "readwrite"); tx.objectStore("queue").put(${JSON.stringify(row)}); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  db.close();
})()`);
const clearUploaded = () => b.eval(`(async () => {
  const db = await new Promise((res, rej) => { const r = indexedDB.open("outreach-device"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const rows = await new Promise((res) => { const r = db.transaction("queue").objectStore("queue").getAll(); r.onsuccess = () => res(r.result); });
  await new Promise((res, rej) => { const tx = db.transaction("queue", "readwrite"); for (const row of rows) if (row.status === "uploaded") tx.objectStore("queue").delete(row.id); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  db.close();
})()`);
const serverCount = () => b.eval('Promise.all([fetch("/api/v1/drafts").then((r) => r.json()), fetch("/api/v1/held").then((r) => r.json())]).then(([d, h]) => d.length + h.length)');
const api = (from) => b.requests.slice(from).filter((r) => r.url.includes("/api/"));
const sealedPosts = (from) => api(from).filter((r) => r.method === "POST" && r.url.endsWith("/notes/sealed"));

try {
  await app.start("first-build");
  await b.open();
  await b.goto(`${app.base}/app/#/sign-in`, "#/sign-in");
  await b.signIn("j.alvarez", pw.j_alvarez);
  await b.workerActive();
  await until(async () => ((await b.inspect()).idb["outreach-device"].meta || []).some(([k]) => k === "setup"), "the device setup");

  // S1. The connection returns: the notes upload by themselves, one at a time, and the status shows it.
  await goOffline();
  let mark = b.requests.length;
  await write(plan.notes.auto_1);
  await write(plan.notes.auto_2);
  out.s1_saved = { text: await b.text(), pill: await b.pill(), inspect: await b.inspect(), requests: b.requests.slice(mark) };
  const held = [];
  await b.intercept(SEALED, "Request", (p, s) => { held.push({ p, s }); });
  mark = b.requests.length;
  await goOnline();
  await until(async () => held.length >= 1, "the first upload to start");
  await until(async () => (await b.text()).includes("Uploading"), "the Uploading status");
  out.s1_uploading = { text: await b.text(), pill: await b.pill(), inspect: await b.inspect() };
  await sleep(300);
  out.s1_held_at_once = held.length;
  b.onPaused = (p, s) => b.proceed(p, s);
  for (const h of held) await b.proceed(h.p, h.s);
  await noEnvelopes("the notes to upload");
  await until(async () => (await b.text()).includes("In review"), "the drafts on My notes");
  await pillIs("Online");
  await b.stopIntercept();
  out.s1_done = { text: await b.text(), pill: await b.pill(), inspect: await b.inspect(), requests: api(mark) };

  // The worker reviews on the server's screen; opening it clears the row.
  const [uploaded] = await queueRows();
  await b.hash(`#/drafts/${uploaded.ref}`);
  out.s1_review = { text: await b.text(), confirm: await b.eval('(() => { const c = document.querySelector("[data-action=confirm]"); return c ? c.disabled : null; })()') };
  await b.hash("#/");
  out.s1_rows_after_open = (await queueRows()).map((r) => r.ref);
  await clearUploaded();

  // S2. Opening the app uploads what is waiting.
  await goOffline();
  await write(plan.notes.open);
  await app.start("first-build");
  mark = b.requests.length;
  await b.reload();
  await noEnvelopes("the upload at app open");
  out.s2 = { inspect: await b.inspect(), requests: api(mark) };
  await clearUploaded();

  // S3. A lost response on a queued note: the server made the draft, the answer never arrived.
  const lostBefore = await serverCount();
  await goOffline();
  await write(plan.notes.lost_2);
  const [lostRow] = (await queueRows()).filter((r) => r.envelope);
  let dropped = 0;
  await b.intercept(SEALED, "Response", (p) => { if (dropped++ === 0) b.drop(p); else b.proceed(p); });
  mark = b.requests.length;
  await goOnline();
  await noEnvelopes("the retry after the lost response");
  await b.stopIntercept();
  out.s3 = { before: lostBefore, after: await serverCount(), key: lostRow.idempotency_key, envelope: lostRow.envelope, dropped, requests: sealedPosts(mark), inspect: await b.inspect() };
  await clearUploaded();

  // S3b. A lost response on a note sent while online: it is saved under the same key, and retried.
  await b.hash("#/");
  const directBefore = await serverCount();
  dropped = 0;
  await b.intercept(SEALED, "Response", (p) => { if (dropped++ === 0) b.drop(p); else b.proceed(p); });
  mark = b.requests.length;
  await b.hash("#/new");
  await fill(plan.notes.direct);
  await submit("#/");
  out.s3b_saved = { text: await b.text(), pill: await b.pill(), inspect: await b.inspect() };
  await noEnvelopes("the retry after the direct lost response");
  await b.stopIntercept();
  out.s3b = { before: directBefore, after: await serverCount(), requests: sealedPosts(mark), inspect: await b.inspect() };
  await clearUploaded();

  // S4. 429 with Retry-After: nothing is sent early, even if the worker presses the button.
  await goOffline();
  await write(plan.notes.limited);
  const times = [];
  await b.intercept(SEALED, "Request", (p) => { times.push(Date.now()); if (times.length === 1) b.answer(p, 429, [{ name: "Retry-After", value: "4" }, { name: "Content-Type", value: "application/json" }]); else b.proceed(p); });
  await goOnline();
  await until(async () => times.length >= 1, "the first attempt");
  await press("[data-action=upload-all]");
  await sleep(1000);
  out.s4_seen_early = times.length;
  out.s4_saved = { text: await b.text(), inspect: await b.inspect() };
  await noEnvelopes("the upload after Retry-After");
  await b.stopIntercept();
  out.s4 = { gap_ms: times[1] - times[0], attempts: times.length, inspect: await b.inspect() };
  await clearUploaded();

  // S5. The manual button still works when automatic uploads keep failing.
  await goOffline();
  await write(plan.notes.manual);
  let failedAttempts = 0, passing = false;
  await b.intercept(SEALED, "Request", (p) => { if (passing) { b.proceed(p); } else { failedAttempts++; b.drop(p); } });
  await goOnline();
  await until(async () => failedAttempts >= 1, "the first failed attempt");
  await until(async () => (await b.text()).includes("Upload my saved notes"), "the manual button");
  out.s5_waiting = { text: await b.text(), pill: await b.pill(), attempts: failedAttempts };
  mark = b.requests.length;
  await press("[data-action=upload-all]");  // the upload still fails until the button has been pressed
  passing = true;
  await noEnvelopes("the manual upload");
  await b.stopIntercept();
  out.s5 = { requests: sealedPosts(mark), inspect: await b.inspect() };
  await clearUploaded();

  // S6. Two tabs: one upload at a time, and each note sent once.
  await goOffline();
  for (const n of plan.notes.tabs) await write(n);
  const keys = (await queueRows()).filter((r) => r.envelope).map((r) => r.idempotency_key);
  const tab = await b.openTab(`${app.base}/app/#/`);
  await until(() => b.evalIn(tab.sessionId, 'document.documentElement.dataset.ready === "1"'), "the second tab");
  let inFlight = 0, maxInFlight = 0;
  const seen = [];
  const slow = async (p, s) => {
    inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
    seen.push({ key: p.request.headers["Idempotency-Key"], session: s });
    await sleep(700);
    inFlight--;
    b.proceed(p, s);
  };
  await b.intercept(SEALED, "Request", slow, [b.session, tab.sessionId]);
  const twoBefore = b.requests.length;
  await app.start("first-build");
  const fire = 'window.dispatchEvent(new Event("online"))';
  await Promise.all([b.eval(fire), b.evalIn(tab.sessionId, fire)]);
  await sleep(150);
  await Promise.all([b.eval(fire), b.evalIn(tab.sessionId, fire)]);
  await noEnvelopes("both tabs' uploads");
  await until(() => b.evalIn(tab.sessionId, 'document.body.innerText.includes("Uploaded")'), "the second tab to show the result");
  await b.stopIntercept();
  out.s6 = { keys, seen, max_in_flight: maxInFlight, requests: sealedPosts(twoBefore), inspect: await b.inspect(), other_tab_text: await b.evalIn(tab.sessionId, "document.body.innerText") };
  await b.closeTab(tab);
  await clearUploaded();

  // S7. An expired session: stop, keep the envelopes, ask to sign in, resume after.
  await goOffline();
  await write(plan.notes.expired_1);
  await write(plan.notes.expired_2);
  const db = new DatabaseSync(plan.db);  // the server is stopped; the browser still sends its old cookie
  db.exec("DELETE FROM sessions");
  db.close();
  mark = b.requests.length;
  await goOnline();
  await until(async () => (await b.text()).includes("Sign in to upload your 2 saved notes"), "the sign-in prompt");
  await sleep(500);
  out.s7_prompt = { text: await b.text(), inspect: await b.inspect(), requests: api(mark), sign_out_shown: await b.eval('getComputedStyle(document.getElementById("sign-out")).display !== "none"') };
  mark = b.requests.length;
  await b.signIn("j.alvarez", pw.j_alvarez);
  await noEnvelopes("the upload after sign-in");
  await until(async () => (await b.text()).includes("Uploaded"), "the Uploaded status");
  out.s7 = { text: await b.text(), inspect: await b.inspect(), requests: sealedPosts(mark) };
  await clearUploaded();

  // S8. A stale CSRF token (another sign-in replaced the session): refreshed, and the note goes once.
  await b.hash("#/");
  await b.eval(`(async () => {
    const pre = await (await fetch("/api/v1/auth/csrf")).json();
    await fetch("/api/v1/auth/sign-in", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": pre.csrf_token }, body: JSON.stringify({ username: "j.alvarez", password: ${JSON.stringify(pw.j_alvarez)} }) });
  })()`);
  const staleBefore = await serverCount();
  mark = b.requests.length;
  await b.hash("#/new");
  await fill(plan.notes.stale);
  await submit();
  await until(async () => (await serverCount()) === staleBefore + 1, "the note after the token refresh");
  out.s8 = { requests: sealedPosts(mark), before: staleBefore, after: await serverCount(), inspect: await b.inspect() };
  await b.hash("#/");

  // S9. Refused by the real server: each moves to Needs attention with a plain reason.
  await goOffline();
  for (const row of Object.values(plan.rows)) await putRow(row);
  const rejectBefore = b.requests.length;
  await app.start("first-build");
  await nudge("online");
  await until(async () => (await queueRows()).filter((r) => r.status === "attention").length === 3 && (await queueRows()).filter((r) => r.status === "uploaded").length === 1, "the refusals");
  await pillIs("Needs attention");
  await b.hash("#/");
  out.s9 = { text: await b.text(), html: await b.eval("document.getElementById('main').innerHTML"), pill: await b.pill(), inspect: await b.inspect(), requests: sealedPosts(rejectBefore) };

  // A real 409: the same key with a different envelope never makes a second draft.
  const conflictBefore = await serverCount();
  await putRow(plan.conflict_second);
  await b.hash("#/");
  mark = b.requests.length;
  await click("[data-action=upload-all]");
  await until(async () => (await queueRows()).some((r) => r.id === plan.conflict_second.id && r.status === "attention"), "the conflict");
  out.s9_conflict = { before: conflictBefore, after: await serverCount(), requests: sealedPosts(mark), row: (await queueRows()).find((r) => r.id === plan.conflict_second.id) };

  // Try again resends the same envelope under the same key.
  const mismatch = plan.rows.mismatch;
  mark = b.requests.length;
  await press(`[data-action=retry-note][data-ref="${mismatch.id}"]`);
  await until(async () => sealedPosts(mark).length >= 1 && sealedPosts(mark)[0].status, "the retry");
  await until(async () => (await queueRows()).find((r) => r.id === mismatch.id).status === "attention", "the refusal again");
  out.s9_retry = { requests: sealedPosts(mark), row: (await queueRows()).find((r) => r.id === mismatch.id) };

  // Delete, after the warning.
  await b.hash(`#/device/${plan.rows.over_limit.id}/delete`);
  out.s9_warning = await b.text();
  await click("[data-action=discard-note]", "#/");
  out.s9_deleted = { rows: (await queueRows()).map((r) => r.id), inspect: await b.inspect() };

  // S10. While offline the app stays quiet.
  await app.stop();
  await b.reload();
  await pillIs("Offline");
  mark = b.requests.length;
  for (let i = 0; i < 12; i++) { await b.hash(i % 2 ? "#/" : "#/new"); await sleep(100); }
  await sleep(24000);
  out.s10 = { requests: api(mark), inspect: await b.inspect(), stopped: await fetch(`${app.base}/api/v1/ping`).then(() => false, () => true) };

  out.violations = b.violations;
  out.all_requests = b.requests;
} catch (err) {
  out.error = String(err && err.stack || err);
  try { out.error_text = await b.text(); out.error_rows = (await queueRows()).map((r) => ({ id: r.id, status: r.status, reason: r.reason })); } catch { /* the page may be gone */ }
} finally {
  await b.close();
  if (app.proc && app.proc.exitCode === null) await app.stop().catch(() => {});
  b.removeProfile();
}
process.stdout.write(JSON.stringify(out));
