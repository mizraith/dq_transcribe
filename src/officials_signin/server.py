"""Local HTTP server for officials_signin.

Serves the touch page, the bundled OCR engine (Tesseract.js, under
``web/vendor``) and a small JSON API, and publishes the session roster at
``/roster.json`` for dq_transcribe to import. Standard library only, so it runs
the same on Android (Termux), ChromeOS (Linux), macOS and Linux.

The server binds to the loopback address only: it is reachable from this
device and nowhere else. Requests are never logged with names or member IDs.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import json
import logging
import random
import re
import string
import threading
from http.cookies import SimpleCookie
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from officials_signin import constants
from officials_signin.card_reader import CardReading, check_card, read_card
from officials_signin.database import Database, SessionFields, SigninError, Validation, not_checked_validation
from officials_signin.demo import DemoSize, build_demo, default_demo_size, planned_session_names, stored_demo_size
from officials_signin.export import build_meet_zip
from officials_signin.reports import render_meet_summary, render_session_summary, render_team_display
from officials_signin.roster import build_roster, roster_download_filename
from officials_signin.teams import (
    assign_mentors,
    build_team_view,
    chosen_team_count,
    fifteen_meter_changes,
    is_team_trainee,
    judges_from_signins,
    plan_teams,
)

LOGGER = logging.getLogger(__name__)

_WEB_DIRECTORY = Path(__file__).parent / constants.WEB_DIRECTORY_NAME
_VENDOR_DIRECTORY = _WEB_DIRECTORY / constants.VENDOR_DIRECTORY_NAME
_SIGNIN_ACTION_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_SIGNIN_PREFIX)}(\d+)"
    rf"({re.escape(constants.SIGNIN_VALIDATE_SUFFIX)}|{re.escape(constants.SIGNIN_REMOVE_SUFFIX)})$"
)
_MEET_ACTION_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_MEET_PREFIX)}(\d+)"
    rf"({re.escape(constants.MEET_OPEN_SUFFIX)}|{re.escape(constants.MEET_ARCHIVE_SUFFIX)}"
    rf"|{re.escape(constants.MEET_DELETE_SUFFIX)})$"
)
_MEET_ZIP_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_MEET_PREFIX)}(\d+){re.escape(constants.MEET_ZIP_SUFFIX)}$"
)
_SESSION_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_SESSION_PREFIX)}(\d+)$")
_SESSION_DELETE_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_SESSION_PREFIX)}(\d+){re.escape(constants.SESSION_DELETE_SUFFIX)}$"
)
_SIGNIN_EDIT_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_SIGNIN_PREFIX)}(\d+){re.escape(constants.SIGNIN_EDIT_SUFFIX)}$"
)
_SIGNIN_TEAM_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_SIGNIN_PREFIX)}(\d+){re.escape(constants.SIGNIN_TEAM_SUFFIX)}$"
)
_SIGNIN_SWAP_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_SIGNIN_PREFIX)}(\d+){re.escape(constants.SIGNIN_SWAP_SUFFIX)}$"
)
_TEAM_NAME_PATTERN = re.compile("^" + re.escape(constants.TEAM_NAME_FORMAT).replace(r"\{number\}", r"\d{1,2}") + "$")
_SCAN_ID_PATTERN = re.compile(constants.DIAGNOSTICS_SCAN_ID_PATTERN)
_DATE_PATTERN = re.compile(constants.DATE_PATTERN)
_TIME_PATTERN = re.compile(constants.TIME_OF_DAY_PATTERN)


def build_web_config() -> dict[str, Any]:
    """Collect the settings the page scripts need, taken from ``constants``.

    Returns:
        A JSON-serializable dictionary, embedded into the scripts as ``${config}``.
    """
    return {
        "appTitle": constants.APP_TITLE,
        "routes": {
            "state": constants.ROUTE_STATE,
            "meets": constants.ROUTE_MEETS,
            "sessions": constants.ROUTE_SESSIONS,
            "activeSession": constants.ROUTE_ACTIVE_SESSION,
            "sessionPrefix": constants.ROUTE_SESSION_PREFIX,
            "sessionDeleteSuffix": constants.SESSION_DELETE_SUFFIX,
            "officials": constants.ROUTE_OFFICIALS,
            "cardReading": constants.ROUTE_CARD_READING,
            "signins": constants.ROUTE_SIGNINS,
            "signinPrefix": constants.ROUTE_SIGNIN_PREFIX,
            "validateSuffix": constants.SIGNIN_VALIDATE_SUFFIX,
            "removeSuffix": constants.SIGNIN_REMOVE_SUFFIX,
            "editSuffix": constants.SIGNIN_EDIT_SUFFIX,
            "roster": constants.ROUTE_ROSTER,
            "printSession": constants.ROUTE_PRINT_SESSION,
            "printMeet": constants.ROUTE_PRINT_MEET,
            "teamDisplay": constants.ROUTE_TEAM_DISPLAY,
            "demo": constants.ROUTE_DEMO,
            "demoExit": constants.ROUTE_DEMO_EXIT,
            "demoOpen": constants.ROUTE_DEMO_OPEN,
            "demoReset": constants.ROUTE_DEMO_RESET,
            "meetPrefix": constants.ROUTE_MEET_PREFIX,
            "meetSave": constants.ROUTE_MEET_SAVE,
            "home": constants.ROUTE_HOME,
            "officialsPage": constants.ROUTE_OFFICIALS_PAGE,
            "coaches": constants.ROUTE_COACHES,
            "meetOpenSuffix": constants.MEET_OPEN_SUFFIX,
            "meetArchiveSuffix": constants.MEET_ARCHIVE_SUFFIX,
            "meetDeleteSuffix": constants.MEET_DELETE_SUFFIX,
            "meetZipSuffix": constants.MEET_ZIP_SUFFIX,
            "meetZip": constants.ROUTE_MEET_ZIP,
            "diagnostics": constants.ROUTE_DIAGNOSTICS,
            "teams": constants.ROUTE_TEAMS,
            "teamsBuild": constants.ROUTE_TEAMS_BUILD,
            "teamsSettings": constants.ROUTE_TEAMS_SETTINGS,
            "teamSuffix": constants.SIGNIN_TEAM_SUFFIX,
            "swapSuffix": constants.SIGNIN_SWAP_SUFFIX,
            "rosterDownload": constants.ROUTE_ROSTER_DOWNLOAD,
        },
        "keys": {
            "error": constants.KEY_ERROR,
            "id": constants.KEY_ID,
            "name": constants.KEY_NAME,
            "startDate": constants.KEY_START_DATE,
            "date": constants.KEY_DATE,
            "startTime": constants.KEY_START_TIME,
            "sessionType": constants.KEY_SESSION_TYPE,
            "meetingTime": constants.KEY_OFFICIALS_MEETING_TIME,
            "estimatedMinutes": constants.KEY_ESTIMATED_MINUTES,
            "rotationSchedule": constants.KEY_ROTATION_SCHEDULE,
            "rotationMode": constants.KEY_ROTATION_MODE,
            "time": constants.KEY_TIME,
            "startTeam": constants.KEY_START_END_TEAM,
            "turnTeam": constants.KEY_TURN_END_TEAM,
            "signinCount": constants.KEY_SIGNIN_COUNT,
            "merged": constants.KEY_MERGED,
            "demo": constants.KEY_DEMO,
            "demoReady": constants.KEY_DEMO_READY,
            "meets": constants.KEY_MEETS,
            "activeMeetId": constants.KEY_ACTIVE_MEET_ID,
            "officialCount": constants.KEY_OFFICIAL_COUNT,
            "withSigninId": constants.KEY_WITH_SIGNIN_ID,
            "archived": constants.KEY_ARCHIVED,
            "sessionCount": constants.KEY_SESSIONS_COUNT,
            "meet": constants.KEY_MEET,
            "sessions": constants.KEY_SESSIONS,
            "activeSessionId": constants.KEY_ACTIVE_SESSION_ID,
            "sessionId": constants.KEY_SESSION_ID,
            "sessionIds": constants.KEY_SESSION_IDS,
            "signins": constants.KEY_SIGNINS,
            "officials": constants.KEY_OFFICIALS,
            "officialId": constants.KEY_OFFICIAL_ID,
            "texts": constants.KEY_TEXTS,
            "card": constants.KEY_CARD,
            "match": constants.KEY_MATCH,
            "roles": constants.KEY_ROLES,
            "trainee": constants.KEY_TRAINEE,
            "club": constants.KEY_CLUB,
            "lsc": constants.KEY_LSC,
            "zone": constants.KEY_ZONE,
            "yearsCertified": constants.KEY_YEARS_CERTIFIED,
            "validated": constants.KEY_VALIDATED,
            "validationMethod": constants.KEY_VALIDATION_METHOD,
            "problems": constants.KEY_PROBLEMS,
            "complete": constants.CARD_FIELD_COMPLETE,
            "missing": constants.CARD_FIELD_MISSING,
            "labelsFound": constants.CARD_FIELD_LABELS_FOUND,
            "memberId": constants.CARD_FIELD_MEMBER_ID,
            "scanId": constants.KEY_SCAN_ID,
            "record": constants.KEY_RECORD,
            "image": constants.KEY_IMAGE,
            "cardName": constants.CARD_FIELD_NAME,
            "team": constants.KEY_TEAM,
            "teams": constants.KEY_TEAMS,
            "members": constants.KEY_MEMBERS,
            "jurisdiction": constants.KEY_JURISDICTION,
            "pattern": constants.KEY_PATTERN,
            "trainees": constants.KEY_TRAINEES,
            "mentor": constants.KEY_MENTOR,
            "mentorSigninId": constants.KEY_MENTOR_SIGNIN_ID,
            "assignment": constants.KEY_ASSIGNMENT,
            "teamLead": constants.KEY_TEAM_LEAD,
            "lanes": constants.KEY_LANES,
            "laneChoices": constants.KEY_LANE_CHOICES,
            "teamCount": constants.KEY_TEAM_COUNT,
            "proposedTeamCount": constants.KEY_PROPOSED_TEAM_COUNT,
            "alternativeTeamCount": constants.KEY_ALTERNATIVE_TEAM_COUNT,
            "layouts": constants.KEY_LAYOUTS,
            "teamSize": constants.KEY_TEAM_SIZE,
            "extras": constants.KEY_EXTRAS,
            "built": constants.KEY_BUILT,
            "unplaced": constants.KEY_UNPLACED,
            "awaitingCheck": constants.KEY_AWAITING_CHECK,
            "jurisdictionFlipped": constants.KEY_JURISDICTION_FLIPPED,
            "jurisdictions": constants.KEY_JURISDICTIONS,
            "startEnd": constants.KEY_START_END,
            "turnEnd": constants.KEY_TURN_END,
            "laneRange": constants.KEY_LANE_RANGE,
            "uneven": constants.KEY_UNEVEN,
            "unpairedTrainees": constants.KEY_UNPAIRED_TRAINEES,
            "rotation": constants.KEY_ROTATION,
            "extraAssignments": constants.KEY_EXTRA_ASSIGNMENTS,
            "fifteenMeterOnTeams": constants.KEY_FIFTEEN_METER_ON_TEAMS,
            "judgeCount": constants.KEY_JUDGE_COUNT,
            "cardMeetId": constants.KEY_CARD_MEET_ID,
        },
        "cardFields": [[name, constants.CARD_FIELD_LABELS[name]] for name in constants.CARD_REQUIRED_FIELDS],
        "roles": list(constants.ROSTER_ROLES),
        "teamPoolRole": constants.TEAM_POOL_ROLE,
        "demoResetWarningSeconds": constants.DEMO_RESET_WARNING_SECONDS,
        "assignmentShortLabels": constants.ASSIGNMENT_SHORT_LABELS,
        "assignmentRelief": constants.ASSIGNMENT_RELIEF,
        "suiteTitle": constants.SUITE_TITLE,
        "suiteApps": [dict(app) for app in constants.SUITE_APPS],
        "homeAppKey": constants.HOME_APP_KEY,
        "meetsMenuLabel": constants.MEETS_MENU_LABEL,
        "officialsAppKey": constants.OFFICIALS_APP_KEY,
        "coachesAppKey": constants.COACHES_APP_KEY,
        "deskChannelName": constants.DESK_CHANNEL_NAME,
        "deskChangedMessage": constants.DESK_CHANGED_MESSAGE,
        "deskRefreshSeconds": constants.DESK_REFRESH_SECONDS,
        "lscChoices": [[code, constants.LSC_NAMES[code]] for code in sorted(constants.LSC_NAMES, key=constants.LSC_NAMES.get)],
        "lscNames": constants.LSC_NAMES,
        "defaultLsc": constants.DEFAULT_LSC_CODE,
        "openQueryKey": constants.OPEN_QUERY_KEY,
        "openTeamsValue": constants.OPEN_TEAMS_VALUE,
        "coachesPage": _coaches_module() is not None,
        "rotationModes": [[mode, constants.ROTATION_MODE_LABELS[mode]] for mode in constants.ROTATION_MODES],
        "assignmentFifteenMeter": constants.ASSIGNMENT_FIFTEEN_METER,
        "assignmentAcj": constants.ASSIGNMENT_ACJ,
        "sessionTypes": list(constants.SESSION_TYPES),
        "sessionTypeOtherLabel": constants.SESSION_TYPE_OTHER_LABEL,
        "sessionLetterTypes": list(constants.SESSION_LETTER_TYPES),
        "sessionLetterPrefix": constants.SESSION_LETTER_PREFIX,
        "meetingMinutesBeforeStart": constants.OFFICIALS_MEETING_MINUTES_BEFORE_START,
        "defaultSessionMinutes": constants.DEFAULT_SESSION_MINUTES,
        "sessionLengthStepMinutes": constants.SESSION_LENGTH_STEP_MINUTES,
        "maxSessionMinutes": constants.MAX_SESSION_MINUTES,
        "defaultRole": constants.DEFAULT_ROLE,
        "validationMethods": {
            "camera": constants.VALIDATION_CAMERA,
            "visual": constants.VALIDATION_VISUAL,
            "none": constants.VALIDATION_NONE,
        },
        "ocr": {
            "enginePath": constants.OCR_ENGINE_PATH,
            "languageDataPath": constants.OCR_LANGUAGE_DATA_PATH,
            "workerScript": constants.OCR_WORKER_SCRIPT_FILENAME,
            "coreScript": constants.OCR_CORE_SCRIPT_FILENAME,
            "language": constants.OCR_LANGUAGE,
            "pageSegmentationModes": list(constants.OCR_PAGE_SEGMENTATION_MODES),
            "workerCount": constants.OCR_WORKER_COUNT,
            "workerStaggerMilliseconds": constants.OCR_WORKER_STAGGER_MILLISECONDS,
            "orientations": [list(orientation) for orientation in constants.OCR_ORIENTATIONS],
            "guide": {
                "analysisWidth": constants.GUIDE_ANALYSIS_WIDTH,
                "intervalMilliseconds": constants.GUIDE_INTERVAL_MILLISECONDS,
                "goodChecksToCapture": constants.GUIDE_GOOD_CHECKS_TO_CAPTURE,
                "minScreenShare": constants.GUIDE_MIN_SCREEN_SHARE,
                "minScreenAreaShare": constants.GUIDE_MIN_SCREEN_AREA_SHARE,
                "edgeMarginShare": constants.GUIDE_EDGE_MARGIN_SHARE,
                "minSharpness": constants.GUIDE_MIN_SHARPNESS,
                "maxMotion": constants.GUIDE_MAX_MOTION,
                "sidewaysRatio": constants.GUIDE_SIDEWAYS_RATIO,
                "sidewaysInnerTrim": constants.GUIDE_SIDEWAYS_INNER_TRIM,
                "headerShare": constants.GUIDE_HEADER_SHARE,
                "burstFrames": constants.CAPTURE_BURST_FRAMES,
                "burstIntervalMilliseconds": constants.CAPTURE_BURST_INTERVAL_MILLISECONDS,
                "stillsKept": constants.CAPTURE_STILLS_KEPT,
                "photoTimeoutMilliseconds": constants.CAPTURE_PHOTO_TIMEOUT_MILLISECONDS,
                "uprightScreenWidth": constants.OCR_UPRIGHT_SCREEN_WIDTH,
                "maxUpscale": constants.OCR_MAX_UPSCALE,
                "messages": constants.GUIDE_MESSAGES,
                "colours": constants.GUIDE_COLOURS,
                "lineWidth": constants.GUIDE_FRAME_LINE_WIDTH,
                "diagnosticsEveryChecks": constants.GUIDE_DIAGNOSTICS_EVERY_CHECKS,
                "states": {
                    "noScreen": constants.GUIDE_STATE_NO_SCREEN,
                    "edge": constants.GUIDE_STATE_EDGE,
                    "turnSideways": constants.GUIDE_STATE_TURN_SIDEWAYS,
                    "small": constants.GUIDE_STATE_SMALL,
                    "blurry": constants.GUIDE_STATE_BLURRY,
                    "moving": constants.GUIDE_STATE_MOVING,
                    "good": constants.GUIDE_STATE_GOOD,
                    "reading": constants.GUIDE_STATE_READING,
                    "retry": constants.GUIDE_STATE_RETRY,
                },
            },
            "screenCellPixels": constants.SCREEN_CELL_PIXELS,
            "screenCellBrightQuantile": constants.SCREEN_CELL_BRIGHT_QUANTILE,
            "screenReferenceQuantile": constants.SCREEN_REFERENCE_QUANTILE,
            "screenBrightRatio": constants.SCREEN_BRIGHT_RATIO,
            "screenTextureSpread": constants.SCREEN_TEXTURE_SPREAD,
            "screenPlainCellWeight": constants.SCREEN_PLAIN_CELL_WEIGHT,
            "screenMinAreaShare": constants.OCR_SCREEN_MIN_AREA_SHARE,
            "screenMarginShare": constants.OCR_SCREEN_MARGIN_SHARE,
            "orientationUnlockMisses": constants.OCR_ORIENTATION_UNLOCK_MISSES,
            "cardHintPattern": constants.OCR_CARD_HINT_PATTERN,
            "contrastCutoffFraction": constants.OCR_CONTRAST_CUTOFF_FRACTION,
            "thresholdWindow": constants.OCR_THRESHOLD_WINDOW_PIXELS,
            "thresholdOffset": constants.OCR_THRESHOLD_OFFSET,
            "maxFrameWidth": constants.OCR_MAX_FRAME_WIDTH_PIXELS,
            "giveUpSeconds": constants.OCR_GIVE_UP_SECONDS,
            "textsLimit": constants.OCR_TEXTS_PER_REQUEST_LIMIT,
            "diagnosticsStorageKey": constants.DIAGNOSTICS_STORAGE_KEY,
            "diagnosticsJpegQuality": constants.DIAGNOSTICS_JPEG_QUALITY,
            "diagnosticsMaxFrames": constants.DIAGNOSTICS_MAX_FRAMES_PER_SCAN,
        },
        "maxYearsCertified": constants.MAX_YEARS_CERTIFIED,
    }


def _render(filename: str, values: dict[str, str]) -> bytes:
    """Fill a web template (a ``string.Template`` file) with values.

    Args:
        filename: Template file inside the web directory.
        values: Text for each ``${name}`` placeholder.

    Returns:
        The finished text, UTF-8 encoded.
    """
    template = string.Template((_WEB_DIRECTORY / filename).read_text("utf-8"))
    return template.substitute(values).encode("utf-8")


def _coaches_module() -> Any | None:
    """The coaches sign-in module (``officials_signin/coaches.py``), or None until it exists.

    Contract for that module (built in its own files by the coaches chat):

    - ``handle_get(handler, path, query) -> bool`` and ``handle_post(handler, path, payload)
      -> bool``: called for ``/coaches``, ``/coaches/...`` and ``/api/coaches/...``; return
      False for a path they do not know (the server then answers 404). They may raise
      ``database.SigninError`` for a 400 with a message for the admin.
    - Through ``handler`` they may use: ``handler.database`` (the real or demo database,
      already chosen for this browser), ``handler.in_demo``, ``handler._send_json``,
      ``handler._send_bytes`` and ``handler._send_json_error``.

    Returns:
        The imported module, or None when it is not there.
    """
    try:
        return importlib.import_module(constants.COACHES_MODULE_NAME)
    except ModuleNotFoundError as error:
        if error.name != constants.COACHES_MODULE_NAME:
            raise
        return None


def _is_coaches_path(path: str) -> bool:
    """True for the coaches page and its files and API."""
    return path == constants.ROUTE_COACHES or path.startswith(
        (constants.ROUTE_COACHES_PREFIX, constants.ROUTE_COACHES_API_PREFIX)
    )


def render_home_page() -> bytes:
    """Render the Admin Assistant main page (launcher and meets)."""
    return _render(
        constants.HOME_PAGE_FILENAME,
        {
            "suite_title": constants.SUITE_TITLE,
            "desk_stylesheet_route": constants.ROUTE_DESK_STYLESHEET,
            "desk_shared_route": constants.ROUTE_DESK_SHARED_SCRIPT,
            "meets_script_route": constants.ROUTE_MEETS_SCRIPT,
            "script_route": constants.ROUTE_HOME_SCRIPT,
        },
    )


def render_page() -> bytes:
    """Render the Officials Sign-In page."""
    return _render(
        constants.PAGE_FILENAME,
        {
            "app_title": constants.APP_TITLE,
            "desk_stylesheet_route": constants.ROUTE_DESK_STYLESHEET,
            "script_route": constants.ROUTE_SCRIPT,
            "card_scanner_route": constants.ROUTE_CARD_SCANNER_SCRIPT,
            "card_camera_route": constants.ROUTE_CARD_CAMERA_SCRIPT,
            "desk_shared_route": constants.ROUTE_DESK_SHARED_SCRIPT,
            "engine_script_route": constants.OCR_ENGINE_PATH + constants.OCR_ENGINE_SCRIPT_FILENAME,
        },
    )


def render_demo_page(current_size: DemoSize) -> bytes:
    """Render the demo setup page, starting from the current demo's size."""
    demo_config = {
        "routes": {"start": constants.ROUTE_DEMO_START, "exit": constants.ROUTE_DEMO_EXIT, "home": constants.ROUTE_HOME},
        "keys": {
            "sessions": constants.KEY_SESSIONS,
            "judges": constants.KEY_JUDGES_COUNT,
            "trainees": constants.KEY_TRAINEES_COUNT,
            "cornerOfficials": constants.KEY_CORNER_OFFICIALS,
            "error": constants.KEY_ERROR,
        },
        "size": current_size.to_payload(),
        "sessionNames": planned_session_names(date.today()),
        "cornerRoles": list(constants.DEMO_SPECIAL_ROLES),
        "maxSessions": constants.DEMO_MAX_SESSIONS,
        "maxJudges": constants.DEMO_MAX_JUDGES,
        "maxTrainees": constants.DEMO_MAX_TRAINEES,
        "defaultJudges": constants.DEMO_DEFAULT_JUDGES,
        "defaultTrainees": constants.DEMO_DEFAULT_TRAINEES,
    }
    return _render(constants.DEMO_PAGE_FILENAME, {"config": json.dumps(demo_config)})


