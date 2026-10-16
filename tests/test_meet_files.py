"""Tests for reading Meet Manager files and using them for DQs.

Uses a hand-written heat sheet in Hy-Tek's usual layout (tests/data/). The real
files from the owner's meet will replace or extend these samples.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests
"""

from __future__ import annotations

import re
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
        "event": [{"Event_ptr": "100", "Event_no": "12", "Event_ltr": "", "Event_sex": "G", "Event_gender": "F", "Event_dist": "50",
                   "Event_stroke": "C", "Low_age": "0", "High_Age": "10", "Ind_rel": "I"},
                  {"Event_ptr": "101", "Event_no": "13", "Event_ltr": "", "Event_sex": "B", "Event_gender": "M", "Event_dist": "200",
                   "Event_stroke": "E", "Low_age": "0", "High_Age": "10", "Ind_rel": "R"}],
        "entry": [{"Event_ptr": "100", "Ath_no": "10", "Fin_heat": "2", "Fin_lane": "4", "Pre_heat": "0", "Pre_lane": "0", "ConvSeed_time": "71.52"}],
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
                         ["10 & Under", "11-12", "13+", None])


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


class MeetSheetTests(unittest.TestCase):
    """Reading meet sheets (announcements) to set up a meet."""

    def test_two_column_candy_sheet(self) -> None:
        from dq_transcribe.meet_files.meet_sheet import read_meet_sheet_text
        sheet = read_meet_sheet_text((Path(__file__).parent / "data" / "sample_meet_sheet_candy.txt").read_text())
        self.assertEqual((sheet.name, sheet.start_date.isoformat(), sheet.course), ("PASA All Treats No Tricks Candy Meet Block Party", "2026-10-16", "Yard"))
        self.assertEqual(len(sheet.events), 26)  # 13 lines, girls' and boys' numbers
        self.assertEqual((sheet.events[0].short_label, sheet.events[3].short_label, sheet.events[25].short_label),
                         ("Girls 100 Freestyle", "Boys 8 & Under 25 Freestyle", "Boys 100 Individual Medley"))
        self.assertEqual((sheet.sessions[0].start_time, sheet.sessions[0].name), ("16:45", "Friday 4:45 PM (warm-up 4:00 PM)"))
        self.assertEqual(sheet.officials, [])
        self.assertEqual(len(sheet.dates), 1)  # the entry deadline (October 14) is not a meet day

    def test_sheet_with_officials_and_sessions(self) -> None:
        from dq_transcribe.meet_files.meet_sheet import read_meet_sheet_text
        sheet = read_meet_sheet_text((Path(__file__).parent / "data" / "sample_meet_sheet_full.txt").read_text())
        self.assertEqual([day.isoformat() for day in sheet.dates], ["2026-11-06", "2026-11-07", "2026-11-08"])
        self.assertEqual([(item["name"], item["role"]) for item in sheet.officials],
                         [("Jordan Example", None), ("Pat Sample", "Meet Referee"), ("Robin Placeholder", "Admin Official"), ("Casey Demo", "Starter")])
        self.assertEqual([(session.day, session.start_time) for session in sheet.sessions],
                         [("2026-11-06", "17:00"), ("2026-11-07", "08:00"), ("2026-11-08", "08:00")])
        self.assertEqual(sheet.missing, [])

    def test_google_links_become_downloads(self) -> None:
        from dq_transcribe.meet_files.meet_sheet import download_address
        self.assertEqual(download_address("https://docs.google.com/document/u/0/d/AbC_1-x/mobilebasic"),
                         "https://docs.google.com/document/d/AbC_1-x/export?format=txt")
        self.assertEqual(download_address("https://drive.google.com/file/d/XyZ/view?usp=sharing"),
                         "https://drive.google.com/uc?export=download&id=XyZ")


