"""Messages to workers and supervisors, worded per channel (add-web-application, Stage 3a).

The core never writes wording. It names what happened with a neutral key (for example
"search_request" or "entry_failed") and its parameters, and the draft's channel supplies the
words: app/email_wording.py for email (commands to reply with, reference tokens in subjects)
and app/web_wording.py for the web screens (buttons, plain titles). Both have the same keys.
"""

from __future__ import annotations

from typing import Any

from .email_wording import EMAIL, EMAIL_PHRASES
from .web_wording import WEB, WEB_PHRASES

CATALOGS = {"email": EMAIL, "web": WEB}
PHRASES = {"email": EMAIL_PHRASES, "web": WEB_PHRASES}


def _fill(template: Any, params: dict[str, Any]) -> str:
    return template(params) if callable(template) else template.format(**params)


def render(channel: str, key: str, params: dict[str, Any]) -> tuple[str, str]:
    """The (subject, body) of message `key` in this channel's words."""
    subject, body = CATALOGS[channel][key]
    return _fill(subject, params), _fill(body, params)


def phrase(channel: str, key: str, **params: Any) -> str:
    """A short phrase in this channel's words (a flag, a verification lead, a line on a screen)."""
    return PHRASES[channel][key].format(**params)
