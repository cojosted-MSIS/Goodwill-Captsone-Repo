// Worker screens for the web application (add-web-application, Stage 3b).
//
// Each screen is a pure function: data from /api/v1 in, an HTML string out. Every value is
// escaped with esc(). app.js fetches the data, puts the HTML in <main>, and handles the
// buttons (data-action) and forms (data-form). The same functions run in Node for the tests
// (tests/test_web_screens.py), so no screen depends on the browser.
//
// Plain language for a worker on a phone outdoors: one task per screen, buttons that say what
// they do, a label on every field, and errors that say what to do next.

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// Icons: small inline SVG, always next to a word, hidden from screen readers.
const ICONS = {
  check: '<path d="M3 8.5l3.2 3.2L13 4.8"/>',
  alert: '<path d="M8 2 1.5 13.5h13L8 2z"/><path d="M8 6.5v3.2M8 11.8v.01"/>',
  cross: '<circle cx="8" cy="8" r="6.2"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>',
  pencil: '<path d="M10.5 2.5l3 3-8 8-3.5.5.5-3.5z"/>',
  clock: '<circle cx="8" cy="8" r="6.2"/><path d="M8 4.5V8l2.5 1.5"/>',
  flag: '<path d="M3.5 14.5v-13h8.5l-1.7 3 1.7 3H3.5"/>',
  info: '<circle cx="8" cy="8" r="6.2"/><path d="M8 7.5v3.5M8 5v.01"/>',
  upload: '<path d="M8 11V3M4.5 6.5 8 3l3.5 3.5M3 13.5h10"/>',
  device: '<rect x="4.5" y="1.5" width="7" height="13" rx="1.5"/><path d="M7.5 12.5h1"/>',
  wifiOff: '<path d="M1.5 1.5l13 13M3 7a8 8 0 0 1 3-1.8M13 7a8 8 0 0 0-4.5-2.2M5.2 9.5a4.5 4.5 0 0 1 2.3-1.1M8 12.5v.01"/>',
};

export function icon(name) {
  return `<svg class="icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`;
}

// A status: a color, an icon, and always a word.
function chip(color, iconName, word) {
  return `<span class="chip ${color}">${icon(iconName)}${esc(word)}</span>`;
}

const STATE_CHIPS = { submitted: ["green", "check"], in_review: ["blue", "clock"], confirmed: ["blue", "upload"],
  failed: ["red", "cross"], draft: ["red", "cross"], expired: ["amber", "clock"] };

function stateChip(state, label) {
  const [color, iconName] = STATE_CHIPS[state] || ["grey", "info"];
  return chip(color, iconName, label);
}

// The sync pill's color and contents (Stage 4 adds the device queue's states).
export function syncPill(online) {
  return { className: `chip ${online ? "green" : "grey"} sync`, html: `${icon(online ? "check" : "wifiOff")}${online ? "Online" : "Offline"}` };
}

function page(title, body, { back = "#/", backLabel = "Back to my notes" } = {}) {
  const nav = back ? `<p class="back"><a href="${esc(back)}">${esc(backLabel)}</a></p>` : "";
  return `${nav}<h1 tabindex="-1">${esc(title)}</h1>${body}`;
}

export function flash(f) {
  if (!f) return "";
  const lines = (f.messages || []).map((m) => `<div class="message"><h2>${esc(m.subject)}</h2><p class="text">${esc(m.body)}</p></div>`);
  return `<div class="banner ${f.kind === "error" ? "error" : "info"}" role="${f.kind === "error" ? "alert" : "status"}">`
    + `${f.text ? `<p>${esc(f.text)}</p>` : ""}${lines.join("")}</div>`;
}

const SSN_WARNING = `<div class="banner warn" id="ssn-warning"><p><strong>Do not write a full Social Security number.</strong> `
  + `Write only the last four digits, for example "SSN ends 6789". A full number is hidden before anything is saved.</p></div>`;

// Sign in

export function signIn({ error } = {}) {
  return page("Sign in", `
    ${error ? `<div class="banner error" role="alert"><p>${esc(error)}</p></div>` : ""}
    <form data-form="sign-in" class="stack" novalidate>
      <label for="username">Username</label>
      <input id="username" name="username" autocomplete="username" autocapitalize="none" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit" class="btn primary">Sign in</button>
    </form>
    <p class="small">Demo accounts only, with synthetic data.</p>`, { back: null });
}

// Home: my notes

