// The device queue's rules (add-web-application, Stage 4c). The store, the clock, and the upload are
// passed in, so the same code runs in the browser and in the tests.
//
// A record holds a sealed envelope and clear metadata only: owner, kind, Idempotency-Key, time saved,
// status, retry count, and a plain reason. The device cannot read a note back. The Idempotency-Key
// is made when the note is saved and never changes.

export const STATUS_LABELS = { saved: "Saved on device", uploading: "Uploading", uploaded: "Uploaded", attention: "Needs attention" };

const HOUR = 3600 * 1000;
const UNSENT = new Set(["saved", "uploading", "attention"]);
const GENERIC_REASON = "The server could not accept this note.";
const CONFLICT_REASON = "The server already has a different note filed under this one, so this note was not added.";
// Refusals whose cause can change, so trying again can help. The same envelope is sent each time: a
// note refused for its content or its age would only be refused again.
const CAN_RETRY = new Set(["sealed_unreadable", "sealed_unknown_key", "sealed_bad_time"]);
const RETRY_AFTER_CAP = HOUR;  // a long or broken header must not strand a note near its 72 hours

// How long a Retry-After header asks for, in milliseconds: seconds, or an HTTP date.
export function parseRetryAfter(value, now) {
  if (!value) return 0;
  const ms = /^\d+$/.test(value.trim()) ? Number(value) * 1000 : Date.parse(value) - now;
  return Number.isNaN(ms) || ms <= 0 ? 0 : Math.min(ms, RETRY_AFTER_CAP);
}

// What an upload's answer means for the note. A status of 0 means the server could not be reached.
// A reason shown to the worker is only ever a fixed message the server tagged with a code.
export function classify({ status, data, retryAfterMs = 0 }) {
  if (status >= 200 && status < 300) return { kind: "uploaded", ref: data.ref, action: data.action };
  if (status === 401) return { kind: "signin" };
  if (status === 0 || status === 403 || status === 408 || status === 429 || status >= 500 || (status === 409 && retryAfterMs)) {
    return retryAfterMs ? { kind: "wait", retryAfterMs } : { kind: "wait" };
  }
  if (status === 409) return { kind: "attention", reason: CONFLICT_REASON, can_retry: false };
  const detail = data && data.detail;
  if (detail && typeof detail.code === "string" && typeof detail.message === "string") {
    return { kind: "attention", reason: detail.message, can_retry: CAN_RETRY.has(detail.code) };
  }
  return { kind: "attention", reason: GENERIC_REASON, can_retry: false };
}

// May a note be saved now? Only for so long after this device last reached the server.
export function writeAllowed(setup, now) {
  return Boolean(setup) && now - setup.received_at <= setup.limits.offline_write_hours * HOUR;
}

export function createQueue({ store, now, limits, upload, onChange = () => {} }) {
  const running = new Set();
  const age = (row) => now() - Date.parse(row.saved_at);

  async function save({ id, owner, kind, savedAt, envelope }) {
    const row = { id, owner, kind, idempotency_key: id, saved_at: savedAt, status: "saved", retries: 0, reason: null, envelope };
    await store.put(row);
    onChange();
    return row;
  }

  // After a crash or a closed tab, nothing is really uploading.
  async function recover() {
    for (const row of await store.all()) {
      if (row.status === "uploading" && !running.has(row.id)) await store.put({ ...row, status: "saved" });
    }
  }

  // At 72 hours the envelope is deleted and a notice with no content stays until it is dismissed.
  async function sweep() {
    const limit = limits.queue_expiry_hours * HOUR;
    for (const row of await store.all()) {
      if (row.status === "expired" || running.has(row.id) || age(row) < limit) continue;
      if (row.status === "uploaded") await store.remove(row.id);
      else await store.put({ id: row.id, owner: row.owner, saved_at: row.saved_at, status: "expired" });
    }
  }

  function shown(row) {
    const warning = UNSENT.has(row.status) && age(row) >= limits.queue_warning_hours * HOUR;
    return { id: row.id, status: row.status, label: STATUS_LABELS[row.status], saved_at: row.saved_at, warning,
      hours_left: Math.max(0, Math.ceil((limits.queue_expiry_hours * HOUR - age(row)) / HOUR)), reason: row.reason ?? null, ref: row.ref ?? null,
      can_retry: Boolean(row.can_retry) };
  }

  async function view(owner) {
    const rows = await store.all();
    const own = rows.filter((r) => r.owner === owner);
    const notes = own.filter((r) => r.status !== "expired").sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1));
    return {
      mine: notes.map(shown),
      notices: own.filter((r) => r.status === "expired").map((r) => ({ id: r.id, saved_at: r.saved_at })),
      others: rows.filter((r) => r.owner !== owner && UNSENT.has(r.status)).length,  // a count only: no time, no kind
      unsent: notes.filter((r) => UNSENT.has(r.status)).length,
      uploadable: notes.filter((r) => r.status === "saved").length,
      uploading: notes.filter((r) => r.status === "uploading").length,
      needsAttention: notes.filter((r) => r.status === "attention").length,
      now: new Date(now()).toISOString(),
    };
  }

  // One upload per note at a time. Returns what happened, so the caller can ask the worker to sign in.
  async function uploadOne(row) {
    if (running.has(row.id)) return { kind: "busy" };
    running.add(row.id);
    try {
      await store.put({ ...row, status: "uploading" });
      onChange();
      const answer = await upload(row);
      if (answer.kind === "uploaded") {
        await store.put({ id: row.id, owner: row.owner, kind: row.kind, saved_at: row.saved_at, status: "uploaded", ref: answer.ref });
      } else if (answer.kind === "attention") {
        await store.put({ ...row, status: "attention", reason: answer.reason, can_retry: Boolean(answer.can_retry) });
      } else {
        await store.put({ ...row, status: "saved", retries: row.retries + 1 });
      }
      onChange();
      return answer;
    } finally {
      running.delete(row.id);
    }
  }

  // Oldest first, one at a time, until none are waiting, including any saved during the run.
  async function uploadAll(owner) {
    let uploaded = 0;
    for (;;) {
      const waiting = (await store.all()).filter((r) => r.owner === owner && r.status === "saved").sort((a, b) => (a.saved_at < b.saved_at ? -1 : 1));
      if (!waiting.length) return { uploaded };
      for (const row of waiting) {
        const answer = await uploadOne(row);
        if (answer.kind === "busy") return { uploaded };
        if (answer.kind === "signin") return { signIn: true, uploaded };
        if (answer.kind === "wait") return { waiting: true, retryAfterMs: answer.retryAfterMs || 0, uploaded };
        if (answer.kind === "uploaded") uploaded += 1;
      }
    }
  }

  // Needs attention: the device cannot read the note, so it cannot be edited. The worker can send the
  // same envelope again, where the cause can change, or delete it and write the note again.
  async function retry(id, owner) {
    const row = await store.get(id);
    if (!row || row.owner !== owner || row.status !== "attention" || !row.can_retry) return;
    const { can_retry: _gone, ...rest } = row;
    await store.put({ ...rest, status: "saved", reason: null, retries: 0 });
    onChange();
  }

  async function discard(id, owner) {
    const row = await store.get(id);
    if (row && row.owner === owner && row.status === "attention") await store.remove(id);
    onChange();
  }

  async function dismiss(id, owner) {
    const row = await store.get(id);
    if (row && row.owner === owner && row.status === "expired") await store.remove(id);
  }

  // The worker opened an uploaded note on the server: its row has done its job.
  async function opened(ref, owner) {
    for (const row of await store.all()) {
      if (row.owner === owner && row.status === "uploaded" && row.ref === ref) await store.remove(row.id);
    }
  }

  return { save, recover, sweep, view, uploadAll, retry, discard, dismiss, opened };
}

