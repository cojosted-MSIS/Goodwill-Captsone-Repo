// Keep full Social Security numbers out of the device (add-web-application, Stage 4c).
//
// The same rules as the server (app/ssn_guard.py), from the patterns the server sends at sign-in,
// run in memory before anything is sealed or sent. A shared table of cases proves the two agree
// (tests/ssn_cases.json). The patterns are written for Python, where \d, \b, and \w cover every
// alphabet; toUnicode gives them the same meaning in JavaScript. Numbers in words are not detected
// [TBC with Goodwill and CHIP].

const WORD = "\\p{L}\\p{N}_";
const SPACE = "\\s\\x1c-\\x1f\\x85";
const BOUNDARY = `(?:(?<![${WORD}])(?=[${WORD}])|(?<=[${WORD}])(?![${WORD}]))`;

function toUnicode(pattern) {
  let out = "";
  let inClass = false;
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === "\\") {
      const next = pattern[++i];
      if (next === "d") out += "\\p{Nd}";
      else if (next === "D") out += "\\P{Nd}";
      else if (next === "w") out += inClass ? WORD : `[${WORD}]`;
      else if (next === "s") out += inClass ? SPACE : `[${SPACE}]`;
      else if (next === "b" && !inClass) out += BOUNDARY;
      else out += `\\${next}`;
      continue;
    }
    if (c === "[") inClass = true;
    if (c === "]") inClass = false;
    out += c;
  }
  return out;
}

export function compileRules(rules) {
  return {
    full: new RegExp(toUnicode(rules.any_full_number), "gu"),
    possible: new RegExp(toUnicode(rules.possible_full_number), "iu"),
    invalid: rules.invalid_full_number_patterns.map((r) => ({ re: new RegExp(toUnicode(r.pattern), "u"), label: r.label })),
  };
}

const lastFour = (number) => number.replace(/\P{Nd}/gu, "").slice(-4);

export function guard(text, compiled) {
  const found = text.match(compiled.full) || [];
  let invalidLabel = null;
  for (const number of found) {
    const rule = compiled.invalid.find((r) => r.re.test(number));
    if (rule) { invalidLabel = rule.label; break; }
  }
  const masked = text.replace(compiled.full, (number) => `***-**-${[...lastFour(number)].slice(-4).join("")}`);
  return { text: masked, masked: found.length, invalidLabel, refused: compiled.possible.test(masked) };
}
