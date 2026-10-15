"""Tests for reading Meet Manager files and using them for DQs.

Uses a hand-written heat sheet in Hy-Tek's usual layout (tests/data/). The real
files from the owner's meet will replace or extend these samples.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.meet_files import MeetFileError, detect_format, read_meet_file
from dq_transcribe.meet_files import mm_database
from dq_transcribe.meet_files.html_report import html_text
from dq_transcribe.meet_files.model import ProgramEvent, club_code, normalize_event_number, stroke_for_slip_codes
from dq_transcribe.meet_files.report_text import parse_report_text, split_columns
from dq_transcribe.meet_files.store import MeetProgramStore

SAMPLE_HEAT_SHEET = Path(__file__).parent / "data" / "sample_heat_sheet.txt"


def sample_text() -> str:
    """The sample heat sheet as text."""
    return SAMPLE_HEAT_SHEET.read_text(encoding="utf-8")


class ModelTests(unittest.TestCase):
    """Event descriptions, club codes and event numbers."""

    def test_event_description(self) -> None:
        event = ProgramEvent.from_description("012", "Girls 10 & Under 50 Yard Breaststroke")
        self.assertEqual((event.number, event.gender, event.age_group, event.distance, event.course, event.stroke, event.relay),
                         ("12", "Girls", "10 & Under", 50, "Yard", "Breaststroke", False))
        relay = ProgramEvent.from_description("13", "Boys 11-12 200 Yard Medley Relay")
        self.assertEqual((relay.stroke, relay.relay, relay.age_group), (constants.STROKE_MEDLEY_RELAY, True, "11-12"))

    def test_stroke_for_slip_codes(self) -> None:
        self.assertEqual(stroke_for_slip_codes(constants.STROKE_BUTTERFLY), constants.STROKE_BUTTERFLY)
        self.assertEqual(stroke_for_slip_codes(constants.STROKE_FREESTYLE_RELAY), constants.STROKE_FREESTYLE)
        self.assertIsNone(stroke_for_slip_codes(constants.STROKE_INDIVIDUAL_MEDLEY))
        self.assertIsNone(stroke_for_slip_codes(constants.STROKE_MEDLEY_RELAY))

    def test_small_helpers(self) -> None:
        self.assertEqual(club_code("PASA-PC"), "PASA")
        self.assertEqual(normalize_event_number(" 02B "), "2b")


class ReportTextTests(unittest.TestCase):
    """The shared heat-sheet parser (used for PDF, HTML and text reports)."""

    def test_heat_sheet(self) -> None:
        program = parse_report_text(sample_text())
        self.assertEqual([event.number for event in program.events], ["12", "13", "21"])
        entries = {(entry.event_number, entry.heat, entry.lane): entry for entry in program.entries}
        self.assertEqual(entries[("12", "1", "1")].swimmer, "Jane Smith")  # middle initial dropped
        self.assertEqual(entries[("12", "1", "3")].swimmer, "Mary-Kate O'Neil")
        self.assertEqual(entries[("12", "2", "4")].club, "PASA")
        relay = entries[("13", "1", "3")]
        self.assertEqual((relay.swimmer, relay.relay, len(relay.relay_swimmers)), ("PASA-A", True, 4))
        self.assertEqual([(session.number, session.event_numbers) for session in program.sessions], [("1", ["12", "13"]), ("2", ["21"])])
        self.assertEqual(program.warnings, [])

    def test_two_column_page_is_read_left_then_right(self) -> None:
        left = ["Event 12  Girls 10 & Under 50 Yard Breaststroke", "Heat 1 of 1  Timed Finals",
                "    1  Smith, Jane                10 PASA-PC     45.12"]
        right = ["Event 21  Girls 11-12 100 Yard Butterfly", "Heat 1 of 1  Timed Finals",
                 "    5  Garcia, Emma              12 PASA-PC   1:15.33"]
        page = [a.ljust(60) + b for a, b in zip(left, right)]
        self.assertEqual(split_columns(page)[3], right[0])
        program = parse_report_text("\n".join(page))
        self.assertEqual([(entry.event_number, entry.lane, entry.swimmer) for entry in program.entries],
                         [("12", "1", "Jane Smith"), ("21", "5", "Emma Garcia")])

    def test_psych_sheet_lines_have_no_heat_or_lane(self) -> None:
        program = parse_report_text("Event 4  Boys 13 & Over 100 Yard Backstroke\n  1  Lee, Pat  14 PASA-PC  1:02.11Y\n")
        self.assertEqual((program.entries[0].heat, program.entries[0].lane, program.entries[0].swimmer), ("", "", "Pat Lee"))


class FileFormatTests(unittest.TestCase):
    """Format detection and the HTML and PDF readers."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())

    def test_html_pre_report(self) -> None:
        path = self.folder / "heats.htm"
        path.write_text("<html><head><title>x</title></head><body><pre>" + sample_text().replace("&", "&amp;") + "</pre></body></html>")
        self.assertEqual(detect_format(path), constants.MEET_FILE_FORMAT_HTML)
        program, file_format = read_meet_file(path)
        self.assertEqual((file_format, len(program.entries)), (constants.MEET_FILE_FORMAT_HTML, 7))

    def test_html_table_rows_become_lines(self) -> None:
        text = html_text("<table><tr><td>Event 12</td><td>Girls 10 &amp; Under 50 Yard Breaststroke</td></tr></table>")
        self.assertIn("Event 12   Girls 10 & Under 50 Yard Breaststroke", " ".join(text.split("\n")).replace("  ", "  "))

    def test_pdf_report(self) -> None:
        if shutil.which(constants.PDF_TO_TEXT_COMMAND) is None:
            self.skipTest("pdftotext is not installed here")
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("reportlab is not installed here")
        path = self.folder / "heats.pdf"
        pdf = canvas.Canvas(str(path), pagesize=letter)
        pdf.setFont("Courier", 8)
        y = 750
        for line in sample_text().splitlines():
            pdf.drawString(20, y, line)
            y -= 10
        pdf.save()
        program, file_format = read_meet_file(path)
        self.assertEqual(file_format, constants.MEET_FILE_FORMAT_PDF)
        self.assertEqual(len(program.entries), 7)

    def test_nothing_found(self) -> None:
        path = self.folder / "notes.txt"
        path.write_text("Just some notes about the meet.\n")
        with self.assertRaises(MeetFileError):
            read_meet_file(path)


