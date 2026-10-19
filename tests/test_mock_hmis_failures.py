"""Task 2.2: failure switches, possible duplicates, and how the gateway reports failures."""

from __future__ import annotations

import httpx
import pytest

from app.hmis_gateway import HmisGateway

from .conftest import ce_fields, client_fields, enrollment_fields


def _set_failure(hmis, operation, mode, times=1):
    assert hmis.post("/_admin/failures", json={"operation": operation, "mode": mode, "times": times}).status_code == 204


@pytest.mark.parametrize(
    ("mode", "status"),
    [("missing_required_field", 422), ("possible_duplicate", 409), ("service_unavailable", 503)],
)
def test_failure_switch_rejects_the_next_call(hmis, mock_hmis_app, mode, status):
    _set_failure(hmis, "create_client", mode)
    response = hmis.post("/clients", json={"fields": client_fields()})
    assert response.status_code == status
    assert response.json()["code"] == mode
    assert mock_hmis_app.state.store.counts()["clients"] == 0
    assert hmis.post("/clients", json={"fields": client_fields()}).status_code == 201


def test_failure_switch_can_last_until_reset(hmis):
    _set_failure(hmis, "create_client", "service_unavailable", times=None)
    for _ in range(3):
        assert hmis.post("/clients", json={"fields": client_fields()}).status_code == 503
    assert hmis.post("/_admin/reset").status_code == 204
    assert hmis.post("/clients", json={"fields": client_fields()}).status_code == 201


def test_failure_switch_applies_only_to_its_operation(hmis):
    _set_failure(hmis, "enroll_in_program", "service_unavailable")
    client = hmis.post("/clients", json={"fields": client_fields()})
    assert client.status_code == 201
    enrollment = hmis.post(f"/clients/{client.json()['client_id']}/enrollments", json={"fields": enrollment_fields()})
    assert enrollment.status_code == 503


def test_service_unavailable_applies_before_any_other_check(hmis):
    _set_failure(hmis, "create_ce_enrollment", "service_unavailable")
    response = hmis.post("/clients/HMIS-C-999999/ce-enrollments", json={"fields": ce_fields()})
    assert response.status_code == 503


def test_possible_duplicate_rejected_without_revealing_the_existing_record(hmis):
    first = hmis.post("/clients", json={"fields": client_fields()})
    second = hmis.post("/clients", json={"fields": client_fields(first_name="PAT ", last_name="example")})
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "possible_duplicate"
    assert first.json()["client_id"] not in second.text
    assert set(body) == {"status", "code", "reason"}


def test_blank_match_fields_never_count_as_duplicates(hmis):
    fields = client_fields(first_name="Chris", last_name=None, name_quality="partial_street_or_code_name",
                           date_of_birth=None, dob_quality="client_doesnt_know")
    assert hmis.post("/clients", json={"fields": fields}).status_code == 201
    assert hmis.post("/clients", json={"fields": fields}).status_code == 201


# The gateway is how the app sees these failures.


def test_gateway_reports_success_with_the_assigned_identifier(gateway):
    result = gateway.create_client(client_fields())
    assert result.ok and result.identifier.startswith("HMIS-C-")
    assert result.code is None


def test_gateway_reports_rejection_with_code_and_reason(hmis, gateway):
    _set_failure(hmis, "create_client", "possible_duplicate")
    result = gateway.create_client(client_fields())
    assert not result.ok
    assert result.identifier is None
    assert result.code == "possible_duplicate"
    assert result.reason


def test_gateway_reports_unreachable_hmis_as_service_unavailable():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    gateway = HmisGateway(httpx.Client(base_url="http://hmis.test", transport=httpx.MockTransport(refuse)))
    result = gateway.create_client(client_fields())
    assert not result.ok
    assert result.code == "service_unavailable"


def test_gateway_sends_dates_as_iso_strings(gateway):
    from datetime import date

    result = gateway.create_client(client_fields(date_of_birth=date(1975, 3, 4)))
    assert result.ok
