"""The staging store is shared by the API's worker threads (the staff audit screen loads two
routes at once). Every read must see the saved draft, whatever runs beside it."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from app.drafts import Draft
from app.storage import Store

NOW = datetime(2026, 10, 9, 18, 0, tzinfo=timezone.utc)


def draft(i: int) -> Draft:
    return Draft(id=f"ENC-2026-10-09-{i:04d}", author="j.alvarez@goodwill-outreach.example", worker_id="j.alvarez",
                 subject="New client", state="in_review", email_sent_at=NOW, encounter_date=date(2026, 10, 9),
                 created_at=NOW, parser="rule_stub", prompt_version="stub-1", parsed_at=NOW)


def hammer(store: Store, rounds: int = 300) -> list[str]:
    for i in range(20):
        store.save_draft(draft(i))
        store.audit(draft(i).id, "draft_created", NOW, version=1)
    missing: list[str] = []

    def read(n: int) -> None:
        d = draft(n % 20)
        if store.get_draft(d.id) is None:
            missing.append(d.id)
        store.audit_events(d.id)
        store.emails(ref=d.id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(read, range(rounds)))
    return missing


def test_parallel_reads_always_find_the_draft():
    assert hammer(Store(), rounds=2000) == []
