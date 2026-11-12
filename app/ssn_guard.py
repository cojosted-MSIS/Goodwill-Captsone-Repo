"""Keep full Social Security numbers out of web notes (add-web-application, Stage 3b).

The offline spec puts these layers on the device before a note is saved (Stage 4). Until then
they run on the server, on every text a worker types in the web app, before anything is kept:

  1. Mask each full number matching `shared.ssn.any_full_number` (123-45-6789, or nine digits)
     to ***-**- and its last four digits. A known invalid number (validation.yaml) is noted
     first, so the parser can still flag it after masking.
  2. Refuse the text when `shared.ssn.possible_full_number` still finds an SSN word followed by
     seven or more digits in another grouping ("social 123 45 6789"): the worker rewrites it with
     only the last four digits. Nothing is kept.
Numbers written in words are not detected [TBC with Goodwill and CHIP].
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parser.shared import known_invalid_ssn_label, mask_ssns

from .config_loader import AppConfig

REFUSED_MESSAGE = ("Your text looks like it has a full Social Security number. Nothing was saved. Please write only "
                   "the last four digits, for example \"SSN ends 6789\".")


@dataclass(frozen=True)
class Guarded:
    text: str  # the text with every full number masked
    masked: int  # how many full numbers were masked
    invalid_label: str | None  # the label of a known invalid full number, if one was masked
    refused: bool  # an SSN in another form is still there: nothing may be kept


def guard(text: str, config: AppConfig) -> Guarded:
    ssn = config.mappings.shared.ssn
    found = [m.group(0) for m in re.finditer(ssn.any_full_number, text)]
    label = next((lbl for lbl in (known_invalid_ssn_label(n, config) for n in found) if lbl), None)
    masked = mask_ssns(text, config)
    refused = re.search(ssn.possible_full_number, masked, re.IGNORECASE) is not None
    return Guarded(text=masked, masked=len(found), invalid_label=label, refused=refused)
