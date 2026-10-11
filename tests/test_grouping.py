"""Tests for dq_transcribe.grouping."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from dq_transcribe.grouping import assign_conversation_groups, normalize_timestamp

BASE = datetime(2026, 10, 16, 10, 0, 0, tzinfo=timezone.utc)


def make_clip(clip_id: int, start_offset: float, duration: float) -> dict:
    """Build a clip dict starting ``start_offset`` seconds after BASE."""
    start = BASE + timedelta(seconds=start_offset)
    return {
        "id": clip_id,
        "created_at": (start + timedelta(seconds=duration)).isoformat(),
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(seconds=duration)).isoformat(),
        "duration_seconds": duration,
    }


class GroupingTests(unittest.TestCase):
    """Clips closer than the gap share a group."""

    def test_gap_under_threshold_groups(self) -> None:
        clips = [make_clip(1, 0, 5), make_clip(2, 7, 5)]  # 2 s gap
        assign_conversation_groups(clips, 5.0)
        self.assertEqual([clip["group_id"] for clip in clips], [1, 1])

    def test_gap_at_or_over_threshold_splits(self) -> None:
        clips = [make_clip(1, 0, 5), make_clip(2, 10, 5), make_clip(3, 17, 3)]
        assign_conversation_groups(clips, 5.0)  # gaps: 5 s, 2 s
        self.assertEqual([clip["group_id"] for clip in clips], [1, 2, 2])

    def test_missing_start_falls_back_to_created_at(self) -> None:
        clip = make_clip(1, 0, 5)
        clip["started_at"] = None
        clip["ended_at"] = None
        assign_conversation_groups([clip], 5.0)
        self.assertEqual(clip["group_id"], 1)

    def test_normalize_timestamp_handles_z_suffix(self) -> None:
        self.assertIn("2026-10-16T10:00:00", normalize_timestamp("2026-10-16T10:00:00.000Z"))
        self.assertIsNone(normalize_timestamp("garbage"))


if __name__ == "__main__":
    unittest.main()
