// The device queue's logic, in Node with real WebCrypto, a fake clock, and an in-memory store, for
// tests/test_device_queue.py. Each case is a function; the results go out as JSON: {name: "ok" | error}.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const plan = JSON.parse(readFileSync(0, "utf8"));
const load = (name) => import(pathToFileURL(`${plan.web}/${name}`).href);
const { createQueue, classify, signOutGate, writeAllowed, STATUS_LABELS } = await load("queue.js");
const { seal } = await load("seal.js");

const HOUR = 3600 * 1000;
const START = Date.UTC(2026, 10, 9, 15, 31);
const LIMITS = { offline_write_hours: 12, queue_expiry_hours: 72, queue_warning_hours: 60 };
const TEXT = "ZZSENTINEL Kim Placeholder";

const pair = await crypto.subtle.generateKey({ name: "RSA-OAEP", modulusLength: 3072, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["wrapKey", "unwrapKey"]);
const der = new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey));
const publicKey = Buffer.from(der).toString("base64");
const keyId = Buffer.from(await crypto.subtle.digest("SHA-256", der)).toString("hex");

function memoryStore() {
  const rows = new Map();
  return { rows, all: async () => [...rows.values()].map((r) => structuredClone(r)), get: async (id) => structuredClone(rows.get(id)),
    put: async (r) => { rows.set(r.id, structuredClone(r)); }, remove: async (id) => { rows.delete(id); } };
}

function harness(answers = []) {
  const store = memoryStore();
  const clock = { now: START };
  const sent = [];
  const upload = async (record) => { sent.push(structuredClone(record)); return answers.length ? answers.shift() : { kind: "uploaded", ref: "ENC-2026-11-09-0001", action: "drafted" }; };
  return { store, clock, sent, queue: createQueue({ store, now: () => clock.now, limits: LIMITS, upload }) };
}

let serial = 0;
async function record(h, owner = "j.alvarez", kind = "new_client") {
  const id = `6f1c2a70-8b44-4f0e-9d13-${String(++serial).padStart(12, "0")}`;
  const savedAt = new Date(h.clock.now).toISOString();
  const envelope = await seal({ text: TEXT, title: "ZZTITLE", written_at: savedAt, ssn_invalid_label: null, contact: "stamp" }, { publicKey, keyId, owner, idempotencyKey: id, kind, savedAt });
  return h.queue.save({ id, owner, kind, savedAt, envelope });
}

const CLEAR_FIELDS = ["envelope", "id", "idempotency_key", "kind", "owner", "reason", "retries", "saved_at", "status"];

