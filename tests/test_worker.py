"""Tests for dq_transcribe.worker and dq_transcribe.database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.worker import process_clip, refine_clip
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

    def test_trash_restore_and_permanent_delete(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        clip = self._queue_and_claim()
        process_clip(self.database, FakeTranscriber(), clip, self.recordings, self.scratch)
        self.assertIsNone(self.database.delete_trashed_clip(clip["id"]), "must be in the trash first")
        self.assertTrue(self.database.trash_clip(clip["id"]))
        self.assertFalse(self.database.trash_clip(clip["id"]), "already in the trash")
        self.assertEqual(self.database.list_clips(), [])
        self.assertEqual([c["id"] for c in self.database.list_clips(trashed=True)], [clip["id"]])
        self.assertTrue(self.database.restore_clip(clip["id"]))
        self.assertEqual(len(self.database.list_clips()), 1)
        self.database.trash_clip(clip["id"])
        self.assertEqual(self.database.delete_trashed_clip(clip["id"]), CLIP_NAME)
        self.assertEqual(self.database.list_clips(trashed=True), [])
        self.assertEqual(self.database.export_all()["clips"], [])

    def test_trashed_queued_clip_is_not_transcribed(self) -> None:
        self.database.add_clip(CLIP_NAME, None)
        clip_id = self.database.list_clips()[0]["id"]
        self.database.trash_clip(clip_id)
        self.assertIsNone(self.database.claim_next_queued_clip())

    def test_refine_pass_replaces_draft_but_keeps_edits(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        clip = self._queue_and_claim()
        process_clip(self.database, FakeTranscriber(), clip, self.recordings, self.scratch, queue_refine=True)
        stored = self.database.list_clips()[0]
        self.assertEqual(stored["refine_status"], constants.CLIP_STATUS_QUEUED)
        edited_id = stored["utterances"][0]["id"]
        self.database.update_utterance_text(edited_id, "hand edit")

        job = self.database.claim_next_refine_clip()
        self.assertEqual([turn["id"] for turn in job["utterances"]], [u["id"] for u in stored["utterances"]])
        refine_clip(self.database, FakeTranscriber(prefix="refined", model_name="small"), job, self.recordings, self.scratch)

        refined = self.database.list_clips()[0]
        self.assertEqual((refined["refine_status"], refined["refine_model"]), (constants.CLIP_STATUS_DONE, "small"))
        texts = [(u["text"], u["refined_text"], u["original_text"]) for u in refined["utterances"]]
        self.assertEqual(texts, [("hand edit", "refined 1", "turn 1"), ("refined 2", "refined 2", "turn 2")])
        self.assertIsNone(self.database.claim_next_refine_clip())

    def test_refine_failure_keeps_draft(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        process_clip(self.database, FakeTranscriber(), self._queue_and_claim(), self.recordings, self.scratch, queue_refine=True)
        refine_clip(self.database, FakeTranscriber(fail=True), self.database.claim_next_refine_clip(), self.recordings, self.scratch)
        stored = self.database.list_clips()[0]
        self.assertEqual(stored["refine_status"], constants.CLIP_STATUS_FAILED)
        self.assertEqual([u["text"] for u in stored["utterances"]], ["turn 1", "turn 2"])

    def test_reprocess_during_refine_discards_stale_refine(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        process_clip(self.database, FakeTranscriber(), self._queue_and_claim(), self.recordings, self.scratch, queue_refine=True)
        job = self.database.claim_next_refine_clip()
        self.database.mark_clip_failed(job["id"], "simulate")  # make it requeueable
        self.assertTrue(self.database.requeue_clip(job["id"]))
        self.assertFalse(self.database.save_refine_result(job["id"], [(1, "stale", "")], "small", 1.0))

    def test_no_refine_without_refine_worker(self) -> None:
        write_wav(self.recordings / CLIP_NAME, TWO_TURN_PATTERN)
        process_clip(self.database, FakeTranscriber(), self._queue_and_claim(), self.recordings, self.scratch)
        self.assertIsNone(self.database.list_clips()[0]["refine_status"])
        self.assertIsNone(self.database.claim_next_refine_clip())

    def test_interrupted_clip_is_requeued(self) -> None:
        self._queue_and_claim()
        self.assertEqual(self.database.requeue_interrupted_clips(), 1)


if __name__ == "__main__":
    unittest.main()
