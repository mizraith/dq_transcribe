"""The coach page server: a separate, read-only web server for phones on the meet Wi-Fi.

The admin app listens on 127.0.0.1 only, so nothing on the network can reach the
capture, transcripts or DQ editing. This second server listens on every network
the tablet is on (``constants.COACH_SERVER_HOST``) and can do exactly three
things:

* ``GET /``: the active meet's posted DQs by event (``coach_page.render_dq_list``),
  or the password form;
* ``GET /dq/<id>``: one posted DQ's slip, the same layout as the printed coach copy;
* ``POST /login``: check the meet password.

It runs in a thread of the main app (so it shares the database objects) and is
started and stopped from Meet setup. It never writes to the database, except
the coach page settings the admin changes through ``CoachPage``.

**Access:** one meet password (a thin wall to keep curious parents out, as the
owner asked). The QR code's link carries the password in ``?key=``; the server
swaps it for a cookie and redirects, so the password does not stay in the
address bar. Changing the password signs every phone out. The password never
appears in the logs.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import socket
import threading
from datetime import datetime
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from dq_transcribe import constants
from dq_transcribe.coach_page import (
    BACK_TO_LIST_LABEL,
    coach_visible_dqs,
    list_url,
    normalize_sort,
    render_dq_list,
    render_login_page,
)
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqStore
from dq_transcribe.slip_page import render_slips

LOGGER = logging.getLogger(__name__)
_WEB_DIRECTORY = Path(__file__).parent / constants.WEB_DIRECTORY_NAME
COACH_URL_FORMAT = "http://{address}:{port}/"
LOOPBACK_PREFIX = "127."
SLIP_TITLE_FORMAT = "DQ: event {event}, heat {heat}, lane {lane}"


def generate_password() -> str:
    """A short random password that is easy to read off a sign and type on a phone."""
    return "".join(secrets.choice(constants.COACH_PASSWORD_ALPHABET) for _ in range(constants.COACH_PASSWORD_LENGTH))


def local_ipv4_addresses() -> list[str]:
    """The tablet's own IPv4 addresses on its networks (best first), loopback excluded.

    Connecting a UDP socket sends nothing; it only asks the system which address
    it would use to reach the target. A public target finds the default route; the
    private targets find a Wi-Fi without internet (the meet's own router) or the
    tablet's hotspot. Android does not let apps list network interfaces, so this is
    the reliable way there.
    """
    addresses: list[str] = []
    for target in constants.ADDRESS_PROBE_TARGETS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((target, constants.ADDRESS_PROBE_PORT))
                address = probe.getsockname()[0]
        except OSError:
            continue
        if address and not address.startswith(LOOPBACK_PREFIX) and address != constants.COACH_SERVER_HOST and address not in addresses:
            addresses.append(address)
    return addresses


class CoachServer(ThreadingHTTPServer):
    """The read-only coach page server.

    Attributes:
        coach_page: The controller (password, cookie check).
        database: App storage (meets, settings).
        dq_store: DQ storage (read only here).
    """

    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], coach_page: CoachPage) -> None:
        """Bind the server (raises ``OSError`` if the port is taken)."""
        self.coach_page = coach_page
        self.database = coach_page.database
        self.dq_store = coach_page.dq_store
        super().__init__(server_address, CoachRequestHandler)


class CoachRequestHandler(BaseHTTPRequestHandler):
    """Serves the coach list, one DQ's slip, the slip font and the password form."""

    server: CoachServer

    def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """The DQ list, a DQ's slip, or the slip font."""
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        club = (query.get(constants.COACH_QUERY_KEY_CLUB) or [""])[0].strip() or None
        sort = normalize_sort((query.get(constants.COACH_QUERY_KEY_SORT) or [""])[0].strip())
        offered_password = (query.get(constants.COACH_QUERY_KEY_PASSWORD) or [""])[0].strip()
        if url.path.startswith(constants.ROUTE_FONTS):
            self._send_font(url.path[len(constants.ROUTE_FONTS):])
            return
        if offered_password:
            self._sign_in(offered_password, list_url(club, sort))
            return
        if not self._signed_in():
            self._send_html(HTTPStatus.OK, render_login_page(self._meet_name()))
            return
        if url.path == constants.COACH_ROUTE_LIST:
            meet_id = self.server.database.get_active_meet_id()
            meet = self.server.database.get_meet(meet_id) if meet_id is not None else None
            dqs = self.server.dq_store.list_dqs(meet_id) if meet is not None else []
            self._send_html(HTTPStatus.OK, render_dq_list(meet, dqs, club, datetime.now().astimezone(), sort))
        elif url.path.startswith(constants.COACH_ROUTE_DQ) and url.path[len(constants.COACH_ROUTE_DQ):].isdigit():
            self._send_slip(int(url.path[len(constants.COACH_ROUTE_DQ):]), club, sort)
        else:
            self._redirect(constants.COACH_ROUTE_LIST)

    def do_POST(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """The password form."""
        if urlsplit(self.path).path != constants.COACH_ROUTE_LOGIN:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get(constants.CONTENT_LENGTH_HEADER, "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > constants.MAX_COACH_FORM_BYTES:
            self._send_html(HTTPStatus.OK, render_login_page(self._meet_name(), wrong_password=True))
            return
        form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        self._sign_in((form.get(constants.COACH_FORM_FIELD_PASSWORD) or [""])[0].strip(), constants.COACH_ROUTE_LIST)

    # --- Helpers -----------------------------------------------------------------

    def _meet_name(self) -> str | None:
        """The active meet's name, for the sign-in page."""
        meet_id = self.server.database.get_active_meet_id()
        meet = self.server.database.get_meet(meet_id) if meet_id is not None else None
        return meet["name"] if meet else None

    def _signed_in(self) -> bool:
        """True if the phone's cookie matches the current password."""
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        morsel = cookie.get(constants.COACH_COOKIE_NAME)
        return morsel is not None and self.server.coach_page.cookie_is_valid(morsel.value)

    def _sign_in(self, password: str, next_url: str) -> None:
        """Set the cookie and go on if the password is right; otherwise show the form again."""
        if not self.server.coach_page.password_is_valid(password):
            self._send_html(HTTPStatus.OK, render_login_page(self._meet_name(), wrong_password=True))
            return
        cookie = (
            f"{constants.COACH_COOKIE_NAME}={self.server.coach_page.cookie_value()}; Path=/; "
            f"Max-Age={constants.COACH_COOKIE_MAX_AGE_SECONDS}; HttpOnly; SameSite=Lax"
        )
        self._redirect(next_url, cookie)

    def _send_slip(self, dq_id: int, club: str | None, sort: str) -> None:
        """One posted DQ's slip (only DQs of the active meet the coach may see)."""
        meet_id = self.server.database.get_active_meet_id()
        dqs = coach_visible_dqs(self.server.dq_store.list_dqs(meet_id)) if meet_id is not None else []
        dq = next((item for item in dqs if item["id"] == dq_id), None)
        if dq is None:
            self._redirect(list_url(club, sort))
            return
        title = SLIP_TITLE_FORMAT.format(event=dq.get("event") or "?", heat=dq.get("heat") or "?", lane=dq.get("lane") or "?")
        self._send_html(HTTPStatus.OK, render_slips([dq], title, back_link=(list_url(club, sort), BACK_TO_LIST_LABEL)))

    def _send_font(self, filename: str) -> None:
        """The slip's script font (only plain file names inside web/fonts/)."""
        font_path = _WEB_DIRECTORY / constants.FONTS_DIRECTORY_NAME / filename
        if "/" in filename or filename.startswith(".") or not font_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(HTTPStatus.OK, constants.FONT_CONTENT_TYPE, font_path.read_bytes(), cache=True)

    def _redirect(self, location: str, cookie: str | None = None) -> None:
        """Send the browser on to another page of this server."""
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header(constants.CONTENT_LENGTH_HEADER, "0")
        self.end_headers()

    def _send_html(self, status: HTTPStatus, body: bytes) -> None:
        """Send a page that phones must not cache (it changes as DQs are posted)."""
        self._send_bytes(status, constants.HTML_CONTENT_TYPE, body)

    def _send_bytes(self, status: HTTPStatus, content_type: str, body: bytes, cache: bool = False) -> None:
        """Send a complete response."""
        self.send_response(status)
        self.send_header(constants.CONTENT_TYPE_HEADER, content_type)
        self.send_header(constants.CONTENT_LENGTH_HEADER, str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Log requests without their query strings (the QR link carries the password)."""
        LOGGER.info("coach %s %s %s", self.address_string(), self.command, urlsplit(self.path).path)


class CoachPage:
    """Starts and stops the coach server, and keeps its password.

    The on/off choice and the password are app settings, so the coach page comes
    back by itself after the app restarts.

    Attributes:
        database: App storage.
        dq_store: DQ storage.
        port: Port to listen on.
    """

    def __init__(self, database: Database, dq_store: DqStore, port: int = constants.COACH_SERVER_PORT, host: str = constants.COACH_SERVER_HOST) -> None:
        """Remember where to listen; nothing starts until ``start`` (or ``restore``)."""
        self.database = database
        self.dq_store = dq_store
        self.port = port
        self.host = host
        self._server: CoachServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._error: str | None = None

    # --- Password -------------------------------------------------------------------

    @property
    def password(self) -> str:
        """The meet password (made the first time it is needed)."""
        password = self.database.get_setting(constants.SETTING_COACH_PAGE_PASSWORD)
        if not password:
            password = self.new_password()
        return password

    def new_password(self) -> str:
        """Pick a new password; every phone signed in with the old one must sign in again."""
        password = generate_password()
        self.database.set_setting(constants.SETTING_COACH_PAGE_PASSWORD, password)
        return password

    def password_is_valid(self, offered: str) -> bool:
        """True if ``offered`` is the password (case and spaces ignored)."""
        normalized = "".join(offered.split()).lower()
        return bool(normalized) and hmac.compare_digest(normalized.encode("utf-8"), self.password.encode("utf-8"))

    def _cookie_secret(self) -> str:
        """A random secret that turns the password into the cookie value."""
        secret = self.database.get_setting(constants.SETTING_COACH_COOKIE_SECRET)
        if not secret:
            secret = secrets.token_hex(16)
            self.database.set_setting(constants.SETTING_COACH_COOKIE_SECRET, secret)
        return secret

    def cookie_value(self) -> str:
        """The cookie a signed-in phone carries (changes with the password)."""
        return hmac.new(self._cookie_secret().encode("utf-8"), self.password.encode("utf-8"), hashlib.sha256).hexdigest()

    def cookie_is_valid(self, value: str) -> bool:
        """True if a phone's cookie was given for the current password."""
        return hmac.compare_digest(value.encode("utf-8"), self.cookie_value().encode("utf-8"))

    # --- Running ----------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """True while the server is listening."""
        return self._server is not None

    def restore(self) -> None:
        """Start the server if the admin left it on (called when the app starts)."""
        if self.database.get_setting(constants.SETTING_COACH_PAGE_ENABLED) == constants.SETTING_TRUE:
            self.start()

    def set_enabled(self, enabled: bool) -> None:
        """Turn the coach page on or off, and remember the choice."""
        self.database.set_setting(constants.SETTING_COACH_PAGE_ENABLED, constants.SETTING_TRUE if enabled else constants.SETTING_FALSE)
        if enabled:
            self.start()
        else:
            self.stop()

    def start(self) -> bool:
        """Start listening (no-op if already running). Returns False if the port could not be opened."""
        with self._lock:
            if self._server is not None:
                return True
            try:
                server = CoachServer((self.host, self.port), self)
            except OSError as error:
                self._error = f"Could not open port {self.port}: {error.strerror or error}"
                LOGGER.warning("Coach page not started: %s", self._error)
                return False
            self._error = None
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, name="coach-page", daemon=True)
            self._thread.start()
            LOGGER.info("Coach page on port %d", self.port)
            return True

    def stop(self) -> None:
        """Stop listening (no-op if not running)."""
        with self._lock:
            server, thread = self._server, self._thread
            self._server = self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            LOGGER.info("Coach page stopped")

    @property
    def bound_port(self) -> int:
        """The port actually in use (differs from ``port`` when port 0 was asked for, in tests)."""
        return self._server.server_address[1] if self._server is not None else self.port

    def status(self) -> dict[str, Any]:
        """What Meet setup shows: on/off, the addresses to open, the QR links and the password."""
        addresses = local_ipv4_addresses()
        urls = [COACH_URL_FORMAT.format(address=address, port=self.bound_port) for address in addresses]
        password = self.password
        return {
            "enabled": self.database.get_setting(constants.SETTING_COACH_PAGE_ENABLED) == constants.SETTING_TRUE,
            "running": self.running,
            "port": self.bound_port,
            "addresses": addresses,
            "urls": urls,
            "qr_urls": [url + "?" + urlencode({constants.COACH_QUERY_KEY_PASSWORD: password}) for url in urls],
            "password": password,
            "error": self._error,
        }
