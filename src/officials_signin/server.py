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
import json
import logging
import re
import string
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from officials_signin import constants
from officials_signin.card_reader import CardReading, check_card, read_card
from officials_signin.database import Database, SigninError, Validation, not_checked_validation
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
            "diagnostics": constants.ROUTE_DIAGNOSTICS,
            "teams": constants.ROUTE_TEAMS,
            "teamsBuild": constants.ROUTE_TEAMS_BUILD,
            "teamsSettings": constants.ROUTE_TEAMS_SETTINGS,
            "teamSuffix": constants.SIGNIN_TEAM_SUFFIX,
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
            "signinCount": constants.KEY_SIGNIN_COUNT,
            "merged": constants.KEY_MERGED,
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
        "assignmentFifteenMeter": constants.ASSIGNMENT_FIFTEEN_METER,
        "assignmentAcj": constants.ASSIGNMENT_ACJ,
        "sessionTypes": list(constants.SESSION_TYPES),
        "sessionTypeOtherLabel": constants.SESSION_TYPE_OTHER_LABEL,
        "sessionLetterTypes": list(constants.SESSION_LETTER_TYPES),
        "sessionLetterPrefix": constants.SESSION_LETTER_PREFIX,
        "meetingMinutesBeforeStart": constants.OFFICIALS_MEETING_MINUTES_BEFORE_START,
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


def render_page() -> bytes:
    """Render the sign-in page."""
    return _render(
        constants.PAGE_FILENAME,
        {
            "app_title": constants.APP_TITLE,
            "script_route": constants.ROUTE_SCRIPT,
            "card_scanner_route": constants.ROUTE_CARD_SCANNER_SCRIPT,
            "engine_script_route": constants.OCR_ENGINE_PATH + constants.OCR_ENGINE_SCRIPT_FILENAME,
        },
    )


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


def card_reading_from_payload(payload: Any) -> CardReading | None:
    """Rebuild a card reading sent back by the page (only known fields are kept)."""
    if not isinstance(payload, dict):
        return None
    return CardReading(**{name: payload.get(name) for name in CardReading.__dataclass_fields__ if name in payload})


