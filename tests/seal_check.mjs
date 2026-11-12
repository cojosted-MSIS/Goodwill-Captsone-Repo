// Seals notes with ui/web/seal.js and real WebCrypto, for tests/test_sealing.py.
// A plan comes in on stdin: {module, key: {public_key, key_id}, notes: [{note, owner, idempotencyKey, kind, savedAt}]}.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const plan = JSON.parse(readFileSync(0, "utf8"));
const { seal, verifyKey } = await import(pathToFileURL(plan.module).href);
const sealed = [];
for (const n of plan.notes) {
  sealed.push(await seal(n.note, { publicKey: plan.key.public_key, keyId: plan.key.key_id, owner: n.owner, idempotencyKey: n.idempotencyKey, kind: n.kind, savedAt: n.savedAt }));
}
process.stdout.write(JSON.stringify({
  sealed,
  verified: await verifyKey(plan.key.public_key, plan.key.key_id),
  wrong_id_verified: await verifyKey(plan.key.public_key, "0".repeat(64)),
}));
