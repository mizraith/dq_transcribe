"""Tests for the training meet (dq_transcribe.demo_data).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.demo_data import (
    DEMO_MEET_NAME, DQS_PER_EVENT, EVENTS, LAST_NOTIFIED_EVENT, LAST_READY_EVENT, create_demo_meet, ensure_demo_meet,
)
from dq_transcribe.dq_store import DqStore
from dq_transcribe.meet_files.store import MeetProgramStore

AFTER_NOTIFICATION = {constants.DQ_STATUS_NOTIFIED, constants.DQ_STATUS_PROTESTED, constants.DQ_STATUS_UPHELD,
                      constants.DQ_STATUS_OVERTURNED, constants.DQ_STATUS_DECLINED}


class DemoDataTests(unittest.TestCase):
    """25 events, 4-10 DQs each, closing in event order; other meets left alone."""

    def test_training_meet(self) -> None:
        root = Path(tempfile.mkdtemp())
        database = Database(root / "test.db")
        database.initialize()
        other = database.create_meet("Real meet", "2026-10-16")
        meet_id = ensure_demo_meet(database, root / "recordings")
        self.assertEqual(database.get_active_meet_id(), other)  # the active meet is not changed
        store = DqStore(database, MeetProgramStore(database))
        by_event: dict[int, list[dict]] = defaultdict(list)
        for dq in store.list_dqs(meet_id):
            by_event[int(dq["event"])].append(dq)
        self.assertEqual(sorted(by_event), list(range(1, len(EVENTS) + 1)))
        self.assertTrue(all(DQS_PER_EVENT[0] <= len(dqs) <= DQS_PER_EVENT[1] for dqs in by_event.values()))
        for number, dqs in by_event.items():
            statuses = {dq["status"] for dq in dqs}
            if number <= LAST_NOTIFIED_EVENT:
                self.assertTrue(statuses <= AFTER_NOTIFICATION, (number, statuses))  # early events are done
            elif number <= LAST_READY_EVENT:
                self.assertTrue(statuses <= {constants.DQ_STATUS_PENDING_NOTIFICATION, constants.DQ_STATUS_DECLINED}, (number, statuses))
            else:
                self.assertFalse(statuses & {constants.DQ_STATUS_NOTIFIED}, (number, statuses))  # later events not notified
        self.assertTrue(all(dq["swimmer"] for dqs in by_event.values() for dq in dqs))
        self.assertEqual(store.candidates(meet_id), [])  # every training call is already a DQ
        total = sum(len(dqs) for dqs in by_event.values())
        self.assertEqual(ensure_demo_meet(database, root / "recordings"), meet_id)  # second start: left alone
        self.assertEqual(len(store.list_dqs(meet_id)), total)
        create_demo_meet(database, root / "recordings", replace=True)  # rebuild: same data, fresh times
        self.assertEqual(len(store.list_dqs(meet_id)), total)
        self.assertEqual([meet["name"] for meet in database.list_meets()].count(DEMO_MEET_NAME), 1)
