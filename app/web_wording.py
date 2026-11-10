"""The web application's wording for every message and phrase (add-web-application, Stage 3a).

The same keys as app/email_wording.py, in the words of the web screens: buttons ("Confirm",
"Try again", "Same client", "Different person", "Make a correction") instead of commands to
reply with, and no reference tokens in titles. Plain language for a worker on a phone outdoors.
"""

from __future__ import annotations

# Parser failures, by code, in web words (the parser's own messages say "resend your note").
PARSER_FAILURES: dict[str, str] = {
    "not_configured": "The AI parser is not set up. Nothing was drafted or entered into HMIS. Ask the demo admin.",
    "timeout": "The AI parser did not answer in time. Nothing was drafted or entered into HMIS. Please send your note again.",
    "unreachable": "The AI parser could not be reached. Nothing was drafted or entered into HMIS. Please send your note again.",
    "unauthorized": "The AI parser refused the demo's key. Nothing was drafted or entered into HMIS. Ask the demo admin.",
    "rate_limited": "The AI parser is busy. Nothing was drafted or entered into HMIS. Please send your note again in a few minutes.",
    "service_error": "The AI parser had an error. Nothing was drafted or entered into HMIS. Please send your note again.",
    "malformed_response": "The AI parser's answer could not be read. Nothing was drafted or entered into HMIS. Please send your note again.",
    "invalid_output": ("The AI parser's draft did not pass the intake checks, even after a second try. Nothing was drafted "
                       "or entered into HMIS. Please send the note again, or enter the record in HMIS yourself."),
}


def parser_failure(params: dict) -> str:
    return PARSER_FAILURES.get(params.get("failure_code") or "", PARSER_FAILURES["service_error"])


# key -> (title, body). A str.format template over the message parameters, or a function of them.
WEB: dict[str, tuple] = {
    # notes
    "parse_failed": ("Could not draft: {title}", parser_failure),
    "search_request": ("Did you search HMIS first?",
                       "Before I draft a new client, please confirm that you searched HMIS and found no existing record. "
                       "Press \"I searched HMIS, no match\" once you have. Nothing has been drafted or sent to HMIS."),
    "search_request_again": ("Did you search HMIS first?",
                             "I still need you to confirm that you searched HMIS and found no existing record. "
                             "Press \"I searched HMIS, no match\" once you have. Nothing has been drafted or sent to HMIS."),
    # updates to a client already in HMIS
    "client_ids_disagree": ("Which client?",
                            "Your note gives more than one client ID: {ids}. Nothing was drafted. "
                            "Please write the note again with the one client ID it is about."),
    "client_id_invalid": ("Check the client ID",
                          "The client ID {client_id} is not in the HMIS format (for example HMIS-C-000101). "
                          "Nothing was drafted. Please check the ID and write the note again."),
    "client_check_failed_id": ("Could not check the client",
                               "HMIS could not be read to check the client ID, so nothing was drafted. Please try again later."),
    "client_check_failed_name": ("Could not check the client",
                                 "HMIS could not be read to find the client, so nothing was drafted. Please try again later."),
    "client_not_found_id": ("Client not found",
                            "No client with the ID {client_id} was found. Nothing was drafted. "
                            "Please check the ID, or write a new-client note for someone not in HMIS yet."),
    "client_not_found_name": ("Client not found",
                              "No client with that name and date of birth was found in HMIS, so nothing was drafted. "
                              "For someone not in HMIS yet, write a new-client note."),
    "client_id_needed": ("Which client?",
                         "To add this update I need the client's HMIS client ID, or their first and last name "
                         "with the full date of birth. Nothing was drafted. Please write the note again with it."),
    "pick_client": ("Which client is this update for?",
                    "I found {count} client{plural} with that name and date of birth. "
                    "Pick the one this update is for. Nothing has been drafted or sent to HMIS.\n\n{lines}"),
    "pick_client_again": ("Which client is this update for?",
                          "Please pick one of these clients: {ids}. Nothing has been drafted or sent to HMIS."),
    "client_not_found_picked": ("Client not found", "The client {client_id} could not be found now, so nothing was drafted."),
    "client_not_found_now": ("Client not found",
                             "The client {client_id} could not be found now, so nothing was changed. Please try again later."),
    # read-only questions
    "query_answer": ("HMIS answer", "{answer}"),
    # drafts
    "verification_note": ("Same name and date of birth in HMIS", "{lead}"),
    "old_version": ("Please review version {v}",
                    "You confirmed version {confirmed}, but version {v} was made after it. "
                    "Please review version {v} and press Confirm on it. Nothing has been entered into HMIS."),
    "missing_info": ("Still needed before entry",
                     "Draft v{v} cannot be entered yet. Please add, with Make a correction:\n{listed}\n"
                     "Nothing has been entered into HMIS."),
    "expired_action": ("Draft is with your supervisor",
                       "This draft was not confirmed in time and is now in your supervisor's queue. "
                       "Nothing has been entered into HMIS. Please talk with your supervisor."),
    "not_in_review": ("Draft not in review",
                      "This draft is not waiting for review. If it could not be drafted, please write your note again."),
    "corrections_parse_failed": ("Could not read your correction", lambda p: parser_failure(p) + f"\nDraft v{p['v']} is unchanged."),
    "rephrase_not_asked": ("Please say it another way",
                           "Which question did you not ask? Please name it, for example "
                           "\"Didn't ask about race\" or \"Veteran: didn't ask\". Draft v{v} is unchanged."),
    "rephrase": ("Please say it another way",
                 "I could not match your correction to any field. Please say it another way, for example "
                 "\"Living situation: staying outside\" or \"It was the third time on the street\". Draft v{v} is unchanged."),
    "correction_refused_stubbed": ("Correct it in HMIS",
                                   "The details of this update are no longer kept here (production retention), so it cannot be "
                                   "corrected here. Please correct it in HMIS. Nothing was changed."),
    "correction_refused_not_ours": ("Correct it in HMIS",
                                    "That entry was not made by this system for this update, so it cannot be corrected here. "
                                    "Please correct it in HMIS. Nothing was changed."),
    # entry
    "entry_failed": ("Not entered in HMIS",
                     "HMIS did not accept {label}. Reason: {reason}.\nWhat this means: {meaning}\n\n"
                     "Recorded in HMIS:\n{recorded}\n\nNot recorded:\n{missing}\n\n"
                     "Your confirmed draft is kept. Press Try again; steps already recorded will not be repeated."),
    "correction_entered": ("Correction entered in HMIS",
                           "HMIS accepted the correction for client {client_id} ({client_label}):\n{lines}\n\n"
                           "To correct these entries again, use Make a correction on this receipt."),
    "update_entered": ("Entered in HMIS",
                       "HMIS accepted the update for client {client_id} ({client_label}). Identifiers HMIS assigned:\n"
                       "  - Case note ID: {case_note_id}\n  - Service ID: {service_id}\n\n"
                       "To correct these entries, use Make a correction on this receipt, for example "
                       "\"It was 45 minutes, not 30\". Only you can correct them, and you confirm again."),
    "new_client_entered": ("Entered in HMIS",
                           "HMIS accepted the entries. Identifiers HMIS assigned:\n"
                           "  - Client ID: {client_id}\n  - Program enrollment ID: {enrollment_id}\n"
                           "  - Coordinated Entry enrollment ID: {ce_enrollment_id}\n\n"
                           "Still to complete in HMIS:\n{remaining}"),
    # the supervisor queue
    "expired_worker": ("Moved to your supervisor's queue",
                       "Draft {ref} was not confirmed within {hours} hours and is now in your supervisor's queue. "
                       "Nothing was entered into HMIS."),
    "expired_supervisor": ("Unconfirmed draft {ref} from {worker_id}",
                           "Draft {ref} from {worker_id} has not been confirmed for {hours} hours. Nothing was entered into HMIS."),
}

