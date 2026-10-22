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

from .api import DEFAULT_DB, build_service, create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Outreach intake API and phone screens (synthetic data only)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file, or :memory:")
    ap.add_argument("--parser", choices=["rule_stub", "reallms"], help="override config/settings.yaml and INTAKE_PARSER")
    ap.add_argument("--model", help="REALLMS model (default: config/settings.yaml)")
    args = ap.parse_args()
    try:
        service = build_service(db_path=args.db, parser=args.parser, model=args.model)
    except ParserStartupError as exc:
        sys.exit(f"Parser could not start: {exc}")
    print(f"Parser: {service.parser.base.name}. Phone screens: http://{args.host}:{args.port}/ui/")
    uvicorn.run(create_app(service), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
