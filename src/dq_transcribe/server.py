"""Local HTTP server for dq_transcribe.

Serves the web app and its JSON API, accepts audio clips recorded in the
browser (queueing them for transcription), and lets the transcript be edited.
It uses only the Python standard library, so it installs nothing and runs the
same on Termux (Android) and Windows.

The server binds to the loopback address only: it is reachable from this
device and nowhere else on the network.
"""

from __future__ import annotations

import html
import io
import json
import logging
import re
import string
import urllib.error
import urllib.request
import wave
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.dq_store import DqError, DqStore, load_dq_codes
from dq_transcribe.grouping import normalize_timestamp
from dq_transcribe.meet_archive import archive_filename, build_meet_archive
from dq_transcribe.auto_dq import AutoDqCreator
from dq_transcribe.coach_server import CoachPage
from dq_transcribe.event_summary import render_event_summary
from dq_transcribe.demo_data import DEMO_MEET_NAME
from dq_transcribe.officials_roster import RosterError, read_roster
from dq_transcribe.slip_page import club_sort_key, print_requests_toolbar, render_slips
from dq_transcribe.meet_files import MeetFileError, read_meet_file
from dq_transcribe.meet_files.meet_sheet import download_address, read_meet_sheet_file, today
from dq_transcribe.meet_files.store import MeetProgramStore
from dq_transcribe.transcript import format_transcript_text
from dq_transcribe.worker import TranscriptionWorker

LOGGER = logging.getLogger(__name__)

_WEB_DIRECTORY = Path(__file__).parent / constants.WEB_DIRECTORY_NAME

_CLIP_AUDIO_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_CLIPS)}/(\d+){re.escape(constants.CLIP_AUDIO_SUFFIX)}$"
)
_CLIP_REPROCESS_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_CLIPS)}/(\d+){re.escape(constants.CLIP_REPROCESS_SUFFIX)}$"
)
_CLIP_TRASH_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_CLIPS)}/(\d+){re.escape(constants.CLIP_TRASH_SUFFIX)}$"
)
_CLIP_RESTORE_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_CLIPS)}/(\d+){re.escape(constants.CLIP_RESTORE_SUFFIX)}$"
)
_CLIP_DELETE_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_CLIPS)}/(\d+){re.escape(constants.CLIP_DELETE_SUFFIX)}$"
)
_UTTERANCE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_UTTERANCES)}/(\d+)$")
_MEET_ACTIVATE_PATTERN = re.compile(
    rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.MEET_ACTIVATE_SUFFIX)}$"
)
_MEET_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+)$")
_MEET_FILE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.ROUTE_MEET_FILE_SUFFIX)}$")
_MEET_PROGRAM_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.ROUTE_MEET_PROGRAM_SUFFIX)}$")
_MEET_ARCHIVE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.MEET_ARCHIVE_SUFFIX)}$")
_MEET_CLOSE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.MEET_CLOSE_SUFFIX)}$")
_MEET_REOPEN_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.MEET_REOPEN_SUFFIX)}$")
_MEET_EMPTY_TRASH_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.MEET_EMPTY_TRASH_SUFFIX)}$")
_SAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")
_WEB_ADDRESS_SCHEMES = ("http://", "https://")
_DEFAULT_DOWNLOAD_NAME = "meet_file"
_DEFAULT_SHEET_NAME = "meet_sheet.txt"
_PASTED_SHEET_NAME = "pasted meet sheet"
_SHEETS_FOLDER = "meet_sheets"
_SIGN_IN_PAGE_MARKER = b"accounts.google.com"
_MAX_STORED_NAME_CHARS = 80
_MEET_ASSIGN_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_MEETS)}/(\d+){re.escape(constants.MEET_ASSIGN_SUFFIX)}$")
_NON_FILENAME_CHARACTERS = re.compile(r"[^a-z0-9]+")
_DQ_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_DQS)}/(\d+)$")
_DQ_TRASH_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_DQS)}/(\d+){re.escape(constants.DQ_TRASH_SUFFIX)}$")
_DQ_RESTORE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_DQS)}/(\d+){re.escape(constants.DQ_RESTORE_SUFFIX)}$")
_DQ_STATE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_DQS)}/(\d+){re.escape(constants.DQ_STATE_SUFFIX)}$")


def meet_folder_name(meet: dict[str, Any]) -> str:
    """File-safe folder name for a meet, for example ``2026-10-16_candy-meet``.

    Args:
        meet: Meet with ``name`` and ``start_date``.

    Returns:
        The folder name.
    """
    slug = _NON_FILENAME_CHARACTERS.sub("-", meet["name"].lower()).strip("-") or "meet"
    return constants.MEET_FOLDER_FORMAT.format(start_date=meet["start_date"], slug=slug)


def build_audio_path(filename_prefix: str, content_type_header: str, directory: Path, timestamp: datetime | None = None) -> Path:
    """Choose a unique, server-generated path for an uploaded audio file.

    Files are grouped into one subdirectory per local calendar day (for example
    ``directory/2026-10-16/clip_20261016_101500_123456.wav``). The filename never
    comes from the client, which rules out path tricks. The day directory is
    not created here; callers create it before writing.

    Args:
        filename_prefix: Start of the file name, for example ``"clip"``.
        content_type_header: Raw Content-Type header sent with the upload, for
            example ``"audio/webm;codecs=opus"``. Parameters after ``;`` are ignored.
        directory: Base recordings directory.
        timestamp: Time used in the filename and day directory. Defaults to now.

    Returns:
        Path inside the day subdirectory with an extension matching the media type.
    """
    media_type = content_type_header.split(";")[0].strip().lower()
    extension = constants.AUDIO_EXTENSION_BY_MEDIA_TYPE.get(media_type, constants.UNKNOWN_AUDIO_EXTENSION)
    moment = timestamp or datetime.now()
    stamp = moment.strftime(constants.RECORDING_TIMESTAMP_FORMAT)
    day_directory = directory / moment.strftime(constants.DAY_DIRECTORY_FORMAT)
    return day_directory / f"{filename_prefix}_{stamp}{extension}"


def build_recording_path(content_type_header: str, recordings_directory: Path, timestamp: datetime | None = None) -> Path:
    """Choose a path for a legacy mic-test upload (see ``build_audio_path``)."""
    return build_audio_path(constants.RECORDING_FILENAME_PREFIX, content_type_header, recordings_directory, timestamp)


