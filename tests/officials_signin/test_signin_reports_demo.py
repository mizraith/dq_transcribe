"""Tests for the rotation schedule, the printouts and the demo meet.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import http.client
import json
import random
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.database import Database, Validation
from officials_signin.demo import assign_roles, build_demo, fake_names
from officials_signin.reports import render_meet_summary, render_session_summary, render_team_display
from officials_signin.server import SigninServer
from officials_signin.teams import build_team_view, format_slot_time, rotation_pairs, rotation_schedule

MEET_DATE = date(2026, 10, 16)
LOOPBACK_HOST = "127.0.0.1"
SECRET_MEMBER_ID = "ABC123XYZ9"
DEMO_SEED = 7


class RotationModeTests(unittest.TestCase):
    """The owner's four rotation schemes, slot by slot (start end, turn end)."""

    def test_four_teams_fixed_ends(self) -> None:
        self.assertEqual(rotation_pairs(4, 4, constants.ROTATION_FIXED_ENDS), [(1, 3), (2, 4), (1, 3), (2, 4)])

    def test_four_teams_rotating_ends(self) -> None:
        self.assertEqual(
            rotation_pairs(4, 5, constants.ROTATION_ROTATING_ENDS), [(1, 3), (2, 4), (3, 1), (4, 2), (1, 3)]
        )

    def test_three_teams_rotating(self) -> None:
        # Team 3 bumps 1 at S, 1 walks down and bumps 2 at T; then 2 bumps 3, 3 walks down...
        self.assertEqual(
            rotation_pairs(3, 4, constants.ROTATION_ROTATING_ENDS), [(1, 2), (3, 1), (2, 3), (1, 2)]
        )

    def test_three_teams_fixed_ends(self) -> None:
        # Team 3 relieves 1 at S, then 2 at T, then rests.
        self.assertEqual(rotation_pairs(3, 4, constants.ROTATION_FIXED_ENDS), [(1, 2), (3, 2), (1, 3), (1, 2)])

    def test_every_team_gets_a_break_with_three_teams(self) -> None:
        for mode in constants.ROTATION_MODES:
            on_deck = [set(pair) for pair in rotation_pairs(3, 3, mode)]
            for team in (1, 2, 3):
                self.assertEqual(sum(team in pair for pair in on_deck), 2, (mode, team))

    def test_small_and_empty(self) -> None:
        self.assertEqual(rotation_pairs(2, 2), [(1, 2), (1, 2)])
        self.assertEqual(rotation_pairs(1, 1), [(1, None)])
        self.assertEqual(rotation_pairs(0, 3), [])

    def test_schedule_covers_the_estimated_length(self) -> None:
        rows = rotation_schedule(4, "08:00", 240)
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0], {constants.KEY_TIME: "8:00 AM", constants.KEY_START_END_TEAM: "Team 1",
                                   constants.KEY_TURN_END_TEAM: "Team 3"})
        self.assertEqual(rows[-1][constants.KEY_TIME], "11:30 AM")
        self.assertEqual(len(rotation_schedule(4, "08:00", 100)), 4)  # rounds up to whole slots
        self.assertEqual(len(rotation_schedule(4, "08:00", None)), constants.DEFAULT_SESSION_MINUTES // 30)

    def test_slot_times(self) -> None:
        self.assertEqual(format_slot_time("11:45", 30), "12:15 PM")
        self.assertEqual(format_slot_time("23:30", 60), "12:30 AM")
        self.assertEqual(format_slot_time(None, 90), "+1:30")


class ReportTests(unittest.TestCase):
    """Printouts: right people, escaped, no member IDs."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.database = Database(self.root / "test.db")
        self.database.initialize()
        self.meet_id = self.database.create_meet("Candy <Meet>", MEET_DATE.isoformat())
        self.session_id = self.database.add_session(
            "Friday PM", MEET_DATE.isoformat(), "13:00", "PM", "12:00", 120
        )
        for index in range(7):
            self.sign_in(f"Judge {index}", 20 - index, member_id=SECRET_MEMBER_ID if index == 0 else None)
        self.sign_in('Mark "Red" Byer', 12, role="Starter")

    def sign_in(self, name: str, years: int, role: str = constants.TEAM_POOL_ROLE, member_id: str | None = None) -> None:
        official = self.database.save_official(None, name, years, None, None, MEET_DATE)
        if member_id:
            with self.database._connect() as connection:  # noqa: SLF001 (as a card read would store it)
                connection.execute("UPDATE officials SET member_id = ? WHERE id = ?", (member_id, official))
        validation = {self.session_id: Validation(True, constants.VALIDATION_CAMERA, [])}
        self.database.sign_in(official, [self.session_id], [role], False, validation)

    def pages(self) -> list[str]:
        meet = self.database.get_state()[constants.KEY_MEET]
        session = self.database.get_session(self.session_id)
        signins = self.database.list_signins(self.session_id)
        return [
            render_session_summary(meet, session, signins).decode(),
            render_meet_summary(meet, [(session, signins)]).decode(),
            render_team_display(meet, session, build_team_view(signins, session), len(signins)).decode(),
        ]

    def test_names_escaped_and_no_member_ids(self) -> None:
        for page in self.pages():
            self.assertIn("Candy &lt;Meet&gt;", page)
            self.assertNotIn("<Meet>", page)
            self.assertNotIn(SECRET_MEMBER_ID, page)
        self.assertIn("Mark &quot;Red&quot; Byer", self.pages()[0])

    def test_session_summary_lists_everyone(self) -> None:
        page = self.pages()[0]
        for index in range(7):
            self.assertIn(f"Judge {index}", page)
        self.assertIn("8 officials", page)
        self.assertIn("officials meeting 12:00 PM", page)

    def test_team_display_before_teams_are_built(self) -> None:
        page = self.pages()[2]
        self.assertIn("No teams yet", page)
        self.assertIn("8 officials", page)  # everyone signed in, even before teams exist


class DemoBuildTests(unittest.TestCase):
    """The demo meet itself."""

    def test_fake_names_are_distinct(self) -> None:
        names = fake_names(40, random.Random(DEMO_SEED))
        self.assertEqual(len(set(names)), 40)

    def test_roles(self) -> None:
        roles = assign_roles(3, 1, head_officials=True)
        self.assertEqual(len(roles), len(constants.DEMO_SPECIAL_ROLES) + 4)
        self.assertEqual(roles[-1], (constants.TEAM_POOL_ROLE, True))
        self.assertEqual(len(assign_roles(3, 1, head_officials=False)), 4)

    def test_build(self) -> None:
        path = Path(tempfile.mkdtemp()) / "demo.db"
        database = build_demo(path, 13, 2, 3, True, MEET_DATE, seed=DEMO_SEED)
        state = database.get_state()
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], constants.DEMO_MEET_NAME)
        self.assertEqual(len(state[constants.KEY_SESSIONS]), 3)
        first = state[constants.KEY_SESSIONS][0]
        self.assertEqual(first["signin_count"], 13 + 2 + len(constants.DEMO_SPECIAL_ROLES))
        signins = database.list_signins(first[constants.KEY_ID])
        self.assertEqual(sum(not signin[constants.KEY_VALIDATED] for signin in signins), constants.DEMO_NEEDS_ADMIN_COUNT)
        # Building again replaces the demo rather than adding to it.
        again = build_demo(path, 4, 0, 1, False, MEET_DATE, seed=DEMO_SEED)
        self.assertEqual(len(again.get_state()[constants.KEY_SESSIONS]), 1)


class DemoServerTests(unittest.TestCase):
    """Demo mode is per browser (cookie); the real meet and the roster stay untouched."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.database = Database(self.root / "real.db")
        self.database.initialize()
        self.database.create_meet("Real Meet", MEET_DATE.isoformat())
        self.server = SigninServer(
            (LOOPBACK_HOST, 0), self.database,
            diagnostics_directory=self.root / "diagnostics", demo_database_path=self.root / "demo.db",
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, cookie: str | None = None
                ) -> tuple[int, Any, dict[str, str]]:
        """Send a request (optionally with a Cookie header); return status, body, headers."""
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.server.server_address[1], timeout=30)
        headers = {} if body is None else {constants.CONTENT_TYPE_HEADER: constants.JSON_CONTENT_TYPE}
        if cookie:
            headers[constants.COOKIE_HEADER] = cookie
        connection.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            decoded: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = raw
        return response.status, decoded, dict(response.getheaders())

    def start_demo(self) -> str:
        body = {constants.KEY_JUDGES_COUNT: 13, constants.KEY_TRAINEES_COUNT: 2,
                constants.KEY_SESSIONS_COUNT: 2, constants.KEY_HEAD_OFFICIALS: True}
        status, reply, headers = self.request("POST", constants.ROUTE_DEMO_START, body)
        self.assertEqual(status, 200, reply)
        return headers[constants.SET_COOKIE_HEADER].split(";")[0]

    def test_demo_is_separate_from_the_real_meet(self) -> None:
        cookie = self.start_demo()
        _, demo_state, _ = self.request("GET", constants.ROUTE_STATE, cookie=cookie)
        self.assertTrue(demo_state[constants.KEY_DEMO])
        self.assertEqual(demo_state[constants.KEY_MEET][constants.KEY_NAME], constants.DEMO_MEET_NAME)
        _, real_state, _ = self.request("GET", constants.ROUTE_STATE)
        self.assertFalse(real_state[constants.KEY_DEMO])
        self.assertEqual(real_state[constants.KEY_MEET][constants.KEY_NAME], "Real Meet")

    def test_demo_printouts_and_teams(self) -> None:
        cookie = self.start_demo()
        status, view, _ = self.request("POST", constants.ROUTE_TEAMS_BUILD, {}, cookie=cookie)
        self.assertEqual(status, 200, view)
        status, view, _ = self.request(
            "POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_ROTATION_MODE: constants.ROTATION_ROTATING_ENDS},
            cookie=cookie,
        )
        self.assertEqual(view[constants.KEY_ROTATION_MODE], constants.ROTATION_ROTATING_ENDS)
        self.assertEqual(view[constants.KEY_ROTATION_SCHEDULE][2][constants.KEY_START_END_TEAM], "Team 3")
        for route in (constants.ROUTE_PRINT_SESSION, constants.ROUTE_PRINT_MEET, constants.ROUTE_TEAM_DISPLAY):
            status, page, _ = self.request("GET", route, cookie=cookie)
            self.assertEqual(status, 200, route)
            self.assertIn(constants.DEMO_MEET_NAME.encode(), page)
        _, display, _ = self.request("GET", constants.ROUTE_TEAM_DISPLAY, cookie=cookie)
        times = [row[constants.KEY_TIME] for row in view[constants.KEY_ROTATION_SCHEDULE]]
        self.assertEqual(len(times), constants.DEFAULT_SESSION_MINUTES // constants.ROTATION_MINUTES)
        for time in times:
            self.assertIn(time.encode(), display)

    def test_bad_rotation_mode_refused(self) -> None:
        cookie = self.start_demo()
        status, _, _ = self.request("POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_ROTATION_MODE: "sideways"},
                                    cookie=cookie)
        self.assertEqual(status, 400)

    def test_exit_clears_the_cookie(self) -> None:
        cookie = self.start_demo()
        status, _, headers = self.request("POST", constants.ROUTE_DEMO_EXIT, {}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(constants.DEMO_COOKIE_NAME, headers[constants.SET_COOKIE_HEADER])


if __name__ == "__main__":
    unittest.main()
