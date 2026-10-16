"""Tests for the coach page: what coaches see, the password, and the admin switch."""

from __future__ import annotations

import http.client
import json
import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dq_transcribe import constants
from dq_transcribe.coach_page import coach_visible_dqs, infraction_text, render_dq_list
from dq_transcribe.coach_server import CoachPage, generate_password, local_ipv4_addresses
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.server import DqTranscribeServer

LOOPBACK_HOST = "127.0.0.1"
MEET_NAME = "Candy Meet"
COMPLETE_DQ = {
    "event": "12", "heat": "2", "lane": "4", "swimmer": "Jane Example", "club": "PASA",
    "official": "Pat Judge", "referee": "Lee Referee",
    "infractions": [{"description": "One hand touch", "code": "3J"}],
}


def _dq(state: str, **fields) -> dict:
    """A DQ as ``DqStore.list_dqs`` returns it (only what the coach page reads)."""
    return {"id": fields.pop("id", 1), "state": state, "trashed_at": None, "relay_leg": None, **COMPLETE_DQ, **fields}


class CoachPageRenderingTests(unittest.TestCase):
    """The list shows only DQs the coach has been told about."""

    def test_only_notified_and_later_states_are_shown(self) -> None:
        dqs = [_dq(state, id=index) for index, state in enumerate(constants.DQ_STATES)]
        shown = {dq["state"] for dq in coach_visible_dqs(dqs)}
        self.assertEqual(shown, set(constants.DQ_STATES_AFTER_NOTIFICATION))

    def test_list_groups_by_event_filters_by_club_and_strikes_overturned(self) -> None:
        dqs = [
            _dq(constants.DQ_STATE_NOTIFIED, id=1),
            _dq(constants.DQ_STATE_OVERTURNED, id=2, club="SCSC", swimmer="Ann Other"),
            _dq(constants.DQ_STATE_ACCEPTED, id=3, swimmer="Not Told Yet"),
        ]
        page = render_dq_list({"name": MEET_NAME}, dqs, None, datetime.now().astimezone()).decode()
        self.assertIn("Event 12", page)
        self.assertIn("3J One hand touch", page)
        self.assertIn('class="dq overturned"', page)
        self.assertNotIn("Not Told Yet", page)
        filtered = render_dq_list({"name": MEET_NAME}, dqs, "SCSC", datetime.now().astimezone()).decode()
        self.assertIn("Ann Other", filtered)
        self.assertNotIn("Jane Example", filtered)

    def test_one_club_sorted_by_swimmer(self) -> None:
        dqs = [
            _dq(constants.DQ_STATE_NOTIFIED, id=1, event="3", swimmer="Zed Adams"),
            _dq(constants.DQ_STATE_NOTIFIED, id=2, event="7", swimmer="Amy Young"),
            _dq(constants.DQ_STATE_NOTIFIED, id=3, event="9", swimmer="Zed Adams"),
            _dq(constants.DQ_STATE_NOTIFIED, id=4, event="9", swimmer="Other Club", club="SCSC"),
            _dq(constants.DQ_STATE_NOTIFIED, id=5, event="11", swimmer="PASA-A"),
        ]
        page = render_dq_list({"name": MEET_NAME}, dqs, "PASA", datetime.now().astimezone(), constants.COACH_SORT_BY_NAME).decode()
        self.assertLess(page.index("Zed Adams"), page.index("Amy Young"))  # by last name: Adams before Young
        self.assertIn("2 DQs", page)
        self.assertLess(page.index("Amy Young"), page.index("PASA-A"))  # relays after the swimmers
        self.assertLess(page.index("Event 3"), page.index("Event 9"))  # a swimmer's DQs in event order
        self.assertNotIn("Other Club", page)
        self.assertIn("sort=name", page)  # the slip links keep the sort for the way back
        by_event = render_dq_list({"name": MEET_NAME}, dqs, None, datetime.now().astimezone(), constants.COACH_SORT_BY_NAME).decode()
        self.assertNotIn("By swimmer", by_event)  # the sort choice appears once a club is chosen

    def test_open_protest_window_is_shown_until_it_closes(self) -> None:
        now = datetime.now(timezone.utc)
        open_dq = _dq(constants.DQ_STATE_NOTIFIED, protest_deadline=(now + timedelta(minutes=10)).isoformat())
        closed_dq = _dq(constants.DQ_STATE_NOTIFIED, protest_deadline=(now - timedelta(minutes=1)).isoformat())
        self.assertIn("Protest window open", render_dq_list({"name": MEET_NAME}, [open_dq], None, now).decode())
        self.assertNotIn("Protest window open", render_dq_list({"name": MEET_NAME}, [closed_dq], None, now).decode())

    def test_infraction_text_without_a_code(self) -> None:
        self.assertEqual(infraction_text({"infractions": [{"description": "Delay of meet", "code": None}]}), "Delay of meet")

    def test_no_meet(self) -> None:
        self.assertIn("No meet is running", render_dq_list(None, [], None, datetime.now()).decode())