class RealLayoutTests(unittest.TestCase):
    """A real Hy-Tek Meet Manager 8 meet program (names replaced) in 1, 2 and 3 columns, HTML and PDF."""

    FIXTURE = Path(__file__).parent / "data" / "hytek_meet_program.htm"

    def single_column(self):
        """The fixture read as HTML (the reference result)."""
        program, file_format = read_meet_file(self.FIXTURE)
        self.assertEqual(file_format, constants.MEET_FILE_FORMAT_HTML)
        return program

    @staticmethod
    def entries(program) -> dict:
        return {(e.event_number, e.heat, e.lane): (e.swimmer, e.club, e.age, e.seed_time) for e in program.entries}

    def test_html_report(self) -> None:
        program = self.single_column()
        self.assertEqual(program.meet_name, "Example Candy Meet Block Party")
        self.assertEqual((len(program.events), len(program.entries), program.summary()["heats"], program.warnings), (26, 538, 78, []))
        first = program.entries[0]
        self.assertEqual((first.event_number, first.heat, first.lane, first.club, first.age, first.seed_time), ("1", "1", "1", "EXSC", 14, "1:11.52"))
        self.assertEqual([event.short_label for event in program.events[:3]], ["Girls 100 Freestyle", "Boys 100 Freestyle", "Girls 8 & Under 25 Freestyle"])

    def _columns(self, columns: int) -> str:
        """The report re-laid out with N columns per page, as pdftotext -layout prints such pages."""
        from dq_transcribe.meet_files.html_report import html_text
        lines = [line for line in html_text(self.FIXTURE.read_text()).splitlines()]
        rows_per_column, width = 45, 84
        pages = []
        per_page = rows_per_column * columns
        for start in range(0, len(lines), per_page):
            chunk = lines[start:start + per_page]
            parts = [chunk[index:index + rows_per_column] for index in range(0, len(chunk), rows_per_column)]
            page = []
            for row in range(rows_per_column):
                page.append("".join((part[row] if row < len(part) else "").ljust(width) for part in parts).rstrip())
            pages.append("\n".join(page))
        return "\f".join(pages)

    def test_two_and_three_columns_read_the_same(self) -> None:
        reference = self.entries(self.single_column())
        for columns in (2, 3):
            program = parse_report_text(self._columns(columns))
            self.assertEqual(self.entries(program), reference, f"{columns} columns")

    def test_pdf_with_result_blanks(self) -> None:
        if shutil.which(constants.PDF_TO_TEXT_COMMAND) is None:
            self.skipTest("pdftotext is not installed here")
        try:
            from reportlab.lib.pagesizes import landscape, letter
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest("reportlab is not installed here")
        from dq_transcribe.meet_files.html_report import html_text
        folder = Path(tempfile.mkdtemp())
        path = folder / "program.pdf"
        pdf = canvas.Canvas(str(path), pagesize=landscape(letter))
        pdf.setFont("Courier", 7)
        y = 580
        for line in html_text(self.FIXTURE.read_text()).splitlines():
            if re.match(r"^\s{1,3}\d{1,2}\s", line):
                line = line.rstrip() + "     _________________    _______"  # a printed heat sheet's result blanks
            pdf.drawString(20, y, line)
            y -= 8.5
            if y < 20:
                pdf.showPage()
                pdf.setFont("Courier", 7)
                y = 580
        pdf.save()
        program, file_format = read_meet_file(path)
        self.assertEqual(file_format, constants.MEET_FILE_FORMAT_PDF)
        self.assertEqual(self.entries(program), self.entries(self.single_column()))


