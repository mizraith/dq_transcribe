"""Tests for dq_transcribe.worker and dq_transcribe.database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.worker import process_clip
from helpers import FakeTranscriber, write_wav

TWO_TURN_PATTERN = [("tone", 2.0), ("silence", 1.5), ("tone", 2.0)]
CLIP_NAME = "2026-10-16/clip_a.wav"


class ProcessClipTests(unittest.TestCase):
    """process_clip stores utterances or records failures."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.recordings = self.root / "recordings"
        self.scratch = self.root / "scratch"
        self.database = Database(self.root / "test.db")
        self.database.initialize()

    def _queue_and_claim(self, name: str = CLIP_NAME) -> dict:
        self.database.add_clip(name, None)
        clip = self.database.claim_next_queued_clip()
        assert clip is not None
        return clip

    def test_two_turn_clip_becomes_two_utterances(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        clip = self._queue_and_claim()
        process_clip(self.database, FakeTranscriber(), clip, self.recordings, self.scratch)
        stored = self.database.list_clips()[0]
        self.assertEqual(stored["status"], constants.CLIP_STATUS_DONE)
        self.assertEqual([item["text"] for item in stored["utterances"]], ["turn 1", "turn 2"])

    def test_transcriber_failure_marks_clip_failed(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        clip = self._queue_and_claim()
        process_clip(self.database, FakeTranscriber(fail=True), clip, self.recordings, self.scratch)
        self.assertEqual(self.database.list_clips()[0]["status"], constants.CLIP_STATUS_FAILED)

    def test_missing_audio_marks_clip_failed(self) -> None:
        clip = self._queue_and_claim("missing.wav")
        process_clip(self.database, FakeTranscriber(), clip, self.recordings, self.scratch)
        self.assertEqual(self.database.list_clips()[0]["status"], constants.CLIP_STATUS_FAILED)

    def test_edit_keeps_original_text_and_reprocess_requeues(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        clip = self._queue_and_claim()
        process_clip(self.database, FakeTranscriber(), clip, self.recordings, self.scratch)
        utterance = self.database.list_clips()[0]["utterances"][0]
        self.assertTrue(self.database.update_utterance_text(utterance["id"], "fixed"))
        edited = self.database.list_clips()[0]["utterances"][0]
        self.assertEqual((edited["text"], edited["original_text"]), ("fixed", "turn 1"))
        self.assertTrue(self.database.requeue_clip(clip["id"]))
        self.assertEqual(self.database.list_clips()[0]["status"], constants.CLIP_STATUS_QUEUED)

    def test_interrupted_clip_is_requeued(self) -> None:
        self._queue_and_claim()
        self.assertEqual(self.database.requeue_interrupted_clips(), 1)


if __name__ == "__main__":
    unittest.main()
