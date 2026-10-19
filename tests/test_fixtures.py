"""Task 1.3: the synthetic sample emails load as test fixtures."""

from __future__ import annotations

import re

import pytest

from app.config_loader import load_config
from app.email_message import EmailFormatError, parse_email_text

EXPECTED = {
    "01_clean_new_client",
    "01b_clean_new_client_complete",
    "02_hedged_referral_trap",
    "03_search_not_stated",
    "04_unknown_dob_and_street_name",
    "05_privacy_traps",
}


def test_all_sample_emails_load(sample_emails):
    assert set(sample_emails) == EXPECTED
    for email in sample_emails.values():
        assert email.body
        assert email.sent_at.tzinfo is not None


def test_sample_senders_are_authorized_workers(sample_emails):
    workers = load_config().workers
    for stem, email in sample_emails.items():
        assert workers.worker_for(email.sender) is not None, stem


def test_sample_emails_go_to_the_intake_inbox(sample_emails):
    intake = load_config().workers.intake_address
    assert {email.recipient for email in sample_emails.values()} == {intake}


def test_subject_date_matches_sent_date(sample_emails):
    for stem, email in sample_emails.items():
        month, day = re.search(r"(\d{1,2})/(\d{1,2})$", email.subject).groups()
        assert (email.sent_at.month, email.sent_at.day) == (int(month), int(day)), stem


def test_01b_adds_length_of_stay_and_full_start_date(sample_emails):
    base = sample_emails["01_clean_new_client"].body
    complete = sample_emails["01b_clean_new_client_complete"].body
    assert "staying outside for over a year" not in base
    assert "staying outside for over a year" in complete
    assert "around March 2025" in base
    assert re.search(r"homeless this time on \d{1,2}/\d{1,2}/\d{4}", complete)


def test_only_the_privacy_trap_contains_a_full_ssn(sample_emails):
    full_ssn = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    with_full = {stem for stem, email in sample_emails.items() if full_ssn.search(email.body)}
    assert with_full == {"05_privacy_traps"}


def test_email_missing_a_header_is_rejected():
    with pytest.raises(EmailFormatError, match="missing Date"):
        parse_email_text("From: a@example.test\nTo: b@example.test\nSubject: x\n\nbody")
