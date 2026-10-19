"""
REALLMS capability probe. Run this before building the extraction pipeline.

Uses SYNTHETIC text only. Do not paste real neighbor information into it.

Setup:
    pip install requests
    export LLM_BASE_URL="https://<host>/api"      # confirm exact base path with the professor / IU
    export LLM_API_KEY="..."
    export LLM_MODEL="<model name from the model list>"   # optional; script lists models first

Assumes an OpenAI-compatible API (likely for Open WebUI / vLLM, but UNVERIFIED for IU's deployment).
If a step fails, record the error: it is evidence about what the service supports.
"""
import json
import os
import sys
import time

import requests

BASE = os.environ.get("LLM_BASE_URL", "").rstrip("/")
KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "")
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

# Synthetic note, written to look like a post-shift worker note. Not real.
NOTE = (
    "Met Sam at the laundromat on Tuesday around 2. Said he slept outside "
    "last night. DOB he gave is 3/14/78 but could be 3/16. Wants help getting "
    "an ID. Agreed to meet at the day center Thursday."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "contact_date_phrase": {"type": "string"},
        "living_situation": {
            "type": "string",
            "enum": ["unsheltered", "sheltered", "housed", "unknown"],
        },
        "living_situation_quote": {"type": "string"},
        "dob_uncertain": {"type": "boolean"},
    },
    "required": ["living_situation", "living_situation_quote", "dob_uncertain"],
    "additionalProperties": False,
}

PROMPT = (
    "Extract fields from this outreach note. Return JSON only. "
    "living_situation_quote must be copied exactly from the note.\n\nNOTE: " + NOTE
)


def step(name):
    print(f"\n=== {name} ===")


def post(payload):
    t0 = time.time()
    r = requests.post(f"{BASE}/chat/completions", headers=HEADERS, json=payload, timeout=120)
    return r, time.time() - t0


def main():
    if not BASE or not KEY:
        sys.exit("Set LLM_BASE_URL and LLM_API_KEY first.")
    global MODEL

    step("1. List models")
    r = requests.get(f"{BASE}/models", headers=HEADERS, timeout=30)
    print(r.status_code)
    try:
        ids = [m.get("id") for m in r.json().get("data", [])]
        print("\n".join(ids) or r.text[:500])
        if not MODEL and ids:
            MODEL = ids[0]
            print(f"(using first model: {MODEL})")
    except Exception:
        print(r.text[:500])

    step("2. Plain completion + latency")
    r, dt = post({"model": MODEL, "messages": [{"role": "user", "content": "Reply with the word ok."}]})
    print(r.status_code, f"{dt:.1f}s")
    print(r.text[:300])

    step("3. Schema enforcement: OpenAI-style response_format")
    r, dt = post({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "extract", "schema": SCHEMA, "strict": True}},
        "temperature": 0,
    })
    print(r.status_code, f"{dt:.1f}s")
    print(r.text[:600])

    step("4. Schema enforcement: vLLM-style guided_json")
    r, dt = post({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "guided_json": SCHEMA,
        "temperature": 0,
    })
    print(r.status_code, f"{dt:.1f}s")
    print(r.text[:600])

    step("5. No enforcement: prompt-only JSON, validated by us")
    ok = 0
    runs = 5
    for i in range(runs):
        r, dt = post({"model": MODEL, "messages": [{"role": "user", "content": PROMPT}], "temperature": 0})
        try:
            text = r.json()["choices"][0]["message"]["content"]
            start, end = text.find("{"), text.rfind("}") + 1
            obj = json.loads(text[start:end])
            quote_ok = obj.get("living_situation_quote", "") in NOTE
            enum_ok = obj.get("living_situation") in SCHEMA["properties"]["living_situation"]["enum"]
            ok += quote_ok and enum_ok
            print(f"run {i+1}: parsed, quote_in_note={quote_ok}, enum_ok={enum_ok}, {dt:.1f}s")
        except Exception as e:
            print(f"run {i+1}: FAILED to parse ({e})")
    print(f"{ok}/{runs} fully valid")

    print("\nRecord for the team: model name, which steps passed, latency, any rate-limit headers or errors.")


if __name__ == "__main__":
    main()
