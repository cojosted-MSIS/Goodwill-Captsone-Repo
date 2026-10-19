"""Run the mock HMIS as its own local service: python -m mock_hmis [--port 8765]."""

from __future__ import annotations

import argparse

import uvicorn

from .service import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Entry-only mock HMIS")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-admin", action="store_true", help="turn off the failure switch and reset routes")
    args = parser.parse_args()
    uvicorn.run(create_app(enable_admin=not args.no_admin), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
