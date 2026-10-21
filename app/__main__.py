"""Run the intake API: python -m app [--port 8000]. Start the mock HMIS first (python -m mock_hmis)."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from parser.factory import ParserStartupError

from .api import DEFAULT_DB, build_service, create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Outreach intake API (synthetic data only)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file, or :memory:")
    args = ap.parse_args()
    try:
        service = build_service(db_path=args.db)
    except ParserStartupError as exc:
        sys.exit(f"Parser could not start: {exc}")
    uvicorn.run(create_app(service), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