class MeetManagerDatabaseTests(unittest.TestCase):
    """The Hy-Tek database reader, with mdbtools replaced by fake tables."""

    TABLES = {
        "meet": [{"Meet_name1": "Candy Meet"}],
        "team": [{"Team_no": "1", "Team_abbr": "PASA"}, {"Team_no": "2", "Team_abbr": "SCSC"}],
        "athlete": [{"Ath_no": "10", "Last_name": "Smith", "First_name": "Jane", "Pref_name": "", "Team_no": "1", "Ath_age": "10"},
                    {"Ath_no": "11", "Last_name": "Lee", "First_name": "Patrick", "Pref_name": "Pat", "Team_no": "2", "Ath_age": "9"}],
        "event": [{"Event_ptr": "100", "Event_no": "12", "Event_ltr": "", "Event_sex": "F", "Event_dist": "50",
                   "Event_stroke": "C", "Low_age": "0", "High_Age": "10", "Ind_rel": "I"},
                  {"Event_ptr": "101", "Event_no": "13", "Event_ltr": "", "Event_sex": "M", "Event_dist": "200",
                   "Event_stroke": "E", "Low_age": "0", "High_Age": "10", "Ind_rel": "R"}],
        "entry": [{"Event_ptr": "100", "Ath_no": "10", "Fin_heat": "2", "Fin_lane": "4", "Pre_heat": "0", "Pre_lane": "0"}],
        "relay": [{"Relay_no": "7", "Event_ptr": "101", "Team_no": "2", "Team_ltr": "A", "Fin_heat": "1", "Fin_lane": "3"}],
        "relay_names": [{"Relay_no": "7", "Ath_no": "11", "Pos_no": "1"}],
        "session": [{"Sess_no": "1", "Sess_ptr": "500", "Sess_name": "Friday PM", "Sess_day": "1", "Sess_starttime": "46800"}],
        "session_item": [{"Sess_ptr": "500", "Event_ptr": "100"}, {"Sess_ptr": "500", "Event_ptr": "101"}],
    }

    def test_read_database(self) -> None:
        fake = mock.MagicMock()
        fake.table.side_effect = lambda key, warnings: self.TABLES.get(key, [])
        with mock.patch.object(mm_database, "_AccessReader", return_value=fake):
            program = mm_database._read_database(Path("meet.mdb"))
        self.assertEqual(program.meet_name, "Candy Meet")
        self.assertEqual([(event.number, event.description) for event in program.events],
                         [("12", "Girls 10 & Under 50 Breaststroke"), ("13", "Boys 10 & Under 200 Medley Relay")])
        self.assertEqual([(e.event_number, e.heat, e.lane, e.swimmer, e.club) for e in program.entries],
                         [("12", "2", "4", "Jane Smith", "PASA"), ("13", "1", "3", "SCSC-A", "SCSC")])
        self.assertEqual(program.entries[1].relay_swimmers, ["Pat Lee"])
        self.assertEqual((program.sessions[0].name, program.sessions[0].start_time, program.sessions[0].event_numbers),
                         ("Friday PM", "13:00", ["12", "13"]))

    def test_missing_reader_is_explained(self) -> None:
        with mock.patch.object(mm_database.shutil, "which", return_value=None):
            with self.assertRaises(MeetFileError) as raised:
                mm_database._read_database(Path("meet.mdb"))
        self.assertIn("mdbtools", str(raised.exception))

    def test_age_groups(self) -> None:
        self.assertEqual([mm_database.age_group_label(*ages) for ages in ((0, 10), (11, 12), (13, 109), (0, 109))],
                         ["10 & Under", "11-12", "13 & Over", "Open"])


