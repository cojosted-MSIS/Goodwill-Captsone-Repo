"""Task 2.1: the three entry operations, required-field checks, and ordering."""

from __future__ import annotations

from .conftest import ce_fields, client_fields, enrollment_fields


def _enter_all(hmis):
    client = hmis.post("/clients", json={"fields": client_fields()})
    client_id = client.json()["client_id"]
    enrollment = hmis.post(f"/clients/{client_id}/enrollments", json={"fields": enrollment_fields()})
    ce = hmis.post(f"/clients/{client_id}/ce-enrollments", json={"fields": ce_fields()})
    return client, enrollment, ce


def test_entry_succeeds_in_order_and_returns_only_assigned_identifiers(hmis):
    client, enrollment, ce = _enter_all(hmis)
    assert client.status_code == enrollment.status_code == ce.status_code == 201
    assert set(client.json()) == {"status", "client_id"}
    assert set(enrollment.json()) == {"status", "enrollment_id"}
    assert set(ce.json()) == {"status", "ce_enrollment_id"}
    assert client.json()["client_id"].startswith("HMIS-C-")


def test_create_client_missing_required_field_is_rejected(hmis, mock_hmis_app):
    response = hmis.post("/clients", json={"fields": client_fields(race=[], veteran_status=None)})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "missing_required_field"
    assert "race" in body["reason"] and "veteran_status" in body["reason"]
    assert mock_hmis_app.state.store.counts()["clients"] == 0


def test_birth_date_not_required_when_client_does_not_know(hmis):
    fields = client_fields(date_of_birth=None, dob_quality="client_doesnt_know")
    assert hmis.post("/clients", json={"fields": fields}).status_code == 201


def test_birth_date_required_when_reported(hmis):
    response = hmis.post("/clients", json={"fields": client_fields(date_of_birth=None)})
    assert response.status_code == 422
    assert "date_of_birth" in response.json()["reason"]


def test_street_name_only_needs_no_last_name(hmis):
    fields = client_fields(first_name="Chris", last_name=None, name_quality="partial_street_or_code_name")
    assert hmis.post("/clients", json={"fields": fields}).status_code == 201


def test_ssn_digits_not_required_when_client_refused(hmis):
    fields = client_fields(ssn_last4=None, ssn_quality="client_refused")
    assert hmis.post("/clients", json={"fields": fields}).status_code == 201


def test_conditional_enrollment_fields_required_for_place_not_meant_for_habitation(hmis):
    client_id = hmis.post("/clients", json={"fields": client_fields()}).json()["client_id"]
    fields = enrollment_fields(length_of_stay=None, approx_date_homelessness_started=None)
    response = hmis.post(f"/clients/{client_id}/enrollments", json={"fields": fields})
    assert response.status_code == 422
    assert "length_of_stay" in response.json()["reason"]
    assert "approx_date_homelessness_started" in response.json()["reason"]


def test_conditional_enrollment_fields_not_required_for_other_prior_situations(hmis):
    client_id = hmis.post("/clients", json={"fields": client_fields()}).json()["client_id"]
    fields = enrollment_fields(
        prior_living_situation="staying_with_friends", length_of_stay=None, approx_date_homelessness_started=None
    )
    assert hmis.post(f"/clients/{client_id}/enrollments", json={"fields": fields}).status_code == 201


def test_enrollment_for_an_unknown_client_is_rejected(hmis):
    response = hmis.post("/clients/HMIS-C-999999/enrollments", json={"fields": enrollment_fields()})
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_client"


def test_ce_enrollment_before_program_enrollment_is_rejected(hmis):
    client_id = hmis.post("/clients", json={"fields": client_fields()}).json()["client_id"]
    response = hmis.post(f"/clients/{client_id}/ce-enrollments", json={"fields": ce_fields()})
    assert response.status_code == 409
    assert response.json()["code"] == "out_of_order"


def test_record_contact_must_be_true(hmis):
    client_id = hmis.post("/clients", json={"fields": client_fields()}).json()["client_id"]
    hmis.post(f"/clients/{client_id}/enrollments", json={"fields": enrollment_fields()})
    response = hmis.post(f"/clients/{client_id}/ce-enrollments", json={"fields": ce_fields(record_contact=False)})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_value"


def test_field_the_operation_does_not_accept_is_rejected(hmis):
    response = hmis.post("/clients", json={"fields": client_fields(full_ssn="512-38-4471")})
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_field"


def test_rejection_never_echoes_submitted_values(hmis):
    response = hmis.post("/clients", json={"fields": client_fields(full_ssn="512-38-4471", race=[])})
    text = response.text
    assert "512-38-4471" not in text
    assert "Pat" not in text and "1975-03-04" not in text


def test_case_note_is_an_optional_field_on_the_program_enrollment(hmis):
    client_id = hmis.post("/clients", json={"fields": client_fields()}).json()["client_id"]
    with_note = enrollment_fields(case_note="Met Pat E. in the Southwest quadrant. Provided water.")
    assert hmis.post(f"/clients/{client_id}/enrollments", json={"fields": with_note}).status_code == 201
    other = hmis.post("/clients", json={"fields": client_fields(first_name="Sam")}).json()["client_id"]
    assert hmis.post(f"/clients/{other}/enrollments", json={"fields": enrollment_fields()}).status_code == 201


def test_case_note_is_not_accepted_on_other_operations(hmis):
    response = hmis.post("/clients", json={"fields": client_fields(case_note="Met Pat E.")})
    assert response.json()["code"] == "unknown_field"


def test_entries_are_stored_in_the_mock(hmis, mock_hmis_app):
    _enter_all(hmis)
    assert mock_hmis_app.state.store.counts() == {"clients": 1, "enrollments": 1, "ce_enrollments": 1}
