"""Command-line entry point: ``python -m dq_transcribe`` starts the app.

Sets up the database, starts the background transcription workers (a fast draft
pass, plus a more accurate refine pass if its model is installed), and runs the
local web server until interrupted with Ctrl+C.
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.demo_data import ensure_demo_meet
from dq_transcribe.database import Database
from dq_transcribe.server import DqTranscribeServer
from dq_transcribe.transcriber import (
    Transcriber,
    TranscriberUnavailableError,
    WhisperCppTranscriber,
    WhisperServerTranscriber,
)
from dq_transcribe.worker import RefineWorker, TranscriptionWorker

LOGGER = logging.getLogger(__name__)


def build_transcriber(
    port: int, model_path: Path, thread_count: int, nice_increment: int, servers: list[WhisperServerTranscriber]
) -> Transcriber:
    """Make a transcriber: a persistent whisper-server if installed, else whisper-cli.

    Args:
        port: Local port for the server.
        model_path: Model file to load.
        thread_count: CPU threads.
        nice_increment: How much to lower its CPU priority (0 = normal).
        servers: Servers are appended here so they can be warmed up and stopped.

    Returns:
        The transcriber.
    """
    if constants.WHISPER_SERVER_PATH.exists():
        server = WhisperServerTranscriber(
            port, model_path=model_path, thread_count=thread_count, nice_increment=nice_increment
        )
        servers.append(server)
        return server
    LOGGER.info("whisper-server not found; using whisper-cli (reloads the model for every turn)")
    return WhisperCppTranscriber(model_path=model_path, thread_count=thread_count, nice_increment=nice_increment)


def warm_up(server: WhisperServerTranscriber) -> None:
    """Start a whisper-server and load its model; log instead of failing (the worker retries)."""
    try:
        server.start()
        LOGGER.info("whisper-server ready: %s", server.model_name)
    except TranscriberUnavailableError as error:
        LOGGER.warning("whisper-server not ready: %s", error)


def _exit_on_terminate(signal_number: int, frame: object) -> None:
    """Turn SIGTERM (for example from pkill) into a normal shutdown so whisper servers are stopped."""
    raise KeyboardInterrupt


def _ensure_training_meet(database: Database) -> None:
    """Create the training meet if it is missing (never fatal: the app works without it)."""
    try:
        ensure_demo_meet(database, constants.RECORDINGS_DIRECTORY)
    except Exception:  # noqa: BLE001 (log and carry on)
        LOGGER.exception("Could not create the training meet")


def main() -> None:
    """Start the app and run until interrupted with Ctrl+C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    signal.signal(signal.SIGTERM, _exit_on_terminate)

    database = Database(constants.DATABASE_PATH)
    database.initialize()
    requeued = database.requeue_interrupted_clips()
    if requeued:
        LOGGER.info("Requeued %d clip(s) interrupted by the last shutdown", requeued)

    servers: list[WhisperServerTranscriber] = []
    refine_worker = None
    if constants.WHISPER_REFINE_MODEL_PATH.exists():
        refine_transcriber = build_transcriber(
            constants.WHISPER_REFINE_SERVER_PORT,
            constants.WHISPER_REFINE_MODEL_PATH,
            constants.WHISPER_REFINE_THREAD_COUNT,
            constants.WHISPER_REFINE_NICE_INCREMENT,
            servers,
        )
        refine_worker = RefineWorker(
            database, refine_transcriber, constants.RECORDINGS_DIRECTORY, constants.SCRATCH_DIRECTORY
        )
        refine_worker.start()
        LOGGER.info("Refine pass on, using %s", refine_transcriber.model_name)
    else:
        LOGGER.info("Refine pass off: %s not found", constants.WHISPER_REFINE_MODEL_PATH)
    transcriber = build_transcriber(
        constants.WHISPER_DRAFT_SERVER_PORT, constants.WHISPER_MODEL_PATH, constants.WHISPER_THREAD_COUNT, 0, servers
    )
    # Load the models in the background so the web page is available at once.
    for whisper_server in servers:
        threading.Thread(target=warm_up, args=(whisper_server,), daemon=True).start()
    worker = TranscriptionWorker(
        database,
        transcriber,
        constants.RECORDINGS_DIRECTORY,
        constants.SCRATCH_DIRECTORY,
        refine_worker=refine_worker,
    )
    worker.start()

    web_server = DqTranscribeServer(
        (constants.SERVER_HOST, constants.SERVER_PORT),
        constants.RECORDINGS_DIRECTORY,
        database,
        worker,
    )
    # The coach page (read-only DQ list on the meet Wi-Fi) comes back on if the admin left it on.
    web_server.coach_page.restore()
    # Detected calls become DQs on their own (switch in Meet setup); the admin approves at notify.
    web_server.auto_dqs.start()
    # The training meet ships with the app: create it once, in the background (it takes a few seconds).
    threading.Thread(target=_ensure_training_meet, args=(database,), daemon=True).start()
    address = f"http://{constants.SERVER_DISPLAY_HOST}:{constants.SERVER_PORT}{constants.ROUTE_HOME}"
    print(f"{constants.APP_NAME} running. Open {address} in Chrome. Press Ctrl+C to stop.")
    try:
        web_server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        web_server.coach_page.stop()
        web_server.auto_dqs.stop()
        worker.stop()
        if refine_worker is not None:
            refine_worker.stop()
        for whisper_server in servers:
            whisper_server.stop()
        web_server.server_close()


if __name__ == "__main__":
    main()