class ProgramStoreAndDqTests(unittest.TestCase):
    """Stored programs: lookups, auto-fill on DQs, event strokes for slip codes."""

    def setUp(self) -> None:
        self.database = Database(Path(tempfile.mkdtemp()) / "test.db")
        self.database.initialize()
        self.programs = MeetProgramStore(self.database)
        self.programs.initialize()
        self.dqs = DqStore(self.database, self.programs)
        self.dqs.initialize()
        self.meet_id = self.database.create_meet("Candy Meet", "2026-10-16")
        self.programs.save(self.meet_id, parse_report_text(sample_text()), constants.MEET_FILE_FORMAT_TEXT, "heats.txt")

    def test_lookup_and_strokes(self) -> None:
        self.assertEqual(self.programs.lookup(self.meet_id, "12", "02", "4")["swimmer"], "Lily Nguyen")
        self.assertIsNone(self.programs.lookup(self.meet_id, "12", "1", "8"))
        self.assertEqual(self.programs.event_strokes(self.meet_id), {"12": "Breaststroke", "21": "Butterfly"})

    def test_dq_is_filled_in_and_never_overwritten(self) -> None:
        dq_id = self.dqs.create_dq({"event": "12", "heat": "2", "lane": "4", "infractions": []}, self.meet_id)
        dq = self.dqs.list_dqs(self.meet_id)[0]
        self.assertEqual((dq["swimmer"], dq["club"], dq["event_label"]), ("Lily Nguyen", "PASA", "Girls 10 & Under 50 Breaststroke"))
        self.dqs.update_dq(dq_id, {"swimmer": "Lilly Nguyen", "lane": "4"})
        dq = self.dqs.list_dqs(self.meet_id)[0]
        self.assertEqual(dq["swimmer"], "Lilly Nguyen")  # typed name kept
        self.assertTrue(dq["lookup_differs"])

    def test_newest_file_is_active(self) -> None:
        newer = parse_report_text(sample_text().replace("Nguyen, Lily", "Tran, Mai"))
        self.programs.save(self.meet_id, newer, constants.MEET_FILE_FORMAT_TEXT, "heats2.txt")
        self.assertEqual(self.programs.lookup(self.meet_id, "12", "2", "4")["swimmer"], "Mai Tran")
        self.assertEqual(len(self.programs.summary(self.meet_id)["history"]), 1)
