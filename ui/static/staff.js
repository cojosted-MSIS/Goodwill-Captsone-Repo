// Staff screens for the outreach intake demo (task 5.2). Synthetic data only.
// Parser run (A2, B2), mapped draft (A3, B3), staged record (A4, B4), submitted record and
// audit trail (B8). Everything is read from the intake system's own staging store; nothing
// here reads HMIS. Text is always set with textContent, never as HTML.
"use strict";

const TABS = [
  ["run", "Parser run"],
  ["mapped", "Mapped draft"],
  ["record", "Staged record"],
  ["audit", "Submitted record and audit"],
];

const STATE_CHIPS = {
  in_review: ["Awaiting worker confirmation", "warn"],
  draft: ["Not in review", "warn"],
  confirmed: ["Confirmed: entering", "warn"],
  submitted: ["CONFIRMED: submitted", "ok"],
  failed: ["Not entered in HMIS", "warn"],
  expired: ["With supervisor", "warn"],
};

function chip(text, kind) {
  return h("span", { class: `chip ${kind || ""}` }, text);
}

function stateChip(state) {
  const [text, kind] = STATE_CHIPS[state] || [state, ""];
  return chip(text, kind);
}

function windowFrame(address, title, chipEl, body, opts) {
  const o = opts || {};
  return h("div", { class: "window" },
    h("div", { class: "chrome" },
      h("div", { class: "dots", "aria-hidden": "true" }, h("span"), h("span"), h("span")),
      h("div", { class: "address" }, `intake.goodwill-internal.example / ${address}`)),
    h("div", { class: "title-row" }, h("h1", { class: o.mono ? "mono" : "" }, title), chipEl || null),
    o.tabsFor ? tabs(o.tabsFor, o.active) : null,
    h("div", { class: "body" }, body),
    o.footer ? h("div", { class: "footer" }, o.footer) : null);
}

function tabs(id, active) {
  return h("nav", { class: "tabs", "aria-label": "Views of this draft" },
    h("a", { href: "#/" }, "← All drafts"),
    TABS.map(([key, label]) => h("a", { href: `#/${key}/${id}`, "aria-current": key === active ? "page" : null }, label)));
}

function show(value) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) return "(blank)";
  if (Array.isArray(value)) return value.join("; ");
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function confidenceChip(c) {
  const kinds = { high: "ok", medium: "warn", low: "warn", worker: "worker", review: "warn" };
  const text = { worker: "Worker", review: "Review", "n/a": "n/a" }[c] || (c ? c[0].toUpperCase() + c.slice(1) : "n/a");
  return chip(text, kinds[c]);
}

// list of drafts

