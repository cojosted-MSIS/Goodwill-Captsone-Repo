// Stage 4b offline scenarios in real Chrome, for tests/test_offline_browser.py. A plan comes in on
// stdin; observations go out as JSON, and pytest makes the assertions. "Offline" here means the app
// server process is really stopped; one scenario also uses DevTools network emulation.
import { readFileSync } from "node:fs";
import { App, Browser, sleep, until } from "./cdp.mjs";

const plan = JSON.parse(readFileSync(0, "utf8"));
const app = new App(plan);
const b = await Browser.launch(plan.browser);
const out = {};
const NOTE = plan.note;

// The connection check runs on these events, so a test need not wait for its timer.
const nudge = (type) => b.eval(`window.dispatchEvent(new Event(${JSON.stringify(type)}))`);
const pillIs = (word) => until(async () => (await b.pill()) === word, `the status line to say ${word}`);

try {
  await app.start("first-build");
  await b.open();
  await b.goto(`${app.base}/app/#/sign-in`, "#/sign-in");
  await b.signIn("j.alvarez", plan.password);
  await b.workerActive();
  out.signed_in = await b.inspect();
  out.installability = await b.page("Page.getInstallabilityErrors");
  out.manifest = await b.page("Page.getAppManifest");

  // Use the API while online, then check that none of it was cached.
  await b.hash("#/queries/briefing");
  await b.hash("#/");
  out.online_requests = b.requests.filter((r) => r.url.includes("/api/"));
  out.online_inspect = await b.inspect();

  // Really offline: the server is stopped and the page is reloaded.
  await app.stop();
  const mark = b.requests.length;
  await b.reload();
  out.offline_home = { text: await b.text(), pill: await b.pill(), nav_hidden: await b.eval('document.getElementById("bottom-nav").hidden') };
  await b.hash("#/new");
  out.offline_new = await b.text();
  await b.hash("#/queries");
  out.offline_queries = await b.text();
  await b.hash("#/drafts/ENC-2026-01-01-0001");
  out.offline_draft = await b.text();
  out.offline_inspect = await b.inspect();
  out.offline_requests = b.requests.slice(mark);
  out.controlled_offline = await b.eval("Boolean(navigator.serviceWorker.controller)");

  // Back online: the status line and the real screens return.
  await app.start("first-build");
  await b.hash("#/");
  await nudge("online");
  await pillIs("Online");
  await until(async () => (await b.text()).includes("Recent"), "the real home screen");
  out.back_online = { text: await b.text(), pill: await b.pill() };

  // A draft is on screen when the connection goes: Confirm is disabled, and returns afterward.
  await b.hash("#/new");
  let before = await b.renders();
  await b.eval(`(() => { document.getElementById("note-title").value = "Kim, NW quadrant";
    document.getElementById("note-text").value = ${JSON.stringify(NOTE)};
    document.querySelector("form[data-form=new-note]").requestSubmit(); })()`);
  await b.afterRender(before);
  await until(() => b.eval('Boolean(document.querySelector("[data-action=confirm]"))'), "the review screen");
  const confirmDisabled = 'document.querySelector("[data-action=confirm]").disabled';
  out.confirm_online = await b.eval(confirmDisabled);
  await app.stop();
  await nudge("offline");
  await pillIs("Offline");
  out.confirm_offline = await b.eval(confirmDisabled);
  out.review_offline_text = await b.text();
  const clicks = b.requests.length;
  await b.eval('document.querySelector("[data-action=confirm]").click()');
  await sleep(300);
  out.requests_after_clicking_disabled_confirm = b.requests.slice(clicks).filter((r) => r.method === "POST");
  await b.reload();
  out.review_after_offline_reload = await b.text();
  out.review_offline_inspect = await b.inspect();
  await app.start("first-build");
  await nudge("online");
  await pillIs("Online");
  await until(() => b.eval('Boolean(document.querySelector("[data-action=confirm]"))'), "the review screen to return");
  out.confirm_back_online = await b.eval(confirmDisabled);

  // Network emulation, on the page and on the service worker's own target.
  await b.network(true);
  await pillIs("Offline");
  out.emulated = { pill: await b.pill(), text: await b.text() };
  await b.network(false);
  await pillIs("Online");
  out.emulated_back = await b.pill();

  // A new version must not disturb a note being typed.
  await b.hash("#/new");
  const typed = "A note being typed while a new version arrives.";
  await b.eval(`document.getElementById("note-text").value = ${JSON.stringify(typed)}`);
  const cachesBefore = Object.keys((await b.inspect()).cache);
  const rendersBefore = await b.renders();
  await app.stop();
  await app.start("second-build");
  await b.eval("navigator.serviceWorker.getRegistration().then((r) => r.update())");
  await until(() => b.eval("navigator.serviceWorker.getRegistration().then((r) => Boolean(r.waiting))"), "the new version to wait");
  await sleep(500);
  out.update_while_typing = {
    text: await b.eval('document.getElementById("note-text").value'), renders_same: (await b.renders()) === rendersBefore,
    waiting: await b.eval("navigator.serviceWorker.getRegistration().then((r) => Boolean(r.waiting))"), caches_before: cachesBefore,
  };
  // Nothing is being typed any more: the new version takes over at the next screen.
  await b.eval('document.getElementById("note-text").value = ""');
  await b.eval('location.hash = "#/"');
  await until(async () => {
    const c = Object.keys((await b.inspect()).cache);
    return c.length === 1 && !cachesBefore.includes(c[0]);
  }, "the new version to take over");
  await until(() => b.eval('document.documentElement.dataset.ready === "1"'), "the page after the update");
  out.after_update = { caches: Object.keys((await b.inspect()).cache), text: await b.text() };

  // Sign out: the device profile is gone.
  await until(() => b.eval('!document.getElementById("sign-out").hidden'), "the sign-out button");
  before = await b.renders();
  await b.eval('document.getElementById("sign-out").click()');
  await b.afterRender(before, "#/sign-in");
  out.after_sign_out = await b.inspect();

  out.violations = b.violations;
  out.all_requests = b.requests;
} catch (err) {
  out.error = String(err && err.stack || err);
} finally {
  await b.close();
  if (app.proc && app.proc.exitCode === null) await app.stop().catch(() => {});
  b.removeProfile();
}
process.stdout.write(JSON.stringify(out));
