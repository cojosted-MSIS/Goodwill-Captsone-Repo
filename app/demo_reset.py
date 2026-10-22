"""Demo only: clear the mock HMIS and the local staging store so Scenarios A and B can be rerun.

Guards, so this can never act on a real HMIS:
1. The configured HMIS address must be a loopback address (this machine). Anything else is
   refused before any request is sent.
2. The HMIS must answer the reset with the mock's marker header. If it does not, nothing in
   the staging store is cleared.
It is reached only through POST /demo/reset with an explicit confirmation phrase, never
through an email or a reply. The HMIS gateway (entry only) is not used or changed.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import httpx

from mock_hmis.service import MOCK_RESET_HEADER, MOCK_RESET_VALUE

from .workflow import IntakeService

CONFIRM_PHRASE = "reset demo"


class DemoResetRefused(Exception):
    """The reset was refused. The message is safe to show on screen."""


def is_loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def reset_demo(service: IntakeService, hmis_admin: httpx.Client) -> dict:
    """Clear the mock HMIS (records and ID counters), then the staging store."""
    url = service.config.settings.hmis_base_url
    if not is_loopback(url):
        raise DemoResetRefused("Reset is demo only. The configured HMIS is not a local mock HMIS, so nothing was reset.")
    try:
        answer = hmis_admin.post("/_admin/reset")
    except httpx.TransportError as exc:
        raise DemoResetRefused("The mock HMIS did not answer, so nothing was reset. Is it running (demo only)?") from exc
    if answer.status_code != 204 or answer.headers.get(MOCK_RESET_HEADER) != MOCK_RESET_VALUE:
        raise DemoResetRefused("The HMIS did not answer as the mock HMIS, so nothing was reset.")
    service.store.reset()
    return {"reset": True, "hmis": "mock HMIS records and ID counters cleared",
            "staging_store": "drafts, inbox, audit and ID counters cleared"}
