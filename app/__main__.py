"""Run the intake API and the phone screens: python -m app [--port 8000] [--parser reallms].

Start the mock HMIS first (python -m mock_hmis). Then open http://127.0.0.1:8000/ui/.
The default parser is the rule-based stub, which runs offline with no key. --parser reallms
(or INTAKE_PARSER=reallms) uses REALLMS with the model in config/settings.yaml
(gemma-4-31B-it) unless --model or LLM_MODEL names another. The key is read from .env and
is never sent to the browser or written to the logs.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from parser.factory import ParserStartupError

from .api import DEFAULT_DB, build_service, create_app, run_housekeeping_every


def main() -> None:
    ap = argparse.ArgumentParser(description="Outreach intake API and phone screens (synthetic data only)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file, or :memory:")
    ap.add_argument("--parser", choices=["rule_stub", "reallms"], help="override config/settings.yaml and INTAKE_PARSER")
    ap.add_argument("--model", help="REALLMS model (default: config/settings.yaml)")
    ap.add_argument("--email-channel", action="store_true",
                    help="switch the email channel on (off by default), as the email demo does")
    ap.add_argument("--draft-content-views", action="store_true",
                    help="demo only: serve the parser run, mapped draft, and staged record views (off by default)")
    ap.add_argument("--demo-reset", action="store_true",
                    help="demo only: serve the web demo's reset and let it clear the device (off by default)")
    args = ap.parse_args()
    try:
        service = build_service(db_path=args.db, parser=args.parser, model=args.model,
                                email_channel=True if args.email_channel else None,
                                draft_content_views=True if args.draft_content_views else None,
                                demo_reset=True if args.demo_reset else None)
    except ParserStartupError as exc:
        sys.exit(f"Parser could not start: {exc}")
    app = create_app(service)
    email = "on" if service.config.settings.channels.email.enabled else "off"
    print(f"Parser: {service.parser.base.name}. Email channel: {email}. Web API: http://{args.host}:{args.port}/api/v1/")
    if app.state.users.missing:
        print("Sign-in is not set up for accounts whose password variable is missing from .env: "
              + ", ".join(app.state.users.missing))
    if email == "on":
        print(f"Phone screens (email demo): http://{args.host}:{args.port}/ui/")
    run_housekeeping_every(service, service.config.settings.web.housekeeping_minutes * 60)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
