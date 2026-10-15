"""Tests for DQ records and detected-call suggestions (dq_transcribe.dq_store)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database, utc_now_iso
from dq_transcribe.dq_store import DqError, DqStore, load_dq_codes, number_sort_key


class DqStoreTests(unittest.TestCase):
    """Create, list, edit and track DQs; suggest calls from transcripts."""

    def setUp(self) -> None:
        self.database = Database(Path(tempfile.mkdtemp()) / "test.db")
        self.database.initialize()
        self.store = DqStore(self.database)
        self.store.initialize()

    def _add_transcribed_clip(self, texts: list[str]) -> list[int]:
        """Insert a finished clip with one utterance per text; return the utterance ids."""
        clip_id = self.database.add_clip("clip.wav", None, "2026-10-14T01:00:00+00:00", "2026-10-14T01:00:20+00:00")
        ids = []
        with self.database.transaction() as connection:
            connection.execute("UPDATE clips SET status = ?, duration_seconds = 20 WHERE id = ?", (constants.CLIP_STATUS_DONE, clip_id))
            for position, text in enumerate(texts):
                cursor = connection.execute(
                    "INSERT INTO utterances (clip_id, position, start_seconds, end_seconds, text, original_text) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (clip_id, position, position * 5.0, position * 5.0 + 4.0, text, text),
                )
                ids.append(cursor.lastrowid)
        return ids

    def test_candidates_come_from_transcripts_and_disappear_once_used(self) -> None:
        self._add_transcribed_clip(["Event 6, heat 4, lanes 1 and 3, scissors kick.", "Accepted."])
        candidates = self.store.candidates(None)
        self.assertEqual([(c["lane"], c["accepted"]) for c in candidates], [("1", True), ("3", True)])
        first = candidates[0]
        self.store.create_dq(
            {
                "event": first["event"], "heat": first["heat"], "lane": first["lane"], "accepted": True,
                constants.REQUEST_KEY_CANDIDATE_KEY: first["key"],
                "infractions": [{"description": desc} for desc in first["infractions"]],
                "evidence": first["evidence"],
            },
            None,
        )
        self.store.dismiss_candidate(candidates[1]["key"], None)
        self.assertEqual(self.store.candidates(None), [])
        dq = self.store.list_dqs(None)[0]
        self.assertEqual((dq["state"], dq["source"], len(dq["evidence"])), (constants.DQ_STATE_ACCEPTED, constants.DQ_SOURCE_AUTO, 2))

    def test_sorted_by_event_heat_lane_with_letter_suffixes(self) -> None:
        for event, lane in (("10", "1"), ("2b", "4"), ("2", "5"), (None, "3"), ("2", "2")):
            self.store.create_dq({"event": event, "lane": lane}, None)
        self.assertEqual([(dq["event"], dq["lane"]) for dq in self.store.list_dqs(None)],
                         [("2", "2"), ("2", "5"), ("2b", "4"), ("10", "1"), (None, "3")])
        self.assertLess(number_sort_key("2b"), number_sort_key("10"))

    def test_update_and_state_history(self) -> None:
        dq_id = self.store.create_dq({"event": "4", "lane": "6"}, None)
        self.assertTrue(self.store.update_dq(dq_id, {"swimmer": "Pat Lee", "infractions": [
            {"description": "One hand touch", "code": "3J", "phases": ["Turn", "Finish"]}]}))
        self.assertTrue(self.store.change_state(dq_id, constants.DQ_STATE_ACCEPTED, "Deck Referee"))
        dq = self.store.list_dqs(None)[0]
        self.assertEqual(dq["swimmer"], "Pat Lee")
        self.assertEqual(dq["infractions"][0]["phases"], ["Turn", "Finish"])
        self.assertEqual(dq["infractions"][0]["slip_revision"], constants.CURRENT_SLIP_REVISION)
        self.assertEqual([h["to_state"] for h in dq["history"]], [constants.DQ_STATE_CALLED, constants.DQ_STATE_ACCEPTED])
        self.assertFalse(self.store.update_dq(999, {"lane": "1"}))

    def test_validation(self) -> None:
        with self.assertRaises(DqError):
            self.store.create_dq({"infractions": [{"description": "x", "phases": ["Lunch"]}]}, None)
        with self.assertRaises(DqError):
            self.store.create_dq({"evidence": [{"clip_id": "nope"}]}, None)
        with self.assertRaises(DqError):
            self.store.change_state(1, "published-ish")

    def test_dq_codes_are_available(self) -> None:
        codes = load_dq_codes()
        self.assertIn("2A", [row["code"] for row in codes])


if __name__ == "__main__":
    unittest.main()
