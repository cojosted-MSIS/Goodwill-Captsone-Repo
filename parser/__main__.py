"""Parse one synthetic email and print the result.

    python -m parser sample-data/emails/01b_clean_new_client_complete.txt
    python -m parser sample-data/emails/02_hedged_referral_trap.txt --parser reallms --model glm-5.2
"""

from __future__ import annotations

import argparse

from app.config_loader import load_config
from app.email_message import load_email_file

from .factory import build_parser


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse one synthetic worker email")
    ap.add_argument("email", help="path to an email file in sample-data/emails/")
    ap.add_argument("--parser", choices=["rule_stub", "reallms"], help="override settings.yaml")
    ap.add_argument("--model", help="REALLMS model (overrides settings.yaml)")
    args = ap.parse_args()

    config = load_config()
    if args.parser:
        config = config.model_copy(update={"settings": config.settings.model_copy(update={"parser": args.parser})})
    result = build_parser(config, model=args.model).parse(load_email_file(args.email))

    print(f"parser: {result.parser}")
    if not result.ok:
        print(f"FAILED ({result.failure.code}): {result.failure.message}")
        for flag in result.flags:
            print(f"  {flag}")
        return
    search = result.hmis_search_stated
    print(f"worker searched HMIS: {'yes' if search else 'NOT STATED'}")
    for name in config.fields.fields:
        if name in result.fields:
            f = result.fields[name]
            print(f"  {name:34s} {f.value!s:30s} [{f.confidence}]  <- {f.source}")
        elif name in config.parsable_fields():
            blank = "(not stated: email date)" if config.fields.fields[name].fallback == "email_date" else "(blank, flagged)"
            print(f"  {name:34s} {blank:30s}")
    print(f"notices: {', '.join(result.notices) or 'none'}")
    for flag in result.flags:
        print(f"flag: {flag}")
    print(f"case note (generated, check wording): {result.case_note}")


if __name__ == "__main__":
    main()
