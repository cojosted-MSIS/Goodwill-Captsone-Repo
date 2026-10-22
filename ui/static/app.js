// Phone screens for the outreach intake demo (task 5). Synthetic data only.
// Every worker action is sent as a simulated email (POST /mail/send) through the same
// workflow as the intake inbox. Text is always set with textContent, never as HTML.
"use strict";

const OUTCOME_TEXT = {
  drafted: "Draft created. The review email is in your inbox.",
  search_requested: "The system needs you to confirm your HMIS search. See your inbox.",
  revised: "Your changes were applied. A revised draft is in your inbox.",
  rephrase: "Your reply could not be matched to a field. See your inbox.",
  still_missing: "CONFIRM was not accepted: required fields are still missing. See your inbox.",
  old_version: "That was not the latest version. See your inbox.",
  submitted: "Submitted to HMIS.",
  entry_failed: "HMIS did not accept the entry. Here is what happened.",
  parse_failed: "The note could not be drafted. See your inbox.",
  expired: "This draft is with your supervisor. See your inbox.",
  ignored: "The reply was not applied. See your inbox.",
  already_submitted: "This draft was already submitted.",
  dropped: "The message was not accepted: the sender is not an authorized worker.",
};

const state = { scenarios: [], worker: null, toast: null };

// helpers (h, api and timeOf are in common.js)

function sendMail(subject, body) {
  return api("/mail/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sender: state.worker, subject, body }),
  });
}

function go(hash, toast) {
  state.toast = toast || null;
  if (location.hash === hash) render();
  else location.hash = hash;
}

function phone(title, backHash, body, extra) {
  const now = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const toast = state.toast ? h("div", { class: "toast", role: "status" }, state.toast) : null;
  state.toast = null;
  return h("div", { class: "phone" },
    h("div", { class: "status-bar" }, h("span", {}, now), h("span", {}, "LTE 64%")),
    h("div", { class: "top-bar" },
      backHash ? h("button", { class: "icon-btn", "aria-label": "Back", onclick: () => go(backHash) }, "←") : null,
      h("h1", {}, title),
      extra || null),
    h("div", { class: "screen" }, toast, body));
}

function errorScreen(err) {
  return phone("Something went wrong", "#/", h("p", { class: "error" }, err.message));
}

// screen 0: demo home

async function resetDemo() {
  if (!window.confirm("Reset the demo? This clears the mock HMIS and all demo drafts, emails and audit records.")) return;
  try {
    await api("/demo/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: "reset demo" }),
    });
    go("#/", "Demo reset: the mock HMIS and the staging store are clear.");
  } catch (err) {
    go("#/", err.message);
  }
}

async function homeScreen() {
  const drafts = await api("/demo/drafts");
  const cards = state.scenarios.map((s) =>
    h("div", { class: "card" },
      h("h2", {}, `Scenario ${s.id}: ${s.title}`),
      h("p", {}, s.summary),
      s.scripted ? h("p", { class: "small" }, "Uses a scripted demo example, not a live model result.") : null,
      h("button", { class: "btn primary", onclick: () => go(`#/compose/${s.id}`) }, `Start scenario ${s.id}`)));
  const list = drafts.length
    ? h("ul", { class: "mail-list" }, drafts.map((d) =>
        h("li", {}, h("a", { href: d.state === "submitted" ? `#/receipt/${d.id}` : "#/inbox" },
          h("div", { class: "mail-subject" }, d.subject),
          h("div", { class: "mail-meta" }, h("span", {}, d.id), h("span", {}, `v${d.version}`),
            h("span", { class: `tag ${d.state === "submitted" ? "ok" : "warn"}` }, d.state.replace("_", " ")))))))
    : h("p", { class: "small" }, "No drafts yet.");
  return phone("Outreach intake demo", null, [
    h("p", { class: "small" }, `Signed in as ${state.worker}`),
    ...cards,
    h("div", { class: "actions" },
      h("button", { class: "btn", onclick: () => go("#/compose/new") }, "Write a new note"),
      h("button", { class: "btn", onclick: () => go("#/inbox") }, "Open inbox")),
    h("p", { class: "small" }, h("a", { href: "/ui/staff.html" }, "Staff views: parser run, mapped draft, staged record, audit")),
    h("div", { class: "section-label" }, "Demo only"),
    h("div", { class: "card reset-card" },
      h("p", {}, "Clears the mock HMIS records and this demo's drafts, inbox and audit, so the next run starts at HMIS-C-000001. "
        + "It works only against the local mock HMIS, never a real one."),
      h("button", { class: "btn", onclick: resetDemo }, "Reset demo (demo only)")),
    h("div", { class: "section-label" }, "Drafts"),
    list,
  ]);
}

