"""Background transcription of queued clips, in two passes.

Two worker threads run at the same time:

* The **draft** worker takes newly uploaded clips one at a time. For each clip it
  measures loudness, splits the audio into turns at pauses, transcribes each turn
  with a fast model, and stores the results, so text appears quickly.
* The **refine** worker then re-transcribes the same turns with a slower, more
  accurate model and replaces the draft text, except on lines edited by hand
  (their refined text is kept alongside for comparison).

If anything goes wrong, the clip is marked failed with a reason (draft pass) or
keeps its draft text (refine pass), and can be reprocessed from the web page.
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
    queue_refine: bool = False,
) -> None:
    """Analyze, split, and transcribe one clip, then store the result.

    Failures are caught and recorded on the clip rather than raised.

    Args:
        database: Where results are stored.
        transcriber: Speech engine used for each turn.
        clip: Claimed clip, with ``id`` and ``audio_filename``.
        recordings_directory: Folder holding the clip's WAV file.
        scratch_directory: Folder for temporary per-turn WAV files.
        queue_refine: Queue the clip for the refine pass afterwards.
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
        database.save_processing_result(
            clip_id, analysis, utterances, transcriber.model_name, elapsed, queue_refine=queue_refine
        )
        LOGGER.info("Clip %d done: %d turn(s) in %.1f s", clip_id, len(utterances), elapsed)
    except Exception as error:  # noqa: BLE001 - any failure must be recorded, not crash the worker
        LOGGER.exception("Clip %d failed", clip_id)
        database.mark_clip_failed(clip_id, f"{type(error).__name__}: {error}")


def refine_clip(
    database: Database,
    transcriber: Transcriber,
    clip: dict[str, Any],
    recordings_directory: Path,
    scratch_directory: Path,
) -> None:
    """Re-transcribe a clip's turns with the refine model and store the results.

    The turns are the ones the draft pass found, so lines stay aligned. Failures
    are recorded on the clip (the draft text stays) rather than raised.

    Args:
        database: Where results are stored.
        transcriber: The more accurate speech engine.
        clip: Claimed clip, with ``id``, ``audio_filename`` and ``utterances``
            (each with ``id``, ``start_seconds`` and ``end_seconds``).
        recordings_directory: Folder holding the clip's WAV file.
        scratch_directory: Folder for temporary per-turn WAV files.
    """
    clip_id = clip["id"]
    started = time.monotonic()
    try:
        audio = read_mono_wav(recordings_directory / clip["audio_filename"])
        scratch_directory.mkdir(parents=True, exist_ok=True)
        refined: list[tuple[int, str, str]] = []
        for turn in clip["utterances"]:
            turn_path = scratch_directory / f"refine_clip{clip_id}_utterance{turn['id']}{constants.CLIP_FILE_EXTENSION}"
            write_wav_segment(audio, turn["start_seconds"], turn["end_seconds"], turn_path)
            try:
                result = transcriber.transcribe(turn_path)
            finally:
                turn_path.unlink(missing_ok=True)
            refined.append((turn["id"], result.text, result.raw_output))
        elapsed = time.monotonic() - started
        if database.save_refine_result(clip_id, refined, transcriber.model_name, elapsed):
            LOGGER.info("Clip %d refined: %d turn(s) in %.1f s", clip_id, len(refined), elapsed)
    except Exception:  # noqa: BLE001 - a failed refine must not crash the worker; the draft stays
        LOGGER.exception("Refining clip %d failed", clip_id)
        database.mark_refine_failed(clip_id)


class _QueueWorker(threading.Thread):
    """Thread that takes jobs from a database queue one at a time until stopped.

    Subclasses define how to claim the next job and how to process it.
    """

    def __init__(
        self,
        thread_name: str,
        database: Database,
        transcriber: Transcriber,
        recordings_directory: Path,
        scratch_directory: Path,
        idle_poll_seconds: float,
    ) -> None:
        """Prepare the worker (call ``start`` to run it).

        Args:
            thread_name: Name of the thread, shown in logs and debuggers.
            database: Queue and results store.
            transcriber: Speech engine.
            recordings_directory: Folder holding clip WAV files.
            scratch_directory: Folder for temporary files.
            idle_poll_seconds: How often to check the queue when nothing wakes the worker.
        """
        super().__init__(name=thread_name, daemon=True)
        self._database = database
        self._transcriber = transcriber
        self._recordings_directory = recordings_directory
        self._scratch_directory = scratch_directory
        self._idle_poll_seconds = idle_poll_seconds
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()

    def wake(self) -> None:
        """Tell the worker that a job was just queued."""
        self._wake_event.set()

    def stop(self) -> None:
        """Ask the worker to finish its current job and exit."""
        self._stop_event.set()
        self._wake_event.set()

    def run(self) -> None:
        """Process queued jobs one at a time until ``stop`` is called."""
        while not self._stop_event.is_set():
            job = self._claim_next()
            if job is None:
                self._wake_event.wait(self._idle_poll_seconds)
                self._wake_event.clear()
                continue
            self._process(job)

    def _claim_next(self) -> dict[str, Any] | None:
        """Claim the next job from the database, or return None if there is none."""
        raise NotImplementedError

    def _process(self, job: dict[str, Any]) -> None:
        """Process one claimed job."""
        raise NotImplementedError


class RefineWorker(_QueueWorker):
    """Second-pass worker: re-transcribes finished clips with a more accurate model."""

    def __init__(
        self,
        database: Database,
        transcriber: Transcriber,
        recordings_directory: Path,
        scratch_directory: Path,
        idle_poll_seconds: float = constants.WORKER_IDLE_POLL_SECONDS,
    ) -> None:
        """Prepare the refine worker (call ``start`` to run it). Arguments as for ``_QueueWorker``."""
        super().__init__(
            constants.REFINE_WORKER_THREAD_NAME,
            database,
            transcriber,
            recordings_directory,
            scratch_directory,
            idle_poll_seconds,
        )

    def _claim_next(self) -> dict[str, Any] | None:
        return self._database.claim_next_refine_clip()

    def _process(self, job: dict[str, Any]) -> None:
        refine_clip(self._database, self._transcriber, job, self._recordings_directory, self._scratch_directory)


class TranscriptionWorker(_QueueWorker):
    """First-pass (draft) worker: transcribes new clips quickly, then hands them to the refine worker."""

    def __init__(
        self,
        database: Database,
        transcriber: Transcriber,
        recordings_directory: Path,
        scratch_directory: Path,
        idle_poll_seconds: float = constants.WORKER_IDLE_POLL_SECONDS,
        refine_worker: RefineWorker | None = None,
    ) -> None:
        """Prepare the draft worker (call ``start`` to run it).

        Args:
            database: Queue and results store.
            transcriber: The fast speech engine.
            recordings_directory: Folder holding clip WAV files.
            scratch_directory: Folder for temporary files.
            idle_poll_seconds: How often to check the queue when nothing wakes the worker.
            refine_worker: If given, finished clips are queued for it and it is woken.
        """
        super().__init__(
            constants.WORKER_THREAD_NAME,
            database,
            transcriber,
            recordings_directory,
            scratch_directory,
            idle_poll_seconds,
        )
        self._refine_worker = refine_worker

    def _claim_next(self) -> dict[str, Any] | None:
        return self._database.claim_next_queued_clip()

    def _process(self, job: dict[str, Any]) -> None:
        process_clip(
            self._database,
            self._transcriber,
            job,
            self._recordings_directory,
            self._scratch_directory,
            queue_refine=self._refine_worker is not None,
        )
        if self._refine_worker is not None:
            self._refine_worker.wake()
