"""The email channel's wording for every message and phrase (add-web-application, Stage 3a).

The core says what happened with a neutral key and parameters (app/messages.py); this file says it
the way the email version always has: commands to reply with (CONFIRM, RETRY, SAME CLIENT,
DIFFERENT PERSON, CLIENT <ID>) and a reference token in each subject, which the email channel
reads when the worker replies. The web wording is in app/web_wording.py, with the same keys.
"""

from __future__ import annotations

# key -> (subject, body). Each is a str.format template over the message parameters.
EMAIL: dict[str, tuple[str, str]] = {
    # notes
    "parse_failed": ("Could not draft: {title} [{ref}]", "{failure}\n\nPlease resend your note as a new email."),
    "search_request": ("Please confirm HMIS search: {title} [{ref}]",
                       "Before I draft a new client, please confirm that you searched HMIS and found no existing record.\n"
                       "Reply \"Searched HMIS, no match\" once you have. Nothing has been drafted or sent to HMIS."),
    "search_request_again": ("Please confirm HMIS search: {title} [{ref}]",
                             "I still need you to confirm that you searched HMIS and found no existing record.\n"
                             "Reply \"Searched HMIS, no match\" once you have. Nothing has been drafted or sent to HMIS."),
    # updates to a client already in HMIS
    "client_ids_disagree": ("Which client? [{ref}]",
                            "Your note gives more than one client ID: {ids}. Nothing was drafted. "
                            "Please resend the note with the one client ID it is about."),
    "client_id_invalid": ("Check the client ID [{ref}]",
                          "The client ID {client_id} is not in the HMIS format (for example HMIS-C-000101). "
                          "Nothing was drafted. Please check the ID and resend the note."),
    "client_check_failed_id": ("Could not check the client [{ref}]",
                               "HMIS could not be read to check the client ID, so nothing was drafted. Please try again later."),
    "client_check_failed_name": ("Could not check the client [{ref}]",
                                 "HMIS could not be read to find the client, so nothing was drafted. Please try again later."),
    "client_not_found_id": ("Client not found [{ref}]",
                            "No client with the ID {client_id} was found. Nothing was drafted. "
                            "Please check the ID, or send a \"New client:\" note for someone not in HMIS yet."),
    "client_not_found_name": ("Client not found [{ref}]",
                              "No client with that name and date of birth was found in HMIS, so nothing was drafted. "
                              "For someone not in HMIS yet, send a \"New client:\" note."),
    "client_id_needed": ("Which client? [{ref}]",
                         "To add this update I need the client's HMIS client ID, or their first and last name "
                         "with the full date of birth. Nothing was drafted. Please resend the note with it."),
    "pick_client": ("Which client? {title} [{ref}]",
                    "I found {count} client{plural} with that name and date of birth. "
                    "Reply CLIENT <ID> with the one this update is for. Nothing has been drafted or sent to HMIS.\n\n{lines}"),
    "pick_client_again": ("Which client? {title} [{ref}]",
                          "Please reply CLIENT <ID> with one of these client IDs: {ids}. Nothing has been drafted or sent to HMIS."),
    "client_not_found_picked": ("Client not found [{ref}]", "The client {client_id} could not be found now, so nothing was drafted."),
    "client_not_found_now": ("Client not found [{ref}]",
                             "The client {client_id} could not be found now, so nothing was changed. Please try again later."),
    # read-only questions
    "query_answer": ("HMIS answer: {title} [{ref}]", "{answer}"),
    # drafts
    "verification_note": ("Same name in HMIS [{ref} v{v}]", "{lead}"),  # email drafts carry the lead in the verification email
    "old_version": ("Please review version {v} [{ref} v{v}]",
                    "You confirmed version {confirmed}, but version {v} was sent after it. "
                    "Please review version {v} and reply CONFIRM to that email. Nothing has been entered into HMIS."),
    "missing_info": ("Still needed before entry [{ref} v{v}]",
                     "Draft v{v} cannot be entered yet. Please reply with:\n{listed}\nNothing has been entered into HMIS."),
    "expired_action": ("Draft is with your supervisor [{ref}]",
                       "This draft was not confirmed in time and is now in your supervisor's queue. "
                       "Nothing has been entered into HMIS. Please talk with your supervisor."),
    "not_in_review": ("Draft not in review [{ref}]",
                      "This draft is not waiting for review. If it could not be drafted, please resend your note."),
    "corrections_parse_failed": ("Could not read your changes [{ref} v{v}]", "{failure}\nDraft v{v} is unchanged."),
    "rephrase_not_asked": ("Please rephrase [{ref} v{v}]",
                           "Which question did you not ask? Please name it, for example "
                           "\"Didn't ask about race\" or \"Veteran: didn't ask\". Draft v{v} is unchanged."),
    "rephrase": ("Please rephrase [{ref} v{v}]",
                 "I could not match your reply to any field. Please rephrase, for example "
                 "\"Living situation: staying outside\" or \"It was the third time on the street\". Draft v{v} is unchanged."),
    "correction_refused_stubbed": ("Correct it in HMIS [{ref}]",
                                   "The details of this update are no longer kept here (production retention), so it cannot be "
                                   "corrected by email. Please correct it in HMIS. Nothing was changed."),
    "correction_refused_not_ours": ("Correct it in HMIS [{ref}]",
                                    "That entry was not made by this system for this update, so it cannot be corrected here. "
                                    "Please correct it in HMIS. Nothing was changed."),
    # entry
    "entry_failed": ("Not entered in HMIS [{ref}]",
                     "HMIS did not accept {label}. Reason: {reason}.\nWhat this means: {meaning}\n\n"
                     "Recorded in HMIS:\n{recorded}\n\nNot recorded:\n{missing}\n\n"
                     "Your confirmed draft is kept. Reply RETRY to try again; steps already recorded will not be repeated."),
    "correction_entered": ("Correction entered in HMIS [{ref}]",
                           "HMIS accepted the correction for client {client_id} ({client_label}):\n{lines}\n\n"
                           "To correct these entries again, reply to this email with the change."),
    "update_entered": ("Submitted to HMIS [{ref}]",
                       "HMIS accepted the update for client {client_id} ({client_label}). Identifiers HMIS assigned:\n"
                       "  - Case note ID: {case_note_id}\n  - Service ID: {service_id}\n\n"
                       "To correct these entries, reply to this email with the change, for example "
                       "\"It was 45 minutes, not 30\". Only you can correct them, and CONFIRM is needed again."),
    "new_client_entered": ("Submitted to HMIS [{ref}]",
                           "HMIS accepted the entries. Identifiers HMIS assigned:\n"
                           "  - Client ID: {client_id}\n  - Program enrollment ID: {enrollment_id}\n"
                           "  - Coordinated Entry enrollment ID: {ce_enrollment_id}\n\n"
                           "Still to complete in HMIS:\n{remaining}"),
    # the supervisor queue
    "expired_worker": ("Moved to your supervisor's queue [{ref}]",
                       "Draft {ref} was not confirmed within {hours} hours and is now in your supervisor's queue. "
                       "Nothing was entered into HMIS."),
    "expired_supervisor": ("Unconfirmed draft {ref} from {worker_id}",
                           "Draft {ref} from {worker_id} has not been confirmed for {hours} hours. Nothing was entered into HMIS."),
}

