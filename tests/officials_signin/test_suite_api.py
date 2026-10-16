"""The Admin Assistant suite API: the one current meet and session that every app follows.

DQ Transcribe (another port) reads and sets it from the browser, so only that origin
gets CORS headers.

Run from the repo root with:
    PYTHONPATH=src:tests python3 -m unittest discover -s tests/officials_signin
"""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from officials_signin import constants
from officials_signin.database import Database
from officials_signin.server import SigninServer

LOOPBACK_HOST = "127.0.0.1"
DQ_ORIGIN = f"http://localhost:{constants.DQ_TRANSCRIBE_PORT}"
MEET_DATE = date(2026, 10, 16)


class SuiteApiTests(unittest.TestCase):
    """Current meet/session for every app, and who may call it from another port."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.database = Database(self.root / "real.db")
        self.database.initialize()
        self.meet = self.database.create_meet("Candy Meet", MEET_DATE.isoformat())
        self.friday = self.database.add_session("Friday PM", MEET_DATE.isoformat(), "16:45", "PM", "15:45")
        self.saturday = self.database.add_session("Saturday AM", "2026-10-17", "08:00", "AM", "07:00")
        self.other = self.database.create_meet("Fall Classic", "2026-11-01")
        self.database.add_session("Saturday AM", "2026-11-01", "08:00")
        self.database.open_meet(self.meet, MEET_DATE)
        self.server = SigninServer(
            (LOOPBACK_HOST, 0), self.database,
            diagnostics_directory=self.root / "diagnostics", demo_database_path=self.root / "demo.db",
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, origin: str | None = None
                ) -> tuple[int, Any, dict[str, str]]:
        connection = http.client.HTTPConnection(LOOPBACK_HOST, self.server.server_address[1], timeout=10)
        headers = {} if body is None else {constants.CONTENT_TYPE_HEADER: constants.JSON_CONTENT_TYPE}
        if origin:
            headers[constants.ORIGIN_HEADER] = origin
        connection.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            decoded: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = raw
        return response.status, decoded, dict(response.getheaders())

    def test_current_meet_and_sessions(self) -> None:
        status, current, _ = self.request("GET", constants.ROUTE_SUITE_CURRENT)
        self.assertEqual(status, 200)
        self.assertEqual(current[constants.KEY_SUITE], constants.SUITE_TITLE)
        self.assertEqual(current[constants.KEY_MEET][constants.KEY_NAME], "Candy Meet")
        self.assertEqual([s[constants.KEY_NAME] for s in current[constants.KEY_SESSIONS]], ["Friday PM", "Saturday AM"])
        self.assertEqual(current[constants.KEY_ACTIVE_SESSION_ID], self.friday)
        self.assertFalse(current[constants.KEY_DEMO])
        self.assertTrue(current[constants.KEY_VERSION])

    def test_select_session_and_meet_changes_the_version(self) -> None:
        _, before, _ = self.request("GET", constants.ROUTE_SUITE_CURRENT)
        status, after, _ = self.request("POST", constants.ROUTE_SUITE_SELECT, {constants.KEY_SESSION_ID: self.saturday})
        self.assertEqual(status, 200, after)
        self.assertEqual(after[constants.KEY_ACTIVE_SESSION_ID], self.saturday)
        self.assertNotEqual(before[constants.KEY_VERSION], after[constants.KEY_VERSION])
        _, again, _ = self.request("GET", constants.ROUTE_SUITE_CURRENT)
        self.assertEqual(again[constants.KEY_VERSION], after[constants.KEY_VERSION])  # stable when nothing changed
        _, other, _ = self.request("POST", constants.ROUTE_SUITE_SELECT, {constants.KEY_MEET_ID: self.other})
        self.assertEqual(other[constants.KEY_MEET][constants.KEY_NAME], "Fall Classic")
        # The officials page sees the same.
        _, state, _ = self.request("GET", constants.ROUTE_STATE)
        self.assertEqual(state[constants.KEY_MEET][constants.KEY_NAME], "Fall Classic")
        self.assertEqual(self.request("POST", constants.ROUTE_SUITE_SELECT, {constants.KEY_MEET_ID: 999})[0], 400)

    def test_dq_transcribe_origin_gets_cors_headers(self) -> None:
        _, _, headers = self.request("GET", constants.ROUTE_SUITE_CURRENT, origin=DQ_ORIGIN)
        self.assertEqual(headers.get(constants.CORS_ALLOW_ORIGIN_HEADER), DQ_ORIGIN)
        self.assertEqual(headers.get(constants.CORS_ALLOW_CREDENTIALS_HEADER), "true")
        status, _, headers = self.request("OPTIONS", constants.ROUTE_SUITE_SELECT, origin=DQ_ORIGIN)
        self.assertEqual(status, 204)
        self.assertIn("POST", headers.get(constants.CORS_ALLOW_METHODS_HEADER, ""))

    def test_other_origins_and_routes_get_no_cors(self) -> None:
        for origin in ("http://evil.example:8000", "http://localhost:9999"):
            _, _, headers = self.request("GET", constants.ROUTE_SUITE_CURRENT, origin=origin)
            self.assertNotIn(constants.CORS_ALLOW_ORIGIN_HEADER, headers)
            self.assertEqual(self.request("OPTIONS", constants.ROUTE_SUITE_SELECT, origin=origin)[0], 404)
        _, _, headers = self.request("GET", constants.ROUTE_STATE, origin=DQ_ORIGIN)
        self.assertNotIn(constants.CORS_ALLOW_ORIGIN_HEADER, headers)  # only the suite API is shared

    def test_meets_list_for_linking(self) -> None:
        _, reply, _ = self.request("GET", constants.ROUTE_SUITE_MEETS, origin=DQ_ORIGIN)
        self.assertEqual(sorted(meet[constants.KEY_NAME] for meet in reply[constants.KEY_MEETS]), ["Candy Meet", "Fall Classic"])

    def test_main_page_and_app_pages(self) -> None:
        """"/" is the Admin Assistant main page (launcher + meets); each app has its own page."""
        status, home, _ = self.request("GET", constants.ROUTE_HOME)
        self.assertEqual(status, 200)
        self.assertIn(f"<h1>{constants.SUITE_TITLE}</h1>".encode(), home)
        self.assertIn(b'id="app-launcher"', home)
        self.assertIn(b'id="setup-overlay"', home)
        status, officials, _ = self.request("GET", constants.ROUTE_OFFICIALS_PAGE)
        self.assertEqual(status, 200)
        self.assertIn(f"<h1>{constants.APP_TITLE}</h1>".encode(), officials)
        # All meet setup is on the main page now.
        self.assertNotIn(b'id="setup-overlay"', officials)
        self.assertNotIn(b'id="meets-overlay"', officials)
        status, script, _ = self.request("GET", constants.ROUTE_DESK_SHARED_SCRIPT)
        self.assertEqual(status, 200)
        # The launcher's apps come from constants.SUITE_APPS (in the page config).
        for app in constants.SUITE_APPS:
            self.assertIn(json.dumps(app).encode(), script)


if __name__ == "__main__":
    unittest.main()
