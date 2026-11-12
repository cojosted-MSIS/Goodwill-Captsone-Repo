// A real Chrome window that does Scenario F for `demo.py --auto` (add-web-application, Stage 4e).
// Takes one JSON command per line on stdin and answers one JSON line each. The password comes only
// on stdin and is never printed. Synthetic data only.
import { createInterface } from "node:readline";
import { Browser, until } from "../tests/browser/cdp.mjs";

let b;
let base;
let offline = false;

const nudge = () => b.eval('window.dispatchEvent(new Event("online"))');
const pillIs = (word) => until(async () => (await b.pill()) === word, `the status line to say ${word}`);
const rows = async () => (((await b.inspect()).idb["outreach-device"] || {}).queue || []).map(([, v]) => v);

const commands = {
  async start({ browser, base: url, username, password, headless }) {
    base = url;
    b = await Browser.launch(browser, { headless });
    await b.open();
    await b.goto(`${base}/app/#/sign-in`, "#/sign-in");
    await b.signIn(username, password);
    await b.workerActive();
    await until(async () => ((await b.inspect()).idb["outreach-device"].meta || []).some(([k]) => k === "setup"), "the device setup");
    return {};
  },
  async reload_offline() {
    await b.reload();
    await pillIs("Offline");
    offline = true;
    return {};
  },
  async network({ offline: off }) {
    await b.network(off);
    offline = off;
    if (off) await pillIs("Offline");
    return {};
  },
  async pill() { return { pill: await b.pill() }; },
  async write({ note }) {
    await b.hash("#/new");
    const before = await b.renders();
    await b.eval(`(() => { document.getElementById("note-text").value = ${JSON.stringify(note)}; document.querySelector("form[data-form=new-note]").requestSubmit(); })()`);
    await b.afterRender(before, "#/");
    const text = await b.text();
    if (!text.includes("Saved on device")) throw new Error("the note was not saved on the device");
    return { status: "Saved on device", time: text.match(/Note saved [^\n]+/)[0].trim() };
  },
  async nudge() { await nudge(); return {}; },
  async wait_uploaded() {
    await until(async () => (await rows()).some((r) => r.status === "uploaded") && (await rows()).every((r) => !r.envelope), "the note to upload");
    await until(async () => (await b.text()).includes("Uploaded"), "the Uploaded status");
    return { status: "Uploaded" };
  },
  async confirm({ ref }) {
    await b.hash(`#/drafts/${ref}`);
    await until(() => b.eval('Boolean(document.querySelector("[data-action=confirm]")) && !document.querySelector("[data-action=confirm]").disabled'), "Confirm to be enabled");
    const before = await b.renders();
    await b.eval('document.querySelector("[data-action=confirm]").click()');
    await b.afterRender(before);
    await until(async () => (await b.text()).includes("Entered in HMIS"), "the receipt");
    return {};
  },
  async after_reset() {
    await nudge();
    await until(async () => (await rows()).length === 0, "the device to be cleared");
    return { said: "saved notes, notices, the cached public key and rules, the worker profile, and any unfinished sign-out were cleared. The app's own files stay; they hold nothing personal." };
  },
  async close() {
    await b.close();
    b.removeProfile();
    return {};
  },
};

for await (const line of createInterface({ input: process.stdin })) {
  const command = JSON.parse(line);
  try {
    process.stdout.write(`${JSON.stringify({ ok: true, ...(await commands[command.cmd](command)) })}\n`);
  } catch (err) {
    process.stdout.write(`${JSON.stringify({ error: String(err && err.message || err) })}\n`);
  }
  if (command.cmd === "close") break;
}
process.exit(0);
