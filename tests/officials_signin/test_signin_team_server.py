"""Server tests for teams (build, hand changes, 15 m, mentors), session delete and diagnostics.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.database import Database, Validation
from officials_signin.roster import build_roster
from officials_signin.server import SigninServer
from test_signin_server import LOOPBACK_HOST, SigninServerTests

MEET_DATE = date(2026, 10, 16)
JUDGE_COUNT = 13
TRAINEE_NAMES = ("Tess Trainee", "Toby Trainee")


class TeamServerTests(unittest.TestCase):
    """Teams through HTTP, with 13 judges, 2 trainees and a Starter signed in."""

    request = SigninServerTests.request

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.database = Database(self.root / "test.db")
        self.database.initialize()
        self.server = SigninServer((LOOPBACK_HOST, 0), self.database, diagnostics_directory=self.root / "diagnostics")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.database.create_meet("Candy Meet", MEET_DATE.isoformat())
        self.session_id = self.database.add_session("Friday Prelims", MEET_DATE.isoformat(), "13:00", "Prelims", "12:00")
        self.ids: dict[str, int] = {}
        for index in range(JUDGE_COUNT):
            self.ids[f"Judge {index:02d}"] = self.sign_in(f"Judge {index:02d}", 30 - index, False)
        for name in TRAINEE_NAMES:
            self.ids[name] = self.sign_in(name, 0, True)
        self.sign_in("Sam Starter", 10, False, role="Starter")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def sign_in(self, name: str, years: int, trainee: bool, role: str = constants.TEAM_POOL_ROLE) -> int:
        official = self.database.save_official(None, name, years, None, None, MEET_DATE)
        validation = {self.session_id: Validation(True, constants.VALIDATION_VISUAL, [])}
        return self.database.sign_in(official, [self.session_id], [role], trainee, validation)[0]

    def build(self, body: dict[str, Any] | None = None) -> dict[str, Any]:
        status, view, _ = self.request("POST", constants.ROUTE_TEAMS_BUILD, body or {})
        self.assertEqual(status, 200, view)
        return view

    def change(self, name: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        path = constants.ROUTE_SIGNIN_PREFIX + str(self.ids[name]) + constants.SIGNIN_TEAM_SUFFIX
        status, view, _ = self.request("POST", path, body)
        return status, view

    @staticmethod
    def team_names(view: dict[str, Any], team: str) -> list[str]:
        members = next(item for item in view[constants.KEY_TEAMS] if item[constants.KEY_NAME] == team)
        return [member[constants.KEY_NAME] for member in members[constants.KEY_MEMBERS]]

    def swap(self, name: str, other: str) -> tuple[int, dict[str, Any]]:
        path = constants.ROUTE_SIGNIN_PREFIX + str(self.ids[name]) + constants.SIGNIN_SWAP_SUFFIX
        status, view, _ = self.request("POST", path, {constants.KEY_WITH_SIGNIN_ID: self.ids[other]})
        return status, view

    def test_swap_two_judges_between_teams(self) -> None:
        self.build()
        self.change("Judge 01", {constants.KEY_TEAM_LEAD: True})
        status, view = self.swap("Judge 01", "Judge 05")
        self.assertEqual(status, 200, view)
        self.assertIn("Judge 05", self.team_names(view, "Team 1"))
        self.assertIn("Judge 01", self.team_names(view, "Team 2"))
        team_one = next(team for team in view[constants.KEY_TEAMS] if team[constants.KEY_NAME] == "Team 1")
        self.assertFalse(any(member[constants.KEY_TEAM_LEAD] for member in team_one[constants.KEY_MEMBERS]))

    def test_swap_pulls_the_acj_onto_a_team(self) -> None:
        view = self.build()
        self.assertEqual(view[constants.KEY_EXTRAS][0][constants.KEY_NAME], "Judge 00")
        status, view = self.swap("Judge 00", "Judge 12")
        self.assertEqual(status, 200, view)
        self.assertIn("Judge 00", self.team_names(view, "Team 4"))
        self.assertEqual(view[constants.KEY_EXTRAS][0][constants.KEY_NAME], "Judge 12")
        self.assertEqual(view[constants.KEY_EXTRAS][0][constants.KEY_ASSIGNMENT], constants.ASSIGNMENT_ACJ)

    def test_trainees_follow_their_mentor_in_a_swap(self) -> None:
        view = self.build()
        trainee = next(trainee for team in view[constants.KEY_TEAMS] for trainee in team[constants.KEY_TRAINEES])
        mentor_name = trainee[constants.KEY_MENTOR]
        other = "Judge 12" if mentor_name != "Judge 12" else "Judge 11"
        _, view = self.swap(mentor_name, other)
        moved = next(team for team in view[constants.KEY_TEAMS]
                     if any(t[constants.KEY_NAME] == trainee[constants.KEY_NAME] for t in team[constants.KEY_TRAINEES]))
        self.assertIn(mentor_name, self.team_names(view, moved[constants.KEY_NAME]))

    def test_trainee_cannot_be_swapped(self) -> None:
        self.build()
        status, _ = self.swap(TRAINEE_NAMES[0], "Judge 03")
        self.assertEqual(status, 400)

    def test_extra_can_be_given_another_job(self) -> None:
        self.build()
        status, view = self.change("Judge 00", {constants.KEY_TEAM: None, constants.KEY_ASSIGNMENT: constants.ASSIGNMENT_RELIEF})
        self.assertEqual(status, 200)
        self.assertEqual(view[constants.KEY_EXTRAS][0][constants.KEY_ASSIGNMENT], constants.ASSIGNMENT_RELIEF)

    def test_corner_officials_never_go_on_teams(self) -> None:
        # A starter who also ticked Stroke & Turn Judge stays off the teams.
        official = self.database.save_official(None, "Casey Corner", 20, None, None, MEET_DATE)
        validation = {self.session_id: Validation(True, constants.VALIDATION_VISUAL, [])}
        self.database.sign_in(official, [self.session_id], ["Starter", constants.TEAM_POOL_ROLE], False, validation)
        view = self.build()
        self.assertEqual(view[constants.KEY_JUDGE_COUNT], JUDGE_COUNT)
        everyone = [m[constants.KEY_NAME] for team in view[constants.KEY_TEAMS] for m in team[constants.KEY_MEMBERS]]
        everyone += [m[constants.KEY_NAME] for m in view[constants.KEY_EXTRAS]]
        self.assertNotIn("Casey Corner", everyone)
        self.assertNotIn("Sam Starter", everyone)

    def test_build_proposes_four_teams_of_three_and_an_acj(self) -> None:
        view = self.build()
        self.assertEqual(view[constants.KEY_JUDGE_COUNT], JUDGE_COUNT)  # Starter and trainees not counted
        self.assertEqual(view[constants.KEY_TEAM_COUNT], 4)
        self.assertEqual(view[constants.KEY_ALTERNATIVE_TEAM_COUNT], 3)
        self.assertEqual(self.team_names(view, "Team 1"), ["Judge 01", "Judge 02", "Judge 03"])
        self.assertEqual(view[constants.KEY_EXTRAS][0][constants.KEY_NAME], "Judge 00")
        self.assertEqual(view[constants.KEY_EXTRAS][0][constants.KEY_ASSIGNMENT], constants.ASSIGNMENT_ACJ)
        self.assertEqual(view[constants.KEY_UNPAIRED_TRAINEES], [])
        self.assertEqual(view[constants.KEY_TEAMS][0][constants.KEY_JURISDICTION][constants.KEY_PATTERN], "3-3-2 / 2-3-3")

    def test_alternative_layout_and_lanes(self) -> None:
        view = self.build({constants.KEY_TEAM_COUNT: 3})
        self.assertEqual(len(self.team_names(view, "Team 1")), 4)
        status, view, _ = self.request("POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_LANES: 10})
        self.assertEqual(view[constants.KEY_TEAMS][0][constants.KEY_JURISDICTION][constants.KEY_PATTERN], "3-3-2-2 / 2-2-3-3")
        self.assertEqual(len(self.team_names(view, "Team 1")), 4)  # lanes never rebuild

    def test_fifteen_meter_toggle_keeps_hand_changes(self) -> None:
        self.build()
        self.change("Judge 01", {constants.KEY_TEAM_LEAD: True})
        self.change("Judge 12", {constants.KEY_TEAM: None, constants.KEY_ASSIGNMENT: constants.ASSIGNMENT_RELIEF})
        _, view, _ = self.request("POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_FIFTEEN_METER_ON_TEAMS: True})
        team_one = view[constants.KEY_TEAMS][0][constants.KEY_MEMBERS]
        self.assertTrue(team_one[0][constants.KEY_TEAM_LEAD])  # lead kept
        self.assertEqual(team_one[2][constants.KEY_ASSIGNMENT], constants.ASSIGNMENT_FIFTEEN_METER)
        self.assertIn("Judge 12", [extra[constants.KEY_NAME] for extra in view[constants.KEY_EXTRAS]])  # move kept
        _, view, _ = self.request("POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_FIFTEEN_METER_ON_TEAMS: False})
        self.assertIsNone(view[constants.KEY_TEAMS][0][constants.KEY_MEMBERS][2][constants.KEY_ASSIGNMENT])

    def test_one_lead_per_team_and_lead_lost_on_move(self) -> None:
        self.build()
        self.change("Judge 01", {constants.KEY_TEAM_LEAD: True})
        _, view = self.change("Judge 02", {constants.KEY_TEAM_LEAD: True})
        leads = [member[constants.KEY_NAME] for member in view[constants.KEY_TEAMS][0][constants.KEY_MEMBERS] if member[constants.KEY_TEAM_LEAD]]
        self.assertEqual(leads, ["Judge 02"])
        _, view = self.change("Judge 02", {constants.KEY_TEAM: "Team 2", constants.KEY_ASSIGNMENT: None})
        moved = next(member for member in view[constants.KEY_TEAMS][1][constants.KEY_MEMBERS] if member[constants.KEY_NAME] == "Judge 02")
        self.assertFalse(moved[constants.KEY_TEAM_LEAD])

    def test_trainees_follow_mentor_and_mentor_must_be_certified(self) -> None:
        view = self.build()
        trainee = view[constants.KEY_TEAMS][0][constants.KEY_TRAINEES][0]
        self.assertEqual(trainee[constants.KEY_MENTOR], "Judge 01")
        self.change("Judge 01", {constants.KEY_TEAM: "Team 3", constants.KEY_ASSIGNMENT: None})
        _, view, _ = self.request("GET", constants.ROUTE_TEAMS)
        team_three = view[constants.KEY_TEAMS][2]
        self.assertIn(trainee[constants.KEY_NAME], [item[constants.KEY_NAME] for item in team_three[constants.KEY_TRAINEES]])
        status, _ = self.change("Tess Trainee", {constants.KEY_MENTOR_SIGNIN_ID: self.ids["Toby Trainee"]})
        self.assertEqual(status, 400)

    def test_bad_team_changes_are_refused(self) -> None:
        self.build()
        self.assertEqual(self.change("Judge 01", {constants.KEY_TEAM: "Team X"})[0], 400)
        self.assertEqual(self.change("Judge 01", {constants.KEY_ASSIGNMENT: "Timer"})[0], 400)
        self.assertEqual(self.request("POST", constants.ROUTE_TEAMS_SETTINGS, {constants.KEY_LANES: 99})[0], 400)

    def test_roster_carries_team_fields(self) -> None:
        self.build()
        self.change("Judge 01", {constants.KEY_TEAM_LEAD: True})
        lines = {line[constants.KEY_NAME]: line for line in build_roster(self.database.roster_source(self.session_id))[constants.ROSTER_KEY_OFFICIALS]}
        self.assertEqual(lines["Judge 00"][constants.KEY_ASSIGNMENT], constants.ASSIGNMENT_ACJ)
        self.assertTrue(lines["Judge 01"][constants.KEY_TEAM_LEAD])
        self.assertEqual(lines["Tess Trainee"][constants.KEY_MENTOR], "Judge 01")
        self.assertEqual(lines["Tess Trainee"][constants.KEY_TEAM], "Team 1")
        self.assertIsNone(lines["Sam Starter"][constants.KEY_TEAM])

    def test_delete_session_removes_its_signins(self) -> None:
        path = constants.ROUTE_SESSION_PREFIX + str(self.session_id) + constants.SESSION_DELETE_SUFFIX
        status, reply, _ = self.request("POST", path, {})
        self.assertEqual(status, 200)
        self.assertEqual(reply[constants.KEY_SIGNIN_COUNT], JUDGE_COUNT + len(TRAINEE_NAMES) + 1)
        state = self.database.get_state()
        self.assertEqual(state[constants.KEY_SESSIONS], [])
        self.assertIsNone(state[constants.KEY_ACTIVE_SESSION_ID])
        self.assertEqual(self.request("POST", path, {})[0], 400)  # already gone

    def test_diagnostics_saved_and_checked(self) -> None:
        image = constants.DATA_URL_JPEG_PREFIX + base64.b64encode(b"\xff\xd8fake-jpeg\xff\xd9").decode()
        body = {constants.KEY_SCAN_ID: "20261016T120000", constants.KEY_RECORD: {"kind": "frame"}, constants.KEY_IMAGE: image}
        self.assertEqual(self.request("POST", constants.ROUTE_DIAGNOSTICS, body)[0], 200)
        folder = self.root / "diagnostics" / "20261016T120000"
        self.assertTrue((folder / "frame_001.jpg").exists())
        record = json.loads((folder / constants.DIAGNOSTICS_RECORD_FILENAME).read_text().splitlines()[0])
        self.assertEqual(record[constants.KEY_IMAGE], "frame_001.jpg")
        bad = dict(body, **{constants.KEY_SCAN_ID: "../escape"})
        self.assertEqual(self.request("POST", constants.ROUTE_DIAGNOSTICS, bad)[0], 400)


if __name__ == "__main__":
    unittest.main()
