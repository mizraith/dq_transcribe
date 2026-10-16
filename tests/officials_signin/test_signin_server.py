"""Tests for the officials_signin database, server and roster file.

Runs a real server on an OS-chosen port against a temporary database. The
camera is not involved: the tests post OCR text the way the page does.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.card_reader import parse_card_text
from officials_signin.database import Database, Validation, name_key, since_year_to_years, years_to_since_year
from officials_signin.roster import build_roster, roster_download_filename
from officials_signin.server import SigninServer, render_page, render_script, resolve_vendor_file
from test_signin_card_reader import CLEAN_CARD_TEXT, FAKE_MEMBER_ID

LOOPBACK_HOST = "127.0.0.1"
MEET_DATE = "2026-10-16"
EXPIRED_CARD_TEXT = CLEAN_CARD_TEXT.replace("Background Check: 09/30/2027", "Background Check: 09/30/2026")


class SigninServerTests(unittest.TestCase):
    """End-to-end tests through HTTP."""

    def setUp(self) -> None:
        self.database = Database(Path(tempfile.mkdtemp()) / "test.db")
        self.database.initialize()
        self.server = SigninServer((LOOPBACK_HOST, 0), self.database)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # --- helpers -------------------------------------------------------------

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any, dict[str, str]]:
        """Send a request; return status, decoded body (JSON when possible) and headers."""
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.server.server_address[1], timeout=10)
        payload = None if body is None else json.dumps(body)
        headers = {} if body is None else {constants.CONTENT_TYPE_HEADER: constants.JSON_CONTENT_TYPE}
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            decoded: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = raw
        return response.status, decoded, dict(response.getheaders())

    def set_up_meet(self) -> tuple[int, int]:
        """Create a meet with AM and PM sessions; return their IDs (AM is active)."""
        self.request("POST", constants.ROUTE_MEETS, {constants.KEY_NAME: "Candy Meet", constants.KEY_START_DATE: MEET_DATE})
        _, morning, _ = self.request(
            "POST", constants.ROUTE_SESSIONS,
            {constants.KEY_NAME: "Friday AM", constants.KEY_DATE: MEET_DATE, constants.KEY_START_TIME: "08:00"},
        )
        _, evening, _ = self.request(
            "POST", constants.ROUTE_SESSIONS,
            {constants.KEY_NAME: "Friday PM", constants.KEY_DATE: MEET_DATE, constants.KEY_START_TIME: "13:00"},
        )
        return morning[constants.KEY_ID], evening[constants.KEY_ID]

    def read_card(self, text: str, passes: int = 1) -> dict[str, Any]:
        """Post OCR text (as ``passes`` identical passes) and return the server's reading."""
        status, reply, _ = self.request("POST", constants.ROUTE_CARD_READING, {constants.KEY_TEXTS: [text] * passes})
        self.assertEqual(status, 200)
        return reply

    # --- tests ---------------------------------------------------------------

    def test_page_and_scripts_render(self) -> None:
        for path in (constants.ROUTE_HOME, constants.ROUTE_SCRIPT, constants.ROUTE_CARD_SCANNER_SCRIPT):
            status, body, _ = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertNotIn(b"${", body)

    def test_ocr_engine_files_are_served(self) -> None:
        for filename in (
            constants.OCR_ENGINE_SCRIPT_FILENAME, constants.OCR_WORKER_SCRIPT_FILENAME, constants.OCR_CORE_SCRIPT_FILENAME,
        ):
            status, _, headers = self.request("GET", constants.OCR_ENGINE_PATH + filename)
            self.assertEqual(status, 200, filename)
            self.assertEqual(headers[constants.CONTENT_TYPE_HEADER], constants.JAVASCRIPT_CONTENT_TYPE)
        status, _, _ = self.request("GET", constants.OCR_LANGUAGE_DATA_PATH + "/" + constants.OCR_LANGUAGE + ".traineddata.gz")
        self.assertEqual(status, 200)

    def test_vendor_paths_cannot_escape_the_folder(self) -> None:
        self.assertIsNone(resolve_vendor_file(constants.ROUTE_VENDOR_PREFIX + "../signin.js"))
        status, _, _ = self.request("GET", constants.ROUTE_VENDOR_PREFIX + "..%2F..%2Fserver.py")
        self.assertEqual(status, 404)

    def test_card_reading_reports_fields_and_validation(self) -> None:
        self.set_up_meet()
        reply = self.read_card(CLEAN_CARD_TEXT, passes=2)
        self.assertTrue(reply[constants.KEY_VALIDATED])
        self.assertTrue(reply[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])
        self.assertEqual(reply[constants.KEY_CARD][constants.KEY_ZONE], constants.ZONE_WESTERN)
        self.assertIsNone(reply[constants.KEY_MATCH])

    def test_camera_sign_in_validates_and_presigns_later_session(self) -> None:
        morning, evening = self.set_up_meet()
        reading = self.read_card(CLEAN_CARD_TEXT)
        status, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_ROLES: ["Stroke & Turn Judge", "Starter"],
            constants.KEY_CARD: reading[constants.KEY_CARD],
            constants.KEY_SESSION_IDS: [morning, evening],
            constants.KEY_YEARS_CERTIFIED: 6,
        })
        self.assertEqual(status, 200, reply)
        self.assertTrue(reply[constants.KEY_VALIDATED])
        self.assertEqual(len(reply[constants.KEY_SIGNINS]), 2)
        evening_signins = self.database.list_signins(evening)
        self.assertEqual(evening_signins[0][constants.KEY_VALIDATION_METHOD], constants.VALIDATION_CAMERA)

        # The card now matches the known official.
        again = self.read_card(CLEAN_CARD_TEXT)
        self.assertEqual(again[constants.KEY_MATCH][constants.KEY_NAME], 'Pat "Skip" Example')
        self.assertEqual(again[constants.KEY_MATCH][constants.KEY_ROLES], ["Stroke & Turn Judge", "Starter"])
        self.assertNotIn(constants.KEY_MEMBER_ID, again[constants.KEY_MATCH])

    def test_new_name_needs_two_matching_passes(self) -> None:
        self.set_up_meet()
        once = self.read_card(CLEAN_CARD_TEXT)
        self.assertFalse(once[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])
        garbled = CLEAN_CARD_TEXT.replace('PAT "SKIP" EXAMPLE', 'WIARN SKIP EXAMPLE')
        _, mixed, _ = self.request("POST", constants.ROUTE_CARD_READING, {constants.KEY_TEXTS: [garbled, CLEAN_CARD_TEXT]})
        self.assertFalse(mixed[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])
        twice = self.read_card(CLEAN_CARD_TEXT, passes=2)
        self.assertTrue(twice[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])

    def test_known_official_keeps_stored_name_despite_ocr_slip(self) -> None:
        self.set_up_meet()
        reading = self.read_card(CLEAN_CARD_TEXT, passes=2)
        _, first, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: 'Pat "Skip" Example', constants.KEY_ROLES: ["Starter"],
            constants.KEY_CARD: reading[constants.KEY_CARD],
        })
        garbled = CLEAN_CARD_TEXT.replace('PAT "SKIP" EXAMPLE', 'WIARN SKIP EXAMPLE')
        again = self.read_card(garbled)  # one blurry pass, matched by member ID
        self.assertTrue(again[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])
        self.assertEqual(again[constants.KEY_MATCH][constants.KEY_NAME], 'Pat "Skip" Example')
        self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_OFFICIAL_ID: first[constants.KEY_OFFICIAL_ID], constants.KEY_NAME: 'Pat "Skip" Example',
            constants.KEY_ROLES: ["Starter"], constants.KEY_CARD: again[constants.KEY_CARD],
        })
        _, officials, _ = self.request("GET", constants.ROUTE_OFFICIALS)
        self.assertEqual([item[constants.KEY_NAME] for item in officials[constants.KEY_OFFICIALS]], ['Pat "Skip" Example'])

    def test_edit_renames_and_merges_a_duplicate(self) -> None:
        self.set_up_meet()
        # Signed in by name first, then (another session) by a misread card.
        _, typed, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: 'Pat "Skip" Example', constants.KEY_ROLES: ["Starter"], constants.KEY_YEARS_CERTIFIED: 6,
        })
        state = self.database.get_state()
        evening = state[constants.KEY_SESSIONS][1][constants.KEY_ID]
        self.request("POST", constants.ROUTE_ACTIVE_SESSION, {constants.KEY_SESSION_ID: evening})
        garbled = CLEAN_CARD_TEXT.replace('PAT "SKIP" EXAMPLE', 'WIARN SKIP EXAMPLE')
        reading = self.read_card(garbled, passes=2)
        _, misread, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Wiarn Skip Example", constants.KEY_ROLES: ["Starter"], constants.KEY_CARD: reading[constants.KEY_CARD],
        })
        _, officials, _ = self.request("GET", constants.ROUTE_OFFICIALS)
        self.assertEqual(len(officials[constants.KEY_OFFICIALS]), 2)
        path = constants.ROUTE_SIGNIN_PREFIX + str(misread[constants.KEY_SIGNINS][0]) + constants.SIGNIN_EDIT_SUFFIX
        status, reply, _ = self.request("POST", path, {
            constants.KEY_NAME: 'Pat "Skip" Example', constants.KEY_ROLES: ["Chief Judge"], constants.KEY_TRAINEE: False,
        })
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply[constants.KEY_MERGED], 1)
        _, officials, _ = self.request("GET", constants.ROUTE_OFFICIALS)
        merged = officials[constants.KEY_OFFICIALS]
        self.assertEqual([item[constants.KEY_NAME] for item in merged], ['Pat "Skip" Example'])
        self.assertEqual(merged[0][constants.KEY_CLUB], "PASA")  # kept from the card record
        self.assertEqual(merged[0][constants.KEY_YEARS_CERTIFIED], 6)  # filled from the typed record
        # Both sessions' sign-ins now belong to the one official.
        morning = state[constants.KEY_SESSIONS][0][constants.KEY_ID]
        self.assertEqual(self.database.list_signins(morning)[0][constants.KEY_NAME], 'Pat "Skip" Example')
        self.assertEqual(self.database.list_signins(evening)[0][constants.KEY_ROLES], ["Chief Judge"])
        # The next scan of this card finds the corrected name.
        again = self.read_card(garbled)
        self.assertEqual(again[constants.KEY_MATCH][constants.KEY_NAME], 'Pat "Skip" Example')

    def test_edit_refuses_bad_input(self) -> None:
        self.set_up_meet()
        _, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Sam Newcomer", constants.KEY_ROLES: ["Starter"],
        })
        path = constants.ROUTE_SIGNIN_PREFIX + str(reply[constants.KEY_SIGNINS][0]) + constants.SIGNIN_EDIT_SUFFIX
        self.assertEqual(self.request("POST", path, {constants.KEY_NAME: " ", constants.KEY_ROLES: ["Starter"]})[0], 400)
        self.assertEqual(self.request("POST", path, {constants.KEY_NAME: "Sam", constants.KEY_ROLES: ["Timer"]})[0], 400)
        missing = constants.ROUTE_SIGNIN_PREFIX + "999" + constants.SIGNIN_EDIT_SUFFIX
        self.assertEqual(self.request("POST", missing, {constants.KEY_NAME: "Sam", constants.KEY_ROLES: ["Starter"]})[0], 400)

    def test_roster_has_one_line_per_role(self) -> None:
        self.set_up_meet()
        reading = self.read_card(CLEAN_CARD_TEXT)
        self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_ROLES: ["Stroke & Turn Judge", "Starter"], constants.KEY_CARD: reading[constants.KEY_CARD],
        })
        status, roster, _ = self.request("GET", constants.ROUTE_ROSTER)
        self.assertEqual(status, 200)
        self.assertEqual(roster[constants.ROSTER_KEY_FORMAT], constants.ROSTER_FORMAT_NAME)
        self.assertEqual(roster[constants.ROSTER_KEY_VERSION], constants.ROSTER_FORMAT_VERSION)
        self.assertEqual(roster[constants.ROSTER_KEY_SESSION][constants.KEY_NAME], "Friday AM")
        lines = roster[constants.ROSTER_KEY_OFFICIALS]
        self.assertEqual([line[constants.KEY_ROLE] for line in lines], ["Stroke & Turn Judge", "Starter"])
        first = lines[0]
        self.assertEqual(first[constants.KEY_CLUB], "PASA")
        self.assertEqual(first[constants.KEY_ZONE], constants.ZONE_WESTERN)
        self.assertEqual(first[constants.KEY_MEMBER_ID], FAKE_MEMBER_ID)
        self.assertTrue(first[constants.KEY_VALIDATED])
        self.assertIn(first[constants.KEY_VALIDATION_METHOD], constants.VALIDATION_METHODS)
        self.assertTrue(all(line[constants.KEY_ROLE] in constants.ROSTER_ROLES for line in lines))

    def test_roster_download_has_a_file_name(self) -> None:
        self.set_up_meet()
        status, _, headers = self.request("GET", constants.ROUTE_ROSTER_DOWNLOAD)
        self.assertEqual(status, 200)
        self.assertIn("officials_roster_2026-10-16_friday-am.json", headers[constants.CONTENT_DISPOSITION_HEADER])

    def test_expired_card_goes_to_the_admin_then_looks_good(self) -> None:
        self.set_up_meet()
        once = self.read_card(EXPIRED_CARD_TEXT)
        self.assertFalse(once[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])  # keep reading to confirm
        reading = self.read_card(EXPIRED_CARD_TEXT, passes=2)
        self.assertTrue(reading[constants.KEY_CARD][constants.CARD_FIELD_COMPLETE])
        self.assertFalse(reading[constants.KEY_VALIDATED])
        _, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_ROLES: ["Starter"], constants.KEY_CARD: reading[constants.KEY_CARD],
        })
        self.assertFalse(reply[constants.KEY_VALIDATED])
        self.assertEqual(reply[constants.KEY_PROBLEMS], ["Background check: expired 2026-09-30"])
        signin_id = reply[constants.KEY_SIGNINS][0]
        status, _, _ = self.request(
            "POST", constants.ROUTE_SIGNIN_PREFIX + str(signin_id) + constants.SIGNIN_VALIDATE_SUFFIX, {}
        )
        self.assertEqual(status, 200)
        signin = self.database.list_signins(self.database.get_state()[constants.KEY_ACTIVE_SESSION_ID])[0]
        self.assertTrue(signin[constants.KEY_VALIDATED])
        self.assertEqual(signin[constants.KEY_VALIDATION_METHOD], constants.VALIDATION_VISUAL)

    def test_returning_official_by_name_reuses_card_check_from_same_meet(self) -> None:
        morning, evening = self.set_up_meet()
        reading = self.read_card(CLEAN_CARD_TEXT)
        _, first, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_ROLES: ["Starter"], constants.KEY_CARD: reading[constants.KEY_CARD],
        })
        self.request("POST", constants.ROUTE_ACTIVE_SESSION, {constants.KEY_SESSION_ID: evening})
        _, second, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_OFFICIAL_ID: first[constants.KEY_OFFICIAL_ID], constants.KEY_ROLES: ["Starter"],
        })
        self.assertTrue(second[constants.KEY_VALIDATED])

        # At the next meet the card must be checked again.
        self.request("POST", constants.ROUTE_MEETS, {constants.KEY_NAME: "Next Meet", constants.KEY_START_DATE: "2026-11-06"})
        self.request("POST", constants.ROUTE_SESSIONS, {constants.KEY_NAME: "Sat AM", constants.KEY_DATE: "2026-11-07"})
        _, third, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_OFFICIAL_ID: first[constants.KEY_OFFICIAL_ID], constants.KEY_ROLES: ["Starter"],
        })
        self.assertFalse(third[constants.KEY_VALIDATED])

    def test_new_person_by_name_needs_the_admin(self) -> None:
        self.set_up_meet()
        _, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Sam Newcomer", constants.KEY_ROLES: ["Stroke & Turn Judge"], constants.KEY_TRAINEE: True,
        })
        self.assertFalse(reply[constants.KEY_VALIDATED])
        _, officials, _ = self.request("GET", constants.ROUTE_OFFICIALS)
        self.assertEqual(officials[constants.KEY_OFFICIALS][0][constants.KEY_NAME], "Sam Newcomer")
        self.assertTrue(officials[constants.KEY_OFFICIALS][0][constants.KEY_TRAINEE])

    def test_signing_in_again_never_undoes_a_validation(self) -> None:
        self.set_up_meet()
        _, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Sam Newcomer", constants.KEY_ROLES: ["Starter"],
        })
        signin_id = reply[constants.KEY_SIGNINS][0]
        self.request("POST", constants.ROUTE_SIGNIN_PREFIX + str(signin_id) + constants.SIGNIN_VALIDATE_SUFFIX, {})
        _, again, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_OFFICIAL_ID: reply[constants.KEY_OFFICIAL_ID], constants.KEY_ROLES: ["Chief Judge"],
        })
        signin = self.database.list_signins(self.database.get_state()[constants.KEY_ACTIVE_SESSION_ID])[0]
        self.assertTrue(signin[constants.KEY_VALIDATED])
        self.assertEqual(signin[constants.KEY_ROLES], ["Chief Judge"])

    def test_bad_requests_are_refused(self) -> None:
        status, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {constants.KEY_ROLES: ["Starter"]})
        self.assertEqual(status, 400)
        self.assertIn(constants.KEY_ERROR, reply)
        self.set_up_meet()
        status, _, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Sam", constants.KEY_ROLES: ["Timer"],
        })
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Sam", constants.KEY_ROLES: ["Starter"], constants.KEY_SESSION_IDS: [999],
        })
        self.assertEqual(status, 400)

    def test_remove_signin(self) -> None:
        self.set_up_meet()
        _, reply, _ = self.request("POST", constants.ROUTE_SIGNINS, {
            constants.KEY_NAME: "Sam Newcomer", constants.KEY_ROLES: ["Starter"],
        })
        path = constants.ROUTE_SIGNIN_PREFIX + str(reply[constants.KEY_SIGNINS][0]) + constants.SIGNIN_REMOVE_SUFFIX
        self.assertEqual(self.request("POST", path, {})[0], 200)
        self.assertEqual(self.request("POST", path, {})[0], 404)