# Short phrases used inside other text: flags, verification leads, and the review and receipt screens.
EMAIL_PHRASES: dict[str, str] = {
    # verification leads
    "verify_confirm_blocked": ("CONFIRM is not accepted yet: HMIS has a client with the same name and date of birth. "
                               "Please reply SAME CLIENT <ID> or DIFFERENT PERSON with a reason."),
    "verify_not_candidate": "Please reply SAME CLIENT with one of these client IDs: {ids}.",
    "verify_reason_missing": ("Please say why this is a different person, for example \"DIFFERENT PERSON: she is 20 years "
                              "younger than the person in HMIS\". CONFIRM is not accepted yet."),
    "verify_reason_short": ("Because the SSN digits match, please give a fuller reason (at least {minimum} characters). "
                            "CONFIRM is not accepted yet."),
    # validation flags
    "missing_field": "{label} is missing. Please reply with it.{reason}",
    "missing_project_id": "Which project should the neighbor be enrolled in? Reply with the project name.",
    "missing_ce_region": "Which Coordinated Entry region? Reply with the region number, for example \"CE region 7\".",
    "note_date": "the date of your email",
    "contact_date_unclear": ("Your note says the contact was \"{phrase}\", which could not be pinned to one day. "
                             "The {what} date uses the date of your email. Check it."),
    # where a value came from
    "origin_email_date": "email date",
    "origin_worker": "from your reply",
    # the review, verification, and receipt screens
    "confirm_blocked": "CONFIRM is blocked until you reply with: {missing}",
    "grade_hard_stop": ("Hard stop: the last four SSN digits are missing in your note or in HMIS, so the system cannot "
                        "tell. Please get the digits from the neighbor if you can and reply with them."),
    "update_same_client": "You replied SAME CLIENT {client_id}, so your new-client note became this update. No new client is created.",
    "update_correction": "This is a CORRECTION to entries already in HMIS ({ids}). CONFIRM enters it as an update to them.",
    "different_person_line": ("you replied DIFFERENT PERSON (not {ids}), so this is entered as a new client marked "
                              "confirmed distinct, with your reason.{flagged}"),
    "entry_next": "Your confirmed draft is kept. Reply RETRY to try again; steps HMIS already accepted are not repeated.",
    "receipt_update": "The system added these entries to the client's record only through entry operations, after your CONFIRM.",
    "receipt_new_client": ("You searched HMIS and found no match. The system wrote these records only through entry "
                           "operations, after your CONFIRM."),
}
