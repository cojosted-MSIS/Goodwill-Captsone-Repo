// Screenshots of the web app (add-web-application, Stage 3b), driven by scripts/take_screenshots.py.
//
// Reads a plan as JSON on stdin: {browser, base, out, username, password, widths: {phone, desktop},
// steps: [{name, hash} | {name, hash, fill: {selector: value}, check: [selector], submit: selector} |
// {name, hash, offline: true}]}. Offline steps switch the browser's network off for that screenshot. Starts headless
// Chrome or Edge with the DevTools protocol (Node's built-in WebSocket, no packages), signs in
// through the real sign-in form, and writes one full-page PNG per step and width. The password
// comes only from stdin and is never printed. Synthetic data only.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const plan = JSON.parse(readFileSync(0, "utf8"));
const profile = mkdtempSync(join(tmpdir(), "web-shots-"));
const chrome = spawn(plan.browser, ["--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function devtoolsUrl() {
  const file = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 200; i++) {
    if (existsSync(file)) {
      const [port, path] = readFileSync(file, "utf8").split("\n");
      if (port && path) return `ws://127.0.0.1:${port.trim()}${path.trim()}`;
    }
    await sleep(100);
  }
  throw new Error("the browser did not start its DevTools endpoint");
}

const ws = new WebSocket(await devtoolsUrl());
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let nextId = 0;
const pending = new Map();
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
  }
};
function send(method, params = {}, sessionId) {
  const id = ++nextId;
  ws.send(JSON.stringify({ id, method, params, sessionId }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const page = (method, params) => send(method, params, sessionId);
await page("Page.enable");
await page("Runtime.enable");

async function evaluate(expression) {
  const r = await page("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || "script error in the page");
  return r.result.value;
}
const renders = () => evaluate("Number(document.documentElement.dataset.renders || 0)");
async function waitForRender(before, hash) {
  for (let i = 0; i < 200; i++) {
    // The page may still be starting, with no document element yet: try again shortly.
    const seen = await evaluate("[Number(document.documentElement.dataset.renders || 0), document.documentElement.dataset.ready, location.hash]").catch(() => null);
    if (!seen) { await sleep(50); continue; }
    const [count, ready, at] = seen;
    if (count > before && ready === "1" && (!hash || at === hash)) return;
    await sleep(50);
  }
  throw new Error(`the screen ${hash || ""} did not finish rendering`);
}

async function width(w) {
  await page("Emulation.setDeviceMetricsOverride", { width: w, height: 800, deviceScaleFactor: 1, mobile: w < 700 });
}
async function shoot(name, w) {
  await width(w);
  await sleep(150);
  const height = await evaluate("Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)");
  await page("Emulation.setDeviceMetricsOverride", { width: w, height: Math.min(height, 16000), deviceScaleFactor: 1, mobile: w < 700 });
  await sleep(100);
  const { data } = await page("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  const file = join(plan.out, `${name}_${w < 700 ? "phone" : "desktop"}.png`);
  writeFileSync(file, Buffer.from(data, "base64"));
  process.stdout.write(`  ${file.split(/[\\/]/).slice(-2).join("/")}\n`);
}
async function go(hash) {
  const before = await renders();
  // The same hash fires no hashchange, so render the screen again by firing it.
  await evaluate(`location.hash === ${JSON.stringify(hash)} ? window.dispatchEvent(new HashChangeEvent("hashchange")) : (location.hash = ${JSON.stringify(hash)})`);
  await waitForRender(before, hash);
}

try {
  await width(plan.widths.phone);
  await page("Page.navigate", { url: `${plan.base}/app/#/sign-in` });
  await waitForRender(0, "#/sign-in");
  if (plan.signInShot !== false) for (const w of [plan.widths.phone, plan.widths.desktop]) await shoot("01_sign_in", w);
  // Sign in through the real form: the password is typed into the page, never printed.
  let before = await renders();
  await evaluate(`(() => { document.getElementById("username").value = ${JSON.stringify(plan.username)};
    document.getElementById("password").value = ${JSON.stringify(plan.password)};
    document.querySelector("form[data-form=sign-in]").requestSubmit(); })()`);
  await waitForRender(before, "#/");
  for (const step of plan.steps) {
    await go(step.hash);
    if (step.offline) {
      await page("Network.enable");
      before = await renders();
      await page("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
      await waitForRender(before);
    }
    if (step.fill || step.check) {
      before = await renders();
      const assignments = Object.entries(step.fill || {}).map(([sel, value]) => `document.querySelector(${JSON.stringify(sel)}).value = ${JSON.stringify(value)};`)
        .concat((step.check || []).map((sel) => `document.querySelector(${JSON.stringify(sel)}).checked = true;`)).join("");
      await evaluate(`(() => { ${assignments} document.querySelector(${JSON.stringify(step.submit)}).requestSubmit(); })()`);
      await waitForRender(before);
    }
    for (const w of [plan.widths.phone, plan.widths.desktop]) await shoot(step.name, w);
    if (step.offline) {
      before = await renders();
      await page("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
      await waitForRender(before);
    }
  }
} finally {
  ws.close();
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* the browser may still hold a file */ }
}
