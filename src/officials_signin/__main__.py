"""Command-line entry point: ``python -m officials_signin`` starts the app.

Creates the database if needed and runs the local web server until it is
interrupted (Ctrl+C or SIGTERM). Open http://localhost:8010 in Chrome.
"""

from __future__ import annotations

import logging
import signal

from officials_signin import constants
from officials_signin.database import Database
from officials_signin.server import SigninServer


def _exit_on_terminate(signal_number: int, frame: object) -> None:
    """Turn SIGTERM (for example from pkill) into a normal shutdown."""
    raise KeyboardInterrupt


def main() -> None:
    """Start the app and run until interrupted."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    signal.signal(signal.SIGTERM, _exit_on_terminate)
    database = Database(constants.DATABASE_PATH)
    database.initialize()
    web_server = SigninServer((constants.SERVER_HOST, constants.SERVER_PORT), database)
    address = f"http://{constants.SERVER_DISPLAY_HOST}:{constants.SERVER_PORT}{constants.ROUTE_HOME}"
    print(f"{constants.APP_TITLE} running. Open {address} in Chrome. Press Ctrl+C to stop.")
    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        web_server.server_close()


if __name__ == "__main__":
    main()
