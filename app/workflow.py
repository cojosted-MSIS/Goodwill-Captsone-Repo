"""The intake workflow, kept as one import path for existing code.

The logic now lives in two modules (add-web-application, Stage 2):
  app/core.py           the channel-neutral core: every use case and rule, one method per action
  app/email_channel.py  the email channel: sender allowlist, subject routing, reply commands,
                        and the review and verification emails
"""

from .core import ENTRY_STEPS, UPDATE_STEPS, IntakeCore, Outcome
from .email_channel import IntakeService, reply_text

__all__ = ["ENTRY_STEPS", "UPDATE_STEPS", "IntakeCore", "IntakeService", "Outcome", "reply_text"]
