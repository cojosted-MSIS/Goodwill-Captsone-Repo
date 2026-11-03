"""Run the mock HMIS as its own local service: python -m mock_hmis [--port 8765] [--db data/mock_hmis.db]."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .service import create_app

# The intake app reads this file through its read-only connection (config/settings.yaml, hmis_queries.database).
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "mock_hmis.db"


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock HMIS: POST-only entry routes plus a read-only SQL layer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file the intake app reads read-only")
    parser.add_argument("--no-admin", action="store_true", help="turn off the failure switch and reset routes")
    args = parser.parse_args()
    uvicorn.run(create_app(enable_admin=not args.no_admin, db_path=args.db), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