const cases = {
  async save_keeps_only_the_envelope_and_clear_metadata() {
    const h = harness();
    await record(h);
    const [row] = await h.store.all();
    assert.deepEqual(Object.keys(row).sort(), CLEAR_FIELDS);
    assert.deepEqual(Object.keys(row.envelope).sort(), ["ciphertext", "key_id", "nonce", "v", "wrapped_key"]);
    assert.equal(row.status, "saved");
    assert.ok(!JSON.stringify(row).includes("ZZSENTINEL") && !JSON.stringify(row).includes("ZZTITLE"));
  },
  async the_key_is_made_at_save_and_never_changes() {
    const h = harness([{ kind: "wait" }, { kind: "wait" }, { kind: "uploaded", ref: "ENC-1", action: "drafted" }]);
    const saved = await record(h);
    for (let i = 0; i < 3; i++) await h.queue.uploadAll("j.alvarez");
    assert.equal(h.sent.length, 3);
    assert.deepEqual([...new Set(h.sent.map((s) => s.idempotency_key))], [saved.id]);
    assert.deepEqual([...new Set(h.sent.map((s) => JSON.stringify(s.envelope)))].length, 1);
  },
  async the_four_status_words() {
    assert.deepEqual(STATUS_LABELS, { saved: "Saved on device", uploading: "Uploading", uploaded: "Uploaded", attention: "Needs attention" });
  },
  async a_new_note_shows_time_and_status_only() {
    const h = harness();
    await record(h);
    const v = await h.queue.view("j.alvarez");
    assert.equal(v.mine.length, 1);
    assert.deepEqual(Object.keys(v.mine[0]).sort(), ["hours_left", "id", "label", "reason", "ref", "saved_at", "status", "warning"]);
    assert.equal(v.mine[0].label, "Saved on device");
    assert.ok(!JSON.stringify(v).includes("ZZSENTINEL") && !JSON.stringify(v).includes("ciphertext"));
  },
  async uploading_shows_while_the_upload_runs() {
    const h = harness();
    let release;
    const gate = new Promise((r) => { release = r; });
    const q = createQueue({ store: h.store, now: () => h.clock.now, limits: LIMITS, upload: async () => { await gate; return { kind: "uploaded", ref: "ENC-1", action: "drafted" }; } });
    const saved = await q.save({ id: "6f1c2a70-8b44-4f0e-9d13-aaaaaaaaaaaa", owner: "j.alvarez", kind: "new_client", savedAt: new Date(START).toISOString(), envelope: { v: 1 } });
    const running = q.uploadAll("j.alvarez");
    await new Promise((r) => setTimeout(r, 10));
    const during = await q.view("j.alvarez");
    assert.equal(during.mine[0].label, "Uploading");
    assert.equal(during.uploading, 1);
    release();
    await running;
    assert.ok(saved);
  },
  async uploaded_deletes_the_envelope() {
    const h = harness();
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    const [row] = await h.store.all();
    assert.equal(row.status, "uploaded");
    assert.equal(row.ref, "ENC-2026-11-09-0001");
    assert.equal(row.envelope, undefined);
    assert.equal((await h.queue.view("j.alvarez")).mine[0].label, "Uploaded");
  },
  async a_failed_upload_stays_saved() {
    const h = harness([{ kind: "wait" }]);
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    const [row] = await h.store.all();
    assert.equal(row.status, "saved");
    assert.equal(row.retries, 1);
    assert.ok(row.envelope);
  },
  async a_refused_note_needs_attention_and_keeps_its_envelope() {
    const h = harness([{ kind: "attention", reason: "A plain reason." }]);
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    const [row] = await h.store.all();
    assert.equal(row.status, "attention");
    assert.equal(row.reason, "A plain reason.");
    assert.ok(row.envelope);
    const v = await h.queue.view("j.alvarez");
    assert.equal(v.mine[0].label, "Needs attention");
    assert.equal(v.needsAttention, 1);
  },
  async an_expired_session_keeps_the_envelope_and_stops() {
    const h = harness([{ kind: "signin" }]);
    await record(h);
    h.clock.now += 1000;
    await record(h);
    const result = await h.queue.uploadAll("j.alvarez");
    assert.equal(h.sent.length, 1);
    assert.equal(result.signIn, true);
    assert.deepEqual((await h.store.all()).map((r) => r.status), ["saved", "saved"]);
    assert.ok((await h.store.all()).every((r) => r.envelope));
  },
  async one_upload_at_a_time_per_note() {
    const h = harness();
    await record(h);
    await Promise.all([h.queue.uploadAll("j.alvarez"), h.queue.uploadAll("j.alvarez"), h.queue.uploadAll("j.alvarez")]);
    assert.equal(h.sent.length, 1);
  },
  async a_note_left_uploading_is_recovered() {
    const h = harness();
    const saved = await record(h);
    await h.store.put({ ...(await h.store.get(saved.id)), status: "uploading" });
    await h.queue.recover();
    assert.equal((await h.store.get(saved.id)).status, "saved");
  },
  async no_warning_before_60_hours() {
    const h = harness();
    await record(h);
    h.clock.now += 60 * HOUR - 1;
    assert.equal((await h.queue.view("j.alvarez")).mine[0].warning, false);
  },
  async a_warning_from_60_hours() {
    const h = harness();
    await record(h);
    h.clock.now += 60 * HOUR;
    const [note] = (await h.queue.view("j.alvarez")).mine;
    assert.equal(note.warning, true);
    assert.equal(note.hours_left, 12);
  },
  async not_expired_before_72_hours() {
    const h = harness();
    await record(h);
    h.clock.now += 72 * HOUR - 1;
    await h.queue.sweep();
    assert.ok((await h.store.all())[0].envelope);
  },
  async expired_at_72_hours_leaves_a_notice_with_no_content() {
    const h = harness();
    await record(h);
    h.clock.now += 72 * HOUR;
    await h.queue.sweep();
    const [row] = await h.store.all();
    assert.deepEqual(Object.keys(row).sort(), ["id", "owner", "saved_at", "status"]);
    assert.equal(row.status, "expired");
    const v = await h.queue.view("j.alvarez");
    assert.equal(v.mine.length, 0);
    assert.equal(v.notices.length, 1);
    assert.deepEqual(Object.keys(v.notices[0]).sort(), ["id", "saved_at"]);
    assert.equal(v.unsent, 0);
  },
  async a_notice_stays_until_dismissed() {
    const h = harness();
    const saved = await record(h);
    h.clock.now += 200 * HOUR;
    await h.queue.sweep();
    await h.queue.sweep();
    assert.equal((await h.queue.view("j.alvarez")).notices.length, 1);
    await h.queue.dismiss(saved.id, "j.alvarez");
    assert.equal((await h.queue.view("j.alvarez")).notices.length, 0);
    assert.equal((await h.store.all()).length, 0);
  },
  async only_the_owner_can_dismiss() {
    const h = harness();
    const saved = await record(h);
    h.clock.now += 200 * HOUR;
    await h.queue.sweep();
    await h.queue.dismiss(saved.id, "m.chen");
    assert.equal((await h.store.all()).length, 1);
  },
  async expiry_covers_every_account() {
    const h = harness();
    await record(h, "m.chen");
    h.clock.now += 72 * HOUR;
    await h.queue.sweep();
    assert.equal((await h.store.all())[0].status, "expired");
  },
  async an_uploaded_row_goes_when_opened() {
    const h = harness();
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    await h.queue.opened("ENC-2026-11-09-0001", "j.alvarez");
    assert.equal((await h.store.all()).length, 0);
  },
  async an_uploaded_row_goes_after_the_queue_limit() {
    const h = harness();
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    h.clock.now += 72 * HOUR;
    await h.queue.sweep();
    assert.equal((await h.store.all()).length, 0);
  },
  async another_account_sees_only_a_count() {
    const h = harness();
    await record(h, "j.alvarez");
    const v = await h.queue.view("m.chen");
    assert.deepEqual(v.mine, []);
    assert.deepEqual(v.notices, []);
    assert.equal(v.others, 1);
    assert.equal(v.unsent, 0);
    assert.ok(!JSON.stringify(v).includes("saved_at") || v.mine.length === 0);
    assert.deepEqual(Object.keys(v).sort(), ["mine", "needsAttention", "notices", "now", "others", "unsent", "uploadable", "uploading"]);
  },
  async another_accounts_uploaded_and_expired_rows_are_not_counted() {
    const h = harness();
    await record(h, "j.alvarez");
    await h.queue.uploadAll("j.alvarez");
    assert.equal((await h.queue.view("m.chen")).others, 0);
  },
  async upload_all_sends_only_the_owners_notes() {
    const h = harness();
    await record(h, "j.alvarez");
    const other = await record(h, "m.chen");
    await h.queue.uploadAll("m.chen");
    assert.deepEqual(h.sent.map((s) => s.id), [other.id]);
    assert.equal(h.sent[0].owner, "m.chen");
  },
  async a_note_needing_attention_is_not_retried_by_upload_all() {
    const h = harness([{ kind: "attention", reason: "A plain reason." }]);
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    await h.queue.uploadAll("j.alvarez");
    assert.equal(h.sent.length, 1);
  },
  async unsent_counts_saved_and_attention() {
    const h = harness([{ kind: "attention", reason: "x" }, { kind: "uploaded", ref: "ENC-1", action: "drafted" }]);
    await record(h);
    await record(h);
    await h.queue.uploadAll("j.alvarez");
    await record(h);
    const v = await h.queue.view("j.alvarez");
    assert.equal(v.unsent, 2);
    assert.equal(v.uploadable, 1);
  },
  async classify_each_answer() {
    assert.deepEqual(classify({ status: 200, data: { ref: "ENC-1", action: "drafted" } }), { kind: "uploaded", ref: "ENC-1", action: "drafted" });
    for (const status of [0, 403, 408, 429, 500, 502, 503]) assert.equal(classify({ status, data: {} }).kind, "wait", String(status));
    assert.equal(classify({ status: 401, data: {} }).kind, "signin");
    const refused = classify({ status: 422, data: { detail: { code: "sealed_offline_limit", message: "A fixed reason." } } });
    assert.deepEqual(refused, { kind: "attention", reason: "A fixed reason." });
    const unknown = classify({ status: 422, data: { detail: [{ loc: ["body"], msg: "ZZECHO" }] } });
    assert.equal(unknown.kind, "attention");
    assert.ok(!unknown.reason.includes("ZZECHO"));
    assert.equal(classify({ status: 409, data: { detail: "text" } }).kind, "attention");
  },
  async writing_is_allowed_up_to_the_limit() {
    const setup = { received_at: START, limits: LIMITS };
    assert.equal(writeAllowed(setup, START + 12 * HOUR), true);
    assert.equal(writeAllowed(setup, START + 12 * HOUR + 1), false);
    assert.equal(writeAllowed(null, START), false);
  },
  async gate_with_nothing_pending_sends_nothing() {
    let posts = 0;
    const flush = signOutGate({ isPending: async () => false, clear: async () => {}, post: async () => { posts++; return { ok: true }; } });
    await flush();
    assert.equal(posts, 0);
  },
  async gate_clears_only_after_the_server_answers() {
    const log = [];
    let pending = true;
    const flush = signOutGate({ isPending: async () => pending, clear: async () => { log.push("clear"); pending = false; }, post: async () => { log.push("post"); return { ok: true }; } });
    await flush();
    assert.deepEqual(log, ["post", "clear"]);
  },
  async gate_keeps_the_flag_when_the_request_fails() {
    let cleared = false;
    const flush = signOutGate({ isPending: async () => true, clear: async () => { cleared = true; }, post: async () => { throw new TypeError("no network"); } });
    await assert.rejects(flush());
    assert.equal(cleared, false);
  },
  async gate_keeps_the_flag_when_the_server_refuses() {
    let cleared = false;
    const flush = signOutGate({ isPending: async () => true, clear: async () => { cleared = true; }, post: async () => ({ ok: false, status: 500 }) });
    await assert.rejects(flush());
    assert.equal(cleared, false);
  },
  async gate_runs_one_request_at_a_time() {
    let posts = 0;
    let pending = true;
    const flush = signOutGate({ isPending: async () => pending, clear: async () => { pending = false; }, post: async () => { posts++; await new Promise((r) => setTimeout(r, 5)); return { ok: true }; } });
    await Promise.all([flush(), flush(), flush()]);
    assert.equal(posts, 1);
  },
  async gate_can_be_retried_after_a_failure() {
    let attempts = 0;
    let pending = true;
    const flush = signOutGate({ isPending: async () => pending, clear: async () => { pending = false; }, post: async () => { attempts++; if (attempts === 1) throw new TypeError("no network"); return { ok: true }; } });
    await assert.rejects(flush());
    await flush();
    assert.equal(pending, false);
  },
};

const results = {};
for (const [name, run] of Object.entries(cases)) {
  try { await run(); results[name] = "ok"; } catch (err) { results[name] = String(err && err.stack || err); }
}
process.stdout.write(JSON.stringify(results));