class HelperTests(unittest.TestCase):
    """Small pure functions."""

    def test_name_key_ignores_quotes_and_case(self) -> None:
        self.assertEqual(name_key('Mark "Red" Byer'), name_key("MARK RED BYER"))

    def test_years_certified_ages_by_itself(self) -> None:
        since = years_to_since_year(6, date(2026, 10, 16))
        self.assertEqual(since_year_to_years(since, date(2028, 3, 1)), 8)
        self.assertIsNone(since_year_to_years(None, date(2028, 3, 1)))

    def test_every_lsc_has_a_zone(self) -> None:
        self.assertEqual(len(constants.ZONE_BY_LSC_CODE), 59)

    def test_roster_roles_match_dq_transcribe(self) -> None:
        try:
            from dq_transcribe import constants as dq_constants
        except ImportError:  # pragma: no cover - only when run without src on the path
            self.skipTest("dq_transcribe not importable")
        self.assertEqual(constants.ROSTER_ROLES, dq_constants.MEET_ROSTER_ROLES)

    def test_roster_builder_and_filename(self) -> None:
        source = {
            constants.KEY_MEET: {constants.KEY_NAME: "Candy Meet", constants.KEY_START_DATE: MEET_DATE},
            constants.ROSTER_KEY_SESSION: {
                constants.KEY_NAME: "Friday PM", constants.KEY_DATE: MEET_DATE, constants.KEY_START_TIME: "13:00",
            },
            constants.KEY_SIGNINS: [],
        }
        roster = build_roster(source, datetime(2026, 10, 16, 14, 45, tzinfo=timezone.utc))
        self.assertEqual(roster[constants.ROSTER_KEY_GENERATED_AT], "2026-10-16T14:45:00+00:00")
        self.assertEqual(roster_download_filename(roster), "officials_roster_2026-10-16_friday-pm.json")

    def test_templates_have_no_stray_dollar_signs(self) -> None:
        render_page()
        render_script(constants.SCRIPT_FILENAME)
        render_script(constants.CARD_SCANNER_SCRIPT_FILENAME)

    def test_card_reading_round_trips_through_storage(self) -> None:
        database = Database(Path(tempfile.mkdtemp()) / "test.db")
        database.initialize()
        meet_id = database.create_meet("Candy Meet", MEET_DATE)
        reading = parse_card_text(CLEAN_CARD_TEXT)
        official_id = database.save_official(None, None, None, reading, meet_id, date(2026, 10, 16))
        validation = database.stored_card_validation(official_id, meet_id, date(2026, 10, 16))
        self.assertEqual(validation, Validation(True, constants.VALIDATION_CAMERA, []))
        self.assertEqual(database.find_official_for_card(reading), official_id)


if __name__ == "__main__":
    unittest.main()