// screen 1: compose (A1, B1)

function composeScreen(id) {
  const scenario = state.scenarios.find((s) => s.id === id);
  const subject = h("input", { "aria-label": "Subject", value: scenario ? scenario.subject : "New client: " });
  const body = h("textarea", { class: "note", "aria-label": "Note" });
  body.value = scenario ? scenario.body : "";
  const status = h("p", { class: "small", role: "status" });
  const send = h("button", {
    class: "btn primary",
    onclick: async () => {
      send.disabled = true;
      try {
        const out = await sendMail(subject.value, body.value);
        go("#/inbox", OUTCOME_TEXT[out.action] || out.action);
      } catch (err) {
        status.textContent = err.message;
        status.className = "error";
        send.disabled = false;
      }
    },
  }, "Send");
  return phone("Compose", "#/", [
    h("div", { class: "header-row" }, h("span", { class: "k" }, "From"), h("span", { class: "v" }, state.worker)),
    h("div", { class: "header-row" }, h("span", { class: "k" }, "To"),
      h("span", { class: "v pill" }, "outreach-intake@goodwill-secure.example")),
    h("div", { class: "header-row" }, h("span", { class: "k" }, "Subject"), subject),
    h("div", { class: "secure" }, "\u{1F512} Sending to secure intake inbox. Do not attach photos of ID documents here."),
    scenario && scenario.scripted
      ? h("div", { class: "banner scripted" }, "This scenario uses a scripted demo parser. If you edit the note, it is parsed normally.")
      : null,
    body,
    status,
  ], send);
}

// screen 2: inbox

async function inboxScreen() {
  const mails = await api(`/mail/inbox/${encodeURIComponent(state.worker)}`);
  const kindTag = (m) => {
    if (m.kind === "review") return m.current ? h("span", { class: "tag current" }, "Needs your reply") : h("span", { class: "tag" }, "Older version");
    if (m.kind === "receipt") return h("span", { class: "tag ok" }, "HMIS receipt");
    if (m.kind === "missing_info" || m.kind === "search_request") return h("span", { class: "tag warn" }, "Needs your reply");
    return null;
  };
  const list = mails.length
    ? h("ul", { class: "mail-list" }, mails.map((m) =>
        h("li", {}, h("a", { href: `#/mail/${m.id}` },
          h("div", { class: "mail-from" }, "Outreach Intake Assistant"),
          h("div", { class: "mail-subject" }, m.subject),
          h("div", { class: "mail-meta" }, h("span", {}, timeOf(m.at)), kindTag(m))))))
    : h("p", { class: "small" }, "Your inbox is empty. Send a note first.");
  return phone("Inbox", "#/", list);
}

// screen 3: review email (A5, B5, B7), or any other email as plain text

function senderBlock(at) {
  return h("div", { class: "sender" },
    h("div", { class: "avatar", "aria-hidden": "true" }, "OI"),
    h("div", {},
      h("div", { class: "who" }, "Outreach Intake Assistant"),
      h("div", { class: "addr" }, `outreach-intake@goodwill-secure.example to me | ${timeOf(at)}`)));
}

