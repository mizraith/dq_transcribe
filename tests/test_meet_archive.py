"""Tests for the meet archive zip and the close-meet rules.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.meet_archive import build_meet_archive
from helpers import build_wav_bytes


class MeetArchiveTests(unittest.TestCase):
    """What goes in the zip, and what does not."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.recordings = self.root / "recordings"
        self.database = Database(self.root / "test.db")
        self.database.initialize()
        self.store = DqStore(self.database)
        self.store.initialize()
        self.meet_id = self.database.create_meet("Candy Meet", "2026-10-16")
        audio = self.recordings / "2026-10-16_candy-meet" / "2026-10-16" / "clip_1.wav"
        audio.parent.mkdir(parents=True)
        audio.write_bytes(build_wav_bytes([("tone", 1.0)]))
        clip_id = self.database.add_clip(audio.relative_to(self.recordings).as_posix(), None,
                                         "2026-10-16T20:00:00+00:00", "2026-10-16T20:00:05+00:00", meet_id=self.meet_id)
        with self.database.transaction() as connection:
            connection.execute("UPDATE clips SET status = ? WHERE id = ?", (constants.CLIP_STATUS_DONE, clip_id))
            connection.execute("INSERT INTO utterances (id, clip_id, position, start_seconds, end_seconds, text, original_text) "
                               "VALUES (1, ?, 0, 0, 4, 'Event 12 heat 1 lane 3 one hand touch', 'x')", (clip_id,))
        self.dq_id = self.store.create_dq(
            {"event": "12", "heat": "1", "lane": "3", "swimmer": "Jane Smith", "club": "PASA", "official": "Red",
             "referee": "Sam Ortiz", "accepted": True, "infractions": [{"description": "One hand touch", "code": "3J"}],
             "evidence": [{"clip_id": clip_id, "utterance_id": 1, "start_seconds": 0, "end_seconds": 4, "role": "call"}]},
            self.meet_id,
        )
        self.store.change_state(self.dq_id, constants.DQ_STATE_NOTIFIED, "Chief Judge")

    def test_archive_contents(self) -> None:
        destination = self.root / "archive.zip"
        counts = build_meet_archive(self.database, self.store, self.meet_id, self.recordings, destination)
        self.assertEqual(counts, {"dqs": 1, "clips": 1, "audio_files": 1})
        with zipfile.ZipFile(destination) as archive:
            names = set(archive.namelist())
            self.assertTrue({"README.txt", "dqs.csv", "dq_history.csv", "dqs.json", "summary.html", "slips.html",
                             "transcript.txt", "clips.json", "audio/2026-10-16_candy-meet/2026-10-16/clip_1.wav"} <= names)
            rows = list(csv.DictReader(io.StringIO(archive.read("dqs.csv").decode())))
            self.assertEqual((rows[0]["swimmer"], rows[0]["codes"], rows[0]["notified_by"]), ("Jane Smith", "3J", "Chief Judge"))
            self.assertIn("Not included: the Hy-Tek Meet Manager files", archive.read("README.txt").decode())
            self.assertIn("one hand touch", archive.read("transcript.txt").decode())
            self.assertFalse(any("meet_files" in name for name in names))

    def test_closing_unlocks_deletes(self) -> None:
        clip_id = self.database.list_clips(meet_id=self.meet_id)[0]["id"]
        self.assertTrue(self.database.clip_meet_is_open(clip_id))
        self.database.set_meet_closed(self.meet_id, True)
        self.assertFalse(self.database.clip_meet_is_open(clip_id))
        self.store.change_state(self.dq_id, constants.DQ_STATE_DECLINED)
        self.assertEqual(self.store.delete_declined(self.meet_id), 1)
        self.assertEqual(self.store.list_dqs(self.meet_id), [])
