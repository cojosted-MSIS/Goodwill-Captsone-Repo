"""Shared fixtures. All data here is synthetic."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config_loader import DEFAULT_CONFIG_DIR
from app.email_message import IntakeEmail, load_email_file
from app.hmis_gateway import HmisGateway
from mock_hmis.service import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_EMAIL_DIR = REPO_ROOT / "sample-data" / "emails"


@pytest.fixture(scope="session")
def sample_emails() -> dict[str, IntakeEmail]:
    """The synthetic worker emails, read in place and keyed by file stem."""
    return {path.stem: load_email_file(path) for path in sorted(SAMPLE_EMAIL_DIR.glob("*.txt"))}


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    """A writable copy of config/ for tests that change configuration."""
    target = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, target)
    return target


@pytest.fixture
def mock_hmis_app():
    return create_app()


@pytest.fixture
def hmis(mock_hmis_app) -> TestClient:
    """The mock HMIS service, in process."""
    with TestClient(mock_hmis_app) as client:
        yield client


@pytest.fixture
def gateway(hmis: TestClient) -> HmisGateway:
    return HmisGateway(hmis)


class FakeClock:
    def __init__(self, start=None):
        from datetime import datetime, timezone

        self.now = start or datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        from datetime import timedelta

        self.now += timedelta(**delta)


class Intake:
    """The workflow wired to the in-process mock HMIS and the stub parser, plus test helpers."""

    def __init__(self, hmis_client, gateway=None, parser=None):
        from app.config_loader import load_config
        from app.storage import Store
        from app.workflow import IntakeService
        from parser.rule_stub import RuleStubParser

        self.config = load_config()
        self.hmis = hmis_client
        self.clock = FakeClock()
        self.gateway = gateway or HmisGateway(hmis_client)
        self.service = IntakeService(self.config, Store(), parser or RuleStubParser(self.config), self.gateway, clock=self.clock)
        self.store = self.service.store

    def receive_sample(self, stem: str):
        return self.service.receive(load_email_file(SAMPLE_EMAIL_DIR / f"{stem}.txt"))

    def receive_text(self, body: str, *, sender="j.alvarez@goodwill-outreach.example", subject="New client 10/7"):
        from datetime import datetime, timedelta, timezone

        email = IntakeEmail(sender=sender, recipient="outreach-intake@goodwill-secure.example", subject=subject,
                            sent_at=datetime(2026, 10, 7, 10, 31, tzinfo=timezone(timedelta(hours=-4))), body=body)
        return self.service.receive(email)

    def draft(self, ref: str):
        return self.store.get_draft(ref)

    def last_email(self, ref: str, kind: str | None = None):
        sent = [e for e in self.store.emails(ref=ref) if e.direction == "out" and (kind is None or e.kind == kind)]
        return sent[-1] if sent else None

    def reply(self, ref: str, text: str, *, sender: str | None = None, version: int | None = None):
        from datetime import timedelta

        draft = self.store.get_draft(ref)
        author = draft.author if draft else self.store.get_pending(ref).author
        if draft:
            v = draft.version if version is None else version
            subject = f"Re: Please confirm: {draft.subject} [{ref} v{v}]"
        else:
            subject = f"Re: Please confirm HMIS search [{ref}]"
        self.clock.advance(minutes=5)
        email = IntakeEmail(sender=sender or author, recipient="outreach-intake@goodwill-secure.example",
                            subject=subject, sent_at=self.clock.now, body=f"{text}\n\n> earlier message quoted here")
        return self.service.receive(email)

    def fail_next(self, operation: str, mode: str, times: int | None = 1):
        assert self.hmis.post("/_admin/failures", json={"operation": operation, "mode": mode, "times": times}).status_code == 204


@pytest.fixture
def intake(hmis) -> Intake:
    return Intake(hmis)


def client_fields(**overrides) -> dict:
    fields = {
        "first_name": "Pat",
        "last_name": "Example",
        "name_quality": "full_name_reported",
        "date_of_birth": "1975-03-04",
        "dob_quality": "full_dob_reported",
        "ssn_last4": "4821",
        "ssn_quality": "full_ssn_reported",
        "race": ["white"],
        "ethnicity": "non_hispanic_latino",
        "gender": ["male"],
        "disabling_condition": "yes",
        "veteran_status": "no",
    }
    fields.update(overrides)
    return fields


def enrollment_fields(**overrides) -> dict:
    fields = {
        "project_id": "PRJ-SO-DEMO",
        "enrollment_date": "2026-10-07",
        "relationship_to_hoh": "self",
        "prior_living_situation": "place_not_meant_for_habitation",
        "length_of_stay": "one_year_or_longer",
        "approx_date_homelessness_started": "2025-08-15",
        "times_homeless_past_three_years": "three_times",
        "months_homeless_past_three_years": "more_than_12_months",
    }
    fields.update(overrides)
    return fields


def ce_fields(**overrides) -> dict:
    fields = {
        "ce_region": "7",
        "ce_project_id": "PRJ-CE-R7-DEMO",
        "assessment_location": "Coordinated Entry Region 7 (demo placeholder)",
        "assessment_contact_type": "in_person_street_contact",
        "current_living_situation": "place_not_meant_for_habitation",
        "household_type": "single_adult",
        "information_date": "2026-10-07",
        "verified_by_project": "Horizon House Street Outreach (demo placeholder)",
        "record_contact": True,
        "contact_service": ["Water", "Hygiene kit"],
    }
    fields.update(overrides)
    return fields