function fieldRow(f) {
  const value = f.missing
    ? h("span", { class: "missing" }, "NOT STATED: please reply with it")
    : h("span", {}, f.value);
  const origin = f.origin_label ? h("span", { class: `origin ${f.origin}` }, f.origin_label) : null;
  const source = f.source ? h("span", { class: "source" }, `"${f.source}"`) : null;
  return h("div", { class: `field${f.flags.length ? " flagged" : ""}` },
    h("div", { class: "label" }, f.label),
    h("div", { class: "value" }, value, source, origin, f.flags.map((m) => h("span", { class: "flag-msg" }, `⚠ ${m}`))));
}

function reviewScreen(mail) {
  const r = mail.review;
  const blocks = [];
  const title = r.subject.replace(/\s*\[[^\]]+\]\s*$/, "");
  blocks.push(h("h2", { class: "mail-title" }, r.revised ? title.replace("Please confirm:", "Please confirm (revised):") : title));
  blocks.push(h("p", { class: "small" }, `${r.draft_id}, draft v${r.version}`));
  blocks.push(senderBlock(mail.at));
  blocks.push(h("p", {}, r.revised
    ? "Updated with your corrections. Reply CONFIRM if this is now correct, or reply with more changes."
    : "Here is your draft. Reply CONFIRM if it is correct, or reply with changes in plain words."));
  if (r.scripted_label) blocks.push(h("div", { class: "banner scripted", role: "note" }, r.scripted_label));
  if (r.missing.length) {
    blocks.push(h("div", { class: "banner warn", role: "alert" },
      `⚠ ${r.missing.length} required field${r.missing.length > 1 ? "s" : ""} missing: ${r.missing.join(", ")}`));
  }
  const otherFlags = r.flags.filter((f) => !f.blocking);
  if (otherFlags.length) {
    blocks.push(h("div", { class: "banner info" }, "Please check:",
      h("ul", {}, otherFlags.map((f) => h("li", {}, f.message)))));
  }
  for (const s of r.sections) {
    blocks.push(h("div", { class: "section-label" }, s.label));
    if (s.fields.length) blocks.push(h("div", { class: "fields" }, s.fields.map(fieldRow)));
    if (s.collapsed.length) {
      blocks.push(h("details", { class: "collapsed" },
        h("summary", {}, `${s.collapsed.length} more field${s.collapsed.length > 1 ? "s" : ""} not needed for this neighbor`),
        h("ul", {}, s.collapsed.map((f) => h("li", {}, `${f.label}: blank`)))));
    }
    if (s.id === "ce_enrollment") blocks.push(h("p", { class: "consent" }, r.consent));
  }
  blocks.push(h("div", { class: "section-label" }, "Case note (generated: read it for wording, not just accuracy)"));
  blocks.push(h("div", { class: "case-note" }, r.case_note || "(none)"));
  if (r.notices.length) {
    blocks.push(h("div", { class: "banner info" }, "Notes:", h("ul", {}, r.notices.map((n) => h("li", {}, n)))));
  }
  blocks.push(h("details", { class: "collapsed" }, h("summary", {}, "Remaining in HMIS (you complete these)"),
    h("ul", {}, r.remaining_in_hmis.map((i) => h("li", {}, i)))));

  const confirm = h("button", {
    class: "btn primary",
    disabled: !r.confirm_allowed,
    "aria-describedby": r.confirm_allowed ? null : "blocked-reason",
    onclick: async () => {
      confirm.disabled = true;
      try {
        const out = await sendMail(`Re: ${mail.subject}`, "CONFIRM");
        if (out.action === "submitted" || out.action === "entry_failed") go(`#/receipt/${out.ref}`, OUTCOME_TEXT[out.action]);
        else go("#/inbox", OUTCOME_TEXT[out.action] || out.action);
      } catch (err) {
        go("#/inbox", err.message);
      }
    },
  }, "Reply CONFIRM");
  blocks.push(h("div", { class: "actions" },
    confirm,
    h("button", { class: "btn", onclick: () => go(`#/reply/${mail.id}`) }, "Reply with changes"),
    r.confirm_blocked_reason ? h("p", { class: "blocked-reason", id: "blocked-reason" }, r.confirm_blocked_reason) : null));
  blocks.push(h("p", { class: "small" }, r.footer));
  return phone("", "#/inbox", blocks);
}

