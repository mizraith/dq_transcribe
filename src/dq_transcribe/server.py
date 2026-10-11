"""Local HTTP server for dq_transcribe.

Serves the web app and its JSON API, accepts audio clips recorded in the
browser (queueing them for transcription), and lets the transcript be edited.
It uses only the Python standard library, so it installs nothing and runs the
same on Termux (Android) and Windows.

The server binds to the loopback address only: it is reachable from this
device and nowhere else on the network.
"""

from __future__ import annotations

import io
import json
import logging
import re
import string
import wave
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dq_transcribe import constants
from dq_transcribe.database import Database
from dq_transcribe.grouping import normalize_timestamp
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
_UTTERANCE_PATTERN = re.compile(rf"^{re.escape(constants.ROUTE_UTTERANCES)}/(\d+)$")


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
        "clippingAmplitude": constants.CLIPPING_AMPLITUDE,
        "clippingWarningSeconds": constants.CLIPPING_WARNING_SECONDS,
        "textKey": constants.REQUEST_KEY_TEXT,
        "audioSuffix": constants.CLIP_AUDIO_SUFFIX,
        "reprocessSuffix": constants.CLIP_REPROCESS_SUFFIX,
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
    ) -> None:
        """Create the server and make sure the recordings directory exists.

        Args:
            server_address: ``(host, port)`` to bind. Use port 0 to let the OS choose.
            recordings_directory: Directory where uploaded audio is saved.
            database: Queue and transcript storage.
            worker: Transcription worker to wake on new clips.
        """
        self.recordings_directory = recordings_directory
        self.recordings_directory.mkdir(parents=True, exist_ok=True)
        self.database = database
        self.worker = worker
        super().__init__(server_address, RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    """Handles page requests, clip uploads, and transcript edits."""

    server: DqTranscribeServer

    # --- GET ----------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (name required by BaseHTTPRequestHandler)
        """Serve pages, scripts, clip data, audio, and downloads."""
        path = urlsplit(self.path).path
        database = self.server.database

        if path == constants.ROUTE_HOME:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_app_page())
        elif path == constants.ROUTE_MIC_TEST:
            self._send_bytes(HTTPStatus.OK, constants.HTML_CONTENT_TYPE, render_mic_test_page())
        elif path == constants.ROUTE_APP_SCRIPT:
            self._send_bytes(HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.APP_SCRIPT_FILENAME))
        elif path == constants.ROUTE_CAPTURE_WORKLET:
            self._send_bytes(
                HTTPStatus.OK, constants.JAVASCRIPT_CONTENT_TYPE, render_script(constants.CAPTURE_WORKLET_FILENAME)
            )
        elif path == constants.ROUTE_CLIPS:
            clips = database.list_clips(limit=constants.CLIP_LIST_LIMIT)
            self._send_json(HTTPStatus.OK, {constants.RESPONSE_KEY_CLIPS: clips})
        elif path == constants.ROUTE_EXPORT:
            body = json.dumps(database.export_all(), indent=2).encode("utf-8")
            self._send_bytes(
                HTTPStatus.OK, constants.JSON_CONTENT_TYPE, body, download_filename=constants.EXPORT_DOWNLOAD_FILENAME
            )
        elif path == constants.ROUTE_TRANSCRIPT_TEXT:
            text = format_transcript_text(database.list_clips(newest_first=False))
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

        clip_path = build_audio_path(
            constants.CLIP_FILENAME_PREFIX, media_type, self.server.recordings_directory
        )
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        clip_path.write_bytes(audio_bytes)
        relative_clip_name = clip_path.relative_to(self.server.recordings_directory).as_posix()
        capture_info_json = self._read_capture_info(self.headers.get(constants.CAPTURE_INFO_HEADER, ""))
        started_at, ended_at = self._read_capture_times(capture_info_json)
        clip_id = self.server.database.add_clip(relative_clip_name, capture_info_json, started_at, ended_at)
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
        base_directory = self.server.recordings_directory.resolve()
        audio_path = None if filename is None else (base_directory / filename).resolve()
        if audio_path is None or not audio_path.is_relative_to(base_directory) or not audio_path.is_file():
            self._send_json_error(HTTPStatus.NOT_FOUND, "No such clip")
            return
        self._send_bytes(HTTPStatus.OK, constants.WAV_UPLOAD_MEDIA_TYPE, audio_path.read_bytes())

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