export function home({ user, drafts = [], held = [], messages = [] }) {
  const waiting = drafts.filter((d) => d.state === "in_review" || d.state === "failed");
  const count = held.length + waiting.length;
  const needs = count ? `<section class="card needs-you" aria-labelledby="needs-heading">
      <h2 id="needs-heading">${icon("alert")}${esc(plural(count, "note"))} ${count === 1 ? "needs" : "need"} you</h2>
      ${held.length ? `<ul>${held.map((h) => `<li><a href="#/held/${esc(h.id)}">${esc(h.title)}: ${h.kind === "pick_client" ? "pick the client" : "did you search HMIS?"}</a></li>`).join("")}</ul>` : ""}
      ${waiting.length ? `<p><a href="#/drafts/${esc(waiting[0].id)}">${esc(plural(waiting.length, "draft"))} to check or try again: open the newest</a></p>` : ""}
    </section>` : "";
  const draftList = drafts.length ? `<ul class="cards">${drafts.map((d) => `
      <li><a class="card" href="#/drafts/${esc(d.id)}"><span class="card-title">${esc(d.title)}</span>
      <span class="card-meta">${esc(d.kind === "update" ? "Visit for a client in HMIS" : "New client")}, version ${esc(d.version)}</span>
      ${stateChip(d.state, d.status_label)}</a></li>`).join("")}</ul>`
    : `<p>You have no drafts yet. Write a note to start.</p>`;
  // Recent messages as short links: the whole message is on the draft's own screen.
  const recent = messages.filter((m) => m.ref).slice(0, 3);
  const messageList = recent.length ? `<h2>Recent messages</h2><ul class="cards">${recent.map((m) => `
      <li><a class="card" href="#/${m.ref.startsWith("ENC-") ? "drafts" : "held"}/${esc(m.ref)}"><span class="card-title">${esc(m.subject)}</span>
      <span class="card-meta">${esc(m.ref)}</span></a></li>`).join("")}</ul>` : "";
  return page(`Hello, ${user ? user.display_name : ""}`, `
    <div class="actions">
      <a class="btn primary big" href="#/new">Write a note about someone new</a>
      <a class="btn big" href="#/update">Add a visit for a client already in HMIS</a>
    </div>
    ${needs}
    <h2>Recent</h2>${draftList}
    ${messageList}`, { back: null });
}

// Writing a note

export function noteForm({ kind = "new", error = null, text = "", title = "" } = {}) {
  const update = kind === "update";
  const help = update
    ? "Write what happened on this visit. Give the client's HMIS client ID, or their first and last name with the full date of birth."
    : "Write what you learned about the neighbor, in your own words. Say that you searched HMIS first and found no match.";
  return page(update ? "Add a visit for a client already in HMIS" : "Write a note about someone new", `
    ${SSN_WARNING}
    ${error ? `<div class="banner error" role="alert"><p>${esc(error)}</p></div>` : ""}
    <form data-form="${update ? "update-note" : "new-note"}" class="stack" novalidate>
      <label for="note-title">Short title (optional)</label>
      <input id="note-title" name="title" maxlength="200" value="${esc(title)}" aria-describedby="title-help">
      <p class="small" id="title-help">Only you see it, for example "Kim, NW quadrant".</p>
      <label for="note-text">Your note</label>
      <p class="small" id="note-help">${esc(help)}</p>
      <textarea id="note-text" name="text" rows="10" required aria-describedby="note-help ssn-warning">${esc(text)}</textarea>
      <button type="submit" class="btn primary">Draft my note</button>
    </form>
    <p class="small">Nothing is sent to HMIS until you check the draft and press Confirm.</p>`);
}

// Held notes: the HMIS search, or which client

export function heldSearch(held) {
  return page("Did you search HMIS first?", `
    <p>Before I draft a new client from "${esc(held.title)}", please confirm that you searched HMIS and found no existing record.</p>
    <p>Nothing has been drafted or sent to HMIS.</p>
    <div class="actions"><button type="button" class="btn primary" data-action="searched" data-ref="${esc(held.id)}">I searched HMIS, no match</button></div>
    <p class="small">If you have not searched yet, search HMIS first, then come back to this note.</p>`);
}

export function pickClient(held) {
  const cards = held.candidates.map((c) => `
    <li class="candidate">
      <p><strong>${esc(c.label)}</strong> <span class="mono">${esc(c.client_id)}</span></p>
      <p class="small">${c.last_contact ? `Last contact ${esc(usDate(c.last_contact))}` : "No contact recorded"}${c.quadrant ? `, ${esc(c.quadrant.toUpperCase())} quadrant` : ""}</p>
      <button type="button" class="btn" data-action="pick" data-ref="${esc(held.id)}" data-client="${esc(c.client_id)}">This visit is for ${esc(c.label)} (${esc(c.client_id)})</button>
    </li>`).join("");
  return page("Which client is this visit for?", `
    <p>I found ${esc(plural(held.candidates.length, "client"))} with that name and date of birth. Pick the one this visit is for.</p>
    <ul class="cards">${cards}</ul>
    <p class="small">Nothing has been drafted or sent to HMIS. If none of them is right, check the name and date of birth in HMIS.</p>`);
}

