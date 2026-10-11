"""Command-line entry point: ``python -m dq_transcribe`` starts the local server."""

from __future__ import annotations

import logging

from dq_transcribe import constants
from dq_transcribe.server import DqTranscribeServer


def main() -> None:
    """Start the local web server and run until interrupted with Ctrl+C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = DqTranscribeServer(
        (constants.SERVER_HOST, constants.SERVER_PORT),
        constants.RECORDINGS_DIRECTORY,
    )
    address = f"http://{constants.SERVER_DISPLAY_HOST}:{constants.SERVER_PORT}{constants.ROUTE_HOME}"
    print(f"{constants.APP_NAME} running. Open {address} in Chrome. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
