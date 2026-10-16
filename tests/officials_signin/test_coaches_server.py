"""Coaches Sign-In through HTTP: card reading, sign-in, head coaches, edits, printouts, demo.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.coaches import list_coach_signins
from officials_signin.database import Database
from officials_signin.server import SigninServer
from test_signin_card_reader import CLEAN_CARD_TEXT, FAKE_MEMBER_ID
import test_signin_reports_demo as demo_tests  # module import, so its tests are not collected twice

MEET_DATE = date(2026, 10, 16)
LOOPBACK_HOST = "127.0.0.1"


class CoachesServerTests(unittest.TestCase):
    """The coaches page shares the meet and sessions; coaches never touch the officials' data."""

    request = demo_tests.DemoServerTests.request

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.database = Database(self.root / "real.db")
        self.database.initialize()
        self.database.create_meet("Real Meet", MEET_DATE.isoformat())
        self.morning = self.database.add_session("Friday AM", MEET_DATE.isoformat(), "08:00", "AM", "07:00")
        self.evening = self.database.add_session("Friday PM", MEET_DATE.isoformat(), "13:00", "PM", "12:00")
        self.server = SigninServer(
            (LOOPBACK_HOST, 0), self.database,
            diagnostics_directory=self.root / "diagnostics", demo_database_path=self.root / "demo.db",
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def post(self, path: str, body: dict[str, Any], cookie: str | None = None) -> tuple[int, Any]:
        status, reply, _ = self.request("POST", path, body, cookie=cookie)
        return status, reply

    def state(self, cookie: str | None = None) -> dict[str, Any]:
        return self.request("GET", constants.ROUTE_COACHES_STATE, cookie=cookie)[1]

    def sign_in_by_name(self, name: str, club: str, head: bool = False) -> int:
        status, reply = self.post(constants.ROUTE_COACHES_SIGNINS, {
            constants.KEY_NAME: name, constants.KEY_CLUB: club, constants.KEY_HEAD_COACH: head,
        })
        self.assertEqual(status, 200, reply)
        return reply[constants.KEY_SIGNINS][0]

    def coach_action(self, signin_id: int, suffix: str, body: dict[str, Any] | None = None) -> int:
        return self.post(f"{constants.ROUTE_COACH_SIGNIN_PREFIX}{signin_id}{suffix}", body or {})[0]

    def test_page_and_state_share_the_meet(self) -> None:
        status, page, _ = self.request("GET", constants.ROUTE_COACHES)
        self.assertEqual(status, 200)
        self.assertIn(b"COACHES", page)
        state = self.state()
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], "Real Meet")
        self.assertEqual([s[constants.KEY_NAME] for s in state[constants.KEY_SESSIONS]], ["Friday AM", "Friday PM"])
        self.assertEqual(state[constants.KEY_COACHES], [])

    def test_sign_in_by_name_needs_the_admin_then_looks_good(self) -> None:
        signin_id = self.sign_in_by_name("Casey Coach", "pasa")
        coach = self.state()[constants.KEY_COACHES][0]
        self.assertEqual((coach[constants.KEY_NAME], coach[constants.KEY_CLUB]), ("Casey Coach", "PASA"))
        self.assertFalse(coach[constants.KEY_VALIDATED])
        self.assertFalse(coach[constants.KEY_HEAD_COACH])  # off by default
        self.assertEqual(self.coach_action(signin_id, constants.SIGNIN_VALIDATE_SUFFIX), 200)
        coach = self.state()[constants.KEY_COACHES][0]
        self.assertTrue(coach[constants.KEY_VALIDATED])
        self.assertEqual(coach[constants.KEY_VALIDATION_METHOD], constants.VALIDATION_VISUAL)

    def test_several_head_coaches_per_club(self) -> None:
        first = self.sign_in_by_name("Avery Agegroup", "PASA")
        second = self.sign_in_by_name("Blake Senior", "PASA")
        self.coach_action(first, constants.COACH_HEAD_SUFFIX, {constants.KEY_HEAD_COACH: True})
        self.coach_action(second, constants.COACH_HEAD_SUFFIX, {constants.KEY_HEAD_COACH: True})
        heads = [c[constants.KEY_NAME] for c in self.state()[constants.KEY_COACHES] if c[constants.KEY_HEAD_COACH]]
        self.assertEqual(sorted(heads), ["Avery Agegroup", "Blake Senior"])
        self.coach_action(first, constants.COACH_HEAD_SUFFIX, {constants.KEY_HEAD_COACH: False})
        heads = [c[constants.KEY_NAME] for c in self.state()[constants.KEY_COACHES] if c[constants.KEY_HEAD_COACH]]
        self.assertEqual(heads, ["Blake Senior"])

    def test_card_sign_in_validates_and_hides_the_member_id(self) -> None:
        status, reading = self.post(constants.ROUTE_COACHES_CARD_READING, {constants.KEY_TEXTS: [CLEAN_CARD_TEXT] * 2})
        self.assertEqual(status, 200)
        self.assertTrue(reading[constants.KEY_VALIDATED])
        self.assertIsNone(reading[constants.KEY_MATCH])
        status, reply = self.post(constants.ROUTE_COACHES_SIGNINS, {
            constants.KEY_CARD: reading[constants.KEY_CARD], constants.KEY_HEAD_COACH: True,
            constants.KEY_SESSION_IDS: [self.morning, self.evening],
        })
        self.assertEqual(status, 200, reply)
        self.assertTrue(reply[constants.KEY_VALIDATED])
        self.assertEqual(len(list_coach_signins(self.database, self.evening)), 1)
        for path in (constants.ROUTE_COACHES_STATE, constants.ROUTE_COACHES_KNOWN):
            _, body, _ = self.request("GET", path)
            self.assertNotIn(FAKE_MEMBER_ID, json.dumps(body))
        # A second scan recognises the coach.
        _, again = self.post(constants.ROUTE_COACHES_CARD_READING, {constants.KEY_TEXTS: [CLEAN_CARD_TEXT]})
        self.assertEqual(again[constants.KEY_MATCH][constants.KEY_NAME], 'Pat "Skip" Example')

    def test_coaches_are_not_officials(self) -> None:
        self.sign_in_by_name("Casey Coach", "PASA")
        self.assertEqual(self.database.list_signins(self.morning), [])
        _, view, _ = self.request("GET", constants.ROUTE_TEAMS)
        self.assertEqual(view[constants.KEY_JUDGE_COUNT], 0)

    def test_edit_and_remove(self) -> None:
        signin_id = self.sign_in_by_name("Casy Coach", "PASA")
        status = self.coach_action(signin_id, constants.SIGNIN_EDIT_SUFFIX, {
            constants.KEY_NAME: "Casey Coach", constants.KEY_CLUB: "DACA", constants.KEY_HEAD_COACH: True,
        })
        self.assertEqual(status, 200)
        coach = self.state()[constants.KEY_COACHES][0]
        self.assertEqual((coach[constants.KEY_NAME], coach[constants.KEY_CLUB], coach[constants.KEY_HEAD_COACH]),
                         ("Casey Coach", "DACA", True))
        self.assertEqual(self.coach_action(signin_id, constants.SIGNIN_REMOVE_SUFFIX), 200)
        self.assertEqual(self.state()[constants.KEY_COACHES], [])
        known = self.request("GET", constants.ROUTE_COACHES_KNOWN)[1][constants.KEY_COACHES]
        self.assertEqual([coach[constants.KEY_NAME] for coach in known], ["Casey Coach"])  # stays known
        self.assertEqual(self.coach_action(999, constants.SIGNIN_REMOVE_SUFFIX), 404)

    def test_counts_printouts_and_zip(self) -> None:
        self.sign_in_by_name("Avery Agegroup", "PASA", head=True)
        self.sign_in_by_name("Blake Senior", "DACA")
        counts = {s[constants.KEY_NAME]: s[constants.KEY_COACH_COUNT] for s in self.state()[constants.KEY_SESSIONS]}
        self.assertEqual(counts, {"Friday AM": 2, "Friday PM": 0})
        _, page, _ = self.request("GET", constants.ROUTE_COACHES_PRINT_SESSION)
        self.assertIn(b"Avery Agegroup", page)
        self.assertIn(b"1 head coach", page)
        self.assertLess(page.index(b"DACA"), page.index(b"PASA"))  # by club
        status, _, _ = self.request("GET", constants.ROUTE_COACHES_PRINT_MEET)
        self.assertEqual(status, 200)
        _, body, _ = self.request("GET", constants.ROUTE_MEET_ZIP)
        coaches_csv = zipfile.ZipFile(io.BytesIO(body)).read("real-meet/coaches.csv").decode()
        self.assertIn("Avery Agegroup", coaches_csv)

    def test_deleting_a_session_removes_its_coaches(self) -> None:
        self.sign_in_by_name("Casey Coach", "PASA")
        self.database.delete_session(self.morning)
        self.assertEqual(list_coach_signins(self.database, self.morning), [])

    def test_demo_has_made_up_coaches_with_head_coaches(self) -> None:
        row = {constants.KEY_JUDGES_COUNT: 6, constants.KEY_TRAINEES_COUNT: 0}
        _, _, headers = self.request("POST", constants.ROUTE_DEMO_START,
                                     {constants.KEY_SESSIONS: [row, row], constants.KEY_CORNER_OFFICIALS: False})
        cookie = headers[constants.SET_COOKIE_HEADER].split(";")[0]
        coaches = self.state(cookie)[constants.KEY_COACHES]
        self.assertGreaterEqual(len(coaches), len(constants.DEMO_CLUB_CODES))
        self.assertTrue(any(coach[constants.KEY_HEAD_COACH] for coach in coaches))
        self.assertEqual(self.state()[constants.KEY_COACHES], [])  # the real meet has none


if __name__ == "__main__":
    unittest.main()