def render_script(filename: str) -> bytes:
    """Render a page script, embedding the shared settings as ``${config}``."""
    return _render(filename, {"config": json.dumps(build_web_config())})


def resolve_vendor_file(url_path: str) -> Path | None:
    """Map a ``/vendor/...`` URL to a file inside the vendor folder, refusing anything outside it.

    Args:
        url_path: Request path starting with ``constants.ROUTE_VENDOR_PREFIX``.

    Returns:
        The file path, or None if it does not exist or would escape the folder.
    """
    relative = url_path[len(constants.ROUTE_VENDOR_PREFIX):]
    candidate = (_VENDOR_DIRECTORY / relative).resolve()
    vendor_root = _VENDOR_DIRECTORY.resolve()
    if vendor_root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def lsc_and_club_from_payload(payload: dict[str, Any]) -> tuple[str | None, str | None] | None:
    """The LSC and club chosen on a sign-in sheet, or None when the sheet did not send them.

    Raises:
        SigninError: For an LSC code that is not one of USA Swimming's 59.
    """
    if constants.KEY_LSC not in payload and constants.KEY_CLUB not in payload:
        return None
    lsc = str(payload.get(constants.KEY_LSC) or "").strip().upper() or None
    if lsc is not None and lsc not in constants.LSC_NAMES:
        raise SigninError("Unknown LSC")
    club = str(payload.get(constants.KEY_CLUB) or "").strip().upper()[: constants.CLUB_MAX_LENGTH] or None
    return lsc, club


