// The device queue's logic, in Node with real WebCrypto, a fake clock, and an in-memory store, for
// tests/test_device_queue.py. Each case is a function; the results go out as JSON: {name: "ok" | error}.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const plan = JSON.parse(readFileSync(0, "utf8"));
const load = (name) => import(pathToFileURL(`${plan.web}/${name}`).href);
const { createQueue, createSync, classify, signOutGate, writeAllowed, backoffDelay, parseRetryAfter, pingDelay, pingGate, STATUS_LABELS } = await load("queue.js");
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

function syncHarness(attempts = []) {
  const h = { clock: { now: START }, timers: [], memo: { failures: 0, next_at: 0, retry_until: 0 }, ready: true, lockBusy: false, attempted: [], signIns: 0, random: 1 };
  h.make = () => createSync({
    attempt: async () => { h.attempted.push(h.clock.now); return attempts.length ? attempts.shift() : {}; },
    now: () => h.clock.now, random: () => h.random,
    memo: { get: async () => ({ ...h.memo }), set: async (v) => { h.memo = v; } },
    lock: async (work) => (h.lockBusy ? { busy: true } : work()), isReady: () => h.ready,
    schedule: (fn, ms) => { const t = { fn, at: h.clock.now + ms }; h.timers.push(t); return t; },
    cancel: (t) => { h.timers = h.timers.filter((x) => x !== t); },
    onSignIn: () => { h.signIns++; },
  });
  h.sync = h.make();
  h.advance = async (ms) => {
    h.clock.now += ms;
    for (const t of h.timers.filter((x) => x.at <= h.clock.now)) { h.timers = h.timers.filter((x) => x !== t); await t.fn(); }
  };
  return h;
}

