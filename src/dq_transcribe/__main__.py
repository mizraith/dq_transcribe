"""Command-line entry point: ``python -m dq_transcribe`` starts the app.

Sets up the database, starts the background transcription workers (a fast draft
pass, plus a more accurate refine pass if its model is installed), and runs the
local web server until interrupted with Ctrl+C.
"""

from __future__ import annotations

import logging

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.server import DqTranscribeServer
from dq_transcribe.transcriber import WhisperCppTranscriber
from dq_transcribe.worker import RefineWorker, TranscriptionWorker

LOGGER = logging.getLogger(__name__)


def main() -> None:
    """Start the app and run until interrupted with Ctrl+C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    database = Database(constants.DATABASE_PATH)
    database.initialize()
    requeued = database.requeue_interrupted_clips()
    if requeued:
        LOGGER.info("Requeued %d clip(s) interrupted by the last shutdown", requeued)

    refine_worker = None
    if constants.WHISPER_REFINE_MODEL_PATH.exists():
        refine_transcriber = WhisperCppTranscriber(
            model_path=constants.WHISPER_REFINE_MODEL_PATH,
            thread_count=constants.WHISPER_REFINE_THREAD_COUNT,
            nice_increment=constants.WHISPER_REFINE_NICE_INCREMENT,
        )
        refine_worker = RefineWorker(
            database, refine_transcriber, constants.RECORDINGS_DIRECTORY, constants.SCRATCH_DIRECTORY
        )
        refine_worker.start()
        LOGGER.info("Refine pass on, using %s", refine_transcriber.model_name)
    else:
        LOGGER.info("Refine pass off: %s not found", constants.WHISPER_REFINE_MODEL_PATH)
    transcriber = WhisperCppTranscriber()
    worker = TranscriptionWorker(
        database,
        transcriber,
        constants.RECORDINGS_DIRECTORY,
        constants.SCRATCH_DIRECTORY,
        refine_worker=refine_worker,
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
        if refine_worker is not None:
            refine_worker.stop()
        server.server_close()


if __name__ == "__main__":
    main()
