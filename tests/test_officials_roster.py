"""Tests for reading the Officials Sign-In roster file (format in ai_docs/officials_roster_format.md).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest

from dq_transcribe.officials_roster import RosterError, read_roster

EXAMPLE = {
    "format": "officials-roster", "version": 1, "generated_at": "2026-10-16T07:45:00-07:00",
    "meet": {"name": "Candy Meet", "start_date": "2026-10-16"},
    "session": {"name": "Friday PM", "date": "2026-10-16", "start_time": "13:00"},
    "officials": [
        {"name": "Ann Bell", "role": "Stroke & Turn Judge", "club": "PASA", "zone": "Western", "years_certified": 6,
         "trainee": False, "validated": True, "validation_method": "camera", "team": None, "member_id": "SECRET123"},
        {"name": "Ann Bell", "role": "Chief Judge", "trainee": False},
        {"name": "Ann  Bell", "role": "Chief Judge"},
        {"name": "Sam Ortiz", "role": "Deck Referee", "trainee": True},
        {"name": "Kim Lee", "role": "Hydration Judge"},
    ],
}


class RosterTests(unittest.TestCase):
    """Name and role only; unknown roles skipped; member IDs never kept."""

    def test_read(self) -> None:
        roster = read_roster(json.dumps(EXAMPLE).encode())
        self.assertEqual([(item["name"], item["role"]) for item in roster.officials],
                         [("Ann Bell", "Stroke & Turn Judge"), ("Ann Bell", "Chief Judge"), ("Sam Ortiz", "Deck Referee")])
        self.assertTrue(roster.officials[2]["trainee"])
        self.assertEqual(roster.session, "Friday PM, 2026-10-16")
        self.assertIn("Hydration Judge", roster.warnings[0])
        self.assertNotIn("SECRET123", json.dumps(roster.officials))

    def test_not_a_roster(self) -> None:
        for raw in (b"hello", json.dumps({"format": "something-else"}).encode()):
            with self.assertRaises(RosterError):
                read_roster(raw)

    def test_newer_version_still_reads_with_a_warning(self) -> None:
        roster = read_roster(json.dumps({**EXAMPLE, "version": 2}).encode())
        self.assertEqual(len(roster.officials), 3)
        self.assertIn("newer", roster.warnings[0])
