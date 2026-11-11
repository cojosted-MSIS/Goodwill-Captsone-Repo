// Seal a note so that this device can write it but never read it back (add-web-application, Stage 4c).
//
// A new random AES-GCM 256-bit key for each note, used once and dropped; it leaves this function
// only wrapped with the server's RSA-OAEP public key. The user ID, the Idempotency-Key, the kind,
// the time saved, the format version, and the key ID are associated data, so an envelope cannot be
// moved to another user or replayed under another key. app/sealing.py opens it.

const FORMAT_VERSION = 1;
const utf8 = new TextEncoder();

const fromB64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
function toB64(bytes) {
  let text = "";
  for (const b of new Uint8Array(bytes)) text += String.fromCharCode(b);
  return btoa(text);
}
const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");

// The page trusts this key because it came from its own origin over HTTPS while signed in. This
// check makes sure one key ID can never name two keys.
export async function verifyKey(publicKey, keyId) {
  return hex(await crypto.subtle.digest("SHA-256", fromB64(publicKey))) === keyId;
}

function associatedData({ keyId, owner, idempotencyKey, kind, savedAt }) {
  return utf8.encode(JSON.stringify(["outreach-note", FORMAT_VERSION, keyId, owner, idempotencyKey, kind, savedAt]));
}

export async function seal(note, { publicKey, keyId, owner, idempotencyKey, kind, savedAt }) {
  const rsa = await crypto.subtle.importKey("spki", fromB64(publicKey), { name: "RSA-OAEP", hash: "SHA-256" }, false, ["wrapKey"]);
  const aes = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt"]);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce, additionalData: associatedData({ keyId, owner, idempotencyKey, kind, savedAt }) },
    aes, utf8.encode(JSON.stringify(note)));
  const wrapped = await crypto.subtle.wrapKey("raw", aes, rsa, { name: "RSA-OAEP" });
  return { v: FORMAT_VERSION, key_id: keyId, wrapped_key: toB64(wrapped), nonce: toB64(nonce), ciphertext: toB64(ciphertext) };
}
