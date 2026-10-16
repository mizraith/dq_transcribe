"""Tests for the workflow demo meet (dq_transcribe.demo_data).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.demo_data import DEMO_MEET_NAME, create_demo_meet
from dq_transcribe.dq_store import DqStore
from dq_transcribe.meet_files.store import MeetProgramStore


class DemoDataTests(unittest.TestCase):
    """The demo meet has DQs in every stage and leaves other meets alone."""

    def test_demo_meet(self) -> None:
        root = Path(tempfile.mkdtemp())
        database = Database(root / "test.db")
        database.initialize()
        other = database.create_meet("Real meet", "2026-10-16")
        database.set_active_meet(other)
        meet_id = create_demo_meet(database, root / "recordings")
        store = DqStore(database, MeetProgramStore(database))
        statuses = Counter(dq["status"] for dq in store.list_dqs(meet_id))
        self.assertEqual(statuses, Counter({
            constants.DQ_STATUS_PENDING_NOTIFICATION: 3, constants.DQ_STATUS_NOTIFIED: 2, constants.DQ_STATUS_CALLED: 1,
            constants.DQ_STATUS_INCOMPLETE: 1, constants.DQ_STATUS_PROTESTED: 1, constants.DQ_STATUS_DECLINED: 1,
        }))
        self.assertEqual(database.get_active_meet_id(), other)  # the active meet is not changed
        self.assertTrue(all(dq["swimmer"] for dq in store.list_dqs(meet_id)))  # filled in from the demo program
        self.assertEqual(store.candidates(meet_id), [])  # the demo calls are already DQs
        self.assertEqual(create_demo_meet(database, root / "recordings"), meet_id)  # second run: left alone
        create_demo_meet(database, root / "recordings", replace=True)
        self.assertEqual(len(store.list_dqs(meet_id)), 9)
        self.assertEqual([meet["name"] for meet in database.list_meets()].count(DEMO_MEET_NAME), 1)
