// Runs ui/web/ssn.js on the shared SSN cases, for tests/test_device_ssn.py.
// A plan comes in on stdin: {module, rules, texts}. The results go out as JSON.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const plan = JSON.parse(readFileSync(0, "utf8"));
const { compileRules, guard } = await import(pathToFileURL(plan.module).href);
const compiled = compileRules(plan.rules);
process.stdout.write(JSON.stringify(plan.texts.map((text) => guard(text, compiled))));
