// Screenshots of the offline queue's states (add-web-application, Stage 4d), driven by
// scripts/take_screenshots.py. Reads a plan as JSON on stdin: {browser, base, out, username, password,
// widths: {phone, desktop}}. Drives the real app and server. The network is switched off in the
// browser. Two things are STAGED, because a real server cannot wait or be fooled on request: a note's
// saved time is moved back for the 60-hour and 72-hour states, and for Needs attention one note's
// saved time is changed and the SSN rules are relaxed on the device, so the real server refuses
// them. Synthetic data only. The password comes only from stdin and is never printed.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Browser, sleep, until } from "../tests/browser/cdp.mjs";

const plan = JSON.parse(readFileSync(0, "utf8"));
const b = await Browser.launch(plan.browser);
const SEALED = "*/api/v1/notes/sealed";
const NOTE = "Met Kim Placeholder, DOB 1/2/1990, NW quadrant around 10:15am. Searched HMIS first, no match. Slept outside last night. Has been staying outside for over a year. "
  + "Been on the street about 3 times in the last 3 years, around 14 months total. Started being homeless this time on 8/15/2025. Male, white, not Hispanic. Has a disabling condition (bad back). "
  + "Not a veteran. SSN ends 4821. Enroll in street outreach, CE region 7. Single adult. Gave water and a hygiene kit. Follow up Thursday.";

const pillIs = (word) => until(async () => (await b.pill()) === word, `the status line to say ${word}`);
const nudge = () => b.eval('window.dispatchEvent(new Event("online"))');
const rows = async () => (((await b.inspect()).idb["outreach-device"] || {}).queue || []).map(([, v]) => v);
const withDb = (body) => b.eval(`(async () => {
  const db = await new Promise((res, rej) => { const r = indexedDB.open("outreach-device"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
  const done = (tx) => new Promise((res, rej) => { tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  const get = (store, key) => new Promise((res) => { const r = db.transaction(store).objectStore(store).get(key); r.onsuccess = () => res(r.result); });
  ${body}
  db.close();
})()`);
const setSaved = (id, iso) => withDb(`const row = await get("queue", ${JSON.stringify(id)}); row.saved_at = ${JSON.stringify(iso)};
  const tx = db.transaction("queue", "readwrite"); tx.objectStore("queue").put(row); await done(tx);`);
const clearQueue = () => withDb('const tx = db.transaction("queue", "readwrite"); tx.objectStore("queue").clear(); await done(tx);');
const hoursAgo = (h) => new Date(Date.now() - h * 3600 * 1000).toISOString();

async function write(text = NOTE) {
  await b.hash("#/new");
  const before = await b.renders();
  await b.eval(`(() => { document.getElementById("note-text").value = ${JSON.stringify(text)}; document.querySelector("form[data-form=new-note]").requestSubmit(); })()`);
  await b.afterRender(before, "#/");
}
async function newestId(known) {
  const found = (await rows()).find((r) => !known.has(r.id));
  known.add(found.id);
  return found.id;
}
async function offline() {
  await b.network(true);
  await pillIs("Offline");
}
async function online() {
  await b.network(false);
  await nudge();
  await pillIs("Online").catch(() => {});
}
async function shoot(name) {
  for (const [w, label] of [[plan.widths.phone, "phone"], [plan.widths.desktop, "desktop"]]) {
    const metrics = { width: w, height: 800, deviceScaleFactor: 1, mobile: w < 700 };
    await b.page("Emulation.setDeviceMetricsOverride", metrics);
    await sleep(150);
    const height = await b.eval("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)");
    await b.page("Emulation.setDeviceMetricsOverride", { ...metrics, height: Math.min(height, 16000) });
    await sleep(100);
    const { data } = await b.page("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    const file = join(plan.out, `${name}_${label}.png`);
    writeFileSync(file, Buffer.from(data, "base64"));
    process.stdout.write(`  web/${name}_${label}.png\n`);
  }
}

try {
  await b.open();
  await b.page("Emulation.setDeviceMetricsOverride", { width: plan.widths.phone, height: 800, deviceScaleFactor: 1, mobile: true });
  await b.goto(`${plan.base}/app/#/sign-in`, "#/sign-in");
  await b.signIn(plan.username, plan.password);
  await b.workerActive();
  await until(async () => ((await b.inspect()).idb["outreach-device"].meta || []).some(([k]) => k === "setup"), "the device setup");

  // Saved on device, then Uploading, then Uploaded: one real note.
  await offline();
  await write();
  await shoot("40_device_saved");
  const held = [];
  await b.intercept(SEALED, "Request", (p) => held.push(p));
  await b.network(false);
  await nudge();
  await until(async () => held.length && (await b.text()).includes("Uploading"), "the Uploading status");
  await shoot("41_device_uploading");
  b.onPaused = (p) => b.proceed(p);
  for (const p of held) await b.proceed(p);
  await until(async () => (await b.text()).includes("In review"), "the draft on My notes");
  await b.stopIntercept();
  await pillIs("Online");
  await shoot("42_device_uploaded");
  await clearQueue();

  // Needs attention: refused by the real server (staged, see above).
  await offline();
  await b.reload();
  const known = new Set();
  await write(NOTE.replace("Kim", "Kit"));
  const moved = await newestId(known);
  await setSaved(moved, new Date(Date.now() - 1000).toISOString());
  await withDb(`const setup = await get("meta", "setup"); setup.rules.any_full_number = "(?!)"; setup.rules.possible_full_number = "(?!)";
    const tx = db.transaction("meta", "readwrite"); tx.objectStore("meta").put(setup, "setup"); await done(tx);`);
  await b.reload();
  await write("Met Lee Sample near the library. Her social is 234 56 7891. Gave water.");
  await b.network(false);
  await nudge();
  await until(async () => (await rows()).filter((r) => r.status === "attention").length === 2, "the refusals");
  await pillIs("Needs attention");
  await b.hash("#/");
  await shoot("43_device_needs_attention");
  await b.hash(`#/device/${moved}/delete`);
  await shoot("44_device_delete_warning");
  await clearQueue();

  // The 60-hour warning, then the 72-hour notice (saved time moved back).
  await b.hash("#/");
  await offline();
  await b.reload();
  const later = new Set();
  await write();
  const aging = await newestId(later);
  await setSaved(aging, hoursAgo(61));
  await b.hash("#/");
  await shoot("45_device_warning_60_hours");
  await setSaved(aging, hoursAgo(73));
  await b.reload();
  await until(async () => (await b.text()).includes("expired before"), "the 72-hour notice");
  await shoot("46_device_expired_notice");
  await clearQueue();

  // Sign in to upload: the session is gone when the connection returns.
  await write();
  await write(NOTE.replace("Kim", "Kip"));
  await b.page("Network.deleteCookies", { name: "hmis_session", url: `${plan.base}/` });
  await b.network(false);
  await nudge();
  await until(async () => (await b.text()).includes("Sign in to upload your 2 saved notes"), "the sign-in prompt");
  await shoot("47_sign_in_to_upload");
} finally {
  await b.close();
  b.removeProfile();
}