WEB_PHRASES: dict[str, str] = {
    # verification leads
    "verify_confirm_blocked": ("Confirm is not available yet: HMIS has a client with the same name and date of birth. "
                               "Choose Same client or Different person first."),
    "verify_not_candidate": "Please choose one of these clients: {ids}.",
    "verify_reason_missing": ("Please say why this is a different person, for example \"She is 20 years younger than "
                              "the person in HMIS\". Confirm is not available yet."),
    "verify_reason_short": ("Because the SSN digits match, please give a fuller reason (at least {minimum} characters). "
                            "Confirm is not available yet."),
    # validation flags
    "missing_field": "{label} is missing. Please add it with Make a correction.{reason}",
    "missing_project_id": "Which project should the neighbor be enrolled in? Add the project name with Make a correction.",
    "missing_ce_region": ("Which Coordinated Entry region? Add the region number with Make a correction, "
                          "for example \"CE region 7\"."),
    "note_date": "the date you wrote the note",
    "contact_date_unclear": ("Your note says the contact was \"{phrase}\", which could not be pinned to one day. "
                             "The {what} date uses the date you wrote the note. Check it."),
    # where a value came from
    "origin_email_date": "date of the note",
    "origin_worker": "from your correction",
    # the review, verification, and receipt screens
    "confirm_blocked": "Confirm is not available until you add: {missing}",
    "grade_hard_stop": ("Hard stop: the last four SSN digits are missing in your note or in HMIS, so the system cannot "
                        "tell. Please get the digits from the neighbor if you can and add them with Make a correction."),
    "update_same_client": "You chose Same client ({client_id}), so your new-client note became this update. No new client is created.",
    "update_correction": "This is a correction to entries already in HMIS ({ids}). Confirm enters it as an update to them.",
    "different_person_line": ("you chose Different person (not {ids}), so this is entered as a new client marked "
                              "confirmed distinct, with your reason.{flagged}"),
    "entry_next": "Your confirmed draft is kept. Press Try again; steps HMIS already accepted are not repeated.",
    "receipt_update": "The system added these entries to the client's record only through entry operations, after you confirmed.",
    "receipt_new_client": ("You searched HMIS and found no match. The system wrote these records only through entry "
                           "operations, after you confirmed."),
}