function plainMailScreen(mail) {
  const blocks = [h("h2", { class: "mail-title" }, mail.subject), senderBlock(mail.at)];
  if (mail.kind === "review" && !mail.current) {
    const note = mail.draft_state === "submitted"
      ? "This draft has been submitted to HMIS."
      : mail.draft_state === "in_review"
        ? `This is version ${mail.version}. Version ${mail.draft_version} was sent after it: reply to that one.`
        : `This draft is no longer waiting for review (${(mail.draft_state || "").replace("_", " ")}).`;
    blocks.push(h("div", { class: "banner info" }, note));
  }
  blocks.push(h("div", { class: "plain-body" }, mail.body));
  const actions = [];
  if (mail.ref && (mail.draft_state === "submitted" || mail.kind === "receipt")) {
    actions.push(h("button", { class: "btn primary", onclick: () => go(`#/receipt/${mail.ref}`) }, "View HMIS receipt"));
  }
  if (mail.ref && mail.draft_state === "failed") {
    actions.push(h("button", { class: "btn primary", onclick: () => go(`#/receipt/${mail.ref}`) }, "What failed and retry"));
  }
  if (["search_request", "missing_info", "notice"].includes(mail.kind) && mail.draft_state !== "submitted") {
    actions.push(h("button", { class: "btn", onclick: () => go(`#/reply/${mail.id}`) }, "Reply"));
  }
  if (actions.length) blocks.push(h("div", { class: "actions" }, actions));
  return phone("", "#/inbox", blocks);
}

async function mailScreen(id) {
  const mail = await api(`/mail/message/${encodeURIComponent(id)}`);
  return mail.review ? reviewScreen(mail) : plainMailScreen(mail);
}

// screen 4: reply (B6)

async function replyScreen(id) {
  const mail = await api(`/mail/message/${encodeURIComponent(id)}`);
  const subject = mail.subject.startsWith("Re:") ? mail.subject : `Re: ${mail.subject}`;
  const body = h("textarea", { class: "note", "aria-label": "Your reply" });
  const scenario = state.scenarios.find((s) => s.suggested_reply && mail.subject.includes(s.subject));
  const status = h("p", { class: "small", role: "status" });
  const send = h("button", {
    class: "btn primary",
    onclick: async () => {
      if (!body.value.trim()) { status.textContent = "Type CONFIRM or your changes first."; return; }
      send.disabled = true;
      try {
        const quoted = mail.body.split("\n").map((l) => `> ${l}`).join("\n");
        const out = await sendMail(subject, `${body.value}\n\n${quoted}`);
        if (out.action === "submitted" || out.action === "entry_failed") go(`#/receipt/${out.ref}`, OUTCOME_TEXT[out.action]);
        else go("#/inbox", OUTCOME_TEXT[out.action] || out.action);
      } catch (err) {
        status.textContent = err.message;
        status.className = "error";
        send.disabled = false;
      }
    },
  }, "Send");
  return phone("Reply", `#/mail/${mail.id}`, [
    h("div", { class: "header-row" }, h("span", { class: "k" }, "From"), h("span", { class: "v" }, state.worker)),
    h("div", { class: "header-row" }, h("span", { class: "k" }, "To"),
      h("span", { class: "v pill" }, "outreach-intake@goodwill-secure.example")),
    h("div", { class: "header-row" }, h("span", { class: "k" }, "Subject"), h("span", { class: "v" }, subject)),
    h("div", { class: "secure" }, "\u{1F512} Sending to secure intake inbox. Do not attach photos of ID documents here."),
    h("p", { class: "small" }, "Write CONFIRM, or your changes in plain words, for example \"Veteran: no\"."),
    scenario ? h("button", { class: "btn", onclick: () => { body.value = scenario.suggested_reply; } },
      "Use the scenario's suggested reply") : null,
    body,
    status,
    h("div", { class: "quoted" }, mail.body.split("\n").slice(0, 12).map((l) => `> ${l}`).join("\n")),
  ], send);
}

