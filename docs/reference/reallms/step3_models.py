"""
Step 3 (response_format json_schema) on every chat model, repeated, with validation.

Reuses NOTE, SCHEMA, PROMPT and the env vars from reallms_probe.py (keep both files
in the same folder). Synthetic text only.

    python step3_models.py
"""
import json
import time

import requests

from reallms_probe import BASE, HEADERS, KEY, NOTE, PROMPT, SCHEMA

MODELS = ["gemma-4-31B-it", "gpt-oss-120b", "qwen3.8-27b"]
RUNS = 5

EXPECTED = {"living_situation": "unsheltered", "dob_uncertain": True}


def check(obj):
    """Return a list of problems with one parsed reply (empty list = valid)."""
    problems = []
    props = SCHEMA["properties"]
    extra = set(obj) - set(props)
    if extra:
        problems.append(f"extra keys {sorted(extra)}")
    for k in SCHEMA["required"]:
        if k not in obj:
            problems.append(f"missing {k}")
    if "living_situation" in obj and obj["living_situation"] not in props["living_situation"]["enum"]:
        problems.append(f"bad enum {obj['living_situation']!r}")
    if "dob_uncertain" in obj and not isinstance(obj["dob_uncertain"], bool):
        problems.append("dob_uncertain not bool")
    q = obj.get("living_situation_quote", "")
    if not isinstance(q, str) or not q.strip() or q not in NOTE:
        problems.append(f"quote not in note {q!r}")
    return problems


def run_once(model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "extract", "schema": SCHEMA, "strict": True}},
        "temperature": 0,
    }
    t0 = time.time()
    r = requests.post(f"{BASE}/chat/completions", headers=HEADERS, json=payload, timeout=180)
    dt = time.time() - t0
    if r.status_code != 200:
        return dt, None, [f"HTTP {r.status_code}: {r.text[:200]}"], None
    choice = r.json()["choices"][0]
    tokens = r.json().get("usage", {}).get("completion_tokens")
    if choice.get("finish_reason") != "stop":
        return dt, None, [f"finish_reason={choice.get('finish_reason')}"], tokens
    content = choice["message"].get("content") or ""
    try:
        obj = json.loads(content)  # strict parse: no fence stripping, so formatting drift shows up
    except json.JSONDecodeError:
        return dt, None, [f"not raw JSON: {content[:80]!r}"], tokens
    return dt, obj, check(obj), tokens


def main():
    if not BASE or not KEY:
        raise SystemExit("Set LLM_BASE_URL and LLM_API_KEY first.")
    summary = []
    for model in MODELS:
        print(f"\n=== {model} ===")
        valid = correct = 0
        times, toks = [], []
        outputs = set()
        for i in range(RUNS):
            dt, obj, problems, tokens = run_once(model)
            times.append(dt)
            if tokens:
                toks.append(tokens)
            if obj is not None:
                outputs.add(json.dumps(obj, sort_keys=True))
            if not problems:
                valid += 1
                if all(obj.get(k) == v for k, v in EXPECTED.items()):
                    correct += 1
            status = "valid" if not problems else "; ".join(problems)
            print(f"run {i+1}: {dt:.1f}s  tokens={tokens}  {status}")
            if obj is not None and i == 0:
                print("  " + json.dumps(obj))
        avg_t = sum(times) / len(times)
        avg_k = round(sum(toks) / len(toks)) if toks else None
        summary.append((model, valid, correct, len(outputs), avg_t, avg_k))

    print("\n=== Summary ===")
    print(f"{'model':<18}{'valid':>7}{'correct':>9}{'distinct':>10}{'avg s':>8}{'avg tok':>9}")
    for model, valid, correct, distinct, avg_t, avg_k in summary:
        print(f"{model:<18}{valid:>4}/{RUNS}{correct:>6}/{RUNS}{distinct:>10}{avg_t:>8.1f}{str(avg_k):>9}")
    print("\nvalid = matches schema + quote copied from note; correct = also unsheltered + dob_uncertain=true;")
    print("distinct = number of different outputs across runs (1 = fully consistent).")


if __name__ == "__main__":
    main()