class SigninServer(ThreadingHTTPServer):
    """HTTP server that holds the database.

    Attributes:
        database: Officials, meets, sessions and sign-ins.
        diagnostics_directory: Where camera diagnostics are saved (when switched on).
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        database: Database,
        diagnostics_directory: Path = constants.DIAGNOSTICS_DIRECTORY,
    ) -> None:
        """Create the server.

        Args:
            server_address: ``(host, port)`` to bind. Use port 0 to let the OS choose.
            database: Storage (already initialized).
            diagnostics_directory: Where camera diagnostics are saved.
        """
        self.database = database
        self.diagnostics_directory = diagnostics_directory
        super().__init__(server_address, RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    """Serves the page and the JSON API."""

    server: SigninServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (signature from the base class)
        """Log the request line only through ``logging`` (bodies, with personal data, are never logged)."""
        LOGGER.debug(format, *args)

    # --- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Serve the page, scripts, OCR engine files, state and the roster."""
        url = urlsplit(self.path)
        path = url.path
        database = self.server.database

        if path == constants.ROUTE_HOME:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_page())
        elif path == constants.ROUTE_SCRIPT:
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.SCRIPT_FILENAME))
        elif path == constants.ROUTE_CARD_SCANNER_SCRIPT:
            self._send_bytes(
                HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.CARD_SCANNER_SCRIPT_FILENAME)
            )
        elif path.startswith(constants.ROUTE_VENDOR_PREFIX):
            self._send_vendor_file(path)
        elif path == constants.ROUTE_STATE:
            self._send_json(HTTPStatus.OK, database.get_state())
        elif path == constants.ROUTE_TEAMS:
            self._send_team_view()
        elif path == constants.ROUTE_OFFICIALS:
            self._send_json(HTTPStatus.OK, {constants.KEY_OFFICIALS: database.list_officials(date.today())})
        elif path in (constants.ROUTE_ROSTER, constants.ROUTE_ROSTER_DOWNLOAD):
            self._send_roster(url.query, download=path == constants.ROUTE_ROSTER_DOWNLOAD)
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
        database = self.server.database
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
            elif path == constants.ROUTE_SESSIONS:
                self._handle_add_session(payload)
            elif (match := _SESSION_DELETE_PATTERN.match(path)) is not None:
                deleted = self.server.database.delete_session(int(match.group(1)))
                LOGGER.info("Deleted a session and its %d sign-in(s)", deleted)
                self._send_json(HTTPStatus.OK, {constants.KEY_SIGNIN_COUNT: deleted})
            elif (match := _SESSION_PATTERN.match(path)) is not None:
                self._handle_update_session(int(match.group(1)), payload)
            elif path == constants.ROUTE_ACTIVE_SESSION:
                self._handle_active_session(payload)
            elif path == constants.ROUTE_CARD_READING:
                self._handle_card_reading(payload)
            elif path == constants.ROUTE_SIGNINS:
                self._handle_sign_in(payload)
            elif path == constants.ROUTE_DIAGNOSTICS:
                self._handle_diagnostics(payload)
            elif path == constants.ROUTE_TEAMS_BUILD:
                self._handle_build_teams(payload)
            elif path == constants.ROUTE_TEAMS_SETTINGS:
                self._handle_team_settings(payload)
            elif (match := _SIGNIN_TEAM_PATTERN.match(path)) is not None:
                self._handle_signin_team(int(match.group(1)), payload)
            elif (match := _SIGNIN_EDIT_PATTERN.match(path)) is not None:
                self._handle_signin_edit(int(match.group(1)), payload)
            elif (match := _SIGNIN_ACTION_PATTERN.match(path)) is not None:
                self._handle_signin_action(int(match.group(1)), match.group(2))
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
        meet_id = self.server.database.create_meet(name, start_date)
        self._send_json(HTTPStatus.OK, {constants.KEY_ID: meet_id})

    @staticmethod
    def _session_fields(payload: dict[str, Any]) -> tuple[str, str, str | None, str | None, str | None]:
        """Validate the session form: name, date, start time, type and officials meeting time.

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
        return name, session_date, start_time, session_type or None, meeting_time

    def _handle_add_session(self, payload: dict[str, Any]) -> None:
        """Add a session to the active meet."""
        session_id = self.server.database.add_session(*self._session_fields(payload))
        self._send_json(HTTPStatus.OK, {constants.KEY_ID: session_id})

    def _handle_update_session(self, session_id: int, payload: dict[str, Any]) -> None:
        """Change a session of the active meet."""
        self.server.database.update_session(session_id, *self._session_fields(payload))
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

    def _handle_active_session(self, payload: dict[str, Any]) -> None:
        """Choose the session being signed in."""
        session_id = payload.get(constants.KEY_SESSION_ID)
        if not isinstance(session_id, int):
            raise SigninError("Pick a session")
        self.server.database.set_active_session(session_id)
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

    def _active_session_date(self) -> date:
        """Date of the active session (today if none), for checking card dates."""
        state = self.server.database.get_state()
        session_id = state[constants.KEY_ACTIVE_SESSION_ID]
        session = None if session_id is None else self.server.database.get_session(session_id)
        return date.today() if session is None else date.fromisoformat(session[constants.KEY_DATE])

    def _handle_card_reading(self, payload: dict[str, Any]) -> None:
        """Parse OCR text from the camera; report what was read and who it matches."""
        texts = payload.get(constants.KEY_TEXTS)
        if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
            raise SigninError("Expected a list of OCR texts")
        texts = [text[: constants.OCR_TEXT_MAX_LENGTH] for text in texts[-constants.OCR_TEXTS_PER_REQUEST_LIMIT:]]
        reading = read_card(texts)
        result = check_card(reading, self._active_session_date())
        official_id = self.server.database.find_official_for_card(reading)
        match = None if official_id is None else self.server.database.get_official(official_id, date.today())
        card = reading.to_dict()
        # A date that looks expired but was read only once may be an OCR slip:
        # report "not complete" so the camera keeps reading to confirm it.
        if result.unconfirmed:
            card[constants.CARD_FIELD_COMPLETE] = False
        # A new official's name read only once may be garbled ("WIARN" for "MARK"):
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
        database = self.server.database
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
        merged = self.server.database.edit_signin(
            signin_id, name, years, [str(role) for role in roles], bool(payload.get(constants.KEY_TRAINEE)), date.today()
        )
        LOGGER.info("Edited sign-in %d (%d duplicate record(s) merged)", signin_id, merged)
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True, constants.KEY_MERGED: merged})

    def _handle_signin_action(self, signin_id: int, action: str) -> None:
        """Validate a sign-in by eye, or remove it."""
        database = self.server.database
        if action == constants.SIGNIN_VALIDATE_SUFFIX:
            found = database.validate_signin_visually(signin_id)
        else:
            found = database.remove_signin(signin_id)
        if not found:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Sign-in not found")
            return
        self._send_json(HTTPStatus.OK, {constants.KEY_OK: True})

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
        session_id = self.server.database.get_state()[constants.KEY_ACTIVE_SESSION_ID]
        session = None if session_id is None else self.server.database.get_session(session_id)
        if session is None:
            raise SigninError("Choose a session first")
        return session

    def _team_view(self) -> dict[str, Any]:
        """The Teams screen for the active session."""
        session = self._active_session()
        return build_team_view(self.server.database.list_signins(session[constants.KEY_ID]), session)

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
        """Change lanes or "15 m on every team" while keeping the teams and hand changes."""
        database = self.server.database
        session = self._active_session()
        session_id = session[constants.KEY_ID]
        fifteen = payload.get(constants.KEY_FIFTEEN_METER_ON_TEAMS)
        database.save_team_settings(
            session_id,
            lanes=self._lanes_from(payload),
            fifteen_meter_on_teams=None if fifteen is None else bool(fifteen),
        )
        if fifteen is not None:
            for signin_id, assignment in fifteen_meter_changes(database.list_signins(session_id), bool(fifteen)).items():
                database.update_signin_team(signin_id, {constants.KEY_ASSIGNMENT: assignment})
        self._send_json(HTTPStatus.OK, self._team_view())

    def _handle_build_teams(self, payload: dict[str, Any]) -> None:
        """Build (or rebuild) the teams automatically, replacing any hand changes."""
        database = self.server.database
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
        placements = plan_teams(judges, count, bool(session[constants.KEY_FIFTEEN_METER_ON_TEAMS]))
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
        database = self.server.database
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
    ) -> None:
        """Send a complete response."""
        self.send_response(status)
        self.send_header(constants.CONTENT_TYPE_HEADER, content_type)
        self.send_header(constants.CONTENT_LENGTH_HEADER, str(len(body)))
        self.send_header(constants.CACHE_CONTROL_HEADER, cache)
        if download_filename is not None:
            self.send_header(constants.CONTENT_DISPOSITION_HEADER, f'attachment; filename="{download_filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        """Send a JSON response."""
        self._send_bytes(status, constants.JSON_CONTENT_TYPE, json.dumps(payload).encode("utf-8"))

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        """Send ``{"error": message}`` with an error status."""
        self._send_json(status, {constants.KEY_ERROR: message})
