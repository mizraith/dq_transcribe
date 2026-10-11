"""Background transcription of queued clips.

A single worker thread takes clips from the database queue one at a time. For
each clip it measures loudness, splits the audio into turns at pauses,
transcribes each turn, and stores the results. If anything goes wrong the clip
is marked failed with a reason and can be reprocessed later from the web page.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from dq_transcribe import constants
from dq_transcribe.audio_analysis import analyze_clip, read_mono_wav, write_wav_segment
from dq_transcribe.database import Database, NewUtterance
from dq_transcribe.transcriber import Transcriber

LOGGER = logging.getLogger(__name__)


def process_clip(
    database: Database,
    transcriber: Transcriber,
    clip: dict[str, Any],
    recordings_directory: Path,
    scratch_directory: Path,
) -> None:
    """Analyze, split, and transcribe one clip, then store the result.

    Failures are caught and recorded on the clip rather than raised.

    Args:
        database: Where results are stored.
        transcriber: Speech engine used for each turn.
        clip: Claimed clip, with ``id`` and ``audio_filename``.
        recordings_directory: Folder holding the clip's WAV file.
        scratch_directory: Folder for temporary per-turn WAV files.
    """
    clip_id = clip["id"]
    started = time.monotonic()
    try:
        audio = read_mono_wav(recordings_directory / clip["audio_filename"])
        analysis = analyze_clip(audio)
        scratch_directory.mkdir(parents=True, exist_ok=True)

        utterances: list[NewUtterance] = []
        for position, turn in enumerate(analysis.turns):
            turn_path = scratch_directory / f"clip{clip_id}_turn{position}{constants.CLIP_FILE_EXTENSION}"
            write_wav_segment(audio, turn.start_seconds, turn.end_seconds, turn_path)
            try:
                result = transcriber.transcribe(turn_path)
            finally:
                turn_path.unlink(missing_ok=True)
            utterances.append(
                NewUtterance(position, turn.start_seconds, turn.end_seconds, result.text, result.raw_output)
            )

        elapsed = time.monotonic() - started
        database.save_processing_result(clip_id, analysis, utterances, transcriber.model_name, elapsed)
        LOGGER.info("Clip %d done: %d turn(s) in %.1f s", clip_id, len(utterances), elapsed)
    except Exception as error:  # noqa: BLE001 - any failure must be recorded, not crash the worker
        LOGGER.exception("Clip %d failed", clip_id)
        database.mark_clip_failed(clip_id, f"{type(error).__name__}: {error}")


class TranscriptionWorker(threading.Thread):
    """Thread that works through the clip queue until stopped."""

    def __init__(
        self,
        database: Database,
        transcriber: Transcriber,
        recordings_directory: Path,
        scratch_directory: Path,
        idle_poll_seconds: float = constants.WORKER_IDLE_POLL_SECONDS,
    ) -> None:
        """Prepare the worker (call ``start`` to run it).

        Args:
            database: Queue and results store.
            transcriber: Speech engine.
            recordings_directory: Folder holding clip WAV files.
            scratch_directory: Folder for temporary files.
            idle_poll_seconds: How often to check the queue when nothing wakes the worker.
        """
        super().__init__(name=constants.WORKER_THREAD_NAME, daemon=True)
        self._database = database
        self._transcriber = transcriber
        self._recordings_directory = recordings_directory
        self._scratch_directory = scratch_directory
        self._idle_poll_seconds = idle_poll_seconds
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

    def wake(self) -> None:
        """Tell the worker that a clip was just queued."""
        self._wake_event.set()

    def stop(self) -> None:
        """Ask the worker to finish its current clip and exit."""
        self._stop_event.set()
        self._wake_event.set()

    def run(self) -> None:
        """Process queued clips one at a time until ``stop`` is called."""
        while not self._stop_event.is_set():
            clip = self._database.claim_next_queued_clip()
            if clip is None:
                self._wake_event.wait(self._idle_poll_seconds)
                self._wake_event.clear()
                continue
            process_clip(
                self._database, self._transcriber, clip, self._recordings_directory, self._scratch_directory
            )