class CoachServerTests(unittest.TestCase):
    """The coach server: password, cookie, the list and one slip."""

    def setUp(self) -> None:
        self.database = Database(Path(tempfile.mkdtemp()) / "test.db")
        self.database.initialize()
        self.store = DqStore(self.database)
        self.store.initialize()
        self.meet_id = self.database.create_meet(MEET_NAME, "2026-10-16")
        self.notified_id = self.store.create_dq(dict(COMPLETE_DQ), self.meet_id)
        self.store.change_state(self.notified_id, constants.DQ_STATE_ACCEPTED, "Deck Referee")
        self.store.change_state(self.notified_id, constants.DQ_STATE_NOTIFIED, "HTML Publish")
        self.hidden_id = self.store.create_dq(dict(COMPLETE_DQ, lane="5", swimmer="Not Told Yet"), self.meet_id)
        self.coach_page = CoachPage(self.database, self.store, port=0, host=LOOPBACK_HOST)
        self.assertTrue(self.coach_page.start())
        self.port = self.coach_page.bound_port

    def tearDown(self) -> None:
        self.coach_page.stop()

    def _get(self, path: str, cookie: str | None = None) -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.port, timeout=5)
        connection.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        return connection.getresponse()

    def _sign_in(self) -> str:
        response = self._get("/?" + constants.COACH_QUERY_KEY_PASSWORD + "=" + self.coach_page.password.upper())
        self.assertEqual(response.status, 303)
        return response.getheader("Set-Cookie").split(";")[0]

    def test_password_is_needed(self) -> None:
        page = self._get("/").read().decode()
        self.assertIn("Meet password", page)
        self.assertNotIn("Jane Example", page)
        wrong = self._get("/?" + constants.COACH_QUERY_KEY_PASSWORD + "=nope").read().decode()
        self.assertIn("password didn", wrong)

    def test_password_form(self) -> None:
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.port, timeout=5)
        body = f"{constants.COACH_FORM_FIELD_PASSWORD}={self.coach_page.password}"
        connection.request("POST", constants.COACH_ROUTE_LOGIN, body=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        response = connection.getresponse()
        self.assertEqual(response.status, 303)
        self.assertIn(constants.COACH_COOKIE_NAME, response.getheader("Set-Cookie"))

    def test_signed_in_phone_sees_only_notified_dqs_and_their_slips(self) -> None:
        cookie = self._sign_in()
        page = self._get("/", cookie).read().decode()
        self.assertIn("Jane Example", page)
        self.assertNotIn("Not Told Yet", page)
        slip = self._get(f"{constants.COACH_ROUTE_DQ}{self.notified_id}", cookie)
        self.assertEqual(slip.status, 200)
        self.assertIn("DISQUALIFICATION REPORT", slip.read().decode())
        hidden = self._get(f"{constants.COACH_ROUTE_DQ}{self.hidden_id}", cookie)
        self.assertEqual(hidden.status, 303)

    def test_new_password_signs_phones_out(self) -> None:
        cookie = self._sign_in()
        self.coach_page.new_password()
        self.assertIn("Meet password", self._get("/", cookie).read().decode())

    def test_password_shape(self) -> None:
        password = generate_password()
        self.assertEqual(len(password), constants.COACH_PASSWORD_LENGTH)
        self.assertTrue(set(password) <= set(constants.COACH_PASSWORD_ALPHABET))

    def test_addresses_exclude_loopback(self) -> None:
        self.assertFalse(any(address.startswith("127.") for address in local_ipv4_addresses()))


class CoachPageAdminTests(unittest.TestCase):
    """Meet setup turns the coach page on and off through the admin server."""

    def setUp(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.database = Database(root / "test.db")
        self.database.initialize()
        self.server = DqTranscribeServer((LOOPBACK_HOST, 0), root / "recordings", self.database, coach_port=0)
        self.server.coach_page.host = LOOPBACK_HOST
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.coach_page.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.server.server_address[1], timeout=5)
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path, body=body, headers={constants.CONTENT_TYPE_HEADER: constants.JSON_CONTENT_TYPE})
        response = connection.getresponse()
        self.assertEqual(response.status, 200, path)
        return json.loads(response.read())[constants.RESPONSE_KEY_COACH_PAGE]

    def test_switch_on_and_off_and_remembered(self) -> None:
        self.assertFalse(self._request("GET", constants.ROUTE_COACH_PAGE)["running"])
        status = self._request("POST", constants.ROUTE_COACH_PAGE, {constants.REQUEST_KEY_ENABLED: True})
        self.assertTrue(status["running"])
        self.assertEqual(self.database.get_setting(constants.SETTING_COACH_PAGE_ENABLED), constants.SETTING_TRUE)
        old_password = status["password"]
        self.assertNotEqual(self._request("POST", constants.ROUTE_COACH_PAGE_PASSWORD, {})["password"], old_password)
        self.assertFalse(self._request("POST", constants.ROUTE_COACH_PAGE, {constants.REQUEST_KEY_ENABLED: False})["running"])

    def test_sign_and_qr_script_are_served(self) -> None:
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.server.server_address[1], timeout=5)
        connection.request("GET", constants.ROUTE_COACH_SIGN)
        sign = connection.getresponse().read().decode()
        self.assertIn("DQs for coaches", sign)
        self.assertNotIn("${", sign)
        connection.request("GET", constants.ROUTE_VENDOR + constants.QR_SCRIPT_FILENAME)
        script = connection.getresponse()
        self.assertEqual(script.status, 200)
        self.assertIn("qrcode", script.read().decode())


if __name__ == "__main__":
    unittest.main()