// A draft: review, verification, receipt, failure, or another state

export function draft(view, options = {}) {
  if (view.state === "in_review" && view.verification) return verification(view, options);
  if (view.state === "in_review") return review(view);
  if (view.state === "submitted") return receipt(view);
  if (view.state === "failed") return failure(view);
  return draftStatus(view);
}

const LABELS = {
  high: ["check", "Stated in your note"],
  medium: ["alert", "Check this: your note was not sure"],
  worker: ["pencil", "From your correction"],
  review: ["alert", "Written by the system: check the wording"],
};

function label(cls, text) {
  const [iconName, word] = LABELS[cls] || ["info", text];
  return `<span class="certainty ${cls}">${icon(iconName)}${esc(text || word)}</span>`;
}

function certainty(f) {
  if (f.origin === "worker") return "worker";
  if (f.origin === "generated") return "review";
  if (f.origin === "email" && f.confidence === "medium") return "medium";
  if (f.origin === "email") return "high";
  return "system";
}

function fieldRow(f) {
  if (f.missing) {
    return `<div class="answer missing"><dt class="eyebrow">${esc(f.label)}</dt><dd>${chip("red", "cross", "Not stated")}`
      + `${f.flags.map((m) => `<p class="flag">${esc(m)}</p>`).join("")}</dd></div>`;
  }
  const cls = certainty(f);
  const check = cls === "medium" || f.flags.length;
  return `<div class="answer${check ? " check" : ""}"><dt class="eyebrow">${esc(f.label)}</dt><dd>
    <span class="value">${esc(f.value)}</span>
    ${cls === "system" ? label("system", f.origin_label || "Set by the system") : label(cls)}
    ${f.source ? `<span class="source">You wrote: <q>${esc(f.source)}</q></span>` : ""}
    ${f.flags.map((m) => `<p class="flag">${esc(m)}</p>`).join("")}</dd></div>`;
}

function confirmBlock(view, { blockedReason, bar = false, after = "" } = {}) {
  const summary = (view.entry_summary || []).map((s) => `<li><strong>${esc(s.what)}</strong>${s.detail ? `: ${esc(s.detail)}` : ""}</li>`).join("");
  const allowed = Boolean(view.confirm_allowed);
  const reason = allowed ? "" : (blockedReason || (view.review && view.review.confirm_blocked_reason) || "This draft cannot be entered yet.");
  return `<section class="confirm${bar ? " bar" : ""}" aria-labelledby="confirm-heading">
    <h2 id="confirm-heading">What Confirm will enter in HMIS</h2>
    <ul class="summary">${summary}</ul>
    ${allowed ? "" : `<p class="blocked" id="confirm-blocked">${esc(reason)}</p>`}
    <button type="button" class="btn primary" data-action="confirm" data-ref="${esc(view.id)}" data-version="${esc(view.version)}"
      ${allowed ? "" : 'disabled aria-describedby="confirm-blocked"'}>Confirm and enter in HMIS</button>
    ${after}
  </section>`;
}

