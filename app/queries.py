"""Read-only HMIS queries by email (add-hmis-readonly-queries): validation, replies, audit.

A "Query:" email from an authorized worker is read by the parser into one of four fixed
query types with parameters. This module checks every parameter, runs the matching fixed
read through app/hmis_reader.py, and writes a minimal reply: never a Social Security
number, a date of birth (even one the worker gave), case note text, a full last name, a
location below the quadrant, or anything about another person. A query never changes
anything except its own email copies and audit record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from parser.interface import QueryRequest

from .config_loader import AppConfig
from .dates import parse_written_date
from .hmis_reader import HmisReader, Neighbor, StatusRow, Watchlist

QUADRANT_LABELS = {"nw": "NW", "ne": "NE", "sw": "SW", "se": "SE"}
DOC_LABELS = {"state_id": "State ID", "birth_certificate": "Birth certificate"}  # [TBC with Horizon House]
STATUS_LABELS = {"requested": "requested", "received": "received", "scheduled": "scheduled", "completed": "completed"}

WHAT_I_CAN_ANSWER = (
    "I can answer four kinds of question:\n"
    "  - Briefing: who has been reported in a quadrant, for example \"Who has been reported in the SW quadrant?\"\n"
    "  - Lookup: a neighbor by name and date of birth, or by HMIS client ID, for example "
    "\"Look up Pat Example, DOB 3/4/1975\"\n"
    "  - Status: whether an ID document or a housing assessment has come in for one neighbor, for example "
    "\"Has Jordan Sample's ID come in? DOB 6/12/1979\"\n"
    "  - No-contact watchlist: who is coming up on {days} days with no contact, optionally in one quadrant, "
    "for example \"Who is coming up on {days} days with no contact in the SE quadrant?\""
)


@dataclass
class CheckedQuery:
    """A query whose parameters passed every check, or the list of what is missing."""

    query_type: str | None
    quadrant: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    client_id: str | None = None
    status_type: str | None = None
    missing: list[str] = field(default_factory=list)  # plain-words requests to the worker
    refused: str | None = None  # why nothing ran, as an audit code

    @property
    def ok(self) -> bool:
        return self.refused is None and not self.missing


def check(request: QueryRequest, config: AppConfig, reference: date) -> CheckedQuery:
    """Validate every parameter. Nothing runs unless this passes."""
    s = config.settings.hmis_queries
    q = CheckedQuery(query_type=request.query_type)
    if request.query_type is None:
        q.refused = "no_query_type"
        return q
    if request.query_type == "no_contact":
        # Only an optional quadrant is read. Names, IDs, dates, and any number of days are ignored:
        # the limits are config values.
        q.quadrant = request.quadrant if request.quadrant in QUADRANT_LABELS else None
        return q

    if request.client_id:
        cid = request.client_id.strip().upper()
        if re.fullmatch(s.client_id_pattern, cid):
            q.client_id = cid
        else:
            q.missing.append("the client ID in the HMIS format (for example HMIS-C-000101); the one given does not match")
    if request.date_of_birth_as_written:
        q.date_of_birth = parse_written_date(request.date_of_birth_as_written, reference)
        if q.date_of_birth is None:
            q.missing.append("the full date of birth (month, day, and year)")
    q.first_name, q.last_name = (request.first_name or None), (request.last_name or None)

    if request.query_type == "briefing":
        if request.quadrant in QUADRANT_LABELS:
            q.quadrant = request.quadrant
        else:
            q.missing.append("the quadrant: NW, NE, SW, or SE")
    else:
        identified = q.client_id or (q.first_name and q.last_name and q.date_of_birth)
        if not identified and not q.missing:
            if q.first_name and q.last_name:
                q.missing.append("the date of birth or the HMIS client ID (I never search by name alone)")
            else:
                q.missing.append("the neighbor's first and last name with the date of birth, or the HMIS client ID")
        if request.query_type == "status":
            if request.status_type in s.status_types:
                q.status_type = request.status_type
            else:
                q.missing.append("what to check: " + " or ".join(label.lower() for label in s.status_types.values()))
    if q.missing:
        q.refused = "missing_parameters"
    return q


def audit_details(q: CheckedQuery, rows: int | None) -> dict:
    """What the audit keeps: client ID, quadrant, and status type in full; a name or date of birth only as "given"."""
    return {
        "query_type": q.query_type,
        "client_id": q.client_id,
        "quadrant": q.quadrant,
        "status_type": q.status_type,
        "name": "given" if (q.first_name or q.last_name) else None,
        "date_of_birth": "given" if q.date_of_birth else None,
        "rows": rows,
        "refused": q.refused,
    }


def _day(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%m/%d/%Y") if iso else "not recorded"


def _who(n: Neighbor) -> str:
    return f"{n.client_id}  {n.first_name} {n.last_initial}."


def _watchlist(q: CheckedQuery, reader: HmisReader, config: AppConfig, project: str, today: date) -> tuple[str, int]:
    s = config.settings.hmis_queries
    days, warn = s.no_contact_days, s.no_contact_warning_days
    w: Watchlist = reader.no_contact(today - timedelta(days=days - warn), today - timedelta(days=days), q.quadrant, project)
    where = f" in the {QUADRANT_LABELS[q.quadrant]} quadrant" if q.quadrant else ""
    lines = [f"No-contact watchlist{where} ({days} days, active enrollments only): "
             f"{w.past} past {days} days, {w.approaching} approaching."]
    if not w.neighbors:
        lines.append(f"\nNo neighbor with an active enrollment{where} has gone {days - warn} days or more without a contact.")

    def line(n: Neighbor) -> str:
        since = (today - date.fromisoformat(n.last_contact)).days
        quad = f"{QUADRANT_LABELS[n.quadrant]} quadrant" if n.quadrant in QUADRANT_LABELS else "quadrant not recorded"
        items = f"  open: {'; '.join(n.open_items)}" if n.open_items else ""
        return f"  - {_who(n)}  last contact {_day(n.last_contact)}, {since} days ago, {quad}{items}"

    past = [n for n in w.neighbors if (today - date.fromisoformat(n.last_contact)).days > days]
    approaching = [n for n in w.neighbors if n not in past]
    if w.past:
        lines += ["", f"PAST {days} DAYS ({w.past})", *map(line, past)]
    if w.approaching:
        lines += ["", f"APPROACHING {days} DAYS: {days - warn} to {days} days ({w.approaching})", *map(line, approaching)]
    total = w.past + w.approaching
    if total > len(w.neighbors):
        lines.append(f"\n{total - len(w.neighbors)} more were not shown (limit {reader.row_limit}). "
                     "Please narrow the question, for example to one quadrant.")
    lines.append("\nA contact is any contact recorded in HMIS, including services entered through this system "
                 "[TBC with Horizon House: what counts as a contact].")
    return "\n".join(lines), len(w.neighbors)


def answer(q: CheckedQuery, reader: HmisReader, config: AppConfig, project: str, today: date) -> tuple[str, int]:
    """Run the fixed read for a checked query. Returns the reply body and the number of rows returned."""
    s = config.settings.hmis_queries
    limit = reader.row_limit
    if q.query_type == "no_contact":
        return _watchlist(q, reader, config, project, today)
    if q.query_type == "briefing":
        window = s.briefing_window_days
        b = reader.briefing(q.quadrant, today - timedelta(days=window), today, project)
        quad = QUADRANT_LABELS[q.quadrant]
        lines = [f"Pre-visit briefing for the {quad} quadrant (last {window} days): "
                 f"{b.total} neighbor{'s' if b.total != 1 else ''} reported."]
        for n in b.neighbors:
            items = f"  open: {'; '.join(n.open_items)}" if n.open_items else ""
            lines.append(f"  - {_who(n)}  last contact {_day(n.last_contact)}{items}")
        if b.total > len(b.neighbors):
            lines.append(f"\n{b.total - len(b.neighbors)} more were not shown (limit {limit}). "
                         "Please narrow the question.")
        return "\n".join(lines), len(b.neighbors)

    neighbors = (reader.lookup_by_id(q.client_id, project) if q.client_id
                 else reader.lookup_by_name(q.first_name, q.last_name, q.date_of_birth, project))
    if q.query_type == "lookup":
        if not neighbors:
            return "No neighbor was found. (I do not suggest similar names or dates.)", 0
        lines = [f"Neighbor lookup: {len(neighbors)} found."]
        for n in neighbors:
            where = f" in the {QUADRANT_LABELS[n.quadrant]} quadrant" if n.quadrant else ""
            lines.append(f"  - {_who(n)}  last contact {_day(n.last_contact)}{where}")
        if len(neighbors) > 1:
            lines.append("\nMore than one neighbor matches. Tell them apart by client ID, quadrant, and last contact.")
        return "\n".join(lines), len(neighbors)

    # status
    label = s.status_types[q.status_type]
    if not neighbors:
        return "No neighbor was found, so no status can be given. (I do not suggest similar names or dates.)", 0
    if len(neighbors) > 1:
        lines = [f"{len(neighbors)} neighbors match, so I did not answer. Please ask again with the client ID:"]
        lines += [f"  - {_who(n)}  last contact {_day(n.last_contact)}" for n in neighbors]
        return "\n".join(lines), len(neighbors)
    n = neighbors[0]
    rows: list[StatusRow] = reader.status(n.client_id, q.status_type, project)
    lines = [f"{label} status for {_who(n)}:"]
    if not rows:
        lines.append(f"  No {label.lower()} recorded.")
    for r in rows:
        kind = DOC_LABELS.get(r.kind, label) if q.status_type == "id_document" else label
        lines.append(f"  - {kind}: {STATUS_LABELS.get(r.status, r.status)} {_day(r.status_date)}")
    return "\n".join(lines), len(rows)


def needs_more(q: CheckedQuery, config: AppConfig) -> str:
    if q.refused == "no_query_type":
        kinds = WHAT_I_CAN_ANSWER.format(days=config.settings.hmis_queries.no_contact_days)
        return f"I could not match your question to a query I can run, so no query was run.\n\n{kinds}"
    return ("No query was run. To answer, I need:\n" + "\n".join(f"  - {m}" for m in q.missing)
            + "\n\nPlease ask again with that.")
