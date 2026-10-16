"""Tests for automatic DQs (dq_transcribe.auto_dq): detected calls become DQs without a tap."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.auto_dq import AutoDqCreator, roster_guesses
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqError, DqStore

MEET_NAME = "Candy Meet"
CLIP_START = "2026-10-16T23:00:{second:02d}+00:00"


class AutoDqTests(unittest.TestCase):
    """Calls heard on the radio are made into DQs, and accepted when the acknowledgment comes."""

    def setUp(self) -> None:
        self.database = Database(Path(tempfile.mkdtemp()) / "test.db")
        self.database.initialize()
        self.store = DqStore(self.database)
        self.store.initialize()
        self.meet_id = self.database.create_meet(MEET_NAME, "2026-10-16")
        self.auto = AutoDqCreator(self.database, self.store)

    def _add_clip(self, texts: list[str], second: int = 0, refine_status: str | None = None) -> int:
        """A transcribed clip in the meet, one utterance per text."""
        clip_id = self.database.add_clip("clip.wav", None, CLIP_START.format(second=second), CLIP_START.format(second=second + 5), meet_id=self.meet_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE clips SET status = ?, refine_status = ?, duration_seconds = 5 WHERE id = ?",
                (constants.CLIP_STATUS_DONE, refine_status, clip_id),
            )
            for position, text in enumerate(texts):
                connection.execute(
                    "INSERT INTO utterances (clip_id, position, start_seconds, end_seconds, text, original_text) VALUES (?, ?, ?, ?, ?, ?)",
                    (clip_id, position, position * 2.0, position * 2.0 + 1.5, text, text),
                )
        return clip_id

    def test_calls_become_dqs_once(self) -> None:
        self._add_clip(["Event 6, heat 4, lanes 1 and 3, scissors kick.", "Accepted."])
        created = self.auto.run_once()["created"]
        self.assertEqual(len(created), 2)
        dqs = self.store.list_dqs(self.meet_id)
        self.assertEqual({(dq["lane"], dq["state"], dq["source"]) for dq in dqs},
                         {("1", constants.DQ_STATE_ACCEPTED, constants.DQ_SOURCE_AUTO), ("3", constants.DQ_STATE_ACCEPTED, constants.DQ_SOURCE_AUTO)})
        self.assertEqual(self.auto.run_once()["created"], [])  # nothing new
        self.store.trash_dq(created[0])
        self.auto._last_signature = None
        self.assertEqual(self.auto.run_once()["created"], [])  # a trashed auto DQ is never made again

    def test_late_acknowledgment_accepts_the_dq(self) -> None:
        self._add_clip(["Event 6, heat 4, lane 2, scissors kick."])
        dq_id = self.auto.run_once()["created"][0]
        self.assertEqual(self.store.list_dqs(self.meet_id)[0]["state"], constants.DQ_STATE_CALLED)
        self._add_clip(["Accepted."], second=8)
        self.assertEqual(self.auto.run_once()["accepted"], [dq_id])
        self.assertEqual(self.store.list_dqs(self.meet_id)[0]["state"], constants.DQ_STATE_ACCEPTED)

    def test_waits_for_the_refine_pass(self) -> None:
        self._add_clip(["Event 6, heat 4, lane 2, scissors kick."], refine_status=constants.CLIP_STATUS_QUEUED)
        self.assertEqual(self.auto.run_once()["created"], [])

    def test_off_switch(self) -> None:
        self.auto.set_enabled(False)
        self._add_clip(["Event 6, heat 4, lane 2, scissors kick."])
        self.assertEqual(self.auto.run_once()["created"], [])
        self.auto.set_enabled(True)
        self.assertEqual(len(self.auto.run_once()["created"]), 1)

    def test_roster_fills_referee_and_chief_judge_when_unique(self) -> None:
        self.database.update_meet(self.meet_id, MEET_NAME, "2026-10-16", [("Lee Ref", "Deck Referee"), ("Kim Chief", "Chief Judge"), ("Al One", "Chief Judge")])
        self._add_clip(["Event 6, heat 4, lane 2, scissors kick."])
        self.auto.run_once()
        dq = self.store.list_dqs(self.meet_id)[0]
        self.assertEqual(dq["referee"], "Lee Ref")
        self.assertIsNone(dq["chief_judge"])  # two chief judges: left for the admin

    def test_roster_guesses_fall_back_to_meet_referee(self) -> None:
        self.assertEqual(roster_guesses([{"name": "Pat", "role": "Meet Referee"}]), {"referee": "Pat"})

    def test_a_call_can_only_be_made_into_a_dq_once(self) -> None:
        self._add_clip(["Event 6, heat 4, lane 2, scissors kick."])
        candidate = self.store.candidates(self.meet_id)[0]
        self.auto.run_once()
        with self.assertRaises(DqError):
            self.store.create_dq({"lane": "2", constants.REQUEST_KEY_CANDIDATE_KEY: candidate["key"]}, self.meet_id)


if __name__ == "__main__":
    unittest.main()