export function review(view) {
  const r = view.review;
  const sections = r.sections.map((s) => `
    <h2>${esc(s.label)}</h2>${s.hint ? `<p class="small hint">${esc(s.hint)}</p>` : ""}
    ${s.fields.length ? `<dl class="answers">${s.fields.map(fieldRow).join("")}</dl>` : ""}
    ${s.collapsed.length ? `<details><summary>${esc(plural(s.collapsed.length, "more field"))} not needed for this neighbor</summary>`
      + `<ul>${s.collapsed.map((f) => `<li>${esc(f.label)}: blank</li>`).join("")}</ul></details>` : ""}`).join("");
  const checks = r.flags.filter((f) => !f.blocking);
  return page(`Check your draft: ${view.title}`, `
    <p class="small">Draft ${esc(view.id)}, version ${esc(view.version)}. Nothing has been sent to HMIS.</p>
    ${r.intro.length ? `<div class="banner info">${r.intro.map((l) => `<p>${esc(l)}</p>`).join("")}</div>` : ""}
    ${r.scripted_label ? `<div class="banner warn"><p>${esc(r.scripted_label)}</p></div>` : ""}
    ${r.missing.length ? `<div class="banner error" role="alert"><p>Still needed before entry: ${esc(r.missing.join(", "))}. Add them with Make a correction.</p></div>` : ""}
    ${checks.length ? `<div class="banner warn"><p>Please check:</p><ul>${checks.map((f) => `<li>${esc(f.message)}</li>`).join("")}</ul></div>` : ""}
    <p class="small">Each answer shows where it came from:</p>
    <p class="legend">${label("high")} ${label("medium")} ${label("worker")} ${label("review")}</p>
    ${sections}
    <h2>Case note</h2>
    <p>${label("review")}</p>
    <p class="text case-note">${esc(r.case_note || "(none)")}</p>
    ${r.update_in_hmis_yourself.length ? `<h2>Update in HMIS yourself</h2><p class="small">From your note. This system never writes these.</p>`
      + `<ul>${r.update_in_hmis_yourself.map((u) => `<li>${esc(u.label)}: ${esc(u.value)}</li>`).join("")}</ul>` : ""}
    ${r.notices.length ? `<div class="banner info"><ul>${r.notices.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
    ${r.same_name_check ? `<p class="small">Same name and date of birth check: ${esc(r.same_name_check)}</p>` : ""}
    ${r.remaining_in_hmis.length ? `<details><summary>Still to complete in HMIS after entry</summary><ul>${r.remaining_in_hmis.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></details>` : ""}
    <p class="small">${esc(r.consent)}</p>
    <p class="small">${esc(r.footer)}</p>
    ${confirmBlock(view, { bar: true, after: `<a class="btn" href="#/drafts/${esc(view.id)}/correct">Make a correction</a>` })}`);
}

const GRADE_CHIPS = {
  likely_same: ["green", "check", "Last four SSN digits match"],
  warning: ["amber", "alert", "Last four SSN digits differ"],
  hard_stop: ["red", "cross", "Last four SSN digits missing"],
};

function reasonFields(view, reason) {
  const min = view.verification ? view.verification.min_reason_length : 1;
  const strict = min > 1;
  return `<label for="reason">Your reason</label>
      <p class="small" id="reason-help">${strict
        ? `The last four SSN digits match, so please give a full reason: at least ${esc(min)} characters. Your supervisor reviews this decision afterward.`
        : "For example: she is 20 years younger than the person in HMIS."}</p>
      <textarea id="reason" name="reason" rows="2" ${strict ? `minlength="${esc(min)}"` : ""} required aria-describedby="reason-help reason-count">${esc(reason)}</textarea>
      <p class="small" id="reason-count" aria-live="polite" data-min="${esc(min)}">${esc(reason.length)} of at least ${esc(min)} characters</p>`;
}

export function verification(view, { error = null, reason = "" } = {}) {
  const v = view.verification;
  const cards = v.candidates.map((c) => {
    const [color, iconName, word] = GRADE_CHIPS[c.grade];
    return `
    <li class="candidate${c.client_id === v.recommend ? " recommended" : ""}">
      <p><strong>${esc(c.label)}</strong> <span class="mono">${esc(c.client_id)}</span></p>
      <p>${c.last_contact_date ? `Last contact ${esc(usDate(c.last_contact_date))}` : "No contact recorded"}${c.quadrant ? `, ${esc(c.quadrant.toUpperCase())} quadrant` : ""}</p>
      ${c.open_items.length ? `<p class="small">Open: ${esc(c.open_items.join("; "))}</p>` : ""}
      <p>${chip(color, iconName, word)}${c.client_id === v.recommend ? ` ${chip("green", "check", "Recommended")}` : ""}</p>
      <button type="button" class="btn${c.client_id === v.recommend ? " primary" : ""}" data-action="same-client" data-ref="${esc(view.id)}" data-client="${esc(c.client_id)}">Same person as ${esc(c.client_id)}: add this as a visit</button>
    </li>`;
  }).join("");
  const hardStop = v.candidates.find((c) => c.grade === "hard_stop");
  return page("Same name and date of birth in HMIS", `
    <p>HMIS already has ${esc(plural(v.candidates.length, "client"))} with this name and date of birth. Decide before anything is entered.</p>
    ${error ? `<div class="banner error" role="alert"><p>${esc(error)}</p></div>` : ""}
    ${v.duplicates_notice ? `<div class="banner warn"><p>${esc(v.duplicates_notice)}</p></div>` : ""}
    ${hardStop ? `<div class="banner warn"><p>${esc(hardStop.grade_text)}</p></div>` : ""}
    <ul class="cards">${cards}</ul>
    ${confirmBlock(view, { blockedReason: "Confirm is not available until you choose Same person or Different person above." })}
    <section class="bar" aria-labelledby="different-heading">
      <h2 id="different-heading">Not the same person?</h2>
      <form data-form="different-person" data-ref="${esc(view.id)}" class="stack" novalidate>
        ${reasonFields(view, reason)}
        <button type="submit" class="btn">This is a different person</button>
      </form>
    </section>`);
}

export function differentPerson(view, { error = null, reason = "" } = {}) {
  return page("Why is this a different person?", `
    ${error ? `<div class="banner error" role="alert"><p>${esc(error)}</p></div>` : ""}
    <form data-form="different-person" data-ref="${esc(view.id)}" class="stack" novalidate>
      ${reasonFields(view, reason)}
      <button type="submit" class="btn primary">Save my reason: this is a different person</button>
    </form>`, { back: `#/drafts/${view.id}`, backLabel: "Back to the same-name check" });
}

export function correction(view, { error = null, text = "" } = {}) {
  const entered = view.state === "submitted";
  return page(entered ? "Correct what was entered" : "Make a correction", `
    ${SSN_WARNING}
    ${error ? `<div class="banner error" role="alert"><p>${esc(error)}</p></div>` : ""}
    <form data-form="correction" data-ref="${esc(view.id)}" class="stack" novalidate>
      <label for="correction-text">What should change?</label>
      <p class="small" id="correction-help">Say it in plain words, for example "It was the third time on the street" or "Veteran: didn't ask".</p>
      <textarea id="correction-text" name="text" rows="5" required aria-describedby="correction-help ssn-warning">${esc(text)}</textarea>
      <button type="submit" class="btn primary">Send the correction</button>
    </form>
    <p class="small">${entered ? "You will check the corrected entries and press Confirm again." : "You will see a new version of the draft to check."}</p>`,
  { back: `#/drafts/${view.id}`, backLabel: "Back to the draft" });
}

export function receipt(view) {
  const r = view.receipt;
  const ids = r.hmis_ids.map((i) => `<div class="answer"><dt class="eyebrow">${esc(i.label)}</dt><dd><span class="value">${esc(i.value)}</span></dd></div>`).join("");
  return page("Entered in HMIS", `
    <p>${chip("green", "check", "Entered in HMIS")}</p>
    <div class="banner ok" role="status"><p>${esc(view.title)}: HMIS accepted it${r.client ? ` for client ${esc(r.client.id)} (${esc(r.client.label)})` : ""}.</p></div>
    <h2>Identifiers HMIS assigned</h2><dl class="answers">${ids}</dl>
    <p class="small">${esc(r.search_note)}</p>
    ${r.remaining_in_hmis.length ? `<h2>Still to complete in HMIS</h2><ul>${r.remaining_in_hmis.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : ""}
    ${view.kind === "update" ? `<div class="actions"><a class="btn" href="#/drafts/${esc(view.id)}/correct">Make a correction to these entries</a></div>` : ""}`);
}

export function failure(view) {
  const r = view.receipt;
  const f = r.failure;
  const done = r.hmis_ids.filter((i) => i.value);
  const todo = r.hmis_ids.filter((i) => !i.value);
  return page("Not entered in HMIS yet", `
    <p>${chip("red", "cross", "Not entered yet")}</p>
    <div class="banner error" role="alert"><p>HMIS did not accept ${esc(f.step)}.</p><p>${esc(f.explanation)}</p></div>
    <h2>Recorded in HMIS</h2>${done.length ? `<ul>${done.map((i) => `<li>${esc(i.label)}: <span class="mono">${esc(i.value)}</span></li>`).join("")}</ul>` : "<p>Nothing yet.</p>"}
    <h2>Not recorded yet</h2><ul>${todo.map((i) => `<li>${esc(i.label)}</li>`).join("")}</ul>
    <p>${esc(f.next)}</p>
    <div class="actions"><button type="button" class="btn primary" data-action="retry" data-ref="${esc(view.id)}">Try again to enter in HMIS</button></div>`);
}

export function draftStatus(view) {
  const text = {
    expired: "This draft was not confirmed in time and is now in your supervisor's queue. Nothing has been entered into HMIS. Please talk with your supervisor.",
    draft: "This note could not be drafted. Please write it again.",
    confirmed: "This draft is being entered in HMIS. Check back in a moment.",
  }[view.state] || "This draft is not waiting for you.";
  return page(view.status_label, `<p>${stateChip(view.state, view.status_label)}</p><p>${esc(view.title)}</p><p>${esc(text)}</p>
    ${view.state === "draft" ? `<div class="actions"><a class="btn primary" href="#/new">Write the note again</a></div>` : ""}`);
}

export function notFound() {
  return page("Not found", "<p>This note or draft is not yours, or it no longer exists.</p>");
}

function usDate(iso) {
  const [y, m, d] = String(iso).split("-");
  return y && m && d ? `${m}/${d}/${y}` : String(iso);
}

// Looking things up in HMIS (Stage 3c): four fixed forms, read-only. The form's fields are the whole
// request: no free text and no parser. Results are shown once and never stored.

export const QUERY_KINDS = {
  briefing: { title: "Who has been reported in a quadrant", button: "Show who was reported" },
  lookup: { title: "Look up a client", button: "Look up the client" },
  status: { title: "Check an ID document or housing assessment", button: "Check the status" },
  "no-contact": { title: "Who has had no contact for a while", button: "Show the watchlist" },
};

const OFFLINE = `<div class="banner warn" role="alert"><p><strong>You are offline.</strong> Looking things up in HMIS needs a `
  + `connection, so it is not available right now. You can still write notes.</p></div>`;

const READ_ONLY = `<p class="small">Read-only: nothing in HMIS changes. You only see records your project can see.</p>`;

export function queriesHome({ options = null, online = true } = {}) {
  const days = options ? options.no_contact_days : 60;
  const items = Object.entries(QUERY_KINDS).map(([kind, k]) => {
    const title = kind === "no-contact" ? `Who has had no contact for ${days} days` : k.title;
    return online ? `<a class="btn" href="#/queries/${kind}">${esc(title)}</a>` : `<p class="card disabled" aria-disabled="true">${esc(title)}</p>`;
  });
  return page("Look something up in HMIS", `${online ? "" : OFFLINE}${READ_ONLY}<div class="actions">${items.join("")}</div>`);
}

function quadrants(name, { optional = false, value = "" } = {}) {
  const choices = (optional ? [["", "All quadrants"]] : []).concat(["NW", "NE", "SW", "SE"].map((q) => [q, `${q} quadrant`]));
  return `<fieldset class="choices"><legend>${optional ? "Quadrant (optional)" : "Quadrant"}</legend>${choices.map(([v, label]) => {
    const id = `${name}-${v || "all"}`;
    return `<div class="choice"><input type="radio" id="${esc(id)}" name="${esc(name)}" value="${esc(v)}"${value === v ? " checked" : ""}${optional ? "" : " required"}>`
      + `<label for="${esc(id)}">${esc(label)}</label></div>`;
  }).join("")}</fieldset>`;
}

function who(values) {
  return `<fieldset class="choices"><legend>Which client</legend>
    <p class="small" id="who-help">Use the HMIS client ID, or the first and last name with the full date of birth. A name alone is never searched.</p>
    <label for="client_id">HMIS client ID</label>
    <input id="client_id" name="client_id" autocapitalize="characters" placeholder="HMIS-C-000101" value="${esc(values.client_id)}" aria-describedby="who-help">
    <p class="or">or</p>
    <label for="first_name">First name</label><input id="first_name" name="first_name" value="${esc(values.first_name)}">
    <label for="last_name">Last name</label><input id="last_name" name="last_name" value="${esc(values.last_name)}">
    <label for="date_of_birth">Date of birth</label><input id="date_of_birth" name="date_of_birth" type="date" value="${esc(values.date_of_birth)}">
  </fieldset>`;
}

export function queryForm(kind, { options = null, online = true, error = null, values = {} } = {}) {
  const k = QUERY_KINDS[kind];
  const days = options ? options.no_contact_days : 60;
  const windowDays = options ? options.briefing_window_days : 90;
  const statusTypes = options ? options.status_types : { id_document: "ID document", housing_assessment: "Housing assessment" };
  const fields = {
    briefing: `<p>Neighbors reported in the quadrant in the last ${esc(windowDays)} days, with their last contact.</p>${quadrants("quadrant", { value: values.quadrant || "" })}`,
    lookup: who(values),
    status: `<label for="status_type">What to check</label><select id="status_type" name="status_type" required>${Object.entries(statusTypes)
      .map(([id, label]) => `<option value="${esc(id)}"${values.status_type === id ? " selected" : ""}>${esc(label)}</option>`).join("")}</select>${who(values)}`,
    "no-contact": `<p>Neighbors with an active enrollment who are coming up on ${esc(days)} days, or past it, without a contact.</p>`
      + quadrants("quadrant", { optional: true, value: values.quadrant || "" }),
  }[kind];
  const title = kind === "no-contact" ? `Who has had no contact for ${days} days` : k.title;
  return page(title, `
    ${online ? "" : OFFLINE}
    ${error ? `<div class="banner error" role="alert"><p>${esc(error)}</p></div>` : ""}
    ${READ_ONLY}
    <form data-form="query" data-kind="${esc(kind)}" class="stack" novalidate>
      <fieldset class="plain"${online ? "" : " disabled"}>${fields}
      <button type="submit" class="btn primary">${esc(k.button)}</button></fieldset>
    </form>`, { back: "#/queries", backLabel: "Back to looking things up" });
}

function resultRow(r) {
  return `<li class="result"><p><strong>${esc(r.name)}</strong> <span class="mono">${esc(r.client_id)}</span></p>
    <p>Last contact ${esc(r.last_contact)}${r.quadrant ? `, ${esc(r.quadrant)} quadrant` : ""}</p>
    ${r.detail ? `<p class="small">${esc(r.detail)}</p>` : ""}</li>`;
}

export function queryResult(kind, out) {
  const again = `<div class="actions"><a class="btn" href="#/queries/${esc(kind)}">Search again</a><a class="btn plain" href="#/queries">Look up something else</a></div>`;
  if (out.action === "query_needs_more") {
    return page("Nothing was looked up", `<p>To search, I need:</p><ul>${out.missing.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>${again}`,
      { back: "#/queries", backLabel: "Back to looking things up" });
  }
  if (!out.result) {
    return page("Nothing was looked up", `<p>HMIS could not be read right now. No query was run. Please try again later.</p>${again}`,
      { back: "#/queries", backLabel: "Back to looking things up" });
  }
  const r = out.result;
  const groupIcon = (g) => (g.label.startsWith("Past") ? icon("cross") : g.label.startsWith("Approaching") ? icon("alert") : "");
  const groups = r.groups.map((g) => `<h2 class="with-icon">${groupIcon(g)}${esc(g.label)} (${esc(g.rows.length)})</h2>${g.hint ? `<p class="small">${esc(g.hint)}</p>` : ""}`
    + `<ul class="results">${g.rows.map(resultRow).join("")}</ul>`).join("");
  const tiles = r.tiles ? `<div class="tiles">
      <div class="tile red"><span class="tile-count">${esc(r.tiles.past)}</span><span class="tile-word">${icon("cross")}Past ${esc(r.tiles.days)} days</span></div>
      <div class="tile amber"><span class="tile-count">${esc(r.tiles.approaching)}</span><span class="tile-word">${icon("alert")}Approaching ${esc(r.tiles.days)} days</span></div>
    </div>` : "";
  const status = r.client ? `<ul class="results">${resultRow(r.client)}</ul>${r.items.length ? `<h2>Status</h2><ul>${r.items
    .map((i) => `<li>${esc(i.what)}: ${esc(i.status)} ${esc(i.date)}</li>`).join("")}</ul>` : ""}` : "";
  return page(r.title, `
    ${tiles}
    ${r.summary ? `<p class="lead">${esc(r.summary)}</p>` : ""}
    ${r.empty ? `<div class="banner info" role="status"><p>${esc(r.empty)}</p></div>` : ""}
    ${status}${groups}
    ${r.more ? `<div class="banner warn"><p>${esc(r.more)}</p></div>` : ""}
    ${r.note ? `<p class="small">${esc(r.note)}</p>` : ""}
    <p class="small">From HMIS as of ${esc(r.as_of)}. Only records your project can see. Nothing in HMIS was changed. This answer is not saved.</p>
    ${again}`, { back: "#/queries", backLabel: "Back to looking things up" });
}

// Supervisor and staff screens (Stage 3d): read-only states, times, and the audit. No note text,
// titles, or field values. Their only controls are links.

function when(iso) {
  if (!iso) return "not yet";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString("en-US", { dateStyle: "short", timeStyle: "short" });
}

const START = { back: "#/", backLabel: "Back to the start" };
const KINDS = { new_client: "New client", update: "Visit for a client in HMIS" };

// A real table on a desktop; CSS stacks each row into a card on a phone (data-label names each cell).
// The roles keep it a table for screen readers even when CSS changes how it is displayed.
function table(caption, headers, rows) {
  return `<table class="stack-table" role="table"><caption class="sr">${esc(caption)}</caption>
    <thead role="rowgroup"><tr role="row">${headers.map((h) => `<th scope="col" role="columnheader">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody role="rowgroup">${rows.map((cells) => `<tr role="row">${cells.map((c, i) => `<td role="cell" data-label="${esc(headers[i])}">${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

const draftLink = (id) => `<a class="mono" href="#/drafts/${esc(id)}">${esc(id)}</a>`;

function trail(events) {
  return `<h2>What happened</h2>${table("What happened to this draft", ["When", "Who", "What happened"],
    events.map((e) => [esc(when(e.at)), esc(e.actor || "System"), esc(e.what)]))}`;
}

function draftTable(drafts, flagKey) {
  return table("Drafts", ["Draft", "Kind", "Worker", "Version", "Started", "Entered", "State"], drafts.map((d) => [
    draftLink(d.id), esc(KINDS[d.kind] || d.kind), esc(d.worker_id), esc(d.version), esc(when(d.created_at)), esc(when(d.submitted_at)),
    `${stateChip(d.state, d.status_label)}${flagKey && d[flagKey] ? ` ${chip("amber", "flag", "Flagged for your review")}` : ""}`,
  ]));
}

function facts(items) {
  return `<dl class="facts">${items.map(([k, v]) => `<div class="answer"><dt class="eyebrow">${esc(k)}</dt><dd><span class="value">${esc(v)}</span></dd></div>`).join("")}</dl>`;
}

export function supervisorHome({ user, queue = [], flags = [] }) {
  return page(`Hello, ${user ? user.display_name : ""}`, `
    <p>You can see drafts and what happened to them. Only the worker who wrote a draft can confirm or correct it.</p>
    <div class="actions">
      <a class="btn primary" href="#/queue">Drafts not confirmed in time (${esc(queue.length)} waiting)</a>
      <a class="btn" href="#/flags">Decisions to look at (${esc(flags.length)} flagged)</a>
      <a class="btn plain" href="#/drafts">See every draft's state</a>
    </div>`, { back: null });
}

export function supervisorQueue(queue) {
  const list = queue.length ? table("Drafts not confirmed in time", ["Draft", "Worker", "Version", "Waiting", "Since", "State"], queue.map((q) => [
    draftLink(q.draft_id), esc(q.worker_id), esc(q.version), `${esc(q.hours_waiting)} hours`, esc(when(q.in_review_since)), chip("amber", "clock", q.status_label),
  ]))
    : `<div class="banner ok" role="status"><p>No drafts are waiting. Every draft was confirmed in time.</p></div>`;
  return page("Drafts not confirmed in time", `
    <p>These drafts were not confirmed in time. Nothing from them was entered in HMIS. Please talk with the worker.</p>${list}`, START);
}

export function supervisorFlags(flags) {
  const list = flags.length ? table("Flagged decisions", ["Draft", "Flag", "The worker's reason"], flags.map((f) => [
    draftLink(f.draft_id), `${chip("amber", "flag", "Flagged")}<p class="small">${esc(f.flag)}</p>`, `<q>${esc(f.reason)}</q>`,
  ]))
    : `<div class="banner ok" role="status"><p>No decisions are flagged.</p></div>`;
  return page("Decisions to look at", `
    <p>A worker said someone is a different person even though the last four SSN digits matched a client in HMIS. The digits are never shown here.</p>${list}`, START);
}

export function supervisorDrafts(drafts) {
  return page("Every draft's state", drafts.length ? draftTable(drafts, "flagged") : "<p>There are no drafts yet.</p>", START);
}

export function supervisorDraft(view) {
  const ids = view.hmis_ids.filter((i) => i.value);
  return page(`Draft ${view.id}`, `
    <p>${stateChip(view.state, view.status_label)}</p>
    ${view.flagged ? `<div class="banner warn"><p>This decision is flagged for your review. <a href="#/flags">See the worker's reason</a>.</p></div>` : ""}
    ${facts([["Kind", KINDS[view.kind] || view.kind], ["Worker", view.worker_id], ["Version", view.version], ["Started", when(view.created_at)],
    ["Confirmed", when(view.confirmed_at)], ["Entered in HMIS", when(view.submitted_at)], ...ids.map((i) => [i.label, i.value])])}
    ${trail(view.events)}
    <p class="small">Names, answers, and note text are not shown here [TBC with Goodwill: what supervisors may see].</p>`,
  { back: "#/drafts", backLabel: "Back to every draft" });
}

export function staffHome({ user }) {
  return page(`Hello, ${user ? user.display_name : ""}`, `
    <p>Read-only: who did what and when. Note text and client answers are never shown here.</p>
    <div class="actions">
      <a class="btn primary" href="#/drafts">See the list of drafts</a>
      <a class="btn" href="#/queries">See the log of HMIS lookups</a>
    </div>`, { back: null });
}

export function staffDrafts(drafts) {
  return page("Drafts", drafts.length ? draftTable(drafts, null) : "<p>There are no drafts yet.</p>", START);
}

export function staffAudit(record) {
  const ids = (record.hmis_id_list || []).filter((i) => i.value);
  return page(`Draft ${record.draft_id}`, `
    <p>${stateChip(record.state, record.status_label)}</p>
    ${facts([["Kind", KINDS[record.kind] || record.kind], ["Worker", record.worker_id], ["Versions", record.versions.length],
    ["Confirmed", when(record.confirmed_at)], ["Entered in HMIS", when(record.submitted_at)], ...ids.map((i) => [i.label, i.value])])}
    ${trail(record.events)}`, { back: "#/drafts", backLabel: "Back to the list of drafts" });
}

export function staffQueries(log) {
  const list = log.length ? table("Log of HMIS lookups", ["When", "Who", "Reference", "What was asked"], log.map((e) => [
    esc(when(e.at)), esc(e.actor || "System"), `<span class="mono">${esc(e.ref)}</span>`, esc(e.what),
  ]))
    : "<p>No HMIS lookups yet.</p>";
  return page("Log of HMIS lookups", `<p>What was asked, by whom, and how many rows came back. Never the answers. A name or date of birth is only noted as given.</p>${list}`, START);
}
