"""Launch the console: `python -m jev_agent.console [--database-url URL] [--port N]`.

Binds to 127.0.0.1 only. There is deliberately no host option: the console has
no authentication, so it must not be reachable from other machines."""

import argparse

import uvicorn

from jev_agent.console.app import create_app
from jev_agent.store import DEFAULT_DATABASE_URL

HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the JEV execution console.")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    print(f"Console for {args.database_url} at http://{HOST}:{args.port}")
    uvicorn.run(create_app(args.database_url), host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
