"""Tests for the rotation schedule, the printouts and the demo meet.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import http.client
import json
import random
import sys
import types
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.database import Database, Validation
from officials_signin.demo import DemoSize, SessionSize, build_demo, demo_years, fake_names, stored_demo_size
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
        self.sign_in('Pat "Skip" Sample', 12, role="Starter")

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
        self.assertIn("Pat &quot;Skip&quot; Sample", self.pages()[0])

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

    def test_years_are_mostly_short_and_capped(self) -> None:
        generator = random.Random(DEMO_SEED)
        years = [demo_years(generator, head_official=False) for _ in range(2000)]
        self.assertLessEqual(max(years), 15)
        self.assertGreater(sum(1 for value in years if value <= 3) / len(years), 0.5)
        self.assertLess(sum(1 for value in years if value >= 10) / len(years), 0.08)
        heads = [demo_years(generator, head_official=True) for _ in range(200)]
        self.assertGreaterEqual(min(heads), constants.DEMO_HEAD_OFFICIAL_MIN_YEARS)

    def test_build_gives_each_session_exactly_what_was_asked(self) -> None:
        path = Path(tempfile.mkdtemp()) / "demo.db"
        size = DemoSize((SessionSize(11, 2), SessionSize(8, 0), SessionSize(14, 1)), corner_officials=True)
        database = build_demo(path, size, MEET_DATE, seed=DEMO_SEED)
        state = database.get_state()
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], constants.DEMO_MEET_NAME)
        corners = len(constants.DEMO_SPECIAL_ROLES)
        for session, wanted in zip(state[constants.KEY_SESSIONS], size.sessions):
            signins = database.list_signins(session[constants.KEY_ID])
            stroke_and_turn = [signin for signin in signins if signin[constants.KEY_ROLES] == [constants.TEAM_POOL_ROLE]]
            self.assertEqual(sum(not signin[constants.KEY_TRAINEE] for signin in stroke_and_turn), wanted.judges)
            self.assertEqual(sum(bool(signin[constants.KEY_TRAINEE]) for signin in stroke_and_turn), wanted.trainees)
            self.assertEqual(len(signins), wanted.judges + wanted.trainees + corners)
        first = database.list_signins(state[constants.KEY_SESSIONS][0][constants.KEY_ID])
        self.assertEqual(sum(not signin[constants.KEY_VALIDATED] for signin in first), constants.DEMO_NEEDS_ADMIN_COUNT)
        later = database.list_signins(state[constants.KEY_SESSIONS][1][constants.KEY_ID])
        self.assertTrue(all(signin[constants.KEY_VALIDATED] for signin in later))
        self.assertEqual(stored_demo_size(database), size)
        # Building again replaces the demo rather than adding to it.
        again = build_demo(path, DemoSize((SessionSize(4, 0),), False), MEET_DATE, seed=DEMO_SEED)
        self.assertEqual(len(again.get_state()[constants.KEY_SESSIONS]), 1)
        self.assertEqual(again.get_state()[constants.KEY_SESSIONS][0]["signin_count"], 4)

    def test_size_checks(self) -> None:
        with self.assertRaises(ValueError):
            DemoSize.from_payload({constants.KEY_SESSIONS: []})
        with self.assertRaises(ValueError):
            DemoSize.from_payload({constants.KEY_SESSIONS: [
                {constants.KEY_JUDGES_COUNT: constants.DEMO_MAX_JUDGES + 1, constants.KEY_TRAINEES_COUNT: 0}]})


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
        row = {constants.KEY_JUDGES_COUNT: 13, constants.KEY_TRAINEES_COUNT: 2}
        body = {constants.KEY_SESSIONS: [row, row], constants.KEY_CORNER_OFFICIALS: True}
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

    def test_demo_page_starts_from_the_current_size(self) -> None:
        cookie = self.start_demo()
        status, page, _ = self.request("GET", constants.ROUTE_DEMO, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertNotIn(b"$", page.replace(b"$$", b""))
        self.assertIn(b'"judge_count": 13', page)

    def test_team_page_has_back_to_teams_and_bold_mode(self) -> None:
        cookie = self.start_demo()
        self.request("POST", constants.ROUTE_TEAMS_BUILD, {}, cookie=cookie)
        _, page, _ = self.request("GET", constants.ROUTE_TEAM_DISPLAY, cookie=cookie)
        self.assertIn(f"/?{constants.OPEN_QUERY_KEY}={constants.OPEN_TEAMS_VALUE}".encode(), page)
        self.assertIn(b"<strong>Fixed ends</strong>", page)

    def test_unchecked_judge_is_kept_off_the_teams(self) -> None:
        cookie = self.start_demo()
        _, view, _ = self.request("POST", constants.ROUTE_TEAMS_BUILD, {}, cookie=cookie)
        self.assertEqual(view[constants.KEY_JUDGE_COUNT], 13 - constants.DEMO_NEEDS_ADMIN_COUNT)
        self.assertEqual(len(view[constants.KEY_AWAITING_CHECK]), constants.DEMO_NEEDS_ADMIN_COUNT)
        waiting = view[constants.KEY_AWAITING_CHECK][0][constants.KEY_ID]
        placed = [member[constants.KEY_ID] for team in view[constants.KEY_TEAMS] for member in team[constants.KEY_MEMBERS]]
        placed += [member[constants.KEY_ID] for member in view[constants.KEY_EXTRAS]]
        self.assertNotIn(waiting, placed)
        # Once checked ("Looks good"), they show up as not placed yet.
        self.request("POST", f"{constants.ROUTE_SIGNIN_PREFIX}{waiting}{constants.SIGNIN_VALIDATE_SUFFIX}", {},
                     cookie=cookie)
        _, view, _ = self.request("GET", constants.ROUTE_TEAMS, cookie=cookie)
        self.assertEqual(view[constants.KEY_AWAITING_CHECK], [])
        self.assertEqual([member[constants.KEY_ID] for member in view[constants.KEY_UNPLACED]], [waiting])

    def test_bad_rotation_mode_refused(self) -> None:
        cookie = self.start_demo()
        status, _, _ = self.request("POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_ROTATION_MODE: "sideways"},
                                    cookie=cookie)
        self.assertEqual(status, 400)

    def test_meet_overview_lists_real_meets_and_switches(self) -> None:
        first = self.database.list_meets()[0][constants.KEY_ID]
        second = self.database.create_meet("Second Meet", "2026-11-01")
        self.database.add_session("Saturday AM", "2026-11-01", "08:00", "AM", "07:00")
        _, overview, _ = self.request("GET", constants.ROUTE_MEETS)
        self.assertEqual([meet[constants.KEY_NAME] for meet in overview[constants.KEY_MEETS]], ["Second Meet", "Real Meet"])
        self.assertEqual(overview[constants.KEY_ACTIVE_MEET_ID], second)
        self.assertEqual(overview[constants.KEY_MEETS][0][constants.KEY_SESSIONS_COUNT], 1)
        self.assertFalse(overview[constants.KEY_DEMO_READY])
        status, _, _ = self.request("POST", f"{constants.ROUTE_MEET_PREFIX}{first}{constants.MEET_OPEN_SUFFIX}", {})
        self.assertEqual(status, 200)
        _, state, _ = self.request("GET", constants.ROUTE_STATE)
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], "Real Meet")
        status, _, _ = self.request("POST", f"{constants.ROUTE_MEET_PREFIX}999{constants.MEET_OPEN_SUFFIX}", {})
        self.assertEqual(status, 400)

    def test_open_meet_picks_todays_or_next_session(self) -> None:
        meet = self.database.create_meet("Two Day", "2026-10-16")
        friday = self.database.add_session("Friday PM", "2026-10-16", "13:00", "PM", "12:00")
        saturday = self.database.add_session("Saturday AM", "2026-10-17", "08:00", "AM", "07:00")
        self.database.open_meet(meet, date(2026, 10, 17))
        self.assertEqual(self.database.get_state()[constants.KEY_ACTIVE_SESSION_ID], saturday)
        self.database.open_meet(meet, date(2026, 10, 1))
        self.assertEqual(self.database.get_state()[constants.KEY_ACTIVE_SESSION_ID], friday)
        self.database.open_meet(meet, date(2026, 12, 1))  # meet is over: its last session
        self.assertEqual(self.database.get_state()[constants.KEY_ACTIVE_SESSION_ID], saturday)

    def test_overview_from_demo_still_lists_real_meets(self) -> None:
        cookie = self.start_demo()
        _, overview, _ = self.request("GET", constants.ROUTE_MEETS, cookie=cookie)
        self.assertTrue(overview[constants.KEY_DEMO])
        self.assertTrue(overview[constants.KEY_DEMO_READY])
        self.assertEqual([meet[constants.KEY_NAME] for meet in overview[constants.KEY_MEETS]], ["Real Meet"])
        # Opening a real meet leaves demo mode.
        meet_id = overview[constants.KEY_MEETS][0][constants.KEY_ID]
        _, _, headers = self.request("POST", f"{constants.ROUTE_MEET_PREFIX}{meet_id}{constants.MEET_OPEN_SUFFIX}", {},
                                     cookie=cookie)
        self.assertIn("Max-Age=0", headers[constants.SET_COOKIE_HEADER])

    def test_demo_open_builds_a_default_demo(self) -> None:
        status, _, headers = self.request("POST", constants.ROUTE_DEMO_OPEN, {})
        self.assertEqual(status, 200)
        cookie = headers[constants.SET_COOKIE_HEADER].split(";")[0]
        _, state, _ = self.request("GET", constants.ROUTE_STATE, cookie=cookie)
        self.assertEqual(len(state[constants.KEY_SESSIONS]), constants.DEMO_DEFAULT_SESSIONS)

    def test_demo_reset_erases_changes_and_keeps_the_size(self) -> None:
        cookie = self.start_demo()  # 13 judges, 2 trainees, 2 sessions, head officials
        _, state, _ = self.request("GET", constants.ROUTE_STATE, cookie=cookie)
        signin_id = state[constants.KEY_SIGNINS][0][constants.KEY_ID]
        self.request("POST", f"{constants.ROUTE_SIGNIN_PREFIX}{signin_id}{constants.SIGNIN_REMOVE_SUFFIX}", {},
                     cookie=cookie)
        _, state, _ = self.request("GET", constants.ROUTE_STATE, cookie=cookie)
        before = len(state[constants.KEY_SIGNINS])
        status, _, _ = self.request("POST", constants.ROUTE_DEMO_RESET, {}, cookie=cookie)
        self.assertEqual(status, 200)
        _, state, _ = self.request("GET", constants.ROUTE_STATE, cookie=cookie)
        self.assertEqual(len(state[constants.KEY_SESSIONS]), 2)
        self.assertEqual(len(state[constants.KEY_SIGNINS]), before + 1)
        _, real, _ = self.request("GET", constants.ROUTE_STATE)
        self.assertEqual(real[constants.KEY_MEET][constants.KEY_NAME], "Real Meet")

    def save(self, body: dict[str, Any], cookie: str | None = None) -> tuple[int, Any]:
        status, reply, _ = self.request("POST", constants.ROUTE_MEET_SAVE, body, cookie=cookie)
        return status, reply

    @staticmethod
    def session_row(name: str, day: str, start: str | None, session_id: int | None = None) -> dict[str, Any]:
        return {constants.KEY_ID: session_id, constants.KEY_NAME: name, constants.KEY_DATE: day,
                constants.KEY_START_TIME: start, constants.KEY_SESSION_TYPE: None,
                constants.KEY_OFFICIALS_MEETING_TIME: None, constants.KEY_ESTIMATED_MINUTES: 180}

    def test_new_meet_with_stacked_sessions(self) -> None:
        status, reply = self.save({
            constants.KEY_ID: None, constants.KEY_NAME: "Winter Champs", constants.KEY_START_DATE: "2026-12-04",
            constants.KEY_SESSIONS: [self.session_row("Friday PM", "2026-12-04", "16:00"),
                                     self.session_row("Saturday Prelims", "2026-12-05", "08:00"),
                                     self.session_row("Saturday Finals", "2026-12-05", "17:00")],
        })
        self.assertEqual(status, 200, reply)
        state = self.database.get_state()
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], "Winter Champs")
        self.assertEqual([session[constants.KEY_NAME] for session in state[constants.KEY_SESSIONS]],
                         ["Friday PM", "Saturday Prelims", "Saturday Finals"])
        self.assertEqual(state[constants.KEY_ACTIVE_SESSION_ID], state[constants.KEY_SESSIONS][0][constants.KEY_ID])

    def test_edit_meet_rows_and_add_one(self) -> None:
        meet_id = self.database.get_state()[constants.KEY_MEET][constants.KEY_ID]
        first = self.database.add_session("Friday PM", "2026-10-16", "13:00", "PM", "12:00")
        status, reply = self.save({
            constants.KEY_ID: meet_id, constants.KEY_NAME: "Real Meet (renamed)", constants.KEY_START_DATE: "2026-10-16",
            constants.KEY_SESSIONS: [self.session_row("Friday Evening", "2026-10-16", "17:00", first),
                                     self.session_row("Saturday AM", "2026-10-17", "08:00")],
        })
        self.assertEqual(status, 200, reply)
        state = self.database.get_state()
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], "Real Meet (renamed)")
        self.assertEqual([(s[constants.KEY_ID] == first, s[constants.KEY_NAME]) for s in state[constants.KEY_SESSIONS]],
                         [(True, "Friday Evening"), (False, "Saturday AM")])

    def test_bad_row_saves_nothing(self) -> None:
        status, reply = self.save({
            constants.KEY_ID: None, constants.KEY_NAME: "Broken", constants.KEY_START_DATE: "2026-12-04",
            constants.KEY_SESSIONS: [self.session_row("Friday PM", "2026-12-04", "16:00"),
                                     self.session_row("Bad", "not a date", None)],
        })
        self.assertEqual(status, 400)
        self.assertIn("Session 2", reply[constants.KEY_ERROR])
        self.assertEqual([meet[constants.KEY_NAME] for meet in self.database.list_meets()], ["Real Meet"])

    def test_session_of_another_meet_refused(self) -> None:
        other_meet = self.database.list_meets()[0][constants.KEY_ID]
        foreign = self.database.add_session("Friday PM", "2026-10-16", "13:00")
        status, _ = self.save({
            constants.KEY_ID: None, constants.KEY_NAME: "New", constants.KEY_START_DATE: "2026-12-04",
            constants.KEY_SESSIONS: [self.session_row("Hijack", "2026-12-04", "16:00", foreign)],
        })
        self.assertEqual(status, 400)
        self.assertEqual(len(self.database.list_meets()), 1)
        self.assertEqual(self.database.get_session(foreign)["meet_id"], other_meet)

    def test_coaches_paths_404_until_the_module_exists(self) -> None:
        status, _, _ = self.request("GET", constants.ROUTE_COACHES)
        self.assertEqual(status, 404)

    def test_coaches_module_gets_its_paths_with_the_right_database(self) -> None:
        calls = []

        def handle_get(handler: Any, path: str, query: str) -> bool:
            calls.append((path, handler.in_demo, handler.database.get_state()[constants.KEY_MEET][constants.KEY_NAME]))
            handler._send_json(200, {"ok": True})
            return True

        def handle_post(handler: Any, path: str, payload: dict[str, Any]) -> bool:
            return False  # unknown path: the server answers 404

        module = types.ModuleType(constants.COACHES_MODULE_NAME)
        module.handle_get = handle_get
        module.handle_post = handle_post
        sys.modules[constants.COACHES_MODULE_NAME] = module
        try:
            cookie = self.start_demo()
            self.assertEqual(self.request("GET", constants.ROUTE_COACHES)[0], 200)
            self.assertEqual(self.request("GET", constants.ROUTE_COACHES_API_PREFIX + "list", cookie=cookie)[0], 200)
            self.assertEqual(self.request("POST", constants.ROUTE_COACHES_API_PREFIX + "nope", {})[0], 404)
        finally:
            del sys.modules[constants.COACHES_MODULE_NAME]
        self.assertEqual(calls, [(constants.ROUTE_COACHES, False, "Real Meet"),
                                 (constants.ROUTE_COACHES_API_PREFIX + "list", True, constants.DEMO_MEET_NAME)])

    def meet_action(self, meet_id: int, suffix: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        status, reply, _ = self.request("POST", f"{constants.ROUTE_MEET_PREFIX}{meet_id}{suffix}", body or {})
        return status, reply

    def test_archive_restore_and_delete_a_meet(self) -> None:
        old_meet = self.database.list_meets()[0][constants.KEY_ID]
        session = self.database.add_session("Friday PM", "2026-10-16", "13:00")
        official = self.database.save_official(None, "Pat Sample", 3, None, None, MEET_DATE)
        self.database.sign_in(official, [session], [constants.TEAM_POOL_ROLE], False,
                              {session: Validation(True, constants.VALIDATION_VISUAL, [])})
        self.database.create_meet("New Meet", "2026-11-01")
        # The open meet cannot be archived; deleting needs archiving first.
        status, reply = self.meet_action(self.database.get_setting(constants.SETTING_ACTIVE_MEET_ID),
                                         constants.MEET_ARCHIVE_SUFFIX, {constants.KEY_ARCHIVED: True})
        self.assertEqual(status, 400, reply)
        self.assertEqual(self.meet_action(old_meet, constants.MEET_DELETE_SUFFIX)[0], 400)
        self.assertEqual(self.meet_action(old_meet, constants.MEET_ARCHIVE_SUFFIX, {constants.KEY_ARCHIVED: True})[0], 200)
        _, overview, _ = self.request("GET", constants.ROUTE_MEETS)
        archived = {meet[constants.KEY_NAME]: meet[constants.KEY_ARCHIVED] for meet in overview[constants.KEY_MEETS]}
        self.assertEqual(archived, {"New Meet": False, "Real Meet": True})
        self.assertEqual(self.meet_action(old_meet, constants.MEET_ARCHIVE_SUFFIX, {constants.KEY_ARCHIVED: False})[0], 200)
        self.assertFalse(self.database.list_meets()[1][constants.KEY_ARCHIVED])
        self.meet_action(old_meet, constants.MEET_ARCHIVE_SUFFIX, {constants.KEY_ARCHIVED: True})
        status, reply = self.meet_action(old_meet, constants.MEET_DELETE_SUFFIX)
        self.assertEqual((status, reply[constants.KEY_SIGNIN_COUNT]), (200, 1))
        self.assertEqual([meet[constants.KEY_NAME] for meet in self.database.list_meets()], ["New Meet"])
        self.assertIsNone(self.database.get_session(session))
        self.assertEqual(self.database.list_officials(MEET_DATE)[0][constants.KEY_NAME], "Pat Sample")  # people stay

    def test_opening_an_archived_meet_restores_it(self) -> None:
        old_meet = self.database.list_meets()[0][constants.KEY_ID]
        self.database.create_meet("New Meet", "2026-11-01")
        self.meet_action(old_meet, constants.MEET_ARCHIVE_SUFFIX, {constants.KEY_ARCHIVED: True})
        self.meet_action(old_meet, constants.MEET_OPEN_SUFFIX)
        self.assertFalse(next(m for m in self.database.list_meets() if m[constants.KEY_ID] == old_meet)[constants.KEY_ARCHIVED])

    def test_exit_clears_the_cookie(self) -> None:
        cookie = self.start_demo()
        status, _, headers = self.request("POST", constants.ROUTE_DEMO_EXIT, {}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(constants.DEMO_COOKIE_NAME, headers[constants.SET_COOKIE_HEADER])


if __name__ == "__main__":
    unittest.main()