class RealMeetSheetTests(unittest.TestCase):
    """Real meet sheets (public announcements, 2025-2026): the PDFs as pdftotext -layout text, and a Word file."""

    FOLDER = Path(__file__).parent / "data" / "meet_sheets"
    # file: (start date, days, course, event count, sessions as (day, start, warm-up or ""), officials as (title, name))
    EXPECTED = {
        "bac_cba.txt": ("2025-06-06", 3, "Meter", 51,
                        [("2025-06-06", "16:30", "15:30"), ("2025-06-07", "08:30", "07:00"), ("2025-06-07", "12:00", ""),
                         ("2025-06-08", "08:30", "07:00"), ("2025-06-08", "12:00", "")],
                        {("Meet Referee", "Manus J-Cheng"), ("Meet Referee", "Lucille Glassman"), ("Admin Official", "Carol Waln"),
                         ("Head Starter", "Jeff Hu"), ("Meet Director", "Tommy Dowley")}),
        "cal.txt": ("2025-01-11", 2, "Yard", 28,
                    [("2025-01-11", "09:00", "07:30"), ("2025-01-11", "13:00", ""), ("2025-01-12", "09:00", "07:30"), ("2025-01-12", "13:00", "")],
                    {("Meet Referee", "Leo Lin"), ("Admin Ref", "Christopher Lam"), ("Head Starter", "Mark Ryan")}),
        "pasa_cba.txt": ("2026-02-07", 2, "Yard", 38,
                         [("2026-02-07", "09:00", "07:30"), ("2026-02-08", "09:00", "07:30")],
                         {("Meet Referee", "Lucille Glassman"), ("Admin Official", "Amer Mirza"), ("Head Starter", "Manus J-Cheng")}),
        "spring_ag.txt": ("2025-03-14", 3, "Yard", 100,
                          [("2025-03-14", "09:00", "07:15"), ("2025-03-15", "09:00", "07:15"), ("2025-03-16", "09:00", "07:15")],
                          {("Meet Referee", "Mike Piccardo"), ("Admin Official", "Angela Cardenas"), ("Head Starter", "Mette Graversen")}),
        "vjo.txt": ("2025-05-30", 3, "Meter", 62,
                    [("2025-05-30", "17:00", "15:30"), ("2025-05-31", "09:00", "07:30"), ("2025-06-01", "09:00", "07:30")],
                    {("Meet Referee", "Don Bautista"), ("Admin Official", "Mike Abegg"), ("Head Starter", "Lesley Ruszel")}),
        "happy_fall.txt": ("2025-10-11", 2, "Yard", 31, [("2025-10-11", "09:00", "08:00"), ("2025-10-12", "09:00", "08:00")], set()),
        "merced.docx": ("2026-04-25", 2, "Meter", 68, [("2026-04-25", "09:00", "07:30"), ("2026-04-26", "09:00", "07:30")], set()),
    }

    def test_real_sheets(self) -> None:
        from dq_transcribe.meet_files.meet_sheet import read_meet_sheet_file
        for name, (start, days, course, event_count, sessions, officials) in self.EXPECTED.items():
            with self.subTest(sheet=name):
                sheet = read_meet_sheet_file(self.FOLDER / name)
                self.assertEqual((sheet.start_date.isoformat(), len(sheet.dates), sheet.course, len(sheet.events)),
                                 (start, days, course, event_count))
                found_sessions = [(item.day, item.start_time, re.sub(r".*warm-up (.*)\)", r"\1", item.name) if "warm-up" in item.name else "")
                                  for item in sheet.sessions]
                expected_sessions = [(day, begin, _twelve(warmup) if warmup else "") for day, begin, warmup in sessions]
                self.assertEqual(found_sessions, expected_sessions)
                self.assertTrue(officials <= {(item["title"], item["name"]) for item in sheet.officials})

    def test_titles(self) -> None:
        from dq_transcribe.meet_files.meet_sheet import read_meet_sheet_file
        self.assertEqual(read_meet_sheet_file(self.FOLDER / "pasa_cba.txt").name,
                         "PACIFIC SWIMMING SHORT COURSE C/B/A+ MEET (PALO ALTO STANFORD AQUATICS)")
        self.assertEqual(read_meet_sheet_file(self.FOLDER / "cal.txt").name, "CAL Invitational Swim Meet")
        events = read_meet_sheet_file(self.FOLDER / "merced.docx").events
        self.assertEqual([event.short_label for event in events[:4]],
                         ["Girls 13+ 200 Freestyle", "Boys 13+ 200 Freestyle", "Girls 11-12 200 Freestyle", "Boys 11-12 200 Freestyle"])


def _twelve(clock: str) -> str:
    """"07:30" -> "7:30 AM"."""
    from datetime import datetime
    return datetime.strptime(clock, "%H:%M").strftime("%I:%M %p").lstrip("0")



if __name__ == "__main__":
    unittest.main()