async function listScreen() {
  const drafts = await api("/demo/drafts");
  const rows = drafts.map((d) => h("tr", {},
    h("td", {}, h("code", {}, d.id)),
    h("td", {}, d.subject),
    h("td", {}, `v${d.version}`),
    h("td", {}, stateChip(d.state)),
    h("td", {}, d.parser),
    h("td", { class: "links" }, TABS.map(([key, label]) => h("a", { href: `#/${key}/${d.id}` }, label)))));
  const body = drafts.length
    ? h("div", { class: "table-wrap" }, h("table", { class: "drafts" },
        h("thead", {}, h("tr", {}, ["Draft", "Subject", "Version", "State", "Parser", "Views"].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows)))
    : h("p", { class: "note" }, "No drafts yet. Send a note from the phone screens first.");
  return windowFrame("drafts", "Drafts in the staging store", null, [
    body,
    h("p", { class: "note" }, h("a", { href: "/ui/" }, "Open the phone screens")),
  ]);
}

// screen 6: parser run (A2, B2)

async function runScreen(id) {
  const r = await api(`/staff/drafts/${encodeURIComponent(id)}/run`);
  const parserText = r.model ? `${r.parser} (model ${r.model})` : r.parser;
  const output = h("table", { class: "output" },
    h("thead", {}, h("tr", {}, ["Field", "Value", "Quote from the note", "Confidence"].map((t) => h("th", {}, t)))),
    h("tbody", {}, r.output.map((f) => h("tr", { class: f.scripted ? "scripted" : "" },
      h("td", {}, f.label),
      h("td", {}, f.value, f.scripted ? h("div", {}, chip("Scripted error", "scripted")) : null),
      h("td", { class: "q" }, f.source ? `"${f.source}"` : ""),
      h("td", {}, confidenceChip(f.confidence))))));
  const left = h("div", {},
    h("div", { class: "label-caps" }, `Fixed instructions: ${r.instructions.title}`),
    h("div", { class: "box prompt" }, r.instructions.text),
    h("div", { class: "label-caps" }, "Input: worker's note"),
    r.note ? h("div", { class: "box" }, r.note) : null,
    h("p", { class: "note" }, r.note_status));
  const right = h("div", {},
    r.scripted ? h("div", { class: "banner scripted" },
      "Scripted demo example: this output contains a deliberate error written for the demo. It is not a live model result.") : null,
    h("div", { class: "label-caps" }, "Parser output (verified, structured)"),
    h("div", { class: "table-wrap" }, output),
    h("div", { class: "label-caps" }, "Case note (generated)"),
    h("div", { class: "box" }, r.case_note || "(none)"),
    r.flags.length ? [h("div", { class: "label-caps" }, "Parser flags"), h("ul", {}, r.flags.map((f) => h("li", {}, f.split(": ").slice(1).join(": ") || f)))] : null,
    r.retry_reasons.length ? [h("div", { class: "label-caps" }, "Checks the first reply failed (retried)"), h("ul", {}, r.retry_reasons.map((f) => h("li", {}, f)))] : null);
  return windowFrame(`runs / ${r.draft_id}`, `Note parser: run for ${r.draft_id}`, chip(r.scripted ? "Scripted" : "Parsed", r.scripted ? "scripted" : "ok"),
    h("div", { class: "run" }, left, right), {
      tabsFor: r.draft_id, active: "run",
      footer: [
        h("span", {}, `Received ${timeOf(r.received_at)}`),
        h("span", {}, `Parse time ${r.elapsed_seconds === null ? "not recorded" : r.elapsed_seconds < 0.1 ? "under 0.1 s" : `${r.elapsed_seconds} s`}`),
        h("span", {}, `Parser: ${parserText}, prompt ${r.prompt_version}`),
        h("span", {}, `Tries ${r.attempts}`),
        h("span", {}, `Fields extracted ${r.output.length} | Parser flags ${r.flags.length} | Missing before entry: ${r.missing.length}`),
      ],
    });
}

// screen 7: mapped draft (A3, B3)

async function mappedScreen(id) {
  const r = await api(`/drafts/${encodeURIComponent(id)}/review`);
  const body = [];
  if (r.scripted_label) body.push(h("div", { class: "banner scripted" }, r.scripted_label));
  if (r.missing.length) body.push(h("div", { class: "banner warn" }, `Missing before entry: ${r.missing.join(", ")}`));
  for (const s of r.sections) {
    body.push(h("div", { class: "label-caps section-caps" }, s.label));
    body.push(h("div", { class: "form" }, s.fields.map((f) => h("div", { class: "item" },
      h("div", { class: "field-label" }, f.label),
      h("div", { class: `input${f.missing ? " missing" : ""}` }, f.missing ? "Not stated: held open for the worker" : f.value),
      f.source ? h("div", { class: "help" }, `${f.origin_label}: "${f.source}"`) :
        f.origin_label ? h("div", { class: "help" }, f.origin_label) : null,
      f.flags.map((m) => h("div", { class: "help flag" }, m))))));
    if (s.collapsed.length) {
      body.push(h("p", { class: "collapsed-list" }, `Not needed for this neighbor, left blank: ${s.collapsed.map((f) => f.label).join(", ")}`));
    }
    if (s.id === "ce_enrollment") body.push(h("p", { class: "note" }, r.consent));
  }
  body.push(h("div", { class: "label-caps section-caps" }, "Case note (generated)"));
  body.push(h("div", { class: "form" }, h("div", { class: "item wide" },
    h("div", { class: "input" }, r.case_note || "(none)"),
    h("div", { class: "help" }, "Summarized from the note; the worker approves the wording"))));
  return windowFrame(`drafts / ${r.draft_id}`, `Mapped draft v${r.version}: new client, program enrollment and Coordinated Entry`,
    stateChip(r.state), body, {
      tabsFor: r.draft_id, active: "mapped",
      footer: [h("span", {}, "Fields follow the demo's HMIS field list in config/fields.yaml. Actual HMIS fields are to be confirmed with CHIP and the HMIS administrator.")],
    });
}

// screen 8: staged record (A4, B4)

function recordTable(rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "record" },
    h("thead", {}, h("tr", {}, ["Column", "Value", "Type", "Source", "Confidence"].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows.map((row) => h("tr", { class: row.confidence === "worker" ? "worker" : (row.value === null ? "blank" : "") },
      h("td", { class: "col" }, row.column),
      h("td", {}, show(row.value)),
      h("td", { class: "type" }, row.type),
      h("td", { class: "src" }, row.source),
      h("td", {}, confidenceChip(row.confidence)))))));
}