// When to upload. 5 seconds, doubling to 5 minutes, with jitter, shared between tabs through `memo`. A
// server's Retry-After is never cut short, even by the connection returning or the manual button.
const BACKOFF_FIRST = 5000;
const BACKOFF_CAP = 5 * 60 * 1000;
const FRESH = { failures: 0, next_at: 0, retry_until: 0 };
const SKIPS_BACKOFF = new Set(["online", "manual", "sign-in"]);

export function backoffDelay(failures, random) {
  const base = Math.min(BACKOFF_CAP, BACKOFF_FIRST * 2 ** (failures - 1));
  return Math.round(base * (0.5 + 0.5 * random()));
}

export function createSync({ attempt, now, random, memo, lock, isReady, schedule, cancel, onSignIn = () => {}, onDone = () => {} }) {
  let paused = false;
  let running = false;
  let timer = null;

  function arm(ms) {
    if (timer) cancel(timer);
    timer = schedule(() => { timer = null; return trigger("timer"); }, Math.max(0, ms));
  }

  // An attempt that could not finish: wait longer before the next one.
  async function failed({ retryAfterMs = 0 } = {}) {
    const before = await memo.get();
    const t = now();
    const failures = before.failures + 1;
    const next = { failures, next_at: t + backoffDelay(failures, random), retry_until: retryAfterMs ? t + retryAfterMs : before.retry_until };
    await memo.set(next);
    arm(Math.max(next.next_at, next.retry_until) - t);
  }

  async function trigger(reason = "tick") {
    if (paused) return { paused: true };
    if (!isReady()) return { notReady: true };
    if (running) return { busy: true };
    running = true;
    try {
      const m = await memo.get();
      const t = now();
      if (t < m.retry_until) { arm(m.retry_until - t); return { deferred: true }; }
      if (!SKIPS_BACKOFF.has(reason) && t < m.next_at) { arm(m.next_at - t); return { deferred: true }; }
      const out = await lock(attempt);
      if (out.busy) return out;
      if (out.signIn) {
        paused = true;
        if (timer) { cancel(timer); timer = null; }
        await memo.set({ ...FRESH });
        onSignIn();
      } else if (out.waiting) {
        await failed(out);
      } else if (m.failures || m.next_at || m.retry_until) {
        await memo.set({ ...FRESH });
      }
      onDone(out);
      return out;
    } finally {
      running = false;
    }
  }

  return { trigger, failed, resume: () => { paused = false; } };
}

// The connection check. While offline it slows down, to save battery and data.
const PING_FIRST = 20000;
const PING_CAP = 120000;
const PINGS_PER_MINUTE = 3;

export function pingDelay(checks, random) {
  return Math.round(Math.min(PING_CAP, PING_FIRST * 2 ** checks) * (0.75 + 0.25 * random()));
}

export function pingGate({ now }) {
  let recent = [];
  return { allow() {
    const t = now();
    recent = recent.filter((at) => t - at < 60000);
    if (recent.length >= PINGS_PER_MINUTE) return false;
    recent.push(t);
    return true;
  } };
}

// A sign-out made while offline must reach the server before any other request does. Every request
// awaits this first; the flag is cleared only after the server answers.
export function signOutGate({ isPending, clear, post }) {
  let running = null;
  async function run() {
    if (!(await isPending())) return;
    const res = await post();
    if (!res.ok) throw new Error("The sign-out was not finished.");
    await clear();
  }
  return function flush() {
    running ||= run().finally(() => { running = null; });
    return running;
  };
}
