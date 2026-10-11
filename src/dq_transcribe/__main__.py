"""Command-line entry point: ``python -m dq_transcribe`` starts the app.

Sets up the database, starts the background transcription worker, and runs the
local web server until interrupted with Ctrl+C.
"""

from __future__ import annotations

import logging

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.server import DqTranscribeServer
from dq_transcribe.transcriber import WhisperCppTranscriber
from dq_transcribe.worker import TranscriptionWorker

LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Start the app and run until interrupted with Ctrl+C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    database = Database(constants.DATABASE_PATH)
    database.initialize()
    requeued = database.requeue_interrupted_clips()
    if requeued:
        LOGGER.info("Requeued %d clip(s) interrupted by the last shutdown", requeued)

    transcriber = WhisperCppTranscriber()
    worker = TranscriptionWorker(
        database, transcriber, constants.RECORDINGS_DIRECTORY, constants.SCRATCH_DIRECTORY
    )
    worker.start()

    server = DqTranscribeServer(
        (constants.SERVER_HOST, constants.SERVER_PORT),
        constants.RECORDINGS_DIRECTORY,
        database,
        worker,
    )
    address = f"http://{constants.SERVER_DISPLAY_HOST}:{constants.SERVER_PORT}{constants.ROUTE_HOME}"
    print(f"{constants.APP_NAME} running. Open {address} in Chrome. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        worker.stop()
        server.server_close()


if __name__ == "__main__":
    main()
