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

// What an upload's answer means for the note. A status of 0 means the server could not be reached.
export function classify({ status, data }) {
  if (status >= 200 && status < 300) return { kind: "uploaded", ref: data.ref, action: data.action };
  if (status === 401) return { kind: "signin" };
  if (status === 0 || status === 403 || status === 408 || status === 429 || status >= 500) return { kind: "wait" };
  const detail = data && data.detail;
  const reason = detail && typeof detail.message === "string" ? detail.message : typeof detail === "string" ? detail : GENERIC_REASON;
  return { kind: "attention", reason };
}

// May a note be saved now? Only for so long after this device last reached the server.
export function writeAllowed(setup, now) {
  return Boolean(setup) && now - setup.received_at <= setup.limits.offline_write_hours * HOUR;
}

export function createQueue({ store, now, limits, upload }) {
  const running = new Set();
  const age = (row) => now() - Date.parse(row.saved_at);

  async function save({ id, owner, kind, savedAt, envelope }) {
    const row = { id, owner, kind, idempotency_key: id, saved_at: savedAt, status: "saved", retries: 0, reason: null, envelope };
    await store.put(row);
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
      hours_left: Math.max(0, Math.ceil((limits.queue_expiry_hours * HOUR - age(row)) / HOUR)), reason: row.reason ?? null, ref: row.ref ?? null };
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
      const answer = await upload(row);
      if (answer.kind === "uploaded") {
        await store.put({ id: row.id, owner: row.owner, kind: row.kind, saved_at: row.saved_at, status: "uploaded", ref: answer.ref });
      } else if (answer.kind === "attention") {
        await store.put({ ...row, status: "attention", reason: answer.reason });
      } else {
        await store.put({ ...row, status: "saved", retries: row.retries + 1 });
      }
      return answer;
    } finally {
      running.delete(row.id);
    }
  }

  async function uploadAll(owner) {
    const waiting = (await store.all()).filter((r) => r.owner === owner && r.status === "saved").sort((a, b) => (a.saved_at < b.saved_at ? -1 : 1));
    for (const row of waiting) {
      const answer = await uploadOne(row);
      if (answer.kind === "signin") return { signIn: true };
      if (answer.kind === "wait") return { waiting: true };
    }
    return {};
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

  return { save, recover, sweep, view, uploadAll, dismiss, opened };
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
