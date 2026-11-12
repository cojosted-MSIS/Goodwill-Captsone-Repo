// Render web screens for tests/test_web_screens.py: node render_screens.mjs <screens.js> <input.json>
// The input maps a name to {fn, args}; the output maps the same name to the screen's HTML.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [, , screensPath, inputPath] = process.argv;
const screens = await import(pathToFileURL(screensPath).href);
const input = JSON.parse(readFileSync(inputPath, "utf8"));
const out = {};
for (const [name, { fn, args }] of Object.entries(input)) out[name] = screens[fn](...args);
process.stdout.write(JSON.stringify(out));
