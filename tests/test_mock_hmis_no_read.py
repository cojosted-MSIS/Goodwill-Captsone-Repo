"""Task 2.3: no read, search, or list path exists, in the mock HMIS or in the app's gateway.

Spec: review-and-submit, "Enter into HMIS without reading from it".
"""

from __future__ import annotations

import inspect
import json

import httpx
from fastapi.routing import APIRoute

from app.hmis_gateway import HmisGateway
from mock_hmis.service import create_app

from .conftest import ce_fields, client_fields, enrollment_fields

ENTRY_PATHS = {"/clients", "/clients/{client_id}/enrollments", "/clients/{client_id}/ce-enrollments"}
ADMIN_PATHS = {"/_admin/failures", "/_admin/reset"}


def _api_routes(app):
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_every_mock_hmis_route_is_a_post():
    for route in _api_routes(create_app()):
        assert route.methods == {"POST"}, route.path


def test_mock_hmis_routes_are_only_entry_and_admin():
    paths = {r.path for r in _api_routes(create_app())}
    assert paths == ENTRY_PATHS | ADMIN_PATHS
    assert {r.path for r in _api_routes(create_app(enable_admin=False))} == ENTRY_PATHS


def test_no_route_of_any_kind_answers_a_get(hmis):
    client_id = hmis.post("/clients", json={"fields": client_fields()}).json()["client_id"]
    for path in [
        "/clients",
        f"/clients/{client_id}",
        f"/clients/{client_id}/enrollments",
        f"/clients/{client_id}/ce-enrollments",
        "/clients/search?first_name=Pat",
        "/search",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]:
        assert hmis.get(path).status_code in (404, 405), path


def test_admin_routes_return_no_records(hmis):
    hmis.post("/clients", json={"fields": client_fields()})
    response = hmis.post("/_admin/reset")
    assert response.status_code == 204
    assert response.content == b""


def test_gateway_offers_only_the_three_entry_operations():
    public = {
        name
        for name, member in inspect.getmembers(HmisGateway, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"create_client", "enroll_in_program", "create_ce_enrollment", "close"}


def test_gateway_only_ever_sends_posts_and_takes_back_only_identifiers():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        key = {
            "/clients": "client_id",
            "/clients/HMIS-C-000001/enrollments": "enrollment_id",
            "/clients/HMIS-C-000001/ce-enrollments": "ce_enrollment_id",
        }[request.url.path]
        body = json.loads(request.content)
        assert set(body) == {"fields"}
        return httpx.Response(201, json={"status": "accepted", key: "ID-1", "extra": "ignored"})

    gateway = HmisGateway(httpx.Client(base_url="http://hmis.test", transport=httpx.MockTransport(handler)))
    results = [
        gateway.create_client(client_fields()),
        gateway.enroll_in_program("HMIS-C-000001", enrollment_fields()),
        gateway.create_ce_enrollment("HMIS-C-000001", ce_fields()),
    ]
    assert {method for method, _ in seen} == {"POST"}
    assert all(r.ok and r.identifier == "ID-1" for r in results)
    assert all(set(vars(r)) == {"ok", "identifier", "code", "reason"} for r in results)
