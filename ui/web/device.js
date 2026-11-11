// What the device keeps, in IndexedDB (add-web-application, Stage 4). Nothing about a client except
// what the worker typed in their own queued notes, and those only as sealed envelopes.
//   meta:  the worker's own profile, so the app can open offline [TBC with Goodwill]; the setup (the
//          server's public key, the SSN rules, the limits, and a contact stamp); and a flag to finish
//          a sign-out when the connection returns; and when the next upload may be tried (times only).
//   queue: sealed notes and their clear metadata (queue.js).
// Changes to this database are additive only, so a new version can always read what an older one saved.

const NAME = "outreach-device";
const VERSION = 2;

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta");
      if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", { keyPath: "id" });
    };
    request.onsuccess = () => {
      request.result.onversionchange = () => request.result.close();
      resolve(request.result);
    };
    request.onerror = () => reject(request.error);
  });
}

async function withStores(names, mode, work) {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(names, mode);
      const request = work(tx);
      tx.oncomplete = () => resolve(request ? request.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

const withMeta = (mode, work) => withStores("meta", mode, (tx) => work(tx.objectStore("meta")));
const withQueue = (mode, work) => withStores("queue", mode, (tx) => work(tx.objectStore("queue")));

export const getMeta = (key) => withMeta("readonly", (store) => store.get(key));
export const setMeta = (key, value) => withMeta("readwrite", (store) => store.put(value, key));
export const deleteMeta = (key) => withMeta("readwrite", (store) => store.delete(key));

export function saveProfile(user) {
  return setMeta("profile", { username: user.username, display_name: user.display_name, role: user.role, last_contact_at: Date.now() });
}
export const getProfile = () => getMeta("profile");
export const clearProfile = () => deleteMeta("profile");

export const queueStore = {
  all: () => withQueue("readonly", (store) => store.getAll()),
  get: (id) => withQueue("readonly", (store) => store.get(id)),
  put: (row) => withQueue("readwrite", (store) => store.put(row)),
  remove: (id) => withQueue("readwrite", (store) => store.delete(id)),
};

// Sign-out: in one transaction, delete this user's notes and notices, the public key and rules, and
// the profile, and set the flag that ends the server's session at the next connection. Another
// account's envelopes stay until their owner signs in or they expire.
export function wipeUser(owner) {
  return withStores(["meta", "queue"], "readwrite", (tx) => {
    const meta = tx.objectStore("meta");
    meta.delete("profile");
    meta.delete("setup");
    meta.delete("upload_backoff");
    meta.put(true, "pending_sign_out");
    tx.objectStore("queue").openCursor().onsuccess = (event) => {
      const cursor = event.target.result;
      if (!cursor) return;
      if (cursor.value.owner === owner) cursor.delete();
      cursor.continue();
    };
  });
}