def card_reading_from_payload(payload: Any) -> CardReading | None:
    """Rebuild a card reading sent back by the page (only known fields are kept)."""
    if not isinstance(payload, dict):
        return None
    return CardReading(**{name: payload.get(name) for name in CardReading.__dataclass_fields__ if name in payload})


class SigninServer(ThreadingHTTPServer):
    """HTTP server that holds the database.

    Attributes:
        database: Officials, meets, sessions and sign-ins (the real meet).
        demo_database_path: Where the demo meet is kept (see ``demo.py``).
        diagnostics_directory: Where camera diagnostics are saved (when switched on).
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        database: Database,
        diagnostics_directory: Path = constants.DIAGNOSTICS_DIRECTORY,
        demo_database_path: Path = constants.DEMO_DATABASE_PATH,
    ) -> None:
        """Create the server.

        Args:
            server_address: ``(host, port)`` to bind. Use port 0 to let the OS choose.
            database: Storage (already initialized).
            diagnostics_directory: Where camera diagnostics are saved.
            demo_database_path: Separate database used by browsers in demo mode.
        """
        self.database = database
        self.diagnostics_directory = diagnostics_directory
        self.demo_database_path = demo_database_path
        self.demo_database: Database | None = None
        self.demo_lock = threading.Lock()
        super().__init__(server_address, RequestHandler)

    def get_demo_database(self) -> Database:
        """The demo database (created empty on first use)."""
        with self.demo_lock:
            if self.demo_database is None:
                self.demo_database = Database(self.demo_database_path)
                self.demo_database.initialize()
            return self.demo_database


class RequestHandler(BaseHTTPRequestHandler):
    """Serves the page and the JSON API."""

    server: SigninServer

    @property
    def in_demo(self) -> bool:
        """True when this browser has switched to the demo meet (a cookie)."""
        cookie = SimpleCookie(self.headers.get(constants.COOKIE_HEADER, ""))
        morsel = cookie.get(constants.DEMO_COOKIE_NAME)
        return morsel is not None and morsel.value == constants.DEMO_COOKIE_ON

    def _suite_client_origin(self) -> str | None:
        """The calling page's origin when it is a suite app on another port (DQ Transcribe), else None.

        Only suite API requests from ``constants.SUITE_CLIENT_PORTS`` on
        ``constants.SUITE_CLIENT_HOSTS`` get CORS headers; everything else stays same-origin.
        """
        origin = self.headers.get(constants.ORIGIN_HEADER)
        if not origin or urlsplit(self.path).path not in constants.SUITE_ROUTES:
            return None
        parts = urlsplit(origin)
        if parts.hostname in constants.SUITE_CLIENT_HOSTS and parts.port in constants.SUITE_CLIENT_PORTS:
            return origin
        return None

    def _send_cors_headers(self) -> None:
        """Let a suite app on another port read the reply (and send this browser's demo cookie)."""
        origin = self._suite_client_origin()
        if origin is None:
            return
        self.send_header(constants.CORS_ALLOW_ORIGIN_HEADER, origin)
        self.send_header(constants.CORS_ALLOW_CREDENTIALS_HEADER, "true")
        self.send_header(constants.VARY_HEADER, constants.ORIGIN_HEADER)

    def do_OPTIONS(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Answer the browser's CORS check before a suite app posts to the suite API."""
        if self._suite_client_origin() is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header(constants.CORS_ALLOW_METHODS_HEADER, constants.CORS_ALLOWED_METHODS)
        self.send_header(constants.CORS_ALLOW_HEADERS_HEADER, constants.CORS_ALLOWED_HEADERS)
        self.send_header(constants.CONTENT_LENGTH_HEADER, "0")
        self.end_headers()

    @property
    def database(self) -> Database:
        """The real meet's database, or the demo one for a browser in demo mode."""
        return self.server.get_demo_database() if self.in_demo else self.server.database

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (signature from the base class)
        """Log the request line only through ``logging`` (bodies, with personal data, are never logged)."""
        LOGGER.debug(format, *args)

    # --- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Serve the page, scripts, OCR engine files, state and the roster."""
        url = urlsplit(self.path)
        path = url.path
        database = self.database

        if path == constants.ROUTE_HOME:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_home_page())
        elif path == constants.ROUTE_OFFICIALS_PAGE:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_page())
        elif path in (constants.ROUTE_HOME_SCRIPT, constants.ROUTE_MEETS_SCRIPT):
            filename = constants.HOME_SCRIPT_FILENAME if path == constants.ROUTE_HOME_SCRIPT else constants.MEETS_SCRIPT_FILENAME
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(filename))
        elif path == constants.ROUTE_SCRIPT:
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.SCRIPT_FILENAME))
        elif path in (constants.ROUTE_CARD_CAMERA_SCRIPT, constants.ROUTE_DESK_SHARED_SCRIPT):
            filename = (
                constants.CARD_CAMERA_SCRIPT_FILENAME if path == constants.ROUTE_CARD_CAMERA_SCRIPT
                else constants.DESK_SHARED_SCRIPT_FILENAME
            )
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(filename))
        elif path == constants.ROUTE_CARD_SCANNER_SCRIPT:
            self._send_bytes(
                HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.CARD_SCANNER_SCRIPT_FILENAME)
            )
        elif path.startswith(constants.ROUTE_VENDOR_PREFIX):
            self._send_vendor_file(path)
        elif path == constants.ROUTE_STATE:
            state = database.get_state()
            state[constants.KEY_DEMO] = self.in_demo
            self._send_json(HTTPStatus.OK, state)
        elif path == constants.ROUTE_DEMO:
            current = stored_demo_size(self.server.get_demo_database())
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_demo_page(current))
        elif path == constants.ROUTE_MEETS:
            self._send_meet_overview()
        elif path == constants.ROUTE_SUITE_CURRENT:
            self._send_json(HTTPStatus.OK, self._suite_current())
        elif path == constants.ROUTE_SUITE_MEETS:
            self._send_json(HTTPStatus.OK, {constants.KEY_MEETS: database.list_meets()})
        elif path == constants.ROUTE_MEET_ZIP:
            meet = database.get_state()[constants.KEY_MEET]
            self._send_meet_zip(database, None if meet is None else meet[constants.KEY_ID])
        elif (match := _MEET_ZIP_PATTERN.match(path)) is not None:
            self._send_meet_zip(self.server.database, int(match.group(1)))  # Meet overview: real meets
        elif path == constants.ROUTE_TEAMS:
            self._send_team_view()
        elif path in (constants.ROUTE_PRINT_SESSION, constants.ROUTE_TEAM_DISPLAY):
            self._send_session_page(url.query, team_display=path == constants.ROUTE_TEAM_DISPLAY)
        elif path == constants.ROUTE_PRINT_MEET:
            self._send_meet_summary()
        elif path in (constants.ROUTE_PRINT_STYLESHEET, constants.ROUTE_DESK_STYLESHEET):
            filename = (
                constants.PRINT_STYLESHEET_FILENAME if path == constants.ROUTE_PRINT_STYLESHEET
                else constants.DESK_STYLESHEET_FILENAME
            )
            self._send_bytes(HTTPStatus.OK, constants.CSS_CONTENT_TYPE, (_WEB_DIRECTORY / filename).read_bytes())
        elif path == constants.ROUTE_OFFICIALS:
            self._send_json(HTTPStatus.OK, {constants.KEY_OFFICIALS: database.list_officials(date.today())})
        elif path in (constants.ROUTE_ROSTER, constants.ROUTE_ROSTER_DOWNLOAD):
            self._send_roster(url.query, download=path == constants.ROUTE_ROSTER_DOWNLOAD)
        elif _is_coaches_path(path) and (coaches := _coaches_module()) is not None:
            try:
                if not coaches.handle_get(self, path, url.query):
                    self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")
            except SigninError as error:
                self._send_json_error(HTTPStatus.BAD_REQUEST, str(error))
        else:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")

    def _send_vendor_file(self, path: str) -> None:
        """Serve one bundled OCR engine file (cacheable; never templated)."""
        file_path = resolve_vendor_file(path)
        if file_path is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = constants.VENDOR_CONTENT_TYPE_BY_SUFFIX.get(file_path.suffix, constants.BINARY_CONTENT_TYPE)
        self._send_bytes(HTTPStatus.OK, content_type, file_path.read_bytes(), cache=constants.VENDOR_CACHE)

    def _send_roster(self, query: str, download: bool) -> None:
        """Send the roster for ``?session_id=`` or, by default, the active session."""
        database = self.database
        requested = parse_qs(query).get(constants.KEY_SESSION_ID, [])
        if requested and requested[0].isdigit():
            session_id: int | None = int(requested[0])
        else:
            session_id = database.get_state()[constants.KEY_ACTIVE_SESSION_ID]
        source = None if session_id is None else database.roster_source(session_id)
        if source is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No session to export")
            return
        roster = build_roster(source)
        body = json.dumps(roster, indent=2).encode("utf-8")
        filename = roster_download_filename(roster) if download else None
        self._send_bytes(HTTPStatus.OK, constants.JSON_CONTENT_TYPE, body, download_filename=filename)

    # --- POST ---------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Handle meet/session setup, card readings and sign-ins."""
        path = urlsplit(self.path).path
        payload = self._read_json_object()
        if payload is None:
            return
        try:
            if path == constants.ROUTE_MEETS:
                self._handle_create_meet(payload)
            elif path == constants.ROUTE_MEET_SAVE:
                self._handle_save_meet(payload)
            elif path == constants.ROUTE_SESSIONS:
                self._handle_add_session(payload)
            elif (match := _SESSION_DELETE_PATTERN.match(path)) is not None:
                deleted = self.database.delete_session(int(match.group(1)))
                LOGGER.info("Deleted a session and its %d sign-in(s)", deleted)
                self._send_json(HTTPStatus.OK, {constants.KEY_SIGNIN_COUNT: deleted})
            elif (match := _SESSION_PATTERN.match(path)) is not None:
                self._handle_update_session(int(match.group(1)), payload)
            elif path == constants.ROUTE_ACTIVE_SESSION:
                self._handle_active_session(payload)
            elif path == constants.ROUTE_SUITE_SELECT:
                self._handle_suite_select(payload)
            elif path == constants.ROUTE_CARD_READING:
                self._handle_card_reading(payload)
            elif path == constants.ROUTE_SIGNINS:
                self._handle_sign_in(payload)
            elif path == constants.ROUTE_DEMO_START:
                self._handle_demo_start(payload)
            elif path == constants.ROUTE_DEMO_EXIT:
                self._send_json(HTTPStatus.OK, {constants.KEY_OK: True}, cookie=self._demo_cookie(on=False))
            elif path == constants.ROUTE_DEMO_OPEN:
                self._handle_demo_open()
            elif path == constants.ROUTE_DEMO_RESET:
                self._handle_demo_reset()
            elif (match := _MEET_ACTION_PATTERN.match(path)) is not None:
                self._handle_meet_action(int(match.group(1)), match.group(2), payload)
            elif path == constants.ROUTE_DIAGNOSTICS:
                self._handle_diagnostics(payload)
            elif path == constants.ROUTE_TEAMS_BUILD:
                self._handle_build_teams(payload)
            elif path == constants.ROUTE_TEAMS_SETTINGS:
                self._handle_team_settings(payload)
            elif (match := _SIGNIN_TEAM_PATTERN.match(path)) is not None:
                self._handle_signin_team(int(match.group(1)), payload)
            elif (match := _SIGNIN_SWAP_PATTERN.match(path)) is not None:
                other = payload.get(constants.KEY_WITH_SIGNIN_ID)
                if not isinstance(other, int):
                    raise SigninError("Pick the official to swap with")
                self.database.swap_signin_places(self._active_session()[constants.KEY_ID], int(match.group(1)), other)
                self._send_json(HTTPStatus.OK, self._team_view())
            elif (match := _SIGNIN_EDIT_PATTERN.match(path)) is not None:
                self._handle_signin_edit(int(match.group(1)), payload)
            elif (match := _SIGNIN_ACTION_PATTERN.match(path)) is not None:
                self._handle_signin_action(int(match.group(1)), match.group(2))
            elif _is_coaches_path(path) and (coaches := _coaches_module()) is not None:
                if not coaches.handle_post(self, path, payload):
                    self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")
            else:
                self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")
        except SigninError as error:
            self._send_json_error(HTTPStatus.BAD_REQUEST, str(error))

    def _handle_create_meet(self, payload: dict[str, Any]) -> None:
        """Create a meet and make it active."""
        name = str(payload.get(constants.KEY_NAME, "")).strip()[: constants.NAME_MAX_LENGTH]
        start_date = str(payload.get(constants.KEY_START_DATE, ""))
        if not name or not _DATE_PATTERN.match(start_date):
            raise SigninError("A meet needs a name and a start date")
        meet_id = self.database.create_meet(name, start_date)
        self._send_json(HTTPStatus.OK, {constants.KEY_ID: meet_id})

    def _handle_save_meet(self, payload: dict[str, Any]) -> None:
        """Create or change a meet and all its sessions at once (Meet setup's Save)."""
        meet_id = payload.get(constants.KEY_ID)
        if meet_id is not None and not isinstance(meet_id, int):
            raise SigninError("Unknown meet")
        name = str(payload.get(constants.KEY_NAME, "")).strip()[: constants.NAME_MAX_LENGTH]
        start_date = str(payload.get(constants.KEY_START_DATE, ""))
        if not name or not _DATE_PATTERN.match(start_date):
            raise SigninError("A meet needs a name and a start date")
        rows = payload.get(constants.KEY_SESSIONS)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise SigninError("Expected a list of sessions")
        if meet_id is None and not rows:
            raise SigninError("Add at least one session")
        if len(rows) > constants.MAX_SESSIONS_PER_MEET:
            raise SigninError(f"At most {constants.MAX_SESSIONS_PER_MEET} sessions")
        sessions = []
        for number, row in enumerate(rows, start=1):
            session_id = row.get(constants.KEY_ID)
            if session_id is not None and not isinstance(session_id, int):
                raise SigninError("Unknown session")
            try:
                fields = SessionFields(*self._session_fields(row))
            except SigninError as error:
                raise SigninError(f"Session {number}: {error}") from error
            sessions.append((session_id, fields))
        saved_id = self.database.save_meet(meet_id, name, start_date, sessions, date.today())
        self._send_json(HTTPStatus.OK, {constants.KEY_ID: saved_id})

    @staticmethod
    def _session_fields(payload: dict[str, Any]) -> tuple[str, str, str | None, str | None, str | None, int | None]:
        """Validate the session form: name, date, start time, type, officials meeting time and length.

        Raises:
            SigninError: With a message for the admin when something is wrong.
        """
        name = str(payload.get(constants.KEY_NAME, "")).strip()[: constants.SESSION_NAME_MAX_LENGTH]
        session_date = str(payload.get(constants.KEY_DATE, ""))
        if not name or not _DATE_PATTERN.match(session_date):
            raise SigninError("A session needs a name and a date")
        start_time = payload.get(constants.KEY_START_TIME) or None
        meeting_time = payload.get(constants.KEY_OFFICIALS_MEETING_TIME) or None
        for label, value in (("Start time", start_time), ("Officials meeting time", meeting_time)):
            if value is not None and not _TIME_PATTERN.match(str(value)):
                raise SigninError(f"{label} must look like 13:00")
        session_type = str(payload.get(constants.KEY_SESSION_TYPE) or "").strip()[: constants.SESSION_TYPE_MAX_LENGTH]
        estimated = payload.get(constants.KEY_ESTIMATED_MINUTES)
        if estimated is not None and (
            not isinstance(estimated, int) or not 0 < estimated <= constants.MAX_SESSION_MINUTES
        ):
            raise SigninError("Estimated length must be between 30 minutes and 12 hours")
        return name, session_date, start_time, session_type or None, meeting_time, estimated

    def _handle_add_session(self, payload: dict[str, Any]) -> None:
        """Add a session to the active meet."""
        session_id = self.database.add_session(*self._session_fields(payload))
        self._send_json(HTTPStatus.OK, {constants.KEY_ID: session_id})

    def _handle_update_session(self, session_id: int, payload: dict[str, Any]) -> None:
        """Change a session of the active meet."""
        self.database.update_session(session_id, *self._session_fields(payload))
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

    def _handle_active_session(self, payload: dict[str, Any]) -> None:
        """Choose the session being signed in."""
        session_id = payload.get(constants.KEY_SESSION_ID)
        if not isinstance(session_id, int):
            raise SigninError("Pick a session")
        self.database.set_active_session(session_id)
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

    def _suite_current(self) -> dict[str, Any]:
        """The suite's current meet and session (what every app shows), with a version stamp.

        ``version`` changes whenever the meet, the current session or the meet's sessions
        change, so an app polling this (DQ Transcribe) can tell at a glance.
        """
        state = self.database.get_state()
        current = {
            constants.KEY_SUITE: constants.SUITE_TITLE,
            constants.KEY_DEMO: self.in_demo,
            constants.KEY_MEET: state[constants.KEY_MEET],
            constants.KEY_SESSIONS: [
                {key: value for key, value in session.items() if key != constants.KEY_SIGNIN_COUNT}
                for session in state[constants.KEY_SESSIONS]
            ],
            constants.KEY_ACTIVE_SESSION_ID: state[constants.KEY_ACTIVE_SESSION_ID],
        }
        fingerprint = json.dumps(current, sort_keys=True).encode("utf-8")
        current[constants.KEY_VERSION] = hashlib.sha1(fingerprint).hexdigest()[:12]  # noqa: S324 (a change stamp, not security)
        return current

    def _handle_suite_select(self, payload: dict[str, Any]) -> None:
        """Make a meet and/or session current for every app (from any app's top bar)."""
        meet_id = payload.get(constants.KEY_MEET_ID)
        session_id = payload.get(constants.KEY_SESSION_ID)
        if meet_id is not None:
            if not isinstance(meet_id, int):
                raise SigninError("Unknown meet")
            self.database.open_meet(meet_id, date.today())
        if session_id is not None:
            if not isinstance(session_id, int):
                raise SigninError("Unknown session")
            self.database.set_active_session(session_id)
        self._send_json(HTTPStatus.OK, self._suite_current())

    def _active_session_date(self) -> date:
        """Date of the active session (today if none), for checking card dates."""
        state = self.database.get_state()
        session_id = state[constants.KEY_ACTIVE_SESSION_ID]
        session = None if session_id is None else self.database.get_session(session_id)
        return date.today() if session is None else date.fromisoformat(session[constants.KEY_DATE])

    def _handle_card_reading(self, payload: dict[str, Any]) -> None:
        """Parse OCR text from the camera; report what was read and who it matches."""
        texts = payload.get(constants.KEY_TEXTS)
        if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
            raise SigninError("Expected a list of OCR texts")
        texts = [text[: constants.OCR_TEXT_MAX_LENGTH] for text in texts[-constants.OCR_TEXTS_PER_REQUEST_LIMIT:]]
        reading = read_card(texts)
        result = check_card(reading, self._active_session_date())
        official_id = self.database.find_official_for_card(reading)
        match = None if official_id is None else self.database.get_official(official_id, date.today())
        card = reading.to_dict()
        # A date that looks expired but was read only once may be an OCR slip:
        # report "not complete" so the camera keeps reading to confirm it.
        if result.unconfirmed:
            card[constants.CARD_FIELD_COMPLETE] = False
        # A new official's name read only once may be garbled ("PAI" for "PAT"):
        # keep reading until two passes agree. A known official keeps their stored name.
        if match is None and reading.name is not None and reading.name_votes < constants.CARD_NAME_CONFIRMATIONS:
            card[constants.CARD_FIELD_COMPLETE] = False
        self._send_json(
            HTTPStatus.OK,
            {
                constants.KEY_CARD: card,
                constants.KEY_VALIDATED: result.validated,
                constants.KEY_PROBLEMS: result.problems,
                constants.KEY_MATCH: match,
            },
        )

    def _handle_sign_in(self, payload: dict[str, Any]) -> None:
        """Sign an official in to the active session and any later sessions picked."""
        database = self.database
        state = database.get_state()
        active_session_id = state[constants.KEY_ACTIVE_SESSION_ID]
        if active_session_id is None or state[constants.KEY_MEET] is None:
            raise SigninError("Choose a session first")
        meet_id = state[constants.KEY_MEET][constants.KEY_ID]
        sessions_by_id = {session[constants.KEY_ID]: session for session in state[constants.KEY_SESSIONS]}
        requested = payload.get(constants.KEY_SESSION_IDS) or [active_session_id]
        if not all(isinstance(session_id, int) and session_id in sessions_by_id for session_id in requested):
            raise SigninError("Unknown session")
        session_ids = list(dict.fromkeys([active_session_id, *requested]))

        years = payload.get(constants.KEY_YEARS_CERTIFIED)
        if years is not None and (not isinstance(years, int) or not 0 <= years <= constants.MAX_YEARS_CERTIFIED):
            raise SigninError("Years certified must be a whole number")
        official_id = payload.get(constants.KEY_OFFICIAL_ID)
        if official_id is not None and not isinstance(official_id, int):
            raise SigninError("Unknown official")
        roles = payload.get(constants.KEY_ROLES)
        if not isinstance(roles, list):
            raise SigninError("Pick at least one role")
        reading = card_reading_from_payload(payload.get(constants.KEY_CARD))
        if official_id is None and reading is not None:
            official_id = database.find_official_for_card(reading)
        name = payload.get(constants.KEY_NAME)
        official_id = database.save_official(
            official_id,
            name if isinstance(name, str) else None,
            years,
            reading,
            meet_id,
            date.today(),
        )

        chosen_club = lsc_and_club_from_payload(payload)
        if chosen_club is not None:
            database.set_official_club(official_id, *chosen_club)

        validations: dict[int, Validation] = {}
        for session_id in session_ids:
            session_date = date.fromisoformat(sessions_by_id[session_id][constants.KEY_DATE])
            if reading is not None:
                result = check_card(reading, session_date)
                validations[session_id] = Validation(result.validated, constants.VALIDATION_CAMERA, result.problems)
            else:
                stored = database.stored_card_validation(official_id, meet_id, session_date)
                validations[session_id] = stored if stored is not None else not_checked_validation()
        signin_ids = database.sign_in(
            official_id, session_ids, [str(role) for role in roles], bool(payload.get(constants.KEY_TRAINEE)), validations
        )
        LOGGER.info("Signed in official %d to %d session(s)", official_id, len(signin_ids))
        self._send_json(
            HTTPStatus.OK,
            {
                constants.KEY_OFFICIAL_ID: official_id,
                constants.KEY_SIGNINS: signin_ids,
                constants.KEY_VALIDATED: validations[active_session_id].validated,
                constants.KEY_PROBLEMS: validations[active_session_id].problems,
            },
        )

    def _handle_signin_edit(self, signin_id: int, payload: dict[str, Any]) -> None:
        """Fix a sign-in: name (renames the official, merging a duplicate), years, roles, trainee."""
        years = payload.get(constants.KEY_YEARS_CERTIFIED)
        if years is not None and (not isinstance(years, int) or not 0 <= years <= constants.MAX_YEARS_CERTIFIED):
            raise SigninError("Years certified must be a whole number")
        roles = payload.get(constants.KEY_ROLES)
        name = payload.get(constants.KEY_NAME)
        if not isinstance(roles, list) or not isinstance(name, str):
            raise SigninError("Name and roles are needed")
        merged = self.database.edit_signin(
            signin_id, name, years, [str(role) for role in roles], bool(payload.get(constants.KEY_TRAINEE)), date.today()
        )
        chosen_club = lsc_and_club_from_payload(payload)
        official_id = self.database.official_for_signin(signin_id)
        if chosen_club is not None and official_id is not None:
            self.database.set_official_club(official_id, *chosen_club)
        LOGGER.info("Edited sign-in %d (%d duplicate record(s) merged)", signin_id, merged)
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True, constants.KEY_MERGED: merged})

    def _handle_signin_action(self, signin_id: int, action: str) -> None:
        """Validate a sign-in by eye, or remove it."""
        database = self.database
        if action == constants.SIGNIN_VALIDATE_SUFFIX:
            found = database.validate_signin_visually(signin_id)
        else:
            found = database.remove_signin(signin_id)
        if not found:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Sign-in not found")
            return
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

    # --- Demo mode ------------------------------------------------------------------

    @staticmethod
    def _demo_cookie(on: bool) -> str:
        """Set-Cookie value that switches this browser into (or out of) demo mode."""
        if on:
            return f"{constants.DEMO_COOKIE_NAME}={constants.DEMO_COOKIE_ON}; Path=/; SameSite=Strict"
        return f"{constants.DEMO_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Strict"

    def _send_meet_zip(self, database: Database, meet_id: int | None) -> None:
        """Download a meet as a zip file (see ``export.py``; no member IDs inside)."""
        if meet_id is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No meet yet")
            return
        try:
            filename, body = build_meet_zip(database, meet_id)
        except LookupError:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        self._send_bytes(HTTPStatus.OK, constants.ZIP_CONTENT_TYPE, body, download_filename=filename)

    def _send_meet_overview(self) -> None:
        """Every real meet plus the demo meet's status, for the Meet overview.

        Real meets always come from the real database, even for a browser in demo mode.
        """
        real = self.server.database
        demo_ready = self.server.get_demo_database().get_state()[constants.KEY_MEET] is not None
        self._send_json(HTTPStatus.OK, {
            constants.KEY_MEETS: real.list_meets(),
            constants.KEY_ACTIVE_MEET_ID: real.get_setting(constants.SETTING_ACTIVE_MEET_ID),
            constants.KEY_DEMO: self.in_demo,
            constants.KEY_DEMO_READY: demo_ready,
        })

    def _handle_meet_action(self, meet_id: int, action: str, payload: dict[str, Any]) -> None:
        """Open, archive / unarchive, or delete one of the real meets (Meet overview).

        These always act on the real meets, even from a browser in demo mode; opening a
        meet also leaves demo mode.
        """
        real = self.server.database
        if action == constants.MEET_OPEN_SUFFIX:
            real.open_meet(meet_id, date.today())
            self._send_json(HTTPStatus.OK, {constants.KEY_OK: True}, cookie=self._demo_cookie(on=False))
        elif action == constants.MEET_ARCHIVE_SUFFIX:
            real.set_meet_archived(meet_id, bool(payload.get(constants.KEY_ARCHIVED, True)))
            self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})
        else:
            deleted = real.delete_meet(meet_id)
            LOGGER.info("Deleted an archived meet and its %d sign-in(s)", deleted)
            self._send_json(HTTPStatus.OK, {constants.KEY_SIGNIN_COUNT: deleted})

    def _rebuild_demo(self, size: DemoSize) -> None:
        """Build a fresh demo database (replacing the old one)."""
        with self.server.demo_lock:
            self.server.demo_database = build_demo(self.server.demo_database_path, size, date.today())

    def _handle_demo_open(self) -> None:
        """Switch this browser to the demo meet, building one with the defaults if there is none."""
        if self.server.get_demo_database().get_state()[constants.KEY_MEET] is None:
            self._rebuild_demo(default_demo_size())
            LOGGER.info("Built the demo meet")
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True}, cookie=self._demo_cookie(on=True))

    def _handle_demo_reset(self) -> None:
        """Rebuild the demo meet at the same size, erasing every change made in it."""
        self._rebuild_demo(stored_demo_size(self.server.get_demo_database()))
        LOGGER.info("Reset the demo meet")
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True}, cookie=self._demo_cookie(on=True))

    def _handle_demo_start(self, payload: dict[str, Any]) -> None:
        """Build a fresh demo meet of the size chosen on the demo page and switch this browser to it."""
        try:
            size = DemoSize.from_payload(payload)
        except ValueError as error:
            raise SigninError(str(error)) from error
        self._rebuild_demo(size)
        LOGGER.info("Started a demo meet")
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True}, cookie=self._demo_cookie(on=True))

    # --- Printable pages ------------------------------------------------------------

    def _session_from_query(self, query: str) -> dict[str, Any] | None:
        """The session named by ``?session_id=`` (of the active meet), or the active session."""
        state = self.database.get_state()
        requested = parse_qs(query).get(constants.KEY_SESSION_ID, [])
        session_id = int(requested[0]) if requested and requested[0].isdigit() else state[constants.KEY_ACTIVE_SESSION_ID]
        if session_id is None:
            return None
        session = self.database.get_session(session_id)
        if session is None or state[constants.KEY_MEET] is None or session["meet_id"] != state[constants.KEY_MEET][constants.KEY_ID]:
            return None
        return session

    def _send_session_page(self, query: str, team_display: bool) -> None:
        """Session summary, or the team display, for one session."""
        session = self._session_from_query(query)
        if session is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such session in the active meet")
            return
        meet = self.database.get_state()[constants.KEY_MEET]
        signins = self.database.list_signins(session[constants.KEY_ID])
        if team_display:
            body = render_team_display(meet, session, build_team_view(signins, session), len(signins))
        else:
            body = render_session_summary(meet, session, signins)
        self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, body)

    def _send_meet_summary(self) -> None:
        """Every session of the active meet on as few pages as possible."""
        database = self.database
        state = database.get_state()
        if state[constants.KEY_MEET] is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No meet yet")
            return
        sessions = [
            (database.get_session(session[constants.KEY_ID]), database.list_signins(session[constants.KEY_ID]))
            for session in state[constants.KEY_SESSIONS]
        ]
        self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_meet_summary(state[constants.KEY_MEET], sessions))

    # --- Camera diagnostics -------------------------------------------------------

    def _handle_diagnostics(self, payload: dict[str, Any]) -> None:
        """Save one diagnostics record (and its frame, if any) for a scan.

        Files go to ``~/.officials_signin/diagnostics/<scan id>/``: ``records.jsonl``
        (one JSON record per line) and ``frame_NNN.jpg``. Only used when the admin
        ticks "Save frames for troubleshooting".
        """
        scan_id = str(payload.get(constants.KEY_SCAN_ID, ""))
        record = payload.get(constants.KEY_RECORD)
        if not _SCAN_ID_PATTERN.match(scan_id) or not isinstance(record, dict):
            raise SigninError("Bad diagnostics record")
        folder = self.server.diagnostics_directory / scan_id
        folder.mkdir(parents=True, exist_ok=True)
        image = payload.get(constants.KEY_IMAGE)
        if isinstance(image, str) and image.startswith(constants.DATA_URL_JPEG_PREFIX):
            frame_count = len(list(folder.glob("frame_*.jpg")))
            if frame_count < constants.DIAGNOSTICS_MAX_FRAMES_PER_SCAN:
                try:
                    image_bytes = base64.b64decode(image[len(constants.DATA_URL_JPEG_PREFIX):], validate=True)
                except (binascii.Error, ValueError):
                    raise SigninError("Bad diagnostics image") from None
                if len(image_bytes) <= constants.DIAGNOSTICS_MAX_IMAGE_BYTES:
                    filename = constants.DIAGNOSTICS_FRAME_FILENAME_FORMAT.format(number=frame_count + 1)
                    (folder / filename).write_bytes(image_bytes)
                    record[constants.KEY_IMAGE] = filename
        with (folder / constants.DIAGNOSTICS_RECORD_FILENAME).open("a", encoding="utf-8") as records:
            records.write(json.dumps(record) + "\n")
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

    # --- Teams ----------------------------------------------------------------

    def _active_session(self) -> dict[str, Any]:
        """The active session row.

        Raises:
            SigninError: If no session is chosen.
        """
        session_id = self.database.get_state()[constants.KEY_ACTIVE_SESSION_ID]
        session = None if session_id is None else self.database.get_session(session_id)
        if session is None:
            raise SigninError("Choose a session first")
        return session

    def _team_view(self) -> dict[str, Any]:
        """The Teams screen for the active session."""
        session = self._active_session()
        return build_team_view(self.database.list_signins(session[constants.KEY_ID]), session)

    def _send_team_view(self) -> None:
        """GET /api/teams."""
        try:
            self._send_json(HTTPStatus.OK, self._team_view())
        except SigninError as error:
            self._send_json_error(HTTPStatus.NOT_FOUND, str(error))

    @staticmethod
    def _lanes_from(payload: dict[str, Any]) -> int | None:
        """Validated lane count from a request, or None if not given."""
        lanes = payload.get(constants.KEY_LANES)
        if lanes is None:
            return None
        if not isinstance(lanes, int) or not constants.MIN_LANES <= lanes <= constants.MAX_LANES:
            raise SigninError(f"Lanes must be {constants.MIN_LANES} to {constants.MAX_LANES}")
        return lanes

    def _handle_team_settings(self, payload: dict[str, Any]) -> None:
        """Change lanes, rotation, "flip jurisdiction" or "15 m on every team", keeping the teams."""
        database = self.database
        session = self._active_session()
        session_id = session[constants.KEY_ID]
        fifteen = payload.get(constants.KEY_FIFTEEN_METER_ON_TEAMS)
        rotation_mode = payload.get(constants.KEY_ROTATION_MODE)
        if rotation_mode is not None and rotation_mode not in constants.ROTATION_MODES:
            raise SigninError("Unknown rotation")
        flipped = payload.get(constants.KEY_JURISDICTION_FLIPPED)
        database.save_team_settings(
            session_id,
            lanes=self._lanes_from(payload),
            fifteen_meter_on_teams=None if fifteen is None else bool(fifteen),
            rotation_mode=rotation_mode,
            jurisdiction_flipped=None if flipped is None else bool(flipped),
        )
        if fifteen is not None:
            for signin_id, assignment in fifteen_meter_changes(database.list_signins(session_id), bool(fifteen)).items():
                database.update_signin_team(signin_id, {constants.KEY_ASSIGNMENT: assignment})
        self._send_json(HTTPStatus.OK, self._team_view())

    def _handle_build_teams(self, payload: dict[str, Any]) -> None:
        """Build (or rebuild) the teams automatically, replacing any hand changes."""
        database = self.database
        session = self._active_session()
        session_id = session[constants.KEY_ID]
        team_count = payload.get(constants.KEY_TEAM_COUNT)
        if team_count is not None and (not isinstance(team_count, int) or team_count < 0):
            raise SigninError("Team count must be a whole number")
        fifteen = payload.get(constants.KEY_FIFTEEN_METER_ON_TEAMS)
        database.save_team_settings(
            session_id,
            lanes=self._lanes_from(payload),
            team_count=team_count,
            fifteen_meter_on_teams=None if fifteen is None else bool(fifteen),
        )
        session = database.get_session(session_id)
        signins = database.list_signins(session_id)
        judges = judges_from_signins(signins)
        count = chosen_team_count(len(judges), session[constants.KEY_TEAM_COUNT])
        # Judges with the same years are mixed randomly (a new mix on every rebuild).
        placements = plan_teams(judges, count, bool(session[constants.KEY_FIFTEEN_METER_ON_TEAMS]), random.Random())
        # Trainees in sign-in order (the list is newest first).
        trainee_ids = [signin[constants.KEY_ID] for signin in reversed(signins) if is_team_trainee(signin)]
        mentors = assign_mentors(trainee_ids, placements, judges)
        team_of = {placement.signin_id: placement.team for placement in placements}
        database.save_team_plan(
            session_id,
            [(placement.signin_id, placement.team, placement.assignment) for placement in placements],
            mentors,
            {trainee: team_of.get(mentor) for trainee, mentor in mentors.items()},
        )
        LOGGER.info("Built %d team(s) from %d judge(s)", count, len(judges))
        self._send_json(HTTPStatus.OK, self._team_view())

    def _handle_signin_team(self, signin_id: int, payload: dict[str, Any]) -> None:
        """Move one official (team or extra job), set a Team Lead, or change a mentor."""
        database = self.database
        session = self._active_session()
        signins = {signin[constants.KEY_ID]: signin for signin in database.list_signins(session[constants.KEY_ID])}
        if signin_id not in signins:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Sign-in not found")
            return
        changes: dict[str, Any] = {}
        if constants.KEY_TEAM in payload:
            team = payload[constants.KEY_TEAM]
            if team is not None and not (isinstance(team, str) and _TEAM_NAME_PATTERN.match(team)):
                raise SigninError("Unknown team")
            changes[constants.KEY_TEAM] = team
        if constants.KEY_ASSIGNMENT in payload:
            assignment = payload[constants.KEY_ASSIGNMENT]
            if assignment is not None and assignment not in constants.EXTRA_ASSIGNMENTS:
                raise SigninError("Unknown assignment")
            changes[constants.KEY_ASSIGNMENT] = assignment
        if constants.KEY_MENTOR_SIGNIN_ID in payload:
            mentor_id = payload[constants.KEY_MENTOR_SIGNIN_ID]
            if mentor_id is not None and (mentor_id not in signins or signins[mentor_id][constants.KEY_TRAINEE]):
                raise SigninError("A mentor must be a certified official signed in to this session")
            changes[constants.KEY_MENTOR_SIGNIN_ID] = mentor_id
            # A trainee goes wherever the mentor is.
            changes[constants.KEY_TEAM] = None if mentor_id is None else signins[mentor_id][constants.KEY_TEAM]
        new_team = changes.get(constants.KEY_TEAM, signins[signin_id][constants.KEY_TEAM])
        if constants.KEY_TEAM_LEAD in payload:
            changes[constants.KEY_TEAM_LEAD] = bool(payload[constants.KEY_TEAM_LEAD]) and new_team is not None
        elif new_team != signins[signin_id][constants.KEY_TEAM]:
            changes[constants.KEY_TEAM_LEAD] = False  # a lead who changes team is no longer that team's lead
        if changes.get(constants.KEY_TEAM_LEAD):
            # One Team Lead per team.
            for other in signins.values():
                if other[constants.KEY_ID] != signin_id and other[constants.KEY_TEAM] == new_team and other[constants.KEY_TEAM_LEAD]:
                    database.update_signin_team(other[constants.KEY_ID], {constants.KEY_TEAM_LEAD: False})
        database.update_signin_team(signin_id, changes)
        # Trainees follow their mentor to a new team.
        if constants.KEY_TEAM in changes and not signins[signin_id][constants.KEY_TRAINEE]:
            for other in signins.values():
                if other[constants.KEY_MENTOR_SIGNIN_ID] == signin_id:
                    database.update_signin_team(other[constants.KEY_ID], {constants.KEY_TEAM: new_team})
        self._send_json(HTTPStatus.OK, self._team_view())

    # --- Helpers ------------------------------------------------------------

    def _read_json_object(self) -> dict[str, Any] | None:
        """Read a JSON object request body, or send an error and return None."""
        try:
            length = int(self.headers.get(constants.CONTENT_LENGTH_HEADER, "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= constants.MAX_REQUEST_BODY_BYTES:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large")
            return None
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Expected a JSON object")
            return None
        return payload

    def _send_bytes(
        self,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
        download_filename: str | None = None,
        cache: str = constants.NO_CACHE,
        cookie: str | None = None,
    ) -> None:
        """Send a complete response (optionally setting a cookie)."""
        self.send_response(status)
        self.send_header(constants.CONTENT_TYPE_HEADER, content_type)
        self.send_header(constants.CONTENT_LENGTH_HEADER, str(len(body)))
        self.send_header(constants.CACHE_CONTROL_HEADER, cache)
        if cookie is not None:
            self.send_header(constants.SET_COOKIE_HEADER, cookie)
        self._send_cors_headers()
        if download_filename is not None:
            self.send_header(constants.CONTENT_DISPOSITION_HEADER, f'attachment; filename="{download_filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any], cookie: str | None = None) -> None:
        """Send a JSON response (optionally setting a cookie)."""
        self._send_bytes(status, constants.JSON_CONTENT_TYPE, json.dumps(payload).encode("utf-8"), cookie=cookie)

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        """Send ``{"error": message}`` with an error status."""
        self._send_json(status, {constants.KEY_ERROR: message})