const cases = {
  async sync_uploads_when_the_connection_returns() {
    const h = syncHarness();
    await h.sync.trigger("online");
    assert.equal(h.attempted.length, 1);
  },
  async sync_does_nothing_while_not_ready() {
    const h = syncHarness();
    h.ready = false;
    await h.sync.trigger("online");
    await h.sync.trigger("tick");
    assert.equal(h.attempted.length, 0);
    assert.equal(h.timers.length, 0);
  },
  async backoff_doubles_to_a_cap() {
    const delays = [1, 2, 3, 4, 5, 6, 7, 8, 12].map((n) => backoffDelay(n, () => 1));
    assert.deepEqual(delays, [5000, 10000, 20000, 40000, 80000, 160000, 300000, 300000, 300000]);
  },
  async backoff_has_jitter_and_never_passes_the_cap() {
    assert.equal(backoffDelay(1, () => 0), 2500);
    assert.equal(backoffDelay(20, () => 0), 150000);
    assert.equal(backoffDelay(20, () => 1), 300000);
    assert.notEqual(backoffDelay(3, () => 0.2), backoffDelay(3, () => 0.8));
  },
  async a_failure_waits_before_the_next_try() {
    const h = syncHarness([{ waiting: true }, { waiting: true }, {}]);
    await h.sync.trigger("open");
    assert.equal(h.attempted.length, 1);
    await h.sync.trigger("tick");
    assert.equal(h.attempted.length, 1, "a periodic check honors the backoff");
    await h.advance(4999);
    assert.equal(h.attempted.length, 1);
    await h.advance(1);
    assert.equal(h.attempted.length, 2);
    await h.advance(9999);
    assert.equal(h.attempted.length, 2);
    await h.advance(1);
    assert.equal(h.attempted.length, 3);
  },
  async success_clears_the_backoff() {
    const h = syncHarness([{ waiting: true }, {}]);
    await h.sync.trigger("open");
    await h.advance(5000);
    assert.deepEqual(h.memo, { failures: 0, next_at: 0, retry_until: 0 });
  },
  async the_connection_returning_skips_the_backoff() {
    const h = syncHarness([{ waiting: true }, {}]);
    await h.sync.trigger("open");
    await h.sync.trigger("online");
    assert.equal(h.attempted.length, 2);
  },
  async the_manual_button_skips_the_backoff() {
    const h = syncHarness([{ waiting: true }, {}]);
    await h.sync.trigger("open");
    await h.sync.trigger("manual");
    assert.equal(h.attempted.length, 2);
  },
  async retry_after_is_never_cut_short() {
    const h = syncHarness([{ waiting: true, retryAfterMs: 120000 }, {}]);
    await h.sync.trigger("open");
    for (const reason of ["online", "manual", "tick", "open", "sign-in"]) {
      const out = await h.sync.trigger(reason);
      assert.equal(out.deferred, true, reason);
    }
    assert.equal(h.attempted.length, 1);
    await h.advance(119999);
    assert.equal(h.attempted.length, 1);
    await h.advance(1);
    assert.equal(h.attempted.length, 2);
  },
  async a_long_retry_after_outlasts_the_backoff_cap() {
    const h = syncHarness([{ waiting: true, retryAfterMs: 900000 }, {}]);
    await h.sync.trigger("open");
    await h.advance(600000);
    assert.equal(h.attempted.length, 1);
  },
  async backoff_is_shared_between_tabs() {
    const h = syncHarness([{ waiting: true, retryAfterMs: 60000 }]);
    await h.sync.trigger("open");
    const other = h.make();
    const out = await other.trigger("online");
    assert.equal(out.deferred, true);
    assert.equal(h.attempted.length, 1);
  },
  async only_one_timer_at_a_time() {
    const h = syncHarness([{ waiting: true }]);
    await h.sync.trigger("open");
    await h.sync.trigger("tick");
    await h.sync.trigger("tick");
    assert.equal(h.timers.length, 1);
  },
  async another_tab_holding_the_lock_means_no_attempt() {
    const h = syncHarness();
    h.lockBusy = true;
    const out = await h.sync.trigger("online");
    assert.equal(out.busy, true);
    assert.equal(h.attempted.length, 0);
  },
  async no_second_run_inside_one_tab() {
    const h = syncHarness();
    await Promise.all([h.sync.trigger("online"), h.sync.trigger("online"), h.sync.trigger("online")]);
    assert.equal(h.attempted.length, 1);
  },
  async an_expired_session_stops_until_resumed() {
    const h = syncHarness([{ signIn: true }, {}]);
    await h.sync.trigger("online");
    assert.equal(h.signIns, 1);
    for (const reason of ["online", "tick", "manual"]) assert.equal((await h.sync.trigger(reason)).paused, true);
    assert.equal(h.attempted.length, 1);
    assert.equal(h.timers.length, 0);
    h.sync.resume();
    await h.sync.trigger("sign-in");
    assert.equal(h.attempted.length, 2);
  },
  async a_failed_direct_send_starts_the_backoff() {
    const h = syncHarness();
    await h.sync.failed({});
    assert.equal(h.memo.failures, 1);
    assert.equal(h.timers.length, 1);
    await h.advance(5000);
    assert.equal(h.attempted.length, 1);
  },
  async retry_after_in_seconds_or_a_date() {
    const now = Date.UTC(2026, 10, 11, 12, 0, 0);
    assert.equal(parseRetryAfter("7", now), 7000);
    assert.equal(parseRetryAfter(new Date(now + 30000).toUTCString(), now), 30000);
    assert.equal(parseRetryAfter(null, now), 0);
    assert.equal(parseRetryAfter("nonsense", now), 0);
    assert.equal(parseRetryAfter(new Date(now - 30000).toUTCString(), now), 0);
    assert.equal(parseRetryAfter("999999", now), 3600000, "a bad proxy cannot strand notes");
  },
  async classify_carries_retry_after() {
    assert.deepEqual(classify({ status: 429, data: {}, retryAfterMs: 7000 }), { kind: "wait", retryAfterMs: 7000 });
    assert.deepEqual(classify({ status: 503, data: {}, retryAfterMs: 1000 }), { kind: "wait", retryAfterMs: 1000 });
  },
  async a_conflict_still_running_waits() {
    assert.deepEqual(classify({ status: 409, data: { detail: "x" }, retryAfterMs: 2000 }), { kind: "wait", retryAfterMs: 2000 });
  },
  async a_real_conflict_needs_attention_in_plain_words() {
    const out = classify({ status: 409, data: { detail: "This Idempotency-Key was already used for a different request." } });
    assert.equal(out.kind, "attention");
    assert.equal(out.can_retry, false);
    assert.ok(!/idempotency/i.test(out.reason));
  },
  async only_reasons_with_a_code_are_shown() {
    const out = classify({ status: 400, data: { detail: "ZZECHO in a free string" } });
    assert.equal(out.kind, "attention");
    assert.ok(!out.reason.includes("ZZECHO"));
  },
  async try_again_is_offered_only_where_the_cause_can_change() {
    const retry = (code) => classify({ status: 422, data: { detail: { code, message: "m" } } }).can_retry;
    for (const code of ["sealed_unreadable", "sealed_unknown_key", "sealed_bad_time"]) assert.equal(retry(code), true, code);
    for (const code of ["sealed_offline_limit", "sealed_expired", "ssn_possible_full_number"]) assert.equal(retry(code), false, code);
  },
  async try_again_resends_the_same_envelope_and_key() {
    const h = harness([{ kind: "attention", reason: "r", can_retry: true }, { kind: "uploaded", ref: "ENC-1", action: "drafted" }]);
    const saved = await record(h);
    await h.queue.uploadAll("j.alvarez");
    assert.equal((await h.store.get(saved.id)).can_retry, true);
    await h.queue.retry(saved.id, "j.alvarez");
    const again = await h.store.get(saved.id);
    assert.equal(again.status, "saved");
    assert.equal(again.reason, null);
    await h.queue.uploadAll("j.alvarez");
    assert.equal(h.sent[1].idempotency_key, h.sent[0].idempotency_key);
    assert.deepEqual(h.sent[1].envelope, h.sent[0].envelope);
  },
  async try_again_is_refused_where_it_cannot_help() {
    const h = harness([{ kind: "attention", reason: "r", can_retry: false }]);
    const saved = await record(h);
    await h.queue.uploadAll("j.alvarez");
    await h.queue.retry(saved.id, "j.alvarez");
    assert.equal((await h.store.get(saved.id)).status, "attention");
  },
  async try_again_belongs_to_the_owner() {
    const h = harness([{ kind: "attention", reason: "r", can_retry: true }]);
    const saved = await record(h);
    await h.queue.uploadAll("j.alvarez");
    await h.queue.retry(saved.id, "m.chen");
    assert.equal((await h.store.get(saved.id)).status, "attention");
  },
  async delete_removes_a_refused_note() {
    const h = harness([{ kind: "attention", reason: "r", can_retry: false }]);
    const saved = await record(h);
    await h.queue.uploadAll("j.alvarez");
    await h.queue.discard(saved.id, "m.chen");
    assert.equal((await h.store.all()).length, 1, "only its owner");
    await h.queue.discard(saved.id, "j.alvarez");
    assert.equal((await h.store.all()).length, 0);
  },
  async delete_is_only_for_refused_notes() {
    const h = harness();
    const saved = await record(h);
    await h.queue.discard(saved.id, "j.alvarez");
    assert.equal((await h.store.all()).length, 1);
  },
  async wait_carries_retry_after_to_the_scheduler() {
    const h = harness([{ kind: "wait", retryAfterMs: 9000 }]);
    await record(h);
    const out = await h.queue.uploadAll("j.alvarez");
    assert.equal(out.waiting, true);
    assert.equal(out.retryAfterMs, 9000);
  },
  async a_note_added_during_a_run_is_picked_up() {
    const h = harness();
    await record(h);
    const q = createQueue({ store: h.store, now: () => h.clock.now, limits: LIMITS, upload: async (row) => {
      h.sent.push(row);
      if (h.sent.length === 1) await h.store.put({ ...row, id: "6f1c2a70-8b44-4f0e-9d13-bbbbbbbbbbbb", idempotency_key: "6f1c2a70-8b44-4f0e-9d13-bbbbbbbbbbbb", status: "saved" });
      return { kind: "uploaded", ref: `ENC-${h.sent.length}`, action: "drafted" };
    } });
    const out = await q.uploadAll("j.alvarez");
    assert.equal(h.sent.length, 2);
    assert.equal(out.uploaded, 2);
  },
  async progress_is_reported() {
    const h = harness();
    let changes = 0;
    const q = createQueue({ store: h.store, now: () => h.clock.now, limits: LIMITS, onChange: () => { changes++; }, upload: async () => ({ kind: "uploaded", ref: "ENC-1", action: "drafted" }) });
    await q.save({ id: "6f1c2a70-8b44-4f0e-9d13-cccccccccccc", owner: "j.alvarez", kind: "new_client", savedAt: new Date(START).toISOString(), envelope: { v: 1 } });
    await q.uploadAll("j.alvarez");
    assert.ok(changes >= 2);
  },
  async offline_checks_slow_down_to_a_cap() {
    const delays = [0, 1, 2, 3, 8].map((n) => pingDelay(n, () => 1));
    assert.deepEqual(delays, [20000, 40000, 80000, 120000, 120000]);
    assert.equal(pingDelay(0, () => 0), 15000);
  },
  async offline_checks_are_limited_per_minute() {
    let now = START;
    const gate = pingGate({ now: () => now });
    let allowed = 0;
    for (let i = 0; i < 60; i++) { if (gate.allow()) allowed++; now += 1000; }
    assert.equal(allowed, 3);
    now += 60000;
    assert.equal(gate.allow(), true);
  },
  async a_long_offline_stretch_stays_under_the_limit() {
    let t = 0, n = 0, checks = [];
    while (t < 600000) { t += pingDelay(n++, () => 0); checks.push(t); }
    for (const c of checks) assert.ok(checks.filter((x) => x > c - 60000 && x <= c).length <= 3);
  },
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
    assert.deepEqual(Object.keys(v.mine[0]).sort(), ["can_retry", "hours_left", "id", "label", "reason", "ref", "saved_at", "status", "warning"]);
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
    assert.deepEqual(refused, { kind: "attention", reason: "A fixed reason.", can_retry: false });
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