def build_web_config() -> dict[str, Any]:
    """Collect the settings the web pages need, taken from ``constants``.

    Returns:
        A JSON-serializable dictionary, embedded into the page scripts.
    """
    return {
        "clipsRoute": constants.ROUTE_CLIPS,
        "clipsKey": constants.RESPONSE_KEY_CLIPS,
        "infoKeyStartedAt": constants.CAPTURE_INFO_KEY_STARTED_AT,
        "infoKeyEndedAt": constants.CAPTURE_INFO_KEY_ENDED_AT,
        "meterFloorDbfs": constants.METER_FLOOR_DBFS,
        "hour12": constants.USE_12_HOUR_CLOCK,
        "clippingAmplitude": constants.CLIPPING_AMPLITUDE,
        "clippingMinSamples": constants.CLIPPING_MIN_SAMPLES,
        "levelTooHotDbfs": constants.LEVEL_TOO_HOT_DBFS,
        "levelTargetLowDbfs": constants.LEVEL_TARGET_LOW_DBFS,
        "levelTargetHighDbfs": constants.LEVEL_TARGET_HIGH_DBFS,
        "downsampleHalfWidth": constants.DOWNSAMPLE_FILTER_HALF_WIDTH,
        "downsampleCutoffFraction": constants.DOWNSAMPLE_CUTOFF_FRACTION,
        "clippingWarningSeconds": constants.CLIPPING_WARNING_SECONDS,
        "textKey": constants.REQUEST_KEY_TEXT,
        "dqIdsKey": constants.RESPONSE_KEY_DQ_IDS,
        "audioSuffix": constants.CLIP_AUDIO_SUFFIX,
        "reprocessSuffix": constants.CLIP_REPROCESS_SUFFIX,
        "trashSuffix": constants.CLIP_TRASH_SUFFIX,
        "restoreSuffix": constants.CLIP_RESTORE_SUFFIX,
        "deleteSuffix": constants.CLIP_DELETE_SUFFIX,
        "viewQueryKey": constants.QUERY_KEY_VIEW,
        "viewTrash": constants.VIEW_TRASH,
        "dqsRoute": constants.ROUTE_DQS,
        "dqsKey": constants.RESPONSE_KEY_DQS,
        "dqStateSuffix": constants.DQ_STATE_SUFFIX,
        "candidatesRoute": constants.ROUTE_CANDIDATES,
        "candidatesKey": constants.RESPONSE_KEY_CANDIDATES,
        "dismissRoute": constants.ROUTE_DISMISS_CANDIDATE,
        "codesRoute": constants.ROUTE_DQ_CODES,
        "codesKey": constants.RESPONSE_KEY_CODES,
        "candidateKeyKey": constants.REQUEST_KEY_CANDIDATE_KEY,
        "stateKey": constants.REQUEST_KEY_STATE,
        "dqStates": {
            "called": constants.DQ_STATE_CALLED, "accepted": constants.DQ_STATE_ACCEPTED,
            "notified": constants.DQ_STATE_NOTIFIED, "declined": constants.DQ_STATE_DECLINED,
            "protested": constants.DQ_STATE_PROTESTED, "upheld": constants.DQ_STATE_UPHELD,
            "overturned": constants.DQ_STATE_OVERTURNED,
        },
        "dqStatusLabels": constants.DQ_STATUS_LABELS,
        "dqEventsPerPage": constants.DQ_EVENTS_PER_PAGE,
        "statesAfterNotification": list(constants.DQ_STATES_AFTER_NOTIFICATION),
        "notifiedByOptions": list(constants.NOTIFIED_BY_OPTIONS),
        "protestRuledByOptions": list(constants.PROTEST_RULED_BY_OPTIONS),
        "maxProtestCycles": constants.MAX_PROTEST_CYCLES,
        "protestWindowMinutes": constants.PROTEST_WINDOW_MINUTES,
        "notifyEventRoute": constants.ROUTE_NOTIFY_EVENT,
        "dqTrashSuffix": constants.DQ_TRASH_SUFFIX,
        "importOfficialsRoute": constants.ROUTE_IMPORT_OFFICIALS,
        "rebuildTrainingMeetRoute": constants.ROUTE_REBUILD_TRAINING_MEET,
        "coachPageRoute": constants.ROUTE_COACH_PAGE,
        "coachPagePasswordRoute": constants.ROUTE_COACH_PAGE_PASSWORD,
        "coachPageKey": constants.RESPONSE_KEY_COACH_PAGE,
        "coachSignRoute": constants.ROUTE_COACH_SIGN,
        "autoDqsRoute": constants.ROUTE_AUTO_DQS,
        "eventSummaryRoute": constants.ROUTE_EVENT_SUMMARY,
        "printRequestedQueryKey": constants.QUERY_KEY_PRINT_REQUESTED,
        "layoutQueryKey": constants.QUERY_KEY_LAYOUT,
        "slipLayoutOnePerPage": constants.SLIP_LAYOUT_ONE_PER_PAGE,
        "slipLayoutTwoUp": constants.SLIP_LAYOUT_TWO_UP,
        "printRequestedFilter": constants.DQ_FILTER_PRINT_REQUESTED,
        "enabledKey": constants.REQUEST_KEY_ENABLED,
        "meetFromSheetRoute": constants.ROUTE_MEET_FROM_SHEET,
        "sheetTextKey": constants.REQUEST_KEY_SHEET_TEXT,
        "sheetKey": constants.RESPONSE_KEY_SHEET,
        "trainingMeetName": DEMO_MEET_NAME,
        "signinRosterUrl": constants.OFFICIALS_SIGNIN_ROSTER_URL,
        "officialsResponseKey": constants.RESPONSE_KEY_OFFICIALS,
        "sessionKey": constants.RESPONSE_KEY_SESSION,
        "warningsKey": constants.RESPONSE_KEY_WARNINGS,
        "dqRestoreSuffix": constants.DQ_RESTORE_SUFFIX,
        "dqFromUtteranceRoute": constants.ROUTE_DQ_FROM_UTTERANCE,
        "utteranceIdKey": constants.REQUEST_KEY_UTTERANCE_ID,
        "textKey": constants.REQUEST_KEY_TEXT,
        "byKey": constants.REQUEST_KEY_BY,
        "noteKey": constants.REQUEST_KEY_NOTE,
        "atKey": constants.REQUEST_KEY_AT,
        "eventKey": constants.REQUEST_KEY_EVENT,
        "includeNotReadyKey": constants.REQUEST_KEY_INCLUDE_NOT_READY,
        "dqRequiredFields": list(constants.DQ_REQUIRED_FIELDS),
        "racePhases": list(constants.RACE_PHASES),
        "sectionAbbreviations": constants.SLIP_SECTION_ABBREVIATIONS,
        "officialRoles": list(constants.OFFICIAL_ROLES),
        "slipRevision": constants.CURRENT_SLIP_REVISION,
        "evidenceRoleCall": constants.EVIDENCE_ROLE_CALL,
        "meetsRoute": constants.ROUTE_MEETS,
        "meetsKey": constants.RESPONSE_KEY_MEETS,
        "activeMeetKey": constants.RESPONSE_KEY_ACTIVE_MEET_ID,
        "meetActivateSuffix": constants.MEET_ACTIVATE_SUFFIX,
        "meetFileSuffix": constants.ROUTE_MEET_FILE_SUFFIX,
        "meetArchiveSuffix": constants.MEET_ARCHIVE_SUFFIX,
        "meetCloseSuffix": constants.MEET_CLOSE_SUFFIX,
        "meetReopenSuffix": constants.MEET_REOPEN_SUFFIX,
        "meetEmptyTrashSuffix": constants.MEET_EMPTY_TRASH_SUFFIX,
        "deletedClipsKey": constants.RESPONSE_KEY_DELETED_CLIPS,
        "deletedDqsKey": constants.RESPONSE_KEY_DELETED_DQS,
        "meetProgramSuffix": constants.ROUTE_MEET_PROGRAM_SUFFIX,
        "programKey": constants.RESPONSE_KEY_PROGRAM,
        "urlKey": constants.REQUEST_KEY_URL,
        "filenameQueryKey": constants.QUERY_KEY_FILENAME,
        "meetFileFormatLabels": constants.MEET_FILE_FORMAT_LABELS,
        "slipsRoute": constants.ROUTE_SLIPS,
        "idsQueryKey": constants.QUERY_KEY_IDS,
        "eventQueryKey": constants.QUERY_KEY_EVENT,
        "noMeetId": constants.NO_MEET_ID,
        "officialsKey": constants.REQUEST_KEY_OFFICIALS,
        "rosterRoles": list(constants.MEET_ROSTER_ROLES),
        "meetNameKey": constants.REQUEST_KEY_MEET_NAME,
        "meetStartDateKey": constants.REQUEST_KEY_MEET_START_DATE,
        "audioInputStorageKey": constants.AUDIO_INPUT_STORAGE_KEY,
        "utterancesRoute": constants.ROUTE_UTTERANCES,
        "workletRoute": constants.ROUTE_CAPTURE_WORKLET,
        "processorName": constants.CAPTURE_PROCESSOR_NAME,
        "chunkSize": constants.CAPTURE_CHUNK_SAMPLES,
        "targetSampleRate": constants.AUDIO_SAMPLE_RATE_HZ,
        "wavMediaType": constants.WAV_UPLOAD_MEDIA_TYPE,
        "jsonMediaType": constants.JSON_CONTENT_TYPE,
        "captureInfoHeader": constants.CAPTURE_INFO_HEADER,
        "startDbfs": constants.CAPTURE_START_DBFS,
        "endDbfs": constants.CAPTURE_END_DBFS,
        "hangSeconds": constants.CAPTURE_HANG_SECONDS,
        "levelSlider": {
            "min": constants.CAPTURE_LEVEL_SLIDER_MIN_DBFS,
            "max": constants.CAPTURE_LEVEL_SLIDER_MAX_DBFS,
            "step": constants.CAPTURE_LEVEL_SLIDER_STEP_DBFS,
        },
        "hangSlider": {
            "min": constants.CAPTURE_HANG_SLIDER_MIN_SECONDS,
            "max": constants.CAPTURE_HANG_SLIDER_MAX_SECONDS,
            "step": constants.CAPTURE_HANG_SLIDER_STEP_SECONDS,
        },
        "prerollSeconds": constants.CAPTURE_PREROLL_SECONDS,
        "trailSeconds": constants.CAPTURE_TRAIL_SECONDS,
        "minClipSeconds": constants.CAPTURE_MIN_CLIP_SECONDS,
        "maxClipSeconds": constants.CAPTURE_MAX_CLIP_SECONDS,
        "startChunks": constants.CAPTURE_START_CHUNKS,
        "echoCancellation": constants.CAPTURE_ECHO_CANCELLATION,
        "noiseSuppression": constants.CAPTURE_NOISE_SUPPRESSION,
        "autoGainControl": constants.CAPTURE_AUTO_GAIN_CONTROL,
        "settingsStorageKey": constants.CAPTURE_SETTINGS_STORAGE_KEY,
        "pollSeconds": constants.CLIP_LIST_POLL_SECONDS,
        "stallSeconds": constants.CAPTURE_STALL_SECONDS,
        "watchdogIntervalSeconds": constants.CAPTURE_WATCHDOG_INTERVAL_SECONDS,
        "uploadRetrySeconds": constants.UPLOAD_RETRY_SECONDS,
        "dbfsFloor": constants.DBFS_FLOOR,
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


def render_mic_test_page() -> bytes:
    """Render the microphone test page with shared constants filled in."""
    return _render(
        constants.MIC_TEST_PAGE_FILENAME,
        {
            "upload_endpoint": constants.ROUTE_UPLOAD_RECORDING,
            "record_seconds": str(constants.MIC_TEST_RECORD_SECONDS),
            "key_saved_as": constants.RESPONSE_KEY_SAVED_AS,
            "key_size_bytes": constants.RESPONSE_KEY_SIZE_BYTES,
            "key_error": constants.RESPONSE_KEY_ERROR,
        },
    )


def render_app_page() -> bytes:
    """Render the main web app page."""
    return _render(
        constants.APP_PAGE_FILENAME,
        {
            "script_route": constants.ROUTE_APP_SCRIPT,
            "qr_script_route": constants.ROUTE_VENDOR + constants.QR_SCRIPT_FILENAME,
            "dq_script_route": constants.ROUTE_DQ_SCRIPT,
            "meet_script_route": constants.ROUTE_MEET_SCRIPT,
            "transcript_route": constants.ROUTE_TRANSCRIPT_TEXT,
            "export_route": constants.ROUTE_EXPORT,
            "mic_test_route": constants.ROUTE_MIC_TEST,
        },
    )


def render_script(filename: str) -> bytes:
    """Render a web script, embedding the shared settings as ``${config}``."""
    return _render(filename, {"config": json.dumps(build_web_config())})


class DqTranscribeServer(ThreadingHTTPServer):
    """HTTP server that knows where clips are stored and how they are queued.

    Attributes:
        recordings_directory: Directory where uploaded audio is saved.
        database: Queue and transcript storage.
        worker: Transcription worker to wake when a clip arrives (may be None in tests).
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        recordings_directory: Path,
        database: Database,
        worker: TranscriptionWorker | None = None,
        coach_port: int = constants.COACH_SERVER_PORT,
    ) -> None:
        """Create the server and make sure the recordings directory exists.

        Args:
            server_address: ``(host, port)`` to bind. Use port 0 to let the OS choose.
            recordings_directory: Directory where uploaded audio is saved.
            database: Queue and transcript storage.
            worker: Transcription worker to wake on new clips.
            coach_port: Port for the coach page server (not started here; see ``CoachPage``).
        """
        self.recordings_directory = recordings_directory
        self.recordings_directory.mkdir(parents=True, exist_ok=True)
        self.database = database
        self.meet_files_directory = recordings_directory.parent / constants.MEET_FILES_DIRECTORY.name
        self.program_store = MeetProgramStore(database)
        self.program_store.initialize()
        self.dq_store = DqStore(database, self.program_store)
        self.dq_store.initialize()
        self.coach_page = CoachPage(database, self.dq_store, coach_port)
        self.auto_dqs = AutoDqCreator(database, self.dq_store)  # started by the app (not in tests)
        self.worker = worker
        super().__init__(server_address, RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    """Handles page requests, clip uploads, and transcript edits."""

    server: DqTranscribeServer

    # --- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Serve pages, scripts, clip data, audio, and downloads."""
        url = urlsplit(self.path)
        path = url.path
        database = self.server.database

        if path == constants.ROUTE_HOME:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_app_page())
        elif path == constants.ROUTE_MIC_TEST:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_mic_test_page())
        elif path == constants.ROUTE_APP_SCRIPT:
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.APP_SCRIPT_FILENAME))
        elif path == constants.ROUTE_MEET_SCRIPT:
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.MEET_SCRIPT_FILENAME))
        elif path == constants.ROUTE_DQ_SCRIPT:
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.DQ_SCRIPT_FILENAME))
        elif path == constants.ROUTE_CAPTURE_WORKLET:
            self._send_bytes(
                HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.CAPTURE_WORKLET_FILENAME)
            )
        elif path == constants.ROUTE_CLIPS:
            views = parse_qs(url.query).get(constants.QUERY_KEY_VIEW, [])
            # The transcript shows the active meet's clips (all clips if no meet is active).
            clips = database.list_clips(
                limit=constants.CLIP_LIST_LIMIT,
                trashed=constants.VIEW_TRASH in views,
                meet_id=database.get_active_meet_id(),
            )
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_CLIPS: clips})
        elif path == constants.ROUTE_DQS:
            trashed = parse_qs(url.query).get(constants.QUERY_KEY_VIEW, [""])[0] == constants.VIEW_TRASH
            dqs = self.server.dq_store.list_dqs(database.get_active_meet_id(), trashed=trashed)
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_DQS: dqs})
        elif path == constants.ROUTE_CANDIDATES:
            candidates = self.server.dq_store.candidates(database.get_active_meet_id())
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_CANDIDATES: candidates})
        elif path == constants.ROUTE_DQ_CODES:
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_CODES: load_dq_codes()})
        elif path == constants.ROUTE_MEETS:
            self._send_json(
                HTTPStatus.OK,
                {
                    constants.RESPONSE_KEY_MEETS: database.list_meets(),
                    constants.RESPONSE_KEY_ACTIVE_MEET_ID: database.get_active_meet_id(),
                },
            )
        elif path == constants.ROUTE_SLIPS:
            self._send_slips(parse_qs(url.query))
        elif path == constants.ROUTE_COACH_PAGE:
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_COACH_PAGE: self.server.coach_page.status()})
        elif path == constants.ROUTE_EVENT_SUMMARY:
            self._send_event_summary(parse_qs(url.query))
        elif path == constants.ROUTE_AUTO_DQS:
            self._send_json(HTTPStatus.OK, {constants.REQUEST_KEY_ENABLED: self.server.auto_dqs.enabled})
        elif path == constants.ROUTE_COACH_SIGN:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, self._render_coach_sign())
        elif path.startswith(constants.ROUTE_VENDOR):
            self._send_vendor_script(path[len(constants.ROUTE_VENDOR):])
        elif path.startswith(constants.ROUTE_FONTS):
            self._send_font(path[len(constants.ROUTE_FONTS):])
        elif (match := _MEET_ARCHIVE_PATTERN.match(path)) is not None:
            self._send_meet_archive(int(match.group(1)))
        elif (match := _MEET_PROGRAM_PATTERN.match(path)) is not None:
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_PROGRAM: self.server.program_store.summary(int(match.group(1)))})
        elif path == constants.ROUTE_EXPORT:
            body = json.dumps(database.export_all(), indent=2).encode("utf-8")
            self._send_bytes(
                HTTPStatus.OK, constants.JSON_CONTENT_TYPE, body, download_filename=constants.EXPORT_DOWNLOAD_FILENAME
            )
        elif path == constants.ROUTE_TRANSCRIPT_TEXT:
            text = format_transcript_text(database.list_clips(newest_first=False, meet_id=database.get_active_meet_id()))
            self._send_bytes(
                HTTPStatus.OK,
                constants.TEXT_CONTENT_TYPE,
                text.encode("utf-8"),
                download_filename=constants.TRANSCRIPT_DOWNLOAD_FILENAME,
            )
        elif (match := _CLIP_AUDIO_PATTERN.match(path)) is not None:
            self._send_clip_audio(int(match.group(1)))
        else:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")

    # --- POST ---------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Accept uploads, reprocess requests, and transcript edits."""
        path = urlsplit(self.path).path

        if path == constants.ROUTE_UPLOAD_RECORDING:
            self._handle_mic_test_upload()
        elif path == constants.ROUTE_CLIPS:
            self._handle_clip_upload()
        elif (match := _CLIP_REPROCESS_PATTERN.match(path)) is not None:
            self._handle_reprocess(int(match.group(1)))
        elif path == constants.ROUTE_MEETS:
            self._handle_create_meet()
        elif path == constants.ROUTE_MEET_FROM_SHEET:
            self._handle_meet_from_sheet(urlsplit(self.path).query)
        elif path == constants.ROUTE_DQS:
            self._handle_create_dq()
        elif path == constants.ROUTE_DISMISS_CANDIDATE:
            self._handle_dismiss_candidate()
        elif path == constants.ROUTE_NOTIFY_EVENT:
            self._handle_notify_event()
        elif path == constants.ROUTE_IMPORT_OFFICIALS:
            self._handle_import_officials()
        elif path == constants.ROUTE_REBUILD_TRAINING_MEET:
            self._handle_rebuild_training_meet()
        elif path == constants.ROUTE_COACH_PAGE:
            self._handle_coach_page_switch()
        elif path == constants.ROUTE_AUTO_DQS:
            self._handle_auto_dqs_switch()
        elif path == constants.ROUTE_DQ_PRINT_REQUESTS:
            self._handle_print_requests()
        elif path == constants.ROUTE_COACH_PAGE_PASSWORD:
            self.server.coach_page.new_password()
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_COACH_PAGE: self.server.coach_page.status()})
        elif path == constants.ROUTE_DQ_FROM_UTTERANCE:
            self._handle_dq_from_utterance()
        elif (match := _DQ_STATE_PATTERN.match(path)) is not None:
            self._handle_dq_state(int(match.group(1)))
        elif (match := _DQ_TRASH_PATTERN.match(path)) is not None:
            self._handle_dq_trash(int(match.group(1)), trashed=True)
        elif (match := _DQ_RESTORE_PATTERN.match(path)) is not None:
            self._handle_dq_trash(int(match.group(1)), trashed=False)
        elif (match := _DQ_PATTERN.match(path)) is not None:
            self._handle_update_dq(int(match.group(1)))
        elif (match := _MEET_PATTERN.match(path)) is not None:
            self._handle_update_meet(int(match.group(1)))
        elif (match := _MEET_ACTIVATE_PATTERN.match(path)) is not None:
            self._handle_activate_meet(int(match.group(1)))
        elif (match := _MEET_ASSIGN_PATTERN.match(path)) is not None:
            self._handle_assign_clips(int(match.group(1)))
        elif (match := _MEET_CLOSE_PATTERN.match(path)) is not None:
            self._handle_close_meet(int(match.group(1)), closed=True)
        elif (match := _MEET_REOPEN_PATTERN.match(path)) is not None:
            self._handle_close_meet(int(match.group(1)), closed=False)
        elif (match := _MEET_EMPTY_TRASH_PATTERN.match(path)) is not None:
            self._handle_empty_trash(int(match.group(1)))
        elif (match := _MEET_FILE_PATTERN.match(path)) is not None:
            self._handle_meet_file(int(match.group(1)), urlsplit(self.path).query)
        elif (match := _CLIP_TRASH_PATTERN.match(path)) is not None:
            self._handle_trash(int(match.group(1)))
        elif (match := _CLIP_RESTORE_PATTERN.match(path)) is not None:
            self._handle_restore(int(match.group(1)))
        elif (match := _CLIP_DELETE_PATTERN.match(path)) is not None:
            self._handle_permanent_delete(int(match.group(1)))
        elif (match := _UTTERANCE_PATTERN.match(path)) is not None:
            self._handle_utterance_edit(int(match.group(1)))
        else:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Not found")

    def _handle_mic_test_upload(self) -> None:
        """Save a legacy mic-test recording (not queued for transcription)."""
        audio_bytes = self._read_request_body()
        if audio_bytes is None:
            return
        recording_path = build_recording_path(
            self.headers.get(constants.CONTENT_TYPE_HEADER, ""), self.server.recordings_directory
        )
        recording_path.parent.mkdir(parents=True, exist_ok=True)
        recording_path.write_bytes(audio_bytes)
        LOGGER.info("Saved %s (%d bytes)", recording_path.name, len(audio_bytes))
        self._send_json(
            HTTPStatus.OK,
            {
                constants.RESPONSE_KEY_SAVED_AS: recording_path.relative_to(self.server.recordings_directory).as_posix(),
                constants.RESPONSE_KEY_SIZE_BYTES: len(audio_bytes),
            },
        )

    def _handle_clip_upload(self) -> None:
        """Save a WAV clip from the browser and queue it for transcription."""
        media_type = self.headers.get(constants.CONTENT_TYPE_HEADER, "").split(";")[0].strip().lower()
        if media_type not in constants.WAV_MEDIA_TYPES:
            self._send_json_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Clips must be uploaded as WAV")
            return
        audio_bytes = self._read_request_body()
        if audio_bytes is None:
            return
        if not self._is_mono_16_bit_wav(audio_bytes):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Not a mono 16-bit WAV file")
            return

        database = self.server.database
        meet_id = database.get_active_meet_id()
        meet = None if meet_id is None else database.get_meet(meet_id)
        clip_directory = self.server.recordings_directory
        if meet is not None:
            clip_directory = clip_directory / meet_folder_name(meet)
        clip_path = build_audio_path(constants.CLIP_FILENAME_PREFIX, media_type, clip_directory)
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(audio_bytes)
        relative_clip_name = clip_path.relative_to(self.server.recordings_directory).as_posix()
        capture_info_json = self._read_capture_info(self.headers.get(constants.CAPTURE_INFO_HEADER, ""))
        started_at, ended_at = self._read_capture_times(capture_info_json)
        clip_id = database.add_clip(
            relative_clip_name, capture_info_json, started_at, ended_at, meet_id=None if meet is None else meet_id
        )
        if self.server.worker is not None:
            self.server.worker.wake()
        LOGGER.info("Queued clip %d (%s, %d bytes)", clip_id, relative_clip_name, len(audio_bytes))
        self._send_json(
            HTTPStatus.OK,
            {
                constants.RESPONSE_KEY_CLIP_ID: clip_id,
                constants.RESPONSE_KEY_SAVED_AS: relative_clip_name,
                constants.RESPONSE_KEY_SIZE_BYTES: len(audio_bytes),
            },
        )

    def _handle_reprocess(self, clip_id: int) -> None:
        """Put a finished or failed clip back in the queue."""
        if not self.server.database.requeue_clip(clip_id):
            self._send_json_error(HTTPStatus.CONFLICT, "Clip not found, or still waiting or running")
            return
        if self.server.worker is not None:
            self.server.worker.wake()
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _read_json_object(self) -> dict[str, Any] | None:
        """Read a JSON object request body, or send an error and return None."""
        body = self._read_request_body()
        if body is None:
            return None
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Expected a JSON object")
            return None
        return payload

    def _read_meet_name_and_date(self, payload: dict[str, Any]) -> tuple[str, str] | None:
        """Validate a meet's name and first day, or send an error and return None."""
        name = payload.get(constants.REQUEST_KEY_MEET_NAME)
        start_date = payload.get(constants.REQUEST_KEY_MEET_START_DATE)
        if not isinstance(name, str) or not name.strip() or len(name) > constants.MAX_MEET_NAME_CHARS:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "The meet needs a name")
            return None
        try:
            datetime.strptime(str(start_date), constants.MEET_START_DATE_FORMAT)
        except ValueError:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "The start date must look like 2026-10-16")
            return None
        return name.strip(), str(start_date)

    def _handle_update_meet(self, meet_id: int) -> None:
        """Change a meet: {"name", "start_date", "officials": [{"name", "role"}, ...]}."""
        payload = self._read_json_object()
        if payload is None:
            return
        name_and_date = self._read_meet_name_and_date(payload)
        if name_and_date is None:
            return
        officials_payload = payload.get(constants.REQUEST_KEY_OFFICIALS, [])
        officials: list[tuple[str, str]] = []
        if not isinstance(officials_payload, list) or len(officials_payload) > constants.MAX_MEET_OFFICIALS:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "officials must be a list")
            return
        for item in officials_payload:
            official_name = item.get("name") if isinstance(item, dict) else None
            role = item.get("role") if isinstance(item, dict) else None
            if not isinstance(official_name, str) or not official_name.strip():
                continue  # blank rows are ignored
            if role not in constants.MEET_ROSTER_ROLES:
                self._send_json_error(HTTPStatus.BAD_REQUEST, f"Unknown role {role!r}")
                return
            officials.append((official_name.strip()[: constants.MAX_MEET_NAME_CHARS], role))
        if not self.server.database.update_meet(meet_id, *name_and_date, officials):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_create_meet(self) -> None:
        """Create a meet from {"name", "start_date"} and make it the active meet."""
        payload = self._read_json_object()
        if payload is None:
            return
        name = payload.get(constants.REQUEST_KEY_MEET_NAME)
        start_date = payload.get(constants.REQUEST_KEY_MEET_START_DATE)
        if not isinstance(name, str) or not name.strip() or len(name) > constants.MAX_MEET_NAME_CHARS:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "The meet needs a name")
            return
        try:
            datetime.strptime(str(start_date), constants.MEET_START_DATE_FORMAT)
        except ValueError:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "The start date must look like 2026-10-16")
            return
        meet_id = self.server.database.create_meet(name.strip(), str(start_date))
        LOGGER.info("Created meet %d: %s (%s)", meet_id, name.strip(), start_date)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_MEET_ID: meet_id})

    def _handle_meet_from_sheet(self, query: str) -> None:
        """Create a meet from its meet sheet: the file as the body (``?name=``), or {"url"} or {"text"}.

        The meet gets the sheet's name and first day, the named officials (in their
        roster roles), and the events and sessions as its first program version.
        It becomes the active meet. The reply says what was found and what is missing.
        """
        media_type = self.headers.get(constants.CONTENT_TYPE_HEADER, "").split(";")[0].strip().lower()
        original_name = parse_qs(query).get(constants.QUERY_KEY_FILENAME, [_DEFAULT_SHEET_NAME])[0]
        source = original_name
        if media_type == constants.JSON_CONTENT_TYPE:
            payload = self._read_json_object()
            if payload is None:
                return
            text = payload.get(constants.REQUEST_KEY_SHEET_TEXT)
            url = str(payload.get(constants.REQUEST_KEY_URL) or "").strip()
            if isinstance(text, str) and text.strip():
                sheet_bytes, original_name, source = text.encode("utf-8"), _PASTED_SHEET_NAME, _PASTED_SHEET_NAME
            elif url.lower().startswith(_WEB_ADDRESS_SCHEMES):
                try:
                    with urllib.request.urlopen(download_address(url), timeout=constants.MEET_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
                        sheet_bytes = response.read(constants.MAX_MEET_FILE_BYTES + 1)
                except (urllib.error.URLError, OSError, ValueError) as error:
                    self._send_json_error(HTTPStatus.BAD_GATEWAY, f"Could not download the meet sheet: {error}")
                    return
                if _SIGN_IN_PAGE_MARKER in sheet_bytes[:20000]:
                    self._send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, "That document is not shared publicly. Download it and pick the file instead.")
                    return
                original_name, source = Path(urlsplit(url).path).name or _DEFAULT_SHEET_NAME, url
            else:
                self._send_json_error(HTTPStatus.BAD_REQUEST, "Paste the meet sheet's web address or its text, or pick the file")
                return
        else:
            sheet_bytes = self._read_request_body()
            if sheet_bytes is None:
                return
        if len(sheet_bytes) > constants.MAX_MEET_FILE_BYTES:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "The meet sheet is too large")
            return
        folder = self.server.meet_files_directory / _SHEETS_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = _SAFE_FILENAME_CHARACTERS.sub("_", original_name)[:_MAX_STORED_NAME_CHARS] or _DEFAULT_SHEET_NAME
        stored_path = folder / f"{datetime.now().strftime(constants.RECORDING_TIMESTAMP_FORMAT)}_{safe_name}"
        stored_path.write_bytes(sheet_bytes)
        program = self._read_meet_manager_file(stored_path, original_name)
        if program is not None:
            self._create_meet_from_program(program[0], program[1], source, original_name, stored_path)
            return
        try:
            sheet = read_meet_sheet_file(stored_path, original_name)
        except MeetFileError as error:
            stored_path.unlink(missing_ok=True)
            self._send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
            return
        if not sheet.name:
            stored_path.unlink(missing_ok=True)
            self._send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, "No meet name found on the sheet")
            return
        database = self.server.database
        start_date = (sheet.start_date or today()).isoformat()
        meet_id = database.create_meet(sheet.name, start_date)
        roster = [(official["name"], official["role"]) for official in sheet.officials if official["role"]]
        if roster:
            database.update_meet(meet_id, sheet.name, start_date, roster)
        if sheet.events or sheet.sessions:
            self.server.program_store.save(meet_id, sheet.program(), constants.MEET_FILE_FORMAT_SHEET, source, original_name, str(stored_path))
        LOGGER.info("Created meet %d from a meet sheet: %s", meet_id, sheet.summary())
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_MEET_ID: meet_id, constants.RESPONSE_KEY_SHEET: sheet.summary()})

    @staticmethod
    def _read_meet_manager_file(path: Path, original_name: str) -> tuple | None:
        """The file as a Meet Manager file (database or heat-sheet report) if it is one: (program, format).

        A file with seeded swimmers is a Meet Manager file; anything else (a meet
        sheet has events but no swimmers) returns None and is read as a meet sheet.
        """
        try:
            program, file_format = read_meet_file(path, original_name)
        except MeetFileError:
            return None
        return (program, file_format) if program.entries else None

    def _create_meet_from_program(self, program: Any, file_format: str, source: str, original_name: str, stored_path: Path) -> None:
        """Create the meet (active) from a Meet Manager file, with the file as its first program version."""
        database = self.server.database
        name = (program.meet_name or Path(original_name).stem)[: constants.MAX_MEET_NAME_CHARS]
        start_date = program.start_date or today().isoformat()
        meet_id = database.create_meet(name, start_date)
        self.server.program_store.save(meet_id, program, file_format, source, original_name, str(stored_path))
        missing = [] if program.start_date else ["the date (set the first day by hand)"]
        summary = {
            "name": name, "start_date": start_date, "events": len(program.events), "entries": len(program.entries),
            "sessions": [{"name": session.name, "day": session.day, "start_time": session.start_time} for session in program.sessions],
            "officials": [], "missing": missing + ["officials (add them, or import from Sign-In)"],
            "file_format": file_format,
        }
        LOGGER.info("Created meet %d from a Meet Manager file: %s", meet_id, {k: v for k, v in summary.items() if k != "sessions"})
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_MEET_ID: meet_id, constants.RESPONSE_KEY_SHEET: summary})

    def _send_slips(self, query: dict[str, list[str]]) -> None:
        """Send printable slips.

        ``?ids=3,4`` for those DQs, ``?event=12`` for an event of the active meet, or
        ``?print_requested=1`` for the slips coaches asked for. ``&layout=two_up``
        prints two per page; the requested slips are then sorted by club.
        """
        meet_id = self.server.database.get_active_meet_id()
        dqs = self.server.dq_store.list_dqs(meet_id)
        wanted_ids = {int(part) for value in query.get(constants.QUERY_KEY_IDS, []) for part in value.split(",") if part.strip().isdigit()}
        event = (query.get(constants.QUERY_KEY_EVENT) or [""])[0].strip()
        layout = (query.get(constants.QUERY_KEY_LAYOUT) or [constants.SLIP_LAYOUT_ONE_PER_PAGE])[0]
        if layout not in constants.SLIP_LAYOUTS:
            layout = constants.SLIP_LAYOUT_ONE_PER_PAGE
        if query.get(constants.QUERY_KEY_PRINT_REQUESTED):
            dqs = [dq for dq in dqs if dq.get("print_requested_at")]
            if layout == constants.SLIP_LAYOUT_TWO_UP:
                dqs.sort(key=club_sort_key)
            toolbar = print_requests_toolbar([dq["id"] for dq in dqs], constants.CURRENT_SLIP_REVISION, layout)
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_slips(dqs, "Requested DQ slips", toolbar_html=toolbar, layout=layout))
            return
        if wanted_ids:
            dqs = [dq for dq in self.server.dq_store.list_dqs(None) if dq["id"] in wanted_ids]
            title = "DQ slips"
        elif event:
            dqs = [dq for dq in dqs if (dq["event"] or "") == event and dq["state"] != constants.DQ_STATE_DECLINED]
            title = f"DQ slips, event {event}"
        else:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Say which DQs: ?ids=3,4 or ?event=12")
            return
        self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_slips(dqs, title, layout=layout))

    def _send_event_summary(self, query: dict[str, list[str]]) -> None:
        """The printed DQ summary of one event of the active meet (``?event=12``)."""
        event = (query.get(constants.QUERY_KEY_EVENT) or [""])[0].strip()
        meet_id = self.server.database.get_active_meet_id()
        meet = self.server.database.get_meet(meet_id) if meet_id is not None else None
        if not event or meet is None:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Say which event of the active meet: ?event=12")
            return
        dqs = [dq for dq in self.server.dq_store.list_dqs(meet_id) if (dq["event"] or "") == event]
        self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_event_summary(meet["name"], event, dqs))

    def _send_font(self, filename: str) -> None:
        """Send a bundled font file (only plain file names inside web/fonts/)."""
        font_path = _WEB_DIRECTORY / constants.FONTS_DIRECTORY_NAME / filename
        if "/" in filename or filename.startswith(".") or not font_path.is_file():
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such font")
            return
        self._send_bytes(HTTPStatus.OK, constants.FONT_CONTENT_TYPE, font_path.read_bytes())

    def _send_meet_archive(self, meet_id: int) -> None:
        """Build the meet's archive zip and send it as a download (streamed, then removed)."""
        meet = self.server.database.get_meet(meet_id)
        if meet is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        scratch = self.server.recordings_directory.parent / constants.SCRATCH_DIRECTORY.name
        scratch.mkdir(parents=True, exist_ok=True)
        filename = archive_filename(meet, meet_folder_name(meet))
        archive_path = scratch / filename
        try:
            counts = build_meet_archive(self.server.database, self.server.dq_store, meet_id, self.server.recordings_directory, archive_path)
            LOGGER.info("Built archive %s: %s", filename, counts)
            self.send_response(HTTPStatus.OK)
            self.send_header(constants.CONTENT_TYPE_HEADER, constants.ZIP_CONTENT_TYPE)
            self.send_header(constants.CONTENT_LENGTH_HEADER, str(archive_path.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            with archive_path.open("rb") as handle:
                while chunk := handle.read(constants.FILE_CHUNK_BYTES):
                    self.wfile.write(chunk)
        finally:
            archive_path.unlink(missing_ok=True)

    def _handle_close_meet(self, meet_id: int, closed: bool) -> None:
        """Close or reopen a meet."""
        if not self.server.database.set_meet_closed(meet_id, closed):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_empty_trash(self, meet_id: int) -> None:
        """Permanently delete a closed meet's trashed clips (and their audio) and declined DQs."""
        meet = self.server.database.get_meet(meet_id)
        if meet is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        if not meet.get("closed_at"):
            self._send_json_error(HTTPStatus.CONFLICT, constants.MEET_STILL_OPEN_MESSAGE)
            return
        deleted_clips = 0
        for clip in self.server.database.list_clips(trashed=True, meet_id=meet_id):
            filename = self.server.database.delete_trashed_clip(clip["id"])
            audio_path = None if filename is None else self._resolve_audio_path(filename)
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)
                deleted_clips += 1
        deleted_dqs = self.server.dq_store.empty_trash(meet_id)
        LOGGER.info("Emptied the trash of meet %d: %d clips, %d DQs", meet_id, deleted_clips, deleted_dqs)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_DELETED_CLIPS: deleted_clips, constants.RESPONSE_KEY_DELETED_DQS: deleted_dqs})

    def _handle_meet_file(self, meet_id: int, query: str) -> None:
        """Load a Meet Manager file for a meet.

        Two ways in: the file itself as the request body (its name in
        ``?name=``), or a JSON body ``{"url": "https://..."}`` to download it. The
        file is kept (one copy, in ``meet_files/``) and read; the result becomes
        the meet's active program. Earlier files are kept as older versions.
        """
        meet = self.server.database.get_meet(meet_id)
        if meet is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        media_type = self.headers.get(constants.CONTENT_TYPE_HEADER, "").split(";")[0].strip().lower()
        if media_type == constants.JSON_CONTENT_TYPE:
            payload = self._read_json_object()
            if payload is None:
                return
            url = str(payload.get(constants.REQUEST_KEY_URL) or "").strip()
            if not url.lower().startswith(_WEB_ADDRESS_SCHEMES):
                self._send_json_error(HTTPStatus.BAD_REQUEST, "The web address must start with http:// or https://")
                return
            try:
                with urllib.request.urlopen(url, timeout=constants.MEET_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
                    file_bytes = response.read(constants.MAX_MEET_FILE_BYTES + 1)
            except (urllib.error.URLError, OSError, ValueError) as error:
                self._send_json_error(HTTPStatus.BAD_GATEWAY, f"Could not download the file: {error}")
                return
            original_name = Path(urlsplit(url).path).name or _DEFAULT_DOWNLOAD_NAME
            source = url
        else:
            file_bytes = self._read_request_body()
            if file_bytes is None:
                return
            original_name = parse_qs(query).get(constants.QUERY_KEY_FILENAME, [_DEFAULT_DOWNLOAD_NAME])[0]
            source = original_name
        if len(file_bytes) > constants.MAX_MEET_FILE_BYTES:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "The meet file is too large")
            return
        folder = self.server.meet_files_directory / meet_folder_name(meet)
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = _SAFE_FILENAME_CHARACTERS.sub("_", original_name)[:_MAX_STORED_NAME_CHARS] or _DEFAULT_DOWNLOAD_NAME
        stored_path = folder / f"{datetime.now().strftime(constants.RECORDING_TIMESTAMP_FORMAT)}_{safe_name}"
        stored_path.write_bytes(file_bytes)
        try:
            program, file_format = read_meet_file(stored_path, original_name)
        except MeetFileError as error:
            stored_path.unlink(missing_ok=True)
            self._send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
            return
        self.server.program_store.save(meet_id, program, file_format, source, original_name, str(stored_path))
        LOGGER.info("Loaded meet file %s for meet %d: %s", original_name, meet_id, program.summary())
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_PROGRAM: self.server.program_store.summary(meet_id)})

    def _handle_activate_meet(self, meet_id: int) -> None:
        """Make a meet active (id 0 clears the active meet)."""
        if not self.server.database.set_active_meet(None if meet_id == constants.NO_MEET_ID else meet_id):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_assign_clips(self, meet_id: int) -> None:
        """File existing clips under a meet: {"clip_ids": [...]} (id 0 = no meet)."""
        payload = self._read_json_object()
        if payload is None:
            return
        clip_ids = payload.get(constants.REQUEST_KEY_CLIP_IDS)
        if not isinstance(clip_ids, list) or not all(isinstance(item, int) for item in clip_ids):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Expected a list of clip ids")
            return
        target = None if meet_id == constants.NO_MEET_ID else meet_id
        if target is not None and self.server.database.get_meet(target) is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such meet")
            return
        count = self.server.database.assign_clips_to_meet(target, clip_ids)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_COUNT: count})

    def _handle_create_dq(self) -> None:
        """Create a DQ (from a detected call or by hand) in the active meet."""
        payload = self._read_json_object()
        if payload is None:
            return
        try:
            dq_id = self.server.dq_store.create_dq(payload, self.server.database.get_active_meet_id())
        except DqError as error:
            self._send_json_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_DQ_ID: dq_id})

    def _handle_update_dq(self, dq_id: int) -> None:
        """Change a DQ's fields or infractions."""
        payload = self._read_json_object()
        if payload is None:
            return
        try:
            found = self.server.dq_store.update_dq(dq_id, payload)
        except DqError as error:
            self._send_json_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        if not found:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such DQ")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_dq_state(self, dq_id: int) -> None:
        """Move a DQ to a new state (recorded in its history)."""
        payload = self._read_json_object()
        if payload is None:
            return
        by_name = payload.get(constants.REQUEST_KEY_BY)
        note = payload.get(constants.REQUEST_KEY_NOTE)
        at = payload.get(constants.REQUEST_KEY_AT)
        try:
            found = self.server.dq_store.change_state(
                dq_id,
                str(payload.get(constants.REQUEST_KEY_STATE)),
                by_name if isinstance(by_name, str) and by_name.strip() else None,
                note.strip() if isinstance(note, str) and note.strip() else None,
                at if isinstance(at, str) and at else None,
            )
        except DqError as error:
            self._send_json_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        if not found:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such DQ")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_dq_from_utterance(self) -> None:
        """Make DQs by hand from a transcript line: {"utterance_id", "text" (selected words, optional)}."""
        payload = self._read_json_object()
        if payload is None:
            return
        utterance_id = payload.get(constants.REQUEST_KEY_UTTERANCE_ID)
        text = payload.get(constants.REQUEST_KEY_TEXT)
        if not isinstance(utterance_id, int):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "utterance_id must be a number")
            return
        dq_ids = self.server.dq_store.create_dq_from_utterance(utterance_id, text if isinstance(text, str) else None)
        if not dq_ids:
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such transcript line")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_DQ_IDS: dq_ids})

    def _handle_dq_trash(self, dq_id: int, trashed: bool) -> None:
        """Move a DQ to the trash or restore it."""
        if not self.server.dq_store.trash_dq(dq_id, trashed):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such DQ, or it is already there")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_rebuild_training_meet(self) -> None:
        """Rebuild the training meet so its times are current (only that meet is touched)."""
        from dq_transcribe.demo_data import create_demo_meet  # local import: demo_data uses this module

        meet_id = create_demo_meet(self.server.database, self.server.recordings_directory, replace=True)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_MEET_ID: meet_id})

    def _handle_auto_dqs_switch(self) -> None:
        """Turn automatic DQs on or off: ``{"enabled": true|false}``."""
        payload = self._read_json_object()
        if payload is None:
            return
        enabled = payload.get(constants.REQUEST_KEY_ENABLED)
        if not isinstance(enabled, bool):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "enabled must be true or false")
            return
        self.server.auto_dqs.set_enabled(enabled)
        self._send_json(HTTPStatus.OK, {constants.REQUEST_KEY_ENABLED: self.server.auto_dqs.enabled})

    def _handle_print_requests(self) -> None:
        """Clear coaches' print requests once printed (or put them back): ``{"dq_ids": [...], "requested": false}``."""
        payload = self._read_json_object()
        if payload is None:
            return
        dq_ids = payload.get(constants.REQUEST_KEY_DQ_IDS)
        requested = payload.get(constants.REQUEST_KEY_REQUESTED)
        if not isinstance(dq_ids, list) or not all(isinstance(item, int) for item in dq_ids) or not isinstance(requested, bool):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Send dq_ids (a list of numbers) and requested (true or false)")
            return
        changed = self.server.dq_store.set_print_requested(dq_ids, requested)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_DQ_IDS: changed})

    def _handle_coach_page_switch(self) -> None:
        """Turn the coach page on or off: ``{"enabled": true|false}``. Replies with its status."""
        payload = self._read_json_object()
        if payload is None:
            return
        enabled = payload.get(constants.REQUEST_KEY_ENABLED)
        if not isinstance(enabled, bool):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "enabled must be true or false")
            return
        self.server.coach_page.set_enabled(enabled)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_COACH_PAGE: self.server.coach_page.status()})

    def _render_coach_sign(self) -> bytes:
        """A printable sign for the coaches' area: the QR code, the address and the password."""
        status = self.server.coach_page.status()
        meet_id = self.server.database.get_active_meet_id()
        meet = self.server.database.get_meet(meet_id) if meet_id is not None else None
        return _render(
            constants.COACH_SIGN_FILENAME,
            {
                "meet_name": html.escape(meet["name"] if meet else ""),
                "url": html.escape(status["urls"][0] if status["urls"] else ""),
                "qr_url": json.dumps(status["qr_urls"][0] if status["qr_urls"] else ""),
                "password": html.escape(status["password"]),
                "qr_script_route": constants.ROUTE_VENDOR + constants.QR_SCRIPT_FILENAME,
            },
        )

    def _send_vendor_script(self, filename: str) -> None:
        """Send a bundled third-party script from web/vendor/ as it is (not a template)."""
        script_path = _WEB_DIRECTORY / constants.VENDOR_DIRECTORY_NAME / filename
        if "/" in filename or filename.startswith(".") or not filename.endswith(".js") or not script_path.is_file():
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such script")
            return
        self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, script_path.read_bytes())

    def _handle_import_officials(self) -> None:
        """Read an officials roster from the Sign-In app: the file as the body, or {"url": ...}.

        Nothing is saved here: the page merges the officials into the meet's roster
        and saves it, so unsaved edits on the page are kept.
        """
        media_type = self.headers.get(constants.CONTENT_TYPE_HEADER, "").split(";")[0].strip().lower()
        if media_type == constants.JSON_CONTENT_TYPE:
            payload = self._read_json_object()
            if payload is None:
                return
            url = str(payload.get(constants.REQUEST_KEY_URL) or constants.OFFICIALS_SIGNIN_ROSTER_URL)
            if not url.lower().startswith(_WEB_ADDRESS_SCHEMES):
                self._send_json_error(HTTPStatus.BAD_REQUEST, "The address must start with http:// or https://")
                return
            try:
                with urllib.request.urlopen(url, timeout=constants.MEET_FILE_DOWNLOAD_TIMEOUT_SECONDS) as response:
                    raw = response.read(constants.MAX_ROSTER_FILE_BYTES + 1)
            except (urllib.error.URLError, OSError, ValueError) as error:
                self._send_json_error(HTTPStatus.BAD_GATEWAY, f"Could not reach the Officials Sign-In app ({error}). Is it running?")
                return
        else:
            raw = self._read_request_body()
            if raw is None:
                return
        if len(raw) > constants.MAX_ROSTER_FILE_BYTES:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "The roster file is too large")
            return
        try:
            roster = read_roster(raw)
        except RosterError as error:
            self._send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
            return
        LOGGER.info("Read an officials roster: %d officials (%s)", len(roster.officials), roster.session)
        self._send_json(HTTPStatus.OK, {
            constants.RESPONSE_KEY_OFFICIALS: roster.officials,
            constants.RESPONSE_KEY_SESSION: roster.session,
            constants.RESPONSE_KEY_WARNINGS: roster.warnings,
        })

    def _handle_notify_event(self) -> None:
        """Notify an event's DQs that are pending notification: {"event", "by", "include_not_ready"}."""
        payload = self._read_json_object()
        if payload is None:
            return
        by_name = payload.get(constants.REQUEST_KEY_BY)
        try:
            notified = self.server.dq_store.notify_event(
                self.server.database.get_active_meet_id(),
                str(payload.get(constants.REQUEST_KEY_EVENT) or ""),
                by_name if isinstance(by_name, str) and by_name.strip() else None,
                bool(payload.get(constants.REQUEST_KEY_INCLUDE_NOT_READY)),
            )
        except DqError as error:
            self._send_json_error(HTTPStatus.CONFLICT, str(error))
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_NOTIFIED: notified})

    def _handle_dismiss_candidate(self) -> None:
        """Hide a detected call."""
        payload = self._read_json_object()
        if payload is None:
            return
        key = payload.get(constants.REQUEST_KEY_CANDIDATE_KEY)
        if not isinstance(key, str) or not key:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Expected a candidate_key")
            return
        self.server.dq_store.dismiss_candidate(key, self.server.database.get_active_meet_id())
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_trash(self, clip_id: int) -> None:
        """Move a clip to the trash bin."""
        if not self.server.database.trash_clip(clip_id):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such clip, or it is already in the trash")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_restore(self, clip_id: int) -> None:
        """Take a clip back out of the trash bin."""
        if not self.server.database.restore_clip(clip_id):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such clip in the trash")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_permanent_delete(self, clip_id: int) -> None:
        """Permanently delete a trashed clip and its audio file (only once its meet is closed)."""
        if self.server.database.clip_meet_is_open(clip_id):
            self._send_json_error(HTTPStatus.CONFLICT, constants.MEET_STILL_OPEN_MESSAGE)
            return
        filename = self.server.database.delete_trashed_clip(clip_id)
        if filename is None:
            self._send_json_error(HTTPStatus.NOT_FOUND, "Only clips in the trash can be deleted")
            return
        audio_path = self._resolve_audio_path(filename)
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)
        LOGGER.info("Permanently deleted clip %d (%s)", clip_id, filename)
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    def _handle_utterance_edit(self, utterance_id: int) -> None:
        """Save edited text for one utterance."""
        body = self._read_request_body()
        if body is None:
            return
        try:
            text = json.loads(body)[constants.REQUEST_KEY_TEXT]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Expected JSON with a text field")
            return
        if not isinstance(text, str) or len(text) > constants.MAX_UTTERANCE_TEXT_CHARS:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Text must be a string of reasonable length")
            return
        if not self.server.database.update_utterance_text(utterance_id, text):
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such utterance")
            return
        self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_OK: True})

    # --- Helpers --------------------------------------------------------------

    @staticmethod
    def _is_mono_16_bit_wav(audio_bytes: bytes) -> bool:
        """Check that bytes are a mono 16-bit PCM WAV file."""
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
                return (
                    wav_file.getnchannels() == constants.AUDIO_CHANNEL_COUNT
                    and wav_file.getsampwidth() == constants.WAV_SAMPLE_WIDTH_BYTES
                )
        except (wave.Error, EOFError):
            return False

    @staticmethod
    def _read_capture_info(header_value: str) -> str | None:
        """Validate the browser's capture-info header; return it if it is reasonable JSON."""
        if not header_value or len(header_value) > constants.MAX_CAPTURE_INFO_CHARS:
            return None
        try:
            json.loads(header_value)
        except json.JSONDecodeError:
            return None
        return header_value

    @staticmethod
    def _read_capture_times(capture_info_json: str | None) -> tuple[str | None, str | None]:
        """Pull the clip's start and end times out of the capture info, if valid.

        Args:
            capture_info_json: Validated capture-info JSON text, or None.

        Returns:
            ``(started_at, ended_at)`` as normalized UTC timestamps; either may be None.
        """
        if capture_info_json is None:
            return None, None
        info = json.loads(capture_info_json)
        if not isinstance(info, dict):
            return None, None
        started = info.get(constants.CAPTURE_INFO_KEY_STARTED_AT)
        ended = info.get(constants.CAPTURE_INFO_KEY_ENDED_AT)
        return (
            normalize_timestamp(started) if isinstance(started, str) else None,
            normalize_timestamp(ended) if isinstance(ended, str) else None,
        )

    def _read_request_body(self) -> bytes | None:
        """Read the request body, or send an error response and return None."""
        try:
            body_length = int(self.headers.get(constants.CONTENT_LENGTH_HEADER, ""))
        except ValueError:
            self._send_json_error(HTTPStatus.LENGTH_REQUIRED, "Content-Length header required")
            return None
        if body_length <= 0:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "Empty request")
            return None
        if body_length > constants.MAX_UPLOAD_BYTES:
            self._send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large")
            return None
        return self.rfile.read(body_length)

    def _send_clip_audio(self, clip_id: int) -> None:
        """Send a clip's WAV file."""
        filename = self.server.database.get_clip_audio_filename(clip_id)
        audio_path = None if filename is None else self._resolve_audio_path(filename)
        if audio_path is None or not audio_path.is_file():
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such clip")
            return
        self._send_bytes(HTTPStatus.OK, constants.WAV_UPLOAD_MEDIA_TYPE, audio_path.read_bytes())

    def _resolve_audio_path(self, filename: str) -> Path | None:
        """Turn a stored audio file name into a path, refusing anything outside the recordings folder."""
        base_directory = self.server.recordings_directory.resolve()
        audio_path = (base_directory / filename).resolve()
        return audio_path if audio_path.is_relative_to(base_directory) else None

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Route request logging through the logging module instead of stderr."""
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        """Send a JSON response."""
        self._send_bytes(status, constants.JSON_CONTENT_TYPE, json.dumps(payload).encode("utf-8"))

    def _send_json_error(self, status: HTTPStatus, message: str) -> None:
        """Send a JSON error response with a human-readable message."""
        self._send_json(status, {constants.RESPONSE_KEY_ERROR: message})

    def _send_bytes(
        self, status: HTTPStatus, content_type: str, body: bytes, download_filename: str | None = None
    ) -> None:
        """Send a complete response.

        Args:
            status: HTTP status.
            content_type: Content-Type header value.
            body: Response body.
            download_filename: If given, ask the browser to save the response under this name.
        """
        self.send_response(status)
        self.send_header(constants.CONTENT_TYPE_HEADER, content_type)
        self.send_header(constants.CONTENT_LENGTH_HEADER, str(len(body)))
        if download_filename is not None:
            self.send_header(constants.CONTENT_DISPOSITION_HEADER, f'attachment; filename="{download_filename}"')
        self.end_headers()
        self.wfile.write(body)
