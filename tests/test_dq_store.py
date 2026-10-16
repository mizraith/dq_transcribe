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

    def test_event_stroke_learned_from_a_saved_dq(self) -> None:
        self._add_transcribed_clip(["Event 6, heat 4, lanes 1 and 3, scissors kick.", "Accepted."])
        self.assertEqual([c["codes"] for c in self.store.candidates(None)], [[None], [None]])
        first = self.store.candidates(None)[0]
        self.store.create_dq({"event": "6", "lane": "1", constants.REQUEST_KEY_CANDIDATE_KEY: first["key"],
                              "infractions": [{"description": "Kick: scissors", "code": "3C", "code_options": ["1C", "3C"]}]}, None)
        remaining = self.store.candidates(None)
        self.assertEqual([(c["lane"], c["codes"], c["stroke"]) for c in remaining], [("3", ["3C"], "Breaststroke")])
        self.assertEqual(self.store.list_dqs(None)[0]["infractions"][0]["code_options"], ["1C", "3C"])

    def test_dq_codes_are_available(self) -> None:
        codes = load_dq_codes()
        self.assertIn("2A", [row["code"] for row in codes])


if __name__ == "__main__":
    unittest.main()


    def _complete_dq(self, event: str, lane: str, accepted: bool = True, evidence: list | None = None) -> int:
        """A DQ with every required field (pending notification once accepted)."""
        return self.store.create_dq(
            {"event": event, "heat": "1", "lane": lane, "swimmer": "Pat Lee", "club": "PASA", "official": "Red",
             "referee": "Sam Ortiz", "accepted": accepted, "infractions": [{"description": "One hand touch"}],
             "evidence": evidence or []},
            None,
        )

    def test_notify_event_waits_for_every_dq(self) -> None:
        first = self._complete_dq("12", "1")
        second = self._complete_dq("12", "2", accepted=False)  # still called
        with self.assertRaises(DqError):
            self.store.notify_event(None, "12", "Chief Judge")
        self.assertEqual(self.store.notify_event(None, "12", "Chief Judge", include_not_ready=True), [first])
        self.store.change_state(second, constants.DQ_STATE_ACCEPTED)
        self.assertEqual(self.store.notify_event(None, "12", "HTML Publish"), [second])
        dqs = {dq["id"]: dq for dq in self.store.list_dqs(None)}
        self.assertEqual((dqs[first]["notified_by"], dqs[second]["status"]), ("Chief Judge", constants.DQ_STATUS_NOTIFIED))
        self.assertIsNotNone(dqs[first]["notified_at"])

    def test_protest_window_and_cycle_limit(self) -> None:
        utterance_ids = self._add_transcribed_clip(["Event 12, heat 1, lane 1, one hand touch."])
        evidence = [{"clip_id": 1, "utterance_id": utterance_ids[0], "start_seconds": 0.0, "end_seconds": 4.0, "role": "call"}]
        dq_id = self._complete_dq("12", "1", evidence=evidence)  # called at 01:00 UTC on 2026-10-14
        dq = self.store.list_dqs(None)[0]
        self.assertEqual(dq["protest_deadline"], "2026-10-14T01:30:00+00:00")
        self.store.change_state(dq_id, constants.DQ_STATE_NOTIFIED, "Chief Judge")
        self.store.change_state(dq_id, constants.DQ_STATE_PROTESTED, at="2026-10-14T01:20:00+00:00")
        self.store.change_state(dq_id, constants.DQ_STATE_UPHELD, "Deck Referee")
        with self.assertRaises(DqError):  # late, no reason
            self.store.change_state(dq_id, constants.DQ_STATE_PROTESTED, at="2026-10-14T01:45:00+00:00")
        self.store.change_state(dq_id, constants.DQ_STATE_PROTESTED, note="coach was at the other end", at="2026-10-14T01:45:00+00:00")
        self.store.change_state(dq_id, constants.DQ_STATE_OVERTURNED, "Meet Referee")
        with self.assertRaises(DqError):  # past the 2-protest limit, no reason
            self.store.change_state(dq_id, constants.DQ_STATE_PROTESTED, at="2026-10-14T01:25:00+00:00")
        dq = self.store.list_dqs(None)[0]
        self.assertEqual((dq["protest_count"], dq["ruled_by"], dq["status"]), (2, "Meet Referee", constants.DQ_STATUS_OVERTURNED))

class DqStatusTests(unittest.TestCase):
    """Accepted DQs split into incomplete and pending notification."""

    def test_status(self) -> None:
        from dq_transcribe.dq_store import dq_status, missing_fields
        complete = {name: "x" for name in constants.DQ_REQUIRED_FIELDS} | {"infractions": [{"description": "One hand touch"}]}
        self.assertEqual(missing_fields(complete), [])
        self.assertEqual(missing_fields({"event": "4"})[-1], constants.DQ_REQUIRED_INFRACTION)
        self.assertEqual(dq_status(constants.DQ_STATE_ACCEPTED, []), constants.DQ_STATUS_PENDING_NOTIFICATION)
        self.assertEqual(dq_status(constants.DQ_STATE_ACCEPTED, ["club"]), constants.DQ_STATUS_INCOMPLETE)
        self.assertEqual(dq_status(constants.DQ_STATE_CALLED, ["club"]), constants.DQ_STATUS_CALLED)
        self.assertEqual(dq_status(constants.DQ_STATE_NOTIFIED, []), constants.DQ_STATUS_NOTIFIED)
        self.assertEqual(list(constants.DQ_STATUS_LABELS), [
            constants.DQ_STATUS_CALLED, constants.DQ_STATUS_INCOMPLETE, constants.DQ_STATUS_PENDING_NOTIFICATION,
            constants.DQ_STATUS_NOTIFIED, constants.DQ_STATUS_PROTESTED, constants.DQ_STATUS_UPHELD,
            constants.DQ_STATUS_OVERTURNED, constants.DQ_STATUS_DECLINED,
        ])