async function recordScreen(id) {
  const v = await api(`/drafts/${encodeURIComponent(id)}`);
  const staged = ["draft", "in_review"].includes(v.state);
  return windowFrame(`api / drafts / ${v.encounter_id}`, `GET /drafts/${v.encounter_id}`,
    chip(staged ? "STAGED: not sent to HMIS" : v.status, staged ? "warn" : "ok"),
    [recordTable(v.rows)], {
      mono: true, tabsFor: v.encounter_id, active: "record",
      footer: [h("span", {}, staged ? "Staged record. Submission to HMIS is blocked until the worker replies CONFIRM."
        : `Draft v${v.version}, state ${v.state}.`)],
    });
}

// screen 9: submitted record with audit trail (B8)

function auditText(e) {
  switch (e.event) {
    case "draft_created": return `Draft v${e.version} generated from the worker's email (parser ${e.parser}${e.model ? `, model ${e.model}` : ""})`;
    case "hmis_search_not_stated": return "Note held: the email did not say HMIS was searched";
    case "hmis_search_confirmed_by_worker": return "Worker confirmed the HMIS search";
    case "review_sent": return `Draft v${e.version} sent to the worker for confirmation${e.blocking ? ` (${e.blocking} required field${e.blocking > 1 ? "s" : ""} missing)` : ""}`;
    case "corrections_applied": return `Worker replied with corrections (${(e.changed_fields || []).join(", ")}); draft v${e.to_version} generated, corrected fields marked as worker-sourced`;
    case "rephrase_requested": return "Worker's reply could not be matched to a field; asked to rephrase";
    case "confirm_blocked": return `Worker replied CONFIRM to v${e.version}; held back until these are supplied: ${(e.blocking || []).join(", ")}`;
    case "confirm_of_old_version": return `Worker confirmed v${e.confirmed} after v${e.current} was sent; asked to review v${e.current}`;
    case "confirmed": return `Worker replied CONFIRM to v${e.version}`;
    case "entry_step": return `HMIS ${e.step.replace("_", " ")}: ${e.ok ? `accepted, ${e.identifier}` : `not accepted (${e.code})`}`;
    case "retry_requested": return "Worker replied RETRY";
    case "submitted": return "Record submitted to HMIS";
    case "email_copies_deleted": return "Email copies deleted from the intake inbox under the retention rule";
    case "expired_to_supervisor_queue": return "Not confirmed in time; moved to the supervisor queue";
    default: return e.event.replaceAll("_", " ");
  }
}

async function auditScreen(id) {
  const [v, a] = await Promise.all([api(`/drafts/${encodeURIComponent(id)}`), api(`/drafts/${encodeURIComponent(id)}/audit`)]);
  const ids = [["Client ID", a.hmis_ids.client_id], ["Program enrollment ID", a.hmis_ids.enrollment_id],
    ["Coordinated Entry enrollment ID", a.hmis_ids.ce_enrollment_id]];
  const rows = v.rows.concat([{ column: "worker_confirmed_at", value: a.confirmed_at, type: "datetime", source: "Reply CONFIRM", confidence: "n/a" }]);
  const submitted = a.state === "submitted";
  return windowFrame(`api / drafts / ${a.draft_id} / audit`, `Submitted record ${a.draft_id}`,
    submitted ? chip("CONFIRMED: submitted", "ok") : stateChip(a.state), [
      h("div", { class: "label-caps" }, "Identifiers HMIS assigned"),
      h("div", { class: "ids" }, ids.map(([label, value]) => h("div", {}, `${label}: `, h("code", {}, value || "not assigned")))),
      a.changed_fields.length ? h("p", { class: "note" }, `Worker-corrected fields (shaded): ${a.changed_fields.join(", ")}`) : null,
      recordTable(rows),
      h("div", { class: "label-caps" }, "Audit trail"),
      h("ol", { class: "audit" }, a.events.map((e) => h("li", {}, h("time", {}, timeOf(e.at)), auditText(e)))),
      h("p", { class: "note" }, "The audit record keeps who, when, versions and changed field names. It never holds the note text."),
    ], {
      mono: false, tabsFor: a.draft_id, active: "audit",
      footer: [h("span", {}, "Entered into the mock HMIS. Live submission depends on CHIP approving API access.")],
    });
}

// router

async function render() {
  const root = document.getElementById("app");
  const [, route, arg] = (location.hash || "#/").split("/");
  let screen;
  try {
    if (route === "run") screen = await runScreen(arg);
    else if (route === "mapped") screen = await mappedScreen(arg);
    else if (route === "record") screen = await recordScreen(arg);
    else if (route === "audit") screen = await auditScreen(arg);
    else screen = await listScreen();
  } catch (err) {
    screen = windowFrame("error", "Could not load this view", null, h("p", { class: "error" }, err.message));
  }
  root.replaceChildren(screen);
  window.scrollTo(0, 0);
  markPageHeight();
}

window.addEventListener("hashchange", render);
render();
