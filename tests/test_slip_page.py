"""Tests for the printable DQ slip (dq_transcribe.slip_page).

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from dq_transcribe.slip_page import initials, render_slips, revision_label


def example_dq(**changes) -> dict:
    """A DQ as listed by the store."""
    dq = {
        "event": "46", "heat": "2", "lane": "4", "relay_leg": None, "swimmer": "Lily Nguyen", "club": "PASA",
        "official": "Ann Bell", "chief_judge": "Lee Chan", "referee": "Sam Ortiz", "notified_at": None,
        "infractions": [
            {"description": "Past vertical at turn: delay initiating turn", "code": "2C", "phases": ["Turn"], "detail": ""},
            {"description": "No touch at turn", "code": "2A", "phases": ["Turn"], "detail": "3"},
            {"description": "Swam in the wrong lane", "code": None, "phases": []},
        ],
    }
    dq.update(changes)
    return dq


class SlipTests(unittest.TestCase):
    """What is written where on the slip."""

    def test_labels(self) -> None:
        self.assertEqual(revision_label("2024-01"), "rev. (1/24)")
        self.assertEqual(initials("Lee  Chan"), "LC")

    def test_slip_marks_infractions_and_names(self) -> None:
        page = render_slips([example_dq()], "test").decode("utf-8")
        self.assertIn('Delay initiating turn(2C) <span class="blank ">X</span>', page)
        self.assertIn('No touch at turn(2A) <span class="blank ">X 3</span>', page)
        self.assertIn("Swam in the wrong lane", page)  # no code: written on the Other line
        self.assertIn('<span class="blank full name">Ann Bell</span>', page)
        self.assertIn('<span class="blank name">LC</span>', page)
        self.assertIn("rev. (1/24)", page)
        self.assertEqual(page.count('class="slip"'), 1)

    def test_names_are_escaped(self) -> None:
        page = render_slips([example_dq(swimmer="<b>Pat</b>")], "test").decode("utf-8")
        self.assertIn("&lt;b&gt;Pat&lt;/b&gt;", page)