// screen 5: HMIS receipt

function failureScreen(r) {
  const f = r.failure;
  const recorded = r.hmis_ids.filter((i) => i.value);
  const status = h("p", { class: "small", role: "status" });
  const retry = h("button", {
    class: "btn primary",
    onclick: async () => {
      retry.disabled = true;
      try {
        const out = await sendMail(`Re: Not entered in HMIS [${r.draft_id}]`, "RETRY");
        go(`#/receipt/${r.draft_id}`, OUTCOME_TEXT[out.action] || out.action);
      } catch (err) {
        status.textContent = err.message;
        status.className = "error";
        retry.disabled = false;
      }
    },
  }, "Reply RETRY");
  return phone("Not entered in HMIS", "#/inbox", [
    h("div", { class: "banner warn", role: "alert" }, `HMIS did not accept ${f.step} for ${r.subject}.`),
    h("div", { class: "section-label" }, "What happened"),
    h("p", {}, f.explanation),
    h("div", { class: "section-label" }, "Recorded in HMIS so far"),
    recorded.length
      ? h("div", { class: "receipt-ids" }, recorded.map((i) => h("div", {}, h("span", {}, i.label), h("code", {}, i.value))))
      : h("p", { class: "small" }, "Nothing was recorded."),
    h("p", { class: "small" }, f.next),
    h("div", { class: "actions" }, retry,
      h("button", { class: "btn", onclick: () => go("#/") }, "Back to demo home")),
    status,
  ]);
}

async function receiptScreen(id) {
  const r = await api(`/drafts/${encodeURIComponent(id)}/receipt`);
  if (r.failure) return failureScreen(r);
  return phone("Submitted to HMIS", "#/inbox", [
    h("div", { class: "banner ok", role: "status" }, `✓ HMIS accepted the entries for ${r.subject}.`),
    h("p", { class: "small" }, `Confirmed ${r.confirmed_at ? timeOf(r.confirmed_at) : ""}, submitted ${timeOf(r.submitted_at)}, draft v${r.version}.`),
    h("div", { class: "section-label" }, "Identifiers HMIS assigned"),
    h("div", { class: "receipt-ids" }, r.hmis_ids.map((i) => h("div", {}, h("span", {}, i.label), h("code", {}, i.value)))),
    r.changed_by_worker.length
      ? h("p", { class: "small" }, `Fields you corrected: ${r.changed_by_worker.join(", ")}.`)
      : h("p", { class: "small" }, "No fields were corrected."),
    h("p", { class: "small" }, r.search_note),
    h("div", { class: "section-label" }, "Still to complete in HMIS"),
    h("ul", {}, r.remaining_in_hmis.map((i) => h("li", {}, i))),
    h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => go("#/") }, "Back to demo home")),
  ]);
}

// router

async function render() {
  const root = document.getElementById("app");
  const [, route, arg] = (location.hash || "#/").replace(/^#\//, "#/").split("/");
  let screen;
  try {
    if (route === "compose") screen = composeScreen(arg);
    else if (route === "inbox") screen = await inboxScreen();
    else if (route === "mail") screen = await mailScreen(arg);
    else if (route === "reply") screen = await replyScreen(arg);
    else if (route === "receipt") screen = await receiptScreen(arg);
    else screen = await homeScreen();
  } catch (err) {
    screen = errorScreen(err);
  }
  root.replaceChildren(screen);
  window.scrollTo(0, 0);
  markPageHeight();
}

async function start() {
  try {
    state.scenarios = await api("/demo/scenarios");
  } catch (err) {
    document.getElementById("app").replaceChildren(errorScreen(err));
    return;
  }
  state.worker = state.scenarios.length ? state.scenarios[0].sender : "j.alvarez@goodwill-outreach.example";
  window.addEventListener("hashchange", render);
  render();
}

start();
