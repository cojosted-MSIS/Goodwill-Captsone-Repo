"""Add a new sealing key to .env: python scripts/make_seal_key.py

Makes an RSA key for the offline queue (app/sealing.py) and puts it first in
INTAKE_SEAL_PRIVATE_KEYS in .env, keeping any older keys after it so queued notes can still be
opened. Prints only the new key's ID, never a key. .env is git-ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.sealing import SEAL_KEYS_ENV, Sealer, new_private_key  # noqa: E402


def add_key(env_file: Path) -> str:
    key = new_private_key()
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    prefix = f"{SEAL_KEYS_ENV}="
    older = next((line[len(prefix):].strip() for line in lines if line.startswith(prefix)), "")
    kept = [line for line in lines if not line.startswith(prefix)]
    kept.append(prefix + (f"{key},{older}" if older else key))
    env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return Sealer([key]).current()["key_id"]


if __name__ == "__main__":
    print(f"Added a sealing key to .env. Key ID: {add_key(ROOT / '.env')}")
