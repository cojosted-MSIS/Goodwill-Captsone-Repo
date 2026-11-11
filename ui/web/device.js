// What the device keeps, in IndexedDB (add-web-application, Stage 4). For now only the worker's own
// profile (username, display name, role, last contact), so the app can open offline, and a flag to
// finish a sign-out when the connection returns. Nothing about a client. Changes to this database
// are additive only, so a new version can always read what an older one saved.

const NAME = "outreach-device";
const VERSION = 1;

function open() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("meta")) request.result.createObjectStore("meta");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withMeta(mode, work) {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("meta", mode);
      const request = work(tx.objectStore("meta"));
      tx.oncomplete = () => resolve(request ? request.result : undefined);
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

export const getMeta = (key) => withMeta("readonly", (store) => store.get(key));
export const setMeta = (key, value) => withMeta("readwrite", (store) => store.put(value, key));
export const deleteMeta = (key) => withMeta("readwrite", (store) => store.delete(key));

export function saveProfile(user) {
  return setMeta("profile", { username: user.username, display_name: user.display_name, role: user.role, last_contact_at: Date.now() });
}
export const getProfile = () => getMeta("profile");
export const clearProfile = () => deleteMeta("profile");
